"""Risk analytics: pluggable metrics in one registry.

Importing this package registers every built-in metric. ``sharpe_ratio`` stays
available for the existing Sharpe endpoint; the analytical metrics here operate on
an aligned returns matrix, the portfolio weights and a benchmark.
"""

from __future__ import annotations

from core.risk import metrics as _metrics  # noqa: F401  # registers the built-in metrics
from core.risk._math import aligned_benchmark_returns
from core.risk.engine import compute_benchmark_risk, compute_risk
from core.risk.interfaces import (
    DEFAULT_CONFIDENCE,
    DEFAULT_TRADING_DAYS,
    Matrix,
    Performance,
    RiskContext,
    RiskMetric,
    RiskReport,
    Vector,
    build_risk_metric,
    risk_metrics,
)
from core.risk.performance import compute_performance
from core.risk.sharpe import sharpe_ratio

__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_TRADING_DAYS",
    "Matrix",
    "Performance",
    "RiskContext",
    "RiskMetric",
    "RiskReport",
    "Vector",
    "aligned_benchmark_returns",
    "build_risk_metric",
    "compute_benchmark_risk",
    "compute_performance",
    "compute_risk",
    "risk_metrics",
    "sharpe_ratio",
]
