"""Unit tests for the read-only V2b ratio verification summary."""

from __future__ import annotations

from datetime import date

from data.v2.precompute_schemas import RatioRecord, SectorStatisticRecord
from data.v2.ratio_verify import (
    group_ticker_counts,
    latest_period_counts,
    latest_periods,
    null_shares_by_group,
    null_shares_by_period_type,
    null_shares_latest_by_group,
    period_type_counts,
    sector_peer_counts,
    summarize_ratios,
)
from data.v2.ratios import GENERAL_RATIOS

AS_OF = date(2025, 12, 31)
Q4 = date(2025, 12, 31)
Q3 = date(2025, 9, 30)
Q2 = date(2025, 6, 30)


def _ratio(
    symbol: str,
    group: str,
    ratios: dict[str, float | None],
    *,
    period: date = Q3,
    period_type: str = "ttm",
) -> RatioRecord:
    return RatioRecord(
        symbol=symbol,
        period=period,
        period_type=period_type,  # type: ignore[arg-type]
        ratio_group=group,  # type: ignore[arg-type]
        ratios=ratios,
        source="ssi_statistics",
        data_as_of=AS_OF,
    )


def _stat(
    sector: str, ratio: str, period: date = Q3, *, n: int, period_type: str = "ttm"
) -> SectorStatisticRecord:
    return SectorStatisticRecord(
        sector=sector,
        ratio=ratio,
        period=period,
        period_type=period_type,  # type: ignore[arg-type]
        n=n,
        source="ssi_statistics",
        data_as_of=AS_OF,
    )


def test_latest_periods_picks_the_newest() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0}, period=Q2),
        _ratio("VCB", "banks", {"roe": 16.0}, period=Q3),
        _ratio("FPT", "general", {"roe": 25.0}),
    ]
    assert latest_periods(records) == {"VCB": (Q3, "ttm"), "FPT": (Q3, "ttm")}


def test_group_ticker_counts_counts_distinct_tickers() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0}),
        _ratio("BID", "banks", {"roe": 20.0}),
        _ratio("FPT", "general", {"roe": 25.0}),
        _ratio("BVH", "insurance", {"roe": 12.0}),
    ]
    assert group_ticker_counts(records) == {"banks": 2, "general": 1, "insurance": 1}


def test_null_shares_by_group_is_per_ratio_and_row() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0, "roa": 1.0, "npl": None, "pe": 10.0, "pb": 1.5}),
        _ratio("BID", "banks", {"roe": 20.0, "roa": 1.2, "npl": 0.8, "pe": None, "pb": 2.0}),
    ]
    shares = null_shares_by_group(records)["banks"]
    assert shares["npl"] == 0.5
    assert shares["pe"] == 0.5
    assert shares["roe"] == 0.0
    assert set(shares) == {"roe", "roa", "npl", "pe", "pb"}


def test_null_shares_latest_by_group_uses_only_the_newest_period() -> None:
    records = [
        _ratio(
            "VCB",
            "banks",
            {"roe": 15.0, "roa": 1.0, "npl": 0.7, "pe": 10.0, "pb": 1.5},
            period=Q2,
        ),
        _ratio(
            "VCB",
            "banks",
            {"roe": 16.0, "roa": None, "npl": None, "pe": 11.0, "pb": 1.6},
            period=Q3,
        ),
        _ratio(
            "BID",
            "banks",
            {"roe": 20.0, "roa": 1.2, "npl": 0.8, "pe": None, "pb": 2.0},
            period=Q3,
        ),
    ]
    shares = null_shares_latest_by_group(records)["banks"]
    # The older VCB Q2 row (roa/npl populated) is ignored; only the Q3 rows count.
    assert shares["roa"] == 0.5
    assert shares["npl"] == 0.5
    assert shares["pe"] == 0.5
    assert shares["roe"] == 0.0


def test_null_shares_by_period_type_splits_by_type() -> None:
    records = [
        _ratio(
            "VCB",
            "banks",
            {"roe": 15.0, "roa": 1.0, "npl": 0.7, "pe": 10.0, "pb": 1.5},
            period=Q3,
            period_type="ttm",
        ),
        _ratio(
            "VCB",
            "banks",
            {"roe": None, "roa": None, "npl": 0.7, "pe": 10.0, "pb": 1.5},
            period=Q4,
            period_type="quarter",
        ),
    ]
    shares = null_shares_by_period_type(records)["banks"]
    assert shares["ttm"]["roe"] == 0.0
    assert shares["quarter"]["roe"] == 1.0
    assert shares["quarter"]["npl"] == 0.0


def test_period_type_counts_counts_rows() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0}, period_type="ttm"),
        _ratio("BID", "banks", {"roe": 16.0}, period_type="ttm"),
        _ratio("VCB", "banks", {"roe": None}, period=Q4, period_type="quarter"),
    ]
    assert period_type_counts(records) == {"banks": {"ttm": 2, "quarter": 1}}


def test_latest_period_counts_counts_tickers_per_period() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0}, period=Q2),
        _ratio("VCB", "banks", {"roe": 16.0}, period=Q3),
        _ratio("FPT", "general", {"roe": 25.0}, period=Q3),
    ]
    assert latest_period_counts(records) == {Q3: 2}


def test_sector_peer_counts_prefers_roe_at_the_latest_period() -> None:
    statistics = [
        _stat("Banks", "roe", Q3, n=6),
        _stat("Banks", "pe", Q3, n=4),
        _stat("Banks", "roe", Q2, n=9),  # older period, ignored
        _stat("Technology", "roe", Q3, n=2),
    ]
    assert sector_peer_counts(statistics) == {"Banks": 6, "Technology": 2}


def test_summarize_ratios_reports_coverage_peers_and_warnings() -> None:
    records = [
        _ratio("VCB", "banks", {"roe": 15.0, "roa": 1.0, "npl": 0.7, "pe": 10.0, "pb": 1.5}),
        _ratio("FPT", "general", dict.fromkeys(GENERAL_RATIOS, 5.0)),
    ]
    statistics = [
        _stat("Banks", "roe", Q3, n=6),
        _stat("Technology", "roe", Q3, n=4),
    ]
    summary = summarize_ratios(
        records,
        statistics,
        master=["VCB", "FPT", "XYZ"],
        sector_by_ticker={"VCB": "Banks", "FPT": "Technology"},
        as_of=AS_OF,
    )
    assert summary.tickers_with_ratios == ["FPT", "VCB"]
    assert summary.latest_min == Q3 and summary.latest_max == Q3
    assert summary.group_tickers == {"banks": 1, "general": 1}
    assert summary.sectors_with_enough_peers == ["Banks"]  # N=6; Technology N=4 is low
    assert summary.sector_statistic_rows == 2
    assert summary.tickers_without_ratios == ["XYZ"]
    assert summary.quality_warning_counts == {"no_ratios": 1}
