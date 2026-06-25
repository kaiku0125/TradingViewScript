#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_TRADES_INPUT = Path("generated/trades.json")
DEFAULT_PINE_FILE = Path("trade_history/TradeHistoryLabels.pine")
BLOCK_START = "    // === AUTO-GENERATED TRADES START ==="
BLOCK_END = "    // === AUTO-GENERATED TRADES END ==="


def replace_named_block(content: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = content.find(start_marker)
    end = content.find(end_marker)

    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Could not find block markers: {start_marker} / {end_marker}")

    end += len(end_marker)
    return content[:start] + replacement.rstrip("\n") + content[end:]


def parse_date_parts(value: Any) -> Tuple[int, int, int]:
    if value is None:
        return 0, 0, 0

    text = str(value).strip()
    if not text:
        return 0, 0, 0

    parts = text.split("/")
    if len(parts) != 3:
        return 0, 0, 0

    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return 0, 0, 0


def normalize_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    # Pine numeric args cannot contain localized commas like "82,89".
    text = text.replace(",", ".")
    return float(text)


def escape_pine_string(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_generated_block(trades: List[Dict[str, Any]]) -> str:
    lines = [
        BLOCK_START,
        "    // generated from generated/trades.json",
    ]

    for trade in trades:
        year, month, day = parse_date_parts(trade.get("date"))
        qty = normalize_number(trade.get("qty"))
        amount = normalize_number(trade.get("amount"))
        price = escape_pine_string(trade.get("price", ""))
        symbol = escape_pine_string(trade.get("symbol", ""))
        market = escape_pine_string(trade.get("market", ""))
        side = escape_pine_string(trade.get("side", ""))
        lines.append(
            f'    add_trade("{symbol}", "{market}", "{side}", {year}, {month}, {day}, {qty}, {amount}, "{price}")'
        )

    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TradeHistoryLabels.pine auto-generated trade block.")
    parser.add_argument("--trades-input", default=str(DEFAULT_TRADES_INPUT))
    parser.add_argument("--pine-file", default=str(DEFAULT_PINE_FILE))
    args = parser.parse_args()

    trades = json.loads(Path(args.trades_input).read_text(encoding="utf-8"))
    pine_path = Path(args.pine_file)
    original = pine_path.read_text(encoding="utf-8")
    generated_block = build_generated_block(trades)
    updated = replace_named_block(original, BLOCK_START, BLOCK_END, generated_block)
    pine_path.write_text(updated, encoding="utf-8")

    print(f"Trades input: {args.trades_input}")
    print(f"Pine file updated: {args.pine_file}")
    print(f"Trades written: {len(trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
