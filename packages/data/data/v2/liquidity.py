"""Rolling 20-session medians of order-matching ADTV and ADV.

Liquidity presets (``docs/V2_SPEC.md`` section 4) use **medians** over the last 20
trading sessions, not a single day, so one block trade cannot flatter a thin stock.
Two bases exist and are always labelled:

* ``matched`` — order-matching value/volume (SSI ``totalMatchVal`` / ``totalMatchVol``),
  the preferred, real liquidity measure.
* ``total`` — fall back to total volume when the provider does not separate
  put-through (for example the KBS/VCI raw feeds). The value side is ``None`` when the
  provider publishes no traded value, rather than being invented.

A ticker is ``matched`` only when every bar in the window carries matched volume **and**
matched value; a partially matched window falls back to ``total`` so a median never
mixes the two bases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median

from data.v2.schemas import AdjustedOHLCV

#: The default rolling window, in trading sessions (``docs/V2_SPEC.md`` section 4).
DEFAULT_WINDOW = 20

VOLUME_BASIS_MATCHED = "matched"
VOLUME_BASIS_TOTAL = "total"


@dataclass(frozen=True)
class LiquidityStats:
    """Rolling-median liquidity for one ticker, with its volume basis."""

    as_of: date
    adtv_median: float | None
    adv_median: float | None
    volume_basis: str
    window: int
    observations: int


def rolling_median(values: Sequence[float], window: int) -> list[float | None]:
    """Return the trailing-window median at every position.

    Position ``i`` uses ``values[max(0, i - window + 1) : i + 1]``, so the earliest
    values use a shorter window (the median of what exists) instead of ``None``. A
    ``window`` below 1 raises ``ValueError`` so a misconfiguration cannot silently
    produce an empty series.
    """
    if window < 1:
        raise ValueError("window must be positive")
    medians: list[float | None] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        chunk = list(values[start : index + 1])
        medians.append(median(chunk) if chunk else None)
    return medians


def _ordered(bars: Sequence[AdjustedOHLCV]) -> list[AdjustedOHLCV]:
    """Return bars sorted by date with one bar per date (the last wins)."""
    by_date = {bar.date: bar for bar in bars}
    return [by_date[day] for day in sorted(by_date)]


def _is_matched(window: Sequence[AdjustedOHLCV]) -> bool:
    """Return ``True`` when every bar in ``window`` carries matched volume and value."""
    return bool(window) and all(
        bar.matched_volume is not None and bar.matched_value is not None for bar in window
    )


def liquidity_stats(
    bars: Sequence[AdjustedOHLCV], *, window: int = DEFAULT_WINDOW
) -> LiquidityStats:
    """Return the trailing ``window``-session ADTV/ADV medians for ``bars``.

    Args:
        bars: One ticker's daily bars (any order). Volume/value are taken from the
            matched fields when the whole window has them, otherwise from total
            volume. Bars outside the last ``window`` sessions are ignored.
        window: Rolling window in sessions (default 20).

    Returns:
        A :class:`LiquidityStats`. ``adv_median`` is ``None`` only when the window is
        empty; ``adtv_median`` is additionally ``None`` on the ``total`` basis when
        the provider publishes no traded value. ``as_of`` is the last bar's date.
    """
    if window < 1:
        raise ValueError("window must be positive")
    ordered = _ordered(bars)
    if not ordered:
        return LiquidityStats(
            as_of=date.min,
            adtv_median=None,
            adv_median=None,
            volume_basis=VOLUME_BASIS_TOTAL,
            window=window,
            observations=0,
        )
    tail = ordered[-window:]
    matched = _is_matched(tail)
    if matched:
        volumes = [bar.matched_volume for bar in tail if bar.matched_volume is not None]
        values = [bar.matched_value for bar in tail if bar.matched_value is not None]
        basis = VOLUME_BASIS_MATCHED
    else:
        volumes = [bar.volume for bar in tail]
        values = [bar.value for bar in tail if bar.value is not None]
        basis = VOLUME_BASIS_TOTAL
    return LiquidityStats(
        as_of=tail[-1].date,
        adtv_median=median(values) if values else None,
        adv_median=float(median(volumes)) if volumes else None,
        volume_basis=basis,
        window=window,
        observations=len(tail),
    )


__all__ = [
    "DEFAULT_WINDOW",
    "VOLUME_BASIS_MATCHED",
    "VOLUME_BASIS_TOTAL",
    "LiquidityStats",
    "liquidity_stats",
    "rolling_median",
]
