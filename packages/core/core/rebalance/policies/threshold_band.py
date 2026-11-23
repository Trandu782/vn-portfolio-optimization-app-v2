"""Threshold-band rebalance policy: skip small drifts and cap gross turnover.

A symbol is left at its current weight when its target and current weights differ
by no more than ``band`` (an absolute fraction, so ``0.02`` == two percentage
points). Everything else is traded straight to target. When ``turnover_cap`` is
set, the non-zero target deltas are scaled down so that the gross turnover
(``sum(|delta|)``, buys plus sells) never exceeds that fraction of total value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.rebalance.interfaces import (
    RebalanceContext,
    RebalanceDecision,
    rebalance_policies,
)


class ThresholdBandParams(BaseModel):
    """Parameters for the threshold-band policy."""

    band: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description=(
            "Skip a symbol when its target and current weight differ by at most "
            "this fraction (0.02 == 2 percentage points)."
        ),
    )
    turnover_cap: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional cap on gross turnover (buys plus sells) as a fraction of "
            "total portfolio value. Leave empty for no cap."
        ),
    )


@rebalance_policies.register(
    id="threshold_band",
    name="Threshold band + turnover cap",
    description=(
        "Skip symbols whose drift is within a band, then scale the remaining "
        "trades down so gross turnover stays within an optional cap."
    ),
    parameter_schema=ThresholdBandParams,
)
class ThresholdBand:
    """Skip small drifts and optionally cap gross turnover."""

    id = "threshold_band"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        parsed = ThresholdBandParams(**(params or {}))
        self._band = parsed.band
        self._turnover_cap = parsed.turnover_cap

    def decide(self, context: RebalanceContext) -> RebalanceDecision:
        """Return effective targets after the band skip and turnover cap."""
        symbols = sorted(set(context.current_weights) | set(context.target_weights))
        effective: dict[str, float] = {}
        for symbol in symbols:
            target = context.target_weights.get(symbol, 0.0)
            held = context.current_weights.get(symbol, 0.0)
            effective[symbol] = held if abs(target - held) <= self._band else target

        if self._turnover_cap is not None:
            deltas = {
                symbol: effective[symbol] - context.current_weights.get(symbol, 0.0)
                for symbol in symbols
            }
            gross = sum(abs(delta) for delta in deltas.values())
            if gross > self._turnover_cap and gross > 0.0:
                scale = self._turnover_cap / gross
                effective = {
                    symbol: context.current_weights.get(symbol, 0.0)
                    + deltas[symbol] * scale
                    for symbol in symbols
                }
        return RebalanceDecision(effective_targets=effective)


__all__ = ["ThresholdBand", "ThresholdBandParams"]
