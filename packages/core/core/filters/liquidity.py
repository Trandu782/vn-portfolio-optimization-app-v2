"""Universe filter: minimum average daily traded value."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.universe import SymbolSeries, average_daily_value, universe_filters


class MinAverageDailyValueParams(BaseModel):
    """Parameters for :class:`MinAverageDailyValueFilter`."""

    min_value_vnd: float = Field(
        default=1_000_000_000.0,
        ge=0,
        description="Minimum average daily traded value in VND (default 1 billion).",
    )
    sessions: int = Field(
        default=20,
        ge=1,
        description="Number of most recent sessions to average over.",
    )


@universe_filters.register(
    id="min_adv",
    name="Minimum average traded value",
    description="Drop symbols whose average daily traded value is below a VND threshold.",
    parameter_schema=MinAverageDailyValueParams,
)
class MinAverageDailyValueFilter:
    """Drop candidates whose average daily traded value is too low."""

    id = "min_adv"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        resolved = MinAverageDailyValueParams(**(params or {}))
        self._minimum = resolved.min_value_vnd
        self._sessions = resolved.sessions

    def apply(self, candidate: SymbolSeries) -> str | None:
        adv = average_daily_value(candidate.bars, self._sessions)
        if adv < self._minimum:
            return (
                f"average daily traded value {adv:,.0f} VND over {self._sessions} "
                f"sessions is below the {self._minimum:,.0f} VND minimum"
            )
        return None
