"""Ticker search must keep working when every live provider is unreachable.

Reproduces the "symbols returns HTTP 500" report: the API used to point the
default SQLite URL at an unmigrated file (relative to ``apps/api``), and the
route had no regression test. Here a temporary, migrated database is combined
with an HTTP client that fails every request, so the route has to fall back to
the built-in symbol snapshot instead of raising.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

import data as data_pkg
from app.main import create_app
from data.context import DataContext
from data.db.base import create_all
from data.offline import StaticHttpClient
from data.seed import SEED_SOURCE, seed_symbols
from data.settings import get_settings

TODAY = date(2024, 1, 8)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VNOPT_DATABASE_URL", f"sqlite:///{tmp_path / 'symbols.db'}")
    monkeypatch.setenv("VNOPT_PROVIDER_ORDER", "kbs,vci,dnse,tcbs,ssi_iboard")
    monkeypatch.setenv("VNOPT_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("VNOPT_RETRY_BACKOFF_SECONDS", "0")
    get_settings.cache_clear()
    context = DataContext(get_settings(), http=StaticHttpClient({}), today_provider=lambda: TODAY)
    create_all(context.engine)
    data_pkg.set_context(context)
    with TestClient(create_app()) as test_client:
        yield test_client
    data_pkg.set_context(None)
    get_settings.cache_clear()


def test_symbols_fall_back_to_the_builtin_seed(client: TestClient) -> None:
    response = client.get("/api/v1/symbols")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(seed_symbols())
    assert {item["source"] for item in body["symbols"]} == {SEED_SOURCE}


def test_symbols_exchange_filter_uses_the_seed(client: TestClient) -> None:
    response = client.get("/api/v1/symbols", params={"exchange": "HOSE"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] > 0
    assert {item["exchange"] for item in body["symbols"]} == {"HOSE"}
