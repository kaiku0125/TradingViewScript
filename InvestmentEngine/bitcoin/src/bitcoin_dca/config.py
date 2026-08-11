"""Versioned machine configuration loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "config.1.0-draft.2.json"
)


@dataclass(frozen=True)
class RuntimeConfig:
    config_path: Path
    raw: dict
    config_version: str
    initial_budget: Decimal
    start_date: date
    end_date: date
    timezone: ZoneInfo
    cutoff_time: time
    recommendation_window_end: time
    base_dca: Decimal
    nominal_adaptive_daily: Decimal
    factor_weights: tuple[Decimal, Decimal, Decimal]
    location_score_min_pct: Decimal
    location_score_max_pct: Decimal
    location_lookback_days: int
    sentiment_score_zero_at: Decimal
    sentiment_score_one_at: Decimal
    atr_score_min_multiple: Decimal
    atr_score_max_multiple: Decimal
    drop_score_min_pct: Decimal
    drop_score_max_pct: Decimal
    atr_period: int
    minimum_valid_directional_groups: int
    adaptive_multiplier_min: Decimal
    adaptive_multiplier_max: Decimal
    rounding_unit: Decimal
    bviv_score_min: Decimal
    bviv_score_max: Decimal
    bviv_modifier_min: Decimal
    bviv_modifier_max: Decimal
    bviv_gate_drawdown_pct: Decimal
    bviv_gate_fear_greed_max: Decimal
    acceleration_start_days: int
    full_pace_days: int
    weekly_min_ratio_early: Decimal
    weekly_min_ratio_late: Decimal
    weekly_soft_max_ratio: Decimal
    daily_hard_max: Decimal
    weekly_hard_max: Decimal
    btc_reference_max_age_minutes: int
    fear_greed_max_age_hours: int
    bviv_primary_max_age_hours: int
    bviv_fallback_max_age_hours: int
    volmex_api_key_env: str
    http_timeout_seconds: int
    http_max_attempts: int
    http_retry_delays_seconds: tuple[int, ...]
    data_dir: Path
    reports_dir: Path
    templates_dir: Path
    lock_filename: str


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise ConfigError(f"{field} must be finite")
    return parsed


def _numeric_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"{field} must be an integer or decimal string")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigError(f"{field} is not numeric") from exc
    if not parsed.is_finite():
        raise ConfigError(f"{field} must be finite")
    return parsed


def _parse_time(value: object, field: str) -> time:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be HH:MM")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{field} must be HH:MM") from exc


def _resolve_dir(config_path: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty path string")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def load_config(config_path: Path | str | None = None) -> RuntimeConfig:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    path = path.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid config JSON at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config root must be an object")
    if raw.get("schema_version") != "bitcoin_dca_config.v1":
        raise ConfigError("unsupported config schema_version")
    version = raw.get("config_version")
    if not isinstance(version, str) or not version:
        raise ConfigError("config_version must be a non-empty string")

    plan = raw.get("plan")
    runtime = raw.get("runtime")
    if not isinstance(plan, dict) or not isinstance(runtime, dict):
        raise ConfigError("plan and runtime must be objects")

    try:
        start_date = date.fromisoformat(plan["start_date"])
        end_date = date.fromisoformat(plan["end_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError("plan start_date/end_date must be ISO dates") from exc
    if start_date > end_date:
        raise ConfigError("plan start_date must not exceed end_date")
    if (end_date - start_date).days + 1 != 65:
        raise ConfigError("approved plan must contain exactly 65 calendar days")

    try:
        timezone = ZoneInfo(plan["timezone"])
    except (KeyError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ConfigError("plan.timezone must be a valid IANA timezone") from exc

    initial_budget = _decimal(plan.get("initial_budget"), "plan.initial_budget")
    if initial_budget <= 0:
        raise ConfigError("plan.initial_budget must be positive")
    if plan.get("currency") != "USD" or plan.get("asset") != "BTC":
        raise ConfigError("approved MVP supports only BTC funded in USD")

    factors = raw.get("factors")
    bviv = raw.get("bviv")
    decision = raw.get("decision")
    pacing = raw.get("pacing")
    budget = raw.get("budget")
    data = raw.get("data")
    if not all(
        isinstance(section, dict)
        for section in (factors, bviv, decision, pacing, budget, data)
    ):
        raise ConfigError(
            "factors, bviv, decision, pacing, budget, and data must be objects"
        )
    try:
        location = factors["location"]
        sentiment = factors["sentiment"]
        shock = factors["shock"]
        btc_data = data["btc"]
        fear_greed_data = data["fear_greed"]
        bviv_data = data["bviv"]
    except KeyError as exc:
        raise ConfigError(f"missing strategy config section: {exc.args[0]}") from exc
    if not all(
        isinstance(section, dict)
        for section in (
            location,
            sentiment,
            shock,
            btc_data,
            fear_greed_data,
            bviv_data,
        )
    ):
        raise ConfigError("factor and data provider sections must be objects")

    base_dca = _decimal(plan.get("base_dca"), "plan.base_dca")
    weights = (
        _decimal(location.get("weight"), "factors.location.weight"),
        _decimal(sentiment.get("weight"), "factors.sentiment.weight"),
        _decimal(shock.get("weight"), "factors.shock.weight"),
    )
    location_min = _decimal(
        location.get("score_min_pct"), "factors.location.score_min_pct"
    )
    location_max = _decimal(
        location.get("score_max_pct"), "factors.location.score_max_pct"
    )
    sentiment_zero = _numeric_decimal(
        sentiment.get("score_zero_at"), "factors.sentiment.score_zero_at"
    )
    sentiment_one = _numeric_decimal(
        sentiment.get("score_one_at"), "factors.sentiment.score_one_at"
    )
    atr_min = _decimal(
        shock.get("atr_score_min_multiple"),
        "factors.shock.atr_score_min_multiple",
    )
    atr_max = _decimal(
        shock.get("atr_score_max_multiple"),
        "factors.shock.atr_score_max_multiple",
    )
    drop_min = _decimal(
        shock.get("drop_score_min_pct"), "factors.shock.drop_score_min_pct"
    )
    drop_max = _decimal(
        shock.get("drop_score_max_pct"), "factors.shock.drop_score_max_pct"
    )
    adaptive_min = _decimal(
        decision.get("adaptive_multiplier_min"),
        "decision.adaptive_multiplier_min",
    )
    adaptive_max = _decimal(
        decision.get("adaptive_multiplier_max"),
        "decision.adaptive_multiplier_max",
    )
    rounding_unit = _decimal(decision.get("rounding_unit"), "decision.rounding_unit")
    bviv_score_min = _decimal(bviv.get("score_min"), "bviv.score_min")
    bviv_score_max = _decimal(bviv.get("score_max"), "bviv.score_max")
    bviv_modifier_min = _decimal(bviv.get("modifier_min"), "bviv.modifier_min")
    bviv_modifier_max = _decimal(
        bviv.get("modifier_max_v1"), "bviv.modifier_max_v1"
    )
    bviv_gate_drawdown = _decimal(
        bviv.get("gate_drawdown_pct"), "bviv.gate_drawdown_pct"
    )
    bviv_gate_fear_greed = _numeric_decimal(
        bviv.get("gate_fear_greed_max"), "bviv.gate_fear_greed_max"
    )
    weekly_min_early = _decimal(
        pacing.get("weekly_min_ratio_early"), "pacing.weekly_min_ratio_early"
    )
    weekly_min_late = _decimal(
        pacing.get("weekly_min_ratio_late"), "pacing.weekly_min_ratio_late"
    )
    weekly_soft_ratio = _decimal(
        pacing.get("weekly_soft_max_ratio"), "pacing.weekly_soft_max_ratio"
    )
    daily_hard_max = _decimal(budget.get("daily_hard_max"), "budget.daily_hard_max")
    weekly_hard_max = _decimal(
        budget.get("weekly_hard_max"), "budget.weekly_hard_max"
    )

    decimal_nonnegative = (
        base_dca,
        *weights,
        location_min,
        sentiment_one,
        atr_min,
        drop_min,
        adaptive_min,
        bviv_score_min,
        bviv_modifier_min,
        bviv_gate_drawdown,
        weekly_min_early,
    )
    if any(value < 0 for value in decimal_nonnegative):
        raise ConfigError("strategy decimal values that are minima must not be negative")
    if sum(weights) != Decimal("1") or any(value > 1 for value in weights):
        raise ConfigError("directional factor weights must be in 0..1 and sum to 1")
    if not location_max > location_min or not atr_max > atr_min or not drop_max > drop_min:
        raise ConfigError("factor score maxima must exceed their minima")
    if not Decimal("0") <= sentiment_one < sentiment_zero <= Decimal("100"):
        raise ConfigError("sentiment thresholds must satisfy 0 <= one < zero <= 100")
    if not bviv_score_max > bviv_score_min:
        raise ConfigError("bviv.score_max must exceed bviv.score_min")
    if not Decimal("0") <= bviv_modifier_min <= bviv_modifier_max <= Decimal("1"):
        raise ConfigError("BVIV modifiers must remain within 0..1 in v1")
    if adaptive_max < adaptive_min or rounding_unit <= 0:
        raise ConfigError("adaptive multiplier and rounding unit are invalid")
    if not Decimal("0") <= weekly_min_early <= weekly_min_late <= Decimal("1"):
        raise ConfigError("weekly minimum ratios must be ordered within 0..1")
    if weekly_soft_ratio < 1:
        raise ConfigError("weekly soft max ratio must be at least 1")

    integer_fields = {
        "decision.minimum_valid_directional_groups": decision.get(
            "minimum_valid_directional_groups"
        ),
        "pacing.acceleration_start_days": pacing.get("acceleration_start_days"),
        "pacing.full_pace_days": pacing.get("full_pace_days"),
        "factors.location.lookback_days": location.get("lookback_days"),
        "factors.shock.atr_period": shock.get("atr_period"),
    }
    if any(not isinstance(value, int) for value in integer_fields.values()):
        raise ConfigError("decision and pacing day/count fields must be integers")
    minimum_groups = integer_fields["decision.minimum_valid_directional_groups"]
    acceleration_days = integer_fields["pacing.acceleration_start_days"]
    full_pace_days = integer_fields["pacing.full_pace_days"]
    location_lookback_days = integer_fields["factors.location.lookback_days"]
    atr_period = integer_fields["factors.shock.atr_period"]
    if not 1 <= minimum_groups <= 3:
        raise ConfigError("minimum_valid_directional_groups must be in 1..3")
    if not acceleration_days > full_pace_days >= 1:
        raise ConfigError("pacing day thresholds are invalid")
    if location_lookback_days < 2 or atr_period < 2:
        raise ConfigError("indicator lookback periods must be at least 2")
    if base_dca < 0 or daily_hard_max < base_dca or weekly_hard_max <= 0:
        raise ConfigError("budget hard caps are invalid")

    required_flags = {
        "pacing.snapshot_weekly_target": True,
        "pacing.enable_capacity_check": True,
        "pacing.enable_minimum_required_today": True,
        "budget.final_day_override_daily_max": False,
        "budget.final_day_override_weekly_max": False,
        "budget.allow_soft_cap_feasibility_override": True,
        "budget.allow_negative_remaining": False,
    }
    for dotted, expected in required_flags.items():
        section_name, key = dotted.split(".")
        if raw[section_name].get(key) is not expected:
            raise ConfigError(f"{dotted} must be {str(expected).lower()}")
    if decision.get("rounding_mode") != "floor":
        raise ConfigError("decision.rounding_mode must be floor")
    if pacing.get("minimum_required_rounding") != "ceil":
        raise ConfigError("minimum_required_rounding must be ceil")
    if budget.get("week_start") != "monday":
        raise ConfigError("budget.week_start must be monday")
    if shock.get("combine_method") != "max" or shock.get("atr_smoothing") != "wilder_rma":
        raise ConfigError("approved shock methods are max and wilder_rma")
    if (
        btc_data.get("provider") != "coinbase_exchange"
        or btc_data.get("product") != "BTC-USD"
        or btc_data.get("automatic_fallback") != "none"
        or fear_greed_data.get("provider") != "alternative_me"
        or bviv_data.get("provider") != "volmex"
    ):
        raise ConfigError("canonical data providers do not match the approved design")
    freshness = (
        btc_data.get("reference_max_age_minutes"),
        fear_greed_data.get("max_age_hours"),
        bviv_data.get("primary_max_age_hours"),
        bviv_data.get("fallback_max_age_hours"),
    )
    if any(not isinstance(value, int) or value <= 0 for value in freshness):
        raise ConfigError("all data freshness limits must be positive integers")
    api_key_env = bviv_data.get("api_key_env")
    if api_key_env != "VOLMEX_API_KEY":
        raise ConfigError("data.bviv.api_key_env must be VOLMEX_API_KEY")

    timeout = runtime.get("http_timeout_seconds")
    attempts = runtime.get("http_max_attempts")
    delays = runtime.get("http_retry_delays_seconds")
    if not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError("runtime.http_timeout_seconds must be positive")
    if not isinstance(attempts, int) or attempts < 1:
        raise ConfigError("runtime.http_max_attempts must be positive")
    if (
        not isinstance(delays, list)
        or len(delays) != attempts - 1
        or any(not isinstance(value, int) or value < 0 for value in delays)
    ):
        raise ConfigError("runtime retry delays must match max attempts")

    total_days = (end_date - start_date).days + 1
    base_budget = base_dca * total_days
    if base_budget > initial_budget:
        raise ConfigError("base budget must not exceed initial budget")
    nominal_adaptive_daily = (initial_budget - base_budget) / total_days
    # Check the approved calendar can carry the initial budget under both caps.
    calendar_capacity = Decimal("0")
    cursor = start_date
    while cursor <= end_date:
        bucket_end = min(cursor + timedelta(days=6 - cursor.weekday()), end_date)
        active_days = (bucket_end - cursor).days + 1
        calendar_capacity += min(daily_hard_max * active_days, weekly_hard_max)
        cursor = bucket_end + timedelta(days=1)
    if initial_budget > calendar_capacity:
        raise ConfigError("initial plan is infeasible under configured hard caps")

    cutoff_time = _parse_time(plan.get("data_cutoff_time"), "plan.data_cutoff_time")
    window_end = _parse_time(
        plan.get("recommendation_window_end"),
        "plan.recommendation_window_end",
    )
    if window_end <= cutoff_time:
        raise ConfigError("recommendation window must end after cutoff")

    lock_filename = runtime.get("lock_filename")
    if not isinstance(lock_filename, str) or not lock_filename.endswith(".lock"):
        raise ConfigError("runtime.lock_filename must end in .lock")

    return RuntimeConfig(
        config_path=path,
        raw=raw,
        config_version=version,
        initial_budget=initial_budget,
        start_date=start_date,
        end_date=end_date,
        timezone=timezone,
        cutoff_time=cutoff_time,
        recommendation_window_end=window_end,
        base_dca=base_dca,
        nominal_adaptive_daily=nominal_adaptive_daily,
        factor_weights=weights,
        location_score_min_pct=location_min,
        location_score_max_pct=location_max,
        location_lookback_days=location_lookback_days,
        sentiment_score_zero_at=sentiment_zero,
        sentiment_score_one_at=sentiment_one,
        atr_score_min_multiple=atr_min,
        atr_score_max_multiple=atr_max,
        drop_score_min_pct=drop_min,
        drop_score_max_pct=drop_max,
        atr_period=atr_period,
        minimum_valid_directional_groups=minimum_groups,
        adaptive_multiplier_min=adaptive_min,
        adaptive_multiplier_max=adaptive_max,
        rounding_unit=rounding_unit,
        bviv_score_min=bviv_score_min,
        bviv_score_max=bviv_score_max,
        bviv_modifier_min=bviv_modifier_min,
        bviv_modifier_max=bviv_modifier_max,
        bviv_gate_drawdown_pct=bviv_gate_drawdown,
        bviv_gate_fear_greed_max=bviv_gate_fear_greed,
        acceleration_start_days=acceleration_days,
        full_pace_days=full_pace_days,
        weekly_min_ratio_early=weekly_min_early,
        weekly_min_ratio_late=weekly_min_late,
        weekly_soft_max_ratio=weekly_soft_ratio,
        daily_hard_max=daily_hard_max,
        weekly_hard_max=weekly_hard_max,
        btc_reference_max_age_minutes=freshness[0],
        fear_greed_max_age_hours=freshness[1],
        bviv_primary_max_age_hours=freshness[2],
        bviv_fallback_max_age_hours=freshness[3],
        volmex_api_key_env=api_key_env,
        http_timeout_seconds=timeout,
        http_max_attempts=attempts,
        http_retry_delays_seconds=tuple(delays),
        data_dir=_resolve_dir(path, runtime.get("data_dir"), "runtime.data_dir"),
        reports_dir=_resolve_dir(
            path, runtime.get("reports_dir"), "runtime.reports_dir"
        ),
        templates_dir=_resolve_dir(
            path, runtime.get("templates_dir"), "runtime.templates_dir"
        ),
        lock_filename=lock_filename,
    )
