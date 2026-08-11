"""Append-only execution ledger and derived portfolio state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Callable
from uuid import uuid4

from .config import RuntimeConfig
from .decimal_utils import canonical_btc, canonical_usd
from .errors import JournalValidationError, OperationCancelled, UserInputError
from .storage import JournalStore
from .validation import validate_journal


ConfirmCallback = Callable[[dict], bool]


@dataclass(frozen=True)
class PortfolioState:
    as_of: datetime
    actual_invested_usd: Decimal
    remaining_funds_usd: Decimal
    total_btc: Decimal
    average_cost_usd: Decimal | None
    actual_invested_today_usd: Decimal
    actual_invested_this_week_usd: Decimal
    effective_purchase_count: int
    data_status: str
    latest_execution_id: str | None
    latest_day_close_reason: str | None

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(timespec="seconds"),
            "actual_invested_usd": canonical_usd(str(self.actual_invested_usd)),
            "remaining_funds_usd": canonical_usd(str(self.remaining_funds_usd)),
            "total_btc": canonical_btc(str(self.total_btc)),
            "average_cost_usd": (
                None
                if self.average_cost_usd is None
                else format(self.average_cost_usd, "f")
            ),
            "actual_invested_today_usd": canonical_usd(
                str(self.actual_invested_today_usd)
            ),
            "actual_invested_this_week_usd": canonical_usd(
                str(self.actual_invested_this_week_usd)
            ),
            "effective_purchase_count": self.effective_purchase_count,
            "data_status": self.data_status,
            "latest_execution_id": self.latest_execution_id,
            "latest_day_close_reason": self.latest_day_close_reason,
        }


def _effective_purchases(executions: list[dict]) -> list[dict]:
    reversed_ids = {
        record["reverses_execution_id"]
        for record in executions
        if record.get("event_type") == "reversal"
    }
    return [
        record
        for record in executions
        if record.get("event_type") == "purchase"
        and record.get("execution_id") not in reversed_ids
    ]


def rebuild_portfolio(
    executions: list[dict], config: RuntimeConfig, as_of: datetime
) -> PortfolioState:
    effective = _effective_purchases(executions)
    total_usd = sum(
        (Decimal(record["usd_amount"]) for record in effective), Decimal("0")
    )
    total_btc = sum(
        (Decimal(record["btc_quantity"]) for record in effective), Decimal("0")
    )
    remaining = config.initial_budget - total_usd
    data_status = "valid"
    if remaining < 0:
        data_status = "invalid"
        remaining = Decimal("0")
    with localcontext() as context:
        context.prec = 28
        average_cost = None if total_btc == 0 else total_usd / total_btc

    today = as_of.astimezone(config.timezone).date()
    week_start = today - timedelta(days=today.weekday())
    today_usd = sum(
        (
            Decimal(record["usd_amount"])
            for record in effective
            if record["plan_date"] == today.isoformat()
        ),
        Decimal("0"),
    )
    week_usd = sum(
        (
            Decimal(record["usd_amount"])
            for record in effective
            if week_start <= date.fromisoformat(record["plan_date"]) <= today
        ),
        Decimal("0"),
    )
    latest_execution_id = executions[-1]["execution_id"] if executions else None
    latest_close = None
    for record in executions:
        if record.get("plan_date") != today.isoformat():
            continue
        if record.get("event_type") == "day_close":
            latest_close = record.get("close_reason")
        elif record.get("event_type") == "purchase" and record in effective:
            latest_close = None
    return PortfolioState(
        as_of=as_of,
        actual_invested_usd=total_usd,
        remaining_funds_usd=remaining,
        total_btc=total_btc,
        average_cost_usd=average_cost,
        actual_invested_today_usd=today_usd,
        actual_invested_this_week_usd=week_usd,
        effective_purchase_count=len(effective),
        data_status=data_status,
        latest_execution_id=latest_execution_id,
        latest_day_close_reason=latest_close,
    )


def _current_decision_revision(decisions: list[dict], plan_date: str) -> str | None:
    matching = [record for record in decisions if record.get("plan_date") == plan_date]
    if not matching:
        return None
    superseded = {
        record["supersedes_revision_id"]
        for record in matching
        if record.get("supersedes_revision_id") is not None
    }
    leaves = [record for record in matching if record.get("revision_id") not in superseded]
    if len(leaves) != 1:
        return None
    return leaves[0]["revision_id"]


class JournalService:
    def __init__(self, config: RuntimeConfig, store: JournalStore | None = None):
        self.config = config
        self.store = store or JournalStore(config)

    def _now(self, supplied: datetime | None = None) -> datetime:
        value = supplied or datetime.now(self.config.timezone)
        if value.tzinfo is None or value.utcoffset() is None:
            raise UserInputError("operation time must include a UTC offset")
        return value.astimezone(self.config.timezone)

    def _ensure_plan_date(self, value: date) -> None:
        if value < self.config.start_date or value > self.config.end_date:
            raise UserInputError(
                f"plan date {value.isoformat()} is outside "
                f"{self.config.start_date.isoformat()}..{self.config.end_date.isoformat()}"
            )

    @staticmethod
    def _validate_candidate(
        datasets: dict[str, list[dict]],
        candidate_records: list[dict],
        config: RuntimeConfig,
    ) -> None:
        prospective = {name: list(records) for name, records in datasets.items()}
        prospective["executions"].extend(candidate_records)
        validate_journal(prospective, config)

    def validate(self) -> dict[str, int]:
        with self.store.lock(exclusive=False):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            state = rebuild_portfolio(
                datasets["executions"],
                self.config,
                datetime.now(self.config.timezone),
            )
            if state.data_status != "valid":
                raise JournalValidationError(
                    ["PortfolioState is invalid: actual investment exceeds initial budget"]
                )
        return {name: len(records) for name, records in datasets.items()}

    def portfolio_state(self, *, now: datetime | None = None) -> PortfolioState:
        operation_time = self._now(now)
        with self.store.lock(exclusive=False):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            return rebuild_portfolio(
                datasets["executions"], self.config, operation_time
            )

    def record_purchase(
        self,
        *,
        usd: str,
        btc: str,
        confirm: ConfirmCallback,
        now: datetime | None = None,
        note: str | None = None,
    ) -> tuple[dict, PortfolioState]:
        operation_time = self._now(now)
        plan_date = operation_time.date()
        self._ensure_plan_date(plan_date)
        usd_value = canonical_usd(usd, positive=True)
        btc_value = canonical_btc(btc, positive=True)
        with localcontext() as context:
            context.prec = 28
            effective_price = Decimal(usd_value) / Decimal(btc_value)

        with self.store.lock(exclusive=True):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            operation_id = str(uuid4())
            timestamp = operation_time.isoformat(timespec="seconds")
            record = {
                "schema_version": "execution.v1",
                "execution_id": str(uuid4()),
                "operation_id": operation_id,
                "event_type": "purchase",
                "plan_date": plan_date.isoformat(),
                "decision_revision_id": _current_decision_revision(
                    datasets["decisions"], plan_date.isoformat()
                ),
                "executed_at": timestamp,
                "recorded_at": timestamp,
                "usd_amount": usd_value,
                "btc_quantity": btc_value,
                "venue": "unknown",
                "external_reference": None,
                "reverses_execution_id": None,
                "source": "manual",
                "close_reason": None,
                "note": note,
            }
            preview = {
                "action": "record_purchase",
                "plan_date": record["plan_date"],
                "usd_amount": usd_value,
                "btc_quantity": btc_value,
                "derived_effective_price_usd": format(effective_price, ".8f"),
            }
            if not confirm(preview):
                raise OperationCancelled("purchase was not confirmed")
            self._validate_candidate(datasets, [record], self.config)
            self.store.append_records("executions", [record])
            updated = {name: list(records) for name, records in datasets.items()}
            updated["executions"].append(record)
            state = rebuild_portfolio(updated["executions"], self.config, operation_time)
            return record, state

    def close_day(
        self,
        *,
        reason: str,
        confirm: ConfirmCallback,
        now: datetime | None = None,
        note: str | None = None,
    ) -> tuple[dict, PortfolioState]:
        if reason not in {"skipped", "completed_for_day"}:
            raise UserInputError("close-day reason must be skipped or completed_for_day")
        operation_time = self._now(now)
        plan_date = operation_time.date()
        self._ensure_plan_date(plan_date)
        with self.store.lock(exclusive=True):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            current_state = rebuild_portfolio(
                datasets["executions"], self.config, operation_time
            )
            if reason == "skipped" and current_state.actual_invested_today_usd > 0:
                raise UserInputError("cannot mark a day with purchases as skipped")
            if (
                reason == "completed_for_day"
                and current_state.actual_invested_today_usd <= 0
            ):
                raise UserInputError(
                    "completed_for_day requires at least one effective purchase"
                )
            timestamp = operation_time.isoformat(timespec="seconds")
            record = {
                "schema_version": "execution.v1",
                "execution_id": str(uuid4()),
                "operation_id": str(uuid4()),
                "event_type": "day_close",
                "plan_date": plan_date.isoformat(),
                "decision_revision_id": _current_decision_revision(
                    datasets["decisions"], plan_date.isoformat()
                ),
                "executed_at": timestamp,
                "recorded_at": timestamp,
                "usd_amount": None,
                "btc_quantity": None,
                "venue": "unknown",
                "external_reference": None,
                "reverses_execution_id": None,
                "source": "manual",
                "close_reason": reason,
                "note": note,
            }
            preview = {
                "action": "close_day",
                "plan_date": record["plan_date"],
                "close_reason": reason,
            }
            if not confirm(preview):
                raise OperationCancelled("day close was not confirmed")
            self._validate_candidate(datasets, [record], self.config)
            self.store.append_records("executions", [record])
            updated = {name: list(records) for name, records in datasets.items()}
            updated["executions"].append(record)
            state = rebuild_portfolio(updated["executions"], self.config, operation_time)
            return record, state

    def correct_purchase(
        self,
        *,
        execution_id: str,
        usd: str,
        btc: str,
        confirm: ConfirmCallback,
        now: datetime | None = None,
        note: str | None = None,
    ) -> tuple[list[dict], PortfolioState]:
        if not execution_id:
            raise UserInputError("execution_id is required")
        operation_time = self._now(now)
        usd_value = canonical_usd(usd, positive=True)
        btc_value = canonical_btc(btc, positive=True)
        with self.store.lock(exclusive=True):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            original = next(
                (
                    record
                    for record in datasets["executions"]
                    if record.get("execution_id") == execution_id
                    and record.get("event_type") == "purchase"
                ),
                None,
            )
            if original is None:
                raise UserInputError("execution_id does not reference a purchase")
            already_reversed = any(
                record.get("event_type") == "reversal"
                and record.get("reverses_execution_id") == execution_id
                for record in datasets["executions"]
            )
            if already_reversed:
                raise UserInputError("purchase has already been reversed")

            operation_id = str(uuid4())
            timestamp = operation_time.isoformat(timespec="seconds")
            reversal = {
                "schema_version": "execution.v1",
                "execution_id": str(uuid4()),
                "operation_id": operation_id,
                "event_type": "reversal",
                "plan_date": original["plan_date"],
                "decision_revision_id": original.get("decision_revision_id"),
                "executed_at": timestamp,
                "recorded_at": timestamp,
                "usd_amount": original["usd_amount"],
                "btc_quantity": original["btc_quantity"],
                "venue": original.get("venue", "unknown"),
                "external_reference": None,
                "reverses_execution_id": original["execution_id"],
                "source": "manual",
                "close_reason": None,
                "note": f"Correction reversal: {note}" if note else "Correction reversal",
            }
            replacement = {
                "schema_version": "execution.v1",
                "execution_id": str(uuid4()),
                "operation_id": operation_id,
                "event_type": "purchase",
                "plan_date": original["plan_date"],
                "decision_revision_id": original.get("decision_revision_id"),
                "executed_at": original["executed_at"],
                "recorded_at": timestamp,
                "usd_amount": usd_value,
                "btc_quantity": btc_value,
                "venue": original.get("venue", "unknown"),
                "external_reference": None,
                "reverses_execution_id": None,
                "source": "manual",
                "close_reason": None,
                "note": note,
            }
            preview = {
                "action": "correct_purchase",
                "plan_date": original["plan_date"],
                "original_execution_id": execution_id,
                "old_usd_amount": original["usd_amount"],
                "old_btc_quantity": original["btc_quantity"],
                "new_usd_amount": usd_value,
                "new_btc_quantity": btc_value,
            }
            if not confirm(preview):
                raise OperationCancelled("purchase correction was not confirmed")
            candidates = [reversal, replacement]
            self._validate_candidate(datasets, candidates, self.config)
            self.store.append_records("executions", candidates)
            updated = {name: list(records) for name, records in datasets.items()}
            updated["executions"].extend(candidates)
            state = rebuild_portfolio(updated["executions"], self.config, operation_time)
            return candidates, state
