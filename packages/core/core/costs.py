"""Trading cost models.

Every function takes the user's brokerage fee rate as an explicit parameter,
sourced from ``core.settings.UserSettings`` at the call site. No module reads it
from a global constant or from ``market_rules``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def commission(notional: int, brokerage_fee_rate: Decimal) -> int:
    """Return the whole-dong brokerage commission for one side of a trade.

    Args:
        notional: Traded value in VND.
        brokerage_fee_rate: The user's per-side fee as a fraction (0.0015 ==
            0.15%), taken from ``UserSettings.brokerage_fee_rate``.

    Returns:
        The commission in whole VND, rounded half up.
    """
    exact = Decimal(notional) * brokerage_fee_rate
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_trip_commission(notional: int, brokerage_fee_rate: Decimal) -> int:
    """Return the commission for a buy and a sell of ``notional`` (two sides)."""
    return commission(notional, brokerage_fee_rate) * 2
