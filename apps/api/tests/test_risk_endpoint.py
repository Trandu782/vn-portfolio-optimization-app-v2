"""Tests for the risk endpoints (options, analysis and Sharpe).

A temporary SQLite database is seeded with smooth symbol and index price series
(no network): an empty recorded-fixture HTTP client makes any provider call fail.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import app, create_app
from core.settings import UserSettings
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

TODAY = date(2024, 1, 8)
START = date(2023, 1, 2)
END = START + timedelta(days=259)

_REGISTERED_METRICS = {
    "annualized_volatility",
    "max_drawdown",
    "beta",
    "historical_var",
    "correlation_matrix",
    "sharpe",
    "treynor",
    "jensens_alpha",
}


def _price_series(
    start: date, count: int, *, base: float, phase: float
) -> list[PriceBar]:
    """A smooth, strictly positive price path (so returns are non-degenerate)."""
    rows: list[PriceBar] = []
    for offset in range(count):
        close = base * (1.0 + 0.05 * math.sin((offset + phase) / 5.0))
        rows.append(
            PriceBar(
                date=start + timedelta(days=offset),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                adj_close=close,
                volume=100_000,
                value=2_000_000_000.0,
                source="test",
            )
        )
    return rows


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'risk.db'}")
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
        for code, base, phase in (
            ("AAA", 50_000.0, 0.0),
            ("BBB", 30_000.0, 2.0),
            ("CCC", 70_000.0, 4.0),
        ):
            symbols.upsert(
                SymbolInfo(code=code, exchange="HOSE", type="stock", source="test")
            )
            prices.upsert_many(code, _price_series(START, 260, base=base, phase=phase))
        indices.upsert_many(
            "VNINDEX", _price_series(START, 260, base=1_200.0, phase=1.0)
        )
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


LONG_START = date(2020, 1, 1)


@pytest.fixture
def long_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A client whose database holds ~4 years of bars for AAA/BBB + VNINDEX.

    Seeded so both a 6-month and a multi-year window are fully covered, letting a
    test prove the endpoint uses the requested window instead of a fixed lookback.
    """
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'risk_long.db'}")
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
        for code, base, phase in (("AAA", 50_000.0, 0.0), ("BBB", 30_000.0, 2.0)):
            symbols.upsert(
                SymbolInfo(code=code, exchange="HOSE", type="stock", source="test")
            )
            prices.upsert_many(
                code, _price_series(LONG_START, 1500, base=base, phase=phase)
            )
        indices.upsert_many(
            "VNINDEX", _price_series(LONG_START, 1500, base=1_200.0, phase=1.0)
        )
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "weights": {"AAA": 0.6, "BBB": 0.4},
        "symbols": ["AAA", "BBB", "CCC"],
        "start": START.isoformat(),
        "end": END.isoformat(),
        "benchmark": "VNINDEX",
    }
    body.update(overrides)
    return body


def test_options_publish_metrics_benchmarks_and_defaults(client: TestClient) -> None:
    response = client.get("/api/v1/risk/options")
    assert response.status_code == 200
    body = response.json()

    assert {item["id"] for item in body["metrics"]} >= _REGISTERED_METRICS
    assert {item["code"] for item in body["benchmarks"]} >= {
        "VNINDEX",
        "VN30",
        "HNXINDEX",
        "UPCOMINDEX",
    }
    assert body["defaults"]["benchmark"] == "VNINDEX"
    assert body["defaults"]["confidence"] == pytest.approx(0.95)

    var_option = next(item for item in body["metrics"] if item["id"] == "historical_var")
    assert (
        var_option["parameter_schema"]["properties"]["confidence"]["default"]
        == pytest.approx(0.95)
    )


def test_risk_returns_every_selected_metric(client: TestClient) -> None:
    response = client.post("/api/v1/risk", json=_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body["symbols"]) == {"AAA", "BBB", "CCC"}
    assert body["benchmark"] == "VNINDEX"
    metrics = body["metrics"]
    assert set(metrics) == _REGISTERED_METRICS

    assert metrics["annualized_volatility"]["volatility"] >= 0.0
    assert math.isfinite(metrics["beta"]["beta"])
    matrix = metrics["correlation_matrix"]["matrix"]
    assert len(matrix) == 3
    assert all(len(row) == 3 for row in matrix)
    drawdown = metrics["max_drawdown"]
    assert len(drawdown["dates"]) == len(drawdown["drawdown"])
    assert {item["id"] for item in body["options"]} >= set(metrics)

    performance = body["performance"]
    assert len(performance["dates"]) == len(performance["growth"])
    assert performance["total_return"] == pytest.approx(performance["growth"][-1] / 100.0 - 1.0)
    assert body["assumptions"]["risk_free_rate"] == pytest.approx(
        UserSettings().risk_free_rate
    )


