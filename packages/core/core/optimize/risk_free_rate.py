"""Risk-free-rate providers.

V1 has a single provider: the rate the user saved on the Settings page. A V2
auto-fetch provider (for example a government-bond yield) registers here without
touching the engine, mirroring every other registry in the optimizer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.optimize.interfaces import risk_free_rate_providers
from core.settings import UserSettings


class UserSettingsRiskFreeRateParams(BaseModel):
    """The user-settings provider takes no options."""


@risk_free_rate_providers.register(
    id="user_settings",
    name="User settings",
    description="Use the risk-free rate saved on the Settings page.",
    parameter_schema=UserSettingsRiskFreeRateParams,
)
class UserSettingsRiskFreeRate:
    """Return the user's risk-free rate from :class:`UserSettings`."""

    id = "user_settings"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        UserSettingsRiskFreeRateParams(**(params or {}))

    def rate(self, settings: UserSettings) -> float:
        """Return the user's annual risk-free rate as a fraction."""
        return settings.risk_free_rate
