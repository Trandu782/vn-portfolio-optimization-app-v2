"""Universe filter: minimum number of price sessions in the range."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.universe import SymbolSeries, universe_filters


class MinHistoryParams(BaseModel):
    """Parameters for :class:`MinHistoryFilter`."""

    min_sessions: int = Field(
        default=60,
        ge=1,
        description="Minimum number of price sessions required in the date range.",
    )


@universe_filters.register(
    id="min_history",
    name="Minimum history",
    description="Drop symbols with fewer than N price sessions in the selected range.",
    parameter_schema=MinHistoryParams,
)
class MinHistoryFilter:
    """Drop candidates with too few price sessions in the range."""

    id = "min_history"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        resolved = MinHistoryParams(**(params or {}))
        self._minimum = resolved.min_sessions

    def apply(self, candidate: SymbolSeries) -> str | None:
        if len(candidate.bars) < self._minimum:
            return (
                f"only {len(candidate.bars)} price sessions in range, "
                f"needs at least {self._minimum}"
            )
        return None
