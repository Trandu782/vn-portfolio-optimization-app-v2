"""Full rebalance policy: trade every symbol straight to its target weight."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.rebalance.interfaces import (
    RebalanceContext,
    RebalanceDecision,
    rebalance_policies,
)


class FullRebalanceParams(BaseModel):
    """The full policy takes no parameters."""


@rebalance_policies.register(
    id="full",
    name="Full rebalance",
    description="Trade every symbol straight to its requested target weight.",
    parameter_schema=FullRebalanceParams,
)
class FullRebalance:
    """Return the requested target weights unchanged."""

    id = "full"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        FullRebalanceParams(**(params or {}))

    def decide(self, context: RebalanceContext) -> RebalanceDecision:
        """Return the requested targets unchanged."""
        return RebalanceDecision(effective_targets=dict(context.target_weights))


__all__ = ["FullRebalance", "FullRebalanceParams"]
