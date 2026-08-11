"""Append-only JSONL storage with a shared local file lock."""

from __future__ import annotations

import errno
import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import RuntimeConfig
from .errors import JournalValidationError, LockUnavailableError


DATASET_FILENAMES = {
    "market_snapshots": "market_snapshots.jsonl",
    "decisions": "decisions.jsonl",
    "executions": "executions.jsonl",
    "weekly_targets": "weekly_targets.jsonl",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class JournalPaths:
    data_dir: Path
    lock_file: Path
    datasets: dict[str, Path]


class JournalStore:
    def __init__(self, config: RuntimeConfig):
        data_dir = config.data_dir
        self.paths = JournalPaths(
            data_dir=data_dir,
            lock_file=data_dir / config.lock_filename,
            datasets={
                name: data_dir / filename
                for name, filename in DATASET_FILENAMES.items()
            },
        )

    @contextmanager
    def lock(self, *, exclusive: bool) -> Iterator[None]:
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.paths.lock_file,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise LockUnavailableError(
                        "canonical Journal is locked by another process"
                    ) from exc
                raise
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def read_dataset(self, dataset: str) -> list[dict]:
        path = self.paths.datasets[dataset]
        if not path.exists():
            return []
        records: list[dict] = []
        issues: list[str] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    if not raw_line.endswith("\n"):
                        issues.append(f"{path.name}:{line_number}: incomplete JSONL line")
                        continue
                    line = raw_line[:-1]
                    if not line:
                        issues.append(f"{path.name}:{line_number}: blank JSONL line")
                        continue
                    try:
                        record = json.loads(
                            line,
                            object_pairs_hook=_reject_duplicate_keys,
                        )
                    except (json.JSONDecodeError, ValueError) as exc:
                        issues.append(f"{path.name}:{line_number}: invalid JSON: {exc}")
                        continue
                    if not isinstance(record, dict):
                        issues.append(f"{path.name}:{line_number}: record must be an object")
                        continue
                    records.append(record)
        except UnicodeDecodeError as exc:
            issues.append(f"{path.name}: invalid UTF-8: {exc}")
        if issues:
            raise JournalValidationError(issues)
        return records

    def read_all(self) -> dict[str, list[dict]]:
        return {name: self.read_dataset(name) for name in DATASET_FILENAMES}

    def append_records(self, dataset: str, records: list[dict]) -> None:
        if not records:
            return
        path = self.paths.datasets[dataset]
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        payload = "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for record in records
        ).encode("utf-8")
        descriptor = os.open(
            path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("JSONL append made no forward progress")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
