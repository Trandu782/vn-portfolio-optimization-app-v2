"""Read-only reconciliation of the Sector Analysis engine against pandas.

For Banks and Real Estate under the default settings (VN-Index benchmark, 1Y window,
Standard Retail preset, full market-cap weighting with a 15% cap) this prints the
engine's constituents, weights, excluded tickers and benchmark-relative metrics, then
recomputes the index return series and the same metrics independently with pandas from
the **stored** prices and reports any difference.

Read-only and offline: it reads only the V2 tables and ``indices_daily`` (never the
network). Run from the repo root:

    python scripts/reconcile_sector_analytics.py
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from data.calendar import trading_days_from_dates
from data.db.base import create_engine_for, create_session_factory, session_scope
from data.db.repositories import SqlIndexRepository
from data.models import PriceBar
from data.settings import get_settings
from data.v2.analytics.schemas import AnalyticsPayload, GroupAnalytics
from data.v2.analytics.service import AnalyticsRequest, AnalyticsService
from data.v2.precompute_schemas import ReturnPoint
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

#: Sector labels to reconcile (matched case-insensitively by substring).
TARGET_SECTORS: tuple[str, ...] = ("bank", "real estate")
#: Absolute difference above which a metric is reported as a discrepancy.
TOLERANCE = 1e-6


def _close_series(bars: Sequence[AdjustedOHLCV | PriceBar], calendar: list[date]) -> pd.Series:
    """Return the adjusted closes reindexed on the trading calendar (NaN when absent)."""
    by_date = {bar.date: bar.close for bar in bars}
    values = [by_date.get(day, np.nan) for day in calendar]
    return pd.Series(values, index=pd.DatetimeIndex(calendar), dtype="float64")


def _calendar_returns(
    bars: Sequence[AdjustedOHLCV | PriceBar], calendar: list[date]
) -> dict[date, float]:
    """Return ``close_t / close_{t-1} - 1`` per calendar day, only when both exist."""
    prices = _close_series(bars, calendar)
    returns = prices / prices.shift(1) - 1.0
    return {
        day.date(): float(value)
        for day, value in returns.items()
        if pd.notna(value)
    }


def _rebalance_days(window: list[date]) -> set[date]:
    """Return the first window day plus the last day on/before each quarter end."""
    days: set[date] = {window[0]}
    for year in range(window[0].year, window[-1].year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            boundary = date(year, month, day)
            if window[0] < boundary <= window[-1]:
                eligible = [entry for entry in window if entry <= boundary]
                if eligible:
                    days.add(eligible[-1])
    return days


def _simulate_index(
    window: list[date],
    returns_by_ticker: dict[str, dict[date, float]],
    target_weights: dict[str, float],
    rebalance_days: set[date],
) -> dict[date, float]:
    """Reproduce the engine's cap-cleaned, drifting, quarterly-rebalanced index return."""
    weights = dict(target_weights)
    daily: dict[date, float] = {}
    for day in window[1:]:
        if day in rebalance_days:
            weights = dict(target_weights)
        contributions = [
            (weights[ticker], returns_by_ticker[ticker][day])
            for ticker in weights
            if day in returns_by_ticker.get(ticker, {})
        ]
        available = sum(weight for weight, _ in contributions)
        daily[day] = (
            sum(weight * value for weight, value in contributions) / available
            if available > 0
            else 0.0
        )
        drifted = {
            ticker: (
                weights[ticker] * (1.0 + returns_by_ticker[ticker][day])
                if day in returns_by_ticker.get(ticker, {})
                else weights[ticker]
            )
            for ticker in weights
        }
        total = sum(drifted.values())
        if total > 0:
            weights = {ticker: value / total for ticker, value in drifted.items()}
    return daily


def _compound(values: Iterable[float]) -> float:
    """Return the compounded simple return as a percentage."""
    level = 1.0
    for value in values:
        level *= 1.0 + float(value)
    return (level - 1.0) * 100.0


