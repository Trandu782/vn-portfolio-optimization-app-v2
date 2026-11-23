"""Risk metric: historical value at risk."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.risk._math import portfolio_returns, value_at_risk
from core.risk.interfaces import DEFAULT_CONFIDENCE, RiskContext, risk_metrics


class HistoricalVaRParams(BaseModel):
    """Parameters for :class:`HistoricalVaR`."""

    confidence: float = Field(
        default=DEFAULT_CONFIDENCE,
        gt=0.0,
        lt=1.0,
        description="Confidence level as a fraction (0.95 == 95%).",
    )


@risk_metrics.register(
    id="historical_var",
    name="Historical VaR",
    description=(
        "One-period value at risk from the empirical return distribution at the "
        "chosen confidence, reported as a positive loss fraction."
    ),
    parameter_schema=HistoricalVaRParams,
)
class HistoricalVaR:
    """Empirical value at risk of the portfolio return stream."""

    id = "historical_var"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric with a validated confidence level."""
        self._confidence = HistoricalVaRParams(**(params or {})).confidence

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the confidence used and the value at risk."""
        portfolio = portfolio_returns(context.returns, context.weights)
        return {
            "confidence": self._confidence,
            "value_at_risk": value_at_risk(portfolio, self._confidence),
        }
