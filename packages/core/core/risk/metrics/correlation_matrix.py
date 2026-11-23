"""Risk metric: pairwise correlation matrix of the universe's returns."""

from __future__ import annotations

from typing import Any

from core.risk._math import correlation_from_covariance, sample_covariance
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="correlation_matrix",
    name="Correlation matrix",
    description=(
        "Pairwise correlation of the universe's returns, computed on the rows "
        "where both symbols have an observation."
    ),
)
class CorrelationMatrix:
    """Pairwise correlation matrix of the analysed symbols."""

    id = "correlation_matrix"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it takes no parameters."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the symbol order and the correlation matrix rows."""
        correlation = correlation_from_covariance(sample_covariance(context.returns))
        return {
            "symbols": list(context.symbols),
            "matrix": [[float(value) for value in row] for row in correlation],
        }
