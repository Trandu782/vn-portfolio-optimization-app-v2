"""Efficient frontier and random-portfolio cloud for the guided Optimize page.

Pure NumPy/SciPy: no web, database or network imports. The guided Optimize page
shows three things that all come from here:

* a random-portfolio cloud (Dirichlet-sampled, long-only, capped at ``max_weight``)
  that explains *why* the efficient frontier is the upper-left edge;
* the exact efficient frontier (minimum variance for a sweep of target returns);
* the marked portfolios: minimum variance, maximum Sharpe (tangency), equal weight
  and the user's current holdings.

The risk-free rate is the user's ``UserSettings`` value and arrives as a
parameter; it is never read from a constant. Lot rounding is intentionally *not*
done here so the frontier stays at the weight level; the API rounds each point to
whole lots before it is shown to the user.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize

from core.optimize.interfaces import (
    DEFAULT_TRADING_DAYS,
    InfeasibleConstraintsError,
    Matrix,
    OptimizeContext,
    Vector,
    build_covariance_estimator,
    build_objective,
    build_return_estimator,
)
from core.optimize.sector_caps import (
    FEASIBILITY_TOLERANCE as SECTOR_FEASIBILITY_TOLERANCE,
)
from core.optimize.sector_caps import (
    group_indices_by_sector,
    sector_cap_error,
)

#: Default number of random portfolios drawn for the cloud.
DEFAULT_RANDOM_PORTFOLIOS = 5_000
#: Hard ceiling on the random cloud (configurable through ``Settings``).
MAX_RANDOM_PORTFOLIOS = 20_000
#: Number of target returns swept for the exact frontier.
DEFAULT_FRONTIER_POINTS = 40
#: Rejection-sampling batch size when capping the Dirichlet draws.
_BATCH_SIZE = 1_024
#: Numerical slack used when comparing volatilities along the frontier.
_MONOTONE_TOLERANCE = 1e-9
#: Slack tolerated when checking that a cap can still fully invest.
_FEASIBILITY_TOLERANCE = 1e-12


@dataclass(frozen=True)
class PortfolioPoint:
    """One portfolio at the weight level: weights plus its risk/return statistics."""

    weights: Mapping[str, float]
    expected_return: float
    volatility: float
    sharpe: float


@dataclass(frozen=True)
class RandomCloud:
    """The random-portfolio cloud used to draw the Monte Carlo scatter."""

    returns: Vector
    volatilities: Vector
    sharpes: Vector
    weights: Matrix
    generated: int


@dataclass(frozen=True)
class FrontierAssumptions:
    """Everything the frontier computation used, echoed for reproducibility."""

    risk_free_rate: float
    max_weight: float
    seed: int | None
    portfolios_requested: int
    portfolios_generated: int
    frontier_points: int
    skipped_targets: int
    trading_days: int
    max_sector_weight: float | None = None


@dataclass(frozen=True)
class FrontierResult:
    """The random cloud, the exact frontier and the marked portfolios."""

    symbols: tuple[str, ...]
    random_cloud: RandomCloud
    frontier: tuple[PortfolioPoint, ...]
    min_variance: PortfolioPoint
    tangency: PortfolioPoint
    equal_weight: PortfolioPoint
    current: PortfolioPoint | None
    assumptions: FrontierAssumptions


# -- statistics --------------------------------------------------------------


def _stats(
    weights: Vector, expected: Vector, covariance: Matrix, risk_free_rate: float
) -> tuple[float, float, float]:
    """Return ``(annual return, annual volatility, Sharpe)`` at ``weights``."""
    expected_return = float(weights @ expected)
    variance = float(weights @ covariance @ weights)
    volatility = math.sqrt(max(variance, 0.0))
    sharpe = (expected_return - risk_free_rate) / volatility if volatility > 0.0 else 0.0
    return expected_return, volatility, sharpe


def _point(
    weights: Vector,
    symbols: tuple[str, ...],
    expected: Vector,
    covariance: Matrix,
    risk_free_rate: float,
) -> PortfolioPoint:
    """Build a :class:`PortfolioPoint` from a weight vector and the estimates."""
    expected_return, volatility, sharpe = _stats(weights, expected, covariance, risk_free_rate)
    return PortfolioPoint(
        weights={code: float(weights[index]) for index, code in enumerate(symbols)},
        expected_return=expected_return,
        volatility=volatility,
        sharpe=sharpe,
    )


def _context(
    expected: Vector,
    covariance: Matrix,
    symbols: tuple[str, ...],
    risk_free_rate: float,
    sectors: Mapping[str, str] | None = None,
) -> OptimizeContext:
    """Build a minimal context for the registered objectives (weights only)."""
    return OptimizeContext(
        expected_returns=expected,
        covariance=covariance,
        risk_free_rate=risk_free_rate,
        investable_capital=1.0,
        prices={},
        symbols=symbols,
        exchanges={},
        sectors=dict(sectors or {}),
    )


def _weights_vector(weights: Mapping[str, float], codes: tuple[str, ...]) -> Vector | None:
    """Project ``weights`` onto ``codes`` and renormalize, or ``None`` when empty.

    Symbols in ``weights`` that are not part of the frontier are dropped (they have
    no expected return or covariance here) and the remaining weights are scaled to
    sum to one so the current portfolio can be plotted next to the frontier.
    """
    vector = np.array([float(weights.get(code, 0.0)) for code in codes], dtype=np.float64)
    total = float(vector.sum())
    if total <= 0.0:
        return None
    return vector / total


# -- solver ------------------------------------------------------------------


def _fully_invested(weights: Vector) -> Vector:
    """Return the full-investment equality residual (``sum(weights) - 1``)."""
    return np.array([float(np.sum(weights)) - 1.0], dtype=np.float64)


def _target_factory(target: float, expected: Vector) -> Callable[[Vector], Vector]:
    """Return an equality callable demanding ``w . expected == target``."""

    def evaluate(weights: Vector) -> float:
        return float(weights @ expected) - target

    return lambda weights: np.array([evaluate(weights)], dtype=np.float64)


def _sector_cap_factory(
    indices: Sequence[int], max_sector_weight: float
) -> Callable[[Vector], Vector]:
    """Return an inequality callable demanding ``sum(w in sector) <= cap``."""
    columns = list(indices)

    def evaluate(weights: Vector) -> Vector:
        return np.array(
            [max_sector_weight - float(np.sum(weights[columns]))], dtype=np.float64
        )

    return evaluate


def _solve_weights(
    *,
    objective_id: str,
    context: OptimizeContext,
    max_weight: float,
    target_return: float | None = None,
    start: Vector | None = None,
    sector_groups: Mapping[str, Sequence[int]] | None = None,
    max_sector_weight: float | None = None,
) -> Vector | None:
    """Minimize ``objective_id`` over the capped, fully invested simplex.

    Long-only is enforced through the box bounds and full investment through an
    equality constraint; ``max_weight`` is a per-position bound and
    ``max_sector_weight`` (with ``sector_groups``) caps each sector's total.
    ``target_return`` adds the equality constraint used by the frontier sweep.
    Returns ``None`` when the solver fails so the frontier can skip that target.
    """
    count = context.n_assets
    objective = build_objective(objective_id)
    bounds = [(0.0, max_weight)] * count
    constraints: list[dict[str, Any]] = [{"type": "eq", "fun": _fully_invested}]
    if target_return is not None:
        constraints.append(
            {"type": "eq", "fun": _target_factory(target_return, context.expected_returns)}
        )
    if sector_groups and max_sector_weight is not None:
        for indices in sector_groups.values():
            constraints.append(
                {"type": "ineq", "fun": _sector_cap_factory(indices, max_sector_weight)}
            )

    x0 = np.full(count, 1.0 / float(count), dtype=np.float64)
    if start is not None:
        candidate = np.clip(np.asarray(start, dtype=np.float64), 0.0, max_weight)
        total = float(candidate.sum())
        if total > 0.0:
            x0 = candidate / total

    jac: Callable[[Vector], Vector] | None = None
    if objective.gradient(x0, context) is not None:

        def _gradient(weights: Vector) -> Vector:
            gradient = objective.gradient(weights, context)
            return np.zeros_like(weights) if gradient is None else gradient

        jac = _gradient

    result = minimize(
        fun=lambda weights: objective.value(weights, context),
        x0=x0,
        jac=jac,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-9},
    )
    if not bool(result.success):
        return None
    weights = np.clip(np.asarray(result.x, dtype=np.float64), 0.0, None)
    total = float(weights.sum())
    if total > 0.0:
        weights = weights / total
    return weights


# -- random cloud ------------------------------------------------------------


def _capped_dirichlet(
    rng: np.random.Generator,
    n_assets: int,
    n_portfolios: int,
    max_weight: float,
    deadline: float,
    sector_groups: Mapping[str, Sequence[int]] | None = None,
    max_sector_weight: float | None = None,
) -> Matrix:
    """Draw ``n_portfolios`` Dirichlet weight rows, rejecting any that break a cap.

    A draw is rejected when any position exceeds ``max_weight`` or any sector's
    total exceeds ``max_sector_weight``. The rejection loop is vectorized in
    batches and stops when ``deadline`` (a ``time.monotonic`` value) is reached, so
    a very tight cap can never hang a request; the caller reports how many
    portfolios were actually produced.
    """
    alpha = np.ones(n_assets, dtype=np.float64)
    accepted: list[Matrix] = []
    collected = 0
    while collected < n_portfolios:
        remaining = n_portfolios - collected
        batch = max(remaining * 2, _BATCH_SIZE)
        draws = np.asarray(rng.dirichlet(alpha, size=batch), dtype=np.float64)
        good = draws[np.all(draws <= max_weight, axis=1)]
        if sector_groups and max_sector_weight is not None and good.shape[0] > 0:
            mask = np.ones(good.shape[0], dtype=bool)
            for indices in sector_groups.values():
                columns = list(indices)
                mask &= (
                    good[:, columns].sum(axis=1)
                    <= max_sector_weight + SECTOR_FEASIBILITY_TOLERANCE
                )
            good = good[mask]
        if good.shape[0] > 0:
            accepted.append(good[:remaining])
            collected += int(min(good.shape[0], remaining))
        if time.monotonic() >= deadline:
            break
    if not accepted:
        return np.empty((0, n_assets), dtype=np.float64)
    return np.vstack(accepted).astype(np.float64, copy=False)


def sample_random_portfolios(
    *,
    expected_returns: Vector,
    covariance: Matrix,
    risk_free_rate: float,
    num_portfolios: int = DEFAULT_RANDOM_PORTFOLIOS,
    max_weight: float = 1.0,
    seed: int | None = None,
    time_budget: float = 30.0,
    hard_max_portfolios: int = MAX_RANDOM_PORTFOLIOS,
    sector_groups: Mapping[str, Sequence[int]] | None = None,
    max_sector_weight: float | None = None,
) -> RandomCloud:
    """Draw long-only, capped Dirichlet portfolios.

    Each draw respects both the per-position ``max_weight`` and (when provided)
    the per-sector ``max_sector_weight``.

    Raises:
        ValueError: When the count is out of range.
        InfeasibleConstraintsError: When a cap cannot fully invest.
    """
    count = int(expected_returns.shape[0])
    if num_portfolios < 1:
        raise ValueError("num_portfolios must be at least 1")
    if num_portfolios > hard_max_portfolios:
        raise ValueError(
            f"at most {hard_max_portfolios} random portfolios per run; "
            f"received {num_portfolios}"
        )
    if count == 0:
        raise ValueError("provide at least one asset to sample random portfolios")
    if max_weight * float(count) < 1.0 - _FEASIBILITY_TOLERANCE:
        raise InfeasibleConstraintsError(
            f"a max weight of {max_weight:.0%} across {count} stocks cannot reach 100%"
        )
    if sector_groups and max_sector_weight is not None:
        error = sector_cap_error(sector_groups, max_weight, max_sector_weight)
        if error is not None:
            raise InfeasibleConstraintsError(error)

    rng = np.random.default_rng(seed)
    deadline = time.monotonic() + max(time_budget, 0.0)
    weights = _capped_dirichlet(
        rng,
        count,
        num_portfolios,
        max_weight,
        deadline,
        sector_groups=sector_groups,
        max_sector_weight=max_sector_weight,
    )
    generated = int(weights.shape[0])
    if generated == 0:
        empty = np.empty(0, dtype=np.float64)
        return RandomCloud(
            returns=empty,
            volatilities=empty,
            sharpes=empty,
            weights=np.empty((0, count), dtype=np.float64),
            generated=0,
        )

    returns = np.asarray(weights @ expected_returns, dtype=np.float64)
    variances = np.asarray(
        np.einsum("ij,jk,ik->i", weights, covariance, weights), dtype=np.float64
    )
    volatilities = np.sqrt(np.maximum(variances, 0.0))
    sharpes = np.divide(
        returns - risk_free_rate,
        volatilities,
        out=np.zeros_like(returns),
        where=volatilities > 0.0,
    )
    return RandomCloud(
        returns=returns,
        volatilities=volatilities,
        sharpes=sharpes,
        weights=weights,
        generated=generated,
    )


# -- frontier ----------------------------------------------------------------


def build_efficient_frontier(
    *,
    returns: Matrix,
    symbols: Sequence[str],
    risk_free_rate: float,
    max_weight: float,
    current_weights: Mapping[str, float] | None = None,
    num_portfolios: int = DEFAULT_RANDOM_PORTFOLIOS,
    seed: int | None = None,
    frontier_points: int = DEFAULT_FRONTIER_POINTS,
    time_budget: float = 30.0,
    hard_max_portfolios: int = MAX_RANDOM_PORTFOLIOS,
    trading_days: int = DEFAULT_TRADING_DAYS,
    sectors: Mapping[str, str] | None = None,
    max_sector_weight: float | None = None,
) -> FrontierResult:
    """Build the random cloud, the exact frontier and the marked portfolios.

    The per-stock ``max_weight`` and the optional per-sector ``max_sector_weight``
    are applied to every exact frontier solve and to every random-cloud draw.

    Raises:
        ValueError: When the inputs are structurally invalid or a count is out of
            range.
        InfeasibleConstraintsError: When a cap cannot fully invest, or the
            minimum-variance portfolio cannot be solved.
    """
    codes = tuple(symbol.strip().upper() for symbol in symbols)
    if not codes:
        raise ValueError("provide at least one symbol to build a frontier")
    if returns.ndim != 2 or returns.shape[1] != len(codes):
        raise ValueError("the returns matrix must have one column per symbol")
    if returns.shape[0] < 2:
        raise ValueError("need at least two return observations to build a frontier")
    count = len(codes)
    if not 0.0 < max_weight <= 1.0:
        raise ValueError("max_weight must be in the interval (0, 1]")
    if max_weight * float(count) < 1.0 - _FEASIBILITY_TOLERANCE:
        raise InfeasibleConstraintsError(
            f"a max weight of {max_weight:.0%} across {count} stocks cannot reach "
            "100%; raise the cap so the portfolio can be fully invested"
        )
    sector_groups: dict[str, tuple[int, ...]] | None = None
    if max_sector_weight is not None:
        if not 0.0 < max_sector_weight <= 1.0:
            raise ValueError("max_sector_weight must be in the interval (0, 1]")
        sector_groups = group_indices_by_sector(codes, sectors or {})
        error = sector_cap_error(sector_groups, max_weight, max_sector_weight)
        if error is not None:
            raise InfeasibleConstraintsError(error)
    if num_portfolios < 1:
        raise ValueError("num_portfolios must be at least 1")
    if num_portfolios > hard_max_portfolios:
        raise ValueError(
            f"at most {hard_max_portfolios} random portfolios per run; "
            f"received {num_portfolios}"
        )
    if frontier_points < 2:
        raise ValueError("frontier_points must be at least 2")

    estimator_params = {"trading_days": trading_days}
    expected = build_return_estimator("historical_mean", estimator_params).estimate(returns)
    covariance = build_covariance_estimator("sample", estimator_params).estimate(returns)
    if expected.shape != (count,):
        raise ValueError("the return estimator produced the wrong number of values")
    if covariance.shape != (count, count):
        raise ValueError("the covariance estimator produced a matrix of the wrong shape")

    context = _context(expected, covariance, codes, risk_free_rate, sectors=sectors)

    mv_weights = _solve_weights(
        objective_id="min_variance",
        context=context,
        max_weight=max_weight,
        sector_groups=sector_groups,
        max_sector_weight=max_sector_weight,
    )
    if mv_weights is None:
        raise InfeasibleConstraintsError("the minimum-variance portfolio could not be solved")
    min_variance = _point(mv_weights, codes, expected, covariance, risk_free_rate)

    lower = min_variance.expected_return
    upper = float(np.max(expected))
    targets = (
        np.linspace(lower, upper, frontier_points)
        if upper > lower + _MONOTONE_TOLERANCE
        else np.array([lower], dtype=np.float64)
    )

    frontier: list[PortfolioPoint] = []
    skipped = 0
    previous_volatility = -math.inf
    previous_weights: Vector | None = mv_weights
    for target in targets:
        weights: Vector | None
        if target <= lower + _MONOTONE_TOLERANCE:
            weights = mv_weights
        else:
            weights = _solve_weights(
                objective_id="min_variance",
                context=context,
                max_weight=max_weight,
                target_return=float(target),
                start=previous_weights,
                sector_groups=sector_groups,
                max_sector_weight=max_sector_weight,
            )
        if weights is None:
            skipped += 1
            continue
        _, volatility, _ = _stats(weights, expected, covariance, risk_free_rate)
        if volatility < previous_volatility - _MONOTONE_TOLERANCE:
            # Numerical noise made this target dominated; skip it so the plotted
            # frontier is non-decreasing in volatility as it must be.
            skipped += 1
            continue
        frontier.append(_point(weights, codes, expected, covariance, risk_free_rate))
        previous_volatility = volatility
        previous_weights = weights

    if not frontier:
        frontier = [min_variance]

    # The maximum-Sharpe (tangency) portfolio is the Sharpe-optimal point on the
    # efficient frontier. The frontier is the minimum-variance envelope at a sweep of
    # target returns, so the tangency marker is taken as the best-Sharpe frontier point
    # (guaranteed to lie on the plotted line). A separate free `max_sharpe` solve can
    # drift off the minimum-variance envelope (SLSQP), which used to make the marker
    # float apart from the frontier; it is therefore not used for the plotted point.
    tangency = max(frontier, key=lambda item: item.sharpe)

    equal_weight = _point(
        np.full(count, 1.0 / float(count), dtype=np.float64),
        codes,
        expected,
        covariance,
        risk_free_rate,
    )

    current: PortfolioPoint | None = None
    if current_weights is not None:
        current_vector = _weights_vector(current_weights, codes)
        if current_vector is not None:
            current = _point(current_vector, codes, expected, covariance, risk_free_rate)

    cloud = sample_random_portfolios(
        expected_returns=expected,
        covariance=covariance,
        risk_free_rate=risk_free_rate,
        num_portfolios=num_portfolios,
        max_weight=max_weight,
        seed=seed,
        time_budget=time_budget,
        hard_max_portfolios=hard_max_portfolios,
        sector_groups=sector_groups,
        max_sector_weight=max_sector_weight,
    )

    assumptions = FrontierAssumptions(
        risk_free_rate=float(risk_free_rate),
        max_weight=float(max_weight),
        seed=seed,
        portfolios_requested=num_portfolios,
        portfolios_generated=cloud.generated,
        frontier_points=len(frontier),
        skipped_targets=skipped,
        trading_days=trading_days,
        max_sector_weight=max_sector_weight,
    )
    return FrontierResult(
        symbols=codes,
        random_cloud=cloud,
        frontier=tuple(frontier),
        min_variance=min_variance,
        tangency=tangency,
        equal_weight=equal_weight,
        current=current,
        assumptions=assumptions,
    )


__all__ = [
    "DEFAULT_FRONTIER_POINTS",
    "DEFAULT_RANDOM_PORTFOLIOS",
    "MAX_RANDOM_PORTFOLIOS",
    "FrontierAssumptions",
    "FrontierResult",
    "PortfolioPoint",
    "RandomCloud",
    "build_efficient_frontier",
    "sample_random_portfolios",
]
