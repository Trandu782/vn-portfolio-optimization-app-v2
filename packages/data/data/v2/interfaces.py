"""One adapter interface (Protocol) per data type.

A concrete adapter implements only the protocols it can serve; one class may
implement several (for example KBS serves constituents + OHLCV + ratios). The
contracts are deliberately small so a new provider is one file plus one
registration and the failover runner never learns about a specific source.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    CorporateAction,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
    SymbolMaster,
)


@runtime_checkable
class ConstituentsProvider(Protocol):
    """Publishes the members of indices and exchange baskets."""

    id: str
    display_name: str

    def get_index_constituents(self, index_code: str) -> IndexConstituents:
        """Return the members of ``index_code`` (VN30, VN100, HOSE, HNX, UPCOM)."""


@runtime_checkable
class SectorMapProvider(Protocol):
    """Publishes ICB sector classifications per ticker."""

    id: str
    display_name: str
    supports_bulk_sector_map: bool

    def get_sector_map(self, ticker: str) -> SectorMap:
        """Return the ICB mapping for one ticker."""

    def get_sector_map_all(self) -> list[SectorMap]:
        """Return a provider-native bulk map, or raise when bulk is unsupported."""


@runtime_checkable
class OHLCVProvider(Protocol):
    """Publishes daily OHLCV for stocks and indices."""

    id: str
    display_name: str
    returns_adjusted: bool

    def get_ohlcv(self, symbol: str, start: date, end: date) -> list[AdjustedOHLCV]:
        """Return daily bars for ``symbol`` between ``start`` and ``end`` inclusive."""

    def get_index_ohlcv(
        self, index_code: str, start: date, end: date
    ) -> list[AdjustedOHLCV]:
        """Return daily bars for an index (VNINDEX, VN30, VN100)."""


@runtime_checkable
class RatiosProvider(Protocol):
    """Publishes normalized financial ratios."""

    id: str
    display_name: str

    def get_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return one record per reporting period for ``ticker``."""


@runtime_checkable
class CompanyProfileProvider(Protocol):
    """Publishes company reference data (free-float, shares, market cap)."""

    id: str
    display_name: str
    supports_free_float: bool

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Return the company profile for one ticker."""


@runtime_checkable
class CorporateActionsProvider(Protocol):
    """Publishes corporate-action events (dividends and share issues)."""

    id: str
    display_name: str

    def get_corporate_actions(self, ticker: str, start: date, end: date) -> list[CorporateAction]:
        """Return every DIV/ISS event the provider lists for ``ticker`` in ``[start, end]``."""


@runtime_checkable
class SymbolMasterProvider(Protocol):
    """Publishes a bulk ticker -> exchange security master."""

    id: str
    display_name: str

    def get_symbol_master(self) -> list[SymbolMaster]:
        """Return every stock the provider lists, with its exchange."""


@dataclass(frozen=True)
class ProviderChains:
    """The ordered adapters behind each data type.

    Built from :class:`data.v2.config.V2DataSettings` by
    :func:`data.v2.context.build_chains`; the runner reads only this object, so
    the failover order is never hardcoded in the runner.
    """

    constituents: Sequence[ConstituentsProvider] = ()
    ohlcv: Sequence[OHLCVProvider] = ()
    sector_map: Sequence[SectorMapProvider] = ()
    ratios: Sequence[RatiosProvider] = ()
    company_profile: Sequence[CompanyProfileProvider] = ()
    corporate_actions: Sequence[CorporateActionsProvider] = ()
    symbol_master: Sequence[SymbolMasterProvider] = ()


__all__ = [
    "CompanyProfileProvider",
    "ConstituentsProvider",
    "CorporateActionsProvider",
    "OHLCVProvider",
    "ProviderChains",
    "RatiosProvider",
    "SectorMapProvider",
    "SymbolMasterProvider",
]
