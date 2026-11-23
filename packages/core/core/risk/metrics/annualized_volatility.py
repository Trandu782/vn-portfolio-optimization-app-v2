"""Risk metric: annualized volatility of the portfolio return stream."""

from __future__ import annotations

from typing import Any

from core.risk._math import annualized_volatility, portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="annualized_volatility",
    name="Annualized volatility",
    description=(
        "Standard deviation of the portfolio's daily returns, annualized by the "
        "square root of the trading days per year."
    ),
)
class AnnualizedVolatility:
    """Annualized standard deviation of the weighted portfolio returns."""

    id = "annualized_volatility"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it takes no parameters."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return ``{"volatility": <annualized fraction>}``."""
        portfolio = portfolio_returns(context.returns, context.weights)
        return {"volatility": annualized_volatility(portfolio, context.trading_days)}
