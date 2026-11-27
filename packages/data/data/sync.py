"""Incremental, idempotent sync from the failover chain into the database.

``SyncService`` is the single place that decides *what to fetch* (only missing
days), *whether a source change is safe* (via :mod:`data.consistency`) and *what
to record* (``sync_log``). The CLI (``python -m data.jobs.sync``) and the
protected ``/api/v1/data/refresh`` endpoint both drive this service, so the manual
and scheduled paths behave identically.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES
from core.validation import MIN_MARKET_DATE
from data.benchmarks import BENCHMARK_BY_CODE, BENCHMARKS, Benchmark
from data.calendar import last_trading_day
from data.consistency import compare_overlap
from data.db.base import session_scope
from data.db.models import V2TickerMaster, utcnow
from data.db.repositories import (
    SqlConstituentRepository,
    SqlIndexRepository,
    SqlPriceRepository,
    SqlSymbolRepository,
    SqlSyncLogRepository,
    SyncLogEntry,
)
from data.errors import AllProvidersFailedError, ProviderError
from data.fallback import FallbackProvider
from data.models import RefreshResult, SymbolInfo
from data.seed import SEED_SOURCE, seed_constituents, seed_symbols
from data.settings import DataSettings


@dataclass
class SymbolSyncResult:
    """Outcome of syncing one symbol or benchmark."""

    symbol: str
    kind: str
    ok: bool
    status: str
    provider: str | None = None
    rows: int = 0
    message: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReferenceSyncResult:
    """Outcome of filling the empty symbol / index-constituent tables."""

    ok: bool = True
    symbols: int = 0
    symbol_source: str | None = None
    constituents: dict[str, int] = field(default_factory=dict)
    constituent_sources: dict[str, str] = field(default_factory=dict)
    used_seed: bool = False
    warnings: list[str] = field(default_factory=list)


class SyncService:
    """Incremental sync orchestration over repositories and the failover chain."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        fallback: FallbackProvider,
        settings: DataSettings,
        today_provider: Callable[[], date] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._fallback = fallback
        self._settings = settings
        self._today: Callable[[], date] = today_provider or date.today
        self._monotonic: Callable[[], float] = monotonic or time.monotonic

    def sync_symbol(
        self,
        symbol: str,
        *,
        history_days: int | None = None,
        force_full: bool = False,
        start: date | None = None,
        allow_unknown: bool = False,
    ) -> SymbolSyncResult:
        """Fetch and store only the days missing from ``prices_daily``.

        ``start`` is the earliest date the caller needs. When the stored history
        begins after it, the missing older days are fetched and added, so a long
        analysis window (3Y/5Y/Max) can reach the full available history instead
        of being capped at the first fetch depth.

        When ``allow_unknown`` is ``False`` (the default for unauthenticated read
        paths), unknown tickers not present in ``symbols`` or ``v2_ticker_master``
        return immediately with ``status="unknown_symbol"`` without mutating
        ``symbols`` or ``sync_log`` or issuing outbound HTTP requests.
        """
        code = symbol.strip().upper()
        with session_scope(self._session_factory) as session:
            symbols = SqlSymbolRepository(session)
            prices = SqlPriceRepository(session)
            logs = SqlSyncLogRepository(session)
            started = utcnow()
            symbol_info = symbols.get(code)
            v2_record = (
                session.scalar(
                    select(V2TickerMaster).where(V2TickerMaster.ticker == code)
                )
                if symbol_info is None
                else None
            )
            if symbol_info is None and v2_record is None and not allow_unknown:
                return SymbolSyncResult(
                    code,
                    "symbol",
                    False,
                    "unknown_symbol",
                    message="unknown symbol",
                )
            if symbol_info is None:
                symbols.upsert(
                    SymbolInfo(
                        code=code,
                        exchange=(
                            v2_record.exchange if v2_record is not None else "UNKNOWN"
                        ),
                        name=v2_record.name if v2_record is not None else None,
                        type=(
                            (v2_record.security_type or "stock")
                            if v2_record is not None
                            else "stock"
                        ),
                        source=v2_record.source if v2_record is not None else "manual",
                    )
                )
            earliest = prices.earliest_date(code)
            last = None if force_full else prices.latest_date(code)
            today = self._today()
            last_open = last_trading_day(today, DEFAULT_MARKET_RULES.trading_holidays)
            # A stored history that begins after the caller's ``start`` must be
            # extended backwards even when the latest bar is already current.
            extends_history = (
                start is not None and earliest is not None and earliest > start
            )
            if (
                not force_full
                and not extends_history
                and last is not None
                and last >= last_open
            ):
                return self._finish(
                    logs, started, SymbolSyncResult(code, "symbol", True, "up_to_date")
                )
            if force_full or last is None:
                days = history_days or self._settings.on_demand_history_days
                fetch_start = start or (today - timedelta(days=days))
                fetch_end = today
                replacing = force_full
            elif start is not None and earliest is not None and earliest > start:
                # Extend backwards from the requested start. Fetch up to today so
                # the fetched bars overlap the stored ones: the overlap check
                # (below) keeps the series from splicing two providers.
                fetch_start = start
                fetch_end = today
                replacing = False
            else:
                fetch_start = max(earliest or last, last - timedelta(days=10))
                fetch_end = today
                replacing = False
            fetch_start = max(fetch_start, MIN_MARKET_DATE)
            fetch_end = min(fetch_end, today)
            if fetch_start > fetch_end:
                return self._finish(
                    logs, started, SymbolSyncResult(code, "symbol", True, "up_to_date")
                )
            try:
                result = self._fallback.get_daily_prices(code, fetch_start, fetch_end)
            except AllProvidersFailedError as exc:
                error = exc.failures[-1] if exc.failures else None
                return self._finish(
                    logs,
                    started,
                    SymbolSyncResult(
                        code,
                        "symbol",
                        False,
                        "queued",
                        provider=error.provider if error else None,
                        message="queued for next sync",
                    ),
                    error=error,
                )
            bars = result.value
            if not bars:
                return self._finish(
                    logs,
                    started,
                    SymbolSyncResult(code, "symbol", True, "up_to_date", provider=result.provider),
                )
            warnings: list[str] = []
            previous = None if replacing else prices.source_of_latest(code)
            if previous is not None and result.provider != previous and last is not None:
                existing = prices.get_range(code, fetch_start, last)
                overlap = compare_overlap(
                    existing, bars, tolerance=self._settings.price_mismatch_tolerance
                )
                if overlap.has_overlap and not overlap.consistent:
                    # Refetch the whole history from the new provider, covering
                    # any backwards extension as well as the stored range.
                    history_start = (
                        min(fetch_start, earliest)
                        if earliest is not None
                        else fetch_start
                    )
                    replaced = self._replace_from_provider(
                        prices,
                        code,
                        history_start,
                        today,
                        previous,
                        overlap.max_relative_diff,
                    )
                    if replaced is not None:
                        return self._finish(logs, started, replaced)
                    warnings.append(
                        f"cross-provider mismatch vs {previous} "
                        f"(max {overlap.max_relative_diff:.2%}); full refetch failed"
                    )
            if replacing:
                prices.delete(code)
            written = prices.upsert_many(code, bars)
            return self._finish(
                logs,
                started,
                SymbolSyncResult(
                    code,
                    "symbol",
                    True,
                    "updated",
                    provider=result.provider,
                    rows=written,
                    warnings=warnings,
                ),
            )

    def _replace_from_provider(
        self,
        prices: SqlPriceRepository,
        code: str,
        history_start: date,
        end: date,
        previous_source: str,
        max_diff: float,
    ) -> SymbolSyncResult | None:
        """Refetch the full history from the new provider and replace the series.

        Reuses the caller's session/transaction so a single SQLite connection
        performs the delete and re-insert atomically.
        """
        try:
            full = self._fallback.get_daily_prices(code, history_start, end)
        except AllProvidersFailedError:
            return None
        prices.delete(code)
        written = prices.upsert_many(code, full.value)
        return SymbolSyncResult(
            code,
            "symbol",
            True,
            "replaced",
            provider=full.provider,
            rows=written,
            warnings=[
                f"replaced history from {full.provider}: price mismatch vs "
                f"{previous_source} (max {max_diff:.2%})"
            ],
        )

    def sync_benchmark(
        self,
        benchmark: Benchmark,
        *,
        history_days: int | None = None,
        start: date | None = None,
    ) -> SymbolSyncResult:
        """Fetch and store only the missing days for one benchmark index.

        ``start`` is the earliest date the caller needs; a stored index series
        that begins after it is extended backwards so a long analysis window can
        reach the full available history.
        """
        with session_scope(self._session_factory) as session:
            indices = SqlIndexRepository(session)
            constituents = SqlConstituentRepository(session)
            logs = SqlSyncLogRepository(session)
            started = utcnow()
            reference_source = self._ensure_constituents(constituents, benchmark.code)
            reference_warnings = (
                ["constituents seeded from the built-in list"]
                if reference_source == SEED_SOURCE
                else []
            )
            earliest = indices.earliest_date(benchmark.code)
            last = indices.latest_date(benchmark.code)
            today = self._today()
            last_open = last_trading_day(today, DEFAULT_MARKET_RULES.trading_holidays)
            extends_history = (
                start is not None and earliest is not None and earliest > start
            )
            if not extends_history and last is not None and last >= last_open:
                return self._finish(
                    logs,
                    started,
                    SymbolSyncResult(
                        benchmark.code,
                        "index",
                        True,
                        "up_to_date",
                        warnings=reference_warnings,
                    ),
                )
            if last is None:
                days = history_days or self._settings.on_demand_history_days
                fetch_start = start or (today - timedelta(days=days))
                fetch_end = today
            elif start is not None and earliest is not None and earliest > start:
                # Extend the index backwards from the requested start (up to today,
                # matching the first-fetch window).
                fetch_start = start
                fetch_end = today
            else:
                fetch_start = last - timedelta(days=10)
                fetch_end = today
            fetch_start = max(fetch_start, MIN_MARKET_DATE)
            fetch_end = min(fetch_end, today)
            if fetch_start > fetch_end:
                return self._finish(
                    logs,
                    started,
                    SymbolSyncResult(
                        benchmark.code,
                        "index",
                        True,
                        "up_to_date",
                        warnings=reference_warnings,
                    ),
                )
            try:
                result = self._fallback.get_index_daily(
                    benchmark.code, fetch_start, fetch_end
                )
            except AllProvidersFailedError as exc:
                error = exc.failures[-1] if exc.failures else None
                return self._finish(
                    logs,
                    started,
                    SymbolSyncResult(
                        benchmark.code,
                        "index",
                        False,
                        "queued",
                        provider=error.provider if error else None,
                        message="queued for next sync",
                        warnings=reference_warnings,
                    ),
                    error=error,
                )
            written = indices.upsert_many(benchmark.code, result.value) if result.value else 0
            status = "updated" if written else "up_to_date"
            return self._finish(
                logs,
                started,
                SymbolSyncResult(
                    benchmark.code,
                    "index",
                    True,
                    status,
                    provider=result.provider,
                    rows=written,
                    warnings=reference_warnings,
                ),
            )

    def sync_benchmarks(self, *, history_days: int | None = None) -> list[SymbolSyncResult]:
        """Sync every benchmark index."""
        return [
            self.sync_benchmark(benchmark, history_days=history_days)
            for benchmark in BENCHMARKS
        ]

    def sync_reference_data(self) -> ReferenceSyncResult:
        """Fill the empty symbol and index-constituent tables.

        The failover chain is asked first. Only when every provider fails and the
        table is still empty does this write the built-in snapshot from
        :mod:`data.seed`, so ticker search and the VN30 preset keep working
        offline or behind a restrictive network without ever shadowing live data.
        """
        result = ReferenceSyncResult()
        with session_scope(self._session_factory) as session:
            symbols = SqlSymbolRepository(session)
            if symbols.count() == 0:
                self._load_symbols(symbols, result)
            constituents = SqlConstituentRepository(session)
            for benchmark in BENCHMARKS:
                source = self._ensure_constituents(constituents, benchmark.code)
                if source is None:
                    continue
                count = len(constituents.get(benchmark.code))
                result.constituents[benchmark.code] = count
                result.constituent_sources[benchmark.code] = source
                if source == SEED_SOURCE:
                    result.used_seed = True
                    result.warnings.append(
                        "live providers unavailable; seeded "
                        f"{count} {benchmark.code} constituents"
                    )
        return result

    def _load_symbols(
        self, symbols: SqlSymbolRepository, result: ReferenceSyncResult
    ) -> None:
        """Upsert the provider listing into an empty table, or seed it as a last resort."""
        try:
            listed = self._fallback.list_symbols("")
        except AllProvidersFailedError:
            seeded = seed_symbols()
            for info in seeded:
                symbols.upsert(info)
            result.symbols = len(seeded)
            result.symbol_source = SEED_SOURCE
            result.used_seed = True
            result.warnings.append(
                "live providers unavailable; seeded "
                f"{len(seeded)} symbols from the built-in list"
            )
            return
        for info in listed.value:
            symbols.upsert(info)
        result.symbols = len(listed.value)
        result.symbol_source = listed.provider

    def _seed_constituents(
        self, constituents: SqlConstituentRepository, index_code: str
    ) -> int:
        """Write the built-in members of ``index_code`` when the table has none."""
        if constituents.get(index_code):
            return 0
        codes = seed_constituents(index_code)
        if not codes:
            return 0
        constituents.replace(index_code, codes, SEED_SOURCE)
        return len(codes)

    def _ensure_constituents(
        self, constituents: SqlConstituentRepository, index_code: str
    ) -> str | None:
        """Fill ``index_code``'s members when the table has none.

        Returns the source that filled the table (a provider id or
        :data:`SEED_SOURCE`), or ``None`` when rows already existed or neither a
        provider nor the built-in snapshot could supply members.
        """
        if constituents.get(index_code):
            return None
        try:
            members = self._fallback.get_index_constituents(index_code)
        except AllProvidersFailedError:
            seeded = self._seed_constituents(constituents, index_code)
            return SEED_SOURCE if seeded else None
        constituents.replace(index_code, members.value, members.provider)
        return members.provider

    def ensure_index_constituents(self, index_code: str) -> str | None:
        """Populate ``index_code``'s members if the table is still empty.

        Public wrapper around :meth:`_ensure_constituents` so readers (the universe
        preset endpoint) can trigger the fill without opening their own session.
        Returns the source that filled the table, or ``None`` when rows already
        existed or could not be obtained.
        """
        code = index_code.strip().upper()
        with session_scope(self._session_factory) as session:
            return self._ensure_constituents(SqlConstituentRepository(session), code)

    def refresh_batch(
        self,
        *,
        cursor: int = 0,
        limit: int | None = None,
        time_budget: float | None = None,
    ) -> RefreshResult:
        """Process a bounded batch of symbols + benchmarks and report the remainder."""
        batch_limit = limit if limit is not None else self._settings.sync_batch_size
        budget = (
            time_budget
            if time_budget is not None
            else float(self._settings.sync_time_budget_seconds)
        )
        with session_scope(self._session_factory) as session:
            symbol_codes = [info.code for info in SqlSymbolRepository(session).list()]
        work: list[tuple[str, str]] = [
            *(("index", benchmark.code) for benchmark in BENCHMARKS),
            *(("symbol", code) for code in symbol_codes),
        ]
        total = len(work)
        index = max(0, cursor)
        started = self._monotonic()
        processed = 0
        done_codes: list[str] = []
        failures: dict[str, str] = {}
        while index < total:
            if processed >= batch_limit:
                break
            if processed > 0 and (self._monotonic() - started) >= budget:
                break
            kind, code = work[index]
            result = (
                self.sync_benchmark(BENCHMARK_BY_CODE[code])
                if kind == "index"
                else self.sync_symbol(code)
            )
            if result.ok:
                done_codes.append(code)
            else:
                failures[code] = result.status
            index += 1
            processed += 1
        remaining = total - index
        done = remaining <= 0
        next_cursor = 0 if done else index
        self._record_refresh(processed, next_cursor, total, done)
        return RefreshResult(
            done=done,
            status="done" if done else "partial",
            processed=processed,
            remaining=remaining,
            cursor=next_cursor,
            symbols_done=done_codes,
            failures=failures,
        )

    def _record_refresh(self, processed: int, cursor: int, total: int, done: bool) -> None:
        with session_scope(self._session_factory) as session:
            SqlSyncLogRepository(session).record(
                SyncLogEntry(
                    kind="refresh",
                    status="done" if done else "in_progress",
                    rows_upserted=processed,
                    message=f"cursor={cursor} total={total}",
                    finished_at=utcnow(),
                )
            )

    def _finish(
        self,
        logs: SqlSyncLogRepository,
        started: datetime,
        result: SymbolSyncResult,
        *,
        error: ProviderError | None = None,
    ) -> SymbolSyncResult:
        """Record one sync attempt and return the result."""
        logs.record(
            SyncLogEntry(
                kind=result.kind,
                status=result.status,
                symbol=result.symbol,
                provider=result.provider,
                error=str(error) if error is not None else None,
                error_type=error.error_type if error is not None else None,
                rows_upserted=result.rows,
                message=result.message
                or ("; ".join(result.warnings) if result.warnings else None),
                started_at=started,
                finished_at=utcnow(),
            )
        )
        return result
