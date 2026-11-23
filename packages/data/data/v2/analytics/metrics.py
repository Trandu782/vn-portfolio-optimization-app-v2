"""Benchmark-relative metrics for a group index (``docs/V2_SPEC.md`` section 5).

Beta is ``Cov(group, benchmark) / Var(benchmark)`` on daily simple returns; R² is the
squared Pearson correlation. All "return" fields are percentages (``10.0`` means 10%),
``annualized_volatility`` is an annualised percentage, and ``beta`` / ``r_squared`` /
``correlation`` are dimensionless. A group with fewer than ``low_reliability_threshold``
aligned observations is flagged ``low_reliability`` rather than hidden.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np

from core.risk._math import annualized_volatility as _annualized_volatility
from core.risk._math import beta as _beta
from data.v2.analytics.schemas import BenchmarkMetrics

#: Trading days per year used to annualise volatility.
DEFAULT_TRADING_DAYS = 252
#: Observations below this count are flagged low-reliability.
LOW_RELIABILITY_OBSERVATIONS = 60


def compound_return(returns: Mapping[date, float]) -> float:
    """Return the compounded simple return of ``returns`` as a fraction."""
    level = 1.0
    for value in returns.values():
        level *= 1.0 + value
    return level - 1.0


def _aligned(
    group: Mapping[date, float], benchmark: Mapping[date, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Return the two return series aligned on their common dates."""
    common = sorted(set(group) & set(benchmark))
    group_values = np.array([group[day] for day in common], dtype=np.float64)
    benchmark_values = np.array([benchmark[day] for day in common], dtype=np.float64)
    return group_values, benchmark_values


def benchmark_metrics(
    group: str,
    group_returns: Mapping[date, float],
    benchmark_returns: Mapping[date, float],
    *,
    benchmark: str,
    constituent_count: int,
    trading_days: int = DEFAULT_TRADING_DAYS,
    low_reliability_threshold: int = LOW_RELIABILITY_OBSERVATIONS,
) -> BenchmarkMetrics:
    """Return a group's benchmark-relative performance and risk metrics.

    Args:
        group: The group label.
        group_returns: The group index's daily simple returns (fractions) by date.
        benchmark_returns: The benchmark's daily simple returns (fractions) by date.
        benchmark: The benchmark display/code label.
        constituent_count: The number of constituents in the built index.
        trading_days: Trading days per year for the volatility annualisation.
        low_reliability_threshold: Minimum aligned observations for a reliable reading.
    """
    warnings: list[str] = []
    period_return = compound_return(group_returns) * 100.0 if group_returns else None
    if benchmark_returns:
        benchmark_period: float | None = compound_return(benchmark_returns) * 100.0
    else:
        benchmark_period = None
        warnings.append(f"benchmark {benchmark} has no returns in the window")

    excess = (
        period_return - benchmark_period
        if period_return is not None and benchmark_period is not None
        else None
    )

    group_values, benchmark_values = _aligned(group_returns, benchmark_returns)
    observation_count = int(group_values.size)
    beta_value: float | None = None
    correlation: float | None = None
    r_squared: float | None = None
    if observation_count >= 2:
        if float(np.std(benchmark_values, ddof=1)) > 0.0:
            beta_value = _beta(group_values, benchmark_values)
            correlation = float(np.corrcoef(group_values, benchmark_values)[0, 1])
            r_squared = correlation * correlation
        else:
            warnings.append(
                "the benchmark has zero variance; beta and correlation are unavailable"
            )

    volatility = (
        _annualized_volatility(group_values, trading_days) * 100.0
        if group_values.size >= 2
        else None
    )
    low_reliability = observation_count < low_reliability_threshold
    if low_reliability:
        warnings.append(
            f"only {observation_count} aligned observation(s); low reliability "
            f"(threshold {low_reliability_threshold})"
        )

    return BenchmarkMetrics(
        group=group,
        benchmark=benchmark,
        period_return=period_return,
        benchmark_period_return=benchmark_period,
        excess_return=excess,
        beta=beta_value,
        r_squared=r_squared,
        correlation=correlation,
        annualized_volatility=volatility,
        observation_count=observation_count,
        constituent_count=constituent_count,
        low_reliability=low_reliability,
        warnings=warnings,
    )


__all__ = [
    "DEFAULT_TRADING_DAYS",
    "LOW_RELIABILITY_OBSERVATIONS",
    "benchmark_metrics",
    "compound_return",
]
