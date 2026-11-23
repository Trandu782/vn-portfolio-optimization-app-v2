"""Risk metric: Treynor ratio (excess return per unit of systematic risk)."""

from __future__ import annotations

from typing import Any

from core.risk._math import beta as beta_measure
from core.risk._math import mean_return, portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="treynor",
    name="Treynor ratio",
    description=(
        "Return per unit of market risk: the annualized excess return over the "
        "risk-free rate divided by beta against the benchmark. Higher is better."
    ),
)
class Treynor:
    """Treynor ratio of the portfolio, using the user's risk-free rate."""

    id = "treynor"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it reads the risk-free rate from the context."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the Treynor ratio and its inputs (``None`` when beta is unusable)."""
        portfolio = portfolio_returns(context.returns, context.weights)
        mean = mean_return(portfolio, context.trading_days)
        try:
            beta_value = beta_measure(portfolio, context.benchmark_returns)
        except ValueError:
            beta_value = None
        ratio = (
            (mean - context.risk_free_rate) / beta_value
            if beta_value is not None and beta_value != 0.0
            else None
        )
        return {
            "treynor": ratio,
            "beta": beta_value,
            "mean_return": mean,
            "risk_free_rate": context.risk_free_rate,
        }
