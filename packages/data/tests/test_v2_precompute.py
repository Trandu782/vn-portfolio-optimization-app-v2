"""Resumable, incremental V2 precompute pipeline over fake sources."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES
from data.calendar import VIETNAM_UTC_OFFSET
from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.models import V2Progress
from data.db.repositories import SqlIndexRepository
from data.errors import NetworkError
from data.v2.config import V2DataSettings
from data.v2.precompute import (
    RATIO_WARNING_LOG_LIMIT,
    PrecomputeSources,
    V2PrecomputeService,
)
from data.v2.precompute_schemas import ProgressRecord, RatioRecord, TickerRecord
from data.v2.reader import V2Reader, sector_coverage
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

AS_OF = date(2025, 12, 31)
START = date(2025, 12, 1)


def _weekdays(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(start: date, end: date, base: float = 100.0) -> list[AdjustedOHLCV]:
    bars: list[AdjustedOHLCV] = []
    for index, day in enumerate(_weekdays(start, end)):
        close = base + index
        bars.append(
            AdjustedOHLCV(
                date=day,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                close_raw=close * 1.001,
                volume=1000,
                matched_volume=1000,
                matched_value=1000.0 * close,
                source="ssi_statistics",
            )
        )
    return bars


def _volume(bars: list[AdjustedOHLCV], volume: int) -> list[AdjustedOHLCV]:
    """Return the series with every bar's volume replaced (pre-screen input)."""
    return [bar.model_copy(update={"volume": volume}) for bar in bars]


class _Clock:
    """A mutable clock (default 18:00 ICT, i.e. after the close) so a test can move time."""

    def __init__(self, today: date, hour_ict: int = 18) -> None:
        self.today = today
        self.hour_ict = hour_ict

    def __call__(self) -> datetime:
        return datetime.combine(
            self.today, time(self.hour_ict, 0), tzinfo=VIETNAM_UTC_OFFSET
        )


