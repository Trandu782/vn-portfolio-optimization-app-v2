"""Endpoint exposing the default user settings and their allowed bounds.

The web app reads these so it never hardcodes the default fee or risk-free rate;
``core.settings.UserSettings`` remains the single source of truth.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.settings import (
    BROKERAGE_FEE_RATE_MAX,
    BROKERAGE_FEE_RATE_MIN,
    RISK_FREE_RATE_MAX,
    RISK_FREE_RATE_MIN,
    UserSettings,
)

router = APIRouter(tags=["settings"])


class Bound(BaseModel):
    """Inclusive range allowed for a user setting, as a fraction."""

    min: float
    max: float


class SettingsDefaults(BaseModel):
    """Default values of the user-controlled rates, as fractions."""

    brokerage_fee_rate: float
    risk_free_rate: float


class SettingsBounds(BaseModel):
    """Allowed ranges for the user-controlled rates."""

    brokerage_fee_rate: Bound
    risk_free_rate: Bound


class SettingsResponse(BaseModel):
    """Defaults and bounds the UI needs to render the Settings page."""

    defaults: SettingsDefaults
    bounds: SettingsBounds


@router.get("/settings", response_model=SettingsResponse)
def read_settings() -> SettingsResponse:
    """Return the default user settings and the ranges accepted by the API."""
    defaults = UserSettings()
    return SettingsResponse(
        defaults=SettingsDefaults(
            brokerage_fee_rate=float(defaults.brokerage_fee_rate),
            risk_free_rate=defaults.risk_free_rate,
        ),
        bounds=SettingsBounds(
            brokerage_fee_rate=Bound(
                min=float(BROKERAGE_FEE_RATE_MIN),
                max=float(BROKERAGE_FEE_RATE_MAX),
            ),
            risk_free_rate=Bound(min=RISK_FREE_RATE_MIN, max=RISK_FREE_RATE_MAX),
        ),
    )
