"""Structural validation applied to every provider response before accepting it.

A response is rejected (as a :class:`SchemaError`, which triggers failover) when
it is empty or contains a negative price, a negative volume or a bar whose high
is below its low. Dates are then canonicalised to be sorted and unique: chunked
requests can legitimately return a shared boundary day, so duplicates are
collapsed (last value wins) instead of being treated as corrupt.
"""

from __future__ import annotations

from data.errors import EmptyResultError, SchemaError
from data.models import PriceBar


def canonicalize_price_bars(bars: list[PriceBar], *, provider: str) -> list[PriceBar]:
    """Validate ``bars`` and return them sorted ascending with unique dates.

    Raises:
        EmptyResultError: When ``bars`` is empty.
        SchemaError: When any bar has a negative price/volume or ``high < low``.
    """
    if not bars:
        raise EmptyResultError("provider returned no rows", provider=provider)
    for bar in bars:
        if min(bar.open, bar.high, bar.low, bar.close, bar.adj_close) < 0:
            raise SchemaError(
                f"negative price on {bar.date.isoformat()}", provider=provider
            )
        if bar.volume < 0:
            raise SchemaError(
                f"negative volume on {bar.date.isoformat()}", provider=provider
            )
        if bar.high < bar.low:
            raise SchemaError(
                f"high < low on {bar.date.isoformat()}", provider=provider
            )
    by_date = {bar.date: bar for bar in bars}
    return [by_date[day] for day in sorted(by_date)]
