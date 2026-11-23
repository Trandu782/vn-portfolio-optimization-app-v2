"""Covariance estimator: the pairwise-complete sample covariance."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.optimize._math import sample_covariance
from core.optimize.interfaces import (
    DEFAULT_TRADING_DAYS,
    Matrix,
    covariance_estimators,
)


class SampleCovarianceParams(BaseModel):
    """Parameters for :class:`SampleCovariance`."""

    trading_days: int = Field(
        default=DEFAULT_TRADING_DAYS,
        ge=1,
        description="Trading days per year used to annualize the covariance.",
    )


@covariance_estimators.register(
    id="sample",
    name="Sample covariance",
    description=(
        "Plain historical sample covariance (pairwise-complete), annualized. "
        "Noisy when the number of assets approaches the number of observations."
    ),
    parameter_schema=SampleCovarianceParams,
)
class SampleCovariance:
    """Annualized sample covariance of the observed returns."""

    id = "sample"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._trading_days = SampleCovarianceParams(**(params or {})).trading_days

    def estimate(self, returns: Matrix) -> Matrix:
        """Return the annualized sample covariance matrix."""
        return sample_covariance(returns) * float(self._trading_days)
