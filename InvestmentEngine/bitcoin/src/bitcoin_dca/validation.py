"""Structural and ledger validation for canonical Journal records."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from .config import RuntimeConfig
from .decimal_utils import parse_decimal_string
from .errors import JournalValidationError, UserInputError


DECISION_STATUSES = {
    "normal",
    "degraded",
    "base_only",
    "blocked",
    "plan_infeasible",
    "completed",
}


def _required(record: dict, fields: set[str], prefix: str, issues: list[str]) -> None:
    for field in sorted(fields - record.keys()):
        issues.append(f"{prefix}: missing required field {field}")


def _timestamp(value: object, field: str, prefix: str, issues: list[str]) -> None:
    if not isinstance(value, str):
        issues.append(f"{prefix}: {field} must be an RFC 3339 string")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        issues.append(f"{prefix}: {field} is not a valid RFC 3339 timestamp")
        return
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(f"{prefix}: {field} must include a UTC offset")


def _plan_date(
    value: object,
    field: str,
    prefix: str,
    config: RuntimeConfig,
    issues: list[str],
) -> date | None:
    if not isinstance(value, str):
        issues.append(f"{prefix}: {field} must be an ISO date")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        issues.append(f"{prefix}: {field} must be an ISO date")
        return None
    if parsed < config.start_date or parsed > config.end_date:
        issues.append(f"{prefix}: {field} is outside the approved plan")
    return parsed


def _decimal_field(
    value: object,
    field: str,
    prefix: str,
    issues: list[str],
    *,
    max_places: int,
    positive: bool = False,
) -> Decimal | None:
    try:
        return parse_decimal_string(
            value,
            field=field,
            max_places=max_places,
            positive=positive,
        )
    except UserInputError as exc:
        issues.append(f"{prefix}: {exc}")
        return None


def _validate_revision_chain(
    records: list[dict],
    *,
    group_field: str,
    id_field: str,
    prefix: str,
    issues: list[str],
) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        group = record.get(group_field)
        if isinstance(group, str) and group:
            groups[group].append(record)
    for group, members in groups.items():
        ids = {member.get(id_field) for member in members}
        revisions = [member.get("revision") for member in members]
        if any(not isinstance(value, int) or value < 1 for value in revisions):
            issues.append(f"{prefix} {group}: revisions must be positive integers")
            continue
        if len(set(revisions)) != len(revisions):
            issues.append(f"{prefix} {group}: revision numbers must be unique")
        if set(revisions) != set(range(1, len(revisions) + 1)):
            issues.append(f"{prefix} {group}: revisions must be contiguous from 1")
        superseded: set[str] = set()
        for member in members:
            predecessor = member.get("supersedes_revision_id")
            if predecessor is None:
                if member.get("revision") != 1:
                    issues.append(
                        f"{prefix} {group}: only revision 1 may have no predecessor"
                    )
                continue
            if predecessor not in ids:
                issues.append(f"{prefix} {group}: predecessor {predecessor} not found")
            if predecessor in superseded:
                issues.append(
                    f"{prefix} {group}: predecessor {predecessor} superseded twice"
                )
            superseded.add(predecessor)
        leaves = {value for value in ids if isinstance(value, str)} - superseded
        if len(leaves) != 1:
            issues.append(f"{prefix} {group}: revision chain must have one current leaf")


def _validate_executions(
    records: list[dict], config: RuntimeConfig, issues: list[str]
) -> None:
    ids: set[str] = set()
    purchases: dict[str, dict] = {}
    reversed_ids: set[str] = set()
    required = {
        "schema_version",
        "execution_id",
        "operation_id",
        "event_type",
        "plan_date",
        "decision_revision_id",
        "executed_at",
        "recorded_at",
        "usd_amount",
        "btc_quantity",
        "venue",
        "external_reference",
        "reverses_execution_id",
        "source",
        "close_reason",
        "note",
    }
    for index, record in enumerate(records, start=1):
        prefix = f"executions[{index}]"
        _required(record, required, prefix, issues)
        if record.get("schema_version") != "execution.v1":
            issues.append(f"{prefix}: unsupported schema_version")
        execution_id = record.get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            issues.append(f"{prefix}: execution_id must be a non-empty string")
        elif execution_id in ids:
            issues.append(f"{prefix}: duplicate execution_id {execution_id}")
        else:
            ids.add(execution_id)
        operation_id = record.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            issues.append(f"{prefix}: operation_id must be a non-empty string")
        _plan_date(record.get("plan_date"), "plan_date", prefix, config, issues)
        _timestamp(record.get("executed_at"), "executed_at", prefix, issues)
        _timestamp(record.get("recorded_at"), "recorded_at", prefix, issues)
        if record.get("source") not in {"manual", "imported", "integration"}:
            issues.append(f"{prefix}: invalid source")
        if not isinstance(record.get("venue"), str) or not record.get("venue"):
            issues.append(f"{prefix}: venue must be a non-empty string")
        decision_id = record.get("decision_revision_id")
        if decision_id is not None and (
            not isinstance(decision_id, str) or not decision_id
        ):
            issues.append(f"{prefix}: decision_revision_id must be null or a string")

        event_type = record.get("event_type")
        if event_type in {"purchase", "reversal"}:
            usd = _decimal_field(
                record.get("usd_amount"),
                "usd_amount",
                prefix,
                issues,
                max_places=2,
                positive=True,
            )
            btc = _decimal_field(
                record.get("btc_quantity"),
                "btc_quantity",
                prefix,
                issues,
                max_places=8,
                positive=True,
            )
            if record.get("close_reason") is not None:
                issues.append(f"{prefix}: purchase/reversal close_reason must be null")
            if event_type == "purchase":
                if record.get("reverses_execution_id") is not None:
                    issues.append(f"{prefix}: purchase cannot reverse another event")
                if isinstance(execution_id, str):
                    purchases[execution_id] = record
            else:
                target_id = record.get("reverses_execution_id")
                target = purchases.get(target_id)
                if target is None:
                    issues.append(f"{prefix}: reversal must reference an earlier purchase")
                elif target_id in reversed_ids:
                    issues.append(f"{prefix}: purchase {target_id} is reversed more than once")
                else:
                    reversed_ids.add(target_id)
                    if usd is not None and record.get("usd_amount") != target.get(
                        "usd_amount"
                    ):
                        issues.append(f"{prefix}: reversal USD must match purchase")
                    if btc is not None and record.get("btc_quantity") != target.get(
                        "btc_quantity"
                    ):
                        issues.append(f"{prefix}: reversal BTC must match purchase")
        elif event_type == "day_close":
            if record.get("usd_amount") is not None or record.get("btc_quantity") is not None:
                issues.append(f"{prefix}: day_close must not contain USD or BTC")
            if record.get("reverses_execution_id") is not None:
                issues.append(f"{prefix}: day_close cannot reverse another event")
            if record.get("close_reason") not in {"skipped", "completed_for_day"}:
                issues.append(f"{prefix}: invalid day_close reason")
        else:
            issues.append(f"{prefix}: invalid event_type")


def _validate_snapshots(
    records: list[dict], config: RuntimeConfig, issues: list[str]
) -> set[str]:
    snapshot_ids: set[str] = set()
    required = {
        "schema_version",
        "snapshot_id",
        "operation_id",
        "plan_date",
        "cutoff_at",
        "created_at",
        "btc_reference",
        "btc_previous_reference",
        "btc_daily_candles",
        "fear_greed",
        "bviv",
        "portfolio_input",
        "quality_summary",
    }
    for index, record in enumerate(records, start=1):
        prefix = f"market_snapshots[{index}]"
        _required(record, required, prefix, issues)
        if record.get("schema_version") != "market_snapshot.v1":
            issues.append(f"{prefix}: unsupported schema_version")
        snapshot_id = record.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not snapshot_id:
            issues.append(f"{prefix}: snapshot_id must be a non-empty string")
        elif snapshot_id in snapshot_ids:
            issues.append(f"{prefix}: duplicate snapshot_id {snapshot_id}")
        else:
            snapshot_ids.add(snapshot_id)
        if not isinstance(record.get("operation_id"), str) or not record.get(
            "operation_id"
        ):
            issues.append(f"{prefix}: operation_id must be a non-empty string")
        _plan_date(record.get("plan_date"), "plan_date", prefix, config, issues)
        _timestamp(record.get("cutoff_at"), "cutoff_at", prefix, issues)
        _timestamp(record.get("created_at"), "created_at", prefix, issues)
        for object_field in {
            "btc_reference",
            "btc_previous_reference",
            "btc_daily_candles",
            "fear_greed",
            "bviv",
            "portfolio_input",
            "quality_summary",
        }:
            if not isinstance(record.get(object_field), dict):
                issues.append(f"{prefix}: {object_field} must be an object")
    return snapshot_ids


def _validate_weekly_targets(
    records: list[dict], config: RuntimeConfig, issues: list[str]
) -> set[str]:
    ids: set[str] = set()
    required = {
        "schema_version",
        "weekly_target_id",
        "weekly_target_key",
        "operation_id",
        "revision",
        "supersedes_revision_id",
        "week_start",
        "week_end",
        "created_for_plan_date",
        "created_at",
        "config_version",
        "remaining_funds_at_week_start_usd",
        "active_days_in_week",
        "total_days_remaining",
        "weekly_target_usd",
        "weekly_min_ratio",
        "weekly_min_usd",
        "weekly_soft_max_usd",
        "weekly_hard_max_usd",
    }
    decimal_fields = {
        "remaining_funds_at_week_start_usd": 2,
        "weekly_target_usd": 2,
        "weekly_min_ratio": 8,
        "weekly_min_usd": 2,
        "weekly_soft_max_usd": 2,
        "weekly_hard_max_usd": 2,
    }
    for index, record in enumerate(records, start=1):
        prefix = f"weekly_targets[{index}]"
        _required(record, required, prefix, issues)
        if record.get("schema_version") != "weekly_target.v1":
            issues.append(f"{prefix}: unsupported schema_version")
        target_id = record.get("weekly_target_id")
        if not isinstance(target_id, str) or not target_id:
            issues.append(f"{prefix}: weekly_target_id must be a non-empty string")
        elif target_id in ids:
            issues.append(f"{prefix}: duplicate weekly_target_id {target_id}")
        else:
            ids.add(target_id)
        if not isinstance(record.get("weekly_target_key"), str):
            issues.append(f"{prefix}: weekly_target_key must be a string")
        if not isinstance(record.get("operation_id"), str) or not record.get(
            "operation_id"
        ):
            issues.append(f"{prefix}: operation_id must be a non-empty string")
        if not isinstance(record.get("config_version"), str) or not record.get(
            "config_version"
        ):
            issues.append(f"{prefix}: config_version must be a non-empty string")
        for field in {"week_start", "week_end", "created_for_plan_date"}:
            _plan_date(record.get(field), field, prefix, config, issues)
        _timestamp(record.get("created_at"), "created_at", prefix, issues)
        for field, places in decimal_fields.items():
            _decimal_field(
                record.get(field), field, prefix, issues, max_places=places
            )
        for field in {"active_days_in_week", "total_days_remaining"}:
            if not isinstance(record.get(field), int) or record[field] < 1:
                issues.append(f"{prefix}: {field} must be a positive integer")
    _validate_revision_chain(
        records,
        group_field="weekly_target_key",
        id_field="weekly_target_id",
        prefix="weekly target",
        issues=issues,
    )
    return ids


def _validate_decisions(
    records: list[dict],
    config: RuntimeConfig,
    snapshot_ids: set[str],
    weekly_target_ids: set[str],
    issues: list[str],
) -> set[str]:
    revision_ids: set[str] = set()
    required = {
        "schema_version",
        "decision_id",
        "revision_id",
        "operation_id",
        "revision",
        "supersedes_revision_id",
        "plan_date",
        "snapshot_id",
        "weekly_target_id",
        "config_version",
        "calculated_at",
        "decision_status",
        "scores",
        "market_amounts",
        "pacing",
        "capacity",
        "final_suggested_usd",
        "reason_codes",
        "reason_summary",
    }
    for index, record in enumerate(records, start=1):
        prefix = f"decisions[{index}]"
        _required(record, required, prefix, issues)
        if record.get("schema_version") != "decision.v1":
            issues.append(f"{prefix}: unsupported schema_version")
        revision_id = record.get("revision_id")
        if not isinstance(revision_id, str) or not revision_id:
            issues.append(f"{prefix}: revision_id must be a non-empty string")
        elif revision_id in revision_ids:
            issues.append(f"{prefix}: duplicate revision_id {revision_id}")
        else:
            revision_ids.add(revision_id)
        if not isinstance(record.get("decision_id"), str):
            issues.append(f"{prefix}: decision_id must be a string")
        if not isinstance(record.get("operation_id"), str) or not record.get(
            "operation_id"
        ):
            issues.append(f"{prefix}: operation_id must be a non-empty string")
        if not isinstance(record.get("config_version"), str) or not record.get(
            "config_version"
        ):
            issues.append(f"{prefix}: config_version must be a non-empty string")
        _plan_date(record.get("plan_date"), "plan_date", prefix, config, issues)
        _timestamp(record.get("calculated_at"), "calculated_at", prefix, issues)
        if record.get("snapshot_id") not in snapshot_ids:
            issues.append(f"{prefix}: referenced snapshot not found")
        if record.get("weekly_target_id") not in weekly_target_ids:
            issues.append(f"{prefix}: referenced weekly target not found")
        status = record.get("decision_status")
        if status not in DECISION_STATUSES:
            issues.append(f"{prefix}: invalid decision_status")
        final_amount = record.get("final_suggested_usd")
        if status == "blocked":
            if final_amount is not None:
                issues.append(f"{prefix}: blocked decision final amount must be null")
        else:
            _decimal_field(
                final_amount,
                "final_suggested_usd",
                prefix,
                issues,
                max_places=2,
            )
        for object_field in {"scores", "market_amounts", "pacing", "capacity"}:
            if not isinstance(record.get(object_field), dict):
                issues.append(f"{prefix}: {object_field} must be an object")
        if not isinstance(record.get("reason_codes"), list) or not all(
            isinstance(value, str) for value in record.get("reason_codes", [])
        ):
            issues.append(f"{prefix}: reason_codes must be a string list")
        if not isinstance(record.get("reason_summary"), str):
            issues.append(f"{prefix}: reason_summary must be a string")
    _validate_revision_chain(
        records,
        group_field="decision_id",
        id_field="revision_id",
        prefix="decision",
        issues=issues,
    )
    return revision_ids


def validate_journal(
    datasets: dict[str, list[dict]], config: RuntimeConfig
) -> None:
    issues: list[str] = []
    for dataset in {
        "market_snapshots",
        "decisions",
        "executions",
        "weekly_targets",
    }:
        if dataset not in datasets or not isinstance(datasets[dataset], list):
            issues.append(f"missing dataset {dataset}")
    if issues:
        raise JournalValidationError(issues)

    snapshots = _validate_snapshots(datasets["market_snapshots"], config, issues)
    weekly_targets = _validate_weekly_targets(
        datasets["weekly_targets"], config, issues
    )
    decision_ids = _validate_decisions(
        datasets["decisions"],
        config,
        snapshots,
        weekly_targets,
        issues,
    )
    _validate_executions(datasets["executions"], config, issues)
    for index, record in enumerate(datasets["executions"], start=1):
        decision_revision_id = record.get("decision_revision_id")
        if (
            decision_revision_id is not None
            and decision_revision_id not in decision_ids
        ):
            issues.append(
                f"executions[{index}]: referenced decision revision not found"
            )

    record_ids: list[str] = []
    record_ids.extend(snapshots)
    record_ids.extend(weekly_targets)
    record_ids.extend(decision_ids)
    record_ids.extend(
        record["execution_id"]
        for record in datasets["executions"]
        if isinstance(record.get("execution_id"), str)
    )
    duplicates = {value for value in record_ids if record_ids.count(value) > 1}
    for duplicate in sorted(duplicates):
        issues.append(f"record ID reused across canonical datasets: {duplicate}")

    if issues:
        raise JournalValidationError(issues)
