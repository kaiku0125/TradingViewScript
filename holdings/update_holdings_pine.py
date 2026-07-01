#!/usr/bin/env python3

import argparse
import ast
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_URL = "https://script.google.com/macros/s/AKfycbyZlf8tv1b8fgyFeUyj913rVpC1e4QlQ_uiuRx-3phGklHA3HT0t0_Cqg3JVchvVKJr7A/exec"
DEFAULT_OUTPUT = Path("generated/holdings.pine")
DEFAULT_PNL_FILE = Path("PNLRebalance")
HOLDINGS_BLOCK_START = "// === AUTO-GENERATED START ==="
HOLDINGS_BLOCK_END = "// === AUTO-GENERATED END ==="
USD_BLOCK_START = "// === AUTO-GENERATED USD START ==="
USD_BLOCK_END = "// === AUTO-GENERATED USD END ==="
CASH_LIABILITY_BLOCK_START = "// === AUTO-GENERATED CASH LIABILITY START ==="
CASH_LIABILITY_BLOCK_END = "// === AUTO-GENERATED CASH LIABILITY END ==="
USD_EXCHANGE_MAP = {
    "bybit": "BYBIT_EXCHANGE_USD",
    "binance": "BINANCE_EXCHANGE_USD",
    "crypto_com": "CRYPTO_DOT_COM_EXCHANGE_USD",
    "okx": "OKX_EXCHANGE_USD",
    "pionex": "PIONEX_EXCHANGE_USD",
    "kraken": "KRAKEN_EXCHANGE_USD",
}
CASH_LIABILITY_VARIABLES = {
    "BANK1_AVAL": "BANK1_AVAL",
    "BANK2_AVAL": "BANK2_AVAL",
    "BANK3_AVAL": "BANK3_AVAL",
    "BANK4_AVAL": "BANK4_AVAL",
    "BITO_AVAL": "BITO_AVAL",
    "VISA_AVAL": "VISA_AVAL",
}


