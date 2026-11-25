"""Tests for the optimize endpoints (options and the run itself).

The pipeline runs against a temporary SQLite database seeded with smooth price
series (no network): an empty recorded-fixture HTTP client makes any accidental
provider call fail.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all, session_scope
from data.db.repositories import SqlSymbolRepository
from data.models import SymbolInfo
from data.offline import StaticHttpClient
from data.settings import get_settings
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

TODAY = date(2024, 1, 8)
START = date(2023, 1, 2)
END = START + timedelta(days=259)


def _v2_bars(
    start: date, count: int, *, base: float, phase: float
) -> list[AdjustedOHLCV]:
    """A smooth, strictly positive V2 price path (so returns are non-degenerate)."""
    rows: list[AdjustedOHLCV] = []
    for offset in range(count):
        close = base * (1.0 + 0.05 * math.sin((offset + phase) / 5.0))
        rows.append(
            AdjustedOHLCV(
                date=start + timedelta(days=offset),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                close_raw=close,
                volume=100_000,
                value=2_000_000_000.0,
                source="test",
            )
        )
    return rows


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'optimize.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs")
    get_settings.cache_clear()
    context = DataContext(
        get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY
    )
    create_all(context.engine)
    data_pkg.set_context(context)
    with session_scope(context.session_factory) as session:
        symbols = SqlSymbolRepository(session)
        store = V2Store(session)
        for code, base, phase in (
            ("AAA", 50_000.0, 0.0),
            ("BBB", 30_000.0, 2.0),
            ("CCC", 70_000.0, 4.0),
        ):
            symbols.upsert(
                SymbolInfo(code=code, exchange="HOSE", type="stock", source="test")
            )
            store.upsert_prices(
                code,
                _v2_bars(START, 260, base=base, phase=phase),
                price_adjustment_basis="ssi_adjusted",
                data_as_of=TODAY,
            )
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "symbols": ["AAA", "BBB"],
        "start": START.isoformat(),
        "end": END.isoformat(),
        "capital": 100_000_000,
        "constraints": [{"id": "max_weight", "params": {"max_weight": 0.6}}],
    }
    body.update(overrides)
    return body


def test_options_publish_concepts_and_defaults(client: TestClient) -> None:
    response = client.get("/api/v1/optimize/options")
    assert response.status_code == 200
    body = response.json()

    assert {"min_variance", "max_sharpe", "equal_weight", "inverse_volatility"} <= {
        item["id"] for item in body["objectives"]
    }
    assert "return_estimators" not in body
    assert "covariance_estimators" not in body
    assert {"max_weight", "cash_reserve"} <= {
        item["id"] for item in body["constraints"]
    }
    assert body["defaults"]["objective"] == "min_variance"
    assert body["defaults"]["max_weight"] == pytest.approx(0.25)
    max_weight = next(item for item in body["constraints"] if item["id"] == "max_weight")
    assert max_weight["parameter_schema"]["properties"]["max_weight"]["default"] == 0.25


def test_optimize_returns_a_full_result(client: TestClient) -> None:
    response = client.post("/api/v1/optimize", json=_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body["symbols"]) == {"AAA", "BBB"}
    assert sum(body["weights"].values()) == pytest.approx(1.0, abs=1e-6)
    assert all(isinstance(value, int) for value in body["lots"].values())
    assert all(value % 100 == 0 for value in body["shares"].values())
    assert body["residual_cash"] >= 0
    assert isinstance(body["binding_constraints"], list)
    assert isinstance(body["volatility"], float)

    assumptions = body["assumptions"]
    assert assumptions["objective"] == "min_variance"
    assert assumptions["covariance_estimator"]["id"] == "sample"
    assert assumptions["capital"] == 100_000_000
    assert assumptions["prices_adjusted"] is False
    assert assumptions["risk_free_rate"] == pytest.approx(0.03)
    assert "test" in assumptions["data_sources"]


def test_optimize_uses_the_provided_risk_free_rate(client: TestClient) -> None:
    response = client.post(
        "/api/v1/optimize",
        json=_payload(settings={"brokerage_fee_rate": 0.0015, "risk_free_rate": 0.07}),
    )
    assert response.status_code == 200, response.text
    assert response.json()["assumptions"]["risk_free_rate"] == pytest.approx(0.07)


def test_optimize_applies_cash_reserve(client: TestClient) -> None:
    response = client.post(
        "/api/v1/optimize",
        json=_payload(
            constraints=[
                {"id": "max_weight", "params": {"max_weight": 0.6}},
                {"id": "cash_reserve", "params": {"reserve": 0.2}},
            ]
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cash_reserve"] == pytest.approx(0.2)
    assert body["cash_reserve_value"] == 20_000_000
    assert body["assumptions"]["investable_capital"] == 80_000_000


def test_unknown_objective_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/optimize", json=_payload(objective="does-not-exist"))
    assert response.status_code == 422


def test_infeasible_constraints_are_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/optimize",
        json=_payload(constraints=[{"id": "max_weight", "params": {"max_weight": 0.01}}]),
    )
    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "satisfy" in detail or "constraint" in detail or "violated" in detail


def test_missing_symbols_are_422(client: TestClient) -> None:
    response = client.post("/api/v1/optimize", json=_payload(symbols=["ZZZ"]))
    assert response.status_code == 422




def test_more_than_thirty_symbols_is_422(client: TestClient) -> None:
    symbols = [f"S{index:02d}" for index in range(31)]
    response = client.post("/api/v1/optimize", json=_payload(symbols=symbols))
    assert response.status_code == 422
    assert "at most" in response.json()["detail"].lower()


def _frontier_payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "symbols": ["AAA", "BBB", "CCC"],
        "start": START.isoformat(),
        "end": END.isoformat(),
        "capital": 300_000_000,
        "max_weight": 0.6,
        "num_portfolios": 200,
        "seed": 7,
    }
    body.update(overrides)
    return body


def test_options_publish_frontier_defaults(client: TestClient) -> None:
    response = client.get("/api/v1/optimize/options")
    assert response.status_code == 200
    defaults = response.json()["frontier_defaults"]
    assert defaults["portfolios"] == 5000
    assert defaults["max_portfolios"] == 100_000
    assert defaults["cloud_points"] == 6_000
    assert defaults["frontier_points"] == 40


def test_frontier_returns_cloud_frontier_and_points(client: TestClient) -> None:
    response = client.post("/api/v1/optimize/frontier", json=_frontier_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body["symbols"]) == {"AAA", "BBB", "CCC"}
    assert len(body["random_cloud"]) == 200
    assert len(body["frontier"]) >= 2
    for point in (body["min_variance"], body["tangency"], body["equal_weight"]):
        assert sum(point["weights"].values()) == pytest.approx(1.0, abs=1e-6)
        assert point["residual_cash"] >= 0
        assert all(isinstance(value, int) for value in point["lots"].values())
        assert all(value % 100 == 0 for value in point["shares"].values())

    assumptions = body["assumptions"]
    assert assumptions["seed"] == 7
    assert assumptions["portfolios_requested"] == 200
    assert assumptions["portfolios_generated"] == 200
    assert assumptions["return_estimator"] == "historical_mean"
    assert assumptions["covariance_estimator"] == "sample"
    assert assumptions["prices_adjusted"] is False
    assert assumptions["risk_free_rate"] == pytest.approx(0.03)
    assert "test" in assumptions["data_sources"]
    assert any("in-sample" in warning.lower() for warning in body["warnings"])



def test_frontier_is_reproducible_with_the_same_seed(client: TestClient) -> None:
    first = client.post("/api/v1/optimize/frontier", json=_frontier_payload()).json()
    second = client.post("/api/v1/optimize/frontier", json=_frontier_payload()).json()

    assert first["random_cloud"] == second["random_cloud"]
    assert first["tangency"]["expected_return"] == pytest.approx(
        second["tangency"]["expected_return"], abs=1e-12
    )


def test_frontier_plots_a_stratified_sample_of_the_cloud(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The simulation runs every portfolio; the response carries a bounded sample.

    ``VNOPT_FRONTIER_CLOUD_POINTS`` caps the plotted scatter, so a 100,000-portfolio
    run keeps its statistics without inflating the payload. The sample must be a
    subset of the simulated cloud (same seed), and the marked portfolios, which are
    computed separately from the frontier, are never dropped.
    """
    monkeypatch.setenv("VNOPT_FRONTIER_CLOUD_POINTS", "150")
    sampled = client.post(
        "/api/v1/optimize/frontier", json=_frontier_payload(num_portfolios=800)
    )
    assert sampled.status_code == 200, sampled.text
    body = sampled.json()

    assumptions = body["assumptions"]
    assert assumptions["portfolios_generated"] == 800
    assert assumptions["portfolios_requested"] == 800
    assert assumptions["portfolios_plotted"] == len(body["random_cloud"]) == 150
    for key in ("min_variance", "tangency", "equal_weight"):
        assert body[key]["weights"]

    monkeypatch.setenv("VNOPT_FRONTIER_CLOUD_POINTS", "10000")
    full = client.post(
        "/api/v1/optimize/frontier", json=_frontier_payload(num_portfolios=800)
    ).json()
    assert len(full["random_cloud"]) == 800
    simulated = {
        (point["expected_return"], point["volatility"])
        for point in full["random_cloud"]
    }
    assert all(
        (point["expected_return"], point["volatility"]) in simulated
        for point in body["random_cloud"]
    )


def test_frontier_infeasible_cap_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/optimize/frontier", json=_frontier_payload(max_weight=0.1))
    assert response.status_code == 422
    assert "cannot reach" in response.json()["detail"].lower()


def test_frontier_empty_symbols_is_422(client: TestClient) -> None:
    response = client.post("/api/v1/optimize/frontier", json=_frontier_payload(symbols=[]))
    assert response.status_code == 422


def test_frontier_start_after_end_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/optimize/frontier",
        json=_frontier_payload(start=END.isoformat(), end=START.isoformat()),
    )
    assert response.status_code == 422


def test_frontier_over_the_portfolio_cap_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/optimize/frontier", json=_frontier_payload(num_portfolios=100_001)
    )
    assert response.status_code == 422
    assert "at most" in response.json()["detail"].lower()

