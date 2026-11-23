"""Objective: stay as close as possible to equal weights."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.optimize.interfaces import OptimizeContext, Vector, objectives


class EqualWeightParams(BaseModel):
    """The equal-weight objective takes no options."""


@objectives.register(
    id="equal_weight",
    name="Equal weight",
    description=(
        "Minimize the squared distance from equal weights (1/N per asset). A "
        "simple, transparent baseline that ignores risk and return estimates."
    ),
    parameter_schema=EqualWeightParams,
)
class EqualWeight:
    """Squared distance ``|| w - 1/N ||^2`` from the equal-weight portfolio."""

    id = "equal_weight"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        EqualWeightParams(**(params or {}))

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        """Return the squared distance from equal weights."""
        difference = weights - (1.0 / float(weights.size)) if weights.size else weights
        return float(difference @ difference)

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector | None:
        """Return the analytic gradient, or zeros for an empty problem."""
        if weights.size == 0:
            return weights
        return 2.0 * (weights - 1.0 / float(weights.size))
