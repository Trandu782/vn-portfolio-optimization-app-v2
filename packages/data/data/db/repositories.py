"""Repository interfaces and their SQLAlchemy 2 implementations.

Every database read/write in the data layer goes through one of these classes;
callers depend on the ``Protocol`` shape, not on SQLAlchemy. Upserts are
idempotent and use the SQLite/Postgres ``ON CONFLICT`` clause when available, so
re-running the sync never duplicates a day.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from data.db.models import IndexConstituent, IndexDaily, PriceDaily, Symbol, SyncLog, utcnow
from data.models import PriceBar, SymbolInfo


@dataclass
class SyncLogEntry:
    """One row of the ``sync_log`` progress/audit trail."""

    kind: str
    status: str
    symbol: str | None = None
    provider: str | None = None
    error: str | None = None
    error_type: str | None = None
    rows_upserted: int = 0
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    id: int | None = None


class SymbolRepository(Protocol):
    """Reads and writes the ``symbols`` table."""

    def get(self, code: str) -> SymbolInfo | None: ...
    def list(self, exchange: str | None = None) -> list[SymbolInfo]: ...
    def upsert(self, info: SymbolInfo) -> None: ...
    def count(self) -> int: ...


class PriceRepository(Protocol):
    """Reads and writes the ``prices_daily`` table."""

    def latest_date(self, symbol: str) -> date | None: ...
    def earliest_date(self, symbol: str) -> date | None: ...
    def source_of_latest(self, symbol: str) -> str | None: ...
    def overall_latest_date(self) -> date | None: ...
    def get_range(self, symbol: str, start: date, end: date) -> list[PriceBar]: ...
    def upsert_many(self, symbol: str, bars: Sequence[PriceBar]) -> int: ...
    def delete(self, symbol: str) -> None: ...
    def count(self, symbol: str) -> int: ...


class IndexRepository(Protocol):
    """Reads and writes the ``indices_daily`` table."""

    def latest_date(self, index_code: str) -> date | None: ...
    def earliest_date(self, index_code: str) -> date | None: ...
    def get_range(self, index_code: str, start: date, end: date) -> list[PriceBar]: ...
    def upsert_many(self, index_code: str, bars: Sequence[PriceBar]) -> int: ...
    def count(self, index_code: str) -> int: ...


class ConstituentRepository(Protocol):
    """Reads and replaces the ``index_constituents`` table."""

    def get(self, index_code: str) -> list[str]: ...
    def replace(self, index_code: str, codes: Sequence[str], source: str) -> None: ...


class SyncLogRepository(Protocol):
    """Appends to and reads the ``sync_log`` table."""

    def record(self, entry: SyncLogEntry) -> None: ...
    def recent(self, limit: int = 20) -> list[SyncLogEntry]: ...


def _dialect(session: Session) -> str:
    """Return the underlying database dialect name."""
    return session.get_bind().dialect.name


def _bulk_upsert(
    session: Session,
    model: type[Any],
    rows: Sequence[dict[str, Any]],
    *,
    key_columns: Sequence[str],
    update_columns: Sequence[str],
    chunk: int = 500,
) -> int:
    """Insert ``rows`` and update ``update_columns`` on conflict; return count."""
    if not rows:
        return 0
    dialect = _dialect(session)
    written = 0
    for start in range(0, len(rows), chunk):
        batch = list(rows[start : start + chunk])
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            statement = sqlite_insert(model).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=list(key_columns),
                set_={col: getattr(statement.excluded, col) for col in update_columns},
            )
            session.execute(statement)
        elif dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            pg_statement = pg_insert(model).values(batch)
            pg_statement = pg_statement.on_conflict_do_update(
                index_elements=list(key_columns),
                set_={col: getattr(pg_statement.excluded, col) for col in update_columns},
            )
            session.execute(pg_statement)
        else:  # pragma: no cover - other databases use a portable merge
            for row in batch:
                session.merge(model(**row))
        written += len(batch)
    return written


def _symbol_to_info(row: Symbol) -> SymbolInfo:
    return SymbolInfo(
        code=row.code, exchange=row.exchange, name=row.name, type=row.type, source=row.source
    )


def _price_to_bar(row: PriceDaily) -> PriceBar:
    return PriceBar(
        date=row.date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        adj_close=row.adj_close,
        volume=row.volume,
        value=row.value,
        source=row.source,
    )


class SqlSymbolRepository:
    """SQLAlchemy implementation of :class:`SymbolRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, code: str) -> SymbolInfo | None:
        row = self._session.get(Symbol, code)
        return _symbol_to_info(row) if row is not None else None

    def list(self, exchange: str | None = None) -> list[SymbolInfo]:
        statement = select(Symbol).order_by(Symbol.code)
        if exchange:
            statement = statement.where(Symbol.exchange == exchange.upper())
        return [_symbol_to_info(row) for row in self._session.scalars(statement)]

    def upsert(self, info: SymbolInfo) -> None:
        self._session.merge(
            Symbol(
                code=info.code,
                exchange=info.exchange,
                name=info.name,
                type=info.type,
                source=info.source,
                updated_at=utcnow(),
            )
        )

    def count(self) -> int:
        total = self._session.scalar(select(func.count()).select_from(Symbol))
        return int(total or 0)


class SqlPriceRepository:
    """SQLAlchemy implementation of :class:`PriceRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_date(self, symbol: str) -> date | None:
        return self._session.scalar(
            select(func.max(PriceDaily.date)).where(PriceDaily.symbol_code == symbol)
        )

    def earliest_date(self, symbol: str) -> date | None:
        return self._session.scalar(
            select(func.min(PriceDaily.date)).where(PriceDaily.symbol_code == symbol)
        )

    def source_of_latest(self, symbol: str) -> str | None:
        return self._session.scalar(
            select(PriceDaily.source)
            .where(PriceDaily.symbol_code == symbol)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        )

    def overall_latest_date(self) -> date | None:
        """Return the newest stored price date across every symbol."""
        return self._session.scalar(select(func.max(PriceDaily.date)))

    def get_range(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        statement = (
            select(PriceDaily)
            .where(
                PriceDaily.symbol_code == symbol,
                PriceDaily.date >= start,
                PriceDaily.date <= end,
            )
            .order_by(PriceDaily.date)
        )
        return [_price_to_bar(row) for row in self._session.scalars(statement)]

    def upsert_many(self, symbol: str, bars: Sequence[PriceBar]) -> int:
        rows = [
            {
                "symbol_code": symbol,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
                "volume": bar.volume,
                "value": bar.value,
                "source": bar.source,
            }
            for bar in bars
        ]
        return _bulk_upsert(
            self._session,
            PriceDaily,
            rows,
            key_columns=["symbol_code", "date"],
            update_columns=[
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
                "value",
                "source",
            ],
        )

    def delete(self, symbol: str) -> None:
        self._session.execute(delete(PriceDaily).where(PriceDaily.symbol_code == symbol))

    def count(self, symbol: str) -> int:
        total = self._session.scalar(
            select(func.count())
            .select_from(PriceDaily)
            .where(PriceDaily.symbol_code == symbol)
        )
        return int(total or 0)


def _index_to_bar(row: IndexDaily) -> PriceBar:
    return PriceBar(
        date=row.date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        adj_close=row.adj_close,
        volume=row.volume,
        value=row.value,
        source=row.source,
    )


class SqlIndexRepository:
    """SQLAlchemy implementation of :class:`IndexRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_date(self, index_code: str) -> date | None:
        return self._session.scalar(
            select(func.max(IndexDaily.date)).where(IndexDaily.index_code == index_code)
        )

    def earliest_date(self, index_code: str) -> date | None:
        return self._session.scalar(
            select(func.min(IndexDaily.date)).where(IndexDaily.index_code == index_code)
        )

    def get_range(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        statement = (
            select(IndexDaily)
            .where(
                IndexDaily.index_code == index_code,
                IndexDaily.date >= start,
                IndexDaily.date <= end,
            )
            .order_by(IndexDaily.date)
        )
        return [_index_to_bar(row) for row in self._session.scalars(statement)]

    def upsert_many(self, index_code: str, bars: Sequence[PriceBar]) -> int:
        rows = [
            {
                "index_code": index_code,
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
                "volume": bar.volume,
                "value": bar.value,
                "source": bar.source,
            }
            for bar in bars
        ]
        return _bulk_upsert(
            self._session,
            IndexDaily,
            rows,
            key_columns=["index_code", "date"],
            update_columns=[
                "open",
                "high",
                "low",
                "close",
                "adj_close",
                "volume",
                "value",
                "source",
            ],
        )

    def count(self, index_code: str) -> int:
        total = self._session.scalar(
            select(func.count())
            .select_from(IndexDaily)
            .where(IndexDaily.index_code == index_code)
        )
        return int(total or 0)


class SqlConstituentRepository:
    """SQLAlchemy implementation of :class:`ConstituentRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, index_code: str) -> list[str]:
        statement = (
            select(IndexConstituent.symbol_code)
            .where(IndexConstituent.index_code == index_code)
            .order_by(IndexConstituent.symbol_code)
        )
        return list(self._session.scalars(statement))

    def replace(self, index_code: str, codes: Sequence[str], source: str) -> None:
        self._session.execute(
            delete(IndexConstituent).where(IndexConstituent.index_code == index_code)
        )
        now = utcnow()
        unique_codes = list(dict.fromkeys(code.upper() for code in codes))
        rows = [
            {
                "index_code": index_code,
                "symbol_code": code,
                "source": source,
                "updated_at": now,
            }
            for code in unique_codes
        ]
        if rows:
            _bulk_upsert(
                self._session,
                IndexConstituent,
                rows,
                key_columns=["index_code", "symbol_code"],
                update_columns=["source", "updated_at"],
            )


def _sync_log_to_entry(row: SyncLog) -> SyncLogEntry:
    return SyncLogEntry(
        id=row.id,
        kind=row.kind,
        status=row.status,
        symbol=row.symbol,
        provider=row.provider,
        error=row.error,
        error_type=row.error_type,
        rows_upserted=row.rows_upserted,
        message=row.message,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class SqlSyncLogRepository:
    """SQLAlchemy implementation of :class:`SyncLogRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, entry: SyncLogEntry) -> None:
        self._session.add(
            SyncLog(
                kind=entry.kind,
                status=entry.status,
                symbol=entry.symbol,
                provider=entry.provider,
                error=entry.error,
                error_type=entry.error_type,
                rows_upserted=entry.rows_upserted,
                message=entry.message,
                started_at=entry.started_at or utcnow(),
                finished_at=entry.finished_at,
            )
        )
        self._session.flush()

    def recent(self, limit: int = 20) -> list[SyncLogEntry]:
        statement = select(SyncLog).order_by(SyncLog.id.desc()).limit(limit)
        return [_sync_log_to_entry(row) for row in self._session.scalars(statement)]
