import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import weekly_holdings_pnl_sync as weekly
from holdings import update_holdings_pine as holdings_sync


REPO_ROOT = Path(__file__).resolve().parent.parent
PNL_FILE = REPO_ROOT / "PNLRebalance"
UPDATED_AT = "2026-11-09T01:42:11.862Z"
CRYPTO_ROWS = [
    {"symbol": "BTC", "buy_qty": 0.7487, "buy_cost": 40849, "sell_qty": 0.3263, "sell_income": 9755},
    {"symbol": "ETH", "buy_qty": 12.55, "buy_cost": 21486, "sell_qty": 5.55, "sell_income": 17084},
    {"symbol": "ADA", "buy_qty": 39575, "buy_cost": 11883, "sell_qty": 5299, "sell_income": 6428},
    {"symbol": "BNB", "buy_qty": 16.54, "buy_cost": 7872, "sell_qty": 6.667, "sell_income": 6878},
    {"symbol": "CRO", "buy_qty": 122800, "buy_cost": 14439, "sell_qty": 20178, "sell_income": 5959.89},
]
MSTR_ROW = {"symbol": "MSTR", "buy_qty": 2.5, "buy_cost": 300, "sell_qty": 0, "sell_income": 0}
TODAY_PAYLOAD = {
    "updated_at": UPDATED_AT,
    "holdings": CRYPTO_ROWS,
    "usd_balances": [{"exchange": "okx", "usd_balance": 3772}],
    "cash_liability": [],
}
WITH_MSTR_PAYLOAD = dict(TODAY_PAYLOAD, holdings=CRYPTO_ROWS + [MSTR_ROW])
EXPECTED_CRYPTO_BLOCK = """// === AUTO-GENERATED START ===
// updated_at: 2026-11-09T01:42:11.862Z
var string[] symbols = array.from("BTC", "ETH", "ADA", "BNB", "CRO")
var float[] buyQtys = array.from(0.7487, 12.55, 39575.0, 16.54, 122800.0)
var float[] buyCosts = array.from(40849.0, 21486.0, 11883.0, 7872.0, 14439.0)
var float[] sellQtys = array.from(0.3263, 5.55, 5299.0, 6.667, 20178.0)
var float[] sellIncomes = array.from(9755.0, 17084.0, 6428.0, 6878.0, 5959.89)
// === AUTO-GENERATED END ===
"""
EMPTY_US_BLOCK = """// === AUTO-GENERATED US STOCK START ===
// updated_at: 2026-11-09T01:42:11.862Z
var string[] usSymbols = array.new_string()
var float[] usBuyQtys = array.new_float()
var float[] usBuyCosts = array.new_float()
var float[] usSellQtys = array.new_float()
var float[] usSellIncomes = array.new_float()
// === AUTO-GENERATED US STOCK END ===
"""
MSTR_US_BLOCK = """// === AUTO-GENERATED US STOCK START ===
// updated_at: 2026-11-09T01:42:11.862Z
var string[] usSymbols = array.from("MSTR")
var float[] usBuyQtys = array.from(2.5)
var float[] usBuyCosts = array.from(300.0)
var float[] usSellQtys = array.from(0.0)
var float[] usSellIncomes = array.from(0.0)
// === AUTO-GENERATED US STOCK END ===
"""


def named_block(content: str, start_marker: str, end_marker: str) -> str:
    start = content.index(start_marker)
    end = content.index(end_marker) + len(end_marker)
    return content[start:end] + "\n"


def update_temp_pnl(payload: dict) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "PNLRebalance"
        shutil.copyfile(PNL_FILE, target)
        holdings_sync.update_pnl_file(
            target,
            holdings_sync.build_holdings_blocks(payload),
            holdings_sync.build_usd_pine(payload),
            holdings_sync.build_cash_liability_pine(payload),
        )
        return target.read_text(encoding="utf-8")


