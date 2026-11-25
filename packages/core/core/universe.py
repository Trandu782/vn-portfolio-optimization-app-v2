"""Universe selection: pluggable filters, the filter registry and build_universe.

Universe selection turns a set of candidate symbols into an analysis-ready dataset:
an aligned price matrix (one column per kept ticker, one row per trading date), a
returns matrix, a per-symbol average daily traded value (ADV), data-quality flags
and the exact reason every dropped ticker was removed.

Design rules (see ``docs/ARCHITECTURE.md``):

* A filter is an interface (:class:`UniverseFilter`) plus a registration in
  :data:`universe_filters`. Adding a filter is one new file and one registration;
  :func:`build_universe` never learns about a specific filter.
* :func:`build_universe` is pure: it takes already-loaded :class:`SymbolSeries`
  and returns numpy matrices. It never touches the web, the database or the
  network, so it is trivial to unit-test with hand-built series.
* Every dropped ticker carries a non-empty reason, whether it was removed by a
  registered filter or by the built-in "no price data" guard.

Traded value: the ADV and liquidity checks use each bar's ``value`` when present
and otherwise fall back to ``close * volume`` - an approximation needed because
some anonymous providers report volume but not turnover.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from core.registry import Registry

#: Aligned numeric matrix: ``float64`` with ``NaN`` marking a missing observation.
type Matrix = NDArray[np.float64]


@dataclass(frozen=True)
class DailyBar:
    """One trading day's prices for a single symbol (the domain's normalised view)."""

    date: date
    close: float
    adj_close: float
    volume: int
    value: float | None = None


@dataclass(frozen=True)
class SymbolSeries:
    """A candidate symbol: metadata plus its in-range price history.

    ``suspended`` and ``delisted`` are **authoritative exchange status** signals,
    never inferred from a trailing price bar. A ticker whose latest V2 bar merely
    trails the requested window end is ``stale`` (an explicit data-quality signal),
    so an actively traded name with an incomplete backfill is not mislabelled as
    suspended.
    """

    code: str
    exchange: str
    bars: tuple[DailyBar, ...]
    suspended: bool = False
    delisted: bool = False
    stale: bool = False


@dataclass(frozen=True)
class QualityFlags:
    """Data-quality signals reported for every kept symbol."""

    suspended: bool
    delisted: bool
    missing_data: bool
    illiquid: bool
    stale: bool = False


@dataclass(frozen=True)
class DroppedTicker:
    """A ticker removed from the universe, always with a human-readable reason."""

    code: str
    reason: str
    filter_id: str | None = None


@dataclass(frozen=True)
class FilterSpec:
    """A request to instantiate a registered filter with its parameters."""

    id: str
    params: dict[str, Any] | None = None


@dataclass(eq=False)
class UniverseBuildResult:
    """The aligned dataset plus provenance for every kept and dropped ticker."""

    start: date
    end: date
    symbols: tuple[str, ...]
    dates: tuple[date, ...]
    returns_dates: tuple[date, ...]
    price_matrix: Matrix
    returns_matrix: Matrix
    adv_by_symbol: dict[str, float]
    quality_flags: dict[str, QualityFlags]
    dropped: tuple[DroppedTicker, ...]
    filters_applied: tuple[str, ...]


class UniverseFilter(Protocol):
    """A decision rule applied to one candidate symbol."""

    id: str

    def apply(self, candidate: SymbolSeries) -> str | None:
        """Return a drop reason, or ``None`` to keep the candidate."""


class FilterFactory(Protocol):
    """Callable shape of a filter class in the registry."""

    def __call__(self, params: dict[str, Any] | None = None) -> UniverseFilter: ...


#: Every registered universe filter, keyed by its stable id.
universe_filters: Registry[UniverseFilter] = Registry()


def build_filter(
    filter_id: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[UniverseFilter] = universe_filters,
) -> UniverseFilter:
    """Instantiate the filter registered under ``filter_id``.

    Args:
        filter_id: Stable id from the registry (``exchange``, ``min_adv``, ...).
        params: Parameter mapping validated against the filter's schema.
        registry: Registry to resolve against (tests inject a private one).

    Raises:
        KeyError: When no filter is registered under that id.
        pydantic.ValidationError: When ``params`` do not match the filter schema.
    """
    factory = cast(FilterFactory, registry.get(filter_id))
    return factory(params)


def build_filters(
    specs: Iterable[FilterSpec],
    *,
    registry: Registry[UniverseFilter] = universe_filters,
) -> list[UniverseFilter]:
    """Instantiate every :class:`FilterSpec` against the registry, in order."""
    return [build_filter(spec.id, spec.params, registry=registry) for spec in specs]


def normalize_exchange(exchange: str) -> str:
    """Return a canonical exchange code (``UPCoM``/``UPCOM`` -> ``UPCOM``)."""
    code = exchange.strip().upper()
    if not code:
        return "UNKNOWN"
    if code.startswith("UPCOM"):
        return "UPCOM"
    return code


def traded_value(bar: DailyBar) -> float:
    """Return the bar's traded value in VND, approximating it when absent."""
    if bar.value is not None:
        return bar.value
    return bar.close * bar.volume


