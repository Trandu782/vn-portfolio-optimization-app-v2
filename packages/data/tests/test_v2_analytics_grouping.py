"""The pluggable grouping abstraction (sector, exchange, index bucket)."""

from __future__ import annotations

from data.v2.analytics.grouping import build_grouping, group_rows, groupings
from data.v2.analytics.schemas import UniverseRow


def _row(ticker: str, *, sector: str | None = "Banks", exchange: str = "HOSE",
         indexes: tuple[str, ...] = ("VN100",)) -> UniverseRow:
    return UniverseRow(
        ticker=ticker,
        exchange=exchange,
        sector=sector,
        index_memberships=frozenset(indexes),
    )


def test_registry_exposes_the_three_groupings() -> None:
    assert groupings.list() == ["sector", "exchange", "index"]


def test_sector_grouping_returns_none_for_a_coverage_gap() -> None:
    grouping = build_grouping("sector")
    assert grouping.assign(_row("BANK", sector="Banks")) == "Banks"
    assert grouping.assign(_row("GAP", sector=None)) is None


def test_exchange_grouping_uses_the_board() -> None:
    grouping = build_grouping("exchange")
    assert grouping.assign(_row("A", exchange="hose")) == "HOSE"
    assert grouping.assign(_row("B", exchange="UPCOM")) == "UPCOM"


def test_index_bucket_prefers_vn30_then_vn100_then_non_index() -> None:
    grouping = build_grouping("index")
    assert grouping.assign(_row("BLUE", indexes=("VN30", "VN100"))) == "VN30"
    assert grouping.assign(_row("WIDE", indexes=("VN100",))) == "VN100"
    assert grouping.assign(_row("SMALL", indexes=())) == "Non-index"


def test_index_bucket_label_is_configurable() -> None:
    grouping = build_grouping("index", {"non_index_label": "Outside"})
    assert grouping.assign(_row("SMALL", indexes=())) == "Outside"


def test_group_rows_partitions_and_drops_ungrouped_rows() -> None:
    rows = [
        _row("BANK1", sector="Banks"),
        _row("BANK2", sector="Banks"),
        _row("TECH1", sector="Technology"),
        _row("GAP", sector=None),
    ]
    groups = group_rows(rows, build_grouping("sector"))
    assert {label: sorted(row.ticker for row in members) for label, members in groups.items()} == {
        "Banks": ["BANK1", "BANK2"],
        "Technology": ["TECH1"],
    }
