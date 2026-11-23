"""Tests for the data-freshness and provider-status routes.

A temporary SQLite database is seeded directly (no network) so the latest date
and the active provider are deterministic.
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


def _prices(end: date, count: int, close: float) -> list[PriceBar]:
    """Return ``count`` daily bars ending at ``end``, sourced from KBS."""
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
            source="kbs",
        )
        for offset in range(count)
    ]


@pytest.fixture
def session_factory(tmp_path, monkeypatch) -> Iterator[sessionmaker[Session]]:
    """A temporary database context; the seeded engine factory for the V2 test."""
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'data.db'}")
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
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="VNM", exchange="HOSE", type="stock", source="test")
        )
        SqlPriceRepository(session).upsert_many("VNM", _prices(TODAY, 30, 50_000.0))
    with TestClient(create_app()) as test_client:
        yield test_client


def test_freshness_reports_latest_date_and_active_provider(client: TestClient) -> None:
    response = client.get("/api/v1/data/freshness")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_date"] == TODAY.isoformat()
    assert body["primary"] == "kbs"
    assert body["stale"] is False
    assert [item["id"] for item in body["providers"]] == ["kbs"]


def test_freshness_prefers_the_v2_source_when_it_owns_the_latest_bar(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """The badge reports the V2 source/date when the V2 precompute is current."""
    with session_scope(session_factory) as session:
        V2Store(session).upsert_prices(
            "VNM",
            [
                AdjustedOHLCV(
                    date=TODAY,
                    open=50_000.0,
                    high=50_000.0,
                    low=50_000.0,
                    close=50_000.0,
                    close_raw=50_000.0,
                    volume=100_000,
                    source="ssi_statistics",
                )
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=TODAY,
        )

    response = client.get("/api/v1/data/freshness")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_date"] == TODAY.isoformat()
    assert body["primary"] == "ssi_statistics"
    assert body["stale"] is False


def test_provider_status_lists_kbs_first(client: TestClient) -> None:
    response = client.get("/api/v1/data/providers/status")
    assert response.status_code == 200
    [status] = response.json()
    assert status["id"] == "kbs"
    assert status["healthy"] is True
