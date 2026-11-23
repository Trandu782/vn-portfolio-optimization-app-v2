"""Ports (Protocols) for the data layer.

``DataProvider`` is the interface every market-data source implements. It is a
``Protocol`` so a provider is any object with the right shape - there is no base
class to inherit from and no registry switch to edit. Concrete providers live in
``data.providers`` and are registered in ``data.registry``.

The repository Protocols live in ``data.db.repositories``.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from data.models import PriceBar, SymbolInfo


@runtime_checkable
class DataProvider(Protocol):
    """A source of Vietnamese market data reachable without any credentials."""

    id: str
    display_name: str
    returns_adjusted_prices: bool
    supports_indexes: bool

    def list_symbols(self, exchange: str) -> list[SymbolInfo]:
        """Return the symbols a provider lists on ``exchange`` (or all when empty)."""

    def get_daily_prices(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for ``symbol`` between ``start`` and ``end`` inclusive."""

    def get_index_daily(self, index_code: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for an index (VNINDEX, VN30, ...) between the dates."""

    def get_index_constituents(self, index_code: str) -> list[str]:
        """Return the symbol codes that make up ``index_code``."""
