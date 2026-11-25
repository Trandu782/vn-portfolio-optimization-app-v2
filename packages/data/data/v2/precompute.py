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

Backfill order: already-tracked tickers first, then unpriced ``VN100``/``VN30`` members,
then the remaining unpriced names. ``--limit`` caps the tickers that survive the
pre-screen, so a symbol the screen rejects never consumes a slot and every chunked run
makes real progress.

As-of handling: without an explicit ``--as-of`` the pipeline targets the last
*completed* session — today only after the 15:00 ICT close, otherwise the previous
trading day — and then rolls back to the latest published ``VNINDEX`` session when
the upstream EOD bars have not settled yet (a holiday the built-in calendar does not
know, or a provider that publishes late). Fetch windows never extend past that
target, so a provisional intraday bar is never stored as a session. The quality gate
reports data defects instead of an upstream timing problem, and
``precompute_staleness_tolerance_sessions`` can excuse a known one-session publish
lag without disabling the check.

The pipeline is pure orchestration over injected :class:`PrecomputeSources`, so tests
run it against a temporary database and fake sources without touching the network.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from data.calendar import (
    last_completed_session,
    last_trading_day,
    trading_days_between,
    trading_days_from_dates,
    vietnam_today,
)
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

#: Print a progress line every this many tickers inside the per-ticker loops, so a
#: GitHub Actions log shows live progress instead of staying silent for hours.
PROGRESS_LOG_EVERY = 10

#: Cap on the number of pre-screen rejections the price step logs per run; the rest
#: are summarised in one count, so a 1,000-name universe cannot flood the log.
PRE_SCREEN_LOG_LIMIT = 30


