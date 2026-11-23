"""Shared request and response schemas for version 1 of the API."""

from __future__ import annotations

from pydantic import BaseModel

from core.settings import UserSettings


class Assumptions(BaseModel):
    """The user settings actually used to produce a result."""

    brokerage_fee_rate: float
    risk_free_rate: float


def assumptions_from(settings: UserSettings) -> Assumptions:
    """Build the assumptions block echoed in every compute response."""
    return Assumptions(
        brokerage_fee_rate=float(settings.brokerage_fee_rate),
        risk_free_rate=settings.risk_free_rate,
    )
