"""Data layer for the VN Portfolio Optimizer.

Anonymous market-data providers (KBS primary, then VCI, DNSE, TCBS and SSI
iBoard), the failover chain, the SQLAlchemy repositories, the sync service, the
built-in reference seed and the quality checks. Importing the package registers
every provider in ``data.registry``.
"""

from __future__ import annotations

from data import providers
from data.context import DataContext, get_context, set_context
from data.fallback import FallbackProvider
from data.interfaces import DataProvider
from data.models import (
    STANDARD_PRICE_COLUMNS,
    PriceBar,
    PriceSeries,
    ProviderStatus,
    QualityReport,
    SymbolInfo,
)
from data.presets import INDEX_PRESETS, PRESET_BY_CODE, IndexPreset
from data.registry import build_provider, data_providers

__all__ = [
    "INDEX_PRESETS",
    "PRESET_BY_CODE",
    "STANDARD_PRICE_COLUMNS",
    "DataContext",
    "DataProvider",
    "FallbackProvider",
    "IndexPreset",
    "PriceBar",
    "PriceSeries",
    "ProviderStatus",
    "QualityReport",
    "SymbolInfo",
    "build_provider",
    "data_providers",
    "get_context",
    "providers",
    "set_context",
]
__version__ = "0.1.0"
