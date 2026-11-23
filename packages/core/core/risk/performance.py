"""Historical performance of one return stream (growth of 100).

A descriptive chart, not a backtest: fixed weights, no costs, raw prices and
in-sample over the selected window. ``annualized_return`` is the geometric CAGR
over the number of observed periods; ``total_return`` is the simple
end-to-start change. Missing returns (``NaN``) are skipped, so a gap in an
invested symbol carries the previous level forward rather than fabricating a
return.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

from core.risk._math import drawdown_series, growth_series
from core.risk.interfaces import Performance, Vector


def compute_performance(
    returns: Vector, dates: Sequence[date], trading_days: int
) -> Performance:
    """Return the growth-of-100 series and its headline return statistics.

    Args:
        returns: Simple returns aligned with ``dates`` (``NaN`` for a gap).
        dates: Calendar date per return value.
        trading_days: Trading days per year used to annualize the growth.

    Raises:
        ValueError: When ``returns`` does not have one value per date.

    Returns:
        A :class:`Performance` with the kept dates, the growth series and the
        total return, annualized return and maximum drawdown.
    """
    series = np.asarray(returns, dtype=np.float64)
    if series.shape != (len(dates),):
        raise ValueError("returns must have one value per date")
    finite = np.isfinite(series)
    kept_dates = [day for day, keep in zip(dates, finite, strict=True) if keep]
    growth = growth_series(series)
    if growth.size == 0:
        return Performance(
            dates=(),
            growth=(),
            total_return=0.0,
            annualized_return=0.0,
            max_drawdown=0.0,
        )
    final_level = float(growth[-1]) / 100.0
    total_return = final_level - 1.0
    periods = growth.size
    if final_level > 0.0 and periods > 0:
        annualized_return = final_level ** (float(trading_days) / float(periods)) - 1.0
    else:
        annualized_return = 0.0
    _, max_drawdown = drawdown_series(series)
    return Performance(
        dates=tuple(day.isoformat() for day in kept_dates),
        growth=tuple(float(value) for value in growth),
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=max_drawdown,
    )


__all__ = ["compute_performance"]