def _utc_now() -> datetime:
    """Return the current UTC instant (a runner's clock; sessions are Vietnam dates)."""
    return datetime.now(UTC)


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
    today = (today_provider or vietnam_today)()
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
        now_provider: Callable[[], datetime] | None = None,
        rules: MarketRules = DEFAULT_MARKET_RULES,
        logger: logging.Logger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._sources = sources
        self._settings = settings or get_v2_settings()
        #: The clock the run resolves its Vietnam session with. The runner is UTC, so
        #: a pre-close run and the nightly 02:13 ICT run resolve different dates.
        self._now: Callable[[], datetime] = now_provider or _utc_now
        self._rules = rules
        self._log = logger or logging.getLogger("data.v2.precompute")
        self._backfill_start = date.fromisoformat(self._settings.backfill_start_date)

    def _vietnam_today(self) -> date:
        """Return the current Vietnam calendar date (the runner clock is UTC)."""
        return vietnam_today(self._now())

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
        as_of: date | None = None,
        only_unpriced: bool = False,
    ) -> PrecomputeReport:
        """Run every step and return one report.

        Args:
            mode: ``incremental`` (fetch only new dates) or ``full`` (re-fetch the
                whole backfill window). Anything else raises ``ValueError``.
            start: Override the configured backfill start date.
            limit: Optional cap on the number of tickers the price step processes
                (so a very large universe can be chunked across runs). It is
                applied *after* the pre-screen, so a rejected symbol costs no
                slot; the profile step reuses the same count.
            profiles: Force a profile/corporate-action refresh. Defaults to ``True``
                for a full refresh without a limit and ``False`` otherwise, so a
                chunked backfill fills missing profiles and skips finished ones. A
                forced refresh also re-checks the known-empty tickers that an
                incremental run skips.
            members: Optional index code (``VN30`` or ``VN100``). When set, the
                price, profile, liquidity, quality and adjustment-flag steps only
                process that index's stored members; the master, membership and
                benchmark steps still cover the full universe.
            as_of: Explicit dataset as-of date. When omitted, the pipeline targets the
                last *completed* Vietnam session (today only after the 15:00 ICT
                close) and then falls back to the latest *published* ``VNINDEX``
                session if that date has no upstream bar yet (an unknown holiday or a
                provider that publishes late), logging a warning. An explicit date
                keeps the strict staleness errors, so a genuinely stale dataset still
                fails.
            only_unpriced: Restrict the price step to tickers with no stored bars at
                all, which is the deterministic way to finish a large backfill in
                chunks: the priced tickers are never re-fetched, so every ``limit``
                slot goes to a ticker that still has no data. Combine it with
                ``profiles`` to also re-check the known-empty symbols.
        """
        if mode not in {"incremental", "full"}:
            raise ValueError("mode must be 'incremental' or 'full'")
        target = self._resolve_target(as_of)
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
        if as_of is None:
            # Upstream EOD bars settle after the close, so an automatic run whose
            # target session is not published yet retargets itself to the last
            # published benchmark session instead of failing the quality gate.
            target = self._settle_target(target)
            report.as_of = target
        universe = self._processing_universe(members)
        report.steps.append(
            self._backfill_prices(
                target,
                mode=mode,
                start=fetch_start,
                limit=limit,
                universe=universe,
                refresh_profiles=force_profiles,
                only_unpriced=only_unpriced,
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
        quality_step, quality_errors = self._run_quality(
            target, universe=universe, only_unpriced=only_unpriced
        )
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

    def _resolve_target(self, as_of: date | None) -> date:
        """Return the session this run targets, before any benchmark settlement.

        An explicit ``as_of`` is only rolled back over weekends and the known
        holidays, so a caller asking for a real defect still gets the strict quality
        errors. An automatic run instead targets the last *completed* session: before
        the 15:00 ICT close no official close exists yet, and a market holiday has no
        session at all, so a pre-close or holiday dispatch would otherwise ask for a
        bar that cannot exist and fail the gate with a false ``stale dataset``.
        """
        if as_of is not None:
            return last_trading_day(as_of, self._rules.trading_holidays)
        return last_completed_session(
            self._now(),
            holidays=self._rules.trading_holidays,
            session_close=self._rules.session_close,
        )

    def _settle_target(self, target: date) -> date:
        """Return the last session the upstream benchmark has actually published.

        ``target`` is already the last *completed* session (see ``_resolve_target``),
        so a benchmark that is still behind it means the upstream feed published
        nothing for that session: a holiday the built-in calendar does not know, or a
        provider that is late. Treating that as a defect would fail the run with
        ``quality: stale benchmark`` / ``quality: stale dataset`` for what is only an
        upstream timing problem, so an automatic run retargets itself to the latest
        published benchmark session and warns. An explicit ``--as-of`` never takes
        this path, so the strict errors still catch a genuinely stale dataset.
        """
        with session_scope(self._session_factory) as session:
            latest = SqlIndexRepository(session).latest_date("VNINDEX")
        if latest is None or latest >= target:
            return target
        self._log.warning(
            "as-of fallback: VNINDEX has no bar for %s yet; using the last published "
            "session %s (pass --as-of to force a date)",
            target.isoformat(),
            latest.isoformat(),
        )
        return latest

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
        """Fetch the index series up to ``target`` and never past it.

        ``target`` is the last settled session, so clamping the request to it keeps a
        provisional intraday index bar (which the upstream publishes during the
        session) out of ``indices_daily``; a stored provisional bar would otherwise
        make the benchmark look fresher than every stock bar and break the as-of
        settlement.
        """
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
            if fetch_start > target:
                continue
            try:
                bars = self._sources.index_bars(code, fetch_start, target)
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
        refresh_profiles: bool = False,
        only_unpriced: bool = False,
    ) -> StepResult:
        """Fetch and store adjusted daily bars, resumably and incrementally.

        ``refresh_profiles`` mirrors the forced ``--profiles`` refresh: it keeps the
        known-empty tickers in the candidate set, so a periodic full refresh can
        re-check a symbol that stopped trading. ``only_unpriced`` additionally drops
        every ticker that already has a bar, so a chunked backfill can finish the
        unpriced tail without re-fetching the priced names (combine it with
        ``--profiles`` to re-check the known-empty ones as well).

        Candidates are ordered tracked-first, then unpriced index members, then the
        remaining unpriced names, and ``limit`` is spent only on tickers that pass
        the pre-screen, so a limited run always makes real backfill progress. A
        progress line is printed every :data:`PROGRESS_LOG_EVERY` tickers (and for
        the last one) because the Actions log would otherwise stay silent until
        ``ratio_quality``.
        """
        master = self._master_or(universe)
        if not master:
            return StepResult(name="prices", ok=False, message="empty universe")
        exchange_by_ticker = {record.ticker: record.exchange for record in master}
        all_tickers = [record.ticker for record in master]
        # Tracked names first, then unpriced index members, and (on an incremental
        # run without --profiles) the known-empty names dropped; see the helper.
        ordered = self._order_price_candidates(
            all_tickers,
            skip_known_empty=mode == "incremental" and not refresh_profiles,
        )
        # The pre-screen runs while the limit is spent, so a rejected symbol never
        # consumes a slot; an incremental (or chunked full) run keeps only the
        # tickers whose stored prices are not current.
        tickers = self._select_candidates(
            ordered,
            target=target,
            mode=mode,
            limit=limit,
            only_unpriced=only_unpriced,
        )
        total = len(tickers)
        processed = 0
        fetched = 0
        failures = 0
        for idx, ticker in enumerate(tickers, start=1):
            added, failed = self._backfill_ticker(
                ticker,
                target=target,
                mode=mode,
                start=start,
                exchange=exchange_by_ticker.get(ticker, "HOSE"),
            )
            if failed:
                failures += 1
            if added:
                processed += 1
                fetched += added
            if idx % PROGRESS_LOG_EVERY == 0 or idx == total:
                print(f"[prices] {idx}/{total} {ticker} (+{added} bars)", flush=True)
        message = f"{fetched} bars for {processed} tickers; {failures} failed"
        return StepResult(name="prices", ok=failures == 0, processed=processed, message=message)

    def _backfill_ticker(
        self, ticker: str, *, target: date, mode: str, start: date, exchange: str
    ) -> tuple[int, bool]:
        """Backfill one ticker and return ``(stored bars, failed)``.

        An up-to-date or empty ticker returns ``(0, False)``; a provider failure is
        recorded in ``v2_progress`` and reported as ``(0, True)`` so the caller can
        fail the step without losing the other tickers. Every request ends at
        ``target`` (the last settled session), so a provisional intraday bar is never
        stored as a finished session.
        """
        with session_scope(self._session_factory) as session:
            latest = V2Store(session).latest_price_date(ticker)
        if mode == "incremental" and latest is not None and latest >= target:
            self._record_progress(ticker, "prices", "up_to_date", last_date=latest)
            return 0, False
        if mode == "full" or latest is None:
            # Full backfill (or first fetch): store everything fetched.
            fetch_start = start
            overlap_end: date | None = None
        else:
            # Incremental: refetch a tail overlap together with the new dates so a
            # retroactive re-base (SSI re-adjusts the whole series when a new
            # ex-date lands) is detected and refreshed in place, in this run.
            fetch_start = max(
                start,
                latest - timedelta(days=2 * self._settings.precompute_rebase_overlap_sessions),
            )
            overlap_end = latest
        if fetch_start > target:
            return 0, False
        try:
            bars = self._sources.stock_bars(ticker, fetch_start, target)
        except EmptyResultError:
            self._record_progress(ticker, "prices", "done", last_date=latest)
            return 0, False
        except DataError as exc:
            self._record_progress(
                ticker, "prices", "failed", last_date=latest, error=str(exc)[:1000]
            )
            self._log.warning("prices %s failed: %s", ticker, exc)
            return 0, True
        if overlap_end is not None:
            if self._needs_rebase(ticker, fetch_start, overlap_end, bars):
                # The stored tail disagrees with the fresh adjusted closes: SSI
                # re-based history, so replace the whole series in this run.
                try:
                    bars = self._sources.stock_bars(ticker, start, target)
                except DataError as exc:
                    self._record_progress(
                        ticker,
                        "prices",
                        "failed",
                        last_date=latest,
                        error=str(exc)[:1000],
                    )
                    self._log.warning("prices %s re-base refetch failed: %s", ticker, exc)
                    return 0, True
                self._log.info("prices %s re-based; full history refreshed", ticker)
            else:
                # No re-base: only the genuinely new dates are stored; the unchanged
                # overlap rows are left untouched.
                bars = [bar for bar in bars if bar.date > overlap_end]
        if not bars:
            self._record_progress(ticker, "prices", "done", last_date=latest)
            return 0, False
        prepared, basis = self._prepare_bars(exchange, bars)
        # Persist in this ticker's own session. A duplicate-key batch (Postgres
        # ``CardinalityViolation`` on ``ON CONFLICT DO UPDATE``) or any other
        # database error is contained here and recorded as a failed checkpoint, so
        # one ticker can never abort the whole run and leave every later ticker
        # un-updated. ``_bulk_upsert`` already collapses duplicate ``(symbol, date)``
        # rows before the statement, so this is the last-resort guard.
        try:
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
                        # The cumulative stored bar count, so an incremental run that
                        # adds a session or two keeps the historical count.
                        rows=store.count_prices(ticker),
                    )
                )
        except Exception as exc:
            self._log.error("prices %s upsert failed: %s", ticker, exc)
            self._record_progress(
                ticker, "prices", "failed", last_date=latest, error=str(exc)[:1000]
            )
            return 0, True
        return len(prepared), False

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

    def _order_price_candidates(
        self, tickers: Sequence[str], *, skip_known_empty: bool
    ) -> list[str]:
        """Return the price candidates in backfill priority order.

        Priority (a chunked ``--limit`` run spends its slots in this order):

        1. already-tracked tickers (stored bars or a positive checkpoint count), so
           every scheduled run refreshes the stocks the app already shows;
        2. unpriced members of a tracked index (``VN100``/``VN30``), so the index
           universes the Optimize presets use fill in before the long tail;
        3. every other unpriced symbol, in the master's (alphabetical) order.

        With ``skip_known_empty`` (an incremental run without a forced
        ``--profiles`` refresh) a ticker whose checkpoint is ``done`` with no
        stored bar is dropped, so a symbol that never trades stops costing a daily
        API call; a full run or ``--profiles`` keeps it so the periodic refresh can
        re-check it. Emptiness is decided by ``v2_daily_prices``, so a legacy zero
        count on a priced ticker can never hide it from the daily run.
        """
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            checkpoints = {record.symbol: record for record in store.list_progress("prices")}
            priced = set(store.history_starts())
            index_members = set(store.get_membership("VN100"))
            index_members.update(store.get_membership("VN30"))
        tracked: list[str] = []
        indexed: list[str] = []
        rest: list[str] = []
        for ticker in tickers:
            code = ticker.upper()
            checkpoint = checkpoints.get(code)
            if code in priced or (checkpoint is not None and checkpoint.rows > 0):
                tracked.append(ticker)
            elif skip_known_empty and checkpoint is not None and checkpoint.state == "done":
                continue
            elif code in index_members:
                indexed.append(ticker)
            else:
                rest.append(ticker)
        return tracked + indexed + rest

    def _select_candidates(
        self,
        ordered: Sequence[str],
        *,
        target: date,
        mode: str,
        limit: int | None,
        only_unpriced: bool = False,
    ) -> list[str]:
        """Return the tickers to backfill, in priority order, capped at ``limit``.

        An incremental run, a chunked ``--full --limit`` run and an ``--unpriced`` run
        keep only the tickers whose stored prices are not current, so repeated runs
        walk the universe instead of re-processing the finished names (and a same-day
        run has nothing to do); ``only_unpriced`` drops every ticker that already has
        a bar, whatever its date. The pre-screen then runs while the budget is spent,
        so a symbol it rejects costs no ``--limit`` slot and every limited run makes
        real backfill progress; the rejections are logged once per run, so an unpriced
        ticker can be explained instead of silently disappearing from every run.
        """
        selected: list[str] = []
        if limit is not None and limit <= 0:
            return selected
        check_pending = mode == "incremental" or limit is not None or only_unpriced
        rejected: list[str] = []
        for ticker in ordered:
            if limit is not None and len(selected) >= limit:
                break
            latest: date | None = None
            if check_pending:
                with session_scope(self._session_factory) as session:
                    latest = V2Store(session).latest_price_date(ticker)
                if latest is not None and latest >= target:
                    continue
            if only_unpriced and latest is not None:
                continue
            if self._passes_pre_screen(ticker):
                selected.append(ticker)
            else:
                rejected.append(ticker)
        if rejected:
            listed = ", ".join(rejected[:PRE_SCREEN_LOG_LIMIT])
            more = "" if len(rejected) <= PRE_SCREEN_LOG_LIMIT else ", ..."
            self._log.warning(
                "prices: pre-screen rejected %d candidate(s) (median volume below %d "
                "shares; set VNOPT_V2_PRECOMPUTE_PRE_SCREEN_MIN_MEDIAN_VOLUME=0 to include "
                "them): %s%s",
                len(rejected),
                self._settings.precompute_pre_screen_min_median_volume,
                listed,
                more,
            )
        return selected

    def _passes_pre_screen(self, ticker: str) -> bool:
        """Return ``False`` when ``ticker`` is too illiquid to be worth a backfill.

        This is a **backfill-cost floor, not a liquidity filter**: it removes a
        ticker only when its recent median volume is below the (low, 10k-share
        default) ``precompute_pre_screen_min_median_volume`` so the priced universe
        stays affordable. It is not a tradability/liquidity rule, and setting the
        threshold to 0 (or ``..._PRE_SCREEN_ENABLED=false``) disables it, so "All
        Stocks" is not silently filtered — run one backfill chunk with the pre-screen
        off to price the illiquid tail. A transient screening failure keeps the
        ticker.
        """
        if not self._settings.precompute_pre_screen_enabled:
            return True
        threshold = self._settings.precompute_pre_screen_min_median_volume
        if threshold <= 0:
            return True
        today = self._vietnam_today()
        start = today - timedelta(days=self._settings.precompute_pre_screen_days)
        try:
            bars = self._sources.screen_bars(ticker, start, today)
        except EmptyResultError:
            return False  # no recent prints: illiquid, skip the SSI calls
        except DataError:
            return True  # transient failure: keep rather than drop
        volumes = [bar.volume for bar in bars]
        return bool(volumes) and median(volumes) >= threshold

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
        trimmed to the ticker's group before they are stored. A progress line is
        printed every :data:`PROGRESS_LOG_EVERY` tickers (and for the last one).
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
        total = len(candidates)
        processed = 0
        failures = 0
        written = 0
        for idx, ticker in enumerate(candidates, start=1):
            added = 0
            try:
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
                # SSI's ``finance-indicator`` response can repeat a period inside one
                # batch (seen on ``AAH``). Keep the last copy so the stored row and
                # the progress count match, and so Postgres never sees a duplicate
                # conflict key in one ``ON CONFLICT DO UPDATE`` statement.
                unique_periods = {
                    (period.period, period.period_type): period for period in periods
                }
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
                    for period in unique_periods.values()
                ]
                with session_scope(self._session_factory) as session:
                    added = V2Store(session).upsert_ratios(ratio_rows)
                written += added
                self._record_progress(
                    ticker, "ratios", "done", last_date=target, rows=len(ratio_rows)
                )
                processed += 1
            finally:
                if idx % PROGRESS_LOG_EVERY == 0 or idx == total:
                    print(f"[ratios] {idx}/{total} {ticker} (+{added} rows)", flush=True)
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
    def _sessions_behind(self, latest: date | None, target: date) -> int:
        """Return how many trading sessions ``latest`` lags ``target`` (0 = current).

        An absent series reports :data:`sys.maxsize`, so a configured tolerance can
        never excuse a dataset or benchmark that has no bars at all. The count uses
        the market calendar (weekends plus ``rules.trading_holidays``); an unknown
        holiday is already absorbed by ``_settle_target``, which moves the target back
        to the last session the benchmark published.
        """
        if latest is None:
            return sys.maxsize
        if latest >= target:
            return 0
        return len(
            trading_days_between(
                latest + timedelta(days=1), target, self._rules.trading_holidays
            )
        )

    def _run_quality(
        self,
        target: date,
        *,
        universe: Sequence[TickerRecord] | None = None,
        only_unpriced: bool = False,
    ) -> tuple[StepResult, int]:
        """Run the quality checks; only integrity errors fail the step.

        Integrity errors are dataset-level and hard: an empty benchmark calendar
        (missing benchmark), a benchmark or overall price series older than ``target``
        by more than ``precompute_staleness_tolerance_sessions`` (stale latest date), a
        universe member with no stored bars (no data), a duplicate date, and any
        schema error surfaced by a check. Per-ticker data-quality findings (missing
        days, zero-volume runs, suspicious moves, adjusted-vs-raw mismatch) are
        warnings: they are logged and stored as adjustment flags but never fail the
        step.

        An ``only_unpriced`` backfill never refreshes the priced tickers, so it cannot
        make the dataset-level series current: it reports that lag as a warning
        instead of failing a run whose job is to add tickers. The scheduled
        (non-backfill) runs keep the hard check.
        """
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            master = list(universe) if universe is not None else store.list_ticker_master()
            # Real exchange calendar from the stored VN-Index bars (not the
            # illustrative holiday set), shared by every ticker's missing-day check.
            trading_days = trading_days_from_dates(store.list_index_dates("VNINDEX"))
            benchmark_latest = SqlIndexRepository(session).latest_date("VNINDEX")
            overall_latest = store.overall_latest_price_date()
        tolerance = max(0, self._settings.precompute_staleness_tolerance_sessions)
        errors = 0
        benchmark_lag = self._sessions_behind(benchmark_latest, target)
        if not trading_days:
            self._log.error("quality: benchmark VNINDEX has no stored trading days")
            errors += 1
        elif benchmark_lag > tolerance:
            errors += 1
            self._log.error(
                "quality: stale benchmark, latest VNINDEX bar %s (target %s)",
                benchmark_latest.isoformat() if benchmark_latest else "none",
                target.isoformat(),
            )
        elif benchmark_lag:
            self._log.warning(
                "quality: benchmark is %d session(s) behind %s (within the %d-session "
                "tolerance)",
                benchmark_lag,
                target.isoformat(),
                tolerance,
            )
        dataset_lag = self._sessions_behind(overall_latest, target)
        if master and dataset_lag and not (only_unpriced or dataset_lag <= tolerance):
            errors += 1
            self._log.error(
                "quality: stale dataset, latest price bar %s (target %s)",
                overall_latest.isoformat() if overall_latest else "none",
                target.isoformat(),
            )
        elif master and dataset_lag:
            # Name the cause: a price feed that publishes after the index is the usual
            # reason, and a backfill run cannot fix it by design.
            cause = (
                "the price source has not published that session yet (the VNINDEX "
                "benchmark already has it)"
                if benchmark_latest is not None and benchmark_latest >= target
                else "the upstream feeds are behind it"
            )
            scope = (
                "an --unpriced backfill does not refresh the priced tickers"
                if only_unpriced
                else f"within the {tolerance}-session tolerance"
            )
            self._log.warning(
                "quality: latest price bar %s is %d session(s) behind %s: %s; not failing "
                "this run (%s)",
                overall_latest.isoformat() if overall_latest else "none",
                dataset_lag,
                target.isoformat(),
                cause,
                scope,
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
    "PRE_SCREEN_LOG_LIMIT",
    "PROGRESS_LOG_EVERY",
    "RATIO_WARNING_LOG_LIMIT",
    "V2_BENCHMARKS",
    "PrecomputeSources",
    "V2PrecomputeService",
    "compute_adjustment_flags",
    "recompute_adjustment_flags_offline",
    "sources_from_context",
]

