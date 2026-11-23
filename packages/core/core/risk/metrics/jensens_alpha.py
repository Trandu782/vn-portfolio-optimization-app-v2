"""Risk metric: Jensen's alpha (return above the CAPM prediction)."""

from __future__ import annotations

from typing import Any

from core.risk._math import beta as beta_measure
from core.risk._math import mean_return, portfolio_returns
from core.risk.interfaces import RiskContext, risk_metrics


@risk_metrics.register(
    id="jensens_alpha",
    name="Jensen's alpha",
    description=(
        "Annualized return above what the CAPM predicts for the portfolio's beta: "
        "mean return minus the risk-free rate and beta times the benchmark's "
        "excess return. Positive means it beat its market-adjusted expectation."
    ),
)
class JensensAlpha:
    """Jensen's alpha of the portfolio, using the user's risk-free rate."""

    id = "jensens_alpha"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Create the metric; it reads the risk-free rate from the context."""

    def compute(self, context: RiskContext) -> dict[str, Any]:
        """Return Jensen's alpha and its inputs (``None`` when beta is unusable)."""
        portfolio = portfolio_returns(context.returns, context.weights)
        mean = mean_return(portfolio, context.trading_days)
        benchmark_mean = mean_return(context.benchmark_returns, context.trading_days)
        try:
            beta_value = beta_measure(portfolio, context.benchmark_returns)
        except ValueError:
            beta_value = None
        alpha = None
        if beta_value is not None:
            expected = context.risk_free_rate + beta_value * (
                benchmark_mean - context.risk_free_rate
            )
            alpha = mean - expected
        return {
            "alpha": alpha,
            "beta": beta_value,
            "mean_return": mean,
            "benchmark_return": benchmark_mean,
            "risk_free_rate": context.risk_free_rate,
        }
