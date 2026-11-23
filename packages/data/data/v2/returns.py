"""Per-ticker simple daily returns from adjusted closes.

The V2 precompute pipeline stores adjusted daily bars; returns are a pure function of
those bars, so they are derived on read instead of being duplicated in storage (see
``docs/DECISIONS.md``). Only **simple** daily returns are used (CFA Level 1/2),
computed from the adjusted close so corporate actions do not create fake jumps.

Assumptions
-----------
* Bars may arrive in any order and may contain duplicate dates; the helper sorts by
  date and keeps the last bar for a duplicated date.
* A non-positive prior close cannot yield a return and is skipped rather than
  producing an infinite or undefined value.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from data.v2.schemas import AdjustedOHLCV


@dataclass(frozen=True)
class DailyReturn:
    """One trading day's simple return (``close_t / close_{t-1} - 1``)."""

    date: date
    value: float


def _ordered_unique(bars: Sequence[AdjustedOHLCV]) -> list[AdjustedOHLCV]:
    """Return bars sorted by date with one bar per date (the last wins)."""
    by_date = {bar.date: bar for bar in bars}
    return [by_date[day] for day in sorted(by_date)]


def daily_returns(bars: Sequence[AdjustedOHLCV]) -> list[DailyReturn]:
    """Return the simple daily return series for ``bars``.

    The first bar has no predecessor and therefore no return, so the result has one
    fewer element than the unique dates in ``bars``.
    """
    ordered = _ordered_unique(bars)
    returns: list[DailyReturn] = []
    for previous, current in itertools.pairwise(ordered):
        if previous.close <= 0:
            continue
        returns.append(DailyReturn(current.date, current.close / previous.close - 1.0))
    return returns


def return_series(bars: Sequence[AdjustedOHLCV]) -> dict[date, float]:
    """Return the same series keyed by date, for alignment with other tickers."""
    return {item.date: item.value for item in daily_returns(bars)}


def calendar_returns(
    bars: Sequence[AdjustedOHLCV],
    trading_days: Sequence[date],
) -> dict[date, float]:
    """Return simple daily returns aligned to the benchmark trading calendar.

    A return is produced for ``day`` only when the ticker has a bar on both ``day`` and
    the immediately preceding calendar trading day. A gap (halt, suspension or late
    listing) therefore contributes **no** return instead of a multi-day return placed on
    the resume date, so the analytics engine never mixes a multi-day ticker return with
    the benchmark's single-day return (which would corrupt beta, correlation and
    volatility).

    Args:
        bars: Daily bars for one ticker (adjusted ``close``); any order, duplicates
            resolved by the last bar.
        trading_days: The benchmark's trading days.
    """
    by_date = {bar.date: bar for bar in bars}
    result: dict[date, float] = {}
    for previous_day, day in itertools.pairwise(sorted(trading_days)):
        previous = by_date.get(previous_day)
        current = by_date.get(day)
        if previous is None or current is None:
            continue
        if previous.close <= 0:
            continue
        result[day] = current.close / previous.close - 1.0
    return result


__all__ = ["DailyReturn", "calendar_returns", "daily_returns", "return_series"]
