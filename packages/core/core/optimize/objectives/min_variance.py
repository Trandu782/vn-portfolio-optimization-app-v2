"""Objective: minimize the portfolio variance."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.optimize.interfaces import OptimizeContext, Vector, objectives


class MinVarianceParams(BaseModel):
    """The minimum-variance objective takes no options."""


@objectives.register(
    id="min_variance",
    name="Minimum variance",
    description="Minimize portfolio variance for the selected covariance estimate.",
    parameter_schema=MinVarianceParams,
)
class MinVariance:
    """Portfolio variance ``w' Sigma w`` (the conservative default)."""

    id = "min_variance"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        MinVarianceParams(**(params or {}))

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        """Return the portfolio variance at ``weights``."""
        return float(weights @ context.covariance @ weights)

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector:
        """Return the analytic gradient ``2 Sigma w``."""
        return 2.0 * (context.covariance @ weights)
