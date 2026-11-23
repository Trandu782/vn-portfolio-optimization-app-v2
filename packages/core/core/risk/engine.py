"""Risk engine: compute the requested metrics for one portfolio.

Pure orchestration. It never touches the network: the API supplies the aligned
returns matrix, the benchmark returns and the portfolio weights. Missing weights
are treated as zero; weights for symbols outside the analysed universe are
ignored. Every metric is resolved through the registry, so the engine never
switches on a concrete id.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np

from core.risk._math import portfolio_returns
from core.risk.interfaces import (
    DEFAULT_TRADING_DAYS,
    Matrix,
    RiskContext,
    RiskReport,
    Vector,
    build_risk_metric,
    risk_metrics,
)
from core.risk.performance import compute_performance


def compute_risk(
    *,
    symbols: Sequence[str],
    dates: Sequence[date],
    returns: Matrix,
    benchmark_returns: Vector,
    weights: Mapping[str, float],
    risk_free_rate: float,
    metric_ids: Sequence[str] | None = None,
    metric_params: Mapping[str, Mapping[str, Any]] | None = None,
    trading_days: int = DEFAULT_TRADING_DAYS,
) -> RiskReport:
    """Compute every requested risk metric for one portfolio.

    Args:
        symbols: Universe tickers, in the column order of ``returns``.
        dates: Return date per row of ``returns``.
        returns: Aligned simple returns, ``T x N`` (``NaN`` for a gap).
        benchmark_returns: Benchmark returns aligned with the ``returns`` rows.
        weights: Portfolio weight per symbol. A missing symbol gets ``0.0``;
            extra symbols are ignored. Weights must be finite and non-negative.
        risk_free_rate: The user's annual risk-free rate as a fraction, taken
            from ``UserSettings.risk_free_rate``.
        metric_ids: Metrics to compute; ``None`` or empty computes every
            registered metric.
        metric_params: Optional per-metric parameter mapping, keyed by metric id.
        trading_days: Trading days per year used for annualization.

    Raises:
        ValueError: When the inputs are structurally invalid.
        KeyError: When a requested metric id is not registered.
    """
    codes = tuple(symbols)
    if not codes:
        raise ValueError("provide at least one symbol")
    matrix = np.asarray(returns, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(codes):
        raise ValueError("the returns matrix must have one column per symbol")
    if matrix.shape[0] != len(dates):
        raise ValueError("dates must have one entry per returns row")
    benchmark = np.asarray(benchmark_returns, dtype=np.float64)
    if benchmark.shape != (matrix.shape[0],):
        raise ValueError("benchmark returns must have one value per returns row")

    weight_vector = np.array(
        [float(weights.get(code, 0.0)) for code in codes], dtype=np.float64
    )
    if not bool(np.isfinite(weight_vector).all()):
        raise ValueError("weights must be finite numbers")
    if bool(np.any(weight_vector < 0.0)):
        raise ValueError("weights must not be negative")
    if not bool(np.any(np.abs(weight_vector) > 0.0)):
        raise ValueError("provide at least one non-zero portfolio weight")

    selected = list(metric_ids) if metric_ids else risk_metrics.list()
    context = RiskContext(
        symbols=codes,
        dates=tuple(dates),
        returns=matrix,
        weights=weight_vector,
        benchmark_returns=benchmark,
        risk_free_rate=risk_free_rate,
        trading_days=trading_days,
    )
    params = metric_params or {}
    computed: dict[str, Any] = {}
    for identifier in selected:
        metric = build_risk_metric(identifier, dict(params.get(identifier, {})))
        computed[identifier] = metric.compute(context)

    performance = compute_performance(
        portfolio_returns(matrix, weight_vector), context.dates, trading_days
    )

    return RiskReport(
        symbols=codes,
        weights={
            code: float(weight_vector[index]) for index, code in enumerate(codes)
        },
        metrics=computed,
        performance=performance,
    )


def compute_benchmark_risk(
    *,
    dates: Sequence[date],
    benchmark_returns: Vector,
    risk_free_rate: float,
    metric_ids: Sequence[str] | None = None,
    metric_params: Mapping[str, Mapping[str, Any]] | None = None,
    trading_days: int = DEFAULT_TRADING_DAYS,
) -> RiskReport:
    """Compute the risk metrics for the benchmark itself.

    The index is modelled as a one-asset portfolio that is 100% invested in
    itself, so it flows through exactly the same metric code as a real portfolio:
    its beta is 1, its Jensen's alpha is 0 and its volatility, drawdown and VaR
    describe the index's own return stream.

    Args:
        dates: Return date per benchmark observation.
        benchmark_returns: Benchmark simple returns (``NaN`` for a gap).
        risk_free_rate: The user's annual risk-free rate as a fraction.
        metric_ids: Metrics to compute; ``None`` or empty computes every metric.
        metric_params: Optional per-metric parameter mapping, keyed by metric id.
        trading_days: Trading days per year used for annualization.
    """
    benchmark = np.asarray(benchmark_returns, dtype=np.float64)
    return compute_risk(
        symbols=("BENCHMARK",),
        dates=dates,
        returns=benchmark.reshape(-1, 1),
        benchmark_returns=benchmark,
        weights={"BENCHMARK": 1.0},
        risk_free_rate=risk_free_rate,
        metric_ids=metric_ids,
        metric_params=metric_params,
        trading_days=trading_days,
    )


__all__ = ["compute_benchmark_risk", "compute_risk"]