class FakeSources:
    """Scripted fetchers with call recording and an injectable failure set."""

    def __init__(
        self,
        *,
        bars_by_ticker: dict[str, list[AdjustedOHLCV]],
        vn30: list[str],
        vn100: list[str],
        symbols: list[str] | None = None,
    ) -> None:
        self.bars_by_ticker = bars_by_ticker
        self.vn30 = vn30
        self.vn100 = vn100
        self.symbols = symbols if symbols is not None else ["VCB", "FPT", "XYZ"]
        self.bar_calls: list[tuple[str, date, date]] = []
        self.index_calls: list[tuple[str, date, date]] = []
        self.screen_calls: list[str] = []
        #: When set, index bars stop at this date (an upstream feed that has not
        #: published the newest session yet).
        self.index_bars_end: date | None = None
        self.fail_on: set[str] = set()
        self.fail_actions_on: set[str] = set()
        self.actions_by_ticker: dict[str, list[CorporateAction]] = {}
        self.ratios_by_ticker: dict[str, list[FinancialRatios]] = {}
        self.ratio_calls: list[str] = []

    def ssi_symbol_master(self) -> list[SymbolMaster]:
        return [
            SymbolMaster(
                ticker=ticker, exchange="HOSE", name=ticker, security_type="s",
                source="ssi_statistics",
            )
            for ticker in self.symbols
        ] + [
            SymbolMaster(
                ticker="ETF1", exchange="HOSE", name="ETF", security_type="f",
                source="ssi_statistics",
            ),
        ]

    def kbs_symbol_master(self) -> list[SymbolMaster]:
        return [
            SymbolMaster(ticker=ticker, exchange="HOSE", security_type="stock", source="kbs")
            for ticker in self.symbols
        ]

    def sectors(self) -> list[SectorMap]:
        return [
            SectorMap(
                ticker="VCB", exchange="HOSE", icb_level2_name="Banks",
                icb_level2_code="8300", source="ssi_statistics", as_of=AS_OF,
            ),
            SectorMap(
                ticker="FPT", exchange="HOSE", icb_level2_name="Software",
                icb_level2_code="9500", source="ssi_statistics", as_of=AS_OF,
            ),
        ]

    def index_members(self, code: str) -> IndexConstituents:
        members = self.vn30 if code == "VN30" else self.vn100
        return IndexConstituents(index=code, members=members, as_of=AS_OF, source="kbs")

    def index_bars(self, code: str, start: date, end: date) -> list[AdjustedOHLCV]:
        self.index_calls.append((code, start, end))
        end_date = min(end, self.index_bars_end) if self.index_bars_end is not None else end
        return _bars(start, end_date, base=1000.0)

    def stock_bars(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        self.bar_calls.append((symbol, start, end))
        if symbol in self.fail_on:
            raise NetworkError("boom", provider="ssi_statistics")
        return [bar for bar in self.bars_by_ticker.get(symbol, []) if start <= bar.date <= end]

    def screen_bars(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        self.screen_calls.append(symbol)
        return [bar for bar in self.bars_by_ticker.get(symbol, []) if start <= bar.date <= end]

    def company_profile(self, ticker: str) -> CompanyProfile:
        return CompanyProfile(
            ticker=ticker,
            shares_outstanding=1_000_000,
            market_cap=1_000_000_000_000.0,
            source="ssi_statistics",
        )

    def corporate_actions(
        self, ticker: str, start: date, end: date
    ) -> list[CorporateAction]:
        if ticker in self.fail_actions_on:
            raise NetworkError("actions boom", provider="ssi_statistics")
        return list(self.actions_by_ticker.get(ticker, []))

    def ratios(self, ticker: str) -> list[FinancialRatios]:
        self.ratio_calls.append(ticker)
        return list(self.ratios_by_ticker.get(ticker, []))

    def ratios_latest(self, ticker: str) -> list[FinancialRatios]:
        return self.ratios(ticker)

    def to_sources(self) -> PrecomputeSources:
        return PrecomputeSources(
            ssi_symbol_master=self.ssi_symbol_master,
            kbs_symbol_master=self.kbs_symbol_master,
            sectors=self.sectors,
            index_members=self.index_members,
            index_bars=self.index_bars,
            stock_bars=self.stock_bars,
            screen_bars=self.screen_bars,
            company_profile=self.company_profile,
            corporate_actions=self.corporate_actions,  # type: ignore[arg-type]
            ratios=self.ratios,
            ratios_latest=self.ratios_latest,
        )


@pytest.fixture
def factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_for(f"sqlite:///{tmp_path / 'v2.db'}")
    create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _service(
    factory: sessionmaker[Session], sources: PrecomputeSources, clock: _Clock
) -> V2PrecomputeService:
    settings = V2DataSettings(precompute_pre_screen_enabled=False)
    return V2PrecomputeService(
        session_factory=factory,
        sources=sources,
        settings=settings,
        now_provider=clock,
    )


def _fake(start: date = START) -> FakeSources:
    return FakeSources(
        bars_by_ticker={
            "VCB": _bars(start, AS_OF),
            "FPT": _bars(start, AS_OF),
            "XYZ": _bars(start, AS_OF),
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )


def _extend(fake: FakeSources, start: date, end: date) -> None:
    """Append continuous new bars so the quality checks see no artificial gap."""
    for bars in fake.bars_by_ticker.values():
        bars.extend(_bars(start, end, base=bars[-1].close + 1.0))


def _rebase(bars: list[AdjustedOHLCV], factor: float) -> list[AdjustedOHLCV]:
    """Return the series rescaled as SSI re-bases it after a corporate action.

    ``close`` is the adjusted close the pipeline compares and stores; ``close_raw``
    is scaled alongside it so the adjusted/raw ratio stays constant and the quality
    check does not flag an unrelated mismatch (the test isolates the overlap
    detection, not the adjustment-quality flag).
    """

    def _scale(value: float | None) -> float | None:
        return None if value is None else value * factor

    return [
        bar.model_copy(update={"close": bar.close * factor, "close_raw": _scale(bar.close_raw)})
        for bar in bars
    ]


def test_full_run_builds_every_dataset(factory: sessionmaker[Session]) -> None:
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    report = service.run(mode="full", start=START)

    assert report.ok, report
    steps = {step.name: step for step in report.steps}
    for name in ("ticker_master", "index_membership", "benchmarks", "prices", "liquidity"):
        assert steps[name].ok, steps[name]
    assert report.coverage.covered == 2  # VCB + FPT
    assert report.coverage.missing == 1  # XYZ has no sector
    assert report.coverage.missing_tickers == ["XYZ"]
    assert report.quality_errors == 0

    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.latest_price_date("VCB") == AS_OF
        assert store.get_sector("VCB").icb_level2_name == "Banks"  # type: ignore[union-attr]
        assert store.get_membership("VN30") == ["VCB"]
        assert store.get_membership("VN100") == ["FPT", "VCB"]
        market_cap = store.get_market_cap("VCB")
        assert market_cap is not None
        assert market_cap.market_cap == 1_000_000_000_000.0
        assert market_cap.basis == "full"
        liquidity = store.get_liquidity("VCB")
        assert liquidity is not None
        assert liquidity.volume_basis == "matched"
        assert liquidity.adv_median == 1000.0
        assert SqlIndexRepository(session).latest_date("VN100") == AS_OF

    snapshot = V2Reader(factory).snapshot("VCB", START, AS_OF)
    assert snapshot.sector == "Banks"
    assert snapshot.price_adjustment_basis == "ssi_adjusted"
    assert snapshot.market_cap == 1_000_000_000_000.0
    assert snapshot.returns

    coverage = sector_coverage(factory)
    assert coverage.covered == 2
    assert coverage.missing_tickers == ["XYZ"]


def test_incremental_second_run_fetches_only_new_dates(
    factory: sessionmaker[Session],
) -> None:
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=START).ok

    calls_after_full = list(fake.bar_calls)
    # A second run on the same day has nothing new to fetch.
    assert service.run(mode="incremental", start=START).ok
    assert fake.bar_calls == calls_after_full

    # Advance the clock and append new bars for every ticker.
    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer
    assert service.run(mode="incremental", start=START).ok
    new_calls = fake.bar_calls[len(calls_after_full) :]
    vcb_calls = [call for call in new_calls if call[0] == "VCB"]
    assert vcb_calls, "VCB should have been fetched for the new dates"
    # The incremental fetch reaches the new dates and overlaps the stored tail
    # (so a retroactive re-base can be detected); it never restarts before START.
    assert vcb_calls[-1][1] < date(2026, 1, 1)
    assert vcb_calls[-1][2] == newer
    assert all(call[1] >= START for call in vcb_calls)
    with session_scope(factory) as session:
        assert V2Store(session).latest_price_date("VCB") == newer


def test_incremental_rebase_with_new_action_refreshes_old_rows(
    factory: sessionmaker[Session],
) -> None:
    """SSI re-bases the whole adjusted series when an ex-date lands: old rows refresh."""
    early = date(2025, 6, 2)
    fake = _fake(early)
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=early).ok

    with session_scope(factory) as session:
        oldest = V2Store(session).get_prices("VCB", early)[0]
    assert oldest.date == early
    assert oldest.close == pytest.approx(100.0)
    fake.bar_calls.clear()

    # A new dividend ex-date lands and SSI re-bases every historical close.
    fake.actions_by_ticker["VCB"] = [
        CorporateAction(
            ticker="VCB",
            event_type="DIV",
            exright_date=date(2026, 1, 5),
            ratio=0.05,
            source="ssi_statistics",
        )
    ]
    fake.bars_by_ticker["VCB"] = _rebase(fake.bars_by_ticker["VCB"], 0.95)
    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer

    report = service.run(mode="incremental", start=early)
    assert report.ok, report

    with session_scope(factory) as session:
        after = V2Store(session).get_prices("VCB", early)
        assert V2Store(session).latest_price_date("VCB") == newer
    # The OLD row was replaced in this same run, not left at its stale value.
    assert after[0].date == early
    assert after[0].close == pytest.approx(95.0)
    # The tail overlap plus a full re-fetch: two calls for VCB.
    vcb_calls = [call for call in fake.bar_calls if call[0] == "VCB"]
    assert len(vcb_calls) == 2


def test_incremental_rebase_with_empty_actions_feed_refreshes_old_rows(
    factory: sessionmaker[Session],
) -> None:
    """HPG-like: the actions feed omits the issue, but the price overlap catches it."""
    early = date(2025, 6, 2)
    fake = _fake(early)
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=early).ok

    with session_scope(factory) as session:
        assert V2Store(session).get_prices("VCB", early)[0].close == pytest.approx(100.0)

    # No corporate action is published, yet the adjusted closes are re-based.
    fake.bars_by_ticker["VCB"] = _rebase(fake.bars_by_ticker["VCB"], 0.9)
    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer

    report = service.run(mode="incremental", start=early)
    assert report.ok, report

    with session_scope(factory) as session:
        after = V2Store(session).get_prices("VCB", early)
    assert after[0].close == pytest.approx(90.0)


