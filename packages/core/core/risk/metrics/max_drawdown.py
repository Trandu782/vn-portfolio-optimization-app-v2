"""Risk metric: maximum drawdown and the full drawdown series."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.risk._math import portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="max_drawdown",
    name="Maximum drawdown",
    description=(
        "Largest peak-to-trough decline of the portfolio's cumulative value, "
        "reported as a positive fraction together with the drawdown series."
    ),
)
class MaxDrawdown:
    """Maximum peak-to-trough decline of the accumulated return stream."""

    id = "max_drawdown"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it takes no parameters."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the maximum drawdown, its dates and the drawdown series."""
        portfolio = portfolio_returns(context.returns, context.weights)
        finite = np.isfinite(portfolio)
        values = portfolio[finite]
        if values.size == 0:
            return {"max_drawdown": 0.0, "dates": [], "drawdown": []}
        equity = np.cumprod(1.0 + values)
        peak = np.maximum.accumulate(equity)
        drawdown = equity / peak - 1.0
        dates = [day.isoformat() for day, keep in zip(context.dates, finite, strict=True) if keep]
        return {
            "max_drawdown": float(-np.min(drawdown)),
            "dates": dates,
            "drawdown": [float(value) for value in drawdown],
        }
