"""Resumable, scheduled, online V2 precompute pipeline.

The pipeline builds every V2 dataset from the adapter layer and stores it in the
additive V2 tables (``docs/DECISIONS.md`` records the storage choice):

1. ticker master (SSI + KBS masters, ICB level-2 sectors, explicit coverage gaps);
2. VN30/VN100 membership with an as-of date and source, validating VN30 is a subset;
3. VN-Index, VN30 and VN100 benchmark series from the VCI index bars;
4. adjusted daily prices with matched volume/value, pre-screened then backfilled in
   resumable per-ticker chunks;
5. rolling 20-session ADTV/ADV medians with a volume basis;
6. shares outstanding and full market cap (free-float stays absent);
7. DIV/ISS corporate actions (used by the quality checks and the adjustment fallback);
8. quality checks that fail loudly.

Resumability: each ticker commits in its own session and its checkpoint
(``v2_progress``) records the last committed date. An interrupted backfill resumes from
the stored bars, and an incremental run fetches only ``latest + 1 .. today`` (about one
page per ticker).

The pipeline is pure orchestration over injected :class:`PrecomputeSources`, so tests
run it against a temporary database and fake sources without touching the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from data.calendar import last_trading_day, trading_days_from_dates
from data.db.base import session_scope
from data.db.models import utcnow
from data.db.repositories import SqlIndexRepository
from data.errors import DataError, EmptyResultError
from data.models import PriceBar
from data.v2.adjustment import adjust_price_gaps
from data.v2.adjustment_quality import adjustment_quality_flag, flag_source
from data.v2.config import V2DataSettings, get_v2_settings
from data.v2.context import V2DataContext
from data.v2.fundamentals import aggregate_sector_statistics
from data.v2.liquidity import liquidity_stats
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    CoverageSummary,
    LiquidityRecord,
    MarketCapRecord,
    PrecomputeReport,
    ProgressRecord,
    RatioRecord,
    StepResult,
    TickerRecord,
)
from data.v2.quality import run_v2_quality_checks
from data.v2.ratio_quality import run_ratio_quality_checks
from data.v2.ratios import ratio_group_for, trim_ratios
from data.v2.registry import (
    build_company_profile,
    build_constituents,
    build_corporate_actions,
    build_ohlcv,
    build_ratios,
    build_sector_map,
    build_symbol_master,
)
from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    CorporateAction,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
    SymbolMaster,
)
from data.v2.store import V2Store
from data.v2.universe import UniverseBuild, build_universe, validate_vn30_subset

#: Benchmarks maintained by the V2 pipeline (VCI index bars; V1 keeps its own list).
V2_BENCHMARKS: tuple[str, ...] = ("VNINDEX", "VN30", "VN100")

#: Cap on the number of individual ratio findings the job logs per run; the rest
#: are summarised in one line. ``scripts/verify_v2_ratios.py`` prints the full set.
RATIO_WARNING_LOG_LIMIT = 30


@dataclass(frozen=True)
class PrecomputeSources:
    """The injected fetchers the pipeline orchestrates (one per data need)."""

    ssi_symbol_master: Callable[[], list[SymbolMaster]]
    kbs_symbol_master: Callable[[], list[SymbolMaster]]
    sectors: Callable[[], list[SectorMap]]
    index_members: Callable[[str], IndexConstituents]
    index_bars: Callable[[str, date, date], list[AdjustedOHLCV]]
    stock_bars: Callable[[str, date, date], list[AdjustedOHLCV]]
    screen_bars: Callable[[str, date, date], list[AdjustedOHLCV]]
    company_profile: Callable[[str], CompanyProfile]
    corporate_actions: Callable[[str, date, date], list[CorporateAction]]
    ratios: Callable[[str], list[FinancialRatios]] | None = None
    ratios_latest: Callable[[str], list[FinancialRatios]] | None = None


def sources_from_context(context: V2DataContext) -> PrecomputeSources:
    """Wire the real adapters into :class:`PrecomputeSources`."""
    http = context.http
    settings = context.settings
    ssi_master = build_symbol_master("ssi_statistics", http, settings)
    kbs_master = build_symbol_master("kbs", http, settings)
    sector_map = build_sector_map("ssi_statistics", http, settings)
    members = build_constituents("kbs", http, settings)
    index_bars = build_ohlcv("vci", http, settings)
    stock_bars = build_ohlcv("ssi_statistics", http, settings)
    screen = build_ohlcv("kbs", http, settings)
    profiles = build_company_profile("ssi_statistics", http, settings)
    actions = build_corporate_actions("ssi_statistics", http, settings)
    ratios = build_ratios("ssi_statistics", http, settings)
    return PrecomputeSources(
        ssi_symbol_master=ssi_master.get_symbol_master,
        kbs_symbol_master=kbs_master.get_symbol_master,
        sectors=sector_map.get_sector_map_all,
        index_members=members.get_index_constituents,
        index_bars=index_bars.get_index_ohlcv,
        stock_bars=stock_bars.get_ohlcv,
        screen_bars=screen.get_ohlcv,
        company_profile=profiles.get_company_profile,
        corporate_actions=actions.get_corporate_actions,
        ratios=ratios.get_ratios,
        ratios_latest=getattr(ratios, "get_latest_ratios", ratios.get_ratios),
    )


def compute_adjustment_flags(
    session_factory: sessionmaker[Session],
    *,
    target: date,
    universe: Sequence[TickerRecord] | None = None,
    rules: MarketRules = DEFAULT_MARKET_RULES,
) -> StepResult:
    """Compute each ticker's adjustment-quality flag from the stored data and persist it.

    Reads only stored prices and corporate actions (never the network). ``universe``
    restricts the work to the given tickers; ``None`` uses the whole stored master. Each
    written row's ``source`` carries the price provenance plus
    :data:`~data.v2.adjustment_quality.FLAGS_POLICY_VERSION`, so a later read can tell
    whether the row was produced by the current rule set.
    """
    if universe is not None:
        master = list(universe)
    else:
        with session_scope(session_factory) as session:
            master = V2Store(session).list_ticker_master()
    records: list[AdjustmentFlagRecord] = []
    for record in master:
        with session_scope(session_factory) as session:
            store = V2Store(session)
            bars = store.get_prices(record.ticker)
            actions = store.get_corporate_actions(record.ticker)
        if not bars:
            continue
        flag = adjustment_quality_flag(record.ticker, bars, actions, rules=rules)
        records.append(
            AdjustmentFlagRecord(
                ticker=record.ticker,
                severity=flag.severity,
                flagged=flag.flagged,
                exclude_from_group_indices=flag.exclude_from_group_indices,
                reasons=flag.reasons,
                dates=flag.dates,
                anomalies=flag.anomalies,
                source=flag_source(bars[-1].source),
                data_as_of=target,
            )
        )
    with session_scope(session_factory) as session:
        processed = V2Store(session).upsert_adjustment_flags(records)
    return StepResult(name="adjustment_flags", ok=True, processed=processed)


def recompute_adjustment_flags_offline(
    session_factory: sessionmaker[Session],
    *,
    members: str,
    rules: MarketRules = DEFAULT_MARKET_RULES,
    today_provider: Callable[[], date] | None = None,
) -> PrecomputeReport:
    """Recompute one index's stored adjustment-quality flags from local data only.

    This is the ``--recompute-flags`` entry point: it reads stored prices and corporate
    actions, never the network, so the flags can be refreshed after a policy change
    without re-downloading any price.
    """
    today = (today_provider or date.today)()
    target = last_trading_day(today, rules.trading_holidays)
    report = PrecomputeReport(mode="recompute_flags", as_of=target, started_at=utcnow())
    with session_scope(session_factory) as session:
        store = V2Store(session)
        master = store.list_ticker_master()
        wanted = {code.strip().upper() for code in store.get_membership(members)}
    universe = [record for record in master if record.ticker in wanted]
    report.steps.append(
        compute_adjustment_flags(
            session_factory, target=target, universe=universe, rules=rules
        )
    )
    report.finished_at = utcnow()
    report.ok = all(step.ok for step in report.steps)
    return report


class V2PrecomputeService:
    """Run the V2 precompute pipeline idempotently, resumably and incrementally."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        sources: PrecomputeSources,
        settings: V2DataSettings | None = None,
        today_provider: Callable[[], date] | None = None,
        rules: MarketRules = DEFAULT_MARKET_RULES,
        logger: logging.Logger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._settings = settings or get_v2_settings()
        self._today: Callable[[], date] = today_provider or date.today
        self._rules = rules
        self._log = logger or logging.getLogger("data.v2.precompute")
        self._backfill_start = date.fromisoformat(self._settings.backfill_start_date)

    @property
    def window(self) -> int:
        """Return the configured rolling-liquidity window in sessions."""
        return self._settings.precompute_window_sessions

    def run(
        self,
        *,
        mode: str = "incremental",
        start: date | None = None,
        limit: int | None = None,
        profiles: bool | None = None,
        members: str | None = None,
    ) -> PrecomputeReport:
        """Run every step and return one report.

        Args:
            mode: ``incremental`` (fetch only new dates) or ``full`` (re-fetch the
                whole backfill window). Anything else raises ``ValueError``.
            start: Override the configured backfill start date.
            limit: Optional cap on the number of tickers processed by the price and
                profile steps (so a very large universe can be chunked across runs).
            profiles: Force a profile/corporate-action refresh. Defaults to ``True``
                for a full refresh without a limit and ``False`` otherwise, so a
                chunked backfill fills missing profiles and skips finished ones.
            members: Optional index code (``VN30`` or ``VN100``). When set, the
                price, profile, liquidity, quality and adjustment-flag steps only
                process that index's stored members; the master, membership and
                benchmark steps still cover the full universe.
        """
        if mode not in {"incremental", "full"}:
            raise ValueError("mode must be 'incremental' or 'full'")
        target = last_trading_day(self._today(), self._rules.trading_holidays)
        fetch_start = start or self._backfill_start
        force_profiles = profiles if profiles is not None else (mode == "full" and limit is None)
        report = PrecomputeReport(mode=mode, as_of=target, started_at=utcnow())

        master_step, built = self._build_master(target)
        report.steps.append(master_step)
        if built is not None:
            report.coverage = CoverageSummary(
                covered=len(built.sectors),
                missing=len(built.missing_sector),
                missing_tickers=built.missing_sector,
            )
        report.steps.append(self._sync_membership(target))
        report.steps.append(self._sync_benchmarks(target, mode=mode, start=fetch_start))
        universe = self._processing_universe(members)
        report.steps.append(
            self._backfill_prices(
                target, mode=mode, start=fetch_start, limit=limit, universe=universe
            )
        )
        report.steps.append(
            self._sync_profiles(
                target, limit=limit, force=force_profiles, start=fetch_start, universe=universe
            )
        )
        report.steps.append(self._compute_liquidity(target, universe=universe))
        report.steps.append(
            self._sync_ratios(target, mode=mode, limit=limit, universe=universe)
        )
        report.steps.append(self._compute_sector_statistics(target))
        report.steps.append(self._run_ratio_quality(target))
        quality_step, quality_errors = self._run_quality(target, universe=universe)
        report.steps.append(quality_step)
        report.steps.append(self._compute_adjustment_flags(target, universe=universe))
        report.quality_errors = quality_errors
        report.finished_at = utcnow()
        report.ok = all(step.ok for step in report.steps)
        return report

    def _processing_universe(self, members: str | None) -> list[TickerRecord]:
        """Return the tickers the per-ticker steps should process.

        ``None`` keeps the whole master; ``VN30``/``VN100`` restricts to that
        index's stored members (read after the membership step) so a dev run can
        price only the index names while the master, membership and benchmark
        steps still cover the full universe.
        """
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            master = store.list_ticker_master()
            if members is None:
                return master
            wanted = {code.strip().upper() for code in store.get_membership(members)}
        return [record for record in master if record.ticker in wanted]

    def _master_or(self, universe: Sequence[TickerRecord] | None) -> list[TickerRecord]:
        """Return ``universe`` when supplied, else the full stored master."""
        if universe is not None:
            return list(universe)
        with session_scope(self._session_factory) as session:
            return V2Store(session).list_ticker_master()

    # -- step 1: ticker master / sectors ----------------------------------
    def _build_master(self, target: date) -> tuple[StepResult, UniverseBuild | None]:
        try:
            ssi_master = self._sources.ssi_symbol_master()
            kbs_master = self._sources.kbs_symbol_master()
            sectors = self._sources.sectors()
        except DataError as exc:
            self._log.error("ticker master failed: %s", exc)
            return StepResult(name="ticker_master", ok=False, message=str(exc)), None
        built = build_universe(ssi_master, kbs_master, sectors, as_of=target)
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            store.upsert_ticker_master(built.master)
            store.upsert_sectors(built.sectors)
        if built.missing_sector:
            self._log.warning(
                "sector coverage gaps (%d tickers, excluded from sector features): %s",
                len(built.missing_sector),
                ", ".join(built.missing_sector[:50]),
            )
        if built.excluded:
            self._log.info(
                "excluded securities (%d): %s",
                len(built.excluded),
                ", ".join(f"{ticker} ({reason})" for ticker, reason in built.excluded[:50]),
            )
        message = f"{len(built.missing_sector)} without sector; {len(built.excluded)} excluded"
        return (
            StepResult(name="ticker_master", ok=True, processed=len(built.master), message=message),
            built,
        )

    # -- step 2: VN30 / VN100 membership ----------------------------------
    def _sync_membership(self, target: date) -> StepResult:
        try:
            vn30 = self._sources.index_members("VN30")
            vn100 = self._sources.index_members("VN100")
        except DataError as exc:
            self._log.error("index membership failed: %s", exc)
            return StepResult(name="index_membership", ok=False, message=str(exc))
        violations = validate_vn30_subset(vn30.members, vn100.members)
        if violations:
            message = f"VN30 is not a subset of VN100: {', '.join(violations[:20])}"
            self._log.error(message)
            return StepResult(name="index_membership", ok=False, message=message)
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            store.replace_membership("VN30", vn30.members, as_of=target, source=vn30.source)
            store.replace_membership("VN100", vn100.members, as_of=target, source=vn100.source)
        return StepResult(
            name="index_membership",
            ok=True,
            processed=len(vn30.members) + len(vn100.members),
        )

    # -- step 3: benchmarks ------------------------------------------------
    def _sync_benchmarks(self, target: date, *, mode: str, start: date) -> StepResult:
        processed = 0
        failures = 0
        for code in V2_BENCHMARKS:
            with session_scope(self._session_factory) as session:
                latest = SqlIndexRepository(session).latest_date(code)
            if mode == "incremental" and latest is not None and latest >= target:
                continue
            fetch_start = start if (mode == "full" or latest is None) else latest + timedelta(
                days=1
            )
            if fetch_start > self._today():
                continue
            try:
                bars = self._sources.index_bars(code, fetch_start, self._today())
            except EmptyResultError:
                continue
            except DataError as exc:
                failures += 1
                self._log.warning("benchmark %s failed: %s", code, exc)
                continue
            with session_scope(self._session_factory) as session:
                SqlIndexRepository(session).upsert_many(
                    code, [self._to_price_bar(bar) for bar in bars]
                )
            processed += len(bars)
        message = f"{failures} failed" if failures else None
        return StepResult(
            name="benchmarks", ok=failures == 0, processed=processed, message=message
        )

    @staticmethod
    def _to_price_bar(bar: AdjustedOHLCV) -> PriceBar:
        """Adapt an index :class:`AdjustedOHLCV` to a stored :class:`PriceBar`."""
        return PriceBar(
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            adj_close=bar.close,
            volume=bar.volume,
            value=bar.value,
            source=bar.source,
        )

    # -- step 4: adjusted prices (resumable, incremental) ------------------
    def _backfill_prices(
        self,
        target: date,
        *,
        mode: str,
        start: date,
        limit: int | None,
        universe: Sequence[TickerRecord] | None = None,
    ) -> StepResult:
        master = self._master_or(universe)
        if not master:
            return StepResult(name="prices", ok=False, message="empty universe")
        exchange_by_ticker = {record.ticker: record.exchange for record in master}
        all_tickers = [record.ticker for record in master]
        if mode == "incremental" or limit is not None:
            # Incremental: only the tickers with new dates. Chunked full: the next
            # `limit` unfinished names. This also skips the cheap pre-screen when a
            # same-day run has nothing to do.
            effective_limit = limit if limit is not None else len(all_tickers)
            candidates = self._pending_tickers(all_tickers, target, effective_limit)
        else:
            candidates = all_tickers
        tickers = self._pre_screen(candidates)
        processed = 0
        fetched = 0
        failures = 0
        for ticker in tickers:
            with session_scope(self._session_factory) as session:
                latest = V2Store(session).latest_price_date(ticker)
            if mode == "incremental" and latest is not None and latest >= target:
                self._record_progress(ticker, "prices", "up_to_date", last_date=latest)
                continue
            if mode == "full" or latest is None:
                # Full backfill (or first fetch): store everything fetched.
                fetch_start = start
                overlap_end: date | None = None
            else:
                # Incremental: refetch a tail overlap together with the new dates so
                # a retroactive re-base (SSI re-adjusts the whole series when a new
                # ex-date lands) is detected and refreshed in place, in this run.
                fetch_start = max(
                    start,
                    latest
                    - timedelta(days=2 * self._settings.precompute_rebase_overlap_sessions),
                )
                overlap_end = latest
            if fetch_start > self._today():
                continue
            try:
                bars = self._sources.stock_bars(ticker, fetch_start, self._today())
            except EmptyResultError:
                self._record_progress(ticker, "prices", "done", last_date=latest)
                continue
            except DataError as exc:
                failures += 1
                self._record_progress(
                    ticker, "prices", "failed", last_date=latest, error=str(exc)[:1000]
                )
                self._log.warning("prices %s failed: %s", ticker, exc)
                continue
            if overlap_end is not None:
                if self._needs_rebase(ticker, fetch_start, overlap_end, bars):
                    # The stored tail disagrees with the fresh adjusted closes: SSI
                    # re-based history, so replace the whole series in this run.
                    try:
                        bars = self._sources.stock_bars(ticker, start, self._today())
                    except DataError as exc:
                        failures += 1
                        self._record_progress(
                            ticker,
                            "prices",
                            "failed",
                            last_date=latest,
                            error=str(exc)[:1000],
                        )
                        self._log.warning("prices %s re-base refetch failed: %s", ticker, exc)
                        continue
                    self._log.info("prices %s re-based; full history refreshed", ticker)
                else:
                    # No re-base: only the genuinely new dates are stored; the
                    # unchanged overlap rows are left untouched.
                    bars = [bar for bar in bars if bar.date > overlap_end]
            if not bars:
                self._record_progress(ticker, "prices", "done", last_date=latest)
                continue
            prepared, basis = self._prepare_bars(exchange_by_ticker.get(ticker, "HOSE"), bars)
            with session_scope(self._session_factory) as session:
                store = V2Store(session)
                store.upsert_prices(
                    ticker, prepared, price_adjustment_basis=basis, data_as_of=target
                )
                store.set_progress(
                    ProgressRecord(
                        kind="prices",
                        symbol=ticker,
                        state="done",
                        last_date=store.latest_price_date(ticker),
                        rows=len(prepared),
                    )
                )
            processed += 1
            fetched += len(prepared)
        message = f"{fetched} bars for {processed} tickers; {failures} failed"
        return StepResult(name="prices", ok=failures == 0, processed=processed, message=message)

    def _needs_rebase(
        self, ticker: str, overlap_start: date, overlap_end: date, bars: list[AdjustedOHLCV]
    ) -> bool:
        """Return ``True`` when the fresh tail disagrees with the stored tail.

        SSI's adjusted closes change retroactively when a new corporate action's
        ex-date lands. The incremental fetch overlaps the stored tail, so a
        difference beyond ``precompute_rebase_tolerance`` between the freshly
        fetched and stored adjusted closes means the stored history is stale. This
        reads prices only, never the corporate-actions feed (which omits some
        bonus issues, e.g. HPG).
        """
        with session_scope(self._session_factory) as session:
            stored = {
                bar.date: bar.close
                for bar in V2Store(session).get_prices(ticker, overlap_start, overlap_end)
            }
        if not stored:
            return False
        tolerance = self._settings.precompute_rebase_tolerance
        for bar in bars:
            previous = stored.get(bar.date)
            if previous is None:
                continue
            if abs(bar.close - previous) > tolerance * max(abs(previous), 1.0):
                return True
        return False

    def _pending_tickers(
        self, tickers: list[str], target: date, limit: int
    ) -> list[str]:
        """Return the next ``limit`` tickers whose prices are not yet current.

        Used for a chunked backfill: repeated ``--full --limit N`` runs each take
        the next unfinished names, so the backfill makes progress instead of
        re-processing the same first chunk.
        """
        pending: list[str] = []
        if limit <= 0:
            return pending
        for ticker in tickers:
            with session_scope(self._session_factory) as session:
                latest = V2Store(session).latest_price_date(ticker)
            if latest is not None and latest >= target:
                continue
            pending.append(ticker)
            if len(pending) >= limit:
                break
        return pending

    def _pre_screen(self, tickers: list[str]) -> list[str]:
        """Drop effectively untraded names before the expensive SSI backfill.

        This is a **backfill-cost floor, not a liquidity filter**: it removes a
        ticker only when its recent median volume is below the (low, 10k-share
        default) ``precompute_pre_screen_min_median_volume`` so the priced universe
        stays affordable. It is not a tradability/liquidity rule, and setting the
        threshold to 0 disables it, so "All Stocks" is not silently filtered.
        """
        if not self._settings.precompute_pre_screen_enabled:
            return list(tickers)
        threshold = self._settings.precompute_pre_screen_min_median_volume
        if threshold <= 0:
            return list(tickers)
        start = self._today() - timedelta(days=self._settings.precompute_pre_screen_days)
        kept: list[str] = []
        for ticker in tickers:
            try:
                bars = self._sources.screen_bars(ticker, start, self._today())
            except EmptyResultError:
                continue  # no recent prints: illiquid, skip the SSI calls
            except DataError:
                kept.append(ticker)  # transient failure: keep rather than drop
                continue
            volumes = [bar.volume for bar in bars]
            if volumes and median(volumes) >= threshold:
                kept.append(ticker)
        return kept

    def _prepare_bars(
        self, exchange: str, bars: list[AdjustedOHLCV]
    ) -> tuple[list[AdjustedOHLCV], str]:
        """Return the bars to store plus the price-adjustment basis that produced them."""
        if any(bar.close_raw is not None for bar in bars):
            return list(bars), "ssi_adjusted"
        result = adjust_price_gaps(bars, exchange=exchange, rules=self._rules)
        if result.events:
            return result.bars, "price_gap_heuristic"
        return list(bars), "raw"

    # -- step 5: market cap + corporate actions ----------------------------
    def _sync_profiles(
        self,
        target: date,
        *,
        limit: int | None,
        force: bool,
        start: date,
        universe: Sequence[TickerRecord] | None = None,
    ) -> StepResult:
        master = self._master_or(universe)
        processed = 0
        failures = 0
        partial = 0
        for record in master:
            if limit is not None and processed >= limit:
                break
            ticker = record.ticker
            with session_scope(self._session_factory) as session:
                store = V2Store(session)
                progress = store.get_progress("profile", ticker)
                has_prices = store.latest_price_date(ticker) is not None
            if not has_prices:
                continue
            if not force and progress is not None and progress.state == "done":
                continue
            profile: CompanyProfile | None
            try:
                profile = self._sources.company_profile(ticker)
            except EmptyResultError:
                profile = None
            except DataError as exc:
                failures += 1
                self._record_progress(ticker, "profile", "failed", error=str(exc)[:1000])
                continue
            actions: list[CorporateAction] = []
            actions_error: str | None = None
            try:
                actions = self._sources.corporate_actions(ticker, start, target)
            except EmptyResultError:
                actions = []
            except DataError as exc:
                # Corporate actions are secondary to the profile: keep the market cap
                # that the profile returned and retry the actions on the next run.
                actions_error = str(exc)[:1000]
            with session_scope(self._session_factory) as session:
                store = V2Store(session)
                if profile is not None:
                    store.upsert_market_cap(
                        MarketCapRecord(
                            symbol=ticker,
                            as_of=target,
                            shares_outstanding=profile.shares_outstanding,
                            market_cap=profile.market_cap,
                            basis="full",
                            source=profile.source,
                            data_as_of=target,
                        )
                    )
                if actions_error is None:
                    store.replace_corporate_actions(ticker, actions, data_as_of=target)
                    store.set_progress(
                        ProgressRecord(
                            kind="profile", symbol=ticker, state="done", last_date=target
                        )
                    )
                else:
                    # ``partial`` is retried next run because only ``done`` is skipped.
                    store.set_progress(
                        ProgressRecord(
                            kind="profile",
                            symbol=ticker,
                            state="partial",
                            last_date=target,
                            error=actions_error,
                        )
                    )
            if actions_error is not None:
                partial += 1
            processed += 1
        if failures or partial:
            parts = [f"{failures} failed"]
            if partial:
                parts.append(f"{partial} partial (corporate actions)")
            message: str | None = "; ".join(parts)
        else:
            message = None
        return StepResult(
            name="profiles",
            ok=failures == 0 and partial == 0,
            processed=processed,
            message=message,
        )

    # -- step 6: rolling liquidity medians ---------------------------------
    def _compute_liquidity(
        self, target: date, *, universe: Sequence[TickerRecord] | None = None
    ) -> StepResult:
        master = self._master_or(universe)
        processed = 0
        for record in master:
            with session_scope(self._session_factory) as session:
                bars = V2Store(session).get_prices(record.ticker)
            if not bars:
                continue
            stats = liquidity_stats(bars, window=self.window)
            with session_scope(self._session_factory) as session:
                V2Store(session).upsert_liquidity(
                    LiquidityRecord(
                        symbol=record.ticker,
                        as_of=stats.as_of,
                        adtv_median=stats.adtv_median,
                        adv_median=stats.adv_median,
                        window=stats.window,
                        volume_basis=stats.volume_basis,  # type: ignore[arg-type]
                        source=bars[-1].source,
                        data_as_of=target,
                    )
                )
            processed += 1
        return StepResult(name="liquidity", ok=True, processed=processed)

    # -- step 6b: per-ticker ratios (full backfill / 1-page incremental) ---
    def _sync_ratios(
        self,
        target: date,
        *,
        mode: str,
        limit: int | None,
        universe: Sequence[TickerRecord] | None = None,
    ) -> StepResult:
        """Fetch and store per-ticker ratios.

        A full run pages every period; an incremental run fetches only the latest
        ``finance-indicator`` page (about one request per ticker, the section-8
        budget) and skips a ticker already refreshed on ``target``. Ratios are
        trimmed to the ticker's group before they are stored.
        """
        full_fetch = self._sources.ratios
        if full_fetch is None:
            return StepResult(name="ratios", ok=True, message="no ratios source")
        master = self._master_or(universe)
        if not master:
            return StepResult(name="ratios", ok=False, message="empty universe")
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            sector_by_ticker = {
                row.ticker.strip().upper(): row.icb_level2_name
                for row in store.list_sectors()
                if row.icb_level2_name
            }
            priced = set(store.history_starts())
        fetch = full_fetch
        incremental = False
        latest_fetch = self._sources.ratios_latest
        if mode == "incremental" and latest_fetch is not None:
            fetch = latest_fetch
            incremental = True
        candidates = [record.ticker for record in master if record.ticker in priced]
        if limit is not None:
            candidates = self._pending_ratio_tickers(candidates, limit)
        processed = 0
        failures = 0
        written = 0
        for ticker in candidates:
            if incremental and self._ratio_refreshed_today(ticker, target):
                continue
            try:
                periods = fetch(ticker)
            except EmptyResultError:
                self._record_progress(ticker, "ratios", "done", last_date=target)
                continue
            except DataError as exc:
                failures += 1
                self._record_progress(ticker, "ratios", "failed", error=str(exc)[:1000])
                self._log.warning("ratios %s failed: %s", ticker, exc)
                continue
            sector = sector_by_ticker.get(ticker)
            group = ratio_group_for(sector)
            ratio_rows = [
                RatioRecord(
                    symbol=ticker,
                    period=period.period,
                    period_type=period.period_type,
                    ratio_group=group,
                    ratios=trim_ratios(period.ratios, sector),
                    source=period.provider,
                    data_as_of=target,
                )
                for period in periods
            ]
            with session_scope(self._session_factory) as session:
                written += V2Store(session).upsert_ratios(ratio_rows)
            self._record_progress(
                ticker, "ratios", "done", last_date=target, rows=len(ratio_rows)
            )
            processed += 1
        message = f"{written} ratio rows for {processed} tickers; {failures} failed"
        return StepResult(name="ratios", ok=failures == 0, processed=processed, message=message)

    def _pending_ratio_tickers(self, tickers: list[str], limit: int) -> list[str]:
        """Return the next ``limit`` tickers with no completed ratio backfill."""
        pending: list[str] = []
        if limit <= 0:
            return pending
        for ticker in tickers:
            with session_scope(self._session_factory) as session:
                progress = V2Store(session).get_progress("ratios", ticker)
            if progress is not None and progress.state == "done":
                continue
            pending.append(ticker)
            if len(pending) >= limit:
                break
        return pending

    def _ratio_refreshed_today(self, ticker: str, target: date) -> bool:
        """Return ``True`` when ``ticker``'s ratios were already refreshed on ``target``."""
        with session_scope(self._session_factory) as session:
            progress = V2Store(session).get_progress("ratios", ticker)
        return (
            progress is not None
            and progress.state == "done"
            and progress.last_date == target
        )

    # -- step 6c: precomputed sector peer statistics -----------------------
    def _compute_sector_statistics(self, target: date) -> StepResult:
        """Aggregate the stored ratios into per-(sector, ratio, period) statistics."""
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            records = store.list_ratios()
            sector_by_ticker = {
                row.ticker.strip().upper(): row.icb_level2_name
                for row in store.list_sectors()
                if row.icb_level2_name
            }
        statistics = aggregate_sector_statistics(
            records, sector_by_ticker, source="ssi_statistics", data_as_of=target
        )
        with session_scope(self._session_factory) as session:
            written = V2Store(session).upsert_sector_statistics(statistics)
        return StepResult(name="sector_statistics", ok=True, processed=written)

    # -- step 6d: ratio quality checks (warning-only) ----------------------
    def _run_ratio_quality(self, target: date) -> StepResult:
        """Run the ratio quality checks and log warnings; never fail the step.

        A ticker with no prices can never have ratios (the ``ratios`` step only
        processes priced tickers), so those are reported as one count line instead
        of one ``no_ratios`` warning each. Only priced tickers (or tickers that
        already have ratios) get a per-ticker ``no_ratios`` check, and every other
        finding is logged individually up to :data:`RATIO_WARNING_LOG_LIMIT` with a
        count for the remainder, so the job output stays readable.
        """
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            master = [record.ticker for record in store.list_ticker_master()]
            records = store.list_ratios()
            priced = set(store.history_starts())
            sectors = {
                row.ticker.strip().upper(): row.icb_level2_name
                for row in store.list_sectors()
            }
        by_ticker: dict[str, list[FinancialRatios]] = {}
        for record in records:
            by_ticker.setdefault(record.symbol, []).append(
                FinancialRatios(
                    ticker=record.symbol,
                    period=record.period,
                    period_type=record.period_type,
                    provider=record.source,
                    ratios=dict(record.ratios),
                )
            )
        expected = priced | set(by_ticker)
        skipped = sorted(set(master) - expected)
        warnings = 0
        no_ratio_gaps: list[str] = []
        other: list[tuple[str, str, str]] = []
        for ticker in master:
            if ticker not in expected:
                continue
            for finding in run_ratio_quality_checks(
                ticker,
                by_ticker.get(ticker, []),
                sector=sectors.get(ticker),
                as_of=target,
            ):
                warnings += 1
                if finding.check == "no_ratios":
                    no_ratio_gaps.append(ticker)
                else:
                    other.append((ticker, finding.check, finding.message))
        for ticker in no_ratio_gaps:
            self._log.warning("%s ratios no_ratios: no financial ratios stored", ticker)
        for ticker, check, message in sorted(other)[:RATIO_WARNING_LOG_LIMIT]:
            self._log.warning("%s ratios %s: %s", ticker, check, message)
        overflow = len(other) - RATIO_WARNING_LOG_LIMIT
        if overflow > 0:
            self._log.warning(
                "%d more ratio warnings not listed; run scripts/verify_v2_ratios.py",
                overflow,
            )
        if skipped:
            self._log.info(
                "%d tickers without prices have no ratios (expected)", len(skipped)
            )
        message = (
            f"{warnings} warnings; {len(no_ratio_gaps)} priced tickers without ratios; "
            f"{len(skipped)} without prices"
        )
        return StepResult(
            name="ratio_quality", ok=True, processed=len(expected), message=message
        )

    # -- step 7: loud quality checks ---------------------------------------
    def _run_quality(
        self, target: date, *, universe: Sequence[TickerRecord] | None = None
    ) -> tuple[StepResult, int]:
        """Run the quality checks; only integrity errors fail the step.

        Integrity errors are dataset-level and hard: an empty benchmark calendar
        (missing benchmark), a benchmark or overall price series older than ``target``
        (stale latest date), a universe member with no stored bars (no data), a
        duplicate date, and any schema error surfaced by a check. Per-ticker
        data-quality findings (missing days, zero-volume runs, suspicious moves,
        adjusted-vs-raw mismatch) are warnings: they are logged and stored as adjustment
        flags but never fail the step.
        """
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            master = list(universe) if universe is not None else store.list_ticker_master()
            # Real exchange calendar from the stored VN-Index bars (not the
            # illustrative holiday set), shared by every ticker's missing-day check.
            trading_days = trading_days_from_dates(store.list_index_dates("VNINDEX"))
            benchmark_latest = SqlIndexRepository(session).latest_date("VNINDEX")
            overall_latest = store.overall_latest_price_date()
        errors = 0
        if not trading_days:
            self._log.error("quality: benchmark VNINDEX has no stored trading days")
            errors += 1
        elif benchmark_latest is None or benchmark_latest < target:
            errors += 1
            self._log.error(
                "quality: stale benchmark, latest VNINDEX bar %s (target %s)",
                benchmark_latest.isoformat() if benchmark_latest else "none",
                target.isoformat(),
            )
        if master and (overall_latest is None or overall_latest < target):
            errors += 1
            self._log.error(
                "quality: stale dataset, latest price bar %s (target %s)",
                overall_latest.isoformat() if overall_latest else "none",
                target.isoformat(),
            )
        checked = 0
        for record in master:
            with session_scope(self._session_factory) as session:
                store = V2Store(session)
                bars = store.get_prices(record.ticker)
                actions = store.get_corporate_actions(record.ticker)
                progress = store.get_progress("prices", record.ticker)
            if progress is None or progress.state == "failed":
                # Not attempted in this run (a chunked backfill or a pre-screened name)
                # or the prices step already reported the failure; do not count it here.
                continue
            checked += 1
            report = run_v2_quality_checks(
                record.ticker,
                bars,
                exchange=record.exchange,
                actions=actions,
                rules=self._rules,
                trading_days=trading_days,
            )
            for finding in report.findings:
                if finding.severity == "error":
                    errors += 1
                    self._log.error(
                        "%s %s: %s", record.ticker, finding.check, finding.message
                    )
        return (
            StepResult(
                name="quality", ok=errors == 0, processed=checked, message=f"{errors} errors"
            ),
            errors,
        )

    # -- step 8: persisted adjustment-quality flags ------------------------
    def _compute_adjustment_flags(
        self, target: date, *, universe: Sequence[TickerRecord] | None = None
    ) -> StepResult:
        """Compute each ticker's adjustment-quality flag once and store it.

        The read endpoints then load the flags instead of recomputing them per
        request, which keeps ``/v2/universe`` fast for a ~1,500-ticker universe.
        """
        return compute_adjustment_flags(
            self._session_factory,
            target=target,
            universe=universe,
            rules=self._rules,
        )

    def _record_progress(
        self,
        ticker: str,
        kind: str,
        state: str,
        *,
        last_date: date | None = None,
        rows: int = 0,
        error: str | None = None,
    ) -> None:
        """Persist one checkpoint in a short session."""
        with session_scope(self._session_factory) as session:
            V2Store(session).set_progress(
                ProgressRecord(
                    kind=kind,
                    symbol=ticker,
                    state=state,
                    last_date=last_date,
                    rows=rows,
                    error=error,
                )
            )


__all__ = [
    "V2_BENCHMARKS",
    "PrecomputeSources",
    "V2PrecomputeService",
    "compute_adjustment_flags",
    "recompute_adjustment_flags_offline",
    "sources_from_context",
]