def average_daily_value(bars: Sequence[DailyBar], sessions: int) -> float:
    """Average traded value over the most recent ``sessions`` bars.

    ``sessions`` is clamped to the available history; a symbol with no bars
    returns ``0.0``. Missing ``value`` fields fall back to ``close * volume``.
    """
    if not bars:
        return 0.0
    window = list(bars[-sessions:]) if sessions > 0 else list(bars)
    return sum(traded_value(bar) for bar in window) / len(window)


def build_universe(
    symbols: Iterable[SymbolSeries],
    filters: Sequence[UniverseFilter],
    start: date,
    end: date,
    *,
    adv_sessions: int = 20,
) -> UniverseBuildResult:
    """Filter ``symbols`` and assemble the aligned universe dataset.

    Args:
        symbols: Candidate series. Deduplicated by code; the first occurrence wins.
        filters: Instantiated filters applied in order; the first drop wins.
        start: Inclusive start of the analysis window.
        end: Inclusive end of the analysis window.
        adv_sessions: Number of most recent sessions used for the ADV metric.

    Returns:
        A :class:`UniverseBuildResult` with aligned matrices, ADV, quality flags
        and the dropped tickers (each with a reason).

    Raises:
        ValueError: When ``start`` is after ``end``.
    """
    if start > end:
        raise ValueError("start must not be after end")

    dropped: list[DroppedTicker] = []
    kept: list[SymbolSeries] = []
    seen: set[str] = set()

    for raw in symbols:
        code = raw.code.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        in_range = tuple(
            sorted((bar for bar in raw.bars if start <= bar.date <= end), key=lambda bar: bar.date)
        )
        series = SymbolSeries(
            code=code,
            exchange=normalize_exchange(raw.exchange),
            bars=in_range,
            suspended=raw.suspended,
            delisted=raw.delisted,
            stale=raw.stale,
        )
        if not series.bars:
            dropped.append(
                DroppedTicker(
                    code=code,
                    reason="missing_price_history: no price data in the requested date range",
                )
            )
            continue
        reason, filter_id = _first_drop(series, filters)
        if reason is not None:
            dropped.append(DroppedTicker(code=code, reason=reason, filter_id=filter_id))
            continue
        kept.append(series)

    return _assemble(kept, filters, start, end, adv_sessions, dropped)


def _first_drop(
    series: SymbolSeries, filters: Sequence[UniverseFilter]
) -> tuple[str | None, str | None]:
    """Return the first ``(reason, filter_id)`` that drops ``series``, else ``(None, None)``."""
    for uni_filter in filters:
        reason = uni_filter.apply(series)
        if reason is not None:
            return reason, uni_filter.id
    return None, None


def _assemble(
    kept: Sequence[SymbolSeries],
    filters: Sequence[UniverseFilter],
    start: date,
    end: date,
    adv_sessions: int,
    dropped: Sequence[DroppedTicker],
) -> UniverseBuildResult:
    """Build the aligned matrices, ADV and quality flags for the kept symbols."""
    symbols = tuple(series.code for series in kept)
    filters_applied = tuple(uni_filter.id for uni_filter in filters)

    if not kept:
        empty = np.empty((0, 0), dtype=np.float64)
        return UniverseBuildResult(
            start=start,
            end=end,
            symbols=symbols,
            dates=(),
            returns_dates=(),
            price_matrix=empty,
            returns_matrix=empty,
            adv_by_symbol={},
            quality_flags={},
            dropped=tuple(dropped),
            filters_applied=filters_applied,
        )

    dates = tuple(sorted({bar.date for series in kept for bar in series.bars}))
    date_index = {day: index for index, day in enumerate(dates)}
    rows = len(dates)
    columns = len(kept)

    price = np.full((rows, columns), np.nan, dtype=np.float64)
    adjusted = np.full((rows, columns), np.nan, dtype=np.float64)
    for column, series in enumerate(kept):
        for bar in series.bars:
            row = date_index[bar.date]
            price[row, column] = bar.close
            adjusted[row, column] = bar.adj_close

    returns = _pct_change(adjusted)
    adv_by_symbol = {
        series.code: average_daily_value(series.bars, adv_sessions) for series in kept
    }
    quality_flags = {
        series.code: QualityFlags(
            suspended=series.suspended,
            delisted=series.delisted,
            missing_data=bool(np.isnan(price[:, column]).any()),
            illiquid=adv_by_symbol[series.code] <= 0.0,
            stale=series.stale,
        )
        for column, series in enumerate(kept)
    }
    return UniverseBuildResult(
        start=start,
        end=end,
        symbols=symbols,
        dates=dates,
        returns_dates=dates[1:],
        price_matrix=price,
        returns_matrix=returns,
        adv_by_symbol=adv_by_symbol,
        quality_flags=quality_flags,
        dropped=tuple(dropped),
        filters_applied=filters_applied,
    )


def _pct_change(matrix: Matrix) -> Matrix:
    """Return the column-wise simple returns of ``matrix`` (``NaN`` where undefined)."""
    rows = matrix.shape[0]
    columns = matrix.shape[1]
    if rows < 2:
        return np.empty((0, columns), dtype=np.float64)
    previous = matrix[:-1, :]
    current = matrix[1:, :]
    result = np.full_like(current, np.nan)
    valid = np.isfinite(previous) & np.isfinite(current) & (previous != 0.0)
    result[valid] = current[valid] / previous[valid] - 1.0
    return result
