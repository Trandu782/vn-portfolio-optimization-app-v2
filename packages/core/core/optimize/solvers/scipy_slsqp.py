"""Solver: sequential least squares programming from ``scipy.optimize``.

Long-only (``weights >= 0``) and fully invested (``sum(weights) == 1``) are added
here, inside the solver, so every objective gets them for free. Any other
constraint is passed through as a scipy inequality (``fun(weights) >= 0``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from scipy.optimize import minimize

from core.optimize.interfaces import (
    Constraint,
    Objective,
    OptimizeContext,
    SolverReport,
    Vector,
    solvers,
)


class SlsqpParams(BaseModel):
    """Parameters for :class:`ScipySlsqp`."""

    max_iterations: int = Field(
        default=500, ge=1, description="Maximum SLSQP iterations."
    )
    tolerance: float = Field(
        default=1e-9, gt=0.0, description="Convergence tolerance on the objective."
    )
    binding_tolerance: float = Field(
        default=1e-6,
        gt=0.0,
        description="A constraint counts as binding when its slack is within this.",
    )


@solvers.register(
    id="scipy_slsqp",
    name="SciPy SLSQP",
    description=(
        "Sequential least squares programming. Always enforces long-only and "
        "fully invested; a different solver can be registered without touching "
        "the objectives."
    ),
    parameter_schema=SlsqpParams,
)
class ScipySlsqp:
    """Constrained minimization with ``scipy.optimize.minimize(method='SLSQP')``."""

    id = "scipy_slsqp"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        resolved = SlsqpParams(**(params or {}))
        self._max_iterations = resolved.max_iterations
        self._tolerance = resolved.tolerance
        self._binding_tolerance = resolved.binding_tolerance

    def solve(
        self,
        *,
        objective: Objective,
        constraints: Sequence[Constraint],
        context: OptimizeContext,
    ) -> SolverReport:
        """Minimize ``objective`` over the long-only, fully invested simplex."""
        count = context.n_assets
        if count == 0:
            return SolverReport(
                success=False,
                status="empty",
                message="no assets to optimize",
                iterations=0,
                weights=np.zeros(0, dtype=np.float64),
                binding_constraints=(),
            )

        start = np.full(count, 1.0 / float(count), dtype=np.float64)
        bounds = [(0.0, 1.0)] * count
        scipy_constraints: list[dict[str, Any]] = [
            {"type": "eq", "fun": _fully_invested}
        ]
        for constraint in constraints:
            scipy_constraints.append(
                {"type": "ineq", "fun": _constraint_function(constraint, context)}
            )

        jac: Callable[[Vector], Vector] | None = None
        if objective.gradient(start, context) is not None:
            jac = _objective_gradient(objective, context)

        result = minimize(
            fun=lambda weights: objective.value(weights, context),
            x0=start,
            jac=jac,
            method="SLSQP",
            bounds=bounds,
            constraints=scipy_constraints,
            options={"maxiter": self._max_iterations, "ftol": self._tolerance},
        )

        weights = np.clip(np.asarray(result.x, dtype=np.float64), 0.0, None)
        total = float(weights.sum())
        if total > 0.0:
            weights = weights / total
        return SolverReport(
            success=bool(result.success),
            status=str(result.status),
            message=str(result.message),
            iterations=int(result.nit),
            weights=weights,
            binding_constraints=self._binding(constraints, weights, context),
        )

    def _binding(
        self,
        constraints: Sequence[Constraint],
        weights: Vector,
        context: OptimizeContext,
    ) -> tuple[str, ...]:
        """Return the ids of constraints whose slack is within tolerance."""
        names: list[str] = []
        for constraint in constraints:
            values = np.atleast_1d(constraint.fun(weights, context))
            if values.size and float(np.min(values)) <= self._binding_tolerance:
                names.append(constraint.id)
        return tuple(names)


def _fully_invested(weights: Vector) -> Vector:
    """Return the full-investment equality residual (``sum(weights) - 1``)."""
    return np.array([float(np.sum(weights)) - 1.0], dtype=np.float64)


def _constraint_function(
    constraint: Constraint, context: OptimizeContext
) -> Callable[[Vector], Vector]:
    """Bind a constraint and its context into a scipy inequality callable."""

    def evaluate(weights: Vector) -> Vector:
        return constraint.fun(weights, context)

    return evaluate


def _objective_gradient(
    objective: Objective, context: OptimizeContext
) -> Callable[[Vector], Vector]:
    """Wrap an objective's analytic gradient as a scipy ``jac`` callable."""

    def evaluate(weights: Vector) -> Vector:
        gradient = objective.gradient(weights, context)
        return np.zeros_like(weights) if gradient is None else gradient

    return evaluate
