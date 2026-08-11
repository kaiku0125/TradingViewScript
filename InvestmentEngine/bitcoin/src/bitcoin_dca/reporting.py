"""Deterministic Markdown reports derived only from canonical Journal records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .budget import clipped_week
from .config import RuntimeConfig
from .errors import UserInputError
from .storage import JournalStore
from .validation import validate_journal


ZERO = Decimal("0")


@dataclass(frozen=True)
class ReportResult:
    kind: str
    period_start: date
    period_end: date
    watermark: str
    generated_at: str
    content: str
    output_path: Path | None


def _usd(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return format(value.quantize(Decimal("0.01")), "f")


def _btc(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return format(value.quantize(Decimal("0.00000001")), "f")


def _ratio(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return format(value.quantize(Decimal("0.00000001")), "f")


def _value(mapping: object, key: str, default: object = None) -> object:
    return mapping.get(key, default) if isinstance(mapping, dict) else default


def _future_capacity(capacity: object) -> str:
    if not isinstance(capacity, dict):
        return "N/A"
    current = capacity.get("current_week_future_capacity_usd")
    future = capacity.get("future_week_capacity_usd")
    if current is None or future is None:
        return "N/A"
    return _usd(Decimal(current) + Decimal(future))


def _current_by(records: list[dict], group_field: str, id_field: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        group = record.get(group_field)
        if isinstance(group, str):
            groups.setdefault(group, []).append(record)
    result: dict[str, dict] = {}
    for group, members in groups.items():
        superseded = {
            record["supersedes_revision_id"]
            for record in members
            if record.get("supersedes_revision_id") is not None
        }
        leaves = [record for record in members if record.get(id_field) not in superseded]
        if len(leaves) == 1:
            result[group] = leaves[0]
    return result


def _effective_purchases(executions: list[dict]) -> list[dict]:
    reversed_ids = {
        record.get("reverses_execution_id")
        for record in executions
        if record.get("event_type") == "reversal"
    }
    return [
        record
        for record in executions
        if record.get("event_type") == "purchase"
        and record.get("execution_id") not in reversed_ids
    ]


def _sum_purchases(records: list[dict]) -> tuple[Decimal, Decimal]:
    usd = sum((Decimal(record["usd_amount"]) for record in records), ZERO)
    btc = sum((Decimal(record["btc_quantity"]) for record in records), ZERO)
    return usd, btc


def _days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _execution_status(
    *,
    decision: dict | None,
    actual_usd: Decimal,
    close_reason: str | None,
    remaining_budget: Decimal,
) -> str:
    if remaining_budget <= 0:
        return "completed"
    if decision is None:
        return "no_decision"
    if decision.get("decision_status") == "blocked":
        return "blocked"
    suggested = decision.get("final_suggested_usd")
    if suggested is None:
        return "blocked"
    suggested_value = Decimal(suggested)
    if actual_usd == 0 and close_reason == "skipped":
        return "skipped"
    if actual_usd == 0:
        return "pending"
    if actual_usd < suggested_value:
        return "partially_executed"
    if actual_usd == suggested_value:
        return "executed"
    return "over_executed"


def _latest_close(executions: list[dict], plan_date: date) -> str | None:
    result = None
    correction_operations = {
        record.get("operation_id")
        for record in executions
        if record.get("event_type") == "reversal"
    }
    for record in executions:
        if record.get("plan_date") != plan_date.isoformat():
            continue
        if record.get("event_type") == "day_close":
            result = record.get("close_reason")
        elif (
            record.get("event_type") == "purchase"
            and record.get("operation_id") not in correction_operations
        ):
            result = None
    return result


def _included_records(
    datasets: dict[str, list[dict]], start: date, end: date
) -> dict[str, list[dict]]:
    decisions = [
        record
        for record in datasets["decisions"]
        if start <= date.fromisoformat(record["plan_date"]) <= end
    ]
    snapshot_ids = {record["snapshot_id"] for record in decisions}
    snapshots = [
        record
        for record in datasets["market_snapshots"]
        if record.get("snapshot_id") in snapshot_ids
    ]
    executions = [
        record
        for record in datasets["executions"]
        if date.fromisoformat(record["plan_date"]) <= end
    ]
    targets = [
        record
        for record in datasets["weekly_targets"]
        if date.fromisoformat(record["week_start"]) <= end
        and date.fromisoformat(record["week_end"]) >= start
    ]
    return {
        "market_snapshots": snapshots,
        "decisions": decisions,
        "executions": executions,
        "weekly_targets": targets,
    }


def _watermark(records: dict[str, list[dict]]) -> tuple[str, str]:
    payload = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    watermark = "sha256:" + hashlib.sha256(payload).hexdigest()
    timestamps: list[str] = []
    for record in records["market_snapshots"]:
        timestamps.append(record["created_at"])
    for record in records["decisions"]:
        timestamps.append(record["calculated_at"])
    for record in records["executions"]:
        timestamps.append(record["recorded_at"])
    for record in records["weekly_targets"]:
        timestamps.append(record["created_at"])
    generated_at = max(timestamps) if timestamps else "N/A"
    return watermark, generated_at


def _replace(template: str, values: dict[str, object]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", str(value))
    if "{{" in result or "}}" in result:
        unresolved = sorted(
            {part.split("}}", 1)[0] for part in result.split("{{")[1:]}
        )
        raise ValueError(f"unresolved report placeholders: {', '.join(unresolved)}")
    return result


class ReporterService:
    def __init__(self, config: RuntimeConfig, store: JournalStore | None = None):
        self.config = config
        self.store = store or JournalStore(config)

    def _read(self) -> dict[str, list[dict]]:
        with self.store.lock(exclusive=False):
            datasets = self.store.read_all()
            validate_journal(datasets, self.config)
            return datasets

    def _template(self, name: str) -> str:
        return (self.config.templates_dir / name).read_text(encoding="utf-8")

    def _write(
        self, kind: str, filename: str, content: str, *, write: bool
    ) -> Path | None:
        if not write:
            return None
        folder = self.config.reports_dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        path.write_text(content, encoding="utf-8")
        return path

    def _period(self, kind: str, reference_date: date) -> tuple[date, date]:
        if not self.config.start_date <= reference_date <= self.config.end_date:
            raise UserInputError("report reference date is outside the approved DCA plan")
        if kind == "daily":
            start = end = reference_date
        elif kind == "weekly":
            start, end = clipped_week(reference_date, self.config)
        elif kind == "monthly":
            month_start = reference_date.replace(day=1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            start = max(month_start, self.config.start_date)
            end = min(next_month - timedelta(days=1), self.config.end_date)
        else:
            raise UserInputError("report kind must be daily, weekly, or monthly")
        if start < self.config.start_date or end > self.config.end_date or start > end:
            raise UserInputError("report period is outside the approved DCA plan")
        return start, end

    def generate(
        self,
        kind: str,
        *,
        reference_date: date | None = None,
        write: bool = True,
    ) -> ReportResult:
        reference = reference_date or datetime.now(self.config.timezone).date()
        start, end = self._period(kind, reference)
        datasets = self._read()
        if kind == "daily":
            content, watermark, generated_at = self._daily(datasets, start)
            filename = f"{start.isoformat()}.md"
        elif kind == "weekly":
            content, watermark, generated_at = self._weekly(datasets, start, end)
            filename = f"{start.isoformat()}.md"
        else:
            content, watermark, generated_at = self._monthly(datasets, start, end)
            filename = f"{start.strftime('%Y-%m')}.md"
        output_path = self._write(kind, filename, content, write=write)
        return ReportResult(
            kind=kind,
            period_start=start,
            period_end=end,
            watermark=watermark,
            generated_at=generated_at,
            content=content,
            output_path=output_path,
        )

    def _context(self, datasets: dict[str, list[dict]], start: date, end: date):
        decisions = _current_by(datasets["decisions"], "plan_date", "revision_id")
        targets = _current_by(
            datasets["weekly_targets"], "weekly_target_key", "weekly_target_id"
        )
        snapshots = {
            record["snapshot_id"]: record for record in datasets["market_snapshots"]
        }
        effective = _effective_purchases(datasets["executions"])
        included = _included_records(datasets, start, end)
        watermark, generated_at = _watermark(included)
        return decisions, targets, snapshots, effective, watermark, generated_at

    def _portfolio_at(self, purchases: list[dict], end: date):
        selected = [
            record
            for record in purchases
            if date.fromisoformat(record["plan_date"]) <= end
        ]
        usd, btc = _sum_purchases(selected)
        remaining = max(ZERO, self.config.initial_budget - usd)
        average = None if btc == 0 else usd / btc
        return usd, btc, remaining, average

    def _daily(self, datasets: dict[str, list[dict]], plan_date: date):
        decisions, _, snapshots, effective, watermark, generated_at = self._context(
            datasets, plan_date, plan_date
        )
        key = plan_date.isoformat()
        decision = decisions.get(key)
        snapshot = snapshots.get(decision.get("snapshot_id")) if decision else None
        purchases = [record for record in effective if record["plan_date"] == key]
        actual_usd, actual_btc = _sum_purchases(purchases)
        cumulative_usd, cumulative_btc, remaining, cumulative_average = self._portfolio_at(
            effective, plan_date
        )
        week_start, _ = clipped_week(plan_date, self.config)
        week_purchases = [
            record
            for record in effective
            if week_start <= date.fromisoformat(record["plan_date"]) <= plan_date
        ]
        week_usd, _ = _sum_purchases(week_purchases)
        close_reason = _latest_close(datasets["executions"], plan_date)
        status = _execution_status(
            decision=decision,
            actual_usd=actual_usd,
            close_reason=close_reason,
            remaining_budget=remaining,
        )
        suggested = (
            None
            if decision is None or decision.get("final_suggested_usd") is None
            else Decimal(decision["final_suggested_usd"])
        )
        variance = None if suggested is None else actual_usd - suggested
        average_today = None if actual_btc == 0 else actual_usd / actual_btc
        revisions = [r for r in datasets["decisions"] if r.get("plan_date") == key]
        market = decision.get("market_amounts", {}) if decision else {}
        pacing = decision.get("pacing", {}) if decision else {}
        capacity = decision.get("capacity", {}) if decision else {}
        scores = decision.get("scores", {}) if decision else {}
        portfolio_input = snapshot.get("portfolio_input", {}) if snapshot else {}
        reference = snapshot.get("btc_reference", {}) if snapshot else {}
        daily_data = snapshot.get("btc_daily_candles", {}) if snapshot else {}
        fear = snapshot.get("fear_greed", {}) if snapshot else {}
        bviv = snapshot.get("bviv", {}) if snapshot else {}
        execution_rows = "\n".join(
            "| {executed_at} | {venue} | {usd} | {btc} | {price} | {execution_id} |".format(
                executed_at=record["executed_at"],
                venue=record["venue"],
                usd=record["usd_amount"],
                btc=record["btc_quantity"],
                price=_usd(Decimal(record["usd_amount"]) / Decimal(record["btc_quantity"])),
                execution_id=record["execution_id"],
            )
            for record in purchases
        ) or "| — | — | — | — | — | — |"
        template = self._template("DAILY_JOURNAL.md")
        template_row = "| `{{executed_at}}` | `{{venue}}` | `{{usd_amount}}` | `{{btc_quantity}}` | `{{derived_effective_price_usd}}` | `{{execution_id}}` |"
        template = template.replace(template_row, execution_rows)
        values = {
            "plan_date": key,
            "cutoff_at": _value(snapshot, "cutoff_at", "N/A"),
            "calculated_at": _value(decision, "calculated_at", "N/A"),
            "generated_at": generated_at,
            "decision_status": _value(decision, "decision_status", "no_decision"),
            "execution_status": status,
            "config_version": _value(decision, "config_version", "N/A"),
            "revision": _value(decision, "revision", "N/A"),
            "revision_count": len(revisions),
            "snapshot_id": _value(decision, "snapshot_id", "N/A"),
            "base_usd": _value(market, "base_amount_usd", "N/A"),
            "adaptive_usd": _value(market, "market_adaptive_amount_usd", "N/A"),
            "market_amount_usd": _value(market, "market_amount_usd", "N/A"),
            "pace_floor_usd": _value(pacing, "pace_floor_usd", "N/A"),
            "weekly_catchup_usd": _value(pacing, "weekly_catchup_usd", "N/A"),
            "minimum_required_today_usd": _value(capacity, "minimum_required_today_usd", "N/A"),
            "final_suggested_usd": _usd(suggested),
            "remaining_to_execute_today_usd": _value(decision, "remaining_to_execute_today_usd", "N/A"),
            "reason_summary": _value(decision, "reason_summary", "No canonical decision."),
            "reason_codes": ", ".join(_value(decision, "reason_codes", [])) or "none",
            "btc_reference_price": _value(reference, "value", "N/A"),
            "btc_reference_observed_at": _value(reference, "observed_at", "N/A"),
            "btc_reference_quality": _value(reference, "quality_status", "N/A"),
            "recent_high": _value(daily_data, "recent_high", "N/A"),
            "daily_data_observed_at": _value(
                (daily_data.get("candles") or [{}])[-1], "bucket_end", "N/A"
            ),
            "daily_data_quality": _value(daily_data, "quality_status", "N/A"),
            "atr_14": _value(daily_data, "atr", "N/A"),
            "atr_quality": _value(daily_data, "quality_status", "N/A"),
            "fear_greed": _value(fear, "value", "N/A"),
            "fear_greed_observed_at": _value(fear, "observed_at", "N/A"),
            "fear_greed_quality": _value(fear, "quality_status", "N/A"),
            "bviv": _value(bviv, "value", "N/A"),
            "bviv_observed_at": _value(bviv, "observed_at", "N/A"),
            "bviv_quality": _value(bviv, "quality_status", "N/A"),
            "bviv_fallback_used": _value(bviv, "fallback_used", "N/A"),
            "location_score": _value(scores, "location_score", "N/A"),
            "sentiment_score": _value(scores, "sentiment_score", "N/A"),
            "atr_drop_score": _value(scores, "atr_drop_score", "N/A"),
            "absolute_drop_score": _value(scores, "absolute_drop_score", "N/A"),
            "shock_score": _value(scores, "shock_score", "N/A"),
            "directional_score": _value(scores, "directional_score", "N/A"),
            "bviv_modifier": _value(market, "bviv_modifier", "N/A"),
            "remaining_funds_before_usd": _value(portfolio_input, "remaining_funds_usd", "N/A"),
            "today_hard_capacity_usd": _value(capacity, "today_hard_capacity_usd", "N/A"),
            "weekly_hard_remaining_usd": _value(capacity, "weekly_hard_remaining_usd", "N/A"),
            "weekly_soft_remaining_usd": _value(pacing, "weekly_soft_remaining_usd", "N/A"),
            "soft_cap_overridden_for_feasibility": _value(pacing, "soft_cap_overridden_for_feasibility", "N/A"),
            "total_capacity_including_today_usd": _value(capacity, "total_capacity_including_today_usd", "N/A"),
            "plan_feasible": _value(capacity, "plan_feasible", "N/A"),
            "actual_invested_today_usd": _usd(actual_usd),
            "execution_variance_usd": _usd(variance),
            "actual_btc_today": _btc(actual_btc),
            "actual_average_price_today_usd": _usd(average_today),
            "execution_note": "; ".join(filter(None, (r.get("note") for r in purchases))) or "none",
            "day_close_reason": close_reason or "none",
            "cumulative_actual_invested_usd": _usd(cumulative_usd),
            "remaining_budget_usd": _usd(remaining),
            "cumulative_btc": _btc(cumulative_btc),
            "average_cost_usd": _usd(cumulative_average),
            "actual_invested_this_week_usd": _usd(week_usd),
            "execution_watermark": watermark,
        }
        return _replace(template, values), watermark, generated_at

    def _weekly(self, datasets: dict[str, list[dict]], start: date, end: date):
        decisions, targets, _, effective, watermark, generated_at = self._context(
            datasets, start, end
        )
        target = targets.get(start.isoformat())
        period_purchases = [
            r for r in effective if start <= date.fromisoformat(r["plan_date"]) <= end
        ]
        actual_usd, actual_btc = _sum_purchases(period_purchases)
        average = None if actual_btc == 0 else actual_usd / actual_btc
        cumulative_usd, cumulative_btc, remaining, cumulative_average = self._portfolio_at(
            effective, end
        )
        rows: list[str] = []
        statuses: list[str] = []
        current_decisions: list[dict] = []
        for day in _days(start, end):
            key = day.isoformat()
            decision = decisions.get(key)
            day_purchases = [r for r in effective if r["plan_date"] == key]
            day_actual, _ = _sum_purchases(day_purchases)
            suggested = (
                None
                if decision is None or decision.get("final_suggested_usd") is None
                else Decimal(decision["final_suggested_usd"])
            )
            _, _, day_remaining, _ = self._portfolio_at(effective, day)
            status = _execution_status(
                decision=decision,
                actual_usd=day_actual,
                close_reason=_latest_close(datasets["executions"], day),
                remaining_budget=day_remaining,
            )
            statuses.append(status)
            if decision:
                current_decisions.append(decision)
            rows.append(
                f"| {key} | {_value(decision, 'decision_status', 'no_decision')} | "
                f"{_usd(suggested)} | {_usd(day_actual)} | "
                f"{_usd(None if suggested is None else day_actual - suggested)} | "
                f"{status} | {_value(decision, 'reason_summary', 'No decision')} |"
            )
        template = self._template("WEEKLY_REPORT.md")
        template_row = "| `{{plan_date}}` | `{{decision_status}}` | `{{suggested_usd}}` | `{{actual_usd}}` | `{{variance_usd}}` | `{{execution_status}}` | `{{reason_summary}}` |"
        template = template.replace(template_row, "\n".join(rows))
        target_usd = Decimal(target["weekly_target_usd"]) if target else None
        minimum = Decimal(target["weekly_min_usd"]) if target else None
        min_completion = None if minimum in (None, ZERO) else actual_usd / minimum
        latest = current_decisions[-1] if current_decisions else None
        latest_capacity = latest.get("capacity", {}) if latest else {}
        configs = sorted({d["config_version"] for d in current_decisions})
        issues = []
        if "no_decision" in statuses:
            issues.append("missing decision")
        if "pending" in statuses:
            issues.append("pending execution")
        if any(d.get("decision_status") == "blocked" for d in current_decisions):
            issues.append("blocked decision")
        values = {
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "generated_at": generated_at,
            "weekly_target_id": _value(target, "weekly_target_id", "N/A"),
            "config_versions": ", ".join(configs) or "N/A",
            "execution_watermark": watermark,
            "data_completeness_status": "complete" if not issues else "attention_required",
            "weekly_target_usd": _value(target, "weekly_target_usd", "N/A"),
            "weekly_min_usd": _value(target, "weekly_min_usd", "N/A"),
            "weekly_soft_max_usd": _value(target, "weekly_soft_max_usd", "N/A"),
            "weekly_hard_max_usd": _value(target, "weekly_hard_max_usd", "N/A"),
            "actual_invested_week_usd": _usd(actual_usd),
            "target_variance_usd": _usd(None if target_usd is None else actual_usd - target_usd),
            "weekly_min_completion_ratio": _ratio(min_completion),
            "btc_acquired_week": _btc(actual_btc),
            "actual_average_price_week_usd": _usd(average),
            "normal_days": sum(d.get("decision_status") == "normal" for d in current_decisions),
            "degraded_days": sum(d.get("decision_status") == "degraded" for d in current_decisions),
            "base_only_days": sum(d.get("decision_status") == "base_only" for d in current_decisions),
            "blocked_days": sum(d.get("decision_status") == "blocked" for d in current_decisions),
            "pending_days": statuses.count("pending"),
            "plan_infeasible_days": sum(d.get("decision_status") == "plan_infeasible" for d in current_decisions),
            "soft_cap_override_days": sum(bool(_value(d.get("pacing", {}), "soft_cap_overridden_for_feasibility", False)) for d in current_decisions),
            "open_issue": "; ".join(issues) or "none",
            "cumulative_actual_invested_usd": _usd(cumulative_usd),
            "remaining_budget_usd": _usd(remaining),
            "cumulative_btc": _btc(cumulative_btc),
            "average_cost_usd": _usd(cumulative_average),
            "days_remaining": max(0, (self.config.end_date - end).days),
            "future_hard_capacity_usd": _future_capacity(latest_capacity),
            "plan_feasible": _value(latest_capacity, "plan_feasible", "N/A"),
            "weekly_summary": f"Actual {_usd(actual_usd)} USD; {len(issues)} open issue(s).",
        }
        return _replace(template, values), watermark, generated_at

    def _monthly(self, datasets: dict[str, list[dict]], start: date, end: date):
        decisions, targets, _, effective, watermark, generated_at = self._context(
            datasets, start, end
        )
        current_decisions = [
            decisions[day.isoformat()]
            for day in _days(start, end)
            if day.isoformat() in decisions
        ]
        purchases = [
            r for r in effective if start <= date.fromisoformat(r["plan_date"]) <= end
        ]
        actual_usd, actual_btc = _sum_purchases(purchases)
        average = None if actual_btc == 0 else actual_usd / actual_btc
        suggested_values = [
            Decimal(d["final_suggested_usd"])
            for d in current_decisions
            if d.get("final_suggested_usd") is not None
        ]
        suggested = sum(suggested_values, ZERO)
        cumulative_usd, cumulative_btc, remaining, cumulative_average = self._portfolio_at(
            effective, end
        )
        statuses: dict[str, str] = {}
        for day in _days(start, end):
            key = day.isoformat()
            day_records = [r for r in effective if r["plan_date"] == key]
            day_actual, _ = _sum_purchases(day_records)
            _, _, day_remaining, _ = self._portfolio_at(effective, day)
            statuses[key] = _execution_status(
                decision=decisions.get(key),
                actual_usd=day_actual,
                close_reason=_latest_close(datasets["executions"], day),
                remaining_budget=day_remaining,
            )
        directional = [Decimal(d["scores"]["directional_score"]) for d in current_decisions if d.get("scores", {}).get("directional_score") is not None]
        bviv_modifiers = [Decimal(d["market_amounts"]["bviv_modifier"]) for d in current_decisions if d.get("market_amounts", {}).get("bviv_modifier") is not None]
        week_rows: list[str] = []
        for week_start in sorted(
            {
                max(day - timedelta(days=day.weekday()), self.config.start_date)
                for day in _days(start, end)
            }
        ):
            _, week_end = clipped_week(week_start, self.config)
            range_start, range_end = max(week_start, start), min(week_end, end)
            weekly_decisions = [d for d in current_decisions if range_start <= date.fromisoformat(d["plan_date"]) <= range_end]
            weekly_suggested = sum((Decimal(d["final_suggested_usd"]) for d in weekly_decisions if d.get("final_suggested_usd") is not None), ZERO)
            weekly_purchases = [r for r in purchases if range_start <= date.fromisoformat(r["plan_date"]) <= range_end]
            weekly_actual, _ = _sum_purchases(weekly_purchases)
            target = targets.get(week_start.isoformat())
            minimum = Decimal(target["weekly_min_usd"]) if target else None
            completion = None if minimum in (None, ZERO) else weekly_actual / minimum
            latest = weekly_decisions[-1] if weekly_decisions else None
            feasible = _value(_value(latest, "capacity", {}), "plan_feasible", "N/A")
            week_rows.append(
                f"| {range_start.isoformat()} ～ {range_end.isoformat()} | "
                f"{_value(target, 'weekly_target_usd', 'N/A')} | {_usd(weekly_suggested)} | "
                f"{_usd(weekly_actual)} | {_ratio(completion)} | {feasible} |"
            )
        template = self._template("MONTHLY_REPORT.md")
        template_row = "| `{{week_range}}` | `{{weekly_target_usd}}` | `{{weekly_suggested_usd}}` | `{{weekly_actual_usd}}` | `{{weekly_min_completion_ratio}}` | `{{plan_feasible}}` |"
        template = template.replace(template_row, "\n".join(week_rows))
        configs = sorted({d["config_version"] for d in current_decisions})
        latest = current_decisions[-1] if current_decisions else None
        latest_capacity = latest.get("capacity", {}) if latest else {}
        degraded_dates = [d["plan_date"] for d in current_decisions if d["decision_status"] == "degraded"]
        blocked_dates = [d["plan_date"] for d in current_decisions if d["decision_status"] == "blocked"]
        pending_dates = [key for key, value in statuses.items() if value == "pending"]
        infeasible_dates = [d["plan_date"] for d in current_decisions if d["decision_status"] == "plan_infeasible"]
        adherence = None if suggested == 0 else min(actual_usd, suggested) / suggested
        values = {
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "generated_at": generated_at,
            "config_versions": ", ".join(configs) or "N/A",
            "execution_watermark": watermark,
            "data_completeness_status": "complete" if len(current_decisions) == (end - start).days + 1 and not pending_dates and not blocked_dates else "attention_required",
            "total_suggested_usd": _usd(suggested),
            "total_actual_usd": _usd(actual_usd),
            "total_variance_usd": _usd(actual_usd - suggested),
            "btc_acquired": _btc(actual_btc),
            "execution_count": len(purchases),
            "actual_average_price_usd": _usd(average),
            "decision_days": len(current_decisions),
            "executed_days": list(statuses.values()).count("executed"),
            "partially_executed_days": list(statuses.values()).count("partially_executed"),
            "over_executed_days": list(statuses.values()).count("over_executed"),
            "pending_days": len(pending_dates),
            "blocked_days": len(blocked_dates),
            "adherence_ratio": _ratio(adherence),
            "average_directional_score": _ratio(None if not directional else sum(directional, ZERO) / Decimal(len(directional))),
            "average_bviv_modifier": _ratio(None if not bviv_modifiers else sum(bviv_modifiers, ZERO) / Decimal(len(bviv_modifiers))),
            "minimum_required_days": sum(Decimal(_value(d.get("capacity", {}), "minimum_required_today_usd", "0")) > 0 for d in current_decisions),
            "degraded_dates": ", ".join(degraded_dates) or "none",
            "blocked_dates": ", ".join(blocked_dates) or "none",
            "pending_dates": ", ".join(pending_dates) or "none",
            "plan_infeasible_dates": ", ".join(infeasible_dates) or "none",
            "config_transitions": " → ".join(configs) or "none",
            "corrected_execution_count": sum(r.get("event_type") == "reversal" for r in datasets["executions"] if start <= date.fromisoformat(r["plan_date"]) <= end),
            "cumulative_actual_invested_usd": _usd(cumulative_usd),
            "remaining_budget_usd": _usd(remaining),
            "cumulative_btc": _btc(cumulative_btc),
            "average_cost_usd": _usd(cumulative_average),
            "budget_deployed_ratio": _ratio(cumulative_usd / self.config.initial_budget),
            "days_remaining": max(0, (self.config.end_date - end).days),
            "future_hard_capacity_usd": _future_capacity(latest_capacity),
            "plan_feasible": _value(latest_capacity, "plan_feasible", "N/A"),
            "monthly_summary": f"Actual {_usd(actual_usd)} USD across {len(purchases)} purchase(s).",
        }
        return _replace(template, values), watermark, generated_at
