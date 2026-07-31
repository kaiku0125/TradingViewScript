#!/usr/bin/env python3

import argparse
import ast
import json
import math
import os
import subprocess
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from holdings import update_holdings_pine as holdings_sync
import update_pnl_history as pnl_history


DEFAULT_PNL_FILE = Path("PNLRebalance")
DEFAULT_GENERATED_FILE = Path("generated/holdings.pine")
DEFAULT_COMMIT_MESSAGE = "[update] Update assets"
DEFAULT_ENV_FILE = Path(".env.local")
DEFAULT_STATE_FILE = Path("generated/weekly_holdings_pnl_sync_state.json")
DEFAULT_WEEKLY_REVIEW_SUMMARY_FILE = Path("generated/weekly_review_summary.md")
DEFAULT_TRADE_SNAPSHOT_FILE = Path("generated/trade_rows.json")
DEFAULT_TRADE_HISTORY_PINE_FILE = Path("trade_history/TradeHistoryLabels.pine")
NOTION_API_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
DEFAULT_NOTION_WEEKLY_REVIEW_ICON = "🗓️"
TRADE_ROWS_REFRESHER = Path("refresh_trade_rows.py")
EXPECTED_BRANCH = "update/routine"
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


@dataclass
class SyncState:
    last_checked_at: Optional[str]
    last_source_updated_at: Optional[str]
    last_holdings_hash: Optional[str]
    last_usd_hash: Optional[str]
    last_cash_liability_hash: Optional[str]
    last_result: Optional[str]
    last_total_assets_twd: Optional[float]
    last_speculation_pnl_twd: Optional[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update holdings, compute current speculationPNL, append pnl history, and conditionally commit."
    )
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", default=holdings_sync.DEFAULT_URL)
    parser.add_argument("--output", default=str(DEFAULT_GENERATED_FILE))
    parser.add_argument("--pnl-file", default=str(DEFAULT_PNL_FILE))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser.parse_args()


def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def fetch_json(url: str) -> Any:
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state(path: Path) -> SyncState:
    if not path.exists():
        return SyncState(None, None, None, None, None, None, None, None)

    data = json.loads(path.read_text(encoding="utf-8"))
    return SyncState(
        last_checked_at=data.get("last_checked_at"),
        last_source_updated_at=data.get("last_source_updated_at"),
        last_holdings_hash=data.get("last_holdings_hash"),
        last_usd_hash=data.get("last_usd_hash"),
        last_cash_liability_hash=data.get("last_cash_liability_hash"),
        last_result=data.get("last_result"),
        last_total_assets_twd=data.get("last_total_assets_twd"),
        last_speculation_pnl_twd=data.get("last_speculation_pnl_twd"),
    )


