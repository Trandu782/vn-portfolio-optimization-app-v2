"""Interfaces, registries and result types for the optimization engine.

Every variable concept in the optimizer is an interface plus a registry, mirroring
``core.universe`` and ``core.filters``:

* :class:`ReturnEstimator` -> :data:`return_estimators`
* :class:`CovarianceEstimator` -> :data:`covariance_estimators`
* :class:`Objective` -> :data:`objectives`
* :class:`Constraint` -> :data:`constraints`
* :class:`Solver` -> :data:`solvers`
* :class:`RiskFreeRateProvider` -> :data:`risk_free_rate_providers`

Adding an implementation is one new module with one ``@registry.register`` call;
the engine and the API never switch on a concrete id. Objectives and constraints
receive an immutable :class:`OptimizeContext` (expected returns, covariance, the
user's risk-free rate, investable capital, prices and the symbol/exchange mapping),
so a new objective only needs those inputs.

The brokerage fee and the risk-free rate are user settings and are never read
from a constant here; lot sizes live in ``core.market_rules``. The product
defaults below (objective, estimators, max weight) are choices, not market data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from core.registry import Registry
from core.settings import UserSettings

#: One aligned returns or price matrix (``float64`` with ``NaN`` for a gap).
type Matrix = NDArray[np.float64]
#: A one-dimensional vector (expected returns, weights, constraint values).
type Vector = NDArray[np.float64]

#: Conservative product defaults (see the module docstring).
DEFAULT_OBJECTIVE = "min_variance"
DEFAULT_RETURN_ESTIMATOR = "historical_mean"
DEFAULT_COVARIANCE_ESTIMATOR = "sample"
DEFAULT_SOLVER = "scipy_slsqp"
DEFAULT_MAX_WEIGHT = 0.25
DEFAULT_TRADING_DAYS = 252


class InfeasibleConstraintsError(ValueError):
    """Raised when the requested constraints cannot be satisfied."""


@dataclass(frozen=True)
class OptimizeContext:
    """Immutable inputs shared by objectives and constraints during a solve.

    Attributes:
        expected_returns: Annualized expected return per asset.
        covariance: Annualized covariance matrix (N x N).
        risk_free_rate: The user's annual risk-free rate as a fraction.
        investable_capital: VND actually deployed (capital minus any cash reserve).
        prices: Latest close price per symbol, in VND.
        symbols: Column order of the matrices, one code per asset.
        exchanges: Exchange code per symbol, used for lot sizing.
        sectors: Sector label per symbol (ICB level 2, or ``Unknown``), used by
            the maximum-sector-weight constraint. Empty when no cap is requested.
    """

    expected_returns: Vector
    covariance: Matrix
    risk_free_rate: float
    investable_capital: float
    prices: Mapping[str, float]
    symbols: tuple[str, ...]
    exchanges: Mapping[str, str]
    sectors: Mapping[str, str] = field(default_factory=dict)

    @property
    def n_assets(self) -> int:
        """Return the number of assets in the problem."""
        return len(self.symbols)


@dataclass(frozen=True)
class SolverReport:
    """Outcome of one solver run, before lot rounding."""

    success: bool
    status: str
    message: str
    iterations: int
    weights: Vector
    binding_constraints: tuple[str, ...]


@dataclass(frozen=True)
class OptimizeAssumptions:
    """Every setting used to produce a result, echoed for reproducibility."""

    objective: str
    return_estimator: Mapping[str, Any]
    covariance_estimator: Mapping[str, Any]
    constraints: tuple[Mapping[str, Any], ...]
    capital: int
    investable_capital: int
    cash_reserve: float
    risk_free_rate: float
    risk_free_rate_provider: str
    start: date
    end: date
    data_sources: tuple[str, ...]
    prices_adjusted: bool
    lot_sizes: Mapping[str, int]


@dataclass(frozen=True)
class OptimizeResult:
    """A completed optimization: weights, integer lots and portfolio statistics."""

    symbols: tuple[str, ...]
    weights: Mapping[str, float]
    lots: Mapping[str, int]
    shares: Mapping[str, int]
    values: Mapping[str, float]
    residual_cash: int
    cash_reserve: float
    cash_reserve_value: int
    total_cash: int
    expected_return: float
    volatility: float
    sharpe: float
    solver_status: str
    solver_message: str
    binding_constraints: tuple[str, ...]
    assumptions: OptimizeAssumptions


# -- interfaces --------------------------------------------------------------


class ReturnEstimator(Protocol):
    """Turn a returns matrix into an annualized expected-return vector."""

    id: str

    def estimate(self, returns: Matrix) -> Vector:
        """Return one annualized expected return per column of ``returns``."""


class CovarianceEstimator(Protocol):
    """Turn a returns matrix into an annualized covariance matrix."""

    id: str

    def estimate(self, returns: Matrix) -> Matrix:
        """Return the annualized N x N covariance matrix of ``returns``."""


class Objective(Protocol):
    """A scalar to minimize; the solver always minimizes ``value``."""

    id: str

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        """Return the objective value at ``weights`` (lower is better)."""

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector | None:
        """Return the analytic gradient, or ``None`` to use finite differences."""


class Constraint(Protocol):
    """An inequality constraint in the ``fun(weights) >= 0`` convention."""

    id: str

    def fun(self, weights: Vector, context: OptimizeContext) -> Vector:
        """Return values that must each be greater than or equal to 0."""

    def capital_reserve_fraction(self) -> float:
        """Fraction of capital reserved before solving (0 for ordinary constraints).

        Almost every constraint returns ``0.0``. ``cash_reserve`` returns its
        fraction so the engine can carve that cash out and keep "fully invested"
        applied to the remaining investable capital.
        """


class Solver(Protocol):
    """A constrained optimizer. Long-only and fully invested are always added."""

    id: str

    def solve(
        self,
        *,
        objective: Objective,
        constraints: Sequence[Constraint],
        context: OptimizeContext,
    ) -> SolverReport:
        """Minimize ``objective`` over the long-only, fully invested simplex."""


class RiskFreeRateProvider(Protocol):
    """Source of the risk-free rate (user settings today, auto-fetch in V2)."""

    id: str

    def rate(self, settings: UserSettings) -> float:
        """Return the annual risk-free rate as a fraction."""


# -- registries --------------------------------------------------------------

return_estimators: Registry[ReturnEstimator] = Registry()
covariance_estimators: Registry[CovarianceEstimator] = Registry()
objectives: Registry[Objective] = Registry()
constraints: Registry[Constraint] = Registry()
solvers: Registry[Solver] = Registry()
risk_free_rate_providers: Registry[RiskFreeRateProvider] = Registry()


class _ParamsFactory(Protocol):
    """Constructor shape shared by every registry entry."""

    def __call__(self, params: dict[str, Any] | None = None) -> object: ...


def _instantiate[T](
    registry: Registry[T], identifier: str, params: dict[str, Any] | None
) -> T:
    """Instantiate the registered class for ``identifier`` with validated params."""
    factory = cast("_ParamsFactory", registry.get(identifier))
    return cast("T", factory(params))


@dataclass(frozen=True)
class ConstraintSpec:
    """A request to instantiate a registered constraint with its parameters."""

    id: str
    params: dict[str, Any] | None = None


def build_return_estimator(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[ReturnEstimator] | None = None,
) -> ReturnEstimator:
    """Instantiate the return estimator registered under ``identifier``."""
    return _instantiate(registry or return_estimators, identifier, params)


def build_covariance_estimator(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[CovarianceEstimator] | None = None,
) -> CovarianceEstimator:
    """Instantiate the covariance estimator registered under ``identifier``."""
    return _instantiate(registry or covariance_estimators, identifier, params)


def build_objective(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[Objective] | None = None,
) -> Objective:
    """Instantiate the objective registered under ``identifier``."""
    return _instantiate(registry or objectives, identifier, params)


def build_constraint(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[Constraint] | None = None,
) -> Constraint:
    """Instantiate the constraint registered under ``identifier``."""
    return _instantiate(registry or constraints, identifier, params)


def build_constraints(
    specs: Sequence[ConstraintSpec],
    *,
    registry: Registry[Constraint] | None = None,
) -> list[Constraint]:
    """Instantiate every :class:`ConstraintSpec` against the registry, in order."""
    return [build_constraint(spec.id, spec.params, registry=registry) for spec in specs]


def build_solver(
    identifier: str,
    params: dict[str, Any] | None = None,
    *,
    registry: Registry[Solver] | None = None,
) -> Solver:
    """Instantiate the solver registered under ``identifier``."""
    return _instantiate(registry or solvers, identifier, params)


def build_risk_free_rate_provider(
    identifier: str,
    *,
    registry: Registry[RiskFreeRateProvider] | None = None,
) -> RiskFreeRateProvider:
    """Instantiate the risk-free-rate provider registered under ``identifier``."""
    return _instantiate(registry or risk_free_rate_providers, identifier, None)


def resolve_risk_free_rate(
    identifier: str,
    settings: UserSettings,
    *,
    registry: Registry[RiskFreeRateProvider] | None = None,
) -> float:
    """Return the risk-free rate from the selected provider.

    The provider receives the user's settings, so V1 uses ``UserSettings`` and a
    future auto-fetch provider can be swapped in without touching the engine.
    """
    provider = build_risk_free_rate_provider(identifier, registry=registry)
    return provider.rate(settings)


__all__ = [
    "DEFAULT_COVARIANCE_ESTIMATOR",
    "DEFAULT_MAX_WEIGHT",
    "DEFAULT_OBJECTIVE",
    "DEFAULT_RETURN_ESTIMATOR",
    "DEFAULT_SOLVER",
    "DEFAULT_TRADING_DAYS",
    "Constraint",
    "ConstraintSpec",
    "CovarianceEstimator",
    "InfeasibleConstraintsError",
    "Matrix",
    "Objective",
    "OptimizeAssumptions",
    "OptimizeContext",
    "OptimizeResult",
    "ReturnEstimator",
    "RiskFreeRateProvider",
    "Solver",
    "SolverReport",
    "Vector",
    "build_constraint",
    "build_constraints",
    "build_covariance_estimator",
    "build_objective",
    "build_return_estimator",
    "build_risk_free_rate_provider",
    "build_solver",
    "constraints",
    "covariance_estimators",
    "objectives",
    "resolve_risk_free_rate",
    "return_estimators",
    "risk_free_rate_providers",
    "solvers",
]
