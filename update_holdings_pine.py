#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_URL = "https://script.google.com/macros/s/AKfycbyZlf8tv1b8fgyFeUyj913rVpC1e4QlQ_uiuRx-3phGklHA3HT0t0_Cqg3JVchvVKJr7A/exec"
DEFAULT_OUTPUT = Path("generated/holdings.pine")
DEFAULT_PNL_FILE = Path("PNLRebalance")
AUTO_GENERATED_START = "// === AUTO-GENERATED START ==="
AUTO_GENERATED_END = "// === AUTO-GENERATED END ==="


def fetch_holdings(base_url: str, token: str) -> dict:
    query = urlencode({"token": token})
    url = f"{base_url}?{query}"

    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_pine(payload: dict) -> str:
    holdings = payload.get("holdings", [])
    if not holdings:
        raise ValueError("No holdings found in payload")

    symbols = ", ".join(f'"{item["symbol"]}"' for item in holdings)
    buy_qtys = ", ".join(format_number(item["buy_qty"]) for item in holdings)
    buy_costs = ", ".join(format_number(item["buy_cost"]) for item in holdings)
    sell_qtys = ", ".join(format_number(item["sell_qty"]) for item in holdings)
    sell_incomes = ", ".join(format_number(item["sell_income"]) for item in holdings)

    lines = [
        "// === AUTO-GENERATED START ===",
        f"// updated_at: {payload.get('updated_at', 'unknown')}",
        f"var string[] symbols = array.from({symbols})",
        f"var float[] buyQtys = array.from({buy_qtys})",
        f"var float[] buyCosts = array.from({buy_costs})",
        f"var float[] sellQtys = array.from({sell_qtys})",
        f"var float[] sellIncomes = array.from({sell_incomes})",
        "// === AUTO-GENERATED END ===",
    ]
    return "\n".join(lines) + "\n"


def replace_auto_generated_block(content: str, pine_block: str) -> str:
    start = content.find(AUTO_GENERATED_START)
    end = content.find(AUTO_GENERATED_END)

    if start == -1 or end == -1 or end < start:
        raise ValueError("Could not find AUTO-GENERATED block in target Pine file")

    end += len(AUTO_GENERATED_END)
    return content[:start] + pine_block.rstrip("\n") + content[end:]


def update_pnl_file(target_path: Path, pine_block: str) -> None:
    original = target_path.read_text(encoding="utf-8")
    updated = replace_auto_generated_block(original, pine_block)
    target_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch holdings JSON and generate Pine Script arrays.")
    parser.add_argument("--url", default=os.environ.get("HOLDINGS_WEB_APP_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("HOLDINGS_WEB_APP_TOKEN"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--pnl-file", default=str(DEFAULT_PNL_FILE))
    parser.add_argument("--skip-pnl-update", action="store_true")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("Missing token. Pass --token or set HOLDINGS_WEB_APP_TOKEN.")

    payload = fetch_holdings(args.url, args.token)
    if payload.get("error"):
        raise SystemExit(f"Web app error: {payload['error']}")

    pine = build_pine(payload)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(pine, encoding="utf-8")

    if not args.skip_pnl_update:
        pnl_path = Path(args.pnl_file)
        update_pnl_file(pnl_path, pine)
        print(f"Updated {output_path} and {pnl_path}")
    else:
        print(f"Updated {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