def save_state(path: Path, state: SyncState) -> None:
    path.write_text(
        json.dumps(
            {
                "last_checked_at": state.last_checked_at,
                "last_source_updated_at": state.last_source_updated_at,
                "last_holdings_hash": state.last_holdings_hash,
                "last_usd_hash": state.last_usd_hash,
                "last_cash_liability_hash": state.last_cash_liability_hash,
                "last_result": state.last_result,
                "last_total_assets_twd": state.last_total_assets_twd,
                "last_speculation_pnl_twd": state.last_speculation_pnl_twd,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def now_taipei_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def get_current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def worktree_is_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def branch_exists(branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def ensure_expected_branch() -> None:
    current_branch = get_current_branch()
    if current_branch != EXPECTED_BRANCH:
        if worktree_is_dirty():
            raise SystemExit(
                f"Cannot switch to '{EXPECTED_BRANCH}' from '{current_branch}' because the worktree has uncommitted changes."
            )
        if branch_exists(EXPECTED_BRANCH):
            subprocess.run(["git", "checkout", EXPECTED_BRANCH], check=True)
        else:
            subprocess.run(["git", "checkout", "-b", EXPECTED_BRANCH], check=True)


def extract_nested_value(payload: Any, path: tuple[str, ...]) -> float:
    current = payload
    for key in path:
        current = current[key]
    return float(current)


def first_valid_float(values: list[Any], field_name: str) -> float:
    for value in values:
        if value in (None, "", "-"):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    raise ValueError(f"Could not find a valid float for {field_name}")


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
    twse_row = msg_array[0]
    prices["0050"] = first_valid_float(
        [
            twse_row.get("z"),
            twse_row.get("y"),
            twse_row.get("o"),
            twse_row.get("h"),
            twse_row.get("l"),
        ],
        "0050",
    )

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
    rounded_pnl_value = round(pnl_value)
    updated_content, summary = pnl_history.update_history_content(
        content, rounded_pnl_value, year, month, day, comment
    )
    pnl_path.write_text(updated_content, encoding="utf-8")
    return summary


def has_history_entry_for_date(pnl_path: Path, year: int, month: int, day: int) -> bool:
    content = pnl_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    start_index, end_index = pnl_history.find_history_block(lines)
    entries = pnl_history.parse_history_entries(lines, start_index, end_index)
    return any(entry.same_date(year, month, day) for entry in entries)


def maybe_commit(pnl_path: Path, message: str) -> bool:
    subprocess.run(
        ["git", "add", str(pnl_path), str(DEFAULT_TRADE_HISTORY_PINE_FILE)],
        check=True,
    )
    diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff_result.returncode == 0:
        return False
    subprocess.run(["git", "commit", "-m", message], check=True)
    return True


def build_commit_reasons(
    source_changed: bool,
    has_today_history: bool,
    trade_history_updated: bool,
) -> list[str]:
    reasons: list[str] = []
    if source_changed:
        reasons.append("holdings, exchange USD, or cash/liability values changed")
    if not has_today_history:
        reasons.append("today's pnl history entry was missing")
    if trade_history_updated:
        reasons.append("trade history labels changed")
    return reasons


def refresh_trade_history_snapshot(base_url: str, token: str) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(TRADE_ROWS_REFRESHER),
        "--url",
        base_url,
        "--token",
        token,
        "--output",
        str(DEFAULT_TRADE_SNAPSHOT_FILE),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return False, f"failed to refresh live trade rows: {stderr}"
    stdout = result.stdout.strip().replace("\n", " | ")
    return True, stdout or "trade rows refreshed"


def sync_trade_history(snapshot_path: Path) -> tuple[bool, str]:
    before_content = (
        DEFAULT_TRADE_HISTORY_PINE_FILE.read_text(encoding="utf-8")
        if DEFAULT_TRADE_HISTORY_PINE_FILE.exists()
        else ""
    )
    result = subprocess.run(
        [sys.executable, "trade_history/update_trade_history.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return False, f"failed: {stderr}"

    after_content = (
        DEFAULT_TRADE_HISTORY_PINE_FILE.read_text(encoding="utf-8")
        if DEFAULT_TRADE_HISTORY_PINE_FILE.exists()
        else ""
    )
    updated = before_content != after_content
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    fetched_at = payload.get("fetched_at", "unknown")
    summary = f"updated from live snapshot ({fetched_at})" if updated else f"no changes from live snapshot ({fetched_at})"
    return updated, summary


def build_summary_lines(
    holdings_updated: bool,
    generated_updated: bool,
    pnl_updated: bool,
    trade_history_updated: bool,
    commit_created: bool,
    commit_reasons: list[str],
    holdings_summary: list[str],
    usd_summary: list[str],
    cash_liability_summary: list[str],
    pnl_history_summary: str,
    trade_history_summary: str,
    notion_summary: str,
    snapshot: MarketSnapshot,
    state_result: str,
    source_updated_at: Optional[str],
    state_checked_at: str,
    previous_state: SyncState,
) -> list[str]:
    taipei_now = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    pnl_content = DEFAULT_PNL_FILE.read_text(encoding="utf-8")
    lines = [
        "Weekly holdings and pnl sync",
        f"Date: {taipei_now}",
        f"Last checked at: {state_checked_at}",
        f"Source updated_at: {source_updated_at or 'unknown'}",
        f"State result: {state_result}",
        f"Holdings fetched successfully: yes",
        f"generated/holdings.pine updated: {'yes' if generated_updated else 'no'}",
        f"PNLRebalance updated: {'yes' if pnl_updated else 'no'}",
        f"TradeHistoryLabels.pine updated: {'yes' if trade_history_updated else 'no'}",
        f"Commit created: {'yes' if commit_created else 'no'}",
        f"Commit trigger: {'; '.join(commit_reasons) if commit_reasons else 'none'}",
    ]
    if not holdings_updated:
        lines.append("Holdings changed: no")

    lines.extend(
        [
            "",
            "Price snapshot:",
        ]
    )
    for label, value in snapshot.prices.items():
        lines.append(f"{label} = {format_price(value)}")

    lines.extend(
        [
            "",
            f"speculationPNL = {format_twd(snapshot.speculation_pnl_twd)}",
            f"Ratio = {format_ratio(snapshot.speculation_pnl_ratio)}",
            "",
            "Open positions:",
        ]
    )
    for label, value in snapshot.positions.items():
        if is_meaningful_zero(value) and label != "0050":
            continue
        lines.append(f"{label}: {format_price(value)}")

    lines.extend(["", "Unrealized pnl by asset:"])
    for label, value in snapshot.unrealized_pnl_twd.items():
        lines.append(f"{label}: {format_signed_twd(value)}")

    if snapshot.unsupported_symbols:
        lines.extend(["", "Unsupported symbols:"])
        for symbol in snapshot.unsupported_symbols:
            lines.append(f"- {symbol}")

    lines.extend(
        [
            "",
            "Key inputs:",
            f"Exchange USD balance: {format_price(snapshot.exchange_usd)} USD",
            f"Cash: {snapshot.cash_twd:,.0f} TWD",
            f"ALL_CRYPTO_COST = {format_price(parse_numeric_constant(pnl_content, 'ALL_CRYPTO_COST'))}",
            f"ALL_STOCKS_COST = {format_price(parse_numeric_constant(pnl_content, 'ALL_STOCKS_COST'))}",
            f"INPUT_CRYPTO_COM_VISA = {format_price(parse_numeric_constant(pnl_content, 'VISA_AVAL'))}",
            "",
            "Holdings summary:",
        ]
    )
    for line in holdings_summary:
        lines.append(f"- {line}")
    lines.append("USD summary:")
    for line in usd_summary:
        lines.append(f"- {line}")
    lines.append("Cash/Liability summary:")
    for line in cash_liability_summary:
        lines.append(f"- {line}")
    lines.append("PNL history summary:")
    lines.append(f"- {pnl_history_summary}")
    lines.append("Trade history summary:")
    lines.append(f"- {trade_history_summary}")
    lines.append("Notion weekly review summary:")
    lines.append(f"- {notion_summary}")
    lines.extend(["", "-----", ""])
    lines.extend(
        build_notion_weekly_review_lines(
            snapshot=snapshot,
            holdings_summary=holdings_summary,
            usd_summary=usd_summary,
            cash_liability_summary=cash_liability_summary,
            previous_state=previous_state,
        )
    )
    return lines


def build_notion_weekly_review_lines(
    snapshot: MarketSnapshot,
    holdings_summary: list[str],
    usd_summary: list[str],
    cash_liability_summary: list[str],
    previous_state: SyncState,
) -> list[str]:
    week_label = datetime.now(TAIPEI_TZ).strftime("%Y-W%W")
    top_profit_symbol: Optional[str] = None
    top_profit_value: Optional[float] = None
    if snapshot.unrealized_pnl_twd:
        top_profit_symbol, top_profit_value = max(
            snapshot.unrealized_pnl_twd.items(), key=lambda item: item[1]
        )

    total_asset_change_text = "首次執行，尚無上次同步基準"
    if previous_state.last_total_assets_twd is not None:
        total_asset_change_text = format_signed_twd(
            snapshot.total_assets_twd - previous_state.last_total_assets_twd
        )

    biggest_profit_source_text = "本週無可用資料"
    if top_profit_symbol is not None and top_profit_value is not None:
        biggest_profit_source_text = (
            f"{top_profit_symbol}（未實現損益 {format_signed_twd(top_profit_value)}）"
        )

    lines = [
        "【可直接貼進 Notion 的中文週報摘要】",
        f"週別：{week_label}",
        "",
        "1. 本週總資產變化（系統填入）",
        f"- 本週總資產變化：{total_asset_change_text}",
        f"- 目前總資產：{format_twd(snapshot.total_assets_twd)}",
        f"- 目前 PNL：{format_twd(snapshot.speculation_pnl_twd)}",
        f"- 目前報酬率：{format_ratio(snapshot.speculation_pnl_ratio)}",
        "",
        "2. 本週最大獲利來源（系統填入）",
        f"- 最大獲利來源：{biggest_profit_source_text}",
        f"- 交易所 USD 餘額：{format_price(snapshot.exchange_usd)} USD",
        f"- 現金部位：{snapshot.cash_twd:,.0f} TWD",
        "",
        "3. 本週最大失誤（手動填寫）",
        "- 本週最大失誤：",
        "- 我在哪個判斷、節奏或配置上做錯？",
        "- 如果重來一次，我會改哪一個決策？",
        "",
        "4. 下週調整計畫（手動填寫）",
        "- 下週調整計畫：",
        "- 哪個持倉需要持續觀察？",
        "- 哪個配置需要微調？",
        "",
        "補充摘要",
        "- Holdings 變化：",
    ]
    lines.extend(f"  - {line}" for line in holdings_summary)
    lines.append("- USD Balance 變化：")
    lines.extend(f"  - {line}" for line in usd_summary)
    lines.append("- Cash/Liability 變化：")
    lines.extend(f"  - {line}" for line in cash_liability_summary)
    return lines


def write_weekly_review_summary(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }


def notion_request(method: str, path: str, token: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{NOTION_API_BASE_URL}{path}",
        data=data,
        headers=notion_headers(token),
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API {method} {path} failed: {body}") from exc


def notion_text_block(block_type: str, text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text},
                }
            ]
        },
    }


def notion_review_blocks(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in lines:
        if not line:
            blocks.append(notion_text_block("paragraph", ""))
        elif line.startswith("週別："):
            blocks.append(notion_text_block("paragraph", line))
        elif line[0].isdigit() and ". " in line:
            blocks.append(notion_text_block("heading_2", line))
        elif line == "補充摘要":
            blocks.append(notion_text_block("heading_2", line))
        elif line.startswith("- "):
            blocks.append(notion_text_block("bulleted_list_item", line[2:]))
        elif line.startswith("  - "):
            blocks.append(notion_text_block("bulleted_list_item", line[4:]))
        else:
            blocks.append(notion_text_block("paragraph", line))
    return blocks


def notion_child_page_exists(parent_page_id: str, title: str, token: str) -> bool:
    start_cursor: Optional[str] = None
    while True:
        query = f"?start_cursor={start_cursor}" if start_cursor else ""
        payload = notion_request(
            "GET",
            f"/blocks/{parent_page_id}/children{query}",
            token,
        )
        for block in payload.get("results", []):
            child_page = block.get("child_page")
            if child_page and child_page.get("title") == title:
                return True
        if not payload.get("has_more"):
            return False
        start_cursor = payload.get("next_cursor")


def create_notion_weekly_review(title: str, lines: list[str]) -> str:
    token = os.environ.get("NOTION_TOKEN")
    parent_page_id = os.environ.get("NOTION_PAGE_ID")
    icon = os.environ.get("NOTION_WEEKLY_REVIEW_ICON", DEFAULT_NOTION_WEEKLY_REVIEW_ICON)
    if not token or not parent_page_id:
        return "skipped because NOTION_TOKEN or NOTION_PAGE_ID is missing"

    if notion_child_page_exists(parent_page_id, title, token):
        return f"skipped because {title} already exists"

    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title},
                    }
                ]
            }
        },
        "children": notion_review_blocks(lines),
    }
    if icon:
        payload["icon"] = {"type": "emoji", "emoji": icon}
    result = notion_request("POST", "/pages", token, payload)
    return f"created {title}: {result.get('url', 'unknown url')}"


