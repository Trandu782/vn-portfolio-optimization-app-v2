"""End-to-end API tests: refresh, on-demand backfill, reads, probe and auth.

The whole pipeline runs against recorded fixtures (no network) and a temporary
SQLite database, mirroring the acceptance scenario of syncing benchmarks + a
ticker and reading them back through the API.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from support import load_fixture, make_bar

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all, session_scope
from data.db.repositories import (
    SqlConstituentRepository,
    SqlPriceRepository,
    SqlSymbolRepository,
)
from data.models import SymbolInfo
from data.offline import StaticHttpClient
from data.seed import seed_symbols
from data.settings import get_settings

TOKEN = "test-token"
TODAY = date(2024, 1, 8)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_REFRESH_TOKEN", TOKEN)
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "tcbs")
    get_settings.cache_clear()
    http = StaticHttpClient(
        {
            "/bars-long-term": load_fixture("tcbs_bars.json"),
            "/index/constituents": load_fixture("tcbs_constituents.json"),
        }
    )
    context = DataContext(get_settings(), http=http, today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def test_protected_endpoints_require_token(client: TestClient) -> None:
    assert client.post("/api/v1/data/refresh").status_code == 401
    assert client.get("/api/v1/data/probe").status_code == 401


def test_refresh_and_read_through_api(client: TestClient) -> None:
    refresh = client.post("/api/v1/data/refresh", headers=_auth())
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["done"] is True
    assert body["processed"] == 4  # four benchmarks, no symbols yet

    with session_scope(data_pkg.get_context().session_factory) as session:
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="VNM", exchange="HOSE", type="stock", source="test")
        )

    prices = client.get("/api/v1/prices/VNM")
    assert prices.status_code == 200
    payload = prices.json()
    assert payload["status"] == "ok"
    assert len(payload["rows"]) == 5
    assert payload["rows"][0]["source"] == "tcbs"

    symbols = client.get("/api/v1/symbols").json()
    assert symbols["count"] == 1
    assert symbols["symbols"][0]["code"] == "VNM"

    quality = client.get("/api/v1/data/quality/VNM").json()
    assert set(quality["checks_run"]) == {
        "missing_trading_days",
        "stale_price_runs",
        "zero_volume",
        "price_limit_move",
    }

    status = client.get("/api/v1/data/providers/status").json()
    assert status[0]["id"] == "tcbs"
    assert status[0]["returns_adjusted_prices"] is False

    index = client.get("/api/v1/data/index/VNINDEX")
    assert index.status_code == 200
    assert index.json()["rows"]

    probe = client.get(
        "/api/v1/data/probe",
        headers=_auth(),
        params={"tickers": "VNM", "index_code": "VNINDEX"},
    )
    assert probe.status_code == 200
    assert probe.json()["providers"][0]["provider"] == "tcbs"


def test_cached_data_served_with_stale_warning_when_providers_down(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'api3.db'}")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    with session_scope(context.session_factory) as session:
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="VNM", exchange="HOSE", source="tcbs")
        )
        SqlPriceRepository(session).upsert_many(
            "VNM",
            [
                make_bar(date(2023, 6, 1), 50.0, source="tcbs"),
                make_bar(date(2023, 6, 2), 51.0, source="tcbs"),
            ],
        )
    data_pkg.set_context(context)

    response = client.get("/api/v1/prices/VNM")
    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert len(body["rows"]) == 2
    assert any("stale" in warning.lower() for warning in body["warnings"])


def test_unknown_symbol_with_all_providers_down_is_queued(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'api2.db'}")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)

    response = client.get("/api/v1/prices/XYZ")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["rows"] == []
    assert any("queued for next sync" in warning for warning in body["warnings"])


def test_symbols_endpoint_seeds_reference_data_when_offline(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'api_seed.db'}")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)

    response = client.get("/api/v1/symbols")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(seed_symbols())
    assert "VNM" in {symbol["code"] for symbol in body["symbols"]}
    assert {symbol["source"] for symbol in body["symbols"]} == {"seed"}

    with session_scope(context.session_factory) as session:
        assert "VNM" in SqlConstituentRepository(session).get("VN30")
