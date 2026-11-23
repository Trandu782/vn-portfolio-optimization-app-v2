"""Constraint: cap the total weight invested in each sector."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from core.optimize.interfaces import OptimizeContext, Vector, constraints
from core.optimize.sector_caps import group_indices_by_sector, sector_headroom


class MaxSectorWeightParams(BaseModel):
    """Parameters for :class:`MaxSectorWeight`."""

    max_sector_weight: float = Field(
        default=0.30,
        gt=0.0,
        le=1.0,
        description="Maximum weight per sector as a fraction (0.30 == 30%).",
    )


@constraints.register(
    id="max_sector_weight",
    name="Maximum sector weight",
    description=(
        "Cap the total weight invested in each sector. Tickers without a stored "
        "sector are grouped as 'Unknown'. Requires the request's sector map."
    ),
    parameter_schema=MaxSectorWeightParams,
)
class MaxSectorWeight:
    """Require ``max_sector_weight - sum(w in sector) >= 0`` for every sector."""

    id = "max_sector_weight"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._max = MaxSectorWeightParams(**(params or {})).max_sector_weight

    def fun(self, weights: Vector, context: OptimizeContext) -> Vector:
        """Return the headroom to the cap for every sector."""
        groups = group_indices_by_sector(context.symbols, context.sectors)
        if not groups:
            return np.array([1.0], dtype=np.float64)
        return sector_headroom(weights, groups, self._max)

    def capital_reserve_fraction(self) -> float:
        """A sector cap reserves no cash."""
        return 0.0


__all__ = ["MaxSectorWeight", "MaxSectorWeightParams"]