def sync_notion_weekly_review_best_effort(title: str, lines: list[str]) -> str:
    try:
        return create_notion_weekly_review(title, lines)
    except Exception as exc:
        return f"skipped because Notion sync failed: {exc}"


def send_telegram_message(message: str) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return

    payload = urlencode({"chat_id": chat_id, "text": message})
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    with urlopen(url, data=payload.encode("utf-8")) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {body}")


def notify_telegram_best_effort(message: str) -> None:
    try:
        send_telegram_message(message)
    except Exception as exc:
        print(f"Telegram notification skipped: {exc}")


def print_summary(
    holdings_updated: bool,
    generated_updated: bool,
    pnl_updated: bool,
    trade_history_updated: bool,
    commit_created: bool,
    holdings_summary: list[str],
    usd_summary: list[str],
    cash_liability_summary: list[str],
    pnl_history_summary: str,
    trade_history_summary: str,
    snapshot: MarketSnapshot,
) -> None:
    for line in build_summary_lines(
        holdings_updated=holdings_updated,
        generated_updated=generated_updated,
        pnl_updated=pnl_updated,
        trade_history_updated=trade_history_updated,
        commit_created=commit_created,
        commit_reasons=[],
        holdings_summary=holdings_summary,
        usd_summary=usd_summary,
        cash_liability_summary=cash_liability_summary,
        pnl_history_summary=pnl_history_summary,
        trade_history_summary=trade_history_summary,
        notion_summary="not run from print_summary helper",
        snapshot=snapshot,
        state_result="unknown",
        source_updated_at=None,
        state_checked_at=now_taipei_iso(),
        previous_state=SyncState(None, None, None, None, None, None, None, None),
    ):
        print(line)


