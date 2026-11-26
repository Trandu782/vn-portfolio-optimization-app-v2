"""End-to-end analytics payload built from the stored V2 tables."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.repositories import SqlIndexRepository
from data.models import PriceBar
from data.v2.adjustment_quality import adjustment_quality_flag
from data.v2.analytics.cache import clear_analytics_cache
from data.v2.analytics.service import AnalyticsRequest, AnalyticsService
from data.v2.analytics.universe_reader import load_universe_snapshot
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    TickerRecord,
)
from data.v2.schemas import AdjustedOHLCV, SectorMap
from data.v2.store import V2Store

#: ticker -> (sector, market cap in VND, base daily return, phase)
_UNIVERSE: dict[str, tuple[str, float, float, int]] = {
    "BANK1": ("Banks", 2_000e9, 0.0008, 0),
    "BANK2": ("Banks", 1_500e9, 0.0006, 1),
    "BANK3": ("Banks", 1_200e9, 0.0004, 2),
    "TECH1": ("Technology", 1_800e9, 0.0010, 3),
    "TECH2": ("Technology", 1_300e9, 0.0005, 1),
    "TECH3": ("Technology", 1_100e9, 0.0002, 2),
}


def _weekdays(count: int, start: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _bars(
    days: list[date], base_return: float, phase: int, *, ratio_drift_at: int | None
) -> list[AdjustedOHLCV]:
    bars: list[AdjustedOHLCV] = []
    price = 100.0
    for index, day in enumerate(days):
        drift = ratio_drift_at is not None and index >= ratio_drift_at
        close_raw = price * 0.85 if drift else price
        bars.append(
            AdjustedOHLCV(
                date=day,
                open=price,
                high=price,
                low=price,
                close=price,
                close_raw=close_raw,
                volume=1_000_000,
                matched_volume=900_000,
                matched_value=price * 900_000,
                source="test",
            )
        )
        pattern = (1.0, -1.0, 0.5, -0.5)[(index + phase) % 4]
        price *= 1.0 + base_return * pattern
    return bars


def _index_bars(days: list[date]) -> list[PriceBar]:
    bars: list[PriceBar] = []
    level = 1000.0
    for index, day in enumerate(days):
        bars.append(
            PriceBar(
                date=day,
                open=level,
                high=level,
                low=level,
                close=level,
                adj_close=level,
                volume=0,
                value=None,
                source="test",
            )
        )
        level *= 1.0 + 0.001 * ((index % 5) - 2)
    return bars


def _seed(tmp_path: Path, *, anomaly_ticker: str | None = None) -> sessionmaker[Session]:
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'analytics.db').as_posix()}")
    create_all(engine)
    factory = create_session_factory(engine)
    days = _weekdays(150, date(2024, 1, 2))
    last = days[-1]
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(
                    ticker=ticker,
                    exchange="HOSE",
                    source="test",
                    data_as_of=last,
                )
                for ticker in _UNIVERSE
            ]
        )
        store.upsert_sectors(
            [
                SectorMap(
                    ticker=ticker,
                    exchange="HOSE",
                    icb_level2_name=sector,
                    source="test",
                    as_of=last,
                )
                for ticker, (sector, _, _, _) in _UNIVERSE.items()
            ]
        )
        store.replace_membership("VN30", ["BANK1", "BANK2"], as_of=last, source="test")
        store.replace_membership("VN100", list(_UNIVERSE), as_of=last, source="test")
        bars_by_ticker: dict[str, list[AdjustedOHLCV]] = {}
        for ticker, (_, market_cap, base_return, phase) in _UNIVERSE.items():
            drift_at = 100 if ticker == anomaly_ticker else None
            bars = _bars(days, base_return, phase, ratio_drift_at=drift_at)
            bars_by_ticker[ticker] = bars
            store.upsert_prices(
                ticker,
                bars,
                price_adjustment_basis="ssi_adjusted",
                data_as_of=last,
            )
            store.upsert_liquidity(
                LiquidityRecord(
                    symbol=ticker,
                    as_of=last,
                    adtv_median=20e9,
                    adv_median=200_000.0,
                    window=20,
                    volume_basis="matched",
                    source="test",
                    data_as_of=last,
                )
            )
            store.upsert_market_cap(
                MarketCapRecord(
                    symbol=ticker,
                    as_of=last,
                    shares_outstanding=100_000_000,
                    market_cap=market_cap,
                    basis="full",
                    source="test",
                    data_as_of=last,
                )
            )
        SqlIndexRepository(session).upsert_many("VNINDEX", _index_bars(days))
        # Persist the adjustment-quality flags the way the precompute job does.
        flag_records: list[AdjustmentFlagRecord] = []
        for ticker, bars in bars_by_ticker.items():
            flag = adjustment_quality_flag(ticker, bars)
            flag_records.append(
                AdjustmentFlagRecord(
                    ticker=ticker,
                    severity=flag.severity,
                    flagged=flag.flagged,
                    exclude_from_group_indices=flag.exclude_from_group_indices,
                    reasons=flag.reasons,
                    dates=flag.dates,
                    source="test",
                    data_as_of=last,
                )
            )
        store.upsert_adjustment_flags(flag_records)
    return factory


def test_payload_is_built_from_the_stored_tables(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(
        AnalyticsRequest(timeframe="YTD", grouping="sector", benchmark="VNINDEX")
    )
    assert payload.benchmark == "VNINDEX"
    assert payload.grouping == "sector"
    assert payload.weighting == "market_cap"
    assert payload.market_cap_basis == "full"
    assert payload.price_adjustment_basis == "ssi_adjusted"
    assert payload.volume_basis == "matched"
    assert {group.index.group for group in payload.groups} == {"Banks", "Technology"}
    for group in payload.groups:
        assert group.index.status == "ok"
        assert group.index.constituent_count == 3
        assert group.index.cumulative_returns[0].value == 0.0
        assert group.metrics.observation_count > 60
        assert not group.metrics.low_reliability
        assert group.metrics.beta is not None
    assert payload.correlation is not None
    assert sorted(payload.correlation.labels) == ["Banks", "Technology"]
    assert any("current-constituents" in warning for warning in payload.warnings)


def test_payload_is_json_serialisable(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(AnalyticsRequest(timeframe="YTD"))
    dumped = payload.model_dump(mode="json")
    json.dumps(dumped)
    assert dumped["benchmark"] == "VNINDEX"


def test_grouping_by_exchange_yields_one_group(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(AnalyticsRequest(timeframe="YTD", grouping="exchange"))
    assert [group.index.group for group in payload.groups] == ["HOSE"]


def test_a_thin_filtered_sector_is_insufficient(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(
        AnalyticsRequest(timeframe="YTD", sectors=["Banks"], indexes=["VN30"])
    )
    (group,) = payload.groups
    assert group.index.group == "Banks"
    assert group.index.status == "insufficient"
    assert group.metrics.beta is None


def test_an_adjustment_flagged_ticker_is_reported_and_can_be_excluded(
    tmp_path: Path,
) -> None:
    service = AnalyticsService(_seed(tmp_path, anomaly_ticker="BANK3"))
    included = service.build(AnalyticsRequest(timeframe="YTD"))
    assert any(flag.ticker == "BANK3" for flag in included.adjustment_flags)
    assert any("adjustment-quality flags" in warning for warning in included.warnings)

    excluded = service.build(
        AnalyticsRequest(timeframe="YTD", exclude_adjustment_flagged=True)
    )
    banks = next(group for group in excluded.groups if group.index.group == "Banks")
    assert "BANK3" in banks.index.excluded
    assert banks.index.status == "insufficient"


def test_unknown_benchmark_raises(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    with pytest.raises(ValueError):
        service.build(AnalyticsRequest(timeframe="YTD", benchmark="NOT_AN_INDEX"))


def test_an_empty_database_raises(tmp_path: Path) -> None:
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    create_all(engine)
    service = AnalyticsService(create_session_factory(engine))
    with pytest.raises(ValueError):
        service.build(AnalyticsRequest())


def test_a_short_history_window_is_clamped_with_a_warning(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(AnalyticsRequest(timeframe="3Y"))
    assert payload.window.start == date(2024, 1, 2)
    assert any("stored history begins" in warning for warning in payload.warnings)


def test_analytics_build_uses_single_batched_close_query(tmp_path: Path) -> None:
    """AnalyticsService.build loads closes in one batched query without OHLC/volume columns."""
    clear_analytics_cache()
    factory = _seed(tmp_path)
    queries: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        queries.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", _before)
    try:
        payload = AnalyticsService(factory).build(AnalyticsRequest(timeframe="YTD"))
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    assert payload.groups
    price_bar_selects = [
        stmt
        for stmt in queries
        if "FROM v2_daily_prices" in stmt
        and "max(" not in stmt.lower()
        and "min(" not in stmt.lower()
        and "distinct" not in stmt.lower()
    ]
    assert len(price_bar_selects) == 1, price_bar_selects
    stmt_lower = price_bar_selects[0].lower()
    for unwanted in ("open", "high", "low", "matched_volume"):
        assert unwanted not in stmt_lower, stmt_lower


def test_universe_snapshot_cache_hits_and_invalidates_when_data_date_advances(
    tmp_path: Path,
) -> None:
    """load_universe_snapshot caches by overall_latest_price_date and invalidates on advance."""
    clear_analytics_cache()
    factory = _seed(tmp_path)
    first = load_universe_snapshot(factory)
    assert first.latest_price_date is not None

    queries: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        queries.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", _before)
    try:
        second = load_universe_snapshot(factory)
    finally:
        event.remove(engine, "before_cursor_execute", _before)

    assert second is first
    assert len(queries) == 1, queries

    newer_day = first.latest_price_date + timedelta(days=1)
    with session_scope(factory) as session:
        V2Store(session).upsert_prices(
            "BANK1",
            [
                AdjustedOHLCV(
                    date=newer_day,
                    open=105.0,
                    high=105.0,
                    low=105.0,
                    close=105.0,
                    close_raw=105.0,
                    volume=1_000_000,
                    matched_volume=900_000,
                    matched_value=105.0 * 900_000,
                    source="test",
                )
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=newer_day,
        )

    refreshed = load_universe_snapshot(factory)
    assert refreshed is not first
    assert refreshed.latest_price_date == newer_day


