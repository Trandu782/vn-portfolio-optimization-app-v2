"""Tests for the rebalance endpoints (options and the full rebalance).

A temporary SQLite database is seeded with smooth price series (no network): an
empty recorded-fixture HTTP client makes any accidental provider call fail.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all, session_scope
from data.db.repositories import SqlPriceRepository, SqlSymbolRepository
from data.models import PriceBar, SymbolInfo
from data.offline import StaticHttpClient
from data.settings import get_settings

TODAY = date(2024, 1, 8)  # a Monday, so the last trading day is TODAY itself.


def _prices(end: date, count: int, close: float, *, source: str = "kbs") -> list[PriceBar]:
    """Return ``count`` daily bars ending at ``end`` (source defaults to KBS)."""
    start = end - timedelta(days=count - 1)
    return [
        PriceBar(
            date=start + timedelta(days=offset),
            open=close,
            high=close,
            low=close,
            close=close,
            adj_close=close,
            volume=100_000,
            value=float(100_000) * close,
            source=source,
        )
        for offset in range(count)
    ]


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'rebalance.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    get_settings.cache_clear()
    context = DataContext(
        get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY
    )
    create_all(context.engine)
    data_pkg.set_context(context)
    with session_scope(context.session_factory) as session:
        symbols = SqlSymbolRepository(session)
        prices = SqlPriceRepository(session)
        for code, close in (("VNM", 50_000.0), ("FPT", 100_000.0), ("ACB", 30_000.0)):
            symbols.upsert(SymbolInfo(code=code, exchange="HOSE", type="stock", source="test"))
            prices.upsert_many(code, _prices(TODAY, 30, close))
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def test_options_publish_cost_models_and_policies(client: TestClient) -> None:
    response = client.get("/api/v1/rebalance/options")
    assert response.status_code == 200
    body = response.json()

    assert "vn" in {item["id"] for item in body["cost_models"]}
    assert {"full", "threshold_band"} <= {item["id"] for item in body["policies"]}
    assert body["defaults"]["policy"] == "full"
    assert body["defaults"]["cost_model"] == "vn"
    assert body["defaults"]["min_notional"] == 1_000_000


def test_rebalance_returns_placeable_orders(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [
                {"symbol": "VNM", "shares": 1000, "avg_cost": 40_000},
                {"symbol": "FPT", "shares": 200},
            ],
            "cash": 30_000_000,
            "target_weights": {"VNM": 0.3, "FPT": 0.5},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_value"] == pytest.approx(100_000_000.0)
    assert body["cash_weight"] == pytest.approx(0.3)
    assert body["target_cash_weight"] == pytest.approx(0.2)

    assert [order["side"] for order in body["orders"]] == ["sell", "buy"]
    sell, buy = body["orders"]
    assert (sell["symbol"], sell["lots"], sell["shares"], sell["value"]) == (
        "VNM",
        4,
        400,
        20_000_000,
    )
    assert (sell["fee"], sell["tax"]) == (30_000, 20_000)
    assert (buy["symbol"], buy["lots"], buy["shares"], buy["value"]) == (
        "FPT",
        3,
        300,
        30_000_000,
    )
    assert (buy["fee"], buy["tax"]) == (45_000, 0)
    assert all(order["shares"] % 100 == 0 for order in body["orders"])

    assert body["total_fee"] == 75_000
    assert body["total_tax"] == 20_000
    assert body["total_cost"] == 95_000
    assert body["turnover"] == 50_000_000
    assert body["residual_cash"] == 19_905_000

    assumptions = body["assumptions"]
    assert assumptions["brokerage_fee_rate"] == pytest.approx(0.0015)
    assert assumptions["sell_tax"] == pytest.approx(0.001)
    assert assumptions["prices_adjusted"] is False
    assert assumptions["data_sources"] == ["kbs"]
    assert assumptions["latest_date"] == TODAY.isoformat()


def test_rebalance_never_sells_more_than_held(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [{"symbol": "VNM", "shares": 250}],
            "cash": 0,
            "target_weights": {"VNM": 0.0},
        },
    )
    assert response.status_code == 200, response.text
    [order] = response.json()["orders"]
    assert order["side"] == "sell"
    assert order["shares"] == 200  # two whole lots; 50 odd-lot shares stay
    assert order["shares"] <= 250
    assert order["shares"] % 100 == 0


def test_threshold_policy_skips_small_drifts(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [
                {"symbol": "VNM", "shares": 500},
                {"symbol": "FPT", "shares": 250},
            ],
            "target_weights": {"VNM": 0.52, "FPT": 0.48},
            "policy": "threshold_band",
            "policy_params": {"band": 0.10},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["orders"] == []
    positions = {item["symbol"]: item for item in body["positions"]}
    assert positions["VNM"]["target_weight"] == pytest.approx(0.5)


def test_settings_fee_is_applied(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [{"symbol": "VNM", "shares": 1000}],
            "target_weights": {"VNM": 0.0},
            "settings": {"brokerage_fee_rate": 0.002, "risk_free_rate": 0.03},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assumptions"]["brokerage_fee_rate"] == pytest.approx(0.002)
    [trade] = body["orders"]
    assert trade["value"] == 50_000_000
    assert body["total_fee"] == 100_000
    assert body["total_tax"] == 50_000


def test_unknown_policy_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [{"symbol": "VNM", "shares": 100}],
            "target_weights": {"VNM": 1.0},
            "policy": "does-not-exist",
        },
    )
    assert response.status_code == 422


def test_missing_price_is_a_warning(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [{"symbol": "VNM", "shares": 100}],
            "target_weights": {"VNM": 0.5, "ZZZ": 0.5},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("missing price for ZZZ" in warning for warning in body["warnings"])
    assert all(order["symbol"] != "ZZZ" for order in body["orders"])


def test_duplicate_holdings_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance",
        json={
            "holdings": [
                {"symbol": "VNM", "shares": 10},
                {"symbol": "vnm", "shares": 20},
            ],
            "target_weights": {"VNM": 1.0},
        },
    )
    assert response.status_code == 422
    assert "duplicate" in response.text.lower()


def test_empty_request_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rebalance", json={"holdings": [], "target_weights": {}}
    )
    assert response.status_code == 422