def fetch_holdings(base_url: str, token: str) -> dict:
    query = urlencode({"token": token})
    url = f"{base_url}?{query}"

    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_holdings_pine(payload: dict) -> str:
    holdings = payload.get("holdings", [])
    if not holdings:
        raise ValueError("No holdings found in payload")

    symbols = ", ".join(f'"{item["symbol"]}"' for item in holdings)
    buy_qtys = ", ".join(format_number(item["buy_qty"]) for item in holdings)
    buy_costs = ", ".join(format_number(item["buy_cost"]) for item in holdings)
    sell_qtys = ", ".join(format_number(item["sell_qty"]) for item in holdings)
    sell_incomes = ", ".join(format_number(item["sell_income"]) for item in holdings)

    lines = [
        HOLDINGS_BLOCK_START,
        f"// updated_at: {payload.get('updated_at', 'unknown')}",
        f"var string[] symbols = array.from({symbols})",
        f"var float[] buyQtys = array.from({buy_qtys})",
        f"var float[] buyCosts = array.from({buy_costs})",
        f"var float[] sellQtys = array.from({sell_qtys})",
        f"var float[] sellIncomes = array.from({sell_incomes})",
        HOLDINGS_BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def build_usd_snapshot(payload: dict) -> Dict[str, float]:
    balances = {exchange: 0.0 for exchange in USD_EXCHANGE_MAP}
    for item in payload.get("usd_balances", []):
        exchange = str(item.get("exchange", "")).strip().lower()
        if exchange in balances:
            balances[exchange] = float(item.get("usd_balance", 0))
    return balances


def build_usd_pine(payload: dict) -> str:
    balances = build_usd_snapshot(payload)
    lines = [
        USD_BLOCK_START,
        f"// updated_at: {payload.get('updated_at', 'unknown')}",
        f"var float BYBIT_EXCHANGE_USD = {format_number(balances['bybit'])}",
        f"var float BINANCE_EXCHANGE_USD = {format_number(balances['binance'])}",
        f"var float CRYPTO_DOT_COM_EXCHANGE_USD = {format_number(balances['crypto_com'])}",
        f"var float OKX_EXCHANGE_USD = {format_number(balances['okx'])}",
        f"var float PIONEX_EXCHANGE_USD = {format_number(balances['pionex'])}",
        f"var float KRAKEN_EXCHANGE_USD = {format_number(balances['kraken'])}",
        "var float EXCHANGE_USD =",
        "      BYBIT_EXCHANGE_USD +",
        "      BINANCE_EXCHANGE_USD +",
        "      CRYPTO_DOT_COM_EXCHANGE_USD +",
        "      OKX_EXCHANGE_USD +",
        "      PIONEX_EXCHANGE_USD +",
        "      KRAKEN_EXCHANGE_USD",
        USD_BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def build_cash_liability_snapshot(payload: dict) -> Dict[str, float]:
    snapshot = {key: 0.0 for key in CASH_LIABILITY_VARIABLES}
    debt_total = 0.0

    for item in payload.get("cash_liability", []):
        key = str(item.get("key", "")).strip().upper()
        value = float(item.get("value", 0))

        if key in snapshot:
            snapshot[key] = value

        if key.startswith("DEBT"):
            debt_total += value

    snapshot["DEBT"] = debt_total
    return snapshot


def build_cash_liability_pine(payload: dict) -> str:
    snapshot = build_cash_liability_snapshot(payload)
    lines = [
        CASH_LIABILITY_BLOCK_START,
        f"// updated_at: {payload.get('updated_at', 'unknown')}",
        f"var float BANK1_AVAL = {format_number(snapshot['BANK1_AVAL'])}  // LineBank (TWD)",
        f"var float BANK2_AVAL = {format_number(snapshot['BANK2_AVAL'])}  // Bankee (TWD)",
        f"var float BANK3_AVAL = {format_number(snapshot['BANK3_AVAL'])}  // 台新 (TWD)",
        f"var float BANK4_AVAL = {format_number(snapshot['BANK4_AVAL'])}  // 樂天 (TWD)",
        f"var float BITO_AVAL = {format_number(snapshot['BITO_AVAL'])}  // 幣託 (USD)",
        f"var float VISA_AVAL = {format_number(snapshot['VISA_AVAL'])}  // Visa (USD) 出金",
        f"var float DEBT = {format_number(snapshot['DEBT'])}  // 負債(TWD)",
        CASH_LIABILITY_BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def build_output_content(holdings_block: str, usd_block: str, cash_liability_block: str) -> str:
    return (
        holdings_block.rstrip("\n")
        + "\n\n"
        + usd_block.rstrip("\n")
        + "\n\n"
        + cash_liability_block
    )


def replace_named_block(content: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = content.find(start_marker)
    end = content.find(end_marker)

    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Could not find block markers: {start_marker} / {end_marker}")

    end += len(end_marker)
    return content[:start] + replacement.rstrip("\n") + content[end:]


def update_pnl_file(
    target_path: Path, holdings_block: str, usd_block: str, cash_liability_block: str
) -> None:
    original = target_path.read_text(encoding="utf-8")
    updated = replace_named_block(original, HOLDINGS_BLOCK_START, HOLDINGS_BLOCK_END, holdings_block)
    updated = replace_named_block(updated, USD_BLOCK_START, USD_BLOCK_END, usd_block)
    updated = replace_named_block(
        updated,
        CASH_LIABILITY_BLOCK_START,
        CASH_LIABILITY_BLOCK_END,
        cash_liability_block,
    )
    target_path.write_text(updated, encoding="utf-8")


def parse_array_values(content: str, var_name: str) -> list:
    pattern = rf"var\s+\w+\[\]\s+{re.escape(var_name)}\s*=\s*array\.from\((.*?)\)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find array values for {var_name}")

    raw_values = match.group(1).strip()
    if not raw_values:
        return []

    return ast.literal_eval("[" + raw_values + "]")


def parse_existing_holdings(content: str) -> List[Dict]:
    symbols = parse_array_values(content, "symbols")
    buy_qtys = parse_array_values(content, "buyQtys")
    buy_costs = parse_array_values(content, "buyCosts")
    sell_qtys = parse_array_values(content, "sellQtys")
    sell_incomes = parse_array_values(content, "sellIncomes")

    lengths = {len(symbols), len(buy_qtys), len(buy_costs), len(sell_qtys), len(sell_incomes)}
    if len(lengths) != 1:
        raise ValueError("Existing holdings arrays have inconsistent lengths")

    holdings = []
    for index, symbol in enumerate(symbols):
        holdings.append(
            {
                "symbol": str(symbol),
                "buy_qty": float(buy_qtys[index]),
                "buy_cost": float(buy_costs[index]),
                "sell_qty": float(sell_qtys[index]),
                "sell_income": float(sell_incomes[index]),
            }
        )
    return holdings


def load_existing_holdings(path: Path) -> Optional[List[Dict]]:
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    try:
        return parse_existing_holdings(content)
    except ValueError:
        return None


def parse_existing_usd(content: str) -> Dict[str, float]:
    if USD_BLOCK_START not in content or USD_BLOCK_END not in content:
        raise ValueError("Could not find usd auto-generated block")

    balances = {exchange: 0.0 for exchange in USD_EXCHANGE_MAP}
    for exchange, variable_name in USD_EXCHANGE_MAP.items():
        pattern = rf"var\s+float\s+{re.escape(variable_name)}\s*=\s*(-?\d+(?:\.\d+)?)"
        match = re.search(pattern, content)
        if match:
            balances[exchange] = float(match.group(1))
    return balances


def load_existing_usd(path: Path) -> Optional[Dict[str, float]]:
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    try:
        return parse_existing_usd(content)
    except ValueError:
        return None


def parse_existing_cash_liability(content: str) -> Dict[str, float]:
    if CASH_LIABILITY_BLOCK_START not in content or CASH_LIABILITY_BLOCK_END not in content:
        raise ValueError("Could not find cash liability auto-generated block")

    values = {key: 0.0 for key in CASH_LIABILITY_VARIABLES}
    values["DEBT"] = 0.0
    for variable_name in list(CASH_LIABILITY_VARIABLES.values()) + ["DEBT"]:
        pattern = rf"var\s+float\s+{re.escape(variable_name)}\s*=\s*(-?\d+(?:\.\d+)?)"
        match = re.search(pattern, content)
        if match:
            values[variable_name] = float(match.group(1))
    return values


def load_existing_cash_liability(path: Path) -> Optional[Dict[str, float]]:
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    try:
        return parse_existing_cash_liability(content)
    except ValueError:
        return None


def summarize_holdings_changes(previous: Optional[List[Dict]], current: List[Dict]) -> List[str]:
    if previous is None:
        return ["No previous holdings snapshot found; treated as initial sync."]

    previous_map = {item["symbol"]: item for item in previous}
    current_map = {item["symbol"]: item for item in current}
    summary = []

    for symbol in sorted(set(previous_map) | set(current_map)):
        before = previous_map.get(symbol)
        after = current_map.get(symbol)

        if before is None:
            summary.append(f"{symbol}: added")
            continue

        if after is None:
            summary.append(f"{symbol}: removed")
            continue

        field_changes = []
        for field in ("buy_qty", "buy_cost", "sell_qty", "sell_income"):
            before_value = before[field]
            after_value = after[field]
            if before_value != after_value:
                field_changes.append(
                    f"{field} {format_number(before_value)} -> {format_number(after_value)}"
                )

        if field_changes:
            summary.append(f"{symbol}: " + ", ".join(field_changes))

    if not summary:
        return ["No holdings values changed; only metadata such as updated_at may have changed."]

    return summary


def summarize_usd_changes(previous: Optional[Dict[str, float]], current: Dict[str, float]) -> List[str]:
    if previous is None:
        return ["No previous usd snapshot found; treated as initial sync."]

    summary = []
    for exchange in sorted(current):
        before_value = float(previous.get(exchange, 0))
        after_value = float(current.get(exchange, 0))
        if before_value != after_value:
            summary.append(f"{exchange}: {format_number(before_value)} -> {format_number(after_value)}")

    if not summary:
        return ["No usd values changed; only metadata such as updated_at may have changed."]

    return summary


def summarize_cash_liability_changes(
    previous: Optional[Dict[str, float]], current: Dict[str, float]
) -> List[str]:
    if previous is None:
        return ["No previous cash/liability snapshot found; treated as initial sync."]

    summary = []
    for key in list(CASH_LIABILITY_VARIABLES.values()) + ["DEBT"]:
        before_value = float(previous.get(key, 0))
        after_value = float(current.get(key, 0))
        if before_value != after_value:
            summary.append(f"{key}: {format_number(before_value)} -> {format_number(after_value)}")

    if not summary:
        return ["No cash/liability values changed; only metadata such as updated_at may have changed."]

    return summary


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

    output_path = Path(args.output)
    pnl_path = Path(args.pnl_file)
    previous_holdings = load_existing_holdings(output_path)
    previous_usd = load_existing_usd(output_path)
    previous_cash_liability = load_existing_cash_liability(output_path)
    current_holdings = payload.get("holdings", [])
    current_usd = build_usd_snapshot(payload)
    current_cash_liability = build_cash_liability_snapshot(payload)
    holdings_block = build_holdings_pine(payload)
    usd_block = build_usd_pine(payload)
    cash_liability_block = build_cash_liability_pine(payload)
    output_content = build_output_content(holdings_block, usd_block, cash_liability_block)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content, encoding="utf-8")
    if not args.skip_pnl_update:
        update_pnl_file(pnl_path, holdings_block, usd_block, cash_liability_block)
        print(f"Updated {output_path} and {pnl_path}")
    else:
        print(f"Updated {output_path}")

    print("Holdings summary:")
    for line in summarize_holdings_changes(previous_holdings, current_holdings):
        print(f"- {line}")

    print("USD summary:")
    for line in summarize_usd_changes(previous_usd, current_usd):
        print(f"- {line}")

    print("Cash/Liability summary:")
    for line in summarize_cash_liability_changes(previous_cash_liability, current_cash_liability):
        print(f"- {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
