"""Lot rounding: turn portfolio weights into integer lots and residual cash.

Vietnamese exchanges trade in whole lots (100 shares today), so a weight vector
must be converted to integer lots before it becomes an order. Rounding always
rounds *down* to the nearest whole lot, so a rounded position can never exceed the
target value and therefore can never breach a `max_weight` cap. A small position
can round to zero shares, which only ever reduces the number of holdings. The money
left over is reported as residual cash.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class LotRoundingResult:
    """Integer lots, whole shares, invested value and leftover cash per symbol."""

    lots: Mapping[str, int]
    shares: Mapping[str, int]
    values: Mapping[str, float]
    residual_cash: int


def round_to_lots(
    weights: Mapping[str, float],
    prices: Mapping[str, float],
    capital: float,
    lot_sizes: Mapping[str, int],
) -> LotRoundingResult:
    """Convert ``weights`` over ``capital`` into whole lots at ``prices``.

    Args:
        weights: Target weight per symbol (fractions of ``capital``).
        prices: Price per share in VND; a missing or non-positive price yields 0.
        capital: Investable capital in VND.
        lot_sizes: Lot size per symbol; a missing or non-positive lot yields 0.

    Returns:
        A :class:`LotRoundingResult`. ``residual_cash`` is the whole-VND amount
        that could not be deployed into whole lots.
    """
    lots: dict[str, int] = {}
    shares: dict[str, int] = {}
    values: dict[str, float] = {}
    invested = 0.0
    for symbol, weight in weights.items():
        price = prices.get(symbol)
        lot_size = lot_sizes.get(symbol, 0)
        target_value = max(0.0, weight) * capital
        if price is None or price <= 0.0 or lot_size <= 0 or target_value <= 0.0:
            lots[symbol] = 0
            shares[symbol] = 0
            values[symbol] = 0.0
            continue
        unit = price * float(lot_size)
        count = math.floor(target_value / unit)
        # Guard against floating-point overshoot so the value never exceeds target.
        while count > 0 and count * unit > target_value:
            count -= 1
        value = float(count) * unit
        lots[symbol] = count
        shares[symbol] = count * lot_size
        values[symbol] = value
        invested += value
    residual_cash = round(capital - invested)
    if residual_cash < 0:
        residual_cash = 0
    return LotRoundingResult(
        lots=lots, shares=shares, values=values, residual_cash=residual_cash
    )
