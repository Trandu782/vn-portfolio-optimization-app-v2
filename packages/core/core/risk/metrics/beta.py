"""Risk metric: beta against the chosen benchmark."""

from __future__ import annotations

from typing import Any

from core.risk._math import beta, portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="beta",
    name="Beta vs benchmark",
    description=(
        "Sensitivity of the portfolio's returns to the selected benchmark index "
        "(covariance with the benchmark divided by the benchmark variance)."
    ),
)
class Beta:
    """Portfolio beta measured against the benchmark return series."""

    id = "beta"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it takes no parameters."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return ``{"beta": <beta>}``.

        Raises:
            ValueError: When the benchmark has no usable return variation.
        """
        portfolio = portfolio_returns(context.returns, context.weights)
        return {"beta": beta(portfolio, context.benchmark_returns)}
