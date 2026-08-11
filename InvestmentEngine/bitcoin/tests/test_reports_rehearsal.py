from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


BITCOIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BITCOIN_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.cli import build_parser
from bitcoin_dca.config import load_config
from bitcoin_dca.errors import UserInputError
from bitcoin_dca.ledger import JournalService
from bitcoin_dca.providers import HttpClient, MarketDataService
from bitcoin_dca.recommendation import RecommendationService
from bitcoin_dca.rehearsal import FIXED_NOW, _FixtureTransport, run_first_day_rehearsal
from bitcoin_dca.reporting import ReporterService


class ReportsRehearsalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        source = json.loads(
            (BITCOIN_ROOT / "config" / "config.1.0-draft.2.json").read_text(
                encoding="utf-8"
            )
        )
        source["runtime"]["data_dir"] = str(self.workspace / "data")
        source["runtime"]["reports_dir"] = str(self.workspace / "reports")
        source["runtime"]["templates_dir"] = str(BITCOIN_ROOT / "templates")
        source["runtime"]["http_retry_delays_seconds"] = [0, 0]
        config_path = self.workspace / "config.json"
        config_path.write_text(json.dumps(source), encoding="utf-8")
        self.config = load_config(config_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _complete_first_day(self):
        client = HttpClient(
            self.config,
            transport=_FixtureTransport(),
            clock=lambda: FIXED_NOW,
            sleeper=lambda _: None,
        )
        recommendation = RecommendationService(
            self.config,
            market_data=MarketDataService(self.config, client=client, api_key=None),
            environ={},
        ).recommend(now=FIXED_NOW)
        journal = JournalService(self.config)
        purchase, _ = journal.record_purchase(
            usd=recommendation.decision["final_suggested_usd"],
            btc="0.00249086",
            note="report test",
            confirm=lambda _: True,
            now=FIXED_NOW + timedelta(minutes=1),
        )
        journal.close_day(
            reason="completed_for_day",
            confirm=lambda _: True,
            now=FIXED_NOW + timedelta(minutes=2),
        )
        return recommendation, purchase

    def test_reports_are_deterministic_for_the_same_canonical_watermark(self) -> None:
        self._complete_first_day()
        reporter = ReporterService(self.config)
        for kind in ("daily", "weekly", "monthly"):
            first = reporter.generate(kind, reference_date=FIXED_NOW.date(), write=False)
            second = reporter.generate(kind, reference_date=FIXED_NOW.date(), write=False)
            self.assertEqual(first.content, second.content)
            self.assertEqual(first.watermark, second.watermark)
            self.assertEqual(first.generated_at, second.generated_at)
            self.assertNotIn("{{", first.content)

    def test_reports_write_expected_paths_and_derive_effective_execution(self) -> None:
        recommendation, purchase = self._complete_first_day()
        JournalService(self.config).correct_purchase(
            execution_id=purchase["execution_id"],
            usd="180.00",
            btc="0.00250000",
            note="corrected fixture",
            confirm=lambda _: True,
            now=FIXED_NOW + timedelta(minutes=3),
        )
        reporter = ReporterService(self.config)
        daily = reporter.generate("daily", reference_date=FIXED_NOW.date())
        weekly = reporter.generate("weekly", reference_date=FIXED_NOW.date())
        monthly = reporter.generate("monthly", reference_date=FIXED_NOW.date())
        self.assertEqual(daily.output_path, self.config.reports_dir / "daily" / "2026-08-12.md")
        self.assertEqual(weekly.output_path, self.config.reports_dir / "weekly" / "2026-08-12.md")
        self.assertEqual(monthly.output_path, self.config.reports_dir / "monthly" / "2026-08.md")
        self.assertIn("| 實際投入 | `180.00` USD |", daily.content)
        self.assertIn("| 當日人工結束狀態 | `completed_for_day` |", daily.content)
        self.assertNotIn(recommendation.decision["final_suggested_usd"] + "` USD |\n| 使用者註記", daily.content)
        self.assertIn("corrected fixture", daily.content)
        self.assertIn("Reversed／corrected executions：`1`", monthly.content)

    def test_report_rejects_a_reference_date_outside_the_plan(self) -> None:
        for kind, value in (
            ("daily", "2026-08-11"),
            ("weekly", "2026-08-11"),
            ("monthly", "2026-10-16"),
        ):
            with self.subTest(kind=kind), self.assertRaises(UserInputError):
                ReporterService(self.config).generate(
                    kind, reference_date=date.fromisoformat(value)
                )

    def test_first_day_rehearsal_is_complete_and_leaves_formal_store_untouched(self) -> None:
        outcome = run_first_day_rehearsal(self.config)
        self.assertTrue(outcome.formal_journal_unchanged)
        self.assertEqual(outcome.decision_status, "normal")
        self.assertEqual(outcome.execution_status, "executed")
        self.assertEqual(
            outcome.journal_counts,
            {
                "market_snapshots": 1,
                "decisions": 1,
                "executions": 2,
                "weekly_targets": 1,
            },
        )
        self.assertFalse(self.config.data_dir.exists())
        self.assertFalse(self.config.reports_dir.exists())

    def test_cli_exposes_report_and_rehearsal_commands(self) -> None:
        parser = build_parser()
        report = parser.parse_args(["report", "weekly", "--date", "2026-08-12"])
        rehearsal = parser.parse_args(["rehearse-first-day"])
        self.assertEqual((report.command, report.kind), ("report", "weekly"))
        self.assertEqual(rehearsal.command, "rehearse-first-day")


if __name__ == "__main__":
    unittest.main()
