"""Tests for GET /api/v1/v2/analytics: validation (422s), cache metadata, payload."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all, session_scope
from data.db.repositories import SqlIndexRepository
from data.models import PriceBar
from data.offline import StaticHttpClient
from data.settings import get_settings
from data.v2.adjustment_quality import adjustment_quality_flag
from data.v2.analytics.cache import clear_analytics_cache
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    TickerRecord,
)
from data.v2.schemas import AdjustedOHLCV, SectorMap
from data.v2.store import V2Store

TODAY = date(2024, 7, 1)
START = date(2024, 1, 2)

_UNIVERSE = {
    "B1": ("Banks", 2_000e9, 0.0008, 0),
    "B2": ("Banks", 1_500e9, 0.0006, 1),
    "B3": ("Banks", 1_200e9, 0.0004, 2),
    "T1": ("Technology", 1_800e9, 0.0010, 3),
    "T2": ("Technology", 1_300e9, 0.0005, 1),
    "T3": ("Technology", 1_100e9, 0.0002, 2),
}


def _weekdays(count: int, start: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(days: list[date], base_return: float, phase: int) -> list[AdjustedOHLCV]:
    bars: list[AdjustedOHLCV] = []
    price = 100.0
    for index, day in enumerate(days):
        bars.append(
            AdjustedOHLCV(
                date=day,
                open=price,
                high=price,
                low=price,
                close=price,
                close_raw=price,
                volume=1_000_000,
                matched_volume=900_000,
                matched_value=price * 900_000,
                source="test",
            )
        )
        pattern = (1.0, -1.0, 0.5, -0.5)[(index + phase) % 4]
        price *= 1.0 + base_return * pattern
    return bars


def _index_bars(days: list[date]) -> list[PriceBar]:
    bars: list[PriceBar] = []
    level = 1000.0
    for index, day in enumerate(days):
        bars.append(
            PriceBar(
                date=day,
                open=level,
                high=level,
                low=level,
                close=level,
                adj_close=level,
                volume=0,
                value=None,
                source="test",
            )
        )
        level *= 1.0 + 0.001 * ((index % 5) - 2)
    return bars


def _seed(session_factory) -> None:
    days = _weekdays(120, START)
    last = days[-1]
    with session_scope(session_factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(ticker=ticker, exchange="HOSE", source="test", data_as_of=last)
                for ticker in _UNIVERSE
            ]
        )
        store.upsert_sectors(
            [
                SectorMap(
                    ticker=ticker,
                    exchange="HOSE",
                    icb_level2_name=sector,
                    source="test",
                    as_of=last,
                )
                for ticker, (sector, _, _, _) in _UNIVERSE.items()
            ]
        )
        store.replace_membership("VN100", list(_UNIVERSE), as_of=last, source="test")
        bars_by_ticker: dict[str, list[AdjustedOHLCV]] = {}
        for ticker, (_, market_cap, base_return, phase) in _UNIVERSE.items():
            bars = _bars(days, base_return, phase)
            bars_by_ticker[ticker] = bars
            store.upsert_prices(
                ticker, bars, price_adjustment_basis="ssi_adjusted", data_as_of=last
            )
            store.upsert_liquidity(
                LiquidityRecord(
                    symbol=ticker,
                    as_of=last,
                    adtv_median=20e9,
                    adv_median=200_000.0,
                    window=20,
                    volume_basis="matched",
                    source="test",
                    data_as_of=last,
                )
            )
            store.upsert_market_cap(
                MarketCapRecord(
                    symbol=ticker,
                    as_of=last,
                    shares_outstanding=100_000_000,
                    market_cap=market_cap,
                    basis="full",
                    source="test",
                    data_as_of=last,
                )
            )
        SqlIndexRepository(session).upsert_many("VNINDEX", _index_bars(days))
        store.upsert_adjustment_flags(
            [
                AdjustmentFlagRecord(
                    ticker=ticker,
                    severity=adjustment_quality_flag(ticker, bars).severity,
                    flagged=adjustment_quality_flag(ticker, bars).flagged,
                    exclude_from_group_indices=adjustment_quality_flag(
                        ticker, bars
                    ).exclude_from_group_indices,
                    reasons=adjustment_quality_flag(ticker, bars).reasons,
                    dates=adjustment_quality_flag(ticker, bars).dates,
                    source="test",
                    data_as_of=last,
                )
                for ticker, bars in bars_by_ticker.items()
            ]
        )


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'analytics.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    _seed(context.session_factory)
    clear_analytics_cache()
    data_pkg.set_context(context)
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    clear_analytics_cache()
    get_settings.cache_clear()


def test_analytics_returns_payload_cold_then_cached(client: TestClient) -> None:
    first = client.get("/api/v1/v2/analytics", params={"timeframe": "YTD"})
    assert first.status_code == 200
    body = first.json()
    assert body["served_from_cache"] is False
    assert body["elapsed_ms"] >= 0.0
    assert body["benchmark_returns"]
    assert {group["index"]["group"] for group in body["groups"]} == {"Banks", "Technology"}

    second = client.get("/api/v1/v2/analytics", params={"timeframe": "YTD"})
    assert second.status_code == 200
    assert second.json()["served_from_cache"] is True


def test_unknown_benchmark_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/v2/analytics", params={"benchmark": "NOPE"})
    assert response.status_code == 422


def test_unknown_preset_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/v2/analytics", params={"liquidity_preset": "bogus"})
    assert response.status_code == 422


def test_unknown_grouping_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/v2/analytics", params={"grouping": "bogus"})
    assert response.status_code == 422


def test_custom_without_dates_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/v2/analytics", params={"timeframe": "custom"})
    assert response.status_code == 422


def test_start_after_end_is_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/v2/analytics",
        params={
            "timeframe": "custom",
            "custom_start": "2024-06-01",
            "custom_end": "2024-05-01",
        },
    )
    assert response.status_code == 422


def test_range_outside_stored_data_is_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/v2/analytics",
        params={
            "timeframe": "custom",
            "custom_start": "2030-01-01",
            "custom_end": "2030-02-01",
        },
    )
    assert response.status_code == 422


def test_bad_cap_percent_is_422(client: TestClient) -> None:
    for cap in ("0", "150", "-5"):
        response = client.get(
            "/api/v1/v2/analytics", params={"cap_percent": cap}
        )
        assert response.status_code == 422


def test_unknown_weighting_is_422(client: TestClient) -> None:
    response = client.get("/api/v1/v2/analytics", params={"weighting": "bogus"})
    assert response.status_code == 422
def test_fundamentals_with_no_ratios_is_404_not_a_stack_trace(
    client: TestClient,
) -> None:
    """A ticker with no stored ratios yields a clear 404, never a blank screen."""
    response = client.get("/api/v1/v2/fundamentals/B1")
    assert response.status_code == 404
    assert "no financial ratios stored" in response.json()["detail"]


def test_fundamentals_unknown_ticker_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/v2/fundamentals/ZZZ")
    assert response.status_code == 404
    assert response.json()["detail"]


def test_analytics_benchmark_with_no_bars_in_window_is_handled(
    client: TestClient,
) -> None:
    """A benchmark with no bars in the window must not crash the endpoint."""
    response = client.get(
        "/api/v1/v2/analytics",
        params={
            "timeframe": "custom",
            "custom_start": "2024-01-02",
            "custom_end": "2024-01-05",
        },
    )
    # Either a handled 200 with warnings or a handled 422; never a stack trace.
    assert response.status_code in (200, 422)
    body = response.json()
    if response.status_code == 200:
        assert "warnings" in body
    else:
        assert "detail" in body


def test_v2_read_endpoints_emit_edge_cache_control_headers(client: TestClient) -> None:
    """Precomputed read-only V2 endpoints emit public s-maxage headers for Vercel Edge."""
    for path in (
        "/api/v1/v2/sectors",
        "/api/v1/v2/universe",
        "/api/v1/v2/analytics?benchmark=VNINDEX&timeframe=1Y",
        "/api/v1/v2/coverage",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc and "s-maxage=" in cc, (path, cc)


def test_freshness_and_options_emit_cache_control_headers(client: TestClient) -> None:
    """Freshness and options/symbols endpoints emit public s-maxage headers."""
    resp = client.get("/api/v1/data/freshness")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "public" in cc and "s-maxage=300" in cc

    for path in (
        "/api/v1/symbols",
        "/api/v1/optimize/options",
        "/api/v1/risk/options",
        "/api/v1/rebalance/options",
        "/api/v1/universe/options",
    ):
        opt_resp = client.get(path)
        assert opt_resp.status_code == 200, path
        opt_cc = opt_resp.headers.get("cache-control", "")
        assert "public" in opt_cc and "max-age=3600" in opt_cc and "s-maxage=43200" in opt_cc, (
            path,
            opt_cc,
        )

