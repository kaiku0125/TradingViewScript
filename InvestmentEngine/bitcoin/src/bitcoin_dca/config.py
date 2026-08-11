"""Versioned machine configuration loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "config.1.0-draft.2.json"
)


@dataclass(frozen=True)
class RuntimeConfig:
    config_path: Path
    raw: dict
    config_version: str
    initial_budget: Decimal
    start_date: date
    end_date: date
    timezone: ZoneInfo
    cutoff_time: time
    recommendation_window_end: time
    data_dir: Path
    reports_dir: Path
    templates_dir: Path
    lock_filename: str


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise ConfigError(f"{field} must be finite")
    return parsed


def _parse_time(value: object, field: str) -> time:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be HH:MM")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{field} must be HH:MM") from exc


def _resolve_dir(config_path: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty path string")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def load_config(config_path: Path | str | None = None) -> RuntimeConfig:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    path = path.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid config JSON at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config root must be an object")
    if raw.get("schema_version") != "bitcoin_dca_config.v1":
        raise ConfigError("unsupported config schema_version")
    version = raw.get("config_version")
    if not isinstance(version, str) or not version:
        raise ConfigError("config_version must be a non-empty string")

    plan = raw.get("plan")
    runtime = raw.get("runtime")
    if not isinstance(plan, dict) or not isinstance(runtime, dict):
        raise ConfigError("plan and runtime must be objects")

    try:
        start_date = date.fromisoformat(plan["start_date"])
        end_date = date.fromisoformat(plan["end_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("plan start_date/end_date must be ISO dates") from exc
    if start_date > end_date:
        raise ConfigError("plan start_date must not exceed end_date")
    if (end_date - start_date).days + 1 != 65:
        raise ConfigError("approved plan must contain exactly 65 calendar days")

    try:
        timezone = ZoneInfo(plan["timezone"])
    except (KeyError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ConfigError("plan.timezone must be a valid IANA timezone") from exc

    initial_budget = _decimal(plan.get("initial_budget"), "plan.initial_budget")
    if initial_budget <= 0:
        raise ConfigError("plan.initial_budget must be positive")
    if plan.get("currency") != "USD" or plan.get("asset") != "BTC":
        raise ConfigError("approved MVP supports only BTC funded in USD")

    cutoff_time = _parse_time(plan.get("data_cutoff_time"), "plan.data_cutoff_time")
    window_end = _parse_time(
        plan.get("recommendation_window_end"),
        "plan.recommendation_window_end",
    )
    if window_end <= cutoff_time:
        raise ConfigError("recommendation window must end after cutoff")

    lock_filename = runtime.get("lock_filename")
    if not isinstance(lock_filename, str) or not lock_filename.endswith(".lock"):
        raise ConfigError("runtime.lock_filename must end in .lock")

    return RuntimeConfig(
        config_path=path,
        raw=raw,
        config_version=version,
        initial_budget=initial_budget,
        start_date=start_date,
        end_date=end_date,
        timezone=timezone,
        cutoff_time=cutoff_time,
        recommendation_window_end=window_end,
        data_dir=_resolve_dir(path, runtime.get("data_dir"), "runtime.data_dir"),
        reports_dir=_resolve_dir(
            path, runtime.get("reports_dir"), "runtime.reports_dir"
        ),
        templates_dir=_resolve_dir(
            path, runtime.get("templates_dir"), "runtime.templates_dir"
        ),
        lock_filename=lock_filename,
    )

