#!/usr/bin/env python3

import argparse
import subprocess
import sys
import json
from pathlib import Path


DEFAULT_INPUT = Path("generated/trade_rows.json")
DEFAULT_JSON_OUTPUT = Path("generated/trades.json")
DEFAULT_CSV_OUTPUT = Path("generated/trades.csv")
CONVERTER = Path("trade_history/convert_sheet_rows_to_trades.py")
PINE_GENERATOR = Path("trade_history/generate_trade_history_pine.py")


def invalid_snapshot(reason: str) -> str:
    return f"Invalid trade snapshot: {reason}"


def validate_snapshot_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError(invalid_snapshot("payload must be an object"))

    fetched_at = payload.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        raise ValueError(invalid_snapshot("missing fetched_at"))

    tabs = payload.get("tabs")
    if not isinstance(tabs, dict) or not tabs:
        raise ValueError(invalid_snapshot("tabs must be a non-empty object"))

    spreadsheet_url = payload.get("spreadsheet_url")
    if spreadsheet_url is not None and not isinstance(spreadsheet_url, str):
        raise ValueError(invalid_snapshot("spreadsheet_url must be a string when present"))

    for tab_name, rows in tabs.items():
        if not isinstance(rows, list):
            raise ValueError(invalid_snapshot(f"tab '{tab_name}' must contain a list of rows"))
        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                raise ValueError(invalid_snapshot(f"tab '{tab_name}' row {row_index} must be a list"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update standardized trade history artifacts from local sheet row snapshots."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--csv-output", default=str(DEFAULT_CSV_OUTPUT))
    parser.add_argument("--pine-file", default="trade_history/TradeHistoryLabels.pine")
    parser.add_argument("--skip-refresh-check", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Missing snapshot file: {input_path}")

    if not args.skip_refresh_check:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        try:
            validate_snapshot_payload(payload)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    command = [
        sys.executable,
        str(CONVERTER),
        "--input",
        str(input_path),
        "--json-output",
        args.json_output,
        "--csv-output",
        args.csv_output,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return int(result.returncode)

    pine_command = [
        sys.executable,
        str(PINE_GENERATOR),
        "--trades-input",
        args.json_output,
        "--pine-file",
        args.pine_file,
    ]
    pine_result = subprocess.run(pine_command, check=False)
    return int(pine_result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
