from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from decimal import Decimal
from pathlib import Path


BITCOIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BITCOIN_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.config import load_config
from bitcoin_dca.cli import main as cli_main
from bitcoin_dca.errors import (
    JournalValidationError,
    LockUnavailableError,
    OperationCancelled,
    UserInputError,
)
from bitcoin_dca.ledger import JournalService
from bitcoin_dca.storage import JournalStore


class JournalCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        source_config = json.loads(
            (BITCOIN_ROOT / "config" / "config.1.0-draft.2.json").read_text(
                encoding="utf-8"
            )
        )
        source_config["runtime"]["data_dir"] = str(self.workspace / "data")
        source_config["runtime"]["reports_dir"] = str(self.workspace / "reports")
        source_config["runtime"]["templates_dir"] = str(
            BITCOIN_ROOT / "templates"
        )
        self.config_path = self.workspace / "config.json"
        self.config_path.write_text(
            json.dumps(source_config), encoding="utf-8"
        )
        self.config = load_config(self.config_path)
        self.store = JournalStore(self.config)
        self.service = JournalService(self.config, self.store)
        self.first_day = datetime.fromisoformat("2026-08-12T21:05:00+08:00")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_config_preserves_approved_65_day_plan(self) -> None:
        self.assertEqual(self.config.config_version, "1.0-draft.2")
        self.assertEqual(
            (self.config.end_date - self.config.start_date).days + 1,
            65,
        )
        self.assertEqual(self.config.initial_budget, Decimal("10000.00"))

    def test_pristine_journal_is_valid(self) -> None:
        counts = self.service.validate()
        self.assertEqual(
            counts,
            {
                "market_snapshots": 0,
                "decisions": 0,
                "executions": 0,
                "weekly_targets": 0,
            },
        )

    def test_cli_validate_uses_versioned_config(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(
                ["--config", str(self.config_path), "validate"]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("Journal valid", output.getvalue())

    def test_multiple_purchases_rebuild_portfolio(self) -> None:
        first, _ = self.service.record_purchase(
            usd="100",
            btc="0.00100000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        second, state = self.service.record_purchase(
            usd="150.00",
            btc="0.00100000",
            confirm=lambda _: True,
            now=datetime.fromisoformat("2026-08-12T21:06:00+08:00"),
        )

        self.assertNotEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(state.actual_invested_usd, Decimal("250.00"))
        self.assertEqual(state.remaining_funds_usd, Decimal("9750.00"))
        self.assertEqual(state.total_btc, Decimal("0.00200000"))
        self.assertEqual(state.average_cost_usd, Decimal("125000"))
        self.assertEqual(state.actual_invested_today_usd, Decimal("250.00"))
        self.assertEqual(state.actual_invested_this_week_usd, Decimal("250.00"))
        self.assertEqual(state.effective_purchase_count, 2)
        self.assertEqual(self.service.validate()["executions"], 2)
        raw = self.store.paths.datasets["executions"].read_bytes()
        self.assertTrue(raw.endswith(b"\n"))

    def test_confirmation_cancellation_writes_nothing(self) -> None:
        with self.assertRaises(OperationCancelled):
            self.service.record_purchase(
                usd="100.00",
                btc="0.00100000",
                confirm=lambda _: False,
                now=self.first_day,
            )
        self.assertFalse(self.store.paths.datasets["executions"].exists())

    def test_correction_appends_reversal_and_replacement(self) -> None:
        original, _ = self.service.record_purchase(
            usd="100.00",
            btc="0.00100000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        correction, state = self.service.correct_purchase(
            execution_id=original["execution_id"],
            usd="120.00",
            btc="0.00110000",
            confirm=lambda _: True,
            now=datetime.fromisoformat("2026-08-12T21:07:00+08:00"),
        )

        self.assertEqual(correction[0]["event_type"], "reversal")
        self.assertEqual(
            correction[0]["reverses_execution_id"], original["execution_id"]
        )
        self.assertEqual(correction[1]["event_type"], "purchase")
        self.assertEqual(
            correction[0]["operation_id"], correction[1]["operation_id"]
        )
        self.assertEqual(state.actual_invested_usd, Decimal("120.00"))
        self.assertEqual(state.total_btc, Decimal("0.00110000"))
        self.assertEqual(state.effective_purchase_count, 1)
        self.assertEqual(self.service.validate()["executions"], 3)

    def test_purchase_cannot_be_corrected_twice(self) -> None:
        original, _ = self.service.record_purchase(
            usd="100.00",
            btc="0.00100000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        self.service.correct_purchase(
            execution_id=original["execution_id"],
            usd="110.00",
            btc="0.00100000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        with self.assertRaises(UserInputError):
            self.service.correct_purchase(
                execution_id=original["execution_id"],
                usd="120.00",
                btc="0.00100000",
                confirm=lambda _: True,
                now=self.first_day,
            )

    def test_day_close_rules(self) -> None:
        skipped, state = self.service.close_day(
            reason="skipped",
            confirm=lambda _: True,
            now=self.first_day,
        )
        self.assertEqual(skipped["close_reason"], "skipped")
        self.assertEqual(state.latest_day_close_reason, "skipped")

        self.service.record_purchase(
            usd="80.00",
            btc="0.00080000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        state_after_purchase = self.service.portfolio_state(now=self.first_day)
        self.assertIsNone(state_after_purchase.latest_day_close_reason)
        with self.assertRaises(UserInputError):
            self.service.close_day(
                reason="skipped",
                confirm=lambda _: True,
                now=self.first_day,
            )
        completed, state = self.service.close_day(
            reason="completed_for_day",
            confirm=lambda _: True,
            now=self.first_day,
        )
        self.assertEqual(completed["close_reason"], "completed_for_day")
        self.assertEqual(state.latest_day_close_reason, "completed_for_day")

    def test_completed_for_day_requires_purchase(self) -> None:
        with self.assertRaises(UserInputError):
            self.service.close_day(
                reason="completed_for_day",
                confirm=lambda _: True,
                now=self.first_day,
            )

    def test_decimal_precision_is_enforced(self) -> None:
        with self.assertRaises(UserInputError):
            self.service.record_purchase(
                usd="80.001",
                btc="0.00080000",
                confirm=lambda _: True,
                now=self.first_day,
            )
        with self.assertRaises(UserInputError):
            self.service.record_purchase(
                usd="80.00",
                btc="0.000800001",
                confirm=lambda _: True,
                now=self.first_day,
            )

    def test_outside_plan_date_is_rejected(self) -> None:
        with self.assertRaises(UserInputError):
            self.service.record_purchase(
                usd="80.00",
                btc="0.00080000",
                confirm=lambda _: True,
                now=datetime.fromisoformat("2026-08-11T21:05:00+08:00"),
            )

    def test_over_budget_is_recorded_but_validate_reports_invalid(self) -> None:
        _, state = self.service.record_purchase(
            usd="10000.01",
            btc="0.10000000",
            confirm=lambda _: True,
            now=self.first_day,
        )
        self.assertEqual(state.data_status, "invalid")
        self.assertEqual(state.remaining_funds_usd, Decimal("0"))
        with self.assertRaises(JournalValidationError):
            self.service.validate()

    def test_incomplete_jsonl_line_hard_fails(self) -> None:
        self.store.paths.data_dir.mkdir(parents=True)
        self.store.paths.datasets["executions"].write_text(
            '{"schema_version":"execution.v1"}',
            encoding="utf-8",
        )
        with self.assertRaises(JournalValidationError):
            self.service.validate()

    def test_second_writer_cannot_take_lock(self) -> None:
        second_store = JournalStore(self.config)
        with self.store.lock(exclusive=True):
            with self.assertRaises(LockUnavailableError):
                with second_store.lock(exclusive=True):
                    self.fail("second writer unexpectedly acquired the lock")


if __name__ == "__main__":
    unittest.main()
