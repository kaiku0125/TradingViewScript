#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


Trade = Dict[str, Any]
SheetRows = Dict[str, List[List[Any]]]

DEFAULT_INPUT = Path("generated/trade_rows.json")
DEFAULT_JSON_OUTPUT = Path("generated/trades.json")
DEFAULT_CSV_OUTPUT = Path("generated/trades.csv")

TAB_MAPPINGS = [
    {
        "tab": "006208",
        "symbol": "006208",
        "market": "TW",
        "side": "BUY",
        "start_row": 3,
        "stop_on_empty_qty": True,
        "columns": {
            "date": "A",
            "qty": "B",
            "amount": "C",
            "price": "D",
        },
    },
    {
        "tab": "006208",
        "symbol": "006208",
        "market": "TW",
        "side": "SELL",
        "start_row": 3,
        "stop_on_empty_qty": True,
        "columns": {
            "date": "K",
            "qty": "H",
            "amount": "I",
            "price": "J",
        },
    },
    {
        "tab": "BTC",
        "symbol": "BTC",
        "market": "CRYPTO",
        "side": "BUY",
        "start_row": 3,
        "stop_on_empty_qty": True,
        "columns": {
            "date": "A",
            "qty": "D",
            "amount": "B",
            "price": "C",
        },
    },
    {
        "tab": "BTC",
        "symbol": "BTC",
        "market": "CRYPTO",
        "side": "SELL",
        "start_row": 3,
        "stop_on_empty_qty": True,
        "columns": {
            "date": "K",
            "qty": "J",
            "amount": "H",
            "price": "I",
        },
    },
]


def col_to_index(col: str) -> int:
    result = 0
    for ch in col:
        result = result * 26 + (ord(ch.upper()) - ord("A") + 1)
    return result - 1


def normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    return value


def get_cell(row: List[Any], col: Any) -> Any:
    if not col:
        return ""
    idx = col_to_index(col)
    if idx >= len(row):
        return ""
    return normalize_cell(row[idx])


def is_empty_like(value: Any) -> bool:
    return value in ("", "--", None)


def is_fully_empty_trade(trade: Trade) -> bool:
    return (
        is_empty_like(trade["date"])
        and is_empty_like(trade["qty"])
        and is_empty_like(trade["amount"])
        and is_empty_like(trade["price"])
    )


def build_trades(sheet_rows_by_tab: SheetRows) -> List[Trade]:
    trades: List[Trade] = []

    for mapping in TAB_MAPPINGS:
        rows = sheet_rows_by_tab.get(mapping["tab"], [])
        for row_index in range(mapping["start_row"] - 1, len(rows)):
            row = rows[row_index]
            qty = get_cell(row, mapping["columns"]["qty"])

            if mapping.get("stop_on_empty_qty") and is_empty_like(qty):
                break

            trade = {
                "symbol": mapping["symbol"],
                "market": mapping["market"],
                "side": mapping["side"],
                "date": get_cell(row, mapping["columns"]["date"]),
                "qty": qty,
                "amount": get_cell(row, mapping["columns"]["amount"]),
                "price": get_cell(row, mapping["columns"]["price"]),
            }

            if is_fully_empty_trade(trade):
                continue

            trades.append(trade)

    return trades


def normalize_snapshot_payload(payload: Dict[str, Any]) -> Tuple[SheetRows, Dict[str, Any]]:
    if "tabs" in payload and isinstance(payload["tabs"], dict):
        metadata = {
            "fetched_at": payload.get("fetched_at", ""),
            "spreadsheet_url": payload.get("spreadsheet_url", ""),
        }
        return payload["tabs"], metadata

    return payload, {}


def write_json(trades: List[Trade], output_path: Path) -> None:
    output_path.write_text(
        json.dumps(trades, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(trades: List[Trade], output_path: Path) -> None:
    fieldnames = ["symbol", "market", "side", "date", "qty", "amount", "price"]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert sheet row snapshots into standardized trades without any calculations."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--csv-output", default=str(DEFAULT_CSV_OUTPUT))
    args = parser.parse_args()

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    sheet_rows_by_tab, metadata = normalize_snapshot_payload(payload)
    trades = build_trades(sheet_rows_by_tab)

    write_json(trades, Path(args.json_output))
    write_csv(trades, Path(args.csv_output))

    print(f"Input: {input_path}")
    if metadata.get("fetched_at"):
        print(f"Snapshot fetched_at: {metadata['fetched_at']}")
    print(f"Trades generated: {len(trades)}")
    print(f"JSON output: {args.json_output}")
    print(f"CSV output: {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