def test_incremental_overlap_makes_no_extra_request_when_unchanged(
    factory: sessionmaker[Session],
) -> None:
    """No re-base: one overlap fetch per ticker, never a full re-fetch."""
    early = date(2025, 6, 2)
    fake = _fake(early)
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=early).ok

    fake.bar_calls.clear()
    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer

    report = service.run(mode="incremental", start=early)
    assert report.ok, report

    vcb_calls = [call for call in fake.bar_calls if call[0] == "VCB"]
    assert len(vcb_calls) == 1  # the tail overlap + new dates; no full re-fetch
    start_date, end_date = vcb_calls[0][1], vcb_calls[0][2]
    assert early < start_date < AS_OF  # a short overlap window, not the whole history
    assert end_date == newer
    with session_scope(factory) as session:
        assert V2Store(session).latest_price_date("VCB") == newer


def test_members_filter_restricts_the_price_backfill(
    factory: sessionmaker[Session],
) -> None:
    """``members`` prices only the index names; the master stays full-universe."""
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    report = service.run(mode="full", start=START, members="VN100")
    assert report.ok, report

    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.latest_price_date("VCB") == AS_OF
        assert store.latest_price_date("FPT") == AS_OF
        assert store.latest_price_date("XYZ") is None  # not a VN100 member
        assert {record.ticker for record in store.list_ticker_master()} == {
            "VCB",
            "FPT",
            "XYZ",
        }
        assert store.get_membership("VN100") == ["FPT", "VCB"]


def test_resume_after_a_chunked_run(factory: sessionmaker[Session]) -> None:
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    first = service.run(mode="full", start=START, limit=2)
    assert first.ok, first
    with session_scope(factory) as session:
        store = V2Store(session)
        # Alphabetical order: FPT and VCB were processed, XYZ was not.
        assert store.latest_price_date("FPT") == AS_OF
        assert store.latest_price_date("VCB") == AS_OF
        assert store.latest_price_date("XYZ") is None

    fake.bar_calls.clear()
    second = service.run(mode="incremental", start=START)
    assert second.ok, second
    # Only the unfinished ticker is fetched; the completed ones are up to date.
    assert {call[0] for call in fake.bar_calls} == {"XYZ"}
    with session_scope(factory) as session:
        assert V2Store(session).latest_price_date("XYZ") == AS_OF


def test_interrupted_backfill_resumes(factory: sessionmaker[Session]) -> None:
    fake = _fake()
    fake.fail_on = {"VCB"}
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    first = service.run(mode="full", start=START)
    assert not first.ok  # the VCB failure makes the prices step fail loudly
    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.latest_price_date("VCB") is None
        assert store.latest_price_date("FPT") == AS_OF
        progress = store.get_progress("prices", "VCB")
        assert progress is not None and progress.state == "failed"

    fake.fail_on.clear()
    fake.bar_calls.clear()
    second = service.run(mode="incremental", start=START)
    assert second.ok, second
    assert {call[0] for call in fake.bar_calls} == {"VCB"}
    with session_scope(factory) as session:
        assert V2Store(session).latest_price_date("VCB") == AS_OF


def test_vn30_not_subset_fails_loudly(factory: sessionmaker[Session]) -> None:
    fake = _fake()
    fake.vn30 = ["AAA"]  # AAA is not in VN100
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    report = service.run(mode="full", start=START)

    membership = next(step for step in report.steps if step.name == "index_membership")
    assert not membership.ok
    assert "not a subset of VN100" in (membership.message or "")
    assert not report.ok


def test_store_upserts_are_idempotent(factory: sessionmaker[Session]) -> None:
    record = TickerRecord(
        ticker="VCB", exchange="HOSE", source="ssi_statistics", data_as_of=AS_OF
    )
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master([record])
        store.upsert_ticker_master([record])
        assert len(store.list_ticker_master()) == 1

        store.replace_membership("VN30", ["VCB", "FPT"], as_of=AS_OF, source="kbs")
        store.replace_membership("VN30", ["VCB"], as_of=AS_OF, source="kbs")
        assert store.get_membership("VN30") == ["VCB"]

        store.set_progress(
            ProgressRecord(kind="prices", symbol="VCB", state="done", last_date=AS_OF)
        )
        store.set_progress(
            ProgressRecord(
                kind="prices", symbol="VCB", state="done", last_date=AS_OF, rows=5
            )
        )
        progress = store.get_progress("prices", "VCB")
        assert progress is not None and progress.rows == 5


