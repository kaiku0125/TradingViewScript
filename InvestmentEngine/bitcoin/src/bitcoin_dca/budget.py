"""Pure weekly pacing, capacity, and Budget Guard rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .config import RuntimeConfig


ZERO = Decimal("0")


def floor_to_unit(value: Decimal, unit: Decimal) -> Decimal:
    return (value / unit).to_integral_value(rounding=ROUND_FLOOR) * unit


def ceil_to_unit(value: Decimal, unit: Decimal) -> Decimal:
    return (value / unit).to_integral_value(rounding=ROUND_CEILING) * unit


def clipped_week(plan_date: date, config: RuntimeConfig) -> tuple[date, date]:
    monday = plan_date - timedelta(days=plan_date.weekday())
    sunday = monday + timedelta(days=6)
    return max(monday, config.start_date), min(sunday, config.end_date)


def weekly_min_ratio(days_remaining: int, config: RuntimeConfig) -> Decimal:
    if days_remaining >= config.acceleration_start_days:
        return config.weekly_min_ratio_early
    if days_remaining <= config.full_pace_days:
        return config.weekly_min_ratio_late
    urgency = Decimal(config.acceleration_start_days - days_remaining) / Decimal(
        config.acceleration_start_days - config.full_pace_days
    )
    return config.weekly_min_ratio_early + urgency * (
        config.weekly_min_ratio_late - config.weekly_min_ratio_early
    )


@dataclass(frozen=True)
class WeeklyTarget:
    week_start: date
    week_end: date
    remaining_funds_at_week_start_usd: Decimal
    active_days_in_week: int
    total_days_remaining: int
    weekly_target_usd: Decimal
    weekly_min_ratio: Decimal
    weekly_min_usd: Decimal
    weekly_soft_max_usd: Decimal
    weekly_hard_max_usd: Decimal


def create_weekly_target(
    plan_date: date,
    remaining_funds_at_week_start: Decimal,
    config: RuntimeConfig,
) -> WeeklyTarget:
    if not config.start_date <= plan_date <= config.end_date:
        raise ValueError("plan_date is outside the configured plan")
    if remaining_funds_at_week_start < 0:
        raise ValueError("remaining funds must not be negative")
    week_start, week_end = clipped_week(plan_date, config)
    if plan_date != week_start:
        raise ValueError("weekly target must be created on the first active day")
    active_days = (week_end - week_start).days + 1
    days_remaining = (config.end_date - plan_date).days + 1
    target_exact = remaining_funds_at_week_start * Decimal(active_days) / Decimal(
        days_remaining
    )
    target = floor_to_unit(target_exact, config.rounding_unit)
    minimum_ratio = weekly_min_ratio(days_remaining, config)
    minimum = ceil_to_unit(target_exact * minimum_ratio, config.rounding_unit)
    soft_max = floor_to_unit(
        min(target_exact * config.weekly_soft_max_ratio, config.weekly_hard_max),
        config.rounding_unit,
    )
    return WeeklyTarget(
        week_start=week_start,
        week_end=week_end,
        remaining_funds_at_week_start_usd=remaining_funds_at_week_start,
        active_days_in_week=active_days,
        total_days_remaining=days_remaining,
        weekly_target_usd=target,
        weekly_min_ratio=minimum_ratio,
        weekly_min_usd=minimum,
        weekly_soft_max_usd=soft_max,
        weekly_hard_max_usd=config.weekly_hard_max,
    )


@dataclass(frozen=True)
class CapacityResult:
    days_remaining: int
    active_days_remaining_in_week: int
    weekly_hard_remaining_usd: Decimal
    current_week_future_capacity_usd: Decimal
    future_week_capacity_usd: Decimal
    total_capacity_including_today_usd: Decimal
    today_hard_capacity_usd: Decimal
    minimum_required_today_usd: Decimal
    plan_feasible: bool


def calculate_capacity(
    plan_date: date,
    remaining_funds: Decimal,
    actual_invested_this_week: Decimal,
    config: RuntimeConfig,
) -> CapacityResult:
    if not config.start_date <= plan_date <= config.end_date:
        raise ValueError("plan_date is outside the configured plan")
    if remaining_funds < 0 or actual_invested_this_week < 0:
        raise ValueError("portfolio amounts must not be negative")
    _, week_end = clipped_week(plan_date, config)
    future_days_current_week = (week_end - plan_date).days
    weekly_remaining = max(
        ZERO, config.weekly_hard_max - actual_invested_this_week
    )
    current_future_capacity = min(
        Decimal(future_days_current_week) * config.daily_hard_max,
        weekly_remaining,
    )

    future_capacity = ZERO
    cursor = week_end + timedelta(days=1)
    while cursor <= config.end_date:
        _, bucket_end = clipped_week(cursor, config)
        bucket_days = (bucket_end - cursor).days + 1
        future_capacity += min(
            Decimal(bucket_days) * config.daily_hard_max,
            config.weekly_hard_max,
        )
        cursor = bucket_end + timedelta(days=1)

    current_including_today = min(
        Decimal(future_days_current_week + 1) * config.daily_hard_max,
        weekly_remaining,
    )
    total_capacity = current_including_today + future_capacity
    minimum_required = ceil_to_unit(
        max(ZERO, remaining_funds - current_future_capacity - future_capacity),
        config.rounding_unit,
    )
    today_capacity = min(
        remaining_funds, config.daily_hard_max, weekly_remaining
    )
    feasible = (
        remaining_funds <= total_capacity
        and minimum_required <= today_capacity
    )
    return CapacityResult(
        days_remaining=(config.end_date - plan_date).days + 1,
        active_days_remaining_in_week=future_days_current_week + 1,
        weekly_hard_remaining_usd=weekly_remaining,
        current_week_future_capacity_usd=current_future_capacity,
        future_week_capacity_usd=future_capacity,
        total_capacity_including_today_usd=total_capacity,
        today_hard_capacity_usd=today_capacity,
        minimum_required_today_usd=minimum_required,
        plan_feasible=feasible,
    )


@dataclass(frozen=True)
class BudgetGuardResult:
    required_daily_pace_usd: Decimal
    pace_floor_usd: Decimal
    weekly_gap_usd: Decimal
    weekly_catchup_usd: Decimal
    weekly_soft_remaining_usd: Decimal
    effective_weekly_soft_remaining_usd: Decimal
    soft_cap_overridden_for_feasibility: bool
    guard_candidate_usd: Decimal
    final_suggested_usd: Decimal
    hard_cap_applied: bool


def apply_budget_guard(
    *,
    plan_date: date,
    remaining_funds: Decimal,
    actual_invested_this_week: Decimal,
    market_amount: Decimal,
    weekly_target: WeeklyTarget,
    capacity: CapacityResult,
    config: RuntimeConfig,
) -> BudgetGuardResult:
    required_daily_pace = remaining_funds / Decimal(capacity.days_remaining)
    pace_floor = required_daily_pace * weekly_target.weekly_min_ratio
    weekly_gap = max(
        ZERO, weekly_target.weekly_min_usd - actual_invested_this_week
    )
    weekly_catchup = weekly_gap / Decimal(
        capacity.active_days_remaining_in_week
    )
    weekly_soft_remaining = max(
        ZERO, weekly_target.weekly_soft_max_usd - actual_invested_this_week
    )
    override = capacity.minimum_required_today_usd > weekly_soft_remaining
    effective_soft = weekly_soft_remaining
    if override:
        effective_soft = min(
            capacity.minimum_required_today_usd,
            capacity.weekly_hard_remaining_usd,
        )
    candidate = max(
        market_amount,
        pace_floor,
        weekly_catchup,
        capacity.minimum_required_today_usd,
    )
    if plan_date == config.end_date:
        candidate = remaining_funds
        limits = (
            remaining_funds,
            config.daily_hard_max,
            capacity.weekly_hard_remaining_usd,
        )
    else:
        limits = (
            candidate,
            remaining_funds,
            config.daily_hard_max,
            capacity.weekly_hard_remaining_usd,
            effective_soft,
        )
    bounded = min(limits)
    final = floor_to_unit(max(ZERO, bounded), config.rounding_unit)
    return BudgetGuardResult(
        required_daily_pace_usd=required_daily_pace,
        pace_floor_usd=pace_floor,
        weekly_gap_usd=weekly_gap,
        weekly_catchup_usd=weekly_catchup,
        weekly_soft_remaining_usd=weekly_soft_remaining,
        effective_weekly_soft_remaining_usd=effective_soft,
        soft_cap_overridden_for_feasibility=override,
        guard_candidate_usd=candidate,
        final_suggested_usd=final,
        hard_cap_applied=final < floor_to_unit(candidate, config.rounding_unit),
    )
