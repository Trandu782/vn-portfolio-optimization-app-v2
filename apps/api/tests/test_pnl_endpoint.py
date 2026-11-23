"""Tests for ``POST /api/v1/pnl/evaluate``.

A temporary SQLite database is seeded directly (no network) with symbol and
VN-Index price series whose buy date is the switch point, so the P&L, net-of-cost
and buy-date comparison are deterministic.
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
from data.db.repositories import (
    SqlIndexRepository,
    SqlPriceRepository,
    SqlSymbolRepository,
)
from data.models import PriceBar, SymbolInfo
from data.offline import StaticHttpClient
from data.settings import get_settings

TODAY = date(2024, 1, 8)  # a Monday, so the last trading day is TODAY itself.
BUY = date(2023, 12, 20)
START = date(2023, 12, 1)


def _bars(early: float, late: float, switch: date) -> list[PriceBar]:
    """Daily bars from START to TODAY; ``late`` from the day after ``switch``."""
    rows: list[PriceBar] = []
    day = START
    while day <= TODAY:
        close = early if day <= switch else late
        rows.append(
            PriceBar(
                date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=100_000,
                value=close * 100_000.0,
                source="test",
            )
        )
        day += timedelta(days=1)
    return rows


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'pnl.db'}")
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
        indices = SqlIndexRepository(session)
        for code in ("VNM", "FPT"):
            symbols.upsert(SymbolInfo(code=code, exchange="HOSE", type="stock", source="test"))
        prices.upsert_many("VNM", _bars(early=40_000.0, late=50_000.0, switch=BUY))
        prices.upsert_many("FPT", _bars(early=80_000.0, late=80_000.0, switch=BUY))
        indices.upsert_many("VNINDEX", _bars(early=1_000.0, late=1_100.0, switch=BUY))
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "holdings": [
            {"symbol": "VNM", "shares": 100, "avg_cost": 40_000, "buy_date": BUY.isoformat()},
            {"symbol": "FPT", "shares": 200, "avg_cost": 60_000},
        ],
        "cash": 5_000_000,
    }
    body.update(overrides)
    return body


def test_evaluate_returns_summary_and_rows(client: TestClient) -> None:
    response = client.post("/api/v1/pnl/evaluate", json=_payload())
    assert response.status_code == 200
    body = response.json()

    summary = body["summary"]
    assert summary["market_value_total"] == pytest.approx(21_000_000.0)
    assert summary["cost_basis_total"] == 16_000_000
    assert summary["unrealized_pnl_total"] == pytest.approx(5_000_000.0)
    assert summary["unrealized_pnl_pct"] == pytest.approx(5_000_000.0 / 16_000_000.0)
    assert summary["sell_fee_total"] == 31_500
    assert summary["sell_tax_total"] == 21_000
    assert summary["net_of_costs_total"] == pytest.approx(4_947_500.0)
    assert summary["cash"] == 5_000_000
    assert summary["total_value"] == pytest.approx(26_000_000.0)
    assert summary["excluded_count"] == 0

    assert body["assumptions"]["brokerage_fee_rate"] == pytest.approx(0.0015)
    assert body["sell_tax"] == pytest.approx(0.001)

    rows = {item["symbol"]: item for item in body["holdings"]}
    vnm = rows["VNM"]
    assert vnm["cost_basis"] == 4_000_000
    assert vnm["market_value"] == pytest.approx(5_000_000.0)
    assert vnm["unrealized_pnl"] == pytest.approx(1_000_000.0)
    assert vnm["unrealized_pnl_pct"] == pytest.approx(0.25)
    assert vnm["net_of_costs"] == pytest.approx(987_500.0)
    assert vnm["buy_date"] == BUY.isoformat()
    # Stock 40,000 -> 50,000 (+25%) while VN-Index 1,000 -> 1,100 (+10%).
    assert vnm["buy_price"] == pytest.approx(40_000.0)
    assert vnm["price_return"] == pytest.approx(0.25)
    assert vnm["benchmark_return"] == pytest.approx(0.10)
    assert vnm["beat_market"] is True

    fpt = rows["FPT"]
    assert fpt["buy_date"] is None
    assert fpt["price_return"] is None
    assert fpt["net_of_costs"] == pytest.approx(3_960_000.0)


def test_missing_avg_cost_is_excluded(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pnl/evaluate",
        json=_payload(
            holdings=[
                {"symbol": "VNM", "shares": 100},
                {"symbol": "FPT", "shares": 200, "avg_cost": 60_000},
            ],
            cash=0,
        ),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["excluded_count"] == 1
    assert body["summary"]["cost_basis_total"] == 12_000_000
    assert body["summary"]["unrealized_pnl_total"] == pytest.approx(4_000_000.0)
    rows = {item["symbol"]: item for item in body["holdings"]}
    assert rows["VNM"]["missing_avg_cost"] is True
    assert rows["VNM"]["unrealized_pnl"] is None
    assert any("enter your average cost" in warning for warning in body["warnings"])


def test_settings_override_the_brokerage_fee(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pnl/evaluate",
        json=_payload(settings={"brokerage_fee_rate": 0.0, "risk_free_rate": 0.03}),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["sell_fee_total"] == 0
    assert body["summary"]["net_of_costs_total"] == pytest.approx(4_979_000.0)
    assert body["assumptions"]["brokerage_fee_rate"] == pytest.approx(0.0)


def test_wishlist_holding_is_ignored(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pnl/evaluate",
        json=_payload(
            holdings=[
                {"symbol": "VNM", "shares": 0},
                {"symbol": "FPT", "shares": 200, "avg_cost": 60_000},
            ],
            cash=0,
        ),
    )
    assert response.status_code == 200
    body = response.json()

    assert [item["symbol"] for item in body["holdings"]] == ["FPT"]
    assert body["summary"]["excluded_count"] == 0
    assert body["summary"]["market_value_total"] == pytest.approx(16_000_000.0)


def test_buy_date_after_all_data_is_flagged(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pnl/evaluate",
        json=_payload(
            holdings=[
                {"symbol": "VNM", "shares": 100, "avg_cost": 40_000, "buy_date": "2025-01-01"}
            ],
            cash=0,
        ),
    )
    assert response.status_code == 200
    body = response.json()

    [row] = body["holdings"]
    assert row["buy_date"] == "2025-01-01"
    assert row["price_return"] is None
    assert any("not enough price history" in warning for warning in body["warnings"])


def test_duplicate_symbols_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pnl/evaluate",
        json=_payload(
            holdings=[
                {"symbol": "VNM", "shares": 1},
                {"symbol": "vnm", "shares": 2},
            ]
        ),
    )
    assert response.status_code == 422
    assert "duplicate" in response.text.lower()
