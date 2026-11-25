"""Universe filter: exclude tickers whose latest price bar trails the window end."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.universe import SymbolSeries, universe_filters


class ExcludeStalePricesParams(BaseModel):
    """Parameters for :class:`ExcludeStalePricesFilter` (none)."""


@universe_filters.register(
    id="exclude_stale_prices",
    name="Exclude stale price data",
    description=(
        "Drop symbols whose latest stored price bar trails the requested end by more "
        "than the stale tolerance (an incomplete V1/V2 backfill, not a suspension)."
    ),
    parameter_schema=ExcludeStalePricesParams,
)
class ExcludeStalePricesFilter:
    """Drop candidates whose price history is stale relative to the range end."""

    id = "exclude_stale_prices"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        ExcludeStalePricesParams(**(params or {}))

    def apply(self, candidate: SymbolSeries) -> str | None:
        if candidate.stale:
            return "stale_price_data"
        return None
