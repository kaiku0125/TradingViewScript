"""Structural and ledger validation for canonical Journal records."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
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


def _timestamp(
    value: object, field: str, prefix: str, issues: list[str]
) -> datetime | None:
    if not isinstance(value, str):
        issues.append(f"{prefix}: {field} must be an RFC 3339 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        issues.append(f"{prefix}: {field} is not a valid RFC 3339 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(f"{prefix}: {field} must include a UTC offset")
        return None
    return parsed


def _scan_secret_fields(value: object, prefix: str, issues: list[str]) -> None:
    forbidden = {"apikey", "api_key", "authorization", "token", "secret"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden:
                issues.append(f"{prefix}: forbidden secret field {key}")
            _scan_secret_fields(item, f"{prefix}.{key}", issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_secret_fields(item, f"{prefix}[{index}]", issues)


def _validate_provider_point(
    point: dict,
    *,
    field: str,
    prefix: str,
    cutoff: datetime | None,
    issues: list[str],
) -> None:
    required = {
        "source",
        "symbol",
        "value",
        "interval",
        "observed_at",
        "available_at",
        "fetched_at",
        "timezone",
        "cutoff_at",
        "stale_after",
        "quality_status",
        "fallback_used",
        "request_descriptor",
    }
    point_prefix = f"{prefix}.{field}"
    _required(point, required, point_prefix, issues)
    status = point.get("quality_status")
    if status not in {"valid", "stale", "missing", "invalid"}:
        issues.append(f"{point_prefix}: invalid quality_status")
    if not isinstance(point.get("fallback_used"), bool):
        issues.append(f"{point_prefix}: fallback_used must be boolean")
    for text_field in {"source", "symbol", "interval", "timezone", "stale_after"}:
        if not isinstance(point.get(text_field), str) or not point.get(text_field):
            issues.append(f"{point_prefix}: {text_field} must be a non-empty string")
    if not isinstance(point.get("request_descriptor"), dict):
        issues.append(f"{point_prefix}: request_descriptor must be an object")
    observed = None
    for timestamp_field in {"observed_at", "available_at", "fetched_at"}:
        value = point.get(timestamp_field)
        if value is not None:
            parsed = _timestamp(value, timestamp_field, point_prefix, issues)
            if timestamp_field == "observed_at":
                observed = parsed
    point_cutoff = _timestamp(
        point.get("cutoff_at"), "cutoff_at", point_prefix, issues
    )
    if cutoff is not None and point_cutoff is not None and point_cutoff != cutoff:
        issues.append(f"{point_prefix}: cutoff_at differs from snapshot cutoff")
    if observed is not None and cutoff is not None and observed > cutoff:
        issues.append(f"{point_prefix}: observed_at is after cutoff")
    raw_value = point.get("value")
    if status == "valid" and raw_value is None:
        issues.append(f"{point_prefix}: valid provider value must not be null")
    if raw_value is not None:
        _decimal_field(
            raw_value,
            "value",
            point_prefix,
            issues,
            max_places=18,
        )
    _scan_secret_fields(point, point_prefix, issues)


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
        cutoff = _timestamp(record.get("cutoff_at"), "cutoff_at", prefix, issues)
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
        for point_field in {
            "btc_reference",
            "btc_previous_reference",
            "fear_greed",
            "bviv",
        }:
            point = record.get(point_field)
            if isinstance(point, dict):
                _validate_provider_point(
                    point,
                    field=point_field,
                    prefix=prefix,
                    cutoff=cutoff,
                    issues=issues,
                )
        daily = record.get("btc_daily_candles")
        if isinstance(daily, dict):
            _required(
                daily,
                {
                    "source",
                    "symbol",
                    "interval",
                    "timezone",
                    "cutoff_at",
                    "quality_status",
                    "fallback_used",
                    "candles",
                    "request_descriptor",
                },
                f"{prefix}.btc_daily_candles",
                issues,
            )
            status = daily.get("quality_status")
            if status not in {"valid", "stale", "missing", "invalid"}:
                issues.append(f"{prefix}.btc_daily_candles: invalid quality_status")
            candles = daily.get("candles")
            if not isinstance(candles, list):
                issues.append(f"{prefix}.btc_daily_candles: candles must be a list")
            else:
                previous_end = None
                for candle_index, candle in enumerate(candles, start=1):
                    candle_prefix = (
                        f"{prefix}.btc_daily_candles.candles[{candle_index}]"
                    )
                    if not isinstance(candle, dict):
                        issues.append(f"{candle_prefix}: candle must be an object")
                        continue
                    start = _timestamp(
                        candle.get("bucket_start"),
                        "bucket_start",
                        candle_prefix,
                        issues,
                    )
                    end = _timestamp(
                        candle.get("bucket_end"),
                        "bucket_end",
                        candle_prefix,
                        issues,
                    )
                    if start is not None and end is not None:
                        if end - start != timedelta(days=1):
                            issues.append(f"{candle_prefix}: daily bucket must be 24 hours")
                        if cutoff is not None and end > cutoff:
                            issues.append(f"{candle_prefix}: incomplete candle after cutoff")
                        if previous_end is not None and start != previous_end:
                            issues.append(f"{candle_prefix}: daily candle gap or disorder")
                        previous_end = end
                    for price_field in {"low", "high", "open", "close"}:
                        _decimal_field(
                            candle.get(price_field),
                            price_field,
                            candle_prefix,
                            issues,
                            max_places=18,
                            positive=True,
                        )
                if status == "valid" and daily.get("candle_count") != len(candles):
                    issues.append(
                        f"{prefix}.btc_daily_candles: candle_count does not match"
                    )
                if status == "valid" and len(candles) != config.location_lookback_days + 1:
                    issues.append(
                        f"{prefix}.btc_daily_candles: valid input must contain "
                        f"{config.location_lookback_days + 1} candles"
                    )
            _scan_secret_fields(daily, f"{prefix}.btc_daily_candles", issues)
        portfolio = record.get("portfolio_input")
        if isinstance(portfolio, dict):
            for amount_field in {
                "actual_invested_usd",
                "remaining_funds_usd",
                "actual_invested_this_week_usd",
                "actual_invested_today_usd",
            }:
                _decimal_field(
                    portfolio.get(amount_field),
                    amount_field,
                    f"{prefix}.portfolio_input",
                    issues,
                    max_places=2,
                )
        quality = record.get("quality_summary")
        if isinstance(quality, dict):
            if quality.get("status") not in {"valid", "degraded", "blocked"}:
                issues.append(f"{prefix}.quality_summary: invalid status")
            if not isinstance(quality.get("reason_codes"), list) or not all(
                isinstance(code, str) for code in quality.get("reason_codes", [])
            ):
                issues.append(f"{prefix}.quality_summary: reason_codes must be strings")
        _scan_secret_fields(record, prefix, issues)
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
    keys_by_week_start: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if isinstance(record.get("week_start"), str) and isinstance(
            record.get("weekly_target_key"), str
        ):
            keys_by_week_start[record["week_start"]].add(
                record["weekly_target_key"]
            )
    for week_start, keys in keys_by_week_start.items():
        if len(keys) != 1:
            issues.append(
                f"weekly target {week_start}: must use one stable target key"
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
        parsed_final = None
        if status == "blocked":
            if final_amount is not None:
                issues.append(f"{prefix}: blocked decision final amount must be null")
        else:
            parsed_final = _decimal_field(
                final_amount,
                "final_suggested_usd",
                prefix,
                issues,
                max_places=2,
            )
        for object_field in {"scores", "market_amounts", "pacing", "capacity"}:
            if not isinstance(record.get(object_field), dict):
                issues.append(f"{prefix}: {object_field} must be an object")
        scores = record.get("scores")
        if isinstance(scores, dict):
            for field in {
                "drawdown_pct",
                "daily_drop_pct",
                "atr_pct",
                "down_atr_multiple",
                "location_score",
                "sentiment_score",
                "atr_drop_score",
                "absolute_drop_score",
                "shock_score",
                "directional_score",
                "bviv_level",
                "bviv_modifier",
            }:
                if field in scores and scores[field] is not None:
                    value = _decimal_field(
                        scores[field], field, prefix, issues, max_places=8
                    )
                    if (
                        value is not None
                        and field.endswith("score")
                        and not Decimal("0") <= value <= Decimal("1")
                    ):
                        issues.append(f"{prefix}: {field} must be within 0..1")
        market_amounts = record.get("market_amounts")
        if isinstance(market_amounts, dict):
            for field in {
                "base_amount_usd",
                "adaptive_multiplier",
                "market_adaptive_amount_usd",
                "market_amount_usd",
                "bviv_modifier",
            }:
                if field in market_amounts:
                    value = _decimal_field(
                        market_amounts[field], field, prefix, issues, max_places=8
                    )
                    if (
                        value is not None
                        and field == "bviv_modifier"
                        and value > Decimal("1")
                    ):
                        issues.append(f"{prefix}: BVIV modifier must not amplify in v1")
        capacity = record.get("capacity")
        if isinstance(capacity, dict):
            for field in {
                "weekly_hard_remaining_usd",
                "current_week_future_capacity_usd",
                "future_week_capacity_usd",
                "total_capacity_including_today_usd",
                "today_hard_capacity_usd",
                "minimum_required_today_usd",
            }:
                if field in capacity:
                    _decimal_field(
                        capacity[field], field, prefix, issues, max_places=8
                    )
        pacing = record.get("pacing")
        if isinstance(pacing, dict):
            for field in {
                "required_daily_pace_usd",
                "pace_floor_usd",
                "weekly_gap_usd",
                "weekly_catchup_usd",
                "weekly_soft_remaining_usd",
                "effective_weekly_soft_remaining_usd",
                "guard_candidate_usd",
                "final_suggested_usd",
            }:
                if field in pacing:
                    _decimal_field(
                        pacing[field], field, prefix, issues, max_places=8
                    )
        if parsed_final is not None:
            if parsed_final > config.daily_hard_max:
                issues.append(f"{prefix}: final amount exceeds daily hard max")
            if status == "completed" and parsed_final != 0:
                issues.append(f"{prefix}: completed decision must suggest zero")
            if isinstance(capacity, dict):
                weekly_remaining = capacity.get("weekly_hard_remaining_usd")
                today_capacity = capacity.get("today_hard_capacity_usd")
                for field, raw_limit in (
                    ("weekly hard remaining", weekly_remaining),
                    ("today hard capacity", today_capacity),
                ):
                    if raw_limit is None:
                        continue
                    limit = _decimal_field(
                        raw_limit, field, prefix, issues, max_places=8
                    )
                    if limit is not None and parsed_final > limit:
                        issues.append(f"{prefix}: final amount exceeds {field}")
        remaining_to_execute = record.get("remaining_to_execute_today_usd")
        if remaining_to_execute is not None:
            parsed_remaining = _decimal_field(
                remaining_to_execute,
                "remaining_to_execute_today_usd",
                prefix,
                issues,
                max_places=2,
            )
            if (
                parsed_remaining is not None
                and parsed_final is not None
                and parsed_remaining > parsed_final
            ):
                issues.append(
                    f"{prefix}: remaining_to_execute_today exceeds final amount"
                )
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
    ids_by_plan_date: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if isinstance(record.get("plan_date"), str) and isinstance(
            record.get("decision_id"), str
        ):
            ids_by_plan_date[record["plan_date"]].add(record["decision_id"])
    for plan_date_value, decision_ids in ids_by_plan_date.items():
        if len(decision_ids) != 1:
            issues.append(
                f"decision {plan_date_value}: must use one stable decision_id"
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
    snapshot_by_id = {
        record.get("snapshot_id"): record
        for record in datasets["market_snapshots"]
        if isinstance(record.get("snapshot_id"), str)
    }
    target_by_id = {
        record.get("weekly_target_id"): record
        for record in datasets["weekly_targets"]
        if isinstance(record.get("weekly_target_id"), str)
    }
    for index, decision in enumerate(datasets["decisions"], start=1):
        prefix = f"decisions[{index}]"
        snapshot = snapshot_by_id.get(decision.get("snapshot_id"))
        target = target_by_id.get(decision.get("weekly_target_id"))
        if snapshot is not None:
            if decision.get("operation_id") != snapshot.get("operation_id"):
                issues.append(f"{prefix}: operation_id differs from snapshot")
            if decision.get("plan_date") != snapshot.get("plan_date"):
                issues.append(f"{prefix}: plan_date differs from snapshot")
            snapshot_config = snapshot.get("config_version")
            if (
                snapshot_config is not None
                and decision.get("config_version") != snapshot_config
            ):
                issues.append(f"{prefix}: config_version differs from snapshot")
            portfolio = snapshot.get("portfolio_input")
            if isinstance(portfolio, dict) and decision.get("final_suggested_usd") is not None:
                final = _decimal_field(
                    decision.get("final_suggested_usd"),
                    "final_suggested_usd",
                    prefix,
                    issues,
                    max_places=2,
                )
                remaining = _decimal_field(
                    portfolio.get("remaining_funds_usd"),
                    "portfolio.remaining_funds_usd",
                    prefix,
                    issues,
                    max_places=2,
                )
                if final is not None and remaining is not None and final > remaining:
                    issues.append(f"{prefix}: final amount exceeds snapshot remaining funds")
        if target is not None:
            if decision.get("config_version") != target.get("config_version"):
                issues.append(f"{prefix}: config_version differs from weekly target")
            try:
                plan_date_value = date.fromisoformat(decision.get("plan_date"))
                week_start = date.fromisoformat(target.get("week_start"))
                week_end = date.fromisoformat(target.get("week_end"))
            except (TypeError, ValueError):
                pass
            else:
                if not week_start <= plan_date_value <= week_end:
                    issues.append(f"{prefix}: weekly target does not cover plan_date")
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


def journal_warnings(datasets: dict[str, list[dict]]) -> list[str]:
    """Return non-fatal audit findings that must never trigger data deletion."""
    referenced_snapshots = {
        record.get("snapshot_id") for record in datasets.get("decisions", [])
    }
    return [
        f"orphan market snapshot: {record.get('snapshot_id')}"
        for record in datasets.get("market_snapshots", [])
        if record.get("snapshot_id") not in referenced_snapshots
    ]
