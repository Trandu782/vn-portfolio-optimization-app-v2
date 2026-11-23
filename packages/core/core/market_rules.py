"""Market structure rules for the Vietnamese exchanges.

These values describe the mechanics of the exchanges (lot sizes, the sell tax
and the daily price limits) and the set of trading holidays. They are stored
centrally so no module hardcodes them. The daily price limits and the holiday
calendar are recorded for V1 but are not yet consumed by any feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ExchangeRules:
    """Mechanical rules that apply to a single exchange."""

    code: str
    lot_size: int
    daily_price_limit: Decimal
    """Daily price limit as a fraction of the reference price (e.g. 0.07 == 7%)."""


@dataclass(frozen=True)
class MarketRules:
    """Aggregate market rules shared by the whole optimizer."""

    exchanges: Mapping[str, ExchangeRules]
    sell_tax: Decimal
    """Sell-side tax as a fraction of trade value (0.001 == 0.1%)."""
    trading_holidays: frozenset[date]
    """Illustrative exchange holidays. Unused in V1; keep in sync with the official calendar."""


# Illustrative Vietnamese public holidays on which HOSE/HNX/UPCoM are closed.
# Not consumed by V1 features; replace with the official exchange calendar.
_TRADING_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2025, 1, 1),  # New Year's Day
        date(2025, 1, 28),  # Lunar New Year (Tet) period
        date(2025, 1, 29),
        date(2025, 1, 30),
        date(2025, 1, 31),
        date(2025, 2, 3),
        date(2025, 4, 7),  # Hung Kings' Commemoration Day
        date(2025, 4, 30),  # Reunification Day
        date(2025, 5, 1),  # International Labour Day
        date(2025, 9, 2),  # National Day
    }
)


DEFAULT_MARKET_RULES = MarketRules(
    exchanges={
        "HOSE": ExchangeRules(code="HOSE", lot_size=100, daily_price_limit=Decimal("0.07")),
        "HNX": ExchangeRules(code="HNX", lot_size=100, daily_price_limit=Decimal("0.10")),
        "UPCoM": ExchangeRules(code="UPCoM", lot_size=100, daily_price_limit=Decimal("0.15")),
    },
    sell_tax=Decimal("0.001"),
    trading_holidays=_TRADING_HOLIDAYS,
)
