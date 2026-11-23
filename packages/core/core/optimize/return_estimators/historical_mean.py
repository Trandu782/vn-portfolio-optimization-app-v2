"""Return estimator: the historical mean, annualized."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.optimize._math import column_mean
from core.optimize.interfaces import (
    DEFAULT_TRADING_DAYS,
    Matrix,
    Vector,
    return_estimators,
)


class HistoricalMeanParams(BaseModel):
    """Parameters for :class:`HistoricalMean`."""

    trading_days: int = Field(
        default=DEFAULT_TRADING_DAYS,
        ge=1,
        description="Trading days per year used to annualize the mean return.",
    )


@return_estimators.register(
    id="historical_mean",
    name="Historical mean",
    description=(
        "Average of the observed daily returns, annualized. Transparent but "
        "backward-looking and sensitive to the sample window."
    ),
    parameter_schema=HistoricalMeanParams,
)
class HistoricalMean:
    """Expected return equal to the mean of the observed returns."""

    id = "historical_mean"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._trading_days = HistoricalMeanParams(**(params or {})).trading_days

    def estimate(self, returns: Matrix) -> Vector:
        """Return the annualized mean return per column."""
        return column_mean(returns) * float(self._trading_days)
