"""Exact decimal parsing and canonical formatting."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .errors import UserInputError


def parse_decimal_string(
    value: object,
    *,
    field: str,
    max_places: int,
    positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise UserInputError(f"{field} must be a plain decimal string")
    if "e" in value.lower() or value.startswith("+"):
        raise UserInputError(f"{field} must not use exponent or plus notation")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise UserInputError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise UserInputError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise UserInputError(f"{field} must be greater than zero")
    if not positive and parsed < 0:
        raise UserInputError(f"{field} must not be negative")
    places = max(0, -parsed.as_tuple().exponent)
    if places > max_places:
        raise UserInputError(f"{field} supports at most {max_places} decimal places")
    return parsed


def canonical_decimal(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum), "f")


def canonical_usd(value: object, *, positive: bool = False) -> str:
    parsed = parse_decimal_string(
        value, field="usd_amount", max_places=2, positive=positive
    )
    return canonical_decimal(parsed, 2)


def canonical_btc(value: object, *, positive: bool = False) -> str:
    parsed = parse_decimal_string(
        value, field="btc_quantity", max_places=8, positive=positive
    )
    return canonical_decimal(parsed, 8)

