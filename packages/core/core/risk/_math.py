"""Numeric helpers for the risk metrics (numpy only, deterministic).

Missing observations are ``NaN``. Portfolio-level metrics use the rows where the
invested portfolio has a finite return; pairwise metrics (beta, covariance and
correlation) use the rows where both series are finite. Nothing here draws random
numbers, so every metric is reproducible.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

from core.risk.interfaces import Matrix, Vector

#: Weights below this magnitude are treated as zero when building the portfolio
#: return series, so a gap in an uninvested symbol cannot blank out a day.
_ACTIVE_WEIGHT = 1e-12


def portfolio_returns(returns: Matrix, weights: Vector) -> Vector:
    """Return the weighted portfolio return per row (``NaN`` where undefined).

    Only assets with a non-negligible weight are used, so a gap in a symbol with a
    zero weight does not blank out the portfolio return for that day. A row is
    ``NaN`` when any invested asset is missing a return that day.
    """
    if returns.size == 0:
        return np.empty((0,), dtype=np.float64)
    active = np.abs(weights) > _ACTIVE_WEIGHT
    if not bool(active.any()):
        return np.zeros(returns.shape[0], dtype=np.float64)
    subset = returns[:, active]
    result = np.full(subset.shape[0], np.nan, dtype=np.float64)
    complete = np.isfinite(subset).all(axis=1)
    if bool(complete.any()):
        result[complete] = subset[complete] @ weights[active]
    return result


def annualized_volatility(series: Vector, trading_days: int) -> float:
    """Return the annualized standard deviation of ``series`` (0 with < 2 values)."""
    values = series[np.isfinite(series)]
    if values.size < 2:
        return 0.0
    return float(np.std(values, ddof=1) * np.sqrt(float(trading_days)))


def mean_return(series: Vector, trading_days: int) -> float:
    """Return the annualized arithmetic mean of ``series`` (0 with no values).

    Matches the optimizer's sample-mean annualization: the average daily return
    scaled by the number of trading days per year.
    """
    values = series[np.isfinite(series)]
    if values.size == 0:
        return 0.0
    return float(np.mean(values) * float(trading_days))


def growth_series(series: Vector) -> Vector:
    """Return the growth of 100 for the finite observations (``NaN`` rows skipped)."""
    values = series[np.isfinite(series)]
    if values.size == 0:
        return np.empty((0,), dtype=np.float64)
    return 100.0 * np.cumprod(1.0 + values)


def drawdown_series(series: Vector) -> tuple[Vector, float]:
    """Return the drawdown series (``<= 0``) and the positive maximum drawdown."""
    values = series[np.isfinite(series)]
    if values.size == 0:
        return np.empty((0,), dtype=np.float64), 0.0
    equity = np.cumprod(1.0 + values)
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    return drawdown, float(-np.min(drawdown))


def beta(portfolio: Vector, benchmark: Vector) -> float:
    """Return the portfolio's beta against the benchmark (``cov / var``).

    Raises:
        ValueError: With fewer than two aligned observations, or when the
            benchmark has zero variance over the window.
    """
    mask = np.isfinite(portfolio) & np.isfinite(benchmark)
    if int(mask.sum()) < 2:
        raise ValueError("beta needs at least two aligned portfolio and benchmark returns")
    port = portfolio[mask]
    bench = benchmark[mask]
    variance = float(np.var(bench, ddof=1))
    if variance <= 0.0:
        raise ValueError("the benchmark has zero variance over the window")
    covariance = float(np.cov(port, bench, ddof=1)[0, 1])
    return covariance / variance


def value_at_risk(series: Vector, confidence: float) -> float:
    """Return the historical one-period VaR as a positive loss fraction."""
    values = series[np.isfinite(series)]
    if values.size == 0:
        return 0.0
    return -float(np.quantile(values, 1.0 - confidence))


def sample_covariance(returns: Matrix) -> Matrix:
    """Return the pairwise-complete sample covariance (``ddof=1``), unannualized."""
    n_columns = returns.shape[1]
    covariance = np.zeros((n_columns, n_columns), dtype=np.float64)
    finite = np.isfinite(returns)
    for i in range(n_columns):
        for j in range(i, n_columns):
            mask = finite[:, i] & finite[:, j]
            if int(mask.sum()) <= 1:
                value = 0.0
            else:
                value = float(np.cov(returns[mask, i], returns[mask, j], ddof=1)[0, 1])
            covariance[i, j] = value
            covariance[j, i] = value
    return covariance


def correlation_from_covariance(covariance: Matrix) -> Matrix:
    """Return the correlation matrix derived from ``covariance`` (diagonal 1)."""
    n_assets = covariance.shape[0]
    standard_deviation = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    denominator = np.outer(standard_deviation, standard_deviation)
    correlation: Matrix = np.clip(
        np.asarray(
            np.divide(
                covariance,
                denominator,
                out=np.zeros((n_assets, n_assets), dtype=np.float64),
                where=denominator > 0.0,
            ),
            dtype=np.float64,
        ),
        -1.0,
        1.0,
    )
    np.fill_diagonal(correlation, 1.0)
    return correlation


def aligned_benchmark_returns(
    dates: Sequence[date],
    benchmark_dates: Sequence[date],
    benchmark_closes: Sequence[float],
) -> Vector:
    """Return the benchmark's simple returns aligned to ``dates``.

    ``benchmark_dates`` must be sorted ascending (the data layer returns sorted
    bars). A date with no benchmark observation maps to ``NaN``.
    """
    returns_by_date: dict[date, float] = {}
    previous: float | None = None
    for day, close in zip(benchmark_dates, benchmark_closes, strict=True):
        if previous is not None and previous != 0.0:
            returns_by_date[day] = close / previous - 1.0
        previous = close
    result = np.full(len(dates), np.nan, dtype=np.float64)
    for index, day in enumerate(dates):
        value = returns_by_date.get(day)
        if value is not None:
            result[index] = value
    return result


__all__ = [
    "aligned_benchmark_returns",
    "annualized_volatility",
    "beta",
    "correlation_from_covariance",
    "drawdown_series",
    "growth_series",
    "mean_return",
    "portfolio_returns",
    "sample_covariance",
    "value_at_risk",
]