def test_risk_echoes_the_user_risk_free_rate(client: TestClient) -> None:
    response = client.post(
        "/api/v1/risk",
        json=_payload(settings={"risk_free_rate": 0.07}),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assumptions"]["risk_free_rate"] == pytest.approx(0.07)
    assert body["metrics"]["sharpe"]["risk_free_rate"] == pytest.approx(0.07)


# -- comparison ---------------------------------------------------------------


def test_compare_returns_current_optimized_equal_weight_and_benchmark(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/risk/compare",
        json={
            "symbols": ["AAA", "BBB", "CCC"],
            "start": START.isoformat(),
            "end": END.isoformat(),
            "benchmark": "VNINDEX",
            "current_weights": {"AAA": 0.6, "BBB": 0.4},
            "optimized_weights": {"AAA": 0.5, "CCC": 0.5},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body["symbols"]) == {"AAA", "BBB", "CCC"}
    assert body["benchmark"] == "VNINDEX"
    assert body["current"] is not None
    assert body["optimized"] is not None

    equal = body["equal_weight"]["weights"]
    assert equal == pytest.approx({"AAA": 1 / 3, "BBB": 1 / 3, "CCC": 1 / 3})

    benchmark = body["benchmark_portfolio"]
    assert benchmark["metrics"]["beta"]["beta"] == pytest.approx(1.0)
    assert benchmark["metrics"]["jensens_alpha"]["alpha"] == pytest.approx(0.0)
    assert len(benchmark["performance"]["growth"]) == len(
        benchmark["performance"]["dates"]
    )


def test_compare_without_portfolios_still_returns_equal_and_benchmark(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/risk/compare",
        json={
            "symbols": ["AAA", "BBB"],
            "start": START.isoformat(),
            "end": END.isoformat(),
            "benchmark": "VNINDEX",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current"] is None
    assert body["optimized"] is None
    assert body["equal_weight"] is not None
    assert body["benchmark_portfolio"] is not None


def test_compare_dates_span_the_requested_window(client: TestClient) -> None:
    """The response window is the requested one, not a hardcoded lookback.

    The fixture stores a full year of bars, so a request over START..END must
    return return-dates that begin the day after START and end on END.
    """
    response = client.post(
        "/api/v1/risk/compare",
        json={
            "symbols": ["AAA", "BBB"],
            "start": START.isoformat(),
            "end": END.isoformat(),
            "benchmark": "VNINDEX",
        },
    )
    assert response.status_code == 200, response.text
    dates = response.json()["dates"]
    assert dates[0] == (START + timedelta(days=1)).isoformat()
    assert dates[-1] == END.isoformat()


def _compare_window(client: TestClient, start: date, end: date) -> dict:
    response = client.post(
        "/api/v1/risk/compare",
        json={
            "symbols": ["AAA", "BBB"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "benchmark": "VNINDEX",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_compare_uses_the_selected_window_not_a_default(
    long_client: TestClient,
) -> None:
    """6M and 3Y must return different spans and different metric values."""
    end = date(2023, 11, 1)
    short = _compare_window(long_client, end - timedelta(days=182), end)
    long = _compare_window(long_client, end - timedelta(days=1095), end)

    assert len(long["dates"]) > len(short["dates"])
    assert long["dates"][0] < short["dates"][0]
    assert long["dates"][-1] == short["dates"][-1] == end.isoformat()

    short_return = short["equal_weight"]["performance"]["total_return"]
    long_return = long["equal_weight"]["performance"]["total_return"]
    assert long_return != pytest.approx(short_return)


def test_compare_unknown_benchmark_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/risk/compare",
        json={
            "symbols": ["AAA", "BBB"],
            "start": START.isoformat(),
            "end": END.isoformat(),
            "benchmark": "NOTREAL",
        },
    )
    assert response.status_code == 422


def test_risk_honours_confidence_and_selected_metrics(client: TestClient) -> None:
    response = client.post(
        "/api/v1/risk",
        json=_payload(
            metrics=["historical_var"],
            metric_params={"historical_var": {"confidence": 0.99}},
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["metrics"]) == {"historical_var"}
    assert body["metrics"]["historical_var"]["confidence"] == pytest.approx(0.99)


def test_weights_outside_the_universe_are_ignored_with_a_warning(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/risk",
        json=_payload(weights={"AAA": 0.5, "BBB": 0.5, "ZZZ": 0.2}),
    )
    assert response.status_code == 200, response.text
    assert any("ZZZ" in warning for warning in response.json()["warnings"])


def test_unknown_metric_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/risk", json=_payload(metrics=["does-not-exist"]))
    assert response.status_code == 422


def test_unknown_benchmark_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/risk", json=_payload(benchmark="NOTREAL"))
    assert response.status_code == 422


def test_empty_symbols_are_422(client: TestClient) -> None:
    response = client.post("/api/v1/risk", json=_payload(symbols=[]))
    assert response.status_code == 422


# -- Sharpe ratio (existing endpoint) -----------------------------------------


def test_sharpe_applies_default_settings_when_missing() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/risk/sharpe",
        json={"mean_return": 0.12, "volatility": 0.20},
    )

    assert response.status_code == 200
    payload = response.json()
    defaults = UserSettings()
    assert payload["assumptions"]["risk_free_rate"] == pytest.approx(
        defaults.risk_free_rate
    )
    assert payload["assumptions"]["brokerage_fee_rate"] == pytest.approx(
        float(defaults.brokerage_fee_rate)
    )
    expected = (0.12 - defaults.risk_free_rate) / 0.20
    assert payload["sharpe"] == pytest.approx(expected)


def test_sharpe_echoes_provided_settings() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/risk/sharpe",
        json={
            "mean_return": 0.12,
            "volatility": 0.20,
            "settings": {"brokerage_fee_rate": 0.002, "risk_free_rate": 0.05},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assumptions"]["risk_free_rate"] == pytest.approx(0.05)
    assert payload["assumptions"]["brokerage_fee_rate"] == pytest.approx(0.002)


def test_higher_risk_free_rate_lowers_sharpe() -> None:
    client = TestClient(app)
    base = {"mean_return": 0.12, "volatility": 0.20}
    low = client.post(
        "/api/v1/risk/sharpe",
        json={**base, "settings": {"risk_free_rate": 0.03}},
    ).json()
    high = client.post(
        "/api/v1/risk/sharpe",
        json={**base, "settings": {"risk_free_rate": 0.06}},
    ).json()
    assert high["sharpe"] < low["sharpe"]
