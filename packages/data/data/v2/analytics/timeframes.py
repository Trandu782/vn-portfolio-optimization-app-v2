"""Timeframe resolution for the analytics engine.

The seven UI timeframes (1M, 3M, 6M, YTD, 1Y, 3Y, custom) resolve to a requested
:class:`~data.v2.analytics.schemas.Window`. Resolution is pure and does **not** clamp
to the stored history; the service clamps the requested start to the first stored
trading day and reports the clamp as a payload warning, so a short history degrades
gracefully instead of failing.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from data.v2.analytics.schemas import Window

#: Canonical timeframe labels accepted by :func:`resolve_window`.
TIMEFRAMES: tuple[str, ...] = ("1M", "3M", "6M", "YTD", "1Y", "3Y", "custom")

_MONTHS_BY_TIMEFRAME: dict[str, int] = {
    "1M": 1,
    "3M": 3,
    "6M": 6,
    "1Y": 12,
    "3Y": 36,
}


def subtract_months(day: date, months: int) -> date:
    """Return ``day`` shifted back by ``months``, clamped to the target month end."""
    total = day.year * 12 + (day.month - 1) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def resolve_window(
    timeframe: str,
    as_of: date,
    *,
    custom_start: date | None = None,
) -> Window:
    """Return the requested :class:`Window` for ``timeframe`` ending at ``as_of``.

    Args:
        timeframe: One of :data:`TIMEFRAMES` (case-insensitive).
        as_of: The window end date (usually the latest stored trading day).
        custom_start: The start date, required for ``custom``.

    Raises:
        ValueError: For an unknown timeframe, a ``custom`` window without a start,
            or a start after the end.
    """
    key = timeframe.strip().upper()
    if key == "CUSTOM":
        if custom_start is None:
            raise ValueError("custom timeframe needs a custom_start date")
        if custom_start > as_of:
            raise ValueError("custom_start must not be after the end date")
        return Window(label="custom", start=custom_start, end=as_of)
    if key == "YTD":
        return Window(label="YTD", start=date(as_of.year, 1, 1), end=as_of)
    months = _MONTHS_BY_TIMEFRAME.get(key)
    if months is None:
        expected = ", ".join(TIMEFRAMES)
        raise ValueError(f"unknown timeframe {timeframe!r}; expected one of {expected}")
    return Window(label=key, start=subtract_months(as_of, months), end=as_of)


__all__ = ["TIMEFRAMES", "resolve_window", "subtract_months"]
