"""Interfaces and registries for risk analytics.

Every risk metric is an interface (:class:`RiskMetric`) plus a registration in
:data:`risk_metrics`, mirroring the optimizer, the universe filters and the data
providers. Adding a metric is one new module with one ``@risk_metrics.register``
call; the engine and the API never switch on a concrete id.

All quantities are fractions (0.10 == 10%). The risk-free rate (Sharpe, Treynor
and Jensen's alpha) is the user's value, supplied as a parameter and carried on
the :class:`RiskContext`; it is never read from settings or ``market_rules`` here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from core.registry import Registry

#: One aligned returns matrix (``float64`` with ``NaN`` for a gap).
type Matrix = NDArray[np.float64]
#: A one-dimensional vector (weights, benchmark returns).
type Vector = NDArray[np.float64]

#: Trading days per year used to annualize volatility and covariance.
DEFAULT_TRADING_DAYS = 252
#: Default confidence level for the historical VaR and CVaR metrics.
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True)
class RiskContext:
    """Immutable inputs shared by every risk metric.

    Attributes:
        symbols: Column order of ``returns``, one code per asset.
        dates: Calendar date for each row of ``returns`` (the return dates).
        returns: Aligned simple returns, ``T x N`` with ``NaN`` for a gap.
        weights: Portfolio weight per symbol, aligned with ``symbols``. A weight
            may sum to less than one; cash is the remainder and carries no risk.
        benchmark_returns: Benchmark simple returns aligned with the ``returns``
            rows (``NaN`` where the benchmark has no bar for that date).
        risk_free_rate: The user's annual risk-free rate as a fraction, taken from
            ``UserSettings.risk_free_rate``.
        trading_days: Trading days per year used for annualization.
    """

    symbols: tuple[str, ...]
    dates: tuple[date, ...]
    returns: Matrix
    weights: Vector
    benchmark_returns: Vector
    risk_free_rate: float
    trading_days: int = DEFAULT_TRADING_DAYS

    @property
    def n_assets(self) -> int:
        """Return the number of assets in the analysis."""
        return len(self.symbols)


class RiskMetric(Protocol):
    """A single risk measure computed from a :class:`RiskContext`."""

    id: str

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the metric payload as a JSON-serialisable mapping."""


#: Registry of every available risk metric.
risk_metrics: Registry[RiskMetric] = Registry()


class _ParamsFactory(Protocol):
    """Constructor shape shared by every registry entry."""

    def __call__(self, params: dict[str, Any] | None = None) -> object: ...


def build_risk_metric(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[RiskMetric] | None = None,
) -> RiskMetric:
    """Instantiate the risk metric registered under ``identifier``.

    Raises:
        KeyError: If ``identifier`` is unknown.
        pydantic.ValidationError: If ``params`` does not match the metric schema.
    """
    target = registry or risk_metrics
    factory = cast("_ParamsFactory", target.get(identifier))
    return cast("RiskMetric", factory(params))


@dataclass(frozen=True)
class Performance:
    """Growth of 100 over a period with the headline return statistics.

    A descriptive chart, not a backtest: weights are held fixed, costs are
    ignored and prices are in-sample over the selected window.
    """

    dates: tuple[str, ...]
    growth: tuple[float, ...]
    total_return: float
    annualized_return: float
    max_drawdown: float


@dataclass(frozen=True)
class RiskReport:
    """Every selected metric's payload for one portfolio, plus its performance."""

    symbols: tuple[str, ...]
    weights: Mapping[str, float]
    metrics: Mapping[str, Any]
    performance: Performance


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_TRADING_DAYS",
    "Matrix",
    "Performance",
    "RiskContext",
    "RiskMetric",
    "RiskReport",
    "Vector",
    "build_risk_metric",
    "risk_metrics",
]
