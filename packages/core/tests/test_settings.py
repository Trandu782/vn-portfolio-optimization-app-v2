"""Unit tests for application and user settings."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.settings import Settings, UserSettings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000


def test_settings_read_env_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VNOPT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("VNOPT_API_PORT", "9001")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
    assert settings.api_port == 9001


def test_user_settings_defaults() -> None:
    user = UserSettings()
    assert user.brokerage_fee_rate == Decimal("0.0015")
    assert user.risk_free_rate == pytest.approx(0.03)


def test_user_settings_accepts_bounds() -> None:
    low = UserSettings(
        brokerage_fee_rate=Decimal("0"), risk_free_rate=0.0
    )
    assert low.brokerage_fee_rate == Decimal("0")
    assert low.risk_free_rate == pytest.approx(0.0)

    high = UserSettings(
        brokerage_fee_rate=Decimal("0.01"), risk_free_rate=0.20
    )
    assert high.brokerage_fee_rate == Decimal("0.01")
    assert high.risk_free_rate == pytest.approx(0.20)


def test_user_settings_reject_negative_fee() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserSettings(brokerage_fee_rate=Decimal("-0.01"))
    assert "between 0 and 0.01" in str(exc_info.value)


def test_user_settings_reject_fee_above_max() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserSettings(brokerage_fee_rate=Decimal("0.02"))
    assert "between 0 and 0.01" in str(exc_info.value)


def test_user_settings_reject_negative_risk_free_rate() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserSettings(risk_free_rate=-0.01)
    assert "between 0 and 0.20" in str(exc_info.value)


def test_user_settings_reject_risk_free_rate_above_max() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UserSettings(risk_free_rate=0.25)
    assert "between 0 and 0.20" in str(exc_info.value)

