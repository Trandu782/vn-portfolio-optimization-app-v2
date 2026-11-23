"""Built-in reference seed and its last-resort fallback wiring."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker
from support import FakeProvider, make_bar

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.repositories import (
    SqlConstituentRepository,
    SqlIndexRepository,
    SqlSymbolRepository,
)
from data.errors import NetworkError
from data.fallback import FallbackProvider
from data.models import SymbolInfo
from data.seed import SEED_SOURCE, seed_constituents, seed_symbols
from data.service import DataService
from data.settings import DataSettings
from data.sync import SyncService

TODAY = date(2024, 1, 8)


def _settings() -> DataSettings:
    return DataSettings(
        database_url="sqlite://",
        provider_order="a",
        retry_attempts=1,
        circuit_breaker_failures=5,
    )


def _clock() -> datetime:
    return datetime(2024, 1, 8, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_for(f"sqlite:///{tmp_path / 'seed.db'}")
    create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _chain(
    factory: sessionmaker[Session], providers: list[FakeProvider]
) -> tuple[FallbackProvider, SyncService]:
    settings = _settings()
    fallback = FallbackProvider(
        providers,
        settings=settings,
        order=[provider.id for provider in providers],
        clock=_clock,
        sleeper=lambda _seconds: None,
        today_provider=lambda: TODAY,
    )
    sync = SyncService(
        session_factory=factory,
        fallback=fallback,
        settings=settings,
        today_provider=lambda: TODAY,
    )
    return fallback, sync


def _failing_provider() -> FakeProvider:
    return FakeProvider("a", error=NetworkError("down", provider="a"), always_fail=True)


def test_seed_snapshot_is_unique_and_covers_vn30() -> None:
    all_symbols = seed_symbols()
    codes = [info.code for info in all_symbols]
    assert len(codes) == len(set(codes))
    assert {info.exchange for info in all_symbols} == {"HOSE", "HNX", "UPCOM"}
    assert all(info.source == SEED_SOURCE for info in all_symbols)
    assert seed_symbols("upcom") == seed_symbols("UPCOM")
    assert 0 < len(seed_symbols("UPCOM")) < len(all_symbols)

    vn30 = seed_constituents("VN30")
    assert len(vn30) == 30
    assert set(vn30) <= set(codes)
    assert seed_constituents("VNINDEX") == []


def test_sync_reference_data_falls_back_to_seed(factory: sessionmaker[Session]) -> None:
    _fallback, sync = _chain(factory, [_failing_provider()])
    result = sync.sync_reference_data()

    assert result.used_seed is True
    assert result.symbol_source == SEED_SOURCE
    assert result.symbols == len(seed_symbols())
    assert result.constituents == {"VN30": 30}
    assert result.constituent_sources["VN30"] == SEED_SOURCE

    with session_scope(factory) as session:
        stored = SqlSymbolRepository(session).list()
        assert len(stored) == len(seed_symbols())
        assert {info.source for info in stored} == {SEED_SOURCE}
        assert SqlConstituentRepository(session).get("VN30") == sorted(
            seed_constituents("VN30")
        )


def test_sync_reference_data_prefers_live_provider(factory: sessionmaker[Session]) -> None:
    provider = FakeProvider("a")
    provider.constituents = ["VNM", "FPT"]
    _fallback, sync = _chain(factory, [provider])
    result = sync.sync_reference_data()

    assert result.used_seed is False
    assert result.symbol_source == "a"
    assert result.symbols == 1
    assert result.constituents == {
        "VNINDEX": 2,
        "VN30": 2,
        "HNXINDEX": 2,
        "UPCOMINDEX": 2,
    }

    with session_scope(factory) as session:
        stored = SqlSymbolRepository(session).list()
        assert [info.code for info in stored] == ["VNM"]
        assert stored[0].source == "a"


def test_sync_reference_data_never_overwrites_existing_rows(
    factory: sessionmaker[Session],
) -> None:
    with session_scope(factory) as session:
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="XYZ", exchange="HOSE", source="manual")
        )
        SqlConstituentRepository(session).replace("VN30", ["XYZ"], "manual")

    _fallback, sync = _chain(factory, [_failing_provider()])
    result = sync.sync_reference_data()

    assert result.used_seed is False
    assert result.symbols == 0
    assert result.constituents == {}
    with session_scope(factory) as session:
        assert SqlSymbolRepository(session).count() == 1
        assert SqlConstituentRepository(session).get("VN30") == ["XYZ"]


def test_sync_benchmark_seeds_vn30_when_providers_fail(
    factory: sessionmaker[Session],
) -> None:
    _fallback, sync = _chain(factory, [_failing_provider()])
    results = sync.sync_benchmarks()

    assert all(not result.ok for result in results)
    assert any("seeded" in warning for result in results for warning in result.warnings)
    with session_scope(factory) as session:
        assert SqlConstituentRepository(session).get("VN30") == sorted(
            seed_constituents("VN30")
        )


def test_sync_benchmark_seeds_vn30_even_when_prices_are_current(
    factory: sessionmaker[Session],
) -> None:
    with session_scope(factory) as session:
        SqlIndexRepository(session).upsert_many(
            "VN30", [make_bar(TODAY, 1000.0, source="manual")]
        )

    _fallback, sync = _chain(factory, [_failing_provider()])
    results = sync.sync_benchmarks()

    vn30 = next(result for result in results if result.symbol == "VN30")
    assert vn30.ok and vn30.status == "up_to_date"
    assert any("seeded" in warning for warning in vn30.warnings)
    with session_scope(factory) as session:
        assert SqlConstituentRepository(session).get("VN30") == sorted(
            seed_constituents("VN30")
        )


def test_data_service_list_symbols_seeds_offline(factory: sessionmaker[Session]) -> None:
    fallback, sync = _chain(factory, [_failing_provider()])
    service = DataService(
        session_factory=factory,
        sync_service=sync,
        fallback=fallback,
        settings=_settings(),
        today_provider=lambda: TODAY,
    )

    symbols = service.list_symbols()
    assert len(symbols) == len(seed_symbols())
    hose = service.list_symbols("HOSE")
    assert {info.exchange for info in hose} == {"HOSE"}
    assert {info.source for info in hose} == {SEED_SOURCE}
