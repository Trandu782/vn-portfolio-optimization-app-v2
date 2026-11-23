"""Read-side helper for the V2 acceptance criteria.

Given a ticker and a date range, return adjusted simple returns, the rolling liquidity
medians, market cap/shares and the ICB level-2 sector, with the basis and provenance
flags for every dataset. This reads only the precomputed V2 tables; it never fetches.

If a date bound is omitted it is taken from the stored series (the full available
range). An unknown ticker or a ticker with no stored prices returns a snapshot with an
empty return list rather than raising, so a caller can show "no data yet" honestly.
"""

from __future__ import annotations

from datetime import date
from typing import cast

from sqlalchemy.orm import Session, sessionmaker

from data.db.base import session_scope
from data.v2.precompute_schemas import (
    CoverageSummary,
    PriceAdjustmentBasis,
    ReturnPoint,
    TickerSnapshot,
)
from data.v2.returns import daily_returns
from data.v2.store import V2Store


class V2Reader:
    """Serve the precomputed snapshot for one ticker and range."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def snapshot(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> TickerSnapshot:
        """Return adjusted returns, liquidity, market cap and sector for ``symbol``."""
        code = symbol.strip().upper()
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            earliest = store.earliest_price_date(code)
            latest = store.latest_price_date(code)
            resolved_start = start or earliest
            resolved_end = end or latest
            bars = (
                store.get_prices(code, resolved_start, resolved_end)
                if resolved_start and resolved_end
                else []
            )
            sector = store.get_sector(code)
            liquidity = store.get_liquidity(code)
            market_cap = store.get_market_cap(code)
            source, price_basis, data_as_of = store.latest_price_meta(code)
        returns = [ReturnPoint(date=item.date, value=item.value) for item in daily_returns(bars)]
        return TickerSnapshot(
            symbol=code,
            start=resolved_start or date.min,
            end=resolved_end or date.min,
            sector=sector.icb_level2_name if sector else None,
            sector_source=sector.source if sector else None,
            market_cap=market_cap.market_cap if market_cap else None,
            shares_outstanding=market_cap.shares_outstanding if market_cap else None,
            market_cap_basis=market_cap.basis if market_cap else None,
            liquidity=liquidity,
            price_adjustment_basis=cast(PriceAdjustmentBasis | None, price_basis),
            volume_basis=liquidity.volume_basis if liquidity else None,
            data_as_of=data_as_of,
            source=source,
            returns=returns,
        )


def ticker_snapshot(
    session_factory: sessionmaker[Session],
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> TickerSnapshot:
    """Convenience wrapper around :meth:`V2Reader.snapshot`."""
    return V2Reader(session_factory).snapshot(symbol, start, end)


def sector_coverage(session_factory: sessionmaker[Session]) -> CoverageSummary:
    """Return how many universe tickers have an ICB level-2 sector (and which do not)."""
    with session_scope(session_factory) as session:
        store = V2Store(session)
        master = {record.ticker for record in store.list_ticker_master()}
        sectors = {sector.ticker for sector in store.list_sectors()}
    missing = sorted(master - sectors)
    return CoverageSummary(
        covered=len(master & sectors),
        missing=len(missing),
        missing_tickers=missing,
    )


__all__ = ["V2Reader", "sector_coverage", "ticker_snapshot"]
