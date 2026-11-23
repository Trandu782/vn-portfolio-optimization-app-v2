"""Vietnamese cost model: brokerage fee on both sides plus the sell tax on sells.

The brokerage fee is the user's per-side rate from ``UserSettings``; the sell tax
is the 0.1% (``DEFAULT_MARKET_RULES.sell_tax``) charged on sell value. Both are
passed in explicitly by the engine and applied to the whole-VND order value with
``core.costs.commission`` (round half up).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from core.costs import commission
from core.rebalance.interfaces import (
    CostModel,
    OrderCost,
    OrderSide,
    cost_models,
)


class VnCostParams(BaseModel):
    """The VN cost model has no user options.

    The fee comes from ``UserSettings`` and the sell tax from ``market_rules``, so
    there is nothing to configure here. The empty schema is still published so the
    UI renders the entry like every other registry option.
    """


@cost_models.register(
    id="vn",
    name="Vietnam brokerage + sell tax",
    description=(
        "Brokerage fee on both sides from your settings, plus the 0.1% sell tax "
        "from market rules on sell orders."
    ),
    parameter_schema=VnCostParams,
)
class VnCostModel:
    """Brokerage commission on buys and sells, sell tax on sells only."""

    id = "vn"

    def __init__(self, *, brokerage_fee_rate: Decimal, sell_tax: Decimal) -> None:
        self._brokerage_fee_rate = brokerage_fee_rate
        self._sell_tax = sell_tax

    def estimate(self, value: int, side: OrderSide) -> OrderCost:
        """Return the fee (both sides) and tax (sells only) for ``value`` VND."""
        fee = commission(value, self._brokerage_fee_rate)
        tax = commission(value, self._sell_tax) if side == "sell" else 0
        return OrderCost(fee=fee, tax=tax)


def build(brokerage_fee_rate: Decimal, sell_tax: Decimal) -> CostModel:
    """Return a ready-to-use VN cost model (convenience for tests)."""
    return VnCostModel(brokerage_fee_rate=brokerage_fee_rate, sell_tax=sell_tax)


__all__ = ["VnCostModel", "VnCostParams", "build"]
