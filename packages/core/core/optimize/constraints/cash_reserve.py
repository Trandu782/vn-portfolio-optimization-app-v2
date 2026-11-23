"""Constraint: keep a fraction of the capital in cash."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from core.optimize.interfaces import OptimizeContext, Vector, constraints


class CashReserveParams(BaseModel):
    """Parameters for :class:`CashReserve`."""

    reserve: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Fraction of capital held in cash (0.05 == 5%).",
    )


@constraints.register(
    id="cash_reserve",
    name="Cash reserve",
    description=(
        "Keep a fraction of the capital in cash. The engine carves this cash out "
        "before solving, so the invested weights still sum to 100%."
    ),
    parameter_schema=CashReserveParams,
)
class CashReserve:
    """Reserve part of the capital; the solver optimizes the remaining amount."""

    id = "cash_reserve"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._reserve = CashReserveParams(**(params or {})).reserve

    def fun(self, weights: Vector, context: OptimizeContext) -> Vector:
        """Return a constant satisfied value; the carve-out happens in the engine."""
        return np.array([1.0], dtype=np.float64)

    def capital_reserve_fraction(self) -> float:
        """Return the fraction of capital held in cash."""
        return self._reserve
