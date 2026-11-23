"""Tests for the settings endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.settings import UserSettings


def test_settings_returns_defaults_and_bounds() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    payload = response.json()
    defaults = UserSettings()
    assert payload["defaults"]["brokerage_fee_rate"] == pytest.approx(
        float(defaults.brokerage_fee_rate)
    )
    assert payload["defaults"]["risk_free_rate"] == pytest.approx(defaults.risk_free_rate)
    assert payload["bounds"]["brokerage_fee_rate"] == {"min": 0.0, "max": 0.01}
    assert payload["bounds"]["risk_free_rate"] == {"min": 0.0, "max": 0.2}
