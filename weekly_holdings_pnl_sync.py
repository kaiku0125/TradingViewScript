#!/usr/bin/env python3

import argparse
import ast
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import update_holdings_pine as holdings_sync
import update_pnl_history as pnl_history


DEFAULT_PNL_FILE = Path("PNLRebalance")
DEFAULT_GENERATED_FILE = Path("generated/holdings.pine")
DEFAULT_COMMIT_MESSAGE = "[update] Update assets"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
CRYPTO_PRICE_SOURCE_MAP = {
    "BTC": ("BTC/USD", "https://api.coinbase.com/v2/prices/BTC-USD/spot", ("data", "amount")),
    "ETH": ("ETH/USD", "https://api.coinbase.com/v2/prices/ETH-USD/spot", ("data", "amount")),
    "CRO": ("CRO/USD", "https://api.coinbase.com/v2/prices/CRO-USD/spot", ("data", "amount")),
    "ADA": ("ADA/USDT", "https://api.binance.com/api/v3/ticker/price?symbol=ADAUSDT", ("price",)),
    "BNB": ("BNB/USDT", "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT", ("price",)),
}
FIXED_PRICE_SOURCE_MAP = {
    "0050": ("0050", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_0050.tw&json=1&delay=0"),
    "USD/TWD": ("USD/TWD", "https://open.er-api.com/v6/latest/USD"),
}


@dataclass
class MarketSnapshot:
    prices: Dict[str, float]
    positions: Dict[str, float]
    costs: Dict[str, float]
    unrealized_pnl_twd: Dict[str, float]
    unsupported_symbols: list[str]
    exchange_usd: float
    cash_twd: float
    total_assets_twd: float
    total_crypto_assets_twd: float
    all_cost_twd: float
    speculation_pnl_twd: float
    speculation_pnl_ratio: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update holdings, compute current speculationPNL, append pnl history, and conditionally commit."
    )
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", default=holdings_sync.DEFAULT_URL)
    parser.add_argument("--output", default=str(DEFAULT_GENERATED_FILE))
    parser.add_argument("--pnl-file", default=str(DEFAULT_PNL_FILE))
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser.parse_args()


def fetch_json(url: str) -> Any:
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_nested_value(payload: Any, path: tuple[str, ...]) -> float:
    current = payload
    for key in path:
        current = current[key]
    return float(current)


def fetch_market_prices(symbols: list[str]) -> tuple[Dict[str, float], Dict[str, str], list[str]]:
    prices: Dict[str, float] = {}
    symbol_price_labels: Dict[str, str] = {}
    unsupported_symbols: list[str] = []

    for symbol in symbols:
        source = CRYPTO_PRICE_SOURCE_MAP.get(symbol)
        if source is None:
            unsupported_symbols.append(symbol)
            continue
        label, url, path = source
        payload = fetch_json(url)
        prices[label] = extract_nested_value(payload, path)
        symbol_price_labels[symbol] = label

    twse = fetch_json(FIXED_PRICE_SOURCE_MAP["0050"][1])
    msg_array = twse.get("msgArray", [])
    if not msg_array:
        raise ValueError("TWSE response missing msgArray for 0050")
    prices["0050"] = float(msg_array[0]["z"])

    usd_rates = fetch_json(FIXED_PRICE_SOURCE_MAP["USD/TWD"][1])
    twd_rate = usd_rates.get("rates", {}).get("TWD")
    if twd_rate is None:
        raise ValueError("Exchange rate response missing TWD")
    prices["USD/TWD"] = float(twd_rate)

    return prices, symbol_price_labels, unsupported_symbols


