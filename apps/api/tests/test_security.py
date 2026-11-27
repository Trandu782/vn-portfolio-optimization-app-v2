"""Security hardening tests for validation, auth, rate limiting, headers, cache, and bounds."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import create_app
from app.security import MAX_REQUEST_BODY_BYTES
from data.context import DataContext
from data.db.base import create_all, create_engine_for, session_scope
from data.db.repositories import SqlSymbolRepository, SqlSyncLogRepository
from data.errors import AllProvidersFailedError, EmptyResultError
from data.fallback import FallbackProvider
from data.http import HttpResponse, HttpxHttpClient
from data.models import PriceBar, SymbolInfo
from data.offline import StaticHttpClient
from data.providers.base import ProviderBase
from data.providers.kbs import KbsProvider
from data.settings import DataSettings, get_settings
from data.v2.analytics.cache import cache_size, cached_build, clear_analytics_cache
from data.v2.analytics.schemas import AnalyticsPayload, Window
from data.v2.analytics.service import AnalyticsRequest, _request_key
from data.v2.config import V2DataSettings
from data.v2.providers.kbs import KbsAdapter

TODAY = date(2024, 1, 8)
STRONG_TOKEN = "a" * 32


@pytest.fixture
def sec_client(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, DataContext]]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'security.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    monkeypatch.setenv("VNOPT_REFRESH_TOKEN", STRONG_TOKEN)
    monkeypatch.setenv("VNOPT_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    context = DataContext(
        get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY
    )
    create_all(context.engine)
    with session_scope(context.session_factory) as session:
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="VNM", exchange="HOSE", type="stock", source="test")
        )
    data_pkg.set_context(context)
    with TestClient(create_app()) as test_client:
        yield test_client, context
    data_pkg.set_context(None)
    get_settings.cache_clear()


def test_backfill_requires_auth_and_enforces_bounds(
    sec_client: tuple[TestClient, DataContext],
) -> None:
    client, _ = sec_client
    assert client.post("/api/v1/data/backfill", json={"symbols": ["VNM"]}).status_code == 401

    ok = client.post(
        "/api/v1/data/backfill",
        headers={"Authorization": f"Bearer {STRONG_TOKEN}"},
        json={"symbols": ["VNM"], "history_days": 30},
    )
    assert ok.status_code == 200
    assert ok.headers.get("cache-control") == "no-store"

    too_many = client.post(
        "/api/v1/data/backfill",
        headers={"Authorization": f"Bearer {STRONG_TOKEN}"},
        json={"symbols": [f"S{i:02d}" for i in range(26)]},
    )
    assert too_many.status_code == 422

    bad_days = client.post(
        "/api/v1/data/backfill",
        headers={"Authorization": f"Bearer {STRONG_TOKEN}"},
        json={"symbols": ["VNM"], "history_days": 3651},
    )
    assert bad_days.status_code == 422


@pytest.mark.parametrize(
    "bad_symbol",
    ["..", "../etc", "VCB?x=1", "VCB/foo", "VCB\\foo", "VCB@1", "A" * 17, "V CB"],
)
def test_malformed_symbols_return_422_everywhere(
    sec_client: tuple[TestClient, DataContext], bad_symbol: str
) -> None:
    client, _ = sec_client

    eval_resp = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": bad_symbol, "shares": 10}], "cash": 0},
    )
    assert eval_resp.status_code == 422

    opt_resp = client.post(
        "/api/v1/optimize",
        json={
            "symbols": [bad_symbol],
            "start": "2023-01-01",
            "end": "2024-01-01",
            "capital": 100_000_000,
        },
    )
    assert opt_resp.status_code == 422

    # URL-safe variants for unencoded path routes ('.' / '..' are normalized by HTTP clients)
    if (
        bad_symbol != ".."
        and "/" not in bad_symbol
        and "\\" not in bad_symbol
        and "?" not in bad_symbol
    ):
        assert client.get(f"/api/v1/prices/{bad_symbol}").status_code == 422
        assert client.get(f"/api/v1/v2/ticker/{bad_symbol}").status_code == 422
        assert client.get(f"/api/v1/v2/fundamentals/{bad_symbol}").status_code == 422


def test_path_encoded_slash_and_traversal_rejected_with_422(
    sec_client: tuple[TestClient, DataContext],
) -> None:
    client, _ = sec_client
    for encoded in ("%2E%2E", "VCB%3Fx%3D1", "VCB%23frag", "VCB%40host", "AAAAAAAAAAAAAAAAA"):
        assert client.get(f"/api/v1/prices/{encoded}").status_code == 422
        assert client.get(f"/api/v1/data/quality/{encoded}").status_code == 422
        assert client.get(f"/api/v1/v2/ticker/{encoded}").status_code == 422
        assert client.get(f"/api/v1/v2/fundamentals/{encoded}").status_code == 422


def test_unknown_symbol_read_does_not_pollute_symbols_or_sync_log(
    sec_client: tuple[TestClient, DataContext],
) -> None:
    client, context = sec_client

    price_resp = client.get("/api/v1/prices/NOTREAL")
    assert price_resp.status_code == 200
    assert price_resp.json()["rows"] == []

    eval_resp = client.post(
        "/api/v1/portfolio/evaluate",
        json={"holdings": [{"symbol": "ALSOBAD", "shares": 10}], "cash": 0},
    )
    assert eval_resp.status_code == 200

    with session_scope(context.session_factory) as session:
        symbols = SqlSymbolRepository(session)
        logs = SqlSyncLogRepository(session)
        assert symbols.get("NOTREAL") is None
        assert symbols.get("ALSOBAD") is None
        assert symbols.get("VNM") is not None
        assert logs.recent(10) == []


def test_dates_before_2000_return_422(sec_client: tuple[TestClient, DataContext]) -> None:
    client, _ = sec_client
    assert (
        client.get("/api/v1/prices/VNM", params={"start": "1999-12-31"}).status_code
        == 422
    )
    assert (
        client.get("/api/v1/v2/ticker/VNM", params={"start": "1999-01-01"}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/v2/analytics",
            params={
                "timeframe": "custom",
                "custom_start": "1999-01-01",
                "custom_end": "2024-01-01",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/optimize",
            json={
                "symbols": ["VNM"],
                "start": "1999-01-01",
                "end": "2024-01-01",
                "capital": 10_000_000,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/pnl/evaluate",
            json={
                "holdings": [
                    {
                        "symbol": "VNM",
                        "shares": 10,
                        "avg_cost": 50_000,
                        "buy_date": "1999-12-31",
                    }
                ],
                "cash": 0,
            },
        ).status_code
        == 422
    )


def test_analytics_cache_bounded_lru_and_canonical_keys() -> None:
    clear_analytics_cache()

    def _dummy_payload(as_of: date) -> AnalyticsPayload:
        return AnalyticsPayload(
            data_as_of=as_of,
            generated_at=datetime.now(UTC),
            grouping="sector",
            weighting="market_cap",
            benchmark="VNINDEX",
            window=Window(label="1Y", start=as_of - timedelta(days=30), end=as_of),
            liquidity_preset="standard_retail",
        )

    day1 = date(2024, 1, 2)
    for idx in range(10):
        req = AnalyticsRequest(
            single_stock_cap=0.1 + idx * 0.01,
            sectors=["Technology", "Banks", "Banks"],
            indexes=["VN100", "VN30"],
        )
        cached_build(
            _request_key(req, "VNINDEX"),
            day1,
            lambda d=day1: _dummy_payload(d),
            maxsize=4,
        )
    assert cache_size() == 4

    # Advancing data_as_of evicts stale snapshot entries.
    day2 = date(2024, 1, 3)
    req_a = AnalyticsRequest(
        single_stock_cap=0.25000001,
        sectors=["Banks", "Technology"],
        indexes=["VN30", "VN100"],
    )
    req_b = AnalyticsRequest(
        single_stock_cap=0.25000002,
        sectors=["Technology", "Banks", "Technology"],
        indexes=["VN100", "VN30"],
    )
    assert _request_key(req_a, "VNINDEX") == _request_key(req_b, "VNINDEX")
    _, hit1, _ = cached_build(
        _request_key(req_a, "VNINDEX"), day2, lambda: _dummy_payload(day2), maxsize=4
    )
    _, hit2, _ = cached_build(
        _request_key(req_b, "VNINDEX"), day2, lambda: _dummy_payload(day2), maxsize=4
    )
    assert hit1 is False
    assert hit2 is True
    assert cache_size() == 1
    clear_analytics_cache()


def test_production_mode_hardens_docs_cors_and_refresh_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VNOPT_ENVIRONMENT", "production")
    monkeypatch.setenv("VNOPT_CORS_ORIGINS", "*")
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'prod.db'}")
    monkeypatch.setenv("VNOPT_REFRESH_TOKEN", "change-me")
    get_settings.cache_clear()

    context = DataContext(
        get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY
    )
    create_all(context.engine)
    data_pkg.set_context(context)
    try:
        with TestClient(create_app()) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/redoc").status_code == 404
            assert client.get("/openapi.json").status_code == 404

            health = client.get(
                "/api/v1/health", headers={"Origin": "https://evil.example"}
            )
            assert health.status_code == 200
            assert "access-control-allow-origin" not in health.headers
            assert health.headers.get("x-content-type-options") == "nosniff"
            assert health.headers.get("x-frame-options") == "DENY"
            assert health.headers.get("referrer-policy") == "no-referrer"

            # Placeholder or short tokens are rejected with 503 in production.
            weak = client.post(
                "/api/v1/data/backfill",
                headers={"Authorization": "Bearer change-me"},
                json={"symbols": ["VNM"]},
            )
            assert weak.status_code == 503
            assert "VNOPT_REFRESH_TOKEN" not in weak.text

            monkeypatch.setenv("VNOPT_REFRESH_TOKEN", "short-token")
            get_settings.cache_clear()
            short = client.post(
                "/api/v1/data/backfill",
                headers={"Authorization": "Bearer short-token"},
                json={"symbols": ["VNM"]},
            )
            assert short.status_code == 503
    finally:
        data_pkg.set_context(None)
        get_settings.cache_clear()


def test_body_size_limit_and_rate_limiter_and_security_headers(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'limits.db'}")
    monkeypatch.setenv("VNOPT_REFRESH_TOKEN", STRONG_TOKEN)
    monkeypatch.setenv("VNOPT_RATE_LIMIT_ENABLED", "true")
    get_settings.cache_clear()

    context = DataContext(
        get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY
    )
    create_all(context.engine)
    data_pkg.set_context(context)
    try:
        with TestClient(create_app()) as client:
            oversized = json.dumps({"holdings": [], "pad": "x" * (MAX_REQUEST_BODY_BYTES + 100)})
            too_big = client.post(
                "/api/v1/portfolio/evaluate",
                content=oversized,
                headers={"Content-Type": "application/json"},
            )
            assert too_big.status_code == 413
            assert too_big.headers.get("x-content-type-options") == "nosniff"
            assert too_big.headers.get("cache-control") == "no-store"

            # Auth tier allows 10 req/min; 11th request returns 429 with Retry-After.
            for _ in range(10):
                resp = client.post(
                    "/api/v1/data/backfill",
                    headers={"Authorization": f"Bearer {STRONG_TOKEN}"},
                    json={"symbols": []},
                )
                assert resp.status_code == 200
            throttled = client.post(
                "/api/v1/data/backfill",
                headers={"Authorization": f"Bearer {STRONG_TOKEN}"},
                json={"symbols": []},
            )
            assert throttled.status_code == 429
            assert int(throttled.headers["retry-after"]) >= 1
    finally:
        data_pkg.set_context(None)
        get_settings.cache_clear()


def test_nan_floats_rejected_with_422(sec_client: tuple[TestClient, DataContext]) -> None:
    client, _ = sec_client
    bad_sharpe = client.post(
        "/api/v1/risk/sharpe",
        content='{"mean_return": NaN, "volatility": 0.2}',
        headers={"Content-Type": "application/json"},
    )
    assert bad_sharpe.status_code == 422


def test_provider_url_encoding_chunks_redirects_and_error_hygiene() -> None:
    # 1. KBS V1/V2 URL-encode path segments
    class _SpyHttp(StaticHttpClient):
        def get(self, url: str, *, params=None, headers=None):  # type: ignore[override]
            self.calls.append(url)
            return super().get(url, params=params, headers=headers)

    spy_v1 = _SpyHttp({"/data_day": HttpResponse(200, '{"data_day": []}', "u")})
    kbs_v1 = KbsProvider(spy_v1, DataSettings(database_url="sqlite://"))
    with pytest.raises(EmptyResultError):
        kbs_v1.get_daily_prices("A/B", date(2024, 1, 1), date(2024, 1, 2))
    assert "/stocks/A%2FB/data_day" in spy_v1.calls[-1]

    spy_v2 = _SpyHttp({"/data_day": HttpResponse(200, '{"data_day": []}', "u")})
    kbs_v2 = KbsAdapter(spy_v2, V2DataSettings())
    with pytest.raises(EmptyResultError):
        kbs_v2.get_ohlcv("A/B", date(2024, 1, 1), date(2024, 1, 2))
    assert "/stocks/A%2FB/data_day" in spy_v2.calls[-1]

    # 2. HttpxHttpClient does not follow redirects
    with HttpxHttpClient(user_agent="test") as http_client:
        assert http_client._client.follow_redirects is False

    # 3. _chunks rejects > MAX_CHUNKS
    with pytest.raises(ValueError, match=r"MAX_CHUNKS|chunks"):
        ProviderBase._chunks(date(2000, 1, 1), date(2035, 1, 1), days=365)

    # 4. FallbackProvider sanitizes unexpected/internal error text in statuses()
    class _BoomProvider:
        id = "boom"
        display_name = "Boom"
        returns_adjusted_prices = False
        supports_indexes = True
        unofficial = True

        def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
            raise RuntimeError("secret internal https://internal.host/token=abc")

        def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
            raise RuntimeError("boom")

        def list_symbols(self, exchange: str):
            return []

        def get_index_constituents(self, index_code: str):
            return []

    chain = FallbackProvider(
        [_BoomProvider()],  # type: ignore[list-item]
        settings=DataSettings(database_url="sqlite://", provider_order="boom", retry_attempts=1),
        order=["boom"],
    )
    with pytest.raises(AllProvidersFailedError):
        chain.get_daily_prices("VNM", date(2024, 1, 1), date(2024, 1, 2))
    [status] = chain.statuses()
    assert status.last_error is not None
    assert "internal.host" not in status.last_error
    assert "unexpected" not in status.last_error


def test_verify_v2_db_redacts_remote_url_completely() -> None:
    scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from verify_v2_db import _redacted_database_url  # type: ignore[import-not-found]

    engine = create_engine_for(
        "postgresql+psycopg://postgres.projref123:supersecret@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"
    )
    try:
        redacted = _redacted_database_url(engine)
        assert redacted == "postgresql+psycopg://***"
        assert "projref123" not in redacted
        assert "supersecret" not in redacted
        assert "supabase.com" not in redacted
    finally:
        engine.dispose()
