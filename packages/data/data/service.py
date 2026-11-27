"""Read-side service used by the API.

``DataService`` reads cached data from the repositories, triggers a bounded
on-demand backfill when a requested symbol has never been stored, and runs the
quality checks. It never loops over providers itself - the sync service and
failover chain already own that - so the API layer stays thin.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES
from data.benchmarks import BENCHMARK_BY_CODE
from data.calendar import last_trading_day, trading_days_between
from data.db.base import session_scope
from data.db.repositories import (
    SqlConstituentRepository,
    SqlIndexRepository,
    SqlPriceRepository,
    SqlSymbolRepository,
)
from data.fallback import FallbackProvider
from data.models import (
    DataFreshness,
    PriceBar,
    PriceSeries,
    ProviderStatus,
    QualityFinding,
    QualityReport,
    SymbolInfo,
)
from data.quality import run_quality_checks
from data.settings import DataSettings
from data.sync import SyncService
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store


class DataService:
    """Serve cached data and run on-demand backfills for the API."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        sync_service: SyncService,
        fallback: FallbackProvider,
        settings: DataSettings,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._sync = sync_service
        self._fallback = fallback
        self._settings = settings
        self._today: Callable[[], date] = today_provider or date.today

    @property
    def today(self) -> date:
        """Return the injectable "today" shared with staleness and freshness checks."""
        return self._today()

    def list_symbols(self, exchange: str | None = None) -> list[SymbolInfo]:
        """Return stored symbols, seeding reference data once on an empty database.

        Ticker search must not depend on a prior cron run, so the first request
        against an empty ``symbols`` table asks the failover chain for a listing
        and accepts the built-in snapshot when every provider is unavailable.
        """
        with session_scope(self._session_factory) as session:
            repository = SqlSymbolRepository(session)
            empty = repository.count() == 0
            symbols = repository.list(exchange)
        if empty:
            self._sync.sync_reference_data()
            with session_scope(self._session_factory) as session:
                symbols = SqlSymbolRepository(session).list(exchange)
        return symbols

    def get_symbol(self, code: str) -> SymbolInfo | None:
        """Return the stored metadata for ``code`` (or ``None`` when unknown)."""
        with session_scope(self._session_factory) as session:
            return SqlSymbolRepository(session).get(code.strip().upper())

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Return an index's members, populating them on first use.

        Backs the curated universe presets (VN30 today). The first call against an
        empty ``index_constituents`` table asks the failover chain and accepts the
        built-in snapshot when every provider is unavailable, mirroring
        :meth:`list_symbols`.
        """
        code = index_code.strip().upper()
        with session_scope(self._session_factory) as session:
            members = SqlConstituentRepository(session).get(code)
        if not members:
            self._sync.ensure_index_constituents(code)
            with session_scope(self._session_factory) as session:
                members = SqlConstituentRepository(session).get(code)
        return members

    def provider_status(self) -> list[ProviderStatus]:
        """Return the latest health of every provider in the failover chain."""
        return self._fallback.statuses()

    def data_freshness(self) -> DataFreshness:
        """Return the latest stored price date, the freshest price source and provider health.

        ``latest_date`` is the freshest stored bar across **both** price stores (V1
        ``prices_daily`` and V2 ``v2_daily_prices``), and ``primary`` is the provider
        that owns that freshest bar — the V2 source (``ssi_statistics`` today) when the
        V2 precompute is current, else the first healthy provider in ``PROVIDER_ORDER``
        (KBS by default). The badge renders these, so it reports the source the Portfolio
        page will actually value against.
        """
        with session_scope(self._session_factory) as session:
            v1_latest = SqlPriceRepository(session).overall_latest_date()
            store = V2Store(session)
            v2_latest = store.overall_latest_price_date()
            v2_source = store.latest_source()
        statuses = self._fallback.statuses()
        healthy = [status for status in statuses if status.healthy]
        v2_date = v2_latest if v2_latest is not None else date.min
        v1_date = v1_latest if v1_latest is not None else date.min
        latest: date | None
        primary: str | None
        if v2_date >= v1_date and v2_latest is not None:
            latest = v2_latest
            primary = v2_source or (healthy[0].id if healthy else None)
        else:
            latest = v1_latest
            primary = healthy[0].id if healthy else None
        return DataFreshness(
            latest_date=latest,
            primary=primary,
            stale=self._is_stale(latest, self._today()) if latest is not None else False,
            providers=statuses,
        )

    def overall_latest_price_date(self) -> date | None:
        """Return the freshest stored price date across V1 and V2, or ``None``.

        ``None`` only when neither store has a single bar. Used by the Portfolio page to
        compare every holding's latest bar against the global latest session.
        """
        with session_scope(self._session_factory) as session:
            v1_latest = SqlPriceRepository(session).overall_latest_date()
            v2_latest = V2Store(session).overall_latest_price_date()
        return max(
            (day for day in (v1_latest, v2_latest) if day is not None), default=None
        )

    def get_prices(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        ensure: bool = True,
    ) -> PriceSeries:
        """Return cached daily prices, backfilling missing history on demand.

        The stored series is extended backwards when the requested ``start`` is
        earlier than the earliest stored bar, so a 3Y/5Y/Max window reaches the
        full available history instead of being capped at the first fetch depth.
        """
        code = symbol.upper()
        today = self._today()
        range_end = end or today
        range_start = start or (range_end - timedelta(days=self._settings.on_demand_history_days))
        status = "ok"
        warnings: list[str] = []
        if ensure:
            # An explicit ``start`` means the caller needs data from that date:
            # extend the stored history if it begins later. Without ``start`` we
            # only ensure any data exists (the portfolio/P&L views need the latest
            # bar, not a specific depth).
            needs_sync = (
                not self._covers_since(code, start)
                if start is not None
                else not self._has_prices(code)
            )
            if needs_sync:
                result = self._sync.sync_symbol(code, start=start, allow_unknown=False)
                if not result.ok:
                    status = "queued"
                    warnings.append(
                        "queued for next sync: providers unavailable "
                        f"({result.message or 'no provider served the data'})"
                    )
        return self._read_series(code, range_start, range_end, status, warnings)

    def get_prices_preferring_v2_adjusted(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> PriceSeries:
        """Return prices preferring the V2 **adjusted** closes, else the V1 path.

        The V1 provider prices are unadjusted (``adj_close == close``), so the
        optimizer's returns historically used raw closes. When the V2 precompute has
        stored an adjusted series for ``symbol`` (``v2_daily_prices.close_adj``), this
        serves that instead, so corporate actions do not create fake returns. A symbol
        without V2 data (not precomputed yet) falls back to the V1 series unchanged.
        The provenance label records the V2 source and basis so the UI can show it.
        """
        code = symbol.upper()
        today = self._today()
        range_end = end or today
        range_start = start or (range_end - timedelta(days=self._settings.on_demand_history_days))
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            bars = store.get_prices(code, range_start, range_end)
        if not bars:
            # No V2-adjusted data for this ticker; use the normal (V1) path.
            return self.get_prices(symbol, start=start, end=end, ensure=True)
        return self._price_series_from_v2(code, bars, today)

    def get_prices_preferring_v2_spot(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        recent_days: int | None = None,
    ) -> PriceSeries:
        """Return prices preferring the V2 **spot** (raw) closes, else the V1 path.

        The Portfolio page values a current holding at the latest *spot* market price,
        not a corporate-action-adjusted close. The V2 precompute stores the raw close
        (``v2_daily_prices.close_raw``) alongside the adjusted close, so when V2 has a
        series for ``symbol`` this serves the raw close (``PriceBar.close``) and reports
        the true V2 source and date. A symbol with no V2 bars yet falls back to the V1
        series (still backfilling on demand), so an unknown ticker still gets a price.
        When ``recent_days`` is set (and ``start`` is ``None``), the V2 query reads
        only that trailing window without triggering a bogus V1 ``_covers_since``
        backfill on fallback.
        """
        code = symbol.upper()
        today = self._today()
        range_end = end or today
        lookback = recent_days if recent_days is not None else self._settings.on_demand_history_days
        range_start = start or (range_end - timedelta(days=lookback))
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            bars = store.get_prices(code, range_start, range_end)
            if not bars and recent_days is not None and start is None:
                latest = store.latest_price_date(code)
                if latest is not None:
                    bars = store.get_prices(
                        code, latest - timedelta(days=recent_days), latest
                    )
        if not bars:
            # No V2 data for this ticker; use the normal (V1) path.
            return self.get_prices(symbol, start=start, end=end, ensure=True)
        return self._price_series_from_v2(code, bars, today)

    def get_prices_preferring_v2_spot_batch(
        self,
        symbols: Sequence[str],
        *,
        start: date | None = None,
        end: date | None = None,
        recent_days: int | None = None,
    ) -> dict[str, PriceSeries]:
        """Batch variant of :meth:`get_prices_preferring_v2_spot`."""
        codes = list(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        if not codes:
            return {}
        today = self._today()
        range_end = end or today
        lookback = recent_days if recent_days is not None else self._settings.on_demand_history_days
        range_start = start or (range_end - timedelta(days=lookback))
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            bars_by_code = store.get_prices_batch(codes, range_start, range_end)
            if recent_days is not None and start is None:
                for code in codes:
                    if code not in bars_by_code:
                        latest = store.latest_price_date(code)
                        if latest is not None:
                            bars_by_code[code] = store.get_prices(
                                code, latest - timedelta(days=recent_days), latest
                            )
        result: dict[str, PriceSeries] = {}
        for code in codes:
            bars = bars_by_code.get(code)
            if bars:
                result[code] = self._price_series_from_v2(code, bars, today)
            else:
                result[code] = self.get_prices(code, start=start, end=end, ensure=True)
        return result

    def get_prices_v2(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> PriceSeries:
        """Return prices from the V2 store **only** (no V1 fallback).

        The Optimize, P&L and Risk routes call this so every price, return and
        valuation query resolves from the unified V2 dataset (``v2_daily_prices``).
        A ticker without V2 bars returns an empty series with ``status="missing"``
        and an explicit warning, so the caller surfaces a data-availability problem
        instead of silently using a stale V1 series. Staleness uses the same
        calendar/tolerance rule as the V1 path.
        """
        code = symbol.upper()
        today = self._today()
        range_end = end or today
        range_start = start or (range_end - timedelta(days=self._settings.on_demand_history_days))
        with session_scope(self._session_factory) as session:
            bars = V2Store(session).get_prices(code, range_start, range_end)
        if not bars:
            return PriceSeries(
                symbol=code,
                source=None,
                stale=False,
                status="missing",
                warnings=[
                    f"no V2 price data for {code}; run the V2 precompute/backfill "
                    "(V1 prices are not used for this calculation)"
                ],
                rows=[],
            )
        return self._price_series_from_v2(code, bars, today)

    def get_prices_v2_batch(
        self,
        symbols: Sequence[str],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, PriceSeries]:
        """Return V2-only :class:`PriceSeries` keyed by upper-cased ticker in one query."""
        codes = list(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        )
        if not codes:
            return {}
        today = self._today()
        range_end = end or today
        range_start = start or (
            range_end - timedelta(days=self._settings.on_demand_history_days)
        )
        with session_scope(self._session_factory) as session:
            bars_by_code = V2Store(session).get_prices_batch(codes, range_start, range_end)
        result: dict[str, PriceSeries] = {}
        for code in codes:
            bars = bars_by_code.get(code)
            if not bars:
                result[code] = PriceSeries(
                    symbol=code,
                    source=None,
                    stale=False,
                    status="missing",
                    warnings=[
                        f"no V2 price data for {code}; run the V2 precompute/backfill "
                        "(V1 prices are not used for this calculation)"
                    ],
                    rows=[],
                )
            else:
                result[code] = self._price_series_from_v2(code, bars, today)
        return result

    def _price_series_from_v2(
        self, code: str, bars: list[AdjustedOHLCV], today: date, *, status: str = "ok"
    ) -> PriceSeries:
        """Build a :class:`PriceSeries` from stored V2 bars.

        ``PriceBar.close`` is the raw/spot close (``close_raw`` when the provider
        published one, else the adjusted close — the anonymous providers here publish
        both and ``close_raw`` mirrors the reported close). ``PriceBar.adj_close``
        carries the V2 adjusted close so the returns path stays corporate-action-aware.
        Staleness uses the same calendar/tolerance rule as the V1 path.
        """
        warnings: list[str] = []
        latest = bars[-1].date
        stale = self._is_stale(latest, today)
        if stale:
            warnings.append("data may be stale: latest bar is older than the last trading day")
        rows = [
            PriceBar(
                date=bar.date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close_raw if bar.close_raw is not None else bar.close,
                adj_close=bar.close,
                volume=bar.volume,
                value=bar.value,
                source=bar.source,
            )
            for bar in bars
        ]
        return PriceSeries(
            symbol=code,
            source=rows[-1].source if rows else None,
            stale=stale,
            status=status,
            warnings=warnings,
            rows=rows,
        )

    def get_index_prices(
        self,
        index_code: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> PriceSeries:
        """Return cached benchmark prices, syncing the index on first request."""
        code = index_code.upper()
        today = self._today()
        range_end = end or today
        range_start = start or (range_end - timedelta(days=self._settings.on_demand_history_days))
        status = "ok"
        warnings: list[str] = []
        # Mirror get_prices: extend the index backwards only for an explicit
        # ``start``; otherwise just ensure the index exists.
        needs_sync = (
            not self._index_covers_since(code, start)
            if start is not None
            else not self._has_index(code)
        )
        if needs_sync:
            benchmark = BENCHMARK_BY_CODE.get(code)
            if benchmark is not None:
                result = self._sync.sync_benchmark(benchmark, start=start)
                if not result.ok:
                    status = "queued"
                    warnings.append("queued for next sync: providers unavailable")
        with session_scope(self._session_factory) as session:
            indices = SqlIndexRepository(session)
            rows = indices.get_range(code, range_start, range_end)
            latest = indices.latest_date(code)
        stale = self._is_stale(latest, today)
        if stale:
            warnings.append("data may be stale: latest bar is older than the last trading day")
        return PriceSeries(
            symbol=code,
            source=rows[-1].source if rows else None,
            stale=stale,
            status=status,
            warnings=warnings,
            rows=rows,
        )

    def get_quality(self, symbol: str) -> QualityReport:
        """Run every quality check over the symbol's full stored series."""
        code = symbol.upper()
        with session_scope(self._session_factory) as session:
            info = SqlSymbolRepository(session).get(code)
            prices = SqlPriceRepository(session)
            earliest = prices.earliest_date(code)
            latest = prices.latest_date(code)
            bars = prices.get_range(code, earliest, latest) if earliest and latest else []
        exchange = (info.exchange if info is not None else "HOSE") or "HOSE"
        if exchange == "UNKNOWN":
            exchange = "HOSE"
        if not bars:
            return QualityReport(
                symbol=code,
                ok=False,
                checked_at=datetime.now(UTC),
                checks_run=[],
                findings=[
                    QualityFinding(
                        check="data",
                        severity="error",
                        message="no price data available; sync the symbol first",
                    )
                ],
            )
        return run_quality_checks(
            code, bars, exchange=exchange, rules=DEFAULT_MARKET_RULES, as_of=self._today()
        )

    # -- helpers ------------------------------------------------------------
    def _has_prices(self, code: str) -> bool:
        with session_scope(self._session_factory) as session:
            return SqlPriceRepository(session).count(code) > 0

    def _has_index(self, code: str) -> bool:
        with session_scope(self._session_factory) as session:
            return SqlIndexRepository(session).count(code) > 0

    def _covers_since(self, code: str, start: date) -> bool:
        """Return ``True`` when stored prices already begin on or before ``start``."""
        with session_scope(self._session_factory) as session:
            earliest = SqlPriceRepository(session).earliest_date(code)
        return earliest is not None and earliest <= start

    def _index_covers_since(self, code: str, start: date) -> bool:
        """Return ``True`` when stored index bars already begin on or before ``start``."""
        with session_scope(self._session_factory) as session:
            earliest = SqlIndexRepository(session).earliest_date(code)
        return earliest is not None and earliest <= start

    def _is_stale(self, latest: date | None, today: date) -> bool:
        if latest is None:
            return False
        holidays = DEFAULT_MARKET_RULES.trading_holidays
        last_open = last_trading_day(today, holidays)
        if latest >= last_open:
            return False
        missing = trading_days_between(latest + timedelta(days=1), last_open, holidays)
        return len(missing) > self._settings.stale_tolerance_days

    def _read_series(
        self,
        code: str,
        start: date,
        end: date,
        status: str,
        warnings: list[str],
    ) -> PriceSeries:
        with session_scope(self._session_factory) as session:
            prices = SqlPriceRepository(session)
            rows: list[PriceBar] = prices.get_range(code, start, end)
            latest = prices.latest_date(code)
        stale = self._is_stale(latest, self._today())
        if stale:
            warnings.append("data may be stale: latest bar is older than the last trading day")
        if not rows and status == "ok":
            warnings.append(
                f"no cached bars between {start.isoformat()} and {end.isoformat()}"
            )
        return PriceSeries(
            symbol=code,
            source=rows[-1].source if rows else None,
            stale=stale,
            status=status,
            warnings=warnings,
            rows=rows,
        )
