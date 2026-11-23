"""Constraint: cap each position at a fraction of the portfolio."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from core.optimize.interfaces import OptimizeContext, Vector, constraints


class MaxWeightParams(BaseModel):
    """Parameters for :class:`MaxWeight`."""

    max_weight: float = Field(
        default=0.25,
        gt=0.0,
        le=1.0,
        description="Maximum weight per position as a fraction (0.25 == 25%).",
    )


@constraints.register(
    id="max_weight",
    name="Maximum weight",
    description="Cap each position at a fraction of the invested portfolio (default 25%).",
    parameter_schema=MaxWeightParams,
)
class MaxWeight:
    """Require ``max_weight - w_i >= 0`` for every asset."""

    id = "max_weight"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._max_weight = MaxWeightParams(**(params or {})).max_weight

    def fun(self, weights: Vector, context: OptimizeContext) -> Vector:
        """Return the headroom to the cap for every asset."""
        return np.full(weights.shape, self._max_weight, dtype=np.float64) - weights

    def capital_reserve_fraction(self) -> float:
        """A weight cap reserves no cash."""
        return 0.0
