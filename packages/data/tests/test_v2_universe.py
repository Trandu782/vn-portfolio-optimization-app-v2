"""Ticker-master filtering, sector coverage gaps and VN30/VN100 validation."""

from __future__ import annotations

from datetime import date

from data.v2.schemas import SectorMap, SymbolMaster
from data.v2.universe import build_universe, is_tradable_stock, validate_vn30_subset

AS_OF = date(2025, 12, 31)


def _master(
    ticker: str,
    exchange: str,
    security_type: str = "s",
    *,
    source: str = "ssi_statistics",
) -> SymbolMaster:
    return SymbolMaster(
        ticker=ticker,
        exchange=exchange,
        name=ticker,
        security_type=security_type,
        source=source,
    )


def _sector(ticker: str, name: str) -> SectorMap:
    return SectorMap(
        ticker=ticker,
        exchange="HOSE",
        icb_level2_name=name,
        icb_level2_code="8300",
        source="ssi_statistics",
        as_of=AS_OF,
    )


def test_is_tradable_stock_filters_exchanges_and_types() -> None:
    assert is_tradable_stock("HOSE", "s")
    assert is_tradable_stock("upcom", None)
    assert is_tradable_stock("HNX", "stock")
    assert not is_tradable_stock("GB", "s")  # government-bond board
    assert not is_tradable_stock("VNF", "f")
    assert not is_tradable_stock("HOSE", "etf")
    assert not is_tradable_stock("HOSE", "fund")
    assert not is_tradable_stock("HOSE", "bond")
    assert not is_tradable_stock("HOSE", "covered_warrant")
    assert not is_tradable_stock("HOSE", "unexpected")


def test_build_universe_keeps_stocks_and_reports_gaps_and_exclusions() -> None:
    ssi_master = [
        _master("VCB", "HOSE"),
        _master("FPT", "HOSE"),
        _master("XYZ", "HOSE"),
        _master("ETF1", "HOSE", "f"),
        _master("GB05", "GB"),
    ]
    kbs_master = [
        _master("VCB", "HOSE", "stock", source="kbs"),
        _master("FPT", "HOSE", "stock", source="kbs"),
        _master("KBSONLY", "HNX", "stock", source="kbs"),
    ]
    sectors = [_sector("VCB", "Banks"), _sector("FPT", "Software")]

    built = build_universe(ssi_master, kbs_master, sectors, as_of=AS_OF)

    assert [record.ticker for record in built.master] == ["FPT", "KBSONLY", "VCB", "XYZ"]
    assert built.missing_sector == ["KBSONLY", "XYZ"]  # never guessed
    assert [sector.ticker for sector in built.sectors] == ["FPT", "VCB"]
    excluded = {ticker for ticker, _reason in built.excluded}
    assert excluded == {"ETF1", "GB05"}
    exchanges = {record.ticker: record.exchange for record in built.master}
    assert exchanges["KBSONLY"] == "HNX"
    assert all(record.data_as_of == AS_OF for record in built.master)


def test_validate_vn30_subset() -> None:
    assert validate_vn30_subset(["VCB", "FPT"], ["VCB", "FPT", "HPG"]) == []
    assert validate_vn30_subset(["VCB", "AAA"], ["VCB"]) == ["AAA"]
    assert validate_vn30_subset([], ["VCB"]) == []
