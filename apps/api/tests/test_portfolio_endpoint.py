"""Tests for ``POST /api/v1/portfolio/evaluate``.

A temporary SQLite database is seeded directly (no network) so valuation, weights
and freshness are deterministic. An unknown ticker with an empty fixture client
exercises the "queued for backfill" path.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all, session_scope
from data.db.repositories import SqlPriceRepository, SqlSymbolRepository
from data.models import PriceBar, SymbolInfo
from data.offline import StaticHttpClient
from data.settings import get_settings
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

TODAY = date(2024, 1, 8)  # a Monday, so the last trading day is TODAY itself.
#: The previous trading session (Friday), used to model a ticker that trails the
#: market by exactly one session.
PRIOR_SESSION = date(2024, 1, 5)


def _prices(
    end: date, count: int, close: float, *, volume: int = 100_000, source: str = "kbs"
) -> list[PriceBar]:
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
            volume=volume,
            value=float(volume) * close,
            source=source,
        )
        for offset in range(count)
    ]


def _v2_prices(
    end: date, count: int, *, close: float, close_raw: float, source: str = "ssi_statistics"
) -> list[AdjustedOHLCV]:
    """Return ``count`` V2 adjusted bars ending at ``end``.

    ``close`` is the adjusted close and ``close_raw`` the raw/spot close, so a test can
    exercise the Portfolio's V2-spot reader (which values on ``close_raw``).
    """
    start = end - timedelta(days=count - 1)
    return [
        AdjustedOHLCV(
            date=start + timedelta(days=offset),
            open=close_raw,
            high=close_raw,
            low=close_raw,
            close=close,
            close_raw=close_raw,
            volume=100_000,
            value=float(100_000) * close_raw,
            source=source,
        )
        for offset in range(count)
    ]


def _seed_v2(
    session_factory, code: str, bars: list[AdjustedOHLCV], *, basis: str = "ssi_adjusted"
) -> None:
    """Upsert V2 bars for ``code`` (used by the V2-preference tests)."""
    with session_scope(session_factory) as session:
        V2Store(session).upsert_prices(
            code, bars, price_adjustment_basis=basis, data_as_of=TODAY
        )


@pytest.fixture
def session_factory(tmp_path, monkeypatch) -> Iterator[sessionmaker[Session]]:
    """A temporary database context; the seeded engine factory for V2-preference tests."""
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'portfolio.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)
    yield context.session_factory
    data_pkg.set_context(None)
    get_settings.cache_clear()


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    with session_scope(session_factory) as session:
        symbols = SqlSymbolRepository(session)
        prices = SqlPriceRepository(session)
        seed = (
            ("VNM", 50_000.0, 30, 100_000, TODAY),
            ("FPT", 100_000.0, 30, 100_000, TODAY),
            ("THIN", 10_000.0, 30, 0, TODAY),
            ("LOWLIQ", 10_000.0, 30, 1_000, TODAY),
            ("SUSP", 20_000.0, 30, 100_000, TODAY - timedelta(days=40)),
        )
        for code, close, count, volume, end in seed:
            symbols.upsert(SymbolInfo(code=code, exchange="HOSE", type="stock", source="test"))
            prices.upsert_many(code, _prices(end, count, close, volume=volume))
    with TestClient(create_app()) as test_client:
        yield test_client


def test_evaluate_returns_prices_values_and_weights(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={
            "holdings": [
                {"symbol": "VNM", "shares": 100, "avg_cost": 40_000},
                {"symbol": "FPT", "shares": 200, "avg_cost": None},
            ],
            "cash": 5_000_000,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["cash"] == 5_000_000
    assert body["market_value_total"] == pytest.approx(25_000_000.0)
    assert body["total_value"] == pytest.approx(30_000_000.0)
    assert body["market_values"]["VNM"] == pytest.approx(5_000_000.0)
    assert body["weights"]["FPT"] == pytest.approx(20 / 30)
    assert body["cash_weight"] == pytest.approx(5 / 30)

    holdings = {item["symbol"]: item for item in body["holdings"]}
    assert holdings["VNM"]["latest_price"] == pytest.approx(50_000.0)
    assert holdings["VNM"]["market_value"] == pytest.approx(5_000_000.0)
    assert holdings["VNM"]["avg_cost"] == 40_000
    assert holdings["VNM"]["wishlist"] is False
    assert holdings["VNM"]["source"] == "kbs"
    assert body["freshness"]["source"] == "kbs"
    assert body["freshness"]["stale"] is False
    assert body["freshness"]["latest_date"] == TODAY.isoformat()
    assert body["warnings"] == []


def test_wishlist_holding_has_zero_value_and_weight(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "VNM", "shares": 100}, {"symbol": "FPT", "shares": 0}]},
    )
    assert response.status_code == 200
    body = response.json()

    holdings = {item["symbol"]: item for item in body["holdings"]}
    assert holdings["FPT"]["wishlist"] is True
    assert holdings["FPT"]["market_value"] == 0.0
    assert holdings["FPT"]["weight"] == 0.0
    assert holdings["FPT"]["latest_price"] == pytest.approx(100_000.0)
    assert body["weights"]["FPT"] == 0.0


def test_evaluate_warns_for_illiquid_and_suspended(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "THIN", "shares": 10}, {"symbol": "SUSP", "shares": 10}]},
    )
    assert response.status_code == 200
    holdings = {item["symbol"]: item for item in response.json()["holdings"]}
    assert any("illiquid" in warning for warning in holdings["THIN"]["warnings"])
    suspended = [warning for warning in holdings["SUSP"]["warnings"] if "suspended" in warning]
    assert suspended and "no price bar for the most recent trading session" in suspended[0]


def test_evaluate_warns_for_low_liquidity(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "LOWLIQ", "shares": 10}]},
    )
    assert response.status_code == 200
    holdings = {item["symbol"]: item for item in response.json()["holdings"]}
    assert any("low liquidity" in warning for warning in holdings["LOWLIQ"]["warnings"])


def test_unknown_symbol_is_queued_for_backfill(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "ZZZ", "shares": 10}]},
    )
    assert response.status_code == 200
    body = response.json()
    [holding] = body["holdings"]

    assert holding["latest_price"] is None
    assert holding["market_value"] == 0.0
    assert any("queued" in warning for warning in holding["warnings"])
    assert any("missing price" in warning for warning in holding["warnings"])
    assert any("queued for backfill" in warning for warning in body["warnings"])


def test_cash_only_portfolio(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate", json={"holdings": [], "cash": 1_000_000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["holdings"] == []
    assert body["total_value"] == pytest.approx(1_000_000.0)
    assert body["cash_weight"] == pytest.approx(1.0)


def test_duplicate_symbols_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "VNM", "shares": 1}, {"symbol": "vnm", "shares": 2}]},
    )
    assert response.status_code == 422
    assert "duplicate" in response.text.lower()


def test_negative_shares_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "VNM", "shares": -5}]},
    )
    assert response.status_code == 422


def test_portfolio_prefers_v2_latest_over_stale_v1(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """A fresh V2 spot bar wins over a stale V1 bar for the same ticker."""
    # Make FPT's V1 series stale (ends on Friday) and give FPT a fresh V2 bar at TODAY.
    with session_scope(session_factory) as session:
        prices = SqlPriceRepository(session)
        prices.delete("FPT")
        prices.upsert_many("FPT", _prices(PRIOR_SESSION, 30, 45_000.0))
    _seed_v2(
        session_factory,
        "FPT",
        _v2_prices(TODAY, 30, close=46_850.0, close_raw=46_850.0),
    )

    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "FPT", "shares": 100}]},
    )
    assert response.status_code == 200
    body = response.json()
    [holding] = body["holdings"]

    # V2's raw (spot) close and fresher date win over the stale V1 bar.
    assert holding["latest_price"] == pytest.approx(46_850.0)
    assert holding["latest_date"] == TODAY.isoformat()
    assert holding["source"] == "ssi_statistics"
    assert holding["market_value"] == pytest.approx(4_685_000.0)
    # The summary reports the true V2 source/date.
    assert body["freshness"]["source"] == "ssi_statistics"
    assert body["freshness"]["latest_date"] == TODAY.isoformat()
    # The freshest bar is current, so the holding is not flagged stale.
    assert not any("stale" in warning for warning in holding["warnings"])


def test_holding_lagging_the_latest_session_is_flagged_stale(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """A holding whose latest bar trails the global latest session gets a stale flag."""
    # FPT only has V1 data through the prior session; VNM (seeded by the fixture) is
    # current at TODAY, so the global latest session is TODAY.
    with session_scope(session_factory) as session:
        prices = SqlPriceRepository(session)
        prices.delete("FPT")
        prices.upsert_many("FPT", _prices(PRIOR_SESSION, 30, 45_000.0))

    response = client.post(
        "/api/v1/portfolio/evaluate",
        json={
            "holdings": [
                {"symbol": "VNM", "shares": 100},
                {"symbol": "FPT", "shares": 100},
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    holdings = {item["symbol"]: item for item in body["holdings"]}

    fpt = holdings["FPT"]
    assert fpt["latest_date"] == PRIOR_SESSION.isoformat()
    stale = [warning for warning in fpt["warnings"] if "stale" in warning]
    assert stale, "a lagging holding must be flagged stale instead of ok"
    assert PRIOR_SESSION.isoformat() in stale[0]

    # The current holding is not flagged.
    assert not any("stale" in warning for warning in holdings["VNM"]["warnings"])