def test_profile_keeps_market_cap_when_corporate_actions_fail(
    factory: sessionmaker[Session],
) -> None:
    """A corporate-action failure is a partial profile failure, not a lost market cap."""
    fake = _fake()
    fake.fail_actions_on = {"VCB"}
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    report = service.run(mode="full", start=START)

    profiles = next(step for step in report.steps if step.name == "profiles")
    assert "partial" in (profiles.message or "")
    with session_scope(factory) as session:
        store = V2Store(session)
        market_cap = store.get_market_cap("VCB")
        assert market_cap is not None
        assert market_cap.market_cap == 1_000_000_000_000.0
        progress = store.get_progress("profile", "VCB")
        assert progress is not None and progress.state == "partial"
        # FPT's corporate actions succeeded, so it is fully done.
        done = store.get_progress("profile", "FPT")
        assert done is not None and done.state == "done"


def _financial_ratios(ticker: str, *, roe: float = 15.0) -> list[FinancialRatios]:
    return [
        FinancialRatios(
            ticker=ticker,
            period=date(2025, 9, 30),
            period_type="ttm",
            provider="ssi_statistics",
            ratios={"roe": roe, "roa": 1.0, "npl": 0.7, "pe": 10.0, "pb": 1.5},
        )
    ]


def test_ratios_and_sector_statistics_steps(factory: sessionmaker[Session]) -> None:
    fake = _fake()
    fake.ratios_by_ticker = {
        "VCB": _financial_ratios("VCB", roe=15.0),
        "FPT": _financial_ratios("FPT", roe=25.0),
    }
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)

    report = service.run(mode="full", start=START)
    assert report.ok, report
    steps = {step.name: step for step in report.steps}
    assert steps["ratios"].ok
    assert steps["sector_statistics"].ok
    assert steps["ratio_quality"].ok

    with session_scope(factory) as session:
        store = V2Store(session)
        vcb = store.get_ratios("VCB")
        assert vcb and vcb[0].ratio_group == "banks"
        assert vcb[0].ratios["npl"] == pytest.approx(0.7)
        assert "grossProfitMargin" not in vcb[0].ratios  # trimmed to the bank set
        fpt = store.get_ratios("FPT")
        assert fpt and fpt[0].ratio_group == "general"
        assert "npl" not in fpt[0].ratios  # the general set has no npl
        banks_roe = next(
            s for s in store.list_sector_statistics()
            if s.ratio == "roe" and s.sector == "Banks"
        )
        assert banks_roe.n == 1
        assert banks_roe.median == pytest.approx(15.0)


