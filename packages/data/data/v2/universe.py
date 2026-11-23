"""Build the cleaned V2 ticker master from the SSI and KBS masters plus sectors.

Rules (``docs/V2_SPEC.md`` sections 3.1 and 5, ``docs/V2_DATA_GAPS.md``):

* only the three stock boards HOSE, HNX and UPCoM are kept;
* ETFs, funds, covered warrants, bonds/units and any unrecognised non-stock security
  type are **excluded explicitly** (never silently coerced into a stock);
* the SSI bulk ``sectors-data`` map supplies the **ICB level-2** sector; a universe
  ticker with no sector is a reported coverage gap and is **excluded from sector
  features, never guessed**;
* VN30 must be a subset of VN100 — the pipeline raises when it is not.

This module is pure: the pipeline fetches the three inputs and calls
:func:`build_universe`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from data.models import SymbolInfo
from data.v2.precompute_schemas import TickerRecord
from data.v2.schemas import SectorMap, SymbolMaster
from data.v2.symbols import merge_symbol_master

#: Stock boards included in the V2 universe (UPCoM is stored as ``UPCOM``).
TRADABLE_EXCHANGES: frozenset[str] = frozenset({"HOSE", "HNX", "UPCOM"})

#: Security types that are explicitly excluded (lower-case, provider spellings).
EXCLUDED_SECURITY_TYPES: frozenset[str] = frozenset(
    {
        "etf",
        "fund",
        "cw",
        "warrant",
        "covered_warrant",
        "coveredwarrant",
        "bond",
        "unit",
        "closed_end_fund",
        "closedendfund",
    }
)

#: Security types that are confirmed stocks (empty is treated as a stock below).
STOCK_SECURITY_TYPES: frozenset[str] = frozenset({"s", "stock", "shares", "common"})


def normalize_exchange(value: str | None) -> str:
    """Return ``value`` upper-cased and stripped (``None`` becomes an empty string)."""
    return (value or "").strip().upper()


def _normalize_type(value: str | None) -> str:
    return (value or "").strip().lower()


def is_tradable_stock(exchange: str | None, security_type: str | None) -> bool:
    """Return ``True`` when the security is a stock on HOSE/HNX/UPCoM."""
    if normalize_exchange(exchange) not in TRADABLE_EXCHANGES:
        return False
    kind = _normalize_type(security_type)
    if not kind:
        return True  # both sources are stock lists; a missing type is still a stock
    if kind in EXCLUDED_SECURITY_TYPES:
        return False
    return kind in STOCK_SECURITY_TYPES


def exclusion_reason(exchange: str | None, security_type: str | None) -> str | None:
    """Return why a security is excluded, or ``None`` when it is a tradable stock."""
    if is_tradable_stock(exchange, security_type):
        return None
    board = normalize_exchange(exchange)
    if board not in TRADABLE_EXCHANGES:
        return f"exchange {board or 'UNKNOWN'} is not HOSE/HNX/UPCoM"
    kind = _normalize_type(security_type)
    if kind in EXCLUDED_SECURITY_TYPES:
        return f"excluded security type {kind}"
    return f"unrecognised security type {kind or 'UNKNOWN'}"


@dataclass(frozen=True)
class UniverseBuild:
    """The cleaned universe, its sectors and the explicit gaps/exclusions."""

    master: list[TickerRecord]
    sectors: list[SectorMap]
    missing_sector: list[str]
    excluded: list[tuple[str, str]]


def _to_symbol_infos(rows: Iterable[SymbolMaster]) -> list[SymbolInfo]:
    """Adapt KBS :class:`SymbolMaster` rows to :class:`SymbolInfo` for the merge."""
    return [
        SymbolInfo(
            code=row.ticker,
            exchange=row.exchange,
            name=row.name,
            type=row.security_type,
            source=row.source,
        )
        for row in rows
    ]


def build_universe(
    ssi_master: Sequence[SymbolMaster],
    kbs_master: Sequence[SymbolMaster],
    sectors: Sequence[SectorMap],
    *,
    as_of: date,
    source: str = "ssi_statistics+kbs",
) -> UniverseBuild:
    """Filter and merge the two masters into the cleaned V2 universe.

    Args:
        ssi_master: SSI symbol-master rows (stocks only; carries exchange and name).
        kbs_master: KBS tradable list expressed as :class:`SymbolMaster` rows.
        sectors: The SSI bulk ICB level-2 map.
        as_of: The date this universe snapshot is taken.
        source: Provenance stamped on every :class:`TickerRecord`.

    Returns:
        A :class:`UniverseBuild` with the kept tickers, their covered sectors, the
        tickers missing a sector (coverage gaps) and every excluded ticker with a
        reason.
    """
    merged = merge_symbol_master(ssi_master, _to_symbol_infos(kbs_master))
    sector_by_ticker = {
        sector.ticker.strip().upper(): sector for sector in sectors if sector.icb_level2_name
    }

    master: list[TickerRecord] = []
    missing_sector: list[str] = []
    excluded: list[tuple[str, str]] = []
    for row in merged:
        reason = exclusion_reason(row.exchange, row.security_type)
        if reason is not None:
            excluded.append((row.ticker, reason))
            continue
        ticker = row.ticker.strip().upper()
        master.append(
            TickerRecord(
                ticker=ticker,
                exchange=normalize_exchange(row.exchange),
                name=row.name,
                security_type=row.security_type,
                source=source,
                data_as_of=as_of,
            )
        )
        if ticker not in sector_by_ticker:
            missing_sector.append(ticker)

    master.sort(key=lambda record: record.ticker)
    missing_sector.sort()
    kept = {record.ticker for record in master}
    covered_sectors = [
        sector_by_ticker[ticker] for ticker in sorted(kept & set(sector_by_ticker))
    ]
    excluded.sort(key=lambda item: item[0])
    return UniverseBuild(
        master=master,
        sectors=covered_sectors,
        missing_sector=missing_sector,
        excluded=excluded,
    )


def validate_vn30_subset(vn30: Iterable[str], vn100: Iterable[str]) -> list[str]:
    """Return the VN30 members that are absent from VN100 (empty means valid)."""
    upper_vn100 = {ticker.strip().upper() for ticker in vn100}
    return sorted({ticker.strip().upper() for ticker in vn30} - upper_vn100)


__all__ = [
    "EXCLUDED_SECURITY_TYPES",
    "STOCK_SECURITY_TYPES",
    "TRADABLE_EXCHANGES",
    "UniverseBuild",
    "build_universe",
    "exclusion_reason",
    "is_tradable_stock",
    "normalize_exchange",
    "validate_vn30_subset",
]

