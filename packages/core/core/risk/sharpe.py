"""Sharpe ratio.

The function takes the user's risk-free rate as an explicit parameter, sourced
from ``core.settings.UserSettings`` at the call site. No module reads it from a
global constant or from ``market_rules``.
"""

from __future__ import annotations


def sharpe_ratio(mean_return: float, volatility: float, risk_free_rate: float) -> float:
    """Return the annualized Sharpe ratio of a return stream.

    Args:
        mean_return: Expected annual return as a fraction (0.10 == 10%).
        volatility: Annualized standard deviation of returns as a fraction.
        risk_free_rate: The user's annual risk-free rate as a fraction, taken from
            ``UserSettings.risk_free_rate``.

    Returns:
        ``(mean_return - risk_free_rate) / volatility``.

    Raises:
        ValueError: If ``volatility`` is not positive.
    """
    if volatility <= 0:
        raise ValueError("volatility must be greater than zero")
    return (mean_return - risk_free_rate) / volatility


__all__ = ["sharpe_ratio"]
