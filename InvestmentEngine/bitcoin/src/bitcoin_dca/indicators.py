"""Pure Smart DCA indicator calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .config import RuntimeConfig


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def clamp(value: Decimal, lower: Decimal = ZERO, upper: Decimal = ONE) -> Decimal:
    return min(max(value, lower), upper)


def linear_score(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if upper <= lower:
        raise ValueError("linear score upper bound must exceed lower bound")
    return clamp((value - lower) / (upper - lower))


@dataclass(frozen=True)
class MarketInputs:
    reference_price: Decimal | None
    previous_reference_price: Decimal | None
    recent_high: Decimal | None
    atr: Decimal | None
    fear_greed: Decimal | None
    bviv: Decimal | None
    bviv_fallback_used: bool = False


@dataclass(frozen=True)
class IndicatorResult:
    drawdown_pct: Decimal | None
    daily_drop_pct: Decimal | None
    atr_pct: Decimal | None
    down_atr_multiple: Decimal | None
    location_score: Decimal | None
    sentiment_score: Decimal | None
    atr_drop_score: Decimal | None
    absolute_drop_score: Decimal | None
    shock_score: Decimal | None
    directional_score: Decimal | None
    valid_directional_groups: int
    atr_degraded: bool
    downside_gate: bool
    bviv_level: Decimal | None
    bviv_modifier: Decimal


def _positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def calculate_indicators(
    inputs: MarketInputs, config: RuntimeConfig
) -> IndicatorResult:
    """Calculate scores without I/O or time-dependent state."""
    reference_valid = _positive(inputs.reference_price)
    previous_valid = _positive(inputs.previous_reference_price)
    high_valid = _positive(inputs.recent_high)
    atr_valid = _positive(inputs.atr)
    fear_valid = (
        inputs.fear_greed is not None
        and inputs.fear_greed.is_finite()
        and ZERO <= inputs.fear_greed <= HUNDRED
    )
    bviv_valid = inputs.bviv is not None and inputs.bviv.is_finite() and inputs.bviv >= 0

    drawdown = None
    location_score = None
    if reference_valid and high_valid:
        drawdown = max(
            ZERO,
            (inputs.recent_high - inputs.reference_price)
            / inputs.recent_high
            * HUNDRED,
        )
        location_score = linear_score(
            drawdown,
            config.location_score_min_pct,
            config.location_score_max_pct,
        )

    sentiment_score = None
    if fear_valid:
        sentiment_score = clamp(
            (config.sentiment_score_zero_at - inputs.fear_greed)
            / (config.sentiment_score_zero_at - config.sentiment_score_one_at)
        )

    daily_drop = None
    absolute_drop_score = None
    atr_pct = None
    down_atr_multiple = None
    atr_drop_score = None
    shock_score = None
    atr_degraded = False
    if reference_valid and previous_valid:
        daily_drop = max(
            ZERO,
            (inputs.previous_reference_price - inputs.reference_price)
            / inputs.previous_reference_price
            * HUNDRED,
        )
        absolute_drop_score = linear_score(
            daily_drop, config.drop_score_min_pct, config.drop_score_max_pct
        )
        if atr_valid:
            atr_pct = inputs.atr / inputs.previous_reference_price * HUNDRED
            if atr_pct > 0:
                down_atr_multiple = daily_drop / atr_pct
                atr_drop_score = linear_score(
                    down_atr_multiple,
                    config.atr_score_min_multiple,
                    config.atr_score_max_multiple,
                )
        if atr_drop_score is None:
            atr_degraded = True
            shock_score = absolute_drop_score
        else:
            shock_score = max(atr_drop_score, absolute_drop_score)

    scores = (location_score, sentiment_score, shock_score)
    valid_groups = sum(score is not None for score in scores)
    directional_score = None
    if valid_groups >= config.minimum_valid_directional_groups:
        weighted = ZERO
        active_weight = ZERO
        for score, weight in zip(scores, config.factor_weights):
            if score is not None:
                weighted += score * weight
                active_weight += weight
        with localcontext() as context:
            context.prec = 28
            directional_score = weighted / active_weight

    downside_gate = bool(
        (daily_drop is not None and daily_drop > 0)
        or (drawdown is not None and drawdown >= config.bviv_gate_drawdown_pct)
        or (fear_valid and inputs.fear_greed <= config.bviv_gate_fear_greed_max)
    )
    bviv_level = None
    bviv_modifier = config.bviv_modifier_max
    if bviv_valid:
        bviv_level = linear_score(
            inputs.bviv, config.bviv_score_min, config.bviv_score_max
        )
        if not downside_gate:
            suppression_range = config.bviv_modifier_max - config.bviv_modifier_min
            bviv_modifier = config.bviv_modifier_max - suppression_range * bviv_level

    return IndicatorResult(
        drawdown_pct=drawdown,
        daily_drop_pct=daily_drop,
        atr_pct=atr_pct,
        down_atr_multiple=down_atr_multiple,
        location_score=location_score,
        sentiment_score=sentiment_score,
        atr_drop_score=atr_drop_score,
        absolute_drop_score=absolute_drop_score,
        shock_score=shock_score,
        directional_score=directional_score,
        valid_directional_groups=valid_groups,
        atr_degraded=atr_degraded,
        downside_gate=downside_gate,
        bviv_level=bviv_level,
        bviv_modifier=bviv_modifier,
    )
