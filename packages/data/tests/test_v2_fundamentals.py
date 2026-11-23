"""Sector peer statistics, n/m handling, peer variants and the Fundamentals service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import (
    create_all,
    create_engine_for,
    create_session_factory,
    session_scope,
)
from data.v2.analytics.schemas import UniverseRow
from data.v2.analytics.universe_reader import UniverseSnapshot
from data.v2.fundamentals import (
    FundamentalsService,
    aggregate_sector_statistics,
    compute_sector_statistic,
    select_peer_tickers,
)
from data.v2.precompute_schemas import (
    LiquidityRecord,
    MarketCapRecord,
    RatioRecord,
    TickerRecord,
)
from data.v2.ratios import GENERAL_RATIOS
from data.v2.schemas import SectorMap
from data.v2.store import V2Store

AS_OF = date(2025, 12, 31)
PERIOD = date(2025, 9, 30)


def _snapshot(rows: list[UniverseRow]) -> UniverseSnapshot:
    return UniverseSnapshot(
        master=[],
        rows=rows,
        sector_by_ticker={row.ticker: row.sector for row in rows if row.sector},
        liquidity={},
        market_caps={},
        price_adjustment_bases={},
        latest_price_date=AS_OF,
        sector_gaps=[],
        flags_available=False,
    )


def _row(
    ticker: str,
    sector: str | None,
    *,
    adtv: float | None = None,
    adv: float | None = None,
    mcap: float | None = None,
    indexes: tuple[str, ...] = (),
) -> UniverseRow:
    return UniverseRow(
        ticker=ticker,
        exchange="HOSE",
        sector=sector,
        index_memberships=frozenset(indexes),
        adtv_median=adtv,
        adv_median=adv,
        market_cap=mcap,
    )


def test_select_peer_tickers_variants_and_group_isolation() -> None:
    rows = [
        _row("VCB", "Banks", adtv=20e9, adv=200_000, mcap=1e12, indexes=("VN30", "VN100")),
        _row("BID", "Banks", adtv=5e9, adv=100_000, mcap=300e9, indexes=("VN100",)),
        _row("FPT", "Technology", adtv=20e9, adv=300_000, mcap=1e12, indexes=("VN100",)),
    ]
    snap = _snapshot(rows)
    assert select_peer_tickers(snap, "Banks", variant="all") == ["BID", "VCB"]
    assert select_peer_tickers(snap, "Banks", variant="liquidity", preset_id="standard_retail") == [
        "VCB"
    ]
    assert select_peer_tickers(snap, "Banks", variant="vn100") == ["BID", "VCB"]
    assert "FPT" not in select_peer_tickers(snap, "Banks", variant="all")
    with pytest.raises(ValueError):
        select_peer_tickers(snap, "Banks", variant="nope")  # type: ignore[arg-type]


def test_compute_sector_statistic_excludes_non_positive_pe() -> None:
    values = {"AAA": 10.0, "BBB": 20.0, "CCC": -5.0, "DDD": None}
    stat = compute_sector_statistic(
        "Technology", "pe", PERIOD, "ttm", values, source="ssi_statistics", data_as_of=AS_OF
    )
    assert stat.n == 2
    assert stat.median == pytest.approx(15.0)
    assert stat.mean == pytest.approx(15.0)
    assert stat.minimum == 10.0 and stat.maximum == 20.0
    assert set(stat.percentile_ranks) == {"AAA", "BBB"}
    assert stat.percentile_ranks["AAA"] == pytest.approx(0.0)
    assert stat.percentile_ranks["BBB"] == pytest.approx(100.0)


def test_compute_sector_statistic_keeps_negative_roe() -> None:
    values = {"AAA": -10.0, "BBB": 20.0, "CCC": 30.0}
    stat = compute_sector_statistic(
        "Technology", "roe", PERIOD, "ttm", values, source="ssi_statistics", data_as_of=AS_OF
    )
    assert stat.n == 3
    assert stat.median == pytest.approx(20.0)
    assert stat.minimum == -10.0


def test_compute_sector_statistic_all_nm_is_empty() -> None:
    stat = compute_sector_statistic(
        "Banks",
        "pe",
        PERIOD,
        "ttm",
        {"AAA": -1.0, "BBB": 0.0},
        source="ssi_statistics",
        data_as_of=AS_OF,
    )
    assert stat.n == 0
    assert stat.median is None
    assert stat.percentile_ranks == {}


def test_aggregate_sector_statistics_groups_and_skips_unknown_sector() -> None:
    records = [
        RatioRecord(
            symbol="VCB",
            period=PERIOD,
            period_type="ttm",
            ratio_group="banks",
            ratios={"roe": 15.0, "roa": 1.0},
            source="ssi_statistics",
            data_as_of=AS_OF,
        ),
        RatioRecord(
            symbol="BID",
            period=PERIOD,
            period_type="ttm",
            ratio_group="banks",
            ratios={"roe": 20.0, "roa": 1.2},
            source="ssi_statistics",
            data_as_of=AS_OF,
        ),
        RatioRecord(
            symbol="XYZ",
            period=PERIOD,
            period_type="ttm",
            ratio_group="general",
            ratios={"roe": 99.0},
            source="ssi_statistics",
            data_as_of=AS_OF,
        ),
    ]
    sector_by_ticker = {"VCB": "Banks", "BID": "Banks"}
    stats = aggregate_sector_statistics(
        records, sector_by_ticker, source="ssi_statistics", data_as_of=AS_OF
    )
    roe = next(item for item in stats if item.ratio == "roe")
    assert roe.sector == "Banks"
    assert roe.n == 2
    assert roe.median == pytest.approx(17.5)
    assert all(item.sector == "Banks" for item in stats)


@pytest.fixture
def factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_for(f"sqlite:///{tmp_path / 'fund.db'}")
    create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _seed(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        store = V2Store(session)
        store.upsert_ticker_master(
            [
                TickerRecord(
                    ticker="VCB", exchange="HOSE", source="ssi_statistics", data_as_of=AS_OF
                ),
                TickerRecord(
                    ticker="BID", exchange="HOSE", source="ssi_statistics", data_as_of=AS_OF
                ),
                TickerRecord(
                    ticker="FPT", exchange="HOSE", source="ssi_statistics", data_as_of=AS_OF
                ),
            ]
        )
        store.upsert_sectors(
            [
                SectorMap(
                    ticker="VCB",
                    exchange="HOSE",
                    icb_level2_name="Banks",
                    icb_level2_code="8300",
                    source="ssi_statistics",
                    as_of=AS_OF,
                ),
                SectorMap(
                    ticker="BID",
                    exchange="HOSE",
                    icb_level2_name="Banks",
                    icb_level2_code="8300",
                    source="ssi_statistics",
                    as_of=AS_OF,
                ),
                SectorMap(
                    ticker="FPT",
                    exchange="HOSE",
                    icb_level2_name="Technology",
                    icb_level2_code="9500",
                    source="ssi_statistics",
                    as_of=AS_OF,
                ),
            ]
        )
        store.replace_membership("VN100", ["VCB", "BID", "FPT"], as_of=AS_OF, source="kbs")
        for ticker, adtv, adv, cap in (
            ("VCB", 20e9, 200_000.0, 1e12),
            ("BID", 5e9, 100_000.0, 300e9),
            ("FPT", 20e9, 300_000.0, 1e12),
        ):
            store.upsert_liquidity(
                LiquidityRecord(
                    symbol=ticker,
                    as_of=AS_OF,
                    adtv_median=adtv,
                    adv_median=adv,
                    window=20,
                    volume_basis="matched",
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                )
            )
            store.upsert_market_cap(
                MarketCapRecord(
                    symbol=ticker,
                    as_of=AS_OF,
                    market_cap=cap,
                    basis="full",
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                )
            )
        store.upsert_ratios(
            [
                RatioRecord(
                    symbol="VCB",
                    period=PERIOD,
                    period_type="ttm",
                    ratio_group="banks",
                    ratios={"roe": 15.0, "roa": 1.0, "npl": 0.7, "pe": 10.0, "pb": 1.5},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                ),
                RatioRecord(
                    symbol="BID",
                    period=PERIOD,
                    period_type="ttm",
                    ratio_group="banks",
                    ratios={"roe": 20.0, "roa": 1.2, "npl": 0.9, "pe": 12.0, "pb": 2.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                ),
                RatioRecord(
                    symbol="FPT",
                    period=PERIOD,
                    period_type="ttm",
                    ratio_group="general",
                    ratios={"roe": 25.0, "grossProfitMargin": 40.0, "pe": 15.0, "pb": 3.0},
                    source="ssi_statistics",
                    data_as_of=AS_OF,
                ),
            ]
        )


def test_store_ratio_round_trip_and_idempotency(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    _seed(factory)  # idempotent upsert keeps one row per period
    with session_scope(factory) as session:
        store = V2Store(session)
        vcb = store.get_ratios("VCB")
        assert len(vcb) == 1
        assert vcb[0].ratio_group == "banks"
        assert store.get_ratio("VCB", PERIOD, "ttm") is not None
        assert store.get_ratio("VCB", PERIOD, "annual") is None
        tickers = {record.symbol for record in store.list_ratios(period=PERIOD, period_type="ttm")}
        assert tickers == {"VCB", "BID", "FPT"}


def test_service_compares_only_with_same_sector(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    service = FundamentalsService(factory)
    comparison = service.compare("VCB", period=PERIOD, period_type="ttm", variant="all")
    assert comparison.sector == "Banks"
    assert comparison.ratio_group == "banks"
    assert comparison.provider == "ssi_statistics"
    assert comparison.period == PERIOD
    assert comparison.period_type == "ttm"
    ratios = {item.ratio: item for item in comparison.ratios}
    assert set(ratios) == {"roe", "roa", "npl", "pe", "pb"}
    roe = ratios["roe"]
    assert roe.value == pytest.approx(15.0)
    assert roe.label == "ROE"
    assert roe.category == "profitability"
    assert roe.category_label == "Profitability"
    assert roe.is_percentage is True
    assert roe.direction == "higher"
    assert roe.peers.n == 2  # VCB + BID, never the Technology peer FPT
    assert roe.peers.median == pytest.approx(17.5)
    assert roe.peers.q1 == pytest.approx(15.0)
    assert roe.peers.q3 == pytest.approx(20.0)
    assert roe.peers.minimum == pytest.approx(15.0)
    assert roe.peers.maximum == pytest.approx(20.0)
    assert roe.peers.percentile_rank == pytest.approx(0.0)
    # Valuation multiples are neutral and not a percentage.
    assert ratios["pe"].direction == "neutral"
    assert ratios["pe"].is_percentage is False
    assert ratios["npl"].category == "asset_quality"


def test_service_liquidity_and_vn100_peer_variants(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    service = FundamentalsService(factory)
    liquidity = service.compare(
        "VCB", period=PERIOD, period_type="ttm", variant="liquidity", preset_id="standard_retail"
    )
    roe_liq = next(item for item in liquidity.ratios if item.ratio == "roe")
    assert roe_liq.peers.n == 1  # BID fails the standard-retail preset
    vn100 = service.compare("VCB", period=PERIOD, period_type="ttm", variant="vn100")
    roe_vn100 = next(item for item in vn100.ratios if item.ratio == "roe")
    assert roe_vn100.peers.n == 2  # both banks are VN100 members


def test_service_general_group_uses_general_ratios(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    comparison = FundamentalsService(factory).compare(
        "FPT", period=PERIOD, period_type="ttm", variant="all"
    )
    assert comparison.ratio_group == "general"
    assert {item.ratio for item in comparison.ratios} == set(GENERAL_RATIOS)


def test_service_without_sector_raises(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    with pytest.raises(ValueError):
        FundamentalsService(factory).compare("XYZ", period=PERIOD, period_type="ttm")