class HoldingsMarketBlocksTest(unittest.TestCase):
    def test_payload_without_market_keeps_crypto_block_and_emits_empty_us_arrays(self) -> None:
        blocks = holdings_sync.build_holdings_blocks(TODAY_PAYLOAD)
        self.assertEqual(blocks[holdings_sync.CRYPTO_MARKET], EXPECTED_CRYPTO_BLOCK)
        self.assertEqual(blocks[holdings_sync.US_MARKET], EMPTY_US_BLOCK)

    def test_us_row_goes_to_us_block_without_touching_crypto_block(self) -> None:
        blocks = holdings_sync.build_holdings_blocks(WITH_MSTR_PAYLOAD)
        self.assertEqual(blocks[holdings_sync.CRYPTO_MARKET], EXPECTED_CRYPTO_BLOCK)
        self.assertEqual(blocks[holdings_sync.US_MARKET], MSTR_US_BLOCK)

    def test_update_pnl_file_writes_both_holdings_blocks(self) -> None:
        for payload, us_block in ((TODAY_PAYLOAD, EMPTY_US_BLOCK), (WITH_MSTR_PAYLOAD, MSTR_US_BLOCK)):
            updated = update_temp_pnl(payload)
            self.assertEqual(
                named_block(updated, holdings_sync.US_STOCK_BLOCK_START, holdings_sync.US_STOCK_BLOCK_END),
                us_block,
            )
            self.assertEqual(
                named_block(updated, holdings_sync.HOLDINGS_BLOCK_START, holdings_sync.HOLDINGS_BLOCK_END),
                EXPECTED_CRYPTO_BLOCK,
            )

    def test_update_pnl_file_stops_when_us_markers_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "PNLRebalance"
            content = PNL_FILE.read_text(encoding="utf-8").replace(holdings_sync.US_STOCK_BLOCK_START, "")
            target.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "US STOCK"):
                holdings_sync.update_pnl_file(
                    target,
                    holdings_sync.build_holdings_blocks(TODAY_PAYLOAD),
                    holdings_sync.build_usd_pine(TODAY_PAYLOAD),
                    holdings_sync.build_cash_liability_pine(TODAY_PAYLOAD),
                )
            self.assertEqual(target.read_text(encoding="utf-8"), content)

    def test_generated_output_round_trips_both_markets(self) -> None:
        output = holdings_sync.build_output_content(
            holdings_sync.build_holdings_blocks(WITH_MSTR_PAYLOAD),
            holdings_sync.build_usd_pine(WITH_MSTR_PAYLOAD),
            holdings_sync.build_cash_liability_pine(WITH_MSTR_PAYLOAD),
        )
        parsed = holdings_sync.parse_existing_holdings(output)
        self.assertEqual([(row["symbol"], row["market"]) for row in parsed][-1], ("MSTR", "US"))
        self.assertEqual(holdings_sync.parse_existing_usd(output)["okx"], 3772.0)
        self.assertEqual(
            holdings_sync.summarize_holdings_changes(parsed, WITH_MSTR_PAYLOAD["holdings"]),
            ["No holdings values changed; only metadata such as updated_at may have changed."],
        )

    def test_snapshot_written_before_us_block_existed_still_summarizes_changes(self) -> None:
        old_snapshot = EXPECTED_CRYPTO_BLOCK + "\n" + holdings_sync.build_usd_pine(TODAY_PAYLOAD)
        previous = holdings_sync.parse_existing_holdings(old_snapshot)
        self.assertEqual(len(previous), 5)
        self.assertEqual(
            holdings_sync.summarize_holdings_changes(previous, WITH_MSTR_PAYLOAD["holdings"]),
            ["MSTR (US): added"],
        )


def fake_market_json(mstr_price: float):
    responses = {
        "https://api.coinbase.com/v2/prices/BTC-USD/spot": {"data": {"amount": "100000"}},
        "https://api.coinbase.com/v2/prices/ETH-USD/spot": {"data": {"amount": "3000"}},
        "https://api.coinbase.com/v2/prices/CRO-USD/spot": {"data": {"amount": "0.1"}},
        "https://api.binance.com/api/v3/ticker/price?symbol=ADAUSDT": {"price": "0.5"},
        "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT": {"price": "600"},
        weekly.FIXED_PRICE_SOURCE_MAP["0050"][1]: {"msgArray": [{"z": "50"}]},
        weekly.FIXED_PRICE_SOURCE_MAP["USD/TWD"][1]: {"rates": {"TWD": 32}},
        weekly.US_STOCK_PRICE_URL.format(symbol="MSTR"): {
            "chart": {"result": [{"meta": {"regularMarketPrice": mstr_price}}]}
        },
    }

    def fetch(url: str, headers=None):
        if url == weekly.US_STOCK_PRICE_URL.format(symbol="MSTR"):
            assert headers and "Mozilla" in headers["User-Agent"], "Yahoo needs a browser User-Agent"
        return json.loads(json.dumps(responses[url]))

    return fetch


class WeeklyUsStockSnapshotTest(unittest.TestCase):
    def snapshot(self, payload: dict) -> weekly.MarketSnapshot:
        with mock.patch.object(weekly, "fetch_json", fake_market_json(mstr_price=400.0)):
            return weekly.calculate_market_snapshot(payload, PNL_FILE.read_text(encoding="utf-8"))

    def test_us_value_enters_assets_and_pnl_but_not_cost(self) -> None:
        before = self.snapshot(TODAY_PAYLOAD)
        after = self.snapshot(WITH_MSTR_PAYLOAD)
        mstr_value_twd = 2.5 * 400.0 * 32

        self.assertEqual(before.total_us_stocks_assets_twd, 0.0)
        self.assertTrue(math.isclose(after.total_us_stocks_assets_twd, mstr_value_twd))
        self.assertEqual(after.all_cost_twd, before.all_cost_twd)
        self.assertTrue(math.isclose(after.total_assets_twd - before.total_assets_twd, mstr_value_twd))
        self.assertTrue(math.isclose(after.speculation_pnl_twd - before.speculation_pnl_twd, mstr_value_twd))
        self.assertTrue(math.isclose(after.unrealized_pnl_twd["MSTR"], (1000.0 - 300.0) * 32))
        self.assertEqual(after.total_crypto_assets_twd, before.total_crypto_assets_twd)
        self.assertNotIn("MSTR", after.unsupported_symbols)


if __name__ == "__main__":
    unittest.main()
