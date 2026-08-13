"""Canonical recommend workflow for Gate 4A-3."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from .budget import WeeklyTarget, clipped_week, create_weekly_target
from .config import RuntimeConfig
from .decimal_utils import canonical_usd
from .decision import PortfolioInputs, calculate_decision
from .errors import UserInputError
from .ledger import rebuild_portfolio
from .providers import MarketDataBundle, MarketDataService
from .storage import JournalStore
from .validation import validate_journal


@dataclass(frozen=True)
class RecommendationOutcome:
    snapshot: dict
    decision: dict
    weekly_target: dict
    created_weekly_target: bool
    reused_orphan_snapshot: bool

    @property
    def exit_code(self) -> int:
        return 2 if self.decision["decision_status"] in {"blocked", "plan_infeasible"} else 0


def _current_leaf(records: list[dict], id_field: str) -> dict | None:
    if not records:
        return None
    superseded = {
        record["supersedes_revision_id"]
        for record in records
        if record.get("supersedes_revision_id") is not None
    }
    leaves = [record for record in records if record.get(id_field) not in superseded]
    return leaves[0] if len(leaves) == 1 else None


def _weekly_from_record(record: dict) -> WeeklyTarget:
    return WeeklyTarget(
        week_start=date.fromisoformat(record["week_start"]),
        week_end=date.fromisoformat(record["week_end"]),
        remaining_funds_at_week_start_usd=Decimal(
            record["remaining_funds_at_week_start_usd"]
        ),
        active_days_in_week=record["active_days_in_week"],
        total_days_remaining=record["total_days_remaining"],
        weekly_target_usd=Decimal(record["weekly_target_usd"]),
        weekly_min_ratio=Decimal(record["weekly_min_ratio"]),
        weekly_min_usd=Decimal(record["weekly_min_usd"]),
        weekly_soft_max_usd=Decimal(record["weekly_soft_max_usd"]),
        weekly_hard_max_usd=Decimal(record["weekly_hard_max_usd"]),
    )


def _weekly_record(
    target: WeeklyTarget,
    *,
    operation_id: str,
    created_for_plan_date: date,
    created_at: datetime,
    config: RuntimeConfig,
) -> dict:
    return {
        "schema_version": "weekly_target.v1",
        "weekly_target_id": str(uuid4()),
        "operation_id": operation_id,
        "weekly_target_key": target.week_start.isoformat(),
        "revision": 1,
        "supersedes_revision_id": None,
        "week_start": target.week_start.isoformat(),
        "week_end": target.week_end.isoformat(),
        "created_for_plan_date": created_for_plan_date.isoformat(),
        "created_at": created_at.isoformat(timespec="seconds"),
        "config_version": config.config_version,
        "remaining_funds_at_week_start_usd": canonical_usd(
            str(target.remaining_funds_at_week_start_usd)
        ),
        "active_days_in_week": target.active_days_in_week,
        "total_days_remaining": target.total_days_remaining,
        "weekly_target_usd": canonical_usd(str(target.weekly_target_usd)),
        "weekly_min_ratio": format(target.weekly_min_ratio, ".8f"),
        "weekly_min_usd": canonical_usd(str(target.weekly_min_usd)),
        "weekly_soft_max_usd": canonical_usd(str(target.weekly_soft_max_usd)),
        "weekly_hard_max_usd": canonical_usd(str(target.weekly_hard_max_usd)),
    }


def _unique_codes(*groups: tuple[str, ...] | list[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for code in group:
            if code not in result:
                result.append(code)
    return result


def _snapshot_signature(record: dict) -> dict:
    excluded = {"snapshot_id", "operation_id", "created_at"}
    return {
        key: _without_fetch_metadata(value)
        for key, value in record.items()
        if key not in excluded
    }


def _without_fetch_metadata(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_fetch_metadata(item)
            for key, item in value.items()
            if key not in {"fetched_at", "available_at", "request_descriptor"}
        }
    if isinstance(value, list):
        return [_without_fetch_metadata(item) for item in value]
    return value


class RecommendationService:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        store: JournalStore | None = None,
        market_data: MarketDataService | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.config = config
        self.store = store or JournalStore(config)
        environment = os.environ if environ is None else environ
        self.market_data = market_data or MarketDataService(
            config,
            api_key=environment.get(config.volmex_api_key_env),
        )

    def _now(self, supplied: datetime | None) -> datetime:
        value = supplied or datetime.now(self.config.timezone)
        if value.tzinfo is None or value.utcoffset() is None:
            raise UserInputError("recommend time must include a UTC offset")
        return value.astimezone(self.config.timezone)

    def _window(self, operation_time: datetime) -> datetime:
        plan_date = operation_time.date()
        if not self.config.start_date <= plan_date <= self.config.end_date:
            raise UserInputError("today is outside the approved DCA plan")
        local_clock = operation_time.timetz().replace(tzinfo=None)
        if local_clock < self.config.cutoff_time:
            raise UserInputError("recommend is allowed only at or after 21:00 Asia/Taipei")
        return datetime.combine(
            plan_date,
            self.config.cutoff_time,
            tzinfo=self.config.timezone,
        )

    @staticmethod
    def _prospective(
        datasets: dict[str, list[dict]], dataset: str, record: dict
    ) -> dict[str, list[dict]]:
        result = {name: list(records) for name, records in datasets.items()}
        result[dataset].append(record)
        return result

    def _get_or_create_weekly_target(
        self,
        *,
        datasets: dict[str, list[dict]],
        operation_id: str,
        operation_time: datetime,
        remaining_funds: Decimal,
        actual_invested_this_week: Decimal,
    ) -> tuple[dict, bool, dict[str, list[dict]]]:
        plan_date = operation_time.date()
        week_start, _ = clipped_week(plan_date, self.config)
        key = week_start.isoformat()
        matching = [
            record
            for record in datasets["weekly_targets"]
            if record.get("weekly_target_key") == key
        ]
        current = _current_leaf(matching, "weekly_target_id")
        if current is not None:
            return current, False, datasets

        remaining_at_week_start = remaining_funds + actual_invested_this_week
        target = create_weekly_target(
            week_start,
            remaining_at_week_start,
            self.config,
        )
        record = _weekly_record(
            target,
            operation_id=operation_id,
            created_for_plan_date=plan_date,
            created_at=operation_time,
            config=self.config,
        )
        prospective = self._prospective(datasets, "weekly_targets", record)
        validate_journal(prospective, self.config)
        self.store.append_records("weekly_targets", [record])
        return record, True, prospective

    def _snapshot_record(
        self,
        *,
        operation_id: str,
        operation_time: datetime,
        cutoff: datetime,
        bundle: MarketDataBundle,
        portfolio,
    ) -> dict:
        return {
            "schema_version": "market_snapshot.v1",
            "snapshot_id": str(uuid4()),
            "operation_id": operation_id,
            "config_version": self.config.config_version,
            "plan_date": cutoff.astimezone(self.config.timezone).date().isoformat(),
            "cutoff_at": cutoff.isoformat(timespec="seconds"),
            "created_at": operation_time.isoformat(timespec="seconds"),
            "btc_reference": bundle.btc_reference,
            "btc_previous_reference": bundle.btc_previous_reference,
            "btc_daily_candles": bundle.btc_daily_candles,
            "fear_greed": bundle.fear_greed,
            "bviv": bundle.bviv,
            "portfolio_input": {
                "as_of_execution_id": portfolio.latest_execution_id,
                "actual_invested_usd": canonical_usd(
                    str(portfolio.actual_invested_usd)
                ),
                "remaining_funds_usd": canonical_usd(
                    str(portfolio.remaining_funds_usd)
                ),
                "actual_invested_this_week_usd": canonical_usd(
                    str(portfolio.actual_invested_this_week_usd)
                ),
                "actual_invested_today_usd": canonical_usd(
                    str(portfolio.actual_invested_today_usd)
                ),
                "data_status": portfolio.data_status,
            },
            "quality_summary": {
                "status": bundle.quality_status,
                "reason_codes": list(bundle.reason_codes),
            },
        }

    def _reuse_or_append_snapshot(
        self,
        datasets: dict[str, list[dict]],
        candidate: dict,
    ) -> tuple[dict, bool, dict[str, list[dict]]]:
        referenced = {
            decision.get("snapshot_id") for decision in datasets["decisions"]
        }
        signature = _snapshot_signature(candidate)
        orphan = next(
            (
                snapshot
                for snapshot in reversed(datasets["market_snapshots"])
                if snapshot.get("snapshot_id") not in referenced
                and _snapshot_signature(snapshot) == signature
            ),
            None,
        )
        if orphan is not None:
            return orphan, True, datasets
        prospective = self._prospective(datasets, "market_snapshots", candidate)
        validate_journal(prospective, self.config)
        self.store.append_records("market_snapshots", [candidate])
        return candidate, False, prospective

    def _decision_record(
        self,
        *,
        datasets: dict[str, list[dict]],
        snapshot: dict,
        weekly_target: dict,
        operation_time: datetime,
        bundle: MarketDataBundle,
        portfolio,
    ) -> dict:
        plan_date_string = snapshot["plan_date"]
        plan_date_value = date.fromisoformat(plan_date_string)
        matching = [
            record
            for record in datasets["decisions"]
            if record.get("plan_date") == plan_date_string
        ]
        current = _current_leaf(matching, "revision_id")
        revision = 1 if current is None else current["revision"] + 1
        decision_id = str(uuid4()) if current is None else current["decision_id"]
        target = _weekly_from_record(weekly_target)
        result = calculate_decision(
            plan_date=plan_date_value,
            market=bundle.market_inputs,
            portfolio=PortfolioInputs(
                remaining_funds_usd=portfolio.remaining_funds_usd,
                actual_invested_this_week_usd=portfolio.actual_invested_this_week_usd,
                actual_invested_today_usd=portfolio.actual_invested_today_usd,
                data_status=portfolio.data_status,
            ),
            weekly_target=target,
            config=self.config,
        )
        computed = result.as_dict()
        reasons = _unique_codes(bundle.reason_codes, list(result.reason_codes))
        return {
            "schema_version": "decision.v1",
            "decision_id": decision_id,
            "revision_id": str(uuid4()),
            "operation_id": snapshot["operation_id"],
            "revision": revision,
            "supersedes_revision_id": (
                None if current is None else current["revision_id"]
            ),
            "plan_date": plan_date_string,
            "snapshot_id": snapshot["snapshot_id"],
            "weekly_target_id": weekly_target["weekly_target_id"],
            "config_version": self.config.config_version,
            "calculated_at": operation_time.isoformat(timespec="seconds"),
            "decision_status": result.decision_status,
            "scores": computed["scores"],
            "market_amounts": computed["market_amounts"],
            "pacing": computed["pacing"],
            "capacity": computed["capacity"],
            "final_suggested_usd": computed["final_suggested_usd"],
            "remaining_to_execute_today_usd": computed[
                "remaining_to_execute_today_usd"
            ],
            "reason_codes": reasons,
            "reason_summary": result.reason_summary + " Draft parameters; not a trade.",
        }

    def recommend(self, *, now: datetime | None = None) -> RecommendationOutcome:
        operation_time = self._now(now)
        cutoff = self._window(operation_time)
        operation_id = str(uuid4())
        with self.store.lock(exclusive=True):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            portfolio = rebuild_portfolio(
                datasets["executions"], self.config, operation_time
            )
            weekly_record, created_weekly, datasets = self._get_or_create_weekly_target(
                datasets=datasets,
                operation_id=operation_id,
                operation_time=operation_time,
                remaining_funds=portfolio.remaining_funds_usd,
                actual_invested_this_week=portfolio.actual_invested_this_week_usd,
            )
            bundle = self.market_data.collect(cutoff)
            calculation_time = operation_time if now is not None else self._now(None)
            candidate = self._snapshot_record(
                operation_id=operation_id,
                operation_time=calculation_time,
                cutoff=cutoff,
                bundle=bundle,
                portfolio=portfolio,
            )
            snapshot, reused, datasets = self._reuse_or_append_snapshot(
                datasets, candidate
            )
            decision = self._decision_record(
                datasets=datasets,
                snapshot=snapshot,
                weekly_target=weekly_record,
                operation_time=calculation_time,
                bundle=bundle,
                portfolio=portfolio,
            )
            prospective = self._prospective(datasets, "decisions", decision)
            validate_journal(prospective, self.config)
            self.store.append_records("decisions", [decision])
            return RecommendationOutcome(
                snapshot=snapshot,
                decision=decision,
                weekly_target=weekly_record,
                created_weekly_target=created_weekly,
                reused_orphan_snapshot=reused,
            )
