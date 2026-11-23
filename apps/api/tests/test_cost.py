"""Tests for the rebalance cost endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.costs import commission
from core.settings import UserSettings


def test_cost_applies_default_settings_when_missing() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/rebalance/cost", json={"notional": 100_000_000})

    assert response.status_code == 200
    payload = response.json()
    defaults = UserSettings()
    expected = commission(100_000_000, defaults.brokerage_fee_rate)
    assert payload["assumptions"]["brokerage_fee_rate"] == pytest.approx(
        float(defaults.brokerage_fee_rate)
    )
    assert payload["assumptions"]["risk_free_rate"] == pytest.approx(defaults.risk_free_rate)
    assert payload["commission"] == expected
    assert payload["round_trip_commission"] == expected * 2


def test_higher_fee_raises_reported_cost() -> None:
    client = TestClient(app)
    low = client.post(
        "/api/v1/rebalance/cost",
        json={"notional": 100_000_000, "settings": {"brokerage_fee_rate": 0.0015}},
    ).json()
    high = client.post(
        "/api/v1/rebalance/cost",
        json={"notional": 100_000_000, "settings": {"brokerage_fee_rate": 0.0025}},
    ).json()
    assert high["commission"] > low["commission"]
    assert high["assumptions"]["brokerage_fee_rate"] == pytest.approx(0.0025)


def test_cost_rejects_out_of_range_fee() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/rebalance/cost",
        json={"notional": 100_000_000, "settings": {"brokerage_fee_rate": 0.05}},
    )
    assert response.status_code == 422
