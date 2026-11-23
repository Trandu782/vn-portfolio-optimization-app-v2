"""SQLAlchemy repository behaviour against a temporary SQLite database."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker
from support import make_bar

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.repositories import (
    SqlConstituentRepository,
    SqlIndexRepository,
    SqlPriceRepository,
    SqlSymbolRepository,
    SqlSyncLogRepository,
    SyncLogEntry,
)
from data.models import SymbolInfo


@pytest.fixture
def factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_for(f"sqlite:///{tmp_path / 'test.db'}")
    create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def test_price_upsert_is_idempotent(factory: sessionmaker[Session]) -> None:
    bar = make_bar(date(2024, 1, 2), 100.0, source="tcbs")
    with session_scope(factory) as session:
        SqlSymbolRepository(session).upsert(
            SymbolInfo(code="VNM", exchange="HOSE", source="manual")
        )
        prices = SqlPriceRepository(session)
        assert prices.upsert_many("VNM", [bar]) == 1
        assert prices.upsert_many("VNM", [bar]) == 1
        assert prices.count("VNM") == 1
        assert prices.latest_date("VNM") == date(2024, 1, 2)
        assert prices.source_of_latest("VNM") == "tcbs"
        rows = prices.get_range("VNM", date(2024, 1, 1), date(2024, 1, 3))
        assert rows[0].close == 100.0


def test_symbol_repository_lists_by_exchange(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        repo = SqlSymbolRepository(session)
        repo.upsert(SymbolInfo(code="VNM", exchange="HOSE", source="manual"))
        repo.upsert(SymbolInfo(code="ACB", exchange="HNX", source="manual"))
        assert [info.code for info in repo.list()] == ["ACB", "VNM"]
        assert [info.code for info in repo.list("HOSE")] == ["VNM"]
        assert repo.get("VNM") is not None
        assert repo.count() == 2


def test_constituents_replace(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        repo = SqlConstituentRepository(session)
        repo.replace("VN30", ["VNM", "FPT", "VNM"], "tcbs")
        assert repo.get("VN30") == ["FPT", "VNM"]
        repo.replace("VN30", ["ACB"], "tcbs")
        assert repo.get("VN30") == ["ACB"]


def test_index_repository_roundtrip(factory: sessionmaker[Session]) -> None:
    bar = make_bar(date(2024, 1, 2), 1000.0, source="tcbs")
    with session_scope(factory) as session:
        repo = SqlIndexRepository(session)
        assert repo.upsert_many("VNINDEX", [bar]) == 1
        assert repo.latest_date("VNINDEX") == date(2024, 1, 2)
        assert repo.count("VNINDEX") == 1
        rows = repo.get_range("VNINDEX", date(2024, 1, 1), date(2024, 1, 3))
        assert rows[0].close == 1000.0


def test_sync_log_records_and_reads_recent(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        repo = SqlSyncLogRepository(session)
        repo.record(SyncLogEntry(kind="symbol", status="updated", symbol="VNM", rows_upserted=5))
        repo.record(
            SyncLogEntry(kind="symbol", status="queued", symbol="FPT", error_type="network")
        )
        recent = repo.recent(limit=10)
        assert len(recent) == 2
        assert recent[0].status == "queued"  # newest first
