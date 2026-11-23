"""Optimization engine: estimators -> solver -> lot rounding -> result.

Pure orchestration. It never touches the network: the API supplies the aligned
returns matrix, the latest prices and the exchanges. The
risk-free rate is a parameter sourced from ``UserSettings`` through a
:class:`~core.optimize.interfaces.RiskFreeRateProvider`, never read from a
constant.

Cash reserve is handled here as a capital carve-out: the engine sets aside
``capital * reserve`` and optimizes the remainder, so "fully invested" stays
applied to the investable capital and the reserve is reported alongside the
lot-rounding residual cash.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
from numpy.typing import NDArray

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from core.optimize.interfaces import (
    DEFAULT_SOLVER,
    Constraint,
    ConstraintSpec,
    InfeasibleConstraintsError,
    OptimizeAssumptions,
    OptimizeContext,
    OptimizeResult,
    Vector,
    build_constraints,
    build_covariance_estimator,
    build_objective,
    build_return_estimator,
    build_solver,
)
from core.optimize.lot_rounding import round_to_lots
from core.universe import normalize_exchange

#: Slack tolerated when checking the solver's solution against the constraints.
_FEASIBILITY_TOLERANCE = 1e-4


def lot_size_for(exchange: str, rules: MarketRules) -> int:
    """Return the lot size for ``exchange``; use the largest lot when unknown.

    Exchanges are matched through :func:`core.universe.normalize_exchange` so
    ``UPCoM`` and ``UPCOM`` resolve to the same board. An unknown board falls back
    to the most conservative (largest) lot size in the market rules.
    """
    target = normalize_exchange(exchange)
    for code, entry in rules.exchanges.items():
        if normalize_exchange(code) == target:
            return entry.lot_size
    return max(entry.lot_size for entry in rules.exchanges.values())


def optimize(
    *,
    symbols: Sequence[str],
    exchanges: Mapping[str, str],
    returns: NDArray[np.float64],
    prices: Mapping[str, float],
    capital: int,
    objective_id: str,
    return_estimator_id: str,
    covariance_estimator_id: str,
    constraint_specs: Sequence[ConstraintSpec],
    risk_free_rate: float,
    start: date,
    end: date,
    return_estimator_params: dict[str, Any] | None = None,
    covariance_estimator_params: dict[str, Any] | None = None,
    objective_params: dict[str, Any] | None = None,
    solver_id: str = DEFAULT_SOLVER,
    solver_params: dict[str, Any] | None = None,
    risk_free_rate_provider: str = "user_settings",
    data_sources: Sequence[str] = (),
    prices_adjusted: bool = False,
    market_rules: MarketRules = DEFAULT_MARKET_RULES,
    sectors: Mapping[str, str] | None = None,
) -> OptimizeResult:
    """Run one complete optimization.

    Raises:
        ValueError: When the inputs are structurally invalid (no symbols, wrong
            matrix shape, too few observations, negative capital).
        KeyError: When a selected id is not registered.
        InfeasibleConstraintsError: When the solver cannot satisfy the constraints.
    """
    if capital < 0:
        raise ValueError("capital must not be negative")
    codes = tuple(symbol.strip().upper() for symbol in symbols)
    if not codes:
        raise ValueError("provide at least one symbol to optimize")
    if returns.ndim != 2 or returns.shape[1] != len(codes):
        raise ValueError("the returns matrix must have one column per symbol")
    if returns.shape[0] < 2:
        raise ValueError("need at least two return observations to optimize")

    return_estimator = build_return_estimator(return_estimator_id, return_estimator_params)
    covariance_estimator = build_covariance_estimator(
        covariance_estimator_id, covariance_estimator_params
    )
    objective = build_objective(objective_id, objective_params)
    constraint_objects = build_constraints(constraint_specs)

    reserve = sum(item.capital_reserve_fraction() for item in constraint_objects)
    reserve = min(max(reserve, 0.0), 1.0)
    investable_capital = float(capital) * (1.0 - reserve)

    expected = return_estimator.estimate(returns)
    covariance = covariance_estimator.estimate(returns)
    _validate_shapes(expected, covariance, len(codes))

    context = OptimizeContext(
        expected_returns=expected,
        covariance=covariance,
        risk_free_rate=float(risk_free_rate),
        investable_capital=investable_capital,
        prices={code: float(prices[code]) for code in codes if code in prices},
        symbols=codes,
        exchanges={code: exchanges.get(code, "HOSE") for code in codes},
        sectors={code: (sectors or {}).get(code) or "Unknown" for code in codes},
    )

    solver_constraints = [
        item for item in constraint_objects if item.capital_reserve_fraction() == 0.0
    ]
    solver = build_solver(solver_id, solver_params)
    report = solver.solve(
        objective=objective, constraints=solver_constraints, context=context
    )
    if not report.success:
        raise InfeasibleConstraintsError(
            "the solver could not satisfy the constraints "
            f"(status {report.status!r}): {report.message}"
        )
    _assert_feasible(report.weights, solver_constraints, context)

    weights = report.weights
    lot_sizes = {code: lot_size_for(context.exchanges[code], market_rules) for code in codes}
    rounding = round_to_lots(
        weights={code: float(weights[index]) for index, code in enumerate(codes)},
        prices=context.prices,
        capital=investable_capital,
        lot_sizes=lot_sizes,
    )

    expected_return = float(weights @ expected)
    variance = float(weights @ covariance @ weights)
    volatility = math.sqrt(max(variance, 0.0))
    sharpe = (
        (expected_return - float(risk_free_rate)) / volatility if volatility > 0.0 else 0.0
    )

    cash_reserve_value = round(float(capital) * reserve)
    assumptions = OptimizeAssumptions(
        objective=objective_id,
        return_estimator={
            "id": return_estimator_id,
            "params": dict(return_estimator_params or {}),
        },
        covariance_estimator={
            "id": covariance_estimator_id,
            "params": dict(covariance_estimator_params or {}),
        },
        constraints=tuple(
            {"id": spec.id, "params": dict(spec.params or {})} for spec in constraint_specs
        ),
        capital=capital,
        investable_capital=round(investable_capital),
        cash_reserve=reserve,
        risk_free_rate=float(risk_free_rate),
        risk_free_rate_provider=risk_free_rate_provider,
        start=start,
        end=end,
        data_sources=tuple(data_sources),
        prices_adjusted=prices_adjusted,
        lot_sizes=lot_sizes,
    )
    return OptimizeResult(
        symbols=codes,
        weights={code: float(weights[index]) for index, code in enumerate(codes)},
        lots=rounding.lots,
        shares=rounding.shares,
        values=rounding.values,
        residual_cash=rounding.residual_cash,
        cash_reserve=reserve,
        cash_reserve_value=cash_reserve_value,
        total_cash=cash_reserve_value + rounding.residual_cash,
        expected_return=expected_return,
        volatility=volatility,
        sharpe=sharpe,
        solver_status=report.status,
        solver_message=report.message,
        binding_constraints=report.binding_constraints,
        assumptions=assumptions,
    )


def _validate_shapes(expected: Vector, covariance: NDArray[np.float64], count: int) -> None:
    """Raise when an estimator returns vectors/matrices of the wrong shape."""
    if expected.shape != (count,):
        raise ValueError(
            f"the return estimator produced {expected.shape[0]} values for {count} symbols"
        )
    if covariance.shape != (count, count):
        raise ValueError("the covariance estimator produced a matrix of the wrong shape")


def _assert_feasible(
    weights: Vector, constraints: Sequence[Constraint], context: OptimizeContext
) -> None:
    """Raise :class:`InfeasibleConstraintsError` when the solution breaks a rule."""
    total = float(np.sum(weights))
    if abs(total - 1.0) > _FEASIBILITY_TOLERANCE:
        raise InfeasibleConstraintsError(
            f"the solution is not fully invested (the weights sum to {total:.4f})"
        )
    if float(np.min(weights)) < -_FEASIBILITY_TOLERANCE:
        raise InfeasibleConstraintsError("the solution contains a short position")
    for constraint in constraints:
        values = np.atleast_1d(constraint.fun(weights, context))
        if values.size and float(np.min(values)) < -_FEASIBILITY_TOLERANCE:
            raise InfeasibleConstraintsError(
                f"constraint {constraint.id!r} is violated "
                f"(worst slack {float(np.min(values)):.4g})"
            )
