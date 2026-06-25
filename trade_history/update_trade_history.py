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
        if "fetched_at" not in payload:
            raise SystemExit(
                "Snapshot is missing fetched_at metadata. Refresh generated/trade_rows.json from Google Sheet before running."
            )

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
