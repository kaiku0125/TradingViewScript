#!/usr/bin/env python3

import argparse
import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


DEFAULT_URL = "https://script.google.com/macros/s/AKfycbyZlf8tv1b8fgyFeUyj913rVpC1e4QlQ_uiuRx-3phGklHA3HT0t0_Cqg3JVchvVKJr7A/exec"
DEFAULT_OUTPUT = Path("generated/holdings.pine")
DEFAULT_PNL_FILE = Path("PNLRebalance")
HOLDINGS_BLOCK_START = "// === AUTO-GENERATED START ==="
HOLDINGS_BLOCK_END = "// === AUTO-GENERATED END ==="
US_STOCK_BLOCK_START = "// === AUTO-GENERATED US STOCK START ==="
US_STOCK_BLOCK_END = "// === AUTO-GENERATED US STOCK END ==="
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
HOLDINGS_FIELDS = ("buy_qty", "buy_cost", "sell_qty", "sell_income")
CRYPTO_MARKET = "CRYPTO"
US_MARKET = "US"
US_STOCK_SYMBOLS = ("MSTR",)


@dataclass(frozen=True)
class HoldingsMarket:
    start_marker: str
    end_marker: str
    var_prefix: str

    def var_name(self, base: str) -> str:
        if not self.var_prefix:
            return base
        return self.var_prefix + base[0].upper() + base[1:]


HOLDINGS_MARKETS = {
    CRYPTO_MARKET: HoldingsMarket(HOLDINGS_BLOCK_START, HOLDINGS_BLOCK_END, ""),
    US_MARKET: HoldingsMarket(US_STOCK_BLOCK_START, US_STOCK_BLOCK_END, "us"),
}
HOLDINGS_ARRAYS = (
    ("symbols", "string", "symbol"),
    ("buyQtys", "float", "buy_qty"),
    ("buyCosts", "float", "buy_cost"),
    ("sellQtys", "float", "sell_qty"),
    ("sellIncomes", "float", "sell_income"),
)
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


def format_number(value: float, *, force_decimal: bool = False) -> str:
    formatted = f"{value:.8f}".rstrip("0").rstrip(".")
    if force_decimal and "." not in formatted:
        return f"{formatted}.0"
    return formatted


def holding_market(item: dict) -> str:
    return US_MARKET if item["symbol"] in US_STOCK_SYMBOLS else CRYPTO_MARKET


def partition_holdings(holdings: List[dict]) -> Dict[str, List[dict]]:
    partitions: Dict[str, List[dict]] = {market: [] for market in HOLDINGS_MARKETS}
    for item in holdings:
        partitions[holding_market(item)].append(item)
    return partitions


def format_pine_array(var_type: str, values: List[str]) -> str:
    if not values:
        return f"array.new_{var_type}()"
    return f"array.from({', '.join(values)})"


def build_market_block(market: str, rows: List[dict], updated_at: str) -> str:
    spec = HOLDINGS_MARKETS[market]
    lines = [spec.start_marker, f"// updated_at: {updated_at}"]
    for base, var_type, field in HOLDINGS_ARRAYS:
        if var_type == "string":
            values = [f'"{item[field]}"' for item in rows]
        else:
            values = [format_number(item[field], force_decimal=True) for item in rows]
        lines.append(f"var {var_type}[] {spec.var_name(base)} = {format_pine_array(var_type, values)}")
    lines.append(spec.end_marker)
    return "\n".join(lines) + "\n"


