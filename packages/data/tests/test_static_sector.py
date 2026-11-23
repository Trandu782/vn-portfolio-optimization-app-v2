"""Static sector map loader: validation against the KBS symbol list."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data.models import SymbolInfo
from data.v2.static_sector import (
    SectorFileError,
    kbs_symbol_exchanges,
    load_sector_map_csv,
    sector_coverage,
)

KNOWN = {"VCB": "HOSE", "FPT": "HOSE", "PVS": "HNX"}
HEADER = "ticker,icb_level1,icb_level2,source,as_of\n"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sector_map.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_loads_valid_file_and_enriches_exchange(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "VCB,Banks,Banks,fiintrade,2026-11-01\n"
        "PVS,Oil & Gas,Oil & Gas Producers,fiintrade,2026-11-01\n",
    )
    rows = load_sector_map_csv(path, known_exchanges=KNOWN)
    assert [row.ticker for row in rows] == ["PVS", "VCB"]
    vcb = next(row for row in rows if row.ticker == "VCB")
    assert vcb.exchange == "HOSE"
    assert vcb.icb_level1_name == "Banks"
    assert vcb.icb_level2_name == "Banks"
    assert vcb.source == "fiintrade"
    assert vcb.as_of == date(2026, 11, 1)


def test_unknown_ticker_fails_loudly(tmp_path: Path) -> None:
    path = _write(tmp_path, "VCB,Banks,Banks,src,2026-11-01\nZZZ,Banks,Banks,src,2026-11-01\n")
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(path, known_exchanges=KNOWN)
    message = str(excinfo.value)
    assert "unknown tickers" in message
    assert "ZZZ" in message


def test_duplicate_ticker_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "VCB,Banks,Banks,src,2026-11-01\nVCB,Banks,Banks,src,2026-11-01\n",
    )
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(path, known_exchanges=KNOWN)
    assert "duplicate tickers: VCB" in str(excinfo.value)


def test_missing_column_fails(tmp_path: Path) -> None:
    path = tmp_path / "sector_map.csv"
    path.write_text("ticker,icb_level1\nVCB,Banks\n", encoding="utf-8")
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(path, known_exchanges=KNOWN)
    assert "missing columns" in str(excinfo.value)


def test_blank_cell_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "VCB,Banks,Banks,,2026-11-01\n")
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(path, known_exchanges=KNOWN)
    assert "blank required cells" in str(excinfo.value)


def test_bad_as_of_fails(tmp_path: Path) -> None:
    path = _write(tmp_path, "VCB,Banks,Banks,src,01/11/2026\n")
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(path, known_exchanges=KNOWN)
    assert "as_of is not an ISO date" in str(excinfo.value)


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(SectorFileError) as excinfo:
        load_sector_map_csv(tmp_path / "nope.csv", known_exchanges=KNOWN)
    assert "not found" in str(excinfo.value)


def test_kbs_symbol_exchanges_helper() -> None:
    symbols = [
        SymbolInfo(code="vcb", exchange="hose", source="kbs"),
        SymbolInfo(code="PVS", exchange="HNX", source="kbs"),
    ]
    assert kbs_symbol_exchanges(symbols) == {"VCB": "HOSE", "PVS": "HNX"}


def test_sector_coverage_counts_missing(tmp_path: Path) -> None:
    path = _write(tmp_path, "VCB,Banks,Banks,src,2026-11-01\nPVS,Oil,Oil,src,2026-11-01\n")
    rows = load_sector_map_csv(path, known_exchanges=KNOWN)
    assert sector_coverage(rows, known_tickers=KNOWN) == {"covered": 2, "known": 3, "missing": 1}
