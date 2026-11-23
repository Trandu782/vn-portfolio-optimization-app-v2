"""V2a-2 data-layer tests: the cached build, its invalidation and default exclusions.

Returns are stored on a temporary SQLite database (no network), so the cache key/date and
the default-excluded logic are deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from data.db.base import create_all, create_engine_for, create_session_factory, session_scope
from data.db.repositories import SqlIndexRepository
from data.models import PriceBar
from data.v2.adjustment_quality import adjustment_quality_flag
from data.v2.analytics.cache import clear_analytics_cache
from data.v2.analytics.service import AnalyticsRequest, AnalyticsService
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    TickerRecord,
)
from data.v2.schemas import AdjustedOHLCV, SectorMap
from data.v2.store import V2Store

#: ticker -> (sector, market cap, base daily return, phase, has a >15% glitch)
_UNIVERSE: dict[str, tuple[str, float, float, int, bool]] = {
    "B1": ("Banks", 2_000e9, 0.0008, 0, False),
    "B2": ("Banks", 1_500e9, 0.0006, 1, False),
    "B3": ("Banks", 1_200e9, 0.0004, 2, False),
    "B4": ("Banks", 1_100e9, 0.0005, 0, True),
    "T1": ("Technology", 1_800e9, 0.0010, 3, False),
    "T2": ("Technology", 1_300e9, 0.0005, 1, False),
    "T3": ("Technology", 1_100e9, 0.0002, 2, False),
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
    days: list[date], base_return: float, phase: int, jump: bool
) -> list[AdjustedOHLCV]:
    bars: list[AdjustedOHLCV] = []
    price = 100.0
    for index, day in enumerate(days):
        close = price * (1.20 if jump and index == 100 else 1.0)
        bars.append(
            AdjustedOHLCV(
                date=day,
                open=close,
                high=close,
                low=close,
                close=close,
                close_raw=close,
                volume=1_000_000,
                matched_volume=900_000,
                matched_value=close * 900_000,
                source="test",
            )
        )
        pattern = (1.0, -1.0, 0.5, -0.5)[(index + phase) % 4]
        price = close * (1.0 + base_return * pattern)
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


def _seed(tmp_path: Path) -> sessionmaker[Session]:
    clear_analytics_cache()
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'v2a2.db').as_posix()}")
    create_all(engine)
    factory = create_session_factory(engine)
    days = _weekdays(150, date(2024, 1, 2))
    last = days[-1]
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(ticker=ticker, exchange="HOSE", source="test", data_as_of=last)
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
                for ticker, (sector, _, _, _, _) in _UNIVERSE.items()
            ]
        )
        store.replace_membership("VN100", list(_UNIVERSE), as_of=last, source="test")
        bars_by_ticker: dict[str, list[AdjustedOHLCV]] = {}
        for ticker, (_, market_cap, base_return, phase, jump) in _UNIVERSE.items():
            bars = _bars(days, base_return, phase, jump)
            bars_by_ticker[ticker] = bars
            store.upsert_prices(
                ticker, bars, price_adjustment_basis="ssi_adjusted", data_as_of=last
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
                    anomalies=flag.anomalies,
                    source="test",
                    data_as_of=last,
                )
            )
        store.upsert_adjustment_flags(flag_records)
    return factory


def test_default_excluded_ticker_is_reported_and_counted(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(AnalyticsRequest(timeframe="YTD"))
    assert {item.ticker for item in payload.default_excluded} == {"B4"}
    (b4,) = payload.default_excluded
    assert b4.sector == "Banks"
    assert b4.reasons
    banks = next(group for group in payload.groups if group.index.group == "Banks")
    assert banks.default_excluded_count == 1
    assert banks.index.constituent_count == 3
    assert payload.include_default_excluded is False


def test_include_default_excluded_adds_the_ticker(tmp_path: Path) -> None:
    service = AnalyticsService(_seed(tmp_path))
    payload = service.build(
        AnalyticsRequest(timeframe="YTD", include_default_excluded=True)
    )
    banks = next(group for group in payload.groups if group.index.group == "Banks")
    assert banks.default_excluded_count == 0
    assert banks.index.constituent_count == 4
    assert {item.ticker for item in payload.default_excluded} == {"B4"}
    assert payload.include_default_excluded is True


def test_cached_build_is_a_hit_then_invalidates_on_new_data_as_of(tmp_path: Path) -> None:
    factory = _seed(tmp_path)
    service = AnalyticsService(factory)
    request = AnalyticsRequest(timeframe="YTD")

    first, cached_first, elapsed_first = service.build_cached(request)
    assert cached_first is False
    assert elapsed_first > 0.0

    second, cached_second, elapsed_second = service.build_cached(request)
    assert cached_second is True
    assert elapsed_second == 0.0
    assert second.data_as_of == first.data_as_of

    # Advance the stored data date by one session; the cache must miss again.
    later = first.data_as_of + timedelta(days=1)
    with session_scope(factory) as session:
        V2Store(session).upsert_prices(
            "B1",
            [
                AdjustedOHLCV(
                    date=later,
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    close_raw=1.0,
                    volume=1,
                    matched_volume=1,
                    matched_value=1.0,
                    source="test",
                )
            ],
            price_adjustment_basis="ssi_adjusted",
            data_as_of=later,
        )
    third, cached_third, _ = service.build_cached(request)
    assert cached_third is False
    assert third.data_as_of == later
    clear_analytics_cache()


def test_cached_payload_has_no_per_response_fields(tmp_path: Path) -> None:
    factory = _seed(tmp_path)
    payload, from_cache, elapsed = AnalyticsService(factory).build_cached(
        AnalyticsRequest(timeframe="YTD")
    )
    assert from_cache is False
    assert elapsed > 0.0
    dumped = payload.model_dump()
    assert "served_from_cache" not in dumped
    assert "elapsed_ms" not in dumped
    clear_analytics_cache()



def test_exclusion_is_window_aware_for_a_flagged_ticker(tmp_path: Path) -> None:
    # A name flagged for an anomaly outside the window must not be excluded.
    clear_analytics_cache()
    service = AnalyticsService(_seed(tmp_path))
    days = _weekdays(150, date(2024, 1, 2))
    anomaly_day = days[100]  # B4's single >15% adjusted move

    inside = service.build(
        AnalyticsRequest(timeframe="custom", custom_start=days[95], end_date=days[105])
    )
    banks_in = next(group for group in inside.groups if group.index.group == "Banks")
    assert banks_in.default_excluded_count == 1
    assert {item.ticker for item in inside.default_excluded} == {"B4"}
    (inside_item,) = inside.default_excluded
    assert anomaly_day in inside_item.affected_dates

    after = service.build(
        AnalyticsRequest(timeframe="custom", custom_start=days[110], end_date=days[149])
    )
    banks_after = next(group for group in after.groups if group.index.group == "Banks")
    assert banks_after.default_excluded_count == 0
    assert banks_after.index.constituent_count == 4
    assert {item.ticker for item in after.default_excluded} == set()
    assert {item.ticker for item in after.default_excluded_outside_window} == {"B4"}
    (outside_item,) = after.default_excluded_outside_window
    assert anomaly_day in outside_item.affected_dates  # the earlier anomaly date is shown
    assert outside_item.affected_dates  # the earlier anomaly date is still shown
    clear_analytics_cache()


def test_default_excluded_entry_carries_plain_reason_dates_and_category(
    tmp_path: Path,
) -> None:
    service = AnalyticsService(_seed(tmp_path))
    days = _weekdays(150, date(2024, 1, 2))
    payload = service.build(
        AnalyticsRequest(timeframe="custom", custom_start=days[95], end_date=days[105])
    )
    (item,) = [entry for entry in payload.default_excluded if entry.ticker == "B4"]
    assert item.reason
    assert "adjusted/raw ratio" not in item.reason  # jargon removed
    assert item.category in {"data_glitch", "thin_trading"}
    assert item.affected_dates  # the in-window anomaly date
    assert item.reasons  # full detail list for the expandable section
    clear_analytics_cache()
