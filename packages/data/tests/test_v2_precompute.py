"""Resumable, incremental V2 precompute pipeline over fake sources."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
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


class _Clock:
    """A mutable today provider so a test can advance time."""

    def __init__(self, today: date) -> None:
        self.today = today

    def __call__(self) -> date:
        return self.today


class FakeSources:
    """Scripted fetchers with call recording and an injectable failure set."""

    def __init__(
        self,
        *,
        bars_by_ticker: dict[str, list[AdjustedOHLCV]],
        vn30: list[str],
        vn100: list[str],
    ) -> None:
        self.bars_by_ticker = bars_by_ticker
        self.vn30 = vn30
        self.vn100 = vn100
        self.bar_calls: list[tuple[str, date, date]] = []
        self.index_calls: list[tuple[str, date, date]] = []
        self.fail_on: set[str] = set()
        self.fail_actions_on: set[str] = set()
        self.actions_by_ticker: dict[str, list[CorporateAction]] = {}
        self.ratios_by_ticker: dict[str, list[FinancialRatios]] = {}
        self.ratio_calls: list[str] = []

    def ssi_symbol_master(self) -> list[SymbolMaster]:
        return [
            SymbolMaster(
                ticker="VCB", exchange="HOSE", name="VCB", security_type="s",
                source="ssi_statistics",
            ),
            SymbolMaster(
                ticker="FPT", exchange="HOSE", name="FPT", security_type="s",
                source="ssi_statistics",
            ),
            SymbolMaster(
                ticker="XYZ", exchange="HOSE", name="XYZ", security_type="s",
                source="ssi_statistics",
            ),
            SymbolMaster(
                ticker="ETF1", exchange="HOSE", name="ETF", security_type="f",
                source="ssi_statistics",
            ),
        ]

    def kbs_symbol_master(self) -> list[SymbolMaster]:
        return [
            SymbolMaster(ticker=ticker, exchange="HOSE", security_type="stock", source="kbs")
            for ticker in ("VCB", "FPT", "XYZ")
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
        return _bars(start, end, base=1000.0)

    def stock_bars(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        self.bar_calls.append((symbol, start, end))
        if symbol in self.fail_on:
            raise NetworkError("boom", provider="ssi_statistics")
        return [bar for bar in self.bars_by_ticker.get(symbol, []) if start <= bar.date <= end]

    def screen_bars(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
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
        today_provider=clock,
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
