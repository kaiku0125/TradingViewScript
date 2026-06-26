#!/usr/bin/env python3

import argparse
import json
from dataclasses import dataclass
from math import isnan
from typing import Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_MODE = "aggressive"
DEFAULT_SPACING_ATR_MULTIPLIER = 0.35
TIMEFRAME_CONFIG = {
    "1h": {"interval": "1h", "range": "3mo"},
    "4h": {"interval": "1h", "range": "3mo"},
    "1d": {"interval": "1d", "range": "6mo"},
    "1w": {"interval": "1wk", "range": "2y"},
}


@dataclass
class OhlcBar:
    high: float
    low: float
    close: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate grid bounds using previous low, target price, and latest ATR(14)."
    )
    parser.add_argument("--symbol", required=True, help="Yahoo Finance symbol such as BTC-USD or AAPL")
    parser.add_argument("--timeframe", default="1d", choices=sorted(TIMEFRAME_CONFIG))
    parser.add_argument("--previous-low", required=True, type=float)
    parser.add_argument("--target-price", required=True, type=float)
    parser.add_argument("--fee-rate-percent", type=float, default=0.0)
    parser.add_argument("--atr-period", default=14, type=int)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args()


def fetch_chart(symbol: str, timeframe: str) -> dict:
    config = TIMEFRAME_CONFIG[timeframe]
    params = urlencode(
        {
            "interval": config["interval"],
            "range": config["range"],
            "includePrePost": "false",
            "events": "div,splits,capitalGains",
        }
    )
    url = YAHOO_CHART_URL.format(symbol=symbol) + "?" + params
    with urlopen(url) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise ValueError(f"Yahoo Finance error: {error}")

    results = chart.get("result") or []
    if not results:
        raise ValueError("No chart result returned")

    return results[0]


def compress_to_4h(bars: List[OhlcBar]) -> List[OhlcBar]:
    compressed: List[OhlcBar] = []
    for index in range(0, len(bars), 4):
        chunk = bars[index:index + 4]
        if len(chunk) < 4:
            continue
        compressed.append(
            OhlcBar(
                high=max(bar.high for bar in chunk),
                low=min(bar.low for bar in chunk),
                close=chunk[-1].close,
            )
        )
    return compressed


def build_bars(result: dict, timeframe: str) -> List[OhlcBar]:
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") or []
    if not quotes:
        raise ValueError("No quote data returned")

    quote = quotes[0]
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    bars: List[OhlcBar] = []

    for high, low, close in zip(highs, lows, closes):
        if high is None or low is None or close is None:
            continue
        if any(isnan(value) for value in (high, low, close)):
            continue
        bars.append(OhlcBar(high=float(high), low=float(low), close=float(close)))

    if timeframe == "4h":
        bars = compress_to_4h(bars)

    if not bars:
        raise ValueError("No valid OHLC bars available")

    return bars


def calculate_true_ranges(bars: Iterable[OhlcBar]) -> List[float]:
    bars_list = list(bars)
    if len(bars_list) < 2:
        raise ValueError("Need at least 2 bars to calculate ATR")

    true_ranges: List[float] = []
    previous_close: Optional[float] = None
    for bar in bars_list:
        if previous_close is None:
            true_range = bar.high - bar.low
        else:
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = bar.close
    return true_ranges


def calculate_atr(bars: List[OhlcBar], period: int) -> float:
    true_ranges = calculate_true_ranges(bars)
    if len(true_ranges) < period:
        raise ValueError(f"Not enough bars to calculate ATR({period})")

    atr = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        atr = ((atr * (period - 1)) + true_range) / period
    return atr


def format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def to_percent(value: float, base: float) -> float:
    if base == 0:
        return 0.0
    return (value / base) * 100.0


def main() -> int:
    args = parse_args()
    result = fetch_chart(args.symbol, args.timeframe)
    bars = build_bars(result, args.timeframe)
    atr_value = calculate_atr(bars, args.atr_period)
    lower_bound = args.previous_low - atr_value
    upper_bound = args.target_price
    range_width = upper_bound - lower_bound
    spacing_value = atr_value * DEFAULT_SPACING_ATR_MULTIPLIER
    theoretical_grid_count = round(range_width / spacing_value) if spacing_value > 0 else 0
    reference_price = bars[-1].close
    spacing_percent_lower = to_percent(spacing_value, lower_bound)
    spacing_percent_reference = to_percent(spacing_value, reference_price)
    spacing_percent_upper = to_percent(spacing_value, upper_bound)
    round_trip_fee_percent = args.fee_rate_percent * 2.0
    net_spacing_percent_lower = spacing_percent_lower - round_trip_fee_percent
    net_spacing_percent_reference = spacing_percent_reference - round_trip_fee_percent
    net_spacing_percent_upper = spacing_percent_upper - round_trip_fee_percent

    output = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "atr_period": args.atr_period,
        "atr_value": atr_value,
        "previous_low": args.previous_low,
        "target_price": args.target_price,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "mode": DEFAULT_MODE,
        "fee_rate_percent": args.fee_rate_percent,
        "range_width": range_width,
        "spacing_method": "ATR-based",
        "spacing_atr_multiplier": DEFAULT_SPACING_ATR_MULTIPLIER,
        "spacing_value": spacing_value,
        "reference_price": reference_price,
        "spacing_percent_range": {
            "lower_bound_base": spacing_percent_lower,
            "reference_price_base": spacing_percent_reference,
            "upper_bound_base": spacing_percent_upper,
        },
        "round_trip_fee_percent": round_trip_fee_percent,
        "net_spacing_percent_range": {
            "lower_bound_base": net_spacing_percent_lower,
            "reference_price_base": net_spacing_percent_reference,
            "upper_bound_base": net_spacing_percent_upper,
        },
        "theoretical_grid_count": theoretical_grid_count,
    }

    if args.output == "json":
        print(json.dumps(output, ensure_ascii=True, indent=2))
        return 0

    print(f"symbol: {args.symbol}")
    print(f"timeframe: {args.timeframe}")
    print(f"mode: {DEFAULT_MODE}")
    print(f"ATR({args.atr_period}): {format_number(atr_value)}")
    print(f"lower_bound = previous_low - 1*ATR = {format_number(lower_bound)}")
    print(f"upper_bound = target_price = {format_number(upper_bound)}")
    print(f"spacing_value = 0.35*ATR = {format_number(spacing_value)}")
    print(
        "spacing_percent_range = "
        f"{format_number(spacing_percent_upper)}% ~ {format_number(spacing_percent_lower)}%"
    )
    print(f"spacing_percent @ reference_price = {format_number(spacing_percent_reference)}%")
    print(f"round_trip_fee_percent = {format_number(round_trip_fee_percent)}%")
    print(
        "net_spacing_percent_range = "
        f"{format_number(net_spacing_percent_upper)}% ~ {format_number(net_spacing_percent_lower)}%"
    )
    print(f"net_spacing_percent @ reference_price = {format_number(net_spacing_percent_reference)}%")
    print(f"theoretical_grid_count = {theoretical_grid_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