def build_holdings_blocks(payload: dict) -> Dict[str, str]:
    partitions = partition_holdings(payload.get("holdings", []))
    if not partitions[CRYPTO_MARKET]:
        raise ValueError("No crypto holdings found in payload")

    updated_at = payload.get("updated_at", "unknown")
    return {market: build_market_block(market, rows, updated_at) for market, rows in partitions.items()}


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
        f"var float BYBIT_EXCHANGE_USD = {format_number(balances['bybit'], force_decimal=True)}",
        f"var float BINANCE_EXCHANGE_USD = {format_number(balances['binance'], force_decimal=True)}",
        f"var float CRYPTO_DOT_COM_EXCHANGE_USD = {format_number(balances['crypto_com'], force_decimal=True)}",
        f"var float OKX_EXCHANGE_USD = {format_number(balances['okx'], force_decimal=True)}",
        f"var float PIONEX_EXCHANGE_USD = {format_number(balances['pionex'], force_decimal=True)}",
        f"var float KRAKEN_EXCHANGE_USD = {format_number(balances['kraken'], force_decimal=True)}",
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
        f"var float BANK1_AVAL = {format_number(snapshot['BANK1_AVAL'], force_decimal=True)}  // LineBank (TWD)",
        f"var float BANK2_AVAL = {format_number(snapshot['BANK2_AVAL'], force_decimal=True)}  // Bankee (TWD)",
        f"var float BANK3_AVAL = {format_number(snapshot['BANK3_AVAL'], force_decimal=True)}  // 台新 (TWD)",
        f"var float BANK4_AVAL = {format_number(snapshot['BANK4_AVAL'], force_decimal=True)}  // 樂天 (TWD)",
        f"var float BITO_AVAL = {format_number(snapshot['BITO_AVAL'], force_decimal=True)}  // 幣託 (USD)",
        f"var float VISA_AVAL = {format_number(snapshot['VISA_AVAL'], force_decimal=True)}  // Visa (USD) 出金",
        f"var float DEBT = {format_number(snapshot['DEBT'], force_decimal=True)}  // 負債(TWD)",
        CASH_LIABILITY_BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def build_output_content(holdings_blocks: Dict[str, str], usd_block: str, cash_liability_block: str) -> str:
    blocks = [holdings_blocks[market] for market in HOLDINGS_MARKETS] + [usd_block, cash_liability_block]
    return "\n\n".join(block.rstrip("\n") for block in blocks) + "\n"


def replace_named_block(content: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = content.find(start_marker)
    end = content.find(end_marker)

    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Could not find block markers: {start_marker} / {end_marker}")

    end += len(end_marker)
    return content[:start] + replacement.rstrip("\n") + content[end:]


def update_pnl_file(
    target_path: Path, holdings_blocks: Dict[str, str], usd_block: str, cash_liability_block: str
) -> None:
    updated = target_path.read_text(encoding="utf-8")
    for market, spec in HOLDINGS_MARKETS.items():
        updated = replace_named_block(updated, spec.start_marker, spec.end_marker, holdings_blocks[market])
    updated = replace_named_block(updated, USD_BLOCK_START, USD_BLOCK_END, usd_block)
    updated = replace_named_block(
        updated,
        CASH_LIABILITY_BLOCK_START,
        CASH_LIABILITY_BLOCK_END,
        cash_liability_block,
    )
    target_path.write_text(updated, encoding="utf-8")


def parse_array_values(content: str, var_name: str) -> list:
    pattern = rf"var\s+\w+\[\]\s+{re.escape(var_name)}\s*=\s*array\.(?:from\((.*?)\)|new_\w+\(\))"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find array values for {var_name}")

    raw_values = (match.group(1) or "").strip()
    if not raw_values:
        return []

    return ast.literal_eval("[" + raw_values + "]")


def parse_existing_holdings(content: str) -> List[Dict]:
    holdings = []
    for market, spec in HOLDINGS_MARKETS.items():
        if market != CRYPTO_MARKET and spec.start_marker not in content:
            continue

        columns = {field: parse_array_values(content, spec.var_name(base)) for base, _, field in HOLDINGS_ARRAYS}
        if len({len(values) for values in columns.values()}) != 1:
            raise ValueError(f"Existing {market} holdings arrays have inconsistent lengths")

        for index, symbol in enumerate(columns["symbol"]):
            holding = {"symbol": str(symbol), "market": market}
            holding.update({field: float(columns[field][index]) for field in HOLDINGS_FIELDS})
            holdings.append(holding)
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

    def holding_label(item: dict) -> str:
        market = holding_market(item)
        return item["symbol"] if market == CRYPTO_MARKET else f"{item['symbol']} ({market})"

    previous_map = {holding_label(item): item for item in previous}
    current_map = {holding_label(item): item for item in current}
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
        for field in HOLDINGS_FIELDS:
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
    holdings_blocks = build_holdings_blocks(payload)
    usd_block = build_usd_pine(payload)
    cash_liability_block = build_cash_liability_pine(payload)
    output_content = build_output_content(holdings_blocks, usd_block, cash_liability_block)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content, encoding="utf-8")
    if not args.skip_pnl_update:
        update_pnl_file(pnl_path, holdings_blocks, usd_block, cash_liability_block)
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
