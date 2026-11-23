"""Objective: closest achievable weights to the inverse-volatility allocation."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from core.optimize.interfaces import OptimizeContext, Vector, objectives


class InverseVolatilityParams(BaseModel):
    """The inverse-volatility objective takes no options."""


@objectives.register(
    id="inverse_volatility",
    name="Inverse volatility",
    description="Minimize distance to inverse-volatility weights (w_i ~ 1 / sigma_i).",
    parameter_schema=InverseVolatilityParams,
)
class InverseVolatility:
    """Squared distance to the inverse-volatility weights ``w_i proportional to 1 / sigma_i``."""

    id = "inverse_volatility"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        InverseVolatilityParams(**(params or {}))

    def _target(self, context: OptimizeContext) -> Vector:
        inverse = 1.0 / np.sqrt(np.maximum(np.diag(context.covariance), 1e-18))
        return inverse / inverse.sum()

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        return float(np.sum((weights - self._target(context)) ** 2))

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector:
        return 2.0 * (weights - self._target(context))