def _metrics(
    index_daily: dict[date, float], benchmark_daily: dict[date, float]
) -> dict[str, float]:
    """Return period/excess return, beta, R² and correlation from two return maps."""
    joined = pd.concat(
        [
            pd.Series(index_daily, dtype="float64"),
            pd.Series(benchmark_daily, dtype="float64"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    period = _compound(index_daily.values())
    benchmark_period = _compound(benchmark_daily.values())
    if len(joined) < 2:
        return {
            "period_return": period,
            "excess_return": period - benchmark_period,
            "beta": float("nan"),
            "r_squared": float("nan"),
            "correlation": float("nan"),
            "n": float(len(joined)),
        }
    group = joined.iloc[:, 0].to_numpy(dtype=np.float64)
    bench = joined.iloc[:, 1].to_numpy(dtype=np.float64)
    variance = float(np.var(bench, ddof=1))
    beta = float(np.cov(group, bench, ddof=1)[0, 1] / variance) if variance > 0 else float("nan")
    correlation = float(np.corrcoef(group, bench)[0, 1])
    return {
        "period_return": period,
        "excess_return": period - benchmark_period,
        "beta": beta,
        "r_squared": correlation * correlation,
        "correlation": correlation,
        "n": float(len(joined)),
    }

def _independent_weights(
    constituents: Sequence[str],
    market_caps: dict[str, float],
    weighting: str,
    cap: float | None,
) -> dict[str, float]:
    """Return target weights computed independently: normalise first, then water-fill."""
    if weighting == "equal":
        raw = dict.fromkeys(constituents, 1.0)
    else:
        raw = {
            ticker: market_caps[ticker]
            for ticker in constituents
            if ticker in market_caps
        }
        if not raw:
            return {}
    total = sum(raw.values())
    if total <= 0:
        return dict.fromkeys(raw, 1.0 / len(raw)) if raw else {}
    weights = {ticker: value / total for ticker, value in raw.items()}
    if cap is None or cap <= 0 or cap >= 1.0 or cap * len(weights) < 1.0 - 1e-12:
        return weights
    capped: dict[str, float] = {}
    free = dict(weights)
    while free:
        over = {
            ticker: value for ticker, value in free.items() if value > cap + 1e-12
        }
        if not over:
            break
        for ticker in over:
            capped[ticker] = cap
            del free[ticker]
        remaining = 1.0 - cap * len(capped)
        free_total = sum(free.values())
        if free_total <= 0:
            break
        free = {
            ticker: value / free_total * remaining for ticker, value in free.items()
        }
    return {**free, **capped}


def _find_group(
    payload: AnalyticsPayload, needle: str
) -> GroupAnalytics | None:
    """Return the first group whose label contains ``needle`` (case-insensitive)."""
    for group in payload.groups:
        if needle in group.index.group.lower():
            return group
    return None


def _daily_from_cumulative(
    points: Sequence[ReturnPoint],
) -> dict[date, float]:
    """Derive daily returns from the engine's cumulative (base 0%) path."""
    daily: dict[date, float] = {}
    for index in range(1, len(points)):
        previous = 1.0 + points[index - 1].value / 100.0
        current = 1.0 + points[index].value / 100.0
        if previous > 0:
            daily[points[index].date] = current / previous - 1.0
    return daily


ENGINE_KEYS: tuple[str, ...] = (
    "period_return",
    "excess_return",
    "beta",
    "r_squared",
    "correlation",
)


def _report_group(
    payload: AnalyticsPayload,
    group: GroupAnalytics,
    calendar: list[date],
    store: V2Store,
    index_repo: SqlIndexRepository,
    cap: float | None,
) -> int:
    """Print the engine's group inputs/metrics and compare with pandas."""
    print(f"\n=== {group.index.group} ===")
    if group.index.status != "ok":
        print(f"status {group.index.status}: no published index to reconcile")
        return 0

    print(f"constituents ({len(group.index.constituents)}): "
          f"{', '.join(group.index.constituents)}")
    print("weights (target, cap-cleaned):")
    for ticker, weight in sorted(group.index.weights.items(), key=lambda item: -item[1]):
        print(f"  {ticker:<6} {weight:8.4%}")
    excluded = group.index.excluded
    excluded_text = ", ".join(f"{ticker} ({reason})" for ticker, reason in excluded.items())
    print(f"excluded inside this group ({len(excluded)}): {excluded_text or '(none)'}")
    outside = [
        item.ticker
        for item in payload.default_excluded_outside_window
        if item.sector == group.index.group
    ]
    print(f"flagged earlier, not affecting this window: {', '.join(outside) or '(none)'}")

    window = [day for day in calendar if payload.window.start <= day <= payload.window.end]
    fetch_from = window[0] - timedelta(days=14)
    bars_by_ticker = {
        ticker: store.get_prices(ticker, fetch_from, window[-1])
        for ticker in group.index.constituents
    }
    benchmark_bars = index_repo.get_range(payload.benchmark, fetch_from, window[-1])

    returns_by_ticker = {
        ticker: _calendar_returns(bars_by_ticker.get(ticker, []), calendar)
        for ticker in group.index.constituents
    }
    benchmark_all = _calendar_returns(benchmark_bars, calendar)
    benchmark_daily = {day: benchmark_all[day] for day in window if day in benchmark_all}

    market_caps: dict[str, float] = {}
    for ticker in group.index.constituents:
        record = store.get_market_cap(ticker)
        if record is not None and record.market_cap is not None:
            market_caps[ticker] = float(record.market_cap)
    pandas_weights = _independent_weights(
        group.index.constituents, market_caps, payload.weighting, cap
    )
    engine_weights = group.index.weights
    weight_diff = max(
        (
            abs(engine_weights.get(ticker, 0.0) - weight)
            for ticker, weight in pandas_weights.items()
        ),
        default=0.0,
    )
    print(f"max |engine weight - pandas weight|: {weight_diff:.3e}")
    target_weights = pandas_weights or engine_weights
    simulated = _simulate_index(
        window, returns_by_ticker, target_weights, _rebalance_days(window)
    )
    independent = _metrics(simulated, benchmark_daily)
    engine: dict[str, float | None] = {
        "period_return": group.metrics.period_return,
        "excess_return": group.metrics.excess_return,
        "beta": group.metrics.beta,
        "r_squared": group.metrics.r_squared,
        "correlation": group.metrics.correlation,
    }

    print(f"\n{'metric':<16}{'engine':>13}{'pandas':>13}{'difference':>15}")
    discrepancies = 1 if weight_diff > TOLERANCE else 0
    for key in ENGINE_KEYS:
        engine_value = engine.get(key)
        pandas_value = independent.get(key)
        if engine_value is None or pandas_value is None or not np.isfinite(pandas_value):
            shown = "n/a" if engine_value is None else f"{float(engine_value):.6f}"
            print(f"{key:<16}{shown:>13}{'n/a':>13}{'':>15}")
            continue
        difference = float(engine_value) - float(pandas_value)
        if abs(difference) > TOLERANCE:
            discrepancies += 1
        print(
            f"{key:<16}{float(engine_value):>13.6f}{float(pandas_value):>13.6f}"
            f"{difference:>15.3e}"
        )
    print(
        f"aligned observations: engine {group.metrics.observation_count}, "
        f"pandas {int(independent['n'])}"
    )

    engine_daily = _daily_from_cumulative(group.index.cumulative_returns)
    path_diff = max(
        (
            abs(engine_daily[day] - simulated.get(day, 0.0))
            for day in engine_daily
            if day in simulated
        ),
        default=0.0,
    )
    print(f"index daily-return path max |engine - pandas|: {path_diff:.3e}")
    if path_diff > TOLERANCE:
        discrepancies += 1

    if discrepancies:
        print(f"RESULT: {discrepancies} difference(s) above tolerance {TOLERANCE}")
    else:
        print(f"RESULT: no difference above tolerance {TOLERANCE}")
    return discrepancies


def main() -> int:
    """Reconcile Banks and Real Estate; return 0 (a report, not a pass/fail gate)."""
    settings = get_settings()
    engine = create_engine_for(settings.database_url)
    factory = create_session_factory(engine)
    try:
        request = AnalyticsRequest()
        payload = AnalyticsService(factory).build(request)
        with session_scope(factory) as session:
            store = V2Store(session)
            calendar = sorted(trading_days_from_dates(store.list_index_dates("VNINDEX")))
            index_repo = SqlIndexRepository(session)
            print(
                f"benchmark: {payload.benchmark}  "
                f"window: {payload.window.start} .. {payload.window.end}  "
                f"preset: {payload.liquidity_preset}  weighting: {payload.weighting}"
            )
            total = 0
            for needle in TARGET_SECTORS:
                group = _find_group(payload, needle)
                if group is None:
                    print(f"\n=== {needle.title()} ===\nnot found in this payload")
                    continue
                total += _report_group(
                    payload, group, calendar, store, index_repo, request.single_stock_cap
                )
        print(f"\nTotal differences above tolerance: {total}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