def main() -> int:
    load_local_env(DEFAULT_ENV_FILE)
    ensure_expected_branch()
    args = parse_args()
    output_path = Path(args.output)
    pnl_path = Path(args.pnl_file)
    state_path = Path(args.state_file)

    previous_holdings = holdings_sync.load_existing_holdings(output_path)
    previous_usd = holdings_sync.load_existing_usd(output_path)
    previous_cash_liability = holdings_sync.load_existing_cash_liability(output_path)
    previous_state = load_state(state_path)

    payload = holdings_sync.fetch_holdings(args.url, args.token)
    if payload.get("error"):
        raise SystemExit(f"Web app error: {payload['error']}")

    current_holdings = payload.get("holdings", [])
    current_usd = holdings_sync.build_usd_snapshot(payload)
    current_cash_liability = holdings_sync.build_cash_liability_snapshot(payload)
    source_updated_at = payload.get("updated_at")
    current_holdings_hash = stable_hash(current_holdings)
    current_usd_hash = stable_hash(current_usd)
    current_cash_liability_hash = stable_hash(current_cash_liability)
    checked_at = now_taipei_iso()
    history_year, history_month, history_day = pnl_history.get_default_date()
    holdings_changed = previous_state.last_holdings_hash != current_holdings_hash
    usd_changed = previous_state.last_usd_hash != current_usd_hash
    cash_liability_changed = (
        previous_state.last_cash_liability_hash != current_cash_liability_hash
    )

    state_result = (
        "changed" if (holdings_changed or usd_changed or cash_liability_changed) else "no_change"
    )

    holdings_summary = holdings_sync.summarize_holdings_changes(previous_holdings, current_holdings)
    usd_summary = holdings_sync.summarize_usd_changes(previous_usd, current_usd)
    cash_liability_summary = holdings_sync.summarize_cash_liability_changes(
        previous_cash_liability, current_cash_liability
    )
    source_changed = holdings_changed or usd_changed or cash_liability_changed
    has_today_history = has_history_entry_for_date(
        pnl_path, history_year, history_month, history_day
    )
    should_write_pnl_history = source_changed or not has_today_history

    generated_updated = False
    pnl_updated = False
    trade_history_updated = False
    holdings_block = holdings_sync.build_holdings_pine(payload)
    usd_block = holdings_sync.build_usd_pine(payload)
    cash_liability_block = holdings_sync.build_cash_liability_pine(payload)
    pnl_history_summary = "skipped because source data did not change"
    trade_history_summary = "not run yet"

    if source_changed:
        output_content = holdings_sync.build_output_content(
            holdings_block, usd_block, cash_liability_block
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_content, encoding="utf-8")
        holdings_sync.update_pnl_file(
            pnl_path, holdings_block, usd_block, cash_liability_block
        )
        generated_updated = True
        pnl_updated = True

    snapshot = calculate_market_snapshot(payload, pnl_path.read_text(encoding="utf-8"))
    if should_write_pnl_history:
        pnl_history_summary = write_pnl_history(
            pnl_path, snapshot.speculation_pnl_twd, snapshot.speculation_pnl_ratio
        )
        pnl_updated = True
    elif not source_changed:
        pnl_history_summary = "skipped because today's pnl history already exists"

    trade_rows_refreshed, trade_rows_refresh_summary = refresh_trade_history_snapshot(
        args.url, args.token
    )
    if trade_rows_refreshed:
        trade_history_updated, trade_history_summary = sync_trade_history(
            DEFAULT_TRADE_SNAPSHOT_FILE
        )
        trade_history_summary = f"{trade_rows_refresh_summary}; {trade_history_summary}"
    else:
        trade_history_summary = trade_rows_refresh_summary

    commit_created = False
    commit_reasons = build_commit_reasons(
        source_changed=source_changed,
        has_today_history=has_today_history,
        trade_history_updated=trade_history_updated,
    )
    if args.commit and commit_reasons:
        commit_created = maybe_commit(pnl_path, args.commit_message)

    state = SyncState(
        last_checked_at=checked_at,
        last_source_updated_at=source_updated_at,
        last_holdings_hash=current_holdings_hash,
        last_usd_hash=current_usd_hash,
        last_cash_liability_hash=current_cash_liability_hash,
        last_result=state_result,
        last_total_assets_twd=snapshot.total_assets_twd,
        last_speculation_pnl_twd=snapshot.speculation_pnl_twd,
    )
    save_state(state_path, state)

    weekly_review_lines = build_notion_weekly_review_lines(
        snapshot=snapshot,
        holdings_summary=holdings_summary,
        usd_summary=usd_summary,
        cash_liability_summary=cash_liability_summary,
        previous_state=previous_state,
    )
    weekly_review_title = f"Weekly Review {datetime.now(TAIPEI_TZ).strftime('%Y-W%W')}"
    notion_summary = sync_notion_weekly_review_best_effort(
        weekly_review_title,
        weekly_review_lines[1:],
    )

    summary_lines = build_summary_lines(
        holdings_updated=source_changed,
        generated_updated=generated_updated,
        pnl_updated=pnl_updated,
        trade_history_updated=trade_history_updated,
        commit_created=commit_created,
        commit_reasons=commit_reasons,
        holdings_summary=holdings_summary,
        usd_summary=usd_summary,
        cash_liability_summary=cash_liability_summary,
        pnl_history_summary=pnl_history_summary,
        trade_history_summary=trade_history_summary,
        notion_summary=notion_summary,
        snapshot=snapshot,
        state_result=state_result,
        source_updated_at=source_updated_at,
        state_checked_at=checked_at,
        previous_state=previous_state,
    )
    write_weekly_review_summary(DEFAULT_WEEKLY_REVIEW_SUMMARY_FILE, weekly_review_lines)
    print("\n".join(summary_lines))
    notify_telegram_best_effort("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        load_local_env(DEFAULT_ENV_FILE)
        notify_telegram_best_effort(f"Weekly holdings and pnl sync failed\nError: {exc}")
        raise
