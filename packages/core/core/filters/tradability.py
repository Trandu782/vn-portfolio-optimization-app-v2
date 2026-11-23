"""Universe filter: exclude suspended or delisted symbols."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.universe import SymbolSeries, universe_filters


class ExcludeSuspendedParams(BaseModel):
    """Parameters for :class:`ExcludeSuspendedFilter` (none)."""


@universe_filters.register(
    id="exclude_suspended",
    name="Exclude suspended/delisted",
    description="Drop symbols flagged as suspended or delisted.",
    parameter_schema=ExcludeSuspendedParams,
)
class ExcludeSuspendedFilter:
    """Drop candidates flagged as suspended or delisted."""

    id = "exclude_suspended"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        ExcludeSuspendedParams(**(params or {}))

    def apply(self, candidate: SymbolSeries) -> str | None:
        if candidate.delisted:
            return "delisted"
        if candidate.suspended:
            return "suspended"
        return None