def test_upsert_ratios_merges_duplicate_periods_in_one_batch(
    factory: sessionmaker[Session],
) -> None:
    """SSI repeated ``(symbol, period, period_type)`` for ``AAH``; Postgres rejects it.

    ``ON CONFLICT DO UPDATE`` cannot affect one row twice in a single statement
    (``psycopg.errors.CardinalityViolation``), so the store must collapse the
    duplicates before the upsert: one row survives and its ratio map keeps every
    non-null value from both copies.
    """
    period = date(2025, 9, 30)
    with session_scope(factory) as session:
        written = V2Store(session).upsert_ratios(
            [
                RatioRecord(
                    symbol="AAH",
                    period=period,
                    period_type="quarter",
                    ratio_group="general",
                    ratios={"roe": 8.0, "roa": 2.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                ),
                RatioRecord(
                    # The same key: the store upper-cases the symbol.
                    symbol="aah",
                    period=period,
                    period_type="quarter",
                    ratio_group="general",
                    ratios={"roe": 9.5, "pe": 12.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                ),
            ]
        )
    assert written == 1
    with session_scope(factory) as session:
        rows = V2Store(session).get_ratios("AAH")
    assert len(rows) == 1
    assert rows[0].ratios == {"roe": 9.5, "roa": 2.0, "pe": 12.0}


def test_ratio_quality_logs_capped_warnings_and_skips_unpriced(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    fake = _fake()
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))
    stale_period = AS_OF - timedelta(days=300)
    stale_tickers = [
        f"STALE{index:02d}" for index in range(RATIO_WARNING_LOG_LIMIT + 1)
    ]
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(ticker=t, exchange="HOSE", source="test", data_as_of=AS_OF)
                for t in ("PRICED", "GAP", "UNPRICED")
            ]
            + [
                TickerRecord(ticker=t, exchange="HOSE", source="test", data_as_of=AS_OF)
                for t in stale_tickers
            ]
        )
        store.upsert_prices(
            "PRICED", _bars(START, AS_OF), price_adjustment_basis="raw", data_as_of=AS_OF
        )
        store.upsert_prices(
            "GAP", _bars(START, AS_OF), price_adjustment_basis="raw", data_as_of=AS_OF
        )
        store.upsert_ratios(
            [
                RatioRecord(
                    symbol="PRICED",
                    period=AS_OF,
                    period_type="ttm",
                    ratio_group="general",
                    ratios={"roe": 15.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                )
            ]
            + [
                RatioRecord(
                    symbol=t,
                    period=stale_period,
                    period_type="ttm",
                    ratio_group="general",
                    ratios={"roe": 15.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                )
                for t in stale_tickers
            ]
        )
    with caplog.at_level(logging.INFO, logger="data.v2.precompute"):
        step = service._run_ratio_quality(AS_OF)
    assert step.ok
    text = caplog.text
    # Priced-without-ratios is a real gap and is logged per ticker.
    assert "GAP ratios no_ratios" in text
    # Unpriced tickers never get a per-ticker no-ratios warning.
    assert "UNPRICED ratios no_ratios" not in text
    assert "1 tickers without prices have no ratios" in text
    # The 31 stale findings are capped at RATIO_WARNING_LOG_LIMIT with a count.
    assert "more ratio warnings not listed" in text
    listed = [message for message in caplog.messages if "ratios stale_period" in message]
    assert len(listed) == RATIO_WARNING_LOG_LIMIT
    assert step.message is not None
    assert "32 warnings" in step.message
    assert "1 priced tickers without ratios" in step.message


def test_incremental_ratio_refresh_is_skipped_on_the_same_day(
    factory: sessionmaker[Session],
) -> None:
    fake = _fake()
    fake.ratios_by_ticker = {"VCB": _financial_ratios("VCB")}
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=START).ok

    fake.ratio_calls.clear()
    assert service.run(mode="incremental", start=START).ok
    assert fake.ratio_calls == []  # already refreshed on the target date


def test_unpriced_run_reports_a_dataset_lag_instead_of_failing(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    """A backfill that cannot refresh the priced tickers warns about the lag, not fails.

    Run #9 (2026-11-25) priced PVI while SSI still had no bar for that session and the
    run failed `quality: stale dataset`; the work was correct, the gate was out of scope
    for an --unpriced chunk.
    """
    previous = AS_OF - timedelta(days=1)
    fake = FakeSources(
        bars_by_ticker={
            ticker: _bars(START, previous) for ticker in ("VCB", "FPT", "XYZ")
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )
    # The benchmark has the target session; the price feed does not (the real SSI lag).
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))
    service.run(mode="full", start=START, limit=1)  # prices one ticker only

    fake.bar_calls.clear()
    with caplog.at_level(logging.WARNING, logger="data.v2.precompute"):
        report = service.run(mode="full", start=START, as_of=AS_OF, only_unpriced=True)

    assert report.ok, report
    assert report.quality_errors == 0
    assert "has not published that session yet" in caplog.text
    assert "does not refresh the priced tickers" in caplog.text


def test_limit_prioritizes_index_members_and_spends_it_after_the_prescreen(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    """A VN100 member beats an alphabetically earlier name, and a rejected symbol costs no slot."""
    fake = FakeSources(
        bars_by_ticker={
            # AAA sorts first but never trades: the pre-screen drops it.
            "AAA": _volume(_bars(START, AS_OF), 0),
            "BBB": _bars(START, AS_OF),  # a VN100 member, still unpriced
            "CCC": _bars(START, AS_OF),  # an ordinary unpriced stock
        },
        vn30=["BBB"],
        vn100=["BBB"],
        symbols=["AAA", "BBB", "CCC"],
    )
    service = V2PrecomputeService(
        session_factory=factory,
        sources=fake.to_sources(),
        settings=V2DataSettings(
            precompute_pre_screen_enabled=True,
            precompute_pre_screen_min_median_volume=500,
        ),
        now_provider=_Clock(AS_OF),
    )

    with caplog.at_level(logging.INFO, logger="data.v2.precompute"):
        first = service.run(mode="full", start=START, limit=1)
    assert first.ok, first
    # The index member wins over the alphabetically earlier AAA, and the budget is
    # spent on it: nothing else is even screened.
    assert [call[0] for call in fake.bar_calls] == ["BBB"]
    assert fake.screen_calls == ["BBB"]

    fake.bar_calls.clear()
    fake.screen_calls.clear()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="data.v2.precompute"):
        second = service.run(mode="full", start=START, limit=1)
    assert second.ok, second
    # AAA is screened and rejected without consuming the slot, so CCC takes it.
    assert fake.screen_calls == ["AAA", "CCC"]
    assert [call[0] for call in fake.bar_calls] == ["CCC"]
    # The rejection is reported, so an unpriced ticker can always be explained.
    assert "pre-screen rejected" in caplog.text
    assert "AAA" in caplog.text
    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.latest_price_date("BBB") == AS_OF
        assert store.latest_price_date("CCC") == AS_OF
        assert store.latest_price_date("AAA") is None


def test_unsettled_benchmark_falls_back_to_the_last_published_session(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    """A daytime run retargets itself instead of failing stale benchmark/dataset."""
    previous = AS_OF - timedelta(days=1)
    fake = FakeSources(
        bars_by_ticker={
            ticker: _bars(START, previous) for ticker in ("VCB", "FPT", "XYZ")
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )
    fake.index_bars_end = previous  # VNINDEX has not published AS_OF yet
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))

    with caplog.at_level(logging.WARNING, logger="data.v2.precompute"):
        report = service.run(mode="full", start=START)

    assert report.ok, report
    assert report.as_of == previous
    assert report.quality_errors == 0
    assert "as-of fallback" in caplog.text
    assert "VNINDEX has no bar" in caplog.text


def test_explicit_as_of_keeps_the_strict_quality_errors(
    factory: sessionmaker[Session],
) -> None:
    """An explicit ``--as-of`` never falls back: a stale dataset still fails loudly."""
    previous = AS_OF - timedelta(days=1)
    fake = FakeSources(
        bars_by_ticker={
            ticker: _bars(START, previous) for ticker in ("VCB", "FPT", "XYZ")
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )
    fake.index_bars_end = previous
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))

    report = service.run(mode="full", start=START, as_of=AS_OF)

    assert report.as_of == AS_OF
    assert report.quality_errors == 2  # stale benchmark + stale dataset
    assert not report.ok
    quality = next(step for step in report.steps if step.name == "quality")
    assert not quality.ok


def test_backfill_prints_live_progress_lines(
    factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    """Each per-ticker loop prints one line, so a long job is not silent."""
    fake = _fake()
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))

    assert service.run(mode="full", start=START).ok

    out = capsys.readouterr().out
    assert "[prices] 3/3" in out
    assert "[ratios] 3/3" in out