def safe_eval(expression: str, variables: Dict[str, float]) -> float:
    node = ast.parse(expression, mode="eval")

    def _eval(current: ast.AST) -> float:
        if isinstance(current, ast.Expression):
            return _eval(current.body)
        if isinstance(current, ast.Constant) and isinstance(current.value, (int, float)):
            return float(current.value)
        if isinstance(current, ast.Name):
            if current.id not in variables:
                raise ValueError(f"Unknown variable in expression: {current.id}")
            return variables[current.id]
        if isinstance(current, ast.UnaryOp) and isinstance(current.op, (ast.UAdd, ast.USub)):
            value = _eval(current.operand)
            return value if isinstance(current.op, ast.UAdd) else -value
        if isinstance(current, ast.BinOp) and isinstance(
            current.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left = _eval(current.left)
            right = _eval(current.right)
            if isinstance(current.op, ast.Add):
                return left + right
            if isinstance(current.op, ast.Sub):
                return left - right
            if isinstance(current.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError(f"Unsupported expression: {expression}")

    return _eval(node)


def extract_float_expressions(content: str) -> Dict[str, str]:
    expressions: Dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("var float "):
            continue
        without_prefix = stripped[len("var float ") :]
        if " = " not in without_prefix:
            continue
        constant_name, expr = without_prefix.split(" = ", 1)
        expressions[constant_name.strip()] = expr.split("//", 1)[0].strip()
    return expressions


def parse_numeric_constant(content: str, name: str) -> float:
    expressions = extract_float_expressions(content)
    cache: Dict[str, float] = {}

    def resolve(current_name: str) -> float:
        if current_name in cache:
            return cache[current_name]
        if current_name not in expressions:
            raise ValueError(f"Could not find constant {current_name}")
        resolved = safe_eval(expressions[current_name], {key: resolve(key) for key in expressions if key in cache})
        cache[current_name] = resolved
        return resolved

    while name not in cache:
        unresolved = [key for key in expressions if key not in cache]
        progressed = False
        for current_name in unresolved:
            try:
                cache[current_name] = safe_eval(expressions[current_name], cache)
                progressed = True
            except ValueError:
                continue
        if not progressed:
            break

    return resolve(name)


def build_positions_and_costs(payload: dict) -> tuple[Dict[str, float], Dict[str, float]]:
    positions: Dict[str, float] = {"0050": 0.0}
    costs: Dict[str, float] = {}

    for item in payload.get("holdings", []):
        symbol = str(item["symbol"])
        bought = float(item["buy_qty"])
        sold = float(item["sell_qty"])
        bought_cost = float(item["buy_cost"])
        positions[symbol] = bought - sold
        if bought == 0:
            costs[symbol] = 0.0
        else:
            costs[symbol] = math.ceil(bought_cost * (1 - (sold / bought)))

    return positions, costs


def calculate_market_snapshot(payload: dict, pnl_content: str) -> MarketSnapshot:
    positions, costs = build_positions_and_costs(payload)
    tracked_symbols = [symbol for symbol in positions if symbol != "0050"]
    prices, symbol_price_labels, unsupported_symbols = fetch_market_prices(tracked_symbols)
    usd_snapshot = holdings_sync.build_usd_snapshot(payload)

    bank1 = parse_numeric_constant(pnl_content, "BANK1_AVAL")
    bank2 = parse_numeric_constant(pnl_content, "BANK2_AVAL")
    bank3 = parse_numeric_constant(pnl_content, "BANK3_AVAL")
    bank4 = parse_numeric_constant(pnl_content, "BANK4_AVAL")
    bito = parse_numeric_constant(pnl_content, "BITO_AVAL")
    visa = parse_numeric_constant(pnl_content, "VISA_AVAL")
    all_stocks_cost = parse_numeric_constant(pnl_content, "ALL_STOCKS_COST")
    all_crypto_cost = parse_numeric_constant(pnl_content, "ALL_CRYPTO_COST")
    position_bought_0050 = parse_numeric_constant(pnl_content, "_0050_POSITION_BOUGHT")
    position_sold_0050 = parse_numeric_constant(pnl_content, "_0050_POSITION_SOLD")
    positions["0050"] = position_bought_0050 - position_sold_0050

    usd_twd = prices["USD/TWD"]
    total_cash_twd = bank1 + bank2 + bank3 + bank4 + bito * usd_twd
    total_stocks_assets_twd = prices["0050"] * positions["0050"]
    main_crypto_assets_usd = 0.0
    unrealized_pnl_twd: Dict[str, float] = {}
    for symbol in tracked_symbols:
        if symbol in unsupported_symbols:
            continue
        price_label = symbol_price_labels[symbol]
        remain_usd = prices[price_label] * positions[symbol]
        main_crypto_assets_usd += remain_usd
        unrealized_pnl_twd[symbol] = (remain_usd - costs[symbol]) * usd_twd

    exchange_usd = sum(float(value) for value in usd_snapshot.values())
    total_crypto_assets_twd = (main_crypto_assets_usd + exchange_usd) * usd_twd
    total_assets_twd = total_cash_twd + total_stocks_assets_twd + total_crypto_assets_twd
    all_cost_twd = all_stocks_cost + all_crypto_cost - bito * usd_twd
    speculation_pnl_twd = total_stocks_assets_twd + total_crypto_assets_twd - all_cost_twd + visa * usd_twd
    speculation_pnl_ratio = speculation_pnl_twd / all_cost_twd

    return MarketSnapshot(
        prices=prices,
        positions=positions,
        costs=costs,
        unrealized_pnl_twd=unrealized_pnl_twd,
        unsupported_symbols=unsupported_symbols,
        exchange_usd=exchange_usd,
        cash_twd=total_cash_twd,
        total_assets_twd=total_assets_twd,
        total_crypto_assets_twd=total_crypto_assets_twd,
        all_cost_twd=all_cost_twd,
        speculation_pnl_twd=speculation_pnl_twd,
        speculation_pnl_ratio=speculation_pnl_ratio,
    )


def format_price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_signed_twd(value: float) -> str:
    rounded = round(value)
    return f"{rounded:+,} TWD"


def format_twd(value: float) -> str:
    return f"{value:,.2f} TWD"


def format_ratio(value: float) -> str:
    return f"{value * 100:.2f}%"


def is_meaningful_zero(value: float) -> bool:
    return abs(value) < 1e-12


def write_pnl_history(pnl_path: Path, pnl_value: float, ratio: float) -> str:
    content = pnl_path.read_text(encoding="utf-8")
    year, month, day = pnl_history.get_default_date()
    comment = format_ratio(ratio)
    updated_content, summary = pnl_history.update_history_content(
        content, pnl_value, year, month, day, comment
    )
    pnl_path.write_text(updated_content, encoding="utf-8")
    return summary


def maybe_commit(pnl_path: Path, message: str) -> bool:
    subprocess.run(["git", "add", str(pnl_path)], check=True)
    diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff_result.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-m", message], check=True)
    return True


def print_summary(
    holdings_updated: bool,
    generated_updated: bool,
    pnl_updated: bool,
    commit_created: bool,
    holdings_summary: list[str],
    usd_summary: list[str],
    pnl_history_summary: str,
    snapshot: MarketSnapshot,
) -> None:
    taipei_now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    pnl_content = DEFAULT_PNL_FILE.read_text(encoding="utf-8")
    print(f"Holdings fetched successfully: yes")
    print(f"generated/holdings.pine updated: {'yes' if generated_updated else 'no'}")
    print(f"PNLRebalance updated: {'yes' if pnl_updated else 'no'}")
    print(f"Commit created: {'yes' if commit_created else 'no'}")
    if not holdings_updated:
        print("Holdings changed: no")
    print("")
    print(f"Price snapshot for {taipei_now}:")
    for label, value in snapshot.prices.items():
        print(f"{label} = {format_price(value)}")
    print("")
    print('Current pnl mapped to "speculationPNL":')
    print(format_twd(snapshot.speculation_pnl_twd))
    print(f"Ratio = {format_ratio(snapshot.speculation_pnl_ratio)}")
    print("")
    print("Open positions:")
    for label, value in snapshot.positions.items():
        if is_meaningful_zero(value) and label != "0050":
            continue
        print(f"{label}: {format_price(value)}")
    print("")
    print("Unrealized pnl by asset:")
    for label, value in snapshot.unrealized_pnl_twd.items():
        print(f"{label}: {format_signed_twd(value)}")
    if snapshot.unsupported_symbols:
        print("")
        print("Unsupported symbols:")
        for symbol in snapshot.unsupported_symbols:
            print(f"- {symbol}")
    print("")
    print("Key inputs:")
    print(f"Exchange USD balance: {format_price(snapshot.exchange_usd)} USD")
    print(f"Cash: {snapshot.cash_twd:,.0f} TWD")
    print(f"ALL_CRYPTO_COST = {format_price(parse_numeric_constant(pnl_content, 'ALL_CRYPTO_COST'))}")
    print(f"ALL_STOCKS_COST = {format_price(parse_numeric_constant(pnl_content, 'ALL_STOCKS_COST'))}")
    print(f"INPUT_CRYPTO_COM_VISA = {format_price(parse_numeric_constant(pnl_content, 'VISA_AVAL'))}")
    print("")
    print("Holdings summary:")
    for line in holdings_summary:
        print(f"- {line}")
    print("USD summary:")
    for line in usd_summary:
        print(f"- {line}")
    print("PNL history summary:")
    print(f"- {pnl_history_summary}")


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    pnl_path = Path(args.pnl_file)

    previous_holdings = holdings_sync.load_existing_holdings(output_path)
    previous_usd = holdings_sync.load_existing_usd(output_path)

    payload = holdings_sync.fetch_holdings(args.url, args.token)
    if payload.get("error"):
        raise SystemExit(f"Web app error: {payload['error']}")

    current_holdings = payload.get("holdings", [])
    current_usd = holdings_sync.build_usd_snapshot(payload)
    holdings_block = holdings_sync.build_holdings_pine(payload)
    usd_block = holdings_sync.build_usd_pine(payload)
    output_content = holdings_sync.build_output_content(holdings_block, usd_block)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content, encoding="utf-8")
    holdings_sync.update_pnl_file(pnl_path, holdings_block, usd_block)

    snapshot = calculate_market_snapshot(payload, pnl_path.read_text(encoding="utf-8"))
    pnl_history_summary = write_pnl_history(
        pnl_path, snapshot.speculation_pnl_twd, snapshot.speculation_pnl_ratio
    )

    holdings_summary = holdings_sync.summarize_holdings_changes(previous_holdings, current_holdings)
    usd_summary = holdings_sync.summarize_usd_changes(previous_usd, current_usd)
    holdings_changed = any("No holdings values changed" not in line for line in holdings_summary)

    commit_created = False
    if args.commit and holdings_changed:
        commit_created = maybe_commit(pnl_path, args.commit_message)

    print_summary(
        holdings_updated=holdings_changed,
        generated_updated=True,
        pnl_updated=True,
        commit_created=commit_created,
        holdings_summary=holdings_summary,
        usd_summary=usd_summary,
        pnl_history_summary=pnl_history_summary,
        snapshot=snapshot,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
