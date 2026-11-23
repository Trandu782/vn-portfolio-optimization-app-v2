"""Objective: maximize the Sharpe ratio (equivalently minimize its negative)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import BaseModel

from core.optimize.interfaces import OptimizeContext, Vector, objectives


class MaxSharpeParams(BaseModel):
    """The maximum-Sharpe objective takes no options."""


@objectives.register(
    id="max_sharpe",
    name="Maximum Sharpe",
    description=(
        "Maximize the Sharpe ratio using the expected returns, covariance and the "
        "user's risk-free rate. Non-convex, so the result is a local optimum."
    ),
    parameter_schema=MaxSharpeParams,
)
class MaxSharpe:
    """Negative Sharpe ratio ``-(w'mu - rf) / sqrt(w'Sigma w)``."""

    id = "max_sharpe"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        MaxSharpeParams(**(params or {}))

    def value(self, weights: Vector, context: OptimizeContext) -> float:
        """Return the negative Sharpe ratio at ``weights``."""
        expected = float(weights @ context.expected_returns)
        variance = float(weights @ context.covariance @ weights)
        volatility = math.sqrt(max(variance, 0.0))
        if volatility <= 0.0:
            return 0.0
        return -(expected - context.risk_free_rate) / volatility

    def gradient(self, weights: Vector, context: OptimizeContext) -> Vector | None:
        """Return the analytic gradient of the negative Sharpe ratio."""
        expected = float(weights @ context.expected_returns)
        covariance_weights = context.covariance @ weights
        variance = float(weights @ covariance_weights)
        volatility = math.sqrt(max(variance, 0.0))
        if volatility <= 0.0:
            return np.zeros_like(weights)
        excess = expected - context.risk_free_rate
        first_term = context.expected_returns / volatility
        second_term = excess * covariance_weights / (volatility**3)
        return -(first_term - second_term)