def test_set_progress_keeps_rows_and_refreshes_updated_at(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero count never blanks history, but the checkpoint still moves forward."""
    first = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    second = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
    with session_scope(factory) as session:
        store = V2Store(session)
        monkeypatch.setattr("data.v2.store.utcnow", lambda: first)
        store.set_progress(
            ProgressRecord(
                kind="prices", symbol="VCB", state="done", last_date=START, rows=240
            )
        )
        # An incremental fetch with no new bar reports zero rows for the same ticker.
        monkeypatch.setattr("data.v2.store.utcnow", lambda: second)
        store.set_progress(
            ProgressRecord(kind="prices", symbol="VCB", state="done", last_date=AS_OF)
        )
    with session_scope(factory) as session:
        progress = V2Store(session).get_progress("prices", "VCB")
        updated_at = session.scalar(
            select(V2Progress.updated_at).where(
                V2Progress.kind == "prices", V2Progress.symbol == "VCB"
            )
        )
    assert progress is not None
    assert progress.rows == 240  # the historical count survives
    assert progress.state == "done"
    assert progress.last_date == AS_OF  # the newer checkpoint still lands
    assert updated_at is not None
    assert updated_at.replace(tzinfo=None) == second.replace(tzinfo=None)


def test_incremental_run_keeps_the_historical_row_count(
    factory: sessionmaker[Session],
) -> None:
    """A ticker whose feed ends before the target keeps its stored count."""
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    assert service.run(mode="full", start=START).ok

    with session_scope(factory) as session:
        progress = V2Store(session).get_progress("prices", "VCB")
    assert progress is not None and progress.rows > 0
    stored_rows = progress.rows

    # The clock moves on but VCB's feed still ends at AS_OF (a suspension): the
    # incremental fetch returns only the already-stored overlap, so no new bar.
    clock.today = AS_OF + timedelta(days=7)
    fake.bar_calls.clear()
    service.run(mode="incremental", start=START)
    assert "VCB" in {call[0] for call in fake.bar_calls}  # still polled: it is priced

    with session_scope(factory) as session:
        after = V2Store(session).get_progress("prices", "VCB")
    assert after is not None
    assert after.rows == stored_rows
    assert after.state == "done"


def test_incremental_skips_known_empty_symbols(factory: sessionmaker[Session]) -> None:
    """A symbol that never trades is re-checked by a full run, not every day."""
    fake = _fake()
    fake.bars_by_ticker.pop("XYZ")  # XYZ never prints: the price feed is empty
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    first = service.run(mode="full", start=START)
    assert next(step for step in first.steps if step.name == "prices").ok
    with session_scope(factory) as session:
        progress = V2Store(session).get_progress("prices", "XYZ")
    assert progress is not None
    assert progress.state == "done" and progress.rows == 0

    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer
    fake.bar_calls.clear()
    incremental = service.run(mode="incremental", start=START)
    assert next(step for step in incremental.steps if step.name == "prices").ok
    called = {call[0] for call in fake.bar_calls}
    assert "XYZ" not in called  # no daily polling of a known-empty symbol
    assert "VCB" in called  # the priced names keep updating

    fake.bar_calls.clear()
    service.run(mode="incremental", start=START, profiles=True)
    assert "XYZ" in {call[0] for call in fake.bar_calls}  # --profiles re-checks it

    fake.bar_calls.clear()
    service.run(mode="full", start=START)
    assert "XYZ" in {call[0] for call in fake.bar_calls}  # so does a full refresh


def test_limit_updates_tracked_tickers_before_new_ones(
    factory: sessionmaker[Session],
) -> None:
    """``--limit`` spends its slots on the stocks that already have prices."""
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    # Price only VCB (the sole VN30 member in the fixture); FPT and XYZ stay new.
    assert service.run(mode="full", start=START, members="VN30").ok

    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer
    fake.bar_calls.clear()

    report = service.run(mode="incremental", start=START, limit=1)
    assert report.ok, report
    # Alphabetical order would fetch FPT first; the already-tracked VCB wins.
    assert {call[0] for call in fake.bar_calls} == {"VCB"}


def test_pre_close_run_targets_the_last_completed_session(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    """A 10:02 ICT run after a market holiday does not chase today's session.

    The observed failure: a 2026-11-25 dispatch before the close, with 2026-11-24 a
    holiday, asked for the 2026-11-25 session and failed
    ``quality: stale dataset, latest price bar 2026-11-23``.
    """
    holiday = date(2026, 11, 24)
    last_session = date(2026, 11, 23)
    first = date(2026, 8, 3)
    fake = FakeSources(
        bars_by_ticker={
            ticker: _bars(first, last_session) for ticker in ("VCB", "FPT", "XYZ")
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )
    fake.index_bars_end = last_session  # the holiday session has no bar
    rules = replace(DEFAULT_MARKET_RULES, trading_holidays=frozenset({holiday}))
    service = V2PrecomputeService(
        session_factory=factory,
        sources=fake.to_sources(),
        settings=V2DataSettings(precompute_pre_screen_enabled=False),
        now_provider=_Clock(date(2026, 11, 25), hour_ict=10),
        rules=rules,
    )

    with caplog.at_level(logging.WARNING, logger="data.v2.precompute"):
        report = service.run(mode="full", start=first)

    assert report.ok, report
    assert report.as_of == last_session
    assert report.quality_errors == 0, caplog.text
    # No request ever asks for a session the exchange has not completed.
    assert all(call[2] <= last_session for call in fake.bar_calls)
    assert all(call[2] <= last_session for call in fake.index_calls)


def test_staleness_tolerance_excuses_a_known_one_session_lag(
    factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    """A one-session provider lag fails strictly and passes with a tolerance of 1."""
    previous = AS_OF - timedelta(days=1)
    fake = FakeSources(
        bars_by_ticker={
            ticker: _bars(START, previous) for ticker in ("VCB", "FPT", "XYZ")
        },
        vn30=["VCB"],
        vn100=["VCB", "FPT"],
    )
    fake.index_bars_end = previous

    strict = _service(factory, fake.to_sources(), _Clock(AS_OF))
    strict_report = strict.run(mode="full", start=START, as_of=AS_OF)
    assert strict_report.quality_errors == 2  # stale benchmark + stale dataset
    assert not strict_report.ok

    tolerant = V2PrecomputeService(
        session_factory=factory,
        sources=fake.to_sources(),
        settings=V2DataSettings(
            precompute_pre_screen_enabled=False,
            precompute_staleness_tolerance_sessions=1,
        ),
        now_provider=_Clock(AS_OF),
    )
    with caplog.at_level(logging.WARNING, logger="data.v2.precompute"):
        report = tolerant.run(mode="full", start=START, as_of=AS_OF)

    assert report.ok, report
    assert report.as_of == AS_OF
    assert report.quality_errors == 0
    assert "within the 1-session tolerance" in caplog.text


def test_unpriced_run_finishes_the_tail_without_refetching_priced_tickers(
    factory: sessionmaker[Session],
) -> None:
    """``only_unpriced`` spends every ``limit`` slot on a ticker that has no bars."""
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    # Price only VCB (the sole VN30 member); FPT and XYZ stay unpriced.
    assert service.run(mode="full", start=START, members="VN30").ok

    newer = date(2026, 1, 6)
    _extend(fake, date(2026, 1, 1), newer)
    clock.today = newer
    fake.bar_calls.clear()

    report = service.run(mode="full", start=START, limit=1, only_unpriced=True)

    assert report.ok, report
    # VCB already has bars, so the single slot goes to the first unpriced name (FPT
    # is a VN100 member, ahead of XYZ) and the priced ticker is never re-fetched.
    assert {call[0] for call in fake.bar_calls} == {"FPT"}
    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.latest_price_date("FPT") == newer
        assert store.latest_price_date("XYZ") is None




def test_upsert_prices_collapses_duplicate_dates(
    factory: sessionmaker[Session],
) -> None:
    """A repeated ``(symbol, date)`` in one batch must not raise CardinalityViolation.

    ``ON CONFLICT DO UPDATE`` cannot name the same row twice in one statement, so the
    store must collapse duplicate conflict keys before the upsert: one row survives and
    the last value wins.
    """
    day = date(2025, 11, 25)
    with session_scope(factory) as session:
        store = V2Store(session)
        written = store.upsert_prices(
            "VHM",
            [
                AdjustedOHLCV(
                    date=day,
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                    close_raw=100.0,
                    volume=1_000,
                    source="ssi_statistics",
                ),
                # The same (symbol, date): a provider duplicated the row.
                AdjustedOHLCV(
                    date=day,
                    open=101.0,
                    high=101.0,
                    low=101.0,
                    close=101.0,
                    close_raw=101.0,
                    volume=2_000,
                    source="ssi_statistics",
                ),
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=day,
        )
        bars = store.get_prices("VHM")
    assert written == 1
    assert len(bars) == 1
    assert bars[0].close == pytest.approx(101.0)  # the last copy wins


def test_price_upsert_failure_is_contained_to_one_ticker(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DB error on one ticker is recorded and never aborts the remaining tickers.

    Background: an undeduplicated batch raised ``CardinalityViolation`` inside
    ``upsert_prices`` and aborted the whole ``_backfill_prices`` loop, leaving every
    later ticker un-updated. The per-ticker guard records the failure and continues.
    """
    fake = _fake()
    clock = _Clock(AS_OF)
    service = _service(factory, fake.to_sources(), clock)
    tickers = [
        TickerRecord(ticker=code, exchange="HOSE", source="test", data_as_of=AS_OF)
        for code in ("VCB", "FPT", "XYZ")
    ]
    original = V2Store.upsert_prices

    def flaky(self, symbol, bars, **kwargs):
        if symbol.upper() == "FPT":
            raise RuntimeError("simulated batch upsert failure")
        return original(self, symbol, bars, **kwargs)

    monkeypatch.setattr(V2Store, "upsert_prices", flaky)

    step = service._backfill_prices(
        AS_OF, mode="full", start=START, limit=None, universe=tickers
    )

    assert step.ok is False
    assert "1 failed" in (step.message or "")
    with session_scope(factory) as session:
        store = V2Store(session)
        progress = store.get_progress("prices", "FPT")
        assert progress is not None and progress.state == "failed"
        # The failing ticker stored nothing and was left for the next run ...
        assert store.latest_price_date("FPT") is None
        # ... while the other tickers still wrote their bars.
        assert store.latest_price_date("VCB") == AS_OF
        assert store.latest_price_date("XYZ") == AS_OF



def test_latest_price_dates_reports_one_row_per_ticker(
    factory: sessionmaker[Session],
) -> None:
    """The batch staleness lookup returns the newest bar date for every ticker."""
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_prices(
            "AAA",
            _bars(START, START + timedelta(days=2)),
            price_adjustment_basis="raw",
            data_as_of=AS_OF,
        )
        store.upsert_prices(
            "BBB",
            _bars(START, START + timedelta(days=5)),
            price_adjustment_basis="raw",
            data_as_of=AS_OF,
        )
        latest = store.latest_price_dates()
    assert set(latest) == {"AAA", "BBB"}
    assert latest["AAA"] < latest["BBB"]


def test_select_candidates_prefers_the_most_stale_ticker(
    factory: sessionmaker[Session],
) -> None:
    """A limited run refreshes the oldest bar first, not the alphabetical head.

    The observed bug: a ticker could sit at 2026-11-23 for days because a ``--limit``
    run spent its slots on the alphabetical tracked head. The pending set is now
    ordered most-stale-first, so a name that fell behind is fixed on the next run.
    """
    fake = _fake()
    service = _service(factory, fake.to_sources(), _Clock(AS_OF))
    older = AS_OF - timedelta(days=5)
    newer = AS_OF - timedelta(days=2)
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_prices(
            "VCB", _bars(START, older), price_adjustment_basis="raw", data_as_of=older
        )
        store.upsert_prices(
            "FPT", _bars(START, newer), price_adjustment_basis="raw", data_as_of=newer
        )

    # FPT sorts first alphabetically and is only two sessions behind; VCB is five
    # sessions behind and must win the single slot.
    selected = service._select_candidates(
        ["FPT", "VCB"], target=AS_OF, mode="incremental", limit=1
    )

    assert selected == ["VCB"]


def test_already_priced_tickers_bypass_pre_screen_even_if_volume_dips(
    factory: sessionmaker[Session],
) -> None:
    """An already-priced ticker must be updated without calling screen_bars."""
    yesterday = AS_OF - timedelta(days=1)
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_prices(
            "VCB",
            _bars(START, yesterday),
            price_adjustment_basis="ssi_adjusted",
            data_as_of=yesterday,
        )
        store.set_progress(
            ProgressRecord(kind="prices", symbol="VCB", state="done", last_date=yesterday, rows=22)
        )

    fake = FakeSources(
        bars_by_ticker={"VCB": _volume(_bars(START, AS_OF), 10)},
        vn30=["VCB"],
        vn100=["VCB"],
        symbols=["VCB"],
    )
    service = V2PrecomputeService(
        session_factory=factory,
        sources=fake.to_sources(),
        settings=V2DataSettings(
            precompute_pre_screen_enabled=True,
            precompute_pre_screen_min_median_volume=500,
        ),
        now_provider=_Clock(AS_OF),
    )

    report = service.run(mode="incremental", start=START, as_of=AS_OF)

    assert report.ok, report
    assert fake.screen_calls == []
    with session_scope(factory) as session:
        assert V2Store(session).latest_price_date("VCB") == AS_OF


def test_prescreen_rejections_are_persisted_and_skipped_during_cooldown(
    factory: sessionmaker[Session],
) -> None:
    """Rejected unpriced tickers persist state='pre_screen_rejected' and respect cooldown."""
    fake = FakeSources(
        bars_by_ticker={
            "AAA": _volume(_bars(START, AS_OF), 0),
            "VCB": _bars(START, AS_OF),
        },
        vn30=["VCB"],
        vn100=["VCB"],
        symbols=["AAA", "VCB"],
    )
    clock = _Clock(AS_OF)
    service = V2PrecomputeService(
        session_factory=factory,
        sources=fake.to_sources(),
        settings=V2DataSettings(
            precompute_pre_screen_enabled=True,
            precompute_pre_screen_min_median_volume=500,
        ),
        now_provider=clock,
    )

    # Run 1: AAA has 0 volume -> screened once, rejected, persisted as pre_screen_rejected.
    first = service.run(mode="incremental", start=START, limit=10, as_of=AS_OF)
    assert first.ok, first
    assert "AAA" in fake.screen_calls
    with session_scope(factory) as session:
        checkpoint = V2Store(session).get_progress("prices", "AAA")
        assert checkpoint is not None
        assert checkpoint.state == "pre_screen_rejected"
        assert checkpoint.last_date == AS_OF

    # Run 2: next trading day, within 30d cooldown -> AAA is skipped without screen_bars call.
    day2 = date(2026, 1, 1)
    fake.bars_by_ticker["VCB"] = _bars(START, day2)
    fake.bars_by_ticker["AAA"] = _volume(_bars(START, day2), 0)
    clock.today = day2
    fake.screen_calls.clear()
    second = service.run(mode="incremental", start=START, limit=10, as_of=day2)
    assert second.ok, second
    assert fake.screen_calls == []

    # Run 3: profiles=True forces re-screening of rejected tickers.
    third = service.run(mode="incremental", start=START, limit=10, profiles=True, as_of=day2)
    assert third.ok, third
    assert "AAA" in fake.screen_calls

    # Run 4: after 30d cooldown expires, incremental run re-screens AAA.
    day33 = AS_OF + timedelta(days=33)  # 2026-02-02 (Monday)
    fake.bars_by_ticker["VCB"] = _bars(START, day33)
    fake.bars_by_ticker["AAA"] = _volume(_bars(START, day33), 0)
    clock.today = day33
    fake.screen_calls.clear()
    fourth = service.run(mode="incremental", start=START, limit=10, as_of=day33)
    assert fourth.ok, fourth
    assert "AAA" in fake.screen_calls


def test_incremental_rebase_overlap_fits_in_single_ssi_page() -> None:
    """Default overlap (10 sessions -> 20 calendar days) stays well below SSI's 40-row page size."""
    settings = V2DataSettings()
    assert settings.precompute_rebase_overlap_sessions == 10
    assert settings.precompute_pre_screen_cooldown_days == 30
    assert settings.precompute_ratios_refresh_days == 7
    assert settings.precompute_concurrency == 3


def test_set_progress_many_preserves_nonzero_rows_and_upserts_in_bulk(
    factory: sessionmaker[Session],
) -> None:
    """Bulk progress upsert writes rows together and keeps historical row counts."""
    with session_scope(factory) as session:
        store = V2Store(session)
        store.set_progress(
            ProgressRecord(kind="prices", symbol="VCB", state="done", last_date=AS_OF, rows=500)
        )
        written = store.set_progress_many(
            [
                ProgressRecord(
                    kind="prices", symbol="VCB", state="up_to_date", last_date=AS_OF, rows=0
                ),
                ProgressRecord(
                    kind="prices",
                    symbol="AAA",
                    state="pre_screen_rejected",
                    last_date=AS_OF,
                    rows=0,
                ),
            ]
        )
        assert written == 2
        vcb = store.get_progress("prices", "VCB")
        aaa = store.get_progress("prices", "AAA")
    assert vcb is not None and vcb.rows == 500 and vcb.state == "up_to_date"
    assert aaa is not None and aaa.state == "pre_screen_rejected" and aaa.last_date == AS_OF


