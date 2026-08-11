from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path


BITCOIN_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = BITCOIN_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bitcoin_dca.budget import (
    BudgetGuardResult,
    CapacityResult,
    WeeklyTarget,
    apply_budget_guard,
    calculate_capacity,
    create_weekly_target,
    weekly_min_ratio,
)
from bitcoin_dca.config import load_config
from bitcoin_dca.decision import PortfolioInputs, calculate_decision
from bitcoin_dca.errors import ConfigError, JournalValidationError
from bitcoin_dca.indicators import MarketInputs, calculate_indicators
from bitcoin_dca.validation import validate_journal


class DecisionCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config_path = BITCOIN_ROOT / "config" / "config.1.0-draft.2.json"
        cls.config = load_config(cls.config_path)

    def target(self, plan_date: date, remaining: str = "10000.00") -> WeeklyTarget:
        week_start = plan_date.replace(day=plan_date.day)
        while week_start.weekday() != 0 and week_start > self.config.start_date:
            week_start = week_start.fromordinal(week_start.toordinal() - 1)
        week_start = max(week_start, self.config.start_date)
        return create_weekly_target(
            week_start, Decimal(remaining), self.config
        )

    def portfolio(
        self,
        remaining: str = "10000.00",
        week: str = "0.00",
        today: str = "0.00",
        status: str = "valid",
    ) -> PortfolioInputs:
        return PortfolioInputs(
            remaining_funds_usd=Decimal(remaining),
            actual_invested_this_week_usd=Decimal(week),
            actual_invested_today_usd=Decimal(today),
            data_status=status,
        )

    def strong_market(self) -> MarketInputs:
        return MarketInputs(
            reference_price=Decimal("70"),
            previous_reference_price=Decimal("100"),
            recent_high=Decimal("100"),
            atr=Decimal("10"),
            fear_greed=Decimal("10"),
            bviv=Decimal("100"),
        )

    def test_first_partial_week_target_and_65_day_calendar(self) -> None:
        target = create_weekly_target(
            date(2026, 8, 12), Decimal("10000.00"), self.config
        )
        self.assertEqual(target.week_start, date(2026, 8, 12))
        self.assertEqual(target.week_end, date(2026, 8, 16))
        self.assertEqual(target.active_days_in_week, 5)
        self.assertEqual(target.total_days_remaining, 65)
        self.assertEqual(target.weekly_target_usd, Decimal("769.23"))
        self.assertEqual(target.weekly_min_usd, Decimal("615.39"))
        self.assertEqual(target.weekly_soft_max_usd, Decimal("1000.00"))

    def test_weekly_ratio_accelerates_and_reaches_full_pace(self) -> None:
        self.assertEqual(weekly_min_ratio(21, self.config), Decimal("0.80"))
        self.assertEqual(weekly_min_ratio(14, self.config), Decimal("0.90"))
        self.assertEqual(weekly_min_ratio(7, self.config), Decimal("1.00"))

    def test_shock_uses_max_instead_of_double_counting(self) -> None:
        result = calculate_indicators(
            MarketInputs(
                reference_price=Decimal("94"),
                previous_reference_price=Decimal("100"),
                recent_high=Decimal("100"),
                atr=Decimal("5"),
                fear_greed=Decimal("50"),
                bviv=Decimal("60"),
            ),
            self.config,
        )
        self.assertEqual(
            result.shock_score,
            max(result.atr_drop_score, result.absolute_drop_score),
        )
        self.assertLessEqual(result.shock_score, Decimal("1"))

    def test_high_bviv_suppresses_only_without_downside_gate(self) -> None:
        neutral = calculate_indicators(
            MarketInputs(
                reference_price=Decimal("100"),
                previous_reference_price=Decimal("100"),
                recent_high=Decimal("100"),
                atr=Decimal("5"),
                fear_greed=Decimal("60"),
                bviv=Decimal("100"),
            ),
            self.config,
        )
        downside = calculate_indicators(self.strong_market(), self.config)
        self.assertFalse(neutral.downside_gate)
        self.assertEqual(neutral.bviv_modifier, Decimal("0.90"))
        self.assertTrue(downside.downside_gate)
        self.assertEqual(downside.bviv_modifier, Decimal("1.00"))

    def test_missing_atr_uses_absolute_drop_and_marks_degraded(self) -> None:
        result = calculate_decision(
            plan_date=date(2026, 8, 12),
            market=MarketInputs(
                reference_price=Decimal("90"),
                previous_reference_price=Decimal("100"),
                recent_high=Decimal("100"),
                atr=None,
                fear_greed=Decimal("20"),
                bviv=Decimal("70"),
            ),
            portfolio=self.portfolio(),
            weekly_target=self.target(date(2026, 8, 12)),
            config=self.config,
        )
        self.assertEqual(result.decision_status, "degraded")
        self.assertEqual(
            result.indicators.shock_score,
            result.indicators.absolute_drop_score,
        )
        self.assertIn("SHOCK_ATR_DEGRADED", result.reason_codes)

    def test_two_groups_are_reweighted_and_one_group_is_base_only(self) -> None:
        two_groups = calculate_decision(
            plan_date=date(2026, 8, 12),
            market=MarketInputs(
                reference_price=Decimal("80"),
                previous_reference_price=Decimal("100"),
                recent_high=Decimal("100"),
                atr=Decimal("10"),
                fear_greed=None,
                bviv=None,
            ),
            portfolio=self.portfolio(),
            weekly_target=self.target(date(2026, 8, 12)),
            config=self.config,
        )
        one_group = calculate_decision(
            plan_date=date(2026, 8, 12),
            market=MarketInputs(
                reference_price=Decimal("80"),
                previous_reference_price=None,
                recent_high=Decimal("100"),
                atr=None,
                fear_greed=None,
                bviv=None,
            ),
            portfolio=self.portfolio(),
            weekly_target=self.target(date(2026, 8, 12)),
            config=self.config,
        )
        self.assertEqual(two_groups.decision_status, "degraded")
        self.assertIsNotNone(two_groups.indicators.directional_score)
        self.assertEqual(one_group.decision_status, "base_only")
        self.assertEqual(one_group.market_adaptive_amount_usd, Decimal("0"))

    def test_strong_signal_is_deterministic_and_guarded(self) -> None:
        arguments = dict(
            plan_date=date(2026, 8, 12),
            market=self.strong_market(),
            portfolio=self.portfolio(),
            weekly_target=self.target(date(2026, 8, 12)),
            config=self.config,
        )
        first = calculate_decision(**arguments)
        second = calculate_decision(**arguments)
        encoded_first = json.dumps(
            first.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        encoded_second = json.dumps(
            second.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(encoded_first, encoded_second)
        self.assertEqual(first.decision_status, "normal")
        self.assertEqual(first.indicators.directional_score, Decimal("1"))
        self.assertEqual(first.final_suggested_usd, Decimal("227.69"))

    def test_invalid_btc_or_portfolio_blocks_without_amount(self) -> None:
        target = self.target(date(2026, 8, 12))
        missing_btc = calculate_decision(
            plan_date=date(2026, 8, 12),
            market=MarketInputs(None, None, None, None, None, None),
            portfolio=self.portfolio(),
            weekly_target=target,
            config=self.config,
        )
        invalid_portfolio = calculate_decision(
            plan_date=date(2026, 8, 12),
            market=self.strong_market(),
            portfolio=self.portfolio(status="invalid"),
            weekly_target=target,
            config=self.config,
        )
        self.assertEqual(missing_btc.decision_status, "blocked")
        self.assertIsNone(missing_btc.final_suggested_usd)
        self.assertEqual(invalid_portfolio.decision_status, "blocked")

    def test_capacity_buckets_cover_first_and_last_partial_weeks(self) -> None:
        first = calculate_capacity(
            date(2026, 8, 12), Decimal("10000"), Decimal("0"), self.config
        )
        last = calculate_capacity(
            date(2026, 10, 15), Decimal("900"), Decimal("0"), self.config
        )
        self.assertEqual(first.total_capacity_including_today_usd, Decimal("20000"))
        self.assertTrue(first.plan_feasible)
        self.assertEqual(last.total_capacity_including_today_usd, Decimal("500"))
        self.assertEqual(last.minimum_required_today_usd, Decimal("900"))
        self.assertFalse(last.plan_feasible)

    def test_final_day_never_breaks_daily_hard_cap(self) -> None:
        result = calculate_decision(
            plan_date=date(2026, 10, 15),
            market=self.strong_market(),
            portfolio=self.portfolio(remaining="900.00"),
            weekly_target=create_weekly_target(
                date(2026, 10, 12), Decimal("900.00"), self.config
            ),
            config=self.config,
        )
        self.assertEqual(result.decision_status, "plan_infeasible")
        self.assertEqual(result.final_suggested_usd, Decimal("500.00"))
        self.assertIn("PLAN_INFEASIBLE", result.reason_codes)

    def test_all_65_days_never_exceed_any_financial_hard_limit(self) -> None:
        for ordinal in range(
            self.config.start_date.toordinal(),
            self.config.end_date.toordinal() + 1,
        ):
            plan_date = date.fromordinal(ordinal)
            for remaining in ("0", "50", "500", "2500", "10000"):
                for actual_week in ("0", "1500", "1999", "2500"):
                    result = calculate_decision(
                        plan_date=plan_date,
                        market=self.strong_market(),
                        portfolio=self.portfolio(
                            remaining=remaining, week=actual_week
                        ),
                        weekly_target=self.target(plan_date, remaining),
                        config=self.config,
                    )
                    final = result.final_suggested_usd
                    self.assertLessEqual(final, Decimal(remaining))
                    self.assertLessEqual(final, self.config.daily_hard_max)
                    self.assertLessEqual(
                        final,
                        max(
                            Decimal("0"),
                            self.config.weekly_hard_max
                            - Decimal(actual_week),
                        ),
                    )

    def test_soft_cap_can_be_overridden_only_up_to_hard_cap(self) -> None:
        target = WeeklyTarget(
            week_start=date(2026, 10, 12),
            week_end=date(2026, 10, 15),
            remaining_funds_at_week_start_usd=Decimal("1000"),
            active_days_in_week=4,
            total_days_remaining=4,
            weekly_target_usd=Decimal("1000"),
            weekly_min_ratio=Decimal("1"),
            weekly_min_usd=Decimal("1000"),
            weekly_soft_max_usd=Decimal("200"),
            weekly_hard_max_usd=Decimal("2000"),
        )
        capacity = CapacityResult(
            days_remaining=4,
            active_days_remaining_in_week=4,
            weekly_hard_remaining_usd=Decimal("600"),
            current_week_future_capacity_usd=Decimal("600"),
            future_week_capacity_usd=Decimal("0"),
            total_capacity_including_today_usd=Decimal("600"),
            today_hard_capacity_usd=Decimal("500"),
            minimum_required_today_usd=Decimal("300"),
            plan_feasible=True,
        )
        result = apply_budget_guard(
            plan_date=date(2026, 10, 12),
            remaining_funds=Decimal("600"),
            actual_invested_this_week=Decimal("0"),
            market_amount=Decimal("80"),
            weekly_target=target,
            capacity=capacity,
            config=self.config,
        )
        self.assertTrue(result.soft_cap_overridden_for_feasibility)
        self.assertEqual(result.effective_weekly_soft_remaining_usd, Decimal("300"))
        self.assertEqual(result.final_suggested_usd, Decimal("300.00"))
        self.assertLessEqual(result.final_suggested_usd, self.config.daily_hard_max)
        self.assertLessEqual(
            result.final_suggested_usd, capacity.weekly_hard_remaining_usd
        )

    def test_completed_plan_suggests_zero(self) -> None:
        result = calculate_decision(
            plan_date=date(2026, 10, 15),
            market=self.strong_market(),
            portfolio=self.portfolio(remaining="0.00"),
            weekly_target=create_weekly_target(
                date(2026, 10, 12), Decimal("0"), self.config
            ),
            config=self.config,
        )
        self.assertEqual(result.decision_status, "completed")
        self.assertEqual(result.final_suggested_usd, Decimal("0.00"))

    def test_machine_config_rejects_weight_and_cap_drift(self) -> None:
        source = json.loads(self.config_path.read_text(encoding="utf-8"))
        cases = []
        bad_weight = copy.deepcopy(source)
        bad_weight["factors"]["location"]["weight"] = "0.50"
        cases.append(bad_weight)
        bad_override = copy.deepcopy(source)
        bad_override["budget"]["final_day_override_daily_max"] = True
        cases.append(bad_override)
        with tempfile.TemporaryDirectory() as folder:
            for index, case in enumerate(cases):
                path = Path(folder) / f"bad-{index}.json"
                path.write_text(json.dumps(case), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_journal_validation_rejects_decision_above_hard_cap(self) -> None:
        datasets = {
            "market_snapshots": [
                {
                    "schema_version": "market_snapshot.v1",
                    "snapshot_id": "snapshot-1",
                    "operation_id": "operation-1",
                    "plan_date": "2026-08-12",
                    "cutoff_at": "2026-08-12T21:00:00+08:00",
                    "created_at": "2026-08-12T21:05:00+08:00",
                    "btc_reference": {},
                    "btc_previous_reference": {},
                    "btc_daily_candles": {},
                    "fear_greed": {},
                    "bviv": {},
                    "portfolio_input": {},
                    "quality_summary": {},
                }
            ],
            "weekly_targets": [
                {
                    "schema_version": "weekly_target.v1",
                    "weekly_target_id": "target-1",
                    "weekly_target_key": "2026-08-12",
                    "operation_id": "operation-1",
                    "revision": 1,
                    "supersedes_revision_id": None,
                    "week_start": "2026-08-12",
                    "week_end": "2026-08-16",
                    "created_for_plan_date": "2026-08-12",
                    "created_at": "2026-08-12T21:05:00+08:00",
                    "config_version": "1.0-draft.2",
                    "remaining_funds_at_week_start_usd": "10000.00",
                    "active_days_in_week": 5,
                    "total_days_remaining": 65,
                    "weekly_target_usd": "769.23",
                    "weekly_min_ratio": "0.80000000",
                    "weekly_min_usd": "615.39",
                    "weekly_soft_max_usd": "1000.00",
                    "weekly_hard_max_usd": "2000.00",
                }
            ],
            "decisions": [
                {
                    "schema_version": "decision.v1",
                    "decision_id": "decision-1",
                    "revision_id": "revision-1",
                    "operation_id": "operation-1",
                    "revision": 1,
                    "supersedes_revision_id": None,
                    "plan_date": "2026-08-12",
                    "snapshot_id": "snapshot-1",
                    "weekly_target_id": "target-1",
                    "config_version": "1.0-draft.2",
                    "calculated_at": "2026-08-12T21:05:00+08:00",
                    "decision_status": "normal",
                    "scores": {"directional_score": "0.50000000"},
                    "market_amounts": {"bviv_modifier": "1.00000000"},
                    "pacing": {},
                    "capacity": {
                        "weekly_hard_remaining_usd": "2000.00000000",
                        "today_hard_capacity_usd": "500.00000000",
                    },
                    "final_suggested_usd": "500.01",
                    "reason_codes": [],
                    "reason_summary": "fixture",
                }
            ],
            "executions": [],
        }
        with self.assertRaises(JournalValidationError) as caught:
            validate_journal(datasets, self.config)
        self.assertIn("exceeds daily hard max", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
