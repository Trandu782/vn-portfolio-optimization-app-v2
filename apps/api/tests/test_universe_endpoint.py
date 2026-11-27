"""Tests for the universe endpoints (options, presets, build, backfill).

The whole pipeline runs against a temporary SQLite database seeded directly (no
network): the fixture sets an empty recorded-fixture HTTP client so any accidental
provider call fails and the on-demand backfill is exercised as "queued".
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
from data.db.repositories import SqlSymbolRepository
from data.models import PriceBar, SymbolInfo
from data.offline import StaticHttpClient
from data.settings import get_settings
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

TODAY = date(2024, 1, 8)
START = date(2023, 1, 2)
END = date(2023, 2, 10)  # last bar of the 40-session series


def _v2_bars(start: date, count: int, *, value: float) -> list[AdjustedOHLCV]:
    """Return ``count`` V2 adjusted bars from ``start`` (the universe's only source)."""
    return [
        AdjustedOHLCV(
            date=start + timedelta(days=offset),
            open=50.0,
            high=51.0,
            low=49.0,
            close=50.0,
            close_raw=50.0,
            volume=100_000,
            value=value,
            source="test",
        )
        for offset in range(count)
    ]


def _price_bar(day: date) -> PriceBar:
    """Return one minimal :class:`PriceBar` on ``day`` for the staleness helper."""
    return PriceBar(
        date=day,
        open=50.0,
        high=50.0,
        low=50.0,
        close=50.0,
        adj_close=50.0,
        volume=1_000,
        value=50_000.0,
        source="test",
    )


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'universe.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)
    with session_scope(context.session_factory) as session:
        symbols = SqlSymbolRepository(session)
        store = V2Store(session)
        seed = (
            ("LIQ", "HOSE", 40, 2_000_000_000.0),
            ("THIN", "HOSE", 40, 1_000_000.0),
            ("SHORT", "HOSE", 5, 2_000_000_000.0),
            ("HNX1", "HNX", 40, 2_000_000_000.0),
            # Active blue chips whose V2 backfill stops a few sessions before END,
            # so they are stale but never suspended.
            ("VHM", "HOSE", 35, 2_000_000_000.0),
            ("DCM", "HOSE", 35, 2_000_000_000.0),
        )
        for code, exchange, count, value in seed:
            symbols.upsert(
                SymbolInfo(code=code, exchange=exchange, type="stock", source="test")
            )
            store.upsert_prices(
                code,
                _v2_bars(START, count, value=value),
                price_adjustment_basis="ssi_adjusted",
                data_as_of=TODAY,
            )
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def test_options_publish_filters_and_presets(client: TestClient) -> None:
    response = client.get("/api/v1/universe/options")
    assert response.status_code == 200
    body = response.json()

    filter_ids = {item["id"] for item in body["filters"]}
    assert {"exchange", "min_adv", "exclude_suspended", "min_history"} <= filter_ids
    min_adv = next(item for item in body["filters"] if item["id"] == "min_adv")
    assert min_adv["parameter_schema"]["properties"]["min_value_vnd"]["default"] == 1e9

    preset_ids = {item["id"] for item in body["presets"]}
    assert "VN30" in preset_ids


def test_preset_endpoint_returns_vn30_members(client: TestClient) -> None:
    response = client.get("/api/v1/universe/presets/VN30")
    assert response.status_code == 200
    body = response.json()
    assert body["index_code"] == "VN30"
    assert body["count"] == len(body["symbols"])
    assert body["count"] > 0
    assert "ACB" in body["symbols"]


def test_unknown_preset_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/universe/presets/DOESNOTEXIST").status_code == 404


def test_build_applies_filters_and_reports_reasons(client: TestClient) -> None:
    response = client.post(
        "/api/v1/universe/build",
        json={
            "symbols": ["LIQ", "THIN", "SHORT", "HNX1"],
            "filters": [
                {"id": "exchange", "params": {"exchange": "HOSE"}},
                {"id": "min_adv", "params": {"min_value_vnd": 100_000_000, "sessions": 20}},
                {"id": "min_history", "params": {"min_sessions": 40}},
            ],
            "start": START.isoformat(),
            "end": END.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["symbols"] == ["LIQ"]
    dropped = {item["code"]: item for item in body["dropped"]}
    assert set(dropped) == {"THIN", "SHORT", "HNX1"}
    assert dropped["HNX1"]["filter"] == "exchange"
    assert dropped["THIN"]["filter"] == "min_adv"
    assert dropped["SHORT"]["filter"] == "min_history"
    assert all(item["reason"].strip() for item in body["dropped"])

    assert body["price_matrix"]["columns"] == ["LIQ"]
    assert len(body["price_matrix"]["dates"]) == 40
    assert len(body["price_matrix"]["data"]) == 40
    assert body["returns_matrix"]["columns"] == ["LIQ"]
    assert body["adv_by_symbol"]["LIQ"] == pytest.approx(2_000_000_000.0)
    assert body["quality_flags"]["LIQ"]["illiquid"] is False


def test_build_drops_missing_symbol_with_reason(client: TestClient) -> None:
    response = client.post(
        "/api/v1/universe/build",
        json={"symbols": ["MISSING"], "start": START.isoformat(), "end": END.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbols"] == []
    [dropped] = body["dropped"]
    assert dropped["code"] == "MISSING"
    assert "no price data" in dropped["reason"]


def test_build_never_reports_a_trailing_bar_as_suspended(client: TestClient) -> None:
    """VHM/DCM trail END but are actively traded: stale data, never suspended."""
    response = client.post(
        "/api/v1/universe/build",
        json={
            "symbols": ["VHM", "DCM"],
            "filters": [{"id": "exclude_suspended"}, {"id": "exclude_stale_prices"}],
            "start": START.isoformat(),
            "end": END.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["symbols"] == []
    dropped = {item["code"]: item for item in body["dropped"]}
    assert dropped["VHM"]["reason"] == "stale_price_data"
    assert dropped["DCM"]["reason"] == "stale_price_data"
    assert dropped["VHM"]["filter"] == "exclude_stale_prices"
    assert dropped["DCM"]["filter"] == "exclude_stale_prices"


def test_has_stale_bars_treats_2026_11_24_as_a_holiday() -> None:
    """2026-11-24 was a market holiday; 2026-11-25 is a normal session."""
    from app.api.v1.universe import _has_stale_bars

    session = date(2026, 11, 25)
    # A bar on the session itself is current.
    assert _has_stale_bars([_price_bar(session)], session) is False
    # One business day behind (2026-11-24 a holiday) is within the one-session
    # tolerance, so it is not flagged.
    assert _has_stale_bars([_price_bar(date(2026, 11, 23))], session) is False
    # Two sessions behind (11-23 and 11-25, since 11-24 is closed) is stale.
    assert _has_stale_bars([_price_bar(date(2026, 11, 20))], session) is True


def test_build_rejects_unknown_filter(client: TestClient) -> None:
    response = client.post(
        "/api/v1/universe/build",
        json={
            "symbols": ["LIQ"],
            "filters": [{"id": "does-not-exist", "params": {}}],
            "start": START.isoformat(),
            "end": END.isoformat(),
        },
    )
    assert response.status_code == 422


def test_backfill_endpoint_requires_token(client: TestClient) -> None:
    response = client.post("/api/v1/data/backfill", json={"symbols": ["liq"]})
    assert response.status_code in (401, 503)

    # With a token configured, unauthenticated calls return 401.
    get_settings.cache_clear()
    import os

    prev = os.environ.get("VNOPT_REFRESH_TOKEN")
    os.environ["VNOPT_REFRESH_TOKEN"] = "unit-test-backfill-token"
    try:
        unauth = client.post("/api/v1/data/backfill", json={"symbols": ["liq"]})
        assert unauth.status_code == 401
    finally:
        if prev is None:
            os.environ.pop("VNOPT_REFRESH_TOKEN", None)
        else:
            os.environ["VNOPT_REFRESH_TOKEN"] = prev
        get_settings.cache_clear()


def test_backfill_endpoint_runs_per_symbol(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VNOPT_REFRESH_TOKEN", "unit-test-backfill-token")
    get_settings.cache_clear()
    response = client.post(
        "/api/v1/data/backfill",
        headers={"Authorization": "Bearer unit-test-backfill-token"},
        json={"symbols": ["liq"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requested"] == 1
    [result] = body["results"]
    assert result["symbol"] == "LIQ"
    assert "status" in result

