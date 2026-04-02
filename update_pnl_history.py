#!/usr/bin/env python3

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo


DEFAULT_PNL_FILE = Path("PNLRebalance")
HISTORY_BLOCK_START = "    if array.size(rdArray) == 0"
PUSH_LINE_PATTERN = re.compile(
    r"^(?P<indent>\s*)array\.push\(rdArray, newData\((?P<year>-?\d+), (?P<month>-?\d+), (?P<day>-?\d+), (?P<value>-?\d+(?:\.\d+)?)\)\)(?P<comment>.*)$"
)


@dataclass
class HistoryEntry:
    year: int
    month: int
    day: int
    value_text: str
    indent: str
    comment: str
    line_index: int

    def same_date(self, year: int, month: int, day: int) -> bool:
        return self.year == year and self.month == month and self.day == day

    def render(self, value_text: str) -> str:
        return (
            f"{self.indent}array.push(rdArray, newData({self.year}, {self.month}, {self.day}, {value_text}))"
            f"{self.comment}"
        )


def format_pnl_value(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def get_default_date() -> tuple[int, int, int]:
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    return now.year, now.month, now.day


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update rdArray history in PNLRebalance.")
    parser.add_argument("--pnl-value", required=True, type=float)
    parser.add_argument("--pnl-file", default=str(DEFAULT_PNL_FILE))
    parser.add_argument("--date", help="Optional date in YYYY-MM-DD format")
    return parser.parse_args()


def resolve_date(date_arg: Optional[str]) -> tuple[int, int, int]:
    if not date_arg:
        return get_default_date()

    parsed = datetime.strptime(date_arg, "%Y-%m-%d")
    return parsed.year, parsed.month, parsed.day


def find_history_block(lines: List[str]) -> tuple[int, int]:
    start_index = -1
    for index, line in enumerate(lines):
        if line == HISTORY_BLOCK_START:
            start_index = index
            break

    if start_index == -1:
        raise ValueError("Could not find rdArray history block start")

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith("        "):
            end_index = index
            break

    return start_index, end_index


def parse_history_entries(lines: List[str], start_index: int, end_index: int) -> List[HistoryEntry]:
    entries: List[HistoryEntry] = []
    for index in range(start_index + 1, end_index):
        match = PUSH_LINE_PATTERN.match(lines[index])
        if not match:
            continue

        entries.append(
            HistoryEntry(
                year=int(match.group("year")),
                month=int(match.group("month")),
                day=int(match.group("day")),
                value_text=match.group("value"),
                indent=match.group("indent"),
                comment=match.group("comment"),
                line_index=index,
            )
        )

    if not entries:
        raise ValueError("Could not find any rdArray history entries")

    return entries


def update_history_content(content: str, pnl_value: float, year: int, month: int, day: int) -> tuple[str, str]:
    lines = content.splitlines()
    start_index, end_index = find_history_block(lines)
    entries = parse_history_entries(lines, start_index, end_index)
    pnl_text = format_pnl_value(pnl_value)

    for entry in entries:
        if entry.same_date(year, month, day):
            old_value = entry.value_text
            lines[entry.line_index] = entry.render(pnl_text)
            summary = f"updated {year}-{month}-{day}: {old_value} -> {pnl_text}"
            return "\n".join(lines) + "\n", summary

    template = entries[-1]
    insertion_index = entries[-1].line_index + 1
    new_line = (
        f"{template.indent}array.push(rdArray, newData({year}, {month}, {day}, {pnl_text}))"
    )
    lines.insert(insertion_index, new_line)
    summary = f"added {year}-{month}-{day}: {pnl_text}"
    return "\n".join(lines) + "\n", summary


def main() -> int:
    args = parse_args()
    year, month, day = resolve_date(args.date)
    pnl_path = Path(args.pnl_file)
    content = pnl_path.read_text(encoding="utf-8")
    updated_content, summary = update_history_content(content, args.pnl_value, year, month, day)
    pnl_path.write_text(updated_content, encoding="utf-8")
    print(f"Updated {pnl_path}")
    print("Summary:")
    print(f"- {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
