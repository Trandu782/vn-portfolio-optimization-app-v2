"""Universe filter: keep symbols listed on a single exchange."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.universe import SymbolSeries, normalize_exchange, universe_filters


class ExchangeParams(BaseModel):
    """Parameters for :class:`ExchangeFilter`."""

    exchange: str = Field(
        default="HOSE",
        description="Exchange to keep: HOSE, HNX or UPCOM.",
    )


@universe_filters.register(
    id="exchange",
    name="Exchange",
    description="Keep only symbols listed on the selected exchange (HOSE, HNX or UPCOM).",
    parameter_schema=ExchangeParams,
)
class ExchangeFilter:
    """Drop candidates that are not listed on the configured exchange."""

    id = "exchange"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        resolved = ExchangeParams(**(params or {}))
        self._exchange = normalize_exchange(resolved.exchange)

    def apply(self, candidate: SymbolSeries) -> str | None:
        if normalize_exchange(candidate.exchange) != self._exchange:
            board = candidate.exchange or "an unknown exchange"
            return f"listed on {board}, not {self._exchange}"
        return None
