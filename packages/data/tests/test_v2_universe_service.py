"""The /v2/universe and /v2/sectors helpers and their ``filter_universe`` parity."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import (
    create_all,
    create_engine_for,
    create_session_factory,
    session_scope,
)
from data.v2.analytics.liquidity import UniverseFilterSpec, filter_universe
from data.v2.analytics.universe_reader import load_universe_snapshot
from data.v2.analytics.universe_service import UniverseFilterRequest, UniverseService
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    TickerRecord,
)
from data.v2.schemas import AdjustedOHLCV, SectorMap
from data.v2.store import V2Store

_AS_OF = date(2024, 6, 28)


def _weekdays(count: int) -> list[date]:
    days: list[date] = []
    cursor = date(2024, 1, 2)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(count: int) -> list[AdjustedOHLCV]:
    return [
        AdjustedOHLCV(
            date=day,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            close_raw=100.0,
            volume=1_000_000,
            source="test",
        )
        for day in _weekdays(count)
    ]


def _seed(tmp_path: Path, *, with_flags: bool = False) -> sessionmaker[Session]:
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'universe.db').as_posix()}")
    create_all(engine)
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(ticker="BANK1", exchange="HOSE", source="test", data_as_of=_AS_OF),
                TickerRecord(ticker="BANK2", exchange="HOSE", source="test", data_as_of=_AS_OF),
                TickerRecord(ticker="TECH1", exchange="HOSE", source="test", data_as_of=_AS_OF),
                TickerRecord(ticker="ILLIQ", exchange="HOSE", source="test", data_as_of=_AS_OF),
            ]
        )
        store.upsert_sectors(
            [
                SectorMap(
                    ticker="BANK1",
                    exchange="HOSE",
                    icb_level2_name="Banks",
                    source="test",
                    as_of=_AS_OF,
                ),
                SectorMap(
                    ticker="BANK2",
                    exchange="HOSE",
                    icb_level2_name="Banks",
                    source="test",
                    as_of=_AS_OF,
                ),
                SectorMap(
                    ticker="TECH1",
                    exchange="HOSE",
                    icb_level2_name="Technology",
                    source="test",
                    as_of=_AS_OF,
                ),
            ]
        )
        store.replace_membership("VN30", ["BANK1"], as_of=_AS_OF, source="test")
        store.replace_membership("VN100", ["BANK1", "BANK2", "TECH1"], as_of=_AS_OF, source="test")
        for ticker, adtv in (
            ("BANK1", 20e9),
            ("BANK2", 20e9),
            ("TECH1", 20e9),
            ("ILLIQ", 1e9),
        ):
            store.upsert_prices(
                ticker, _bars(60), price_adjustment_basis="ssi_adjusted", data_as_of=_AS_OF
            )
            store.upsert_liquidity(
                LiquidityRecord(
                    symbol=ticker,
                    as_of=_AS_OF,
                    adtv_median=adtv,
                    adv_median=200_000.0 if adtv > 1e9 else 1_000.0,
                    window=20,
                    volume_basis="matched",
                    source="test",
                    data_as_of=_AS_OF,
                )
            )
            store.upsert_market_cap(
                MarketCapRecord(
                    symbol=ticker,
                    as_of=_AS_OF,
                    shares_outstanding=100_000_000,
                    market_cap=2_000e9,
                    basis="full",
                    source="test",
                    data_as_of=_AS_OF,
                )
            )
        if with_flags:
            store.upsert_adjustment_flags(
                [
                    AdjustmentFlagRecord(
                        ticker="BANK2",
                        severity="warning",
                        flagged=True,
                        exclude_from_group_indices=True,
                        reasons=["unexplained: test"],
                        dates=[date(2024, 4, 1)],
                        source="test",
                        data_as_of=_AS_OF,
                    )
                ]
            )
    return factory


def test_filter_matches_filter_universe_for_the_same_settings(tmp_path: Path) -> None:
    factory = _seed(tmp_path)
    response = UniverseService(factory).filter(
        UniverseFilterRequest(
            preset="standard_retail", sectors=["Banks"], indexes=["VN30"]
        )
    )
    snapshot = load_universe_snapshot(factory)
    expected = filter_universe(
        snapshot.rows,
        "standard_retail",
        UniverseFilterSpec(sectors=frozenset({"Banks"}), indexes=frozenset({"VN30"})),
        as_of=snapshot.latest_price_date,
    )
    assert [ticker.ticker for ticker in response.kept] == [
        row.ticker for row in expected.kept
    ]
    assert [ticker.ticker for ticker in response.rejected] == [
        row.ticker for row, _ in expected.rejected
    ]
    assert response.data_as_of == snapshot.latest_price_date


def test_an_empty_database_reports_v2_data_not_available(tmp_path: Path) -> None:
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    create_all(engine)
    service = UniverseService(create_session_factory(engine))
    universe = service.filter(UniverseFilterRequest())
    assert universe.available is False
    assert any("V2 data not available" in warning for warning in universe.warnings)
    sectors = service.sectors()
    assert sectors.available is False
    assert any("V2 data not available" in warning for warning in sectors.warnings)


def test_sectors_report_total_and_passing_counts(tmp_path: Path) -> None:
    response = UniverseService(_seed(tmp_path)).sectors("standard_retail")
    by_name = {sector.name: sector for sector in response.sectors}
    assert by_name["Banks"].total == 2
    assert by_name["Banks"].passing == 2
    assert by_name["Technology"].total == 1
    assert by_name["Technology"].passing == 1
    assert response.total_without_sector == 1  # ILLIQ has no sector


def test_an_unknown_sector_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        UniverseService(_seed(tmp_path)).filter(UniverseFilterRequest(sectors=["Nope"]))


def test_an_unknown_index_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        UniverseService(_seed(tmp_path)).filter(UniverseFilterRequest(indexes=["VN500"]))


def test_flags_not_computed_is_distinguishable_from_no_flags(tmp_path: Path) -> None:
    response = UniverseService(_seed(tmp_path, with_flags=False)).filter(
        UniverseFilterRequest()
    )
    assert response.flags_available is False
    assert any("not been computed" in warning for warning in response.warnings)


def test_flags_available_when_the_job_has_computed_them(tmp_path: Path) -> None:
    response = UniverseService(_seed(tmp_path, with_flags=True)).filter(
        UniverseFilterRequest()
    )
    assert response.flags_available is True
    assert any(flag.ticker == "BANK2" for flag in response.adjustment_flags)
    # GET /v2/universe omits heavy anomalies payload while keeping ticker/reasons.
    bank2 = next(flag for flag in response.adjustment_flags if flag.ticker == "BANK2")
    assert bank2.anomalies == []


def test_slim_prices_and_filtered_adjustment_flags(tmp_path: Path) -> None:
    from data.v2.precompute_schemas import AdjustmentAnomalyRecord

    factory = _seed(tmp_path, with_flags=False)
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_adjustment_flags(
            [
                AdjustmentFlagRecord(
                    ticker="BANK1",
                    severity="warning",
                    flagged=True,
                    exclude_from_group_indices=False,
                    reasons=["thin trading"],
                    dates=[_AS_OF],
                    anomalies=[
                        AdjustmentAnomalyRecord(
                            date=_AS_OF,
                            exclude=False,
                            category="thin_trading",
                            reason="thin trading",
                        )
                    ],
                    source="test",
                    data_as_of=_AS_OF,
                ),
                AdjustmentFlagRecord(
                    ticker="BANK2",
                    severity="warning",
                    flagged=True,
                    exclude_from_group_indices=True,
                    reasons=["unadjusted split"],
                    dates=[_AS_OF],
                    anomalies=[
                        AdjustmentAnomalyRecord(
                            date=_AS_OF,
                            exclude=True,
                            category="data_glitch",
                            reason="unadjusted split",
                        )
                    ],
                    source="test",
                    data_as_of=_AS_OF,
                ),
            ]
        )

        slim = store.get_prices_slim_batch(["BANK1"], include_volume=False)
        assert len(slim["BANK1"]) == 60
        assert slim["BANK1"][0].close == 100.0
        assert slim["BANK1"][0].volume == 0

        with_vol = store.get_prices_slim_batch(["BANK1"], include_volume=True)
        assert with_vol["BANK1"][0].volume == 1_000_000

        no_anomalies = {
            f.ticker: f for f in store.list_adjustment_flags(include_anomalies=False)
        }
        assert no_anomalies["BANK1"].anomalies == []
        assert no_anomalies["BANK2"].anomalies == []

        excl_only = {
            f.ticker: f
            for f in store.list_adjustment_flags(anomalies_for_excluded_only=True)
        }
        assert excl_only["BANK1"].anomalies == []
        assert len(excl_only["BANK2"].anomalies) == 1

