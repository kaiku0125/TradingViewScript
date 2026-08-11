"""Pure Smart DCA Decision Engine orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from .budget import (
    BudgetGuardResult,
    CapacityResult,
    WeeklyTarget,
    apply_budget_guard,
    calculate_capacity,
)
from .config import RuntimeConfig
from .indicators import IndicatorResult, MarketInputs, calculate_indicators


ZERO = Decimal("0")


def _canonical(value: Decimal | None, places: int = 8) -> str | None:
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum), "f")


def _decimal_dict(value: object) -> object:
    if isinstance(value, Decimal):
        return _canonical(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _decimal_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class PortfolioInputs:
    remaining_funds_usd: Decimal
    actual_invested_this_week_usd: Decimal
    actual_invested_today_usd: Decimal
    data_status: str = "valid"


@dataclass(frozen=True)
class DecisionResult:
    plan_date: date
    config_version: str
    decision_status: str
    indicators: IndicatorResult
    base_amount_usd: Decimal
    adaptive_multiplier: Decimal
    market_adaptive_amount_usd: Decimal
    market_amount_usd: Decimal
    capacity: CapacityResult | None
    budget_guard: BudgetGuardResult | None
    final_suggested_usd: Decimal | None
    remaining_to_execute_today_usd: Decimal | None
    reason_codes: tuple[str, ...]
    reason_summary: str

    def as_dict(self) -> dict:
        """Return stable JSON-ready numeric fields for later DecisionRecord assembly."""
        indicator_values = {
            key: _decimal_dict(value)
            for key, value in asdict(self.indicators).items()
        }
        capacity_values = (
            None
            if self.capacity is None
            else {
                key: _decimal_dict(value)
                for key, value in asdict(self.capacity).items()
            }
        )
        guard_values = (
            None
            if self.budget_guard is None
            else {
                key: _decimal_dict(value)
                for key, value in asdict(self.budget_guard).items()
            }
        )
        return {
            "plan_date": self.plan_date.isoformat(),
            "config_version": self.config_version,
            "decision_status": self.decision_status,
            "scores": indicator_values,
            "market_amounts": {
                "base_amount_usd": _canonical(self.base_amount_usd),
                "adaptive_multiplier": _canonical(self.adaptive_multiplier),
                "market_adaptive_amount_usd": _canonical(
                    self.market_adaptive_amount_usd
                ),
                "market_amount_usd": _canonical(self.market_amount_usd),
                "bviv_modifier": _canonical(self.indicators.bviv_modifier),
            },
            "capacity": capacity_values,
            "pacing": guard_values,
            "final_suggested_usd": _canonical(self.final_suggested_usd, 2),
            "remaining_to_execute_today_usd": _canonical(
                self.remaining_to_execute_today_usd, 2
            ),
            "reason_codes": list(self.reason_codes),
            "reason_summary": self.reason_summary,
        }


def _reason_codes(
    indicators: IndicatorResult,
    market: MarketInputs,
    capacity: CapacityResult | None,
    guard: BudgetGuardResult | None,
) -> list[str]:
    reasons: list[str] = []
    if indicators.location_score is not None and indicators.location_score > 0:
        reasons.append("LOCATION_DRAWDOWN")
    if indicators.sentiment_score is not None and indicators.sentiment_score > 0:
        reasons.append("SENTIMENT_FEAR")
    if indicators.shock_score is not None and indicators.shock_score > 0:
        reasons.append("SHOCK_DAILY_DROP")
    if indicators.atr_degraded:
        reasons.append("SHOCK_ATR_DEGRADED")
    if market.bviv is None:
        reasons.append("BVIV_NEUTRAL_MISSING")
    elif market.bviv_fallback_used:
        reasons.append("BVIV_FALLBACK")
    elif indicators.bviv_modifier < Decimal("1"):
        reasons.append("BVIV_SUPPRESSED")
    if guard is not None:
        if guard.weekly_catchup_usd >= max(
            guard.pace_floor_usd, guard.guard_candidate_usd
        ):
            reasons.append("WEEKLY_CATCHUP")
        if capacity is not None and capacity.minimum_required_today_usd > 0:
            reasons.append("CAPACITY_MINIMUM")
        if guard.soft_cap_overridden_for_feasibility:
            reasons.append("SOFT_CAP_OVERRIDDEN")
        if guard.hard_cap_applied:
            reasons.append("HARD_CAP_APPLIED")
    if capacity is not None and not capacity.plan_feasible:
        reasons.append("PLAN_INFEASIBLE")
    return reasons


def calculate_decision(
    *,
    plan_date: date,
    market: MarketInputs,
    portfolio: PortfolioInputs,
    weekly_target: WeeklyTarget,
    config: RuntimeConfig,
) -> DecisionResult:
    """Calculate a deterministic decision from normalized, pre-cutoff inputs."""
    if not config.start_date <= plan_date <= config.end_date:
        raise ValueError("plan_date is outside the configured plan")
    if portfolio.remaining_funds_usd < 0:
        raise ValueError("remaining funds must not be negative")
    if (
        portfolio.actual_invested_this_week_usd < 0
        or portfolio.actual_invested_today_usd < 0
    ):
        raise ValueError("actual investment inputs must not be negative")
    if not weekly_target.week_start <= plan_date <= weekly_target.week_end:
        raise ValueError("weekly target does not cover plan_date")

    indicators = calculate_indicators(market, config)
    blocked = (
        market.reference_price is None
        or not market.reference_price.is_finite()
        or market.reference_price <= 0
        or portfolio.data_status != "valid"
    )
    if blocked:
        reasons = ("BTC_REFERENCE_INVALID",) if portfolio.data_status == "valid" else (
            "PORTFOLIO_STATE_INVALID",
        )
        return DecisionResult(
            plan_date=plan_date,
            config_version=config.config_version,
            decision_status="blocked",
            indicators=indicators,
            base_amount_usd=config.base_dca,
            adaptive_multiplier=ZERO,
            market_adaptive_amount_usd=ZERO,
            market_amount_usd=ZERO,
            capacity=None,
            budget_guard=None,
            final_suggested_usd=None,
            remaining_to_execute_today_usd=None,
            reason_codes=reasons,
            reason_summary="Decision blocked by invalid canonical input.",
        )

    if indicators.directional_score is None:
        adaptive_multiplier = ZERO
        adaptive_amount = ZERO
    else:
        adaptive_multiplier = config.adaptive_multiplier_min + (
            indicators.directional_score
            * (config.adaptive_multiplier_max - config.adaptive_multiplier_min)
        )
        adaptive_amount = (
            config.nominal_adaptive_daily
            * adaptive_multiplier
            * indicators.bviv_modifier
        )
    market_amount = config.base_dca + adaptive_amount
    capacity = calculate_capacity(
        plan_date,
        portfolio.remaining_funds_usd,
        portfolio.actual_invested_this_week_usd,
        config,
    )
    guard = apply_budget_guard(
        plan_date=plan_date,
        remaining_funds=portfolio.remaining_funds_usd,
        actual_invested_this_week=portfolio.actual_invested_this_week_usd,
        market_amount=market_amount,
        weekly_target=weekly_target,
        capacity=capacity,
        config=config,
    )

    if portfolio.remaining_funds_usd <= 0:
        status = "completed"
    elif not capacity.plan_feasible:
        status = "plan_infeasible"
    elif indicators.directional_score is None:
        status = "base_only"
    elif (
        indicators.valid_directional_groups == 2
        or indicators.atr_degraded
        or market.bviv is None
        or market.bviv_fallback_used
    ):
        status = "degraded"
    else:
        status = "normal"

    reasons = _reason_codes(indicators, market, capacity, guard)
    if status == "completed":
        reasons.append("PLAN_COMPLETED")
    if status == "base_only":
        reasons.append("INSUFFICIENT_DIRECTIONAL_GROUPS")
    final = guard.final_suggested_usd
    remaining_to_execute = max(
        ZERO, final - portfolio.actual_invested_today_usd
    )
    return DecisionResult(
        plan_date=plan_date,
        config_version=config.config_version,
        decision_status=status,
        indicators=indicators,
        base_amount_usd=config.base_dca,
        adaptive_multiplier=adaptive_multiplier,
        market_adaptive_amount_usd=adaptive_amount,
        market_amount_usd=market_amount,
        capacity=capacity,
        budget_guard=guard,
        final_suggested_usd=final,
        remaining_to_execute_today_usd=remaining_to_execute,
        reason_codes=tuple(reasons),
        reason_summary=(
            f"{status}: suggest {format(final, 'f')} USD after pacing and hard caps."
        ),
    )
