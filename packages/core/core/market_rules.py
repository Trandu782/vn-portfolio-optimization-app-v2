"""Market structure rules for the Vietnamese exchanges.

These values describe the mechanics of the exchanges (lot sizes, the sell tax
and the daily price limits) and the set of trading holidays. They are stored
centrally so no module hardcodes them. The daily price limits and the holiday
calendar are recorded for V1 but are not yet consumed by any feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time
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
    session_close: time = time(15, 0)
    """Local (ICT) wall-clock time at which a session's end-of-day bars exist.

    HOSE, HNX and UPCoM run the closing auction from 14:45 and publish the official
    close at 15:00, so a bar for today cannot exist before this time. The precompute
    pipeline uses it to target the last *completed* session, so a run dispatched
    before the close never asks upstream for a bar that cannot exist yet.
    """


# Illustrative Vietnamese public holidays on which HOSE/HNX/UPCoM are closed.
# Kept in sync with the observed exchange calendar: a date that really traded must
# never be listed here (it would hide a genuinely stale price series). The fixed
# solar-calendar holidays are always correct; Tet and ad-hoc closures are added as
# they are confirmed. ``2026-11-24`` is a confirmed non-trading holiday, so the
# freshness checks expect ``2026-11-25`` as the next valid session.
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
        date(2026, 1, 1),  # New Year's Day
        date(2026, 4, 30),  # Reunification Day
        date(2026, 5, 1),  # International Labour Day
        date(2026, 9, 2),  # National Day
        date(2026, 11, 24),  # Confirmed market holiday (Tue); 2026-11-25 is a session
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
