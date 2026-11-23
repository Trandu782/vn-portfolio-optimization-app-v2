"""Risk metric: Sharpe ratio (excess return per unit of total risk)."""

from __future__ import annotations

from typing import Any

from core.risk._math import annualized_volatility, mean_return, portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics
from core.risk.sharpe import sharpe_ratio


@risk_metrics.register(
    id="sharpe",
    name="Sharpe ratio",
    description=(
        "Return per unit of total risk: the annualized excess return over the "
        "risk-free rate divided by annualized volatility. Higher is better."
    ),
)
class Sharpe:
    """Sharpe ratio of the portfolio, using the user's risk-free rate."""

    id = "sharpe"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it reads the risk-free rate from the context."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return the Sharpe ratio and its inputs (``None`` if volatility is zero)."""
        portfolio = portfolio_returns(context.returns, context.weights)
        mean = mean_return(portfolio, context.trading_days)
        volatility = annualized_volatility(portfolio, context.trading_days)
        value = (
            sharpe_ratio(mean, volatility, context.risk_free_rate)
            if volatility > 0.0
            else None
        )
        return {
            "sharpe": value,
            "mean_return": mean,
            "volatility": volatility,
            "risk_free_rate": context.risk_free_rate,
        }
