"""Loader for the optional, user-supplied static ICB sector map.

Reads ``data/reference/sector_map.csv`` with columns
``ticker, icb_level1, icb_level2, source, as_of`` and validates it against the
live KBS symbol list. Every CSV ticker must be a known KBS stock and the KBS
exchange for that ticker fills ``SectorMap.exchange`` (the CSV carries no exchange
column). Unknown tickers are a hard error that lists *all* of them, so a typo can
never silently drop a sector.

The loader is pure (no network, no DB). The V2 precompute job calls it with the
KBS symbol list it already holds; callers that only have codes can pass a
``{ticker: exchange}`` mapping built by :func:`kbs_symbol_exchanges`.

Rules from ``docs/V2_DATA_GAPS.md``: a static file is used only when copied from a
real, cited source, records ``source`` + ``as_of`` and never guesses a sector.
"""

from __future__ import annotations

import csv
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

from data.models import SymbolInfo
from data.v2.schemas import SectorMap

#: Columns the sector CSV must provide (extra columns are ignored).
REQUIRED_COLUMNS: tuple[str, ...] = ("ticker", "icb_level1", "icb_level2", "source", "as_of")


class SectorFileError(ValueError):
    """The static sector file is malformed or names tickers KBS does not list."""


def kbs_symbol_exchanges(symbols: Iterable[SymbolInfo]) -> dict[str, str]:
    """Map each KBS symbol code to its uppercase exchange for validation."""
    return {
        info.code.strip().upper(): info.exchange.strip().upper()
        for info in symbols
        if info.code and info.code.strip()
    }


def load_sector_map_csv(
    path: str | Path,
    *,
    known_exchanges: Mapping[str, str],
) -> list[SectorMap]:
    """Read and validate a static sector CSV against the KBS symbol list.

    Args:
        path: Path to ``data/reference/sector_map.csv``.
        known_exchanges: Uppercase ticker -> exchange, from the KBS symbol list.

    Returns:
        One :class:`SectorMap` per CSV row, sorted by ticker.

    Raises:
        SectorFileError: When the file is missing, a required column is absent, a
            required cell is blank, a ticker is duplicated, ``as_of`` is not an
            ISO date, or a ticker is not in the KBS symbol list. Unknown tickers
            are reported together so the file can be fixed in one pass.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise SectorFileError(f"sector file not found: {file_path}")

    known = {code.strip().upper() for code in known_exchanges}
    rows: list[SectorMap] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    unknown: list[str] = []
    blank: list[str] = []

    with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise SectorFileError(
                f"sector file {file_path} is missing columns: {', '.join(missing)}"
            )
        for line_no, raw in enumerate(reader, start=2):
            values = {key: (raw.get(key) or "").strip() for key in REQUIRED_COLUMNS}
            if not any(values.values()):
                continue  # blank line
            blanks = [key for key in REQUIRED_COLUMNS if not values[key]]
            if blanks:
                blank.append(f"line {line_no}: {', '.join(blanks)}")
                continue
            ticker = values["ticker"].upper()
            if ticker in seen:
                duplicates.append(ticker)
                continue
            seen.add(ticker)
            if ticker not in known:
                unknown.append(ticker)
                continue
            try:
                as_of = date.fromisoformat(values["as_of"])
            except ValueError as exc:
                raise SectorFileError(
                    f"{ticker}: as_of is not an ISO date: {values['as_of']!r}"
                ) from exc
            rows.append(
                SectorMap(
                    ticker=ticker,
                    exchange=known_exchanges[ticker].strip().upper(),
                    icb_level1_name=values["icb_level1"],
                    icb_level2_name=values["icb_level2"],
                    source=values["source"],
                    as_of=as_of,
                )
            )

    problems: list[str] = []
    if blank:
        problems.append("blank required cells: " + "; ".join(blank))
    if duplicates:
        problems.append("duplicate tickers: " + ", ".join(sorted(set(duplicates))))
    if unknown:
        problems.append(
            "unknown tickers (not in the KBS symbol list): " + ", ".join(sorted(unknown))
        )
    if problems:
        raise SectorFileError(f"sector file {file_path} failed validation: " + " | ".join(problems))
    if not rows:
        raise SectorFileError(f"sector file {file_path} contains no data rows")
    return sorted(rows, key=lambda row: row.ticker)


def sector_coverage(rows: Sequence[SectorMap], *, known_tickers: Collection[str]) -> dict[str, int]:
    """Return covered / known / missing counts for the KBS universe.

    Name-less completeness is informational: the loader only fails on *unknown*
    tickers, so a deliberately partial file still loads and reports its coverage.
    """
    known = {ticker.strip().upper() for ticker in known_tickers}
    covered = {row.ticker for row in rows}
    return {
        "covered": len(covered & known),
        "known": len(known),
        "missing": len(known - covered),
    }


__all__ = [
    "REQUIRED_COLUMNS",
    "SectorFileError",
    "kbs_symbol_exchanges",
    "load_sector_map_csv",
    "sector_coverage",
]
