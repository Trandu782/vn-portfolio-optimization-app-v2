"""V2 provider adapter layer for Vietnamese market data.

A parallel, additive layer beside the V1 ``DataProvider`` stack: four typed
schemas, one adapter interface per data type, per-data-type failover chains in
``data.v2.config`` and a :class:`data.v2.runner.FailoverRunner`. Importing this
package registers every adapter.
"""

from __future__ import annotations

from data.v2 import providers
from data.v2.analytics import AnalyticsRequest, AnalyticsService
from data.v2.config import SPEC_CHAIN, VERIFIED_PROVIDERS, V2DataSettings, get_v2_settings
from data.v2.context import V2DataContext, build_chains, build_default_client
from data.v2.errors import BlockedError, NoProvidersConfiguredError
from data.v2.interfaces import (
    CompanyProfileProvider,
    ConstituentsProvider,
    CorporateActionsProvider,
    OHLCVProvider,
    ProviderChains,
    RatiosProvider,
    SectorMapProvider,
    SymbolMasterProvider,
)
from data.v2.liquidity import LiquidityStats, liquidity_stats, rolling_median
from data.v2.precompute import PrecomputeSources, V2PrecomputeService, sources_from_context
from data.v2.precompute_schemas import (
    CoverageSummary,
    LiquidityRecord,
    MarketCapRecord,
    MembershipRecord,
    PrecomputeReport,
    ProgressRecord,
    ReturnPoint,
    StepResult,
    TickerRecord,
    TickerSnapshot,
)
from data.v2.reader import V2Reader, sector_coverage, ticker_snapshot
from data.v2.returns import DailyReturn, calendar_returns, daily_returns, return_series
from data.v2.runner import FailoverRunner, ProviderHealth, Served
from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    CorporateAction,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
    SymbolMaster,
)
from data.v2.store import V2Store
from data.v2.universe import build_universe, validate_vn30_subset

__all__ = [
    "SPEC_CHAIN",
    "VERIFIED_PROVIDERS",
    "AdjustedOHLCV",
    "AnalyticsRequest",
    "AnalyticsService",
    "BlockedError",
    "CompanyProfile",
    "CompanyProfileProvider",
    "ConstituentsProvider",
    "CorporateAction",
    "CorporateActionsProvider",
    "CoverageSummary",
    "DailyReturn",
    "FailoverRunner",
    "FinancialRatios",
    "IndexConstituents",
    "LiquidityRecord",
    "LiquidityStats",
    "MarketCapRecord",
    "MembershipRecord",
    "NoProvidersConfiguredError",
    "OHLCVProvider",
    "PrecomputeReport",
    "PrecomputeSources",
    "ProgressRecord",
    "ProviderChains",
    "ProviderHealth",
    "RatiosProvider",
    "ReturnPoint",
    "SectorMap",
    "SectorMapProvider",
    "Served",
    "StepResult",
    "SymbolMaster",
    "SymbolMasterProvider",
    "TickerRecord",
    "TickerSnapshot",
    "V2DataContext",
    "V2DataSettings",
    "V2PrecomputeService",
    "V2Reader",
    "V2Store",
    "build_chains",
    "build_default_client",
    "build_universe",
    "calendar_returns",
    "daily_returns",
    "get_v2_settings",
    "liquidity_stats",
    "providers",
    "return_series",
    "rolling_median",
    "sector_coverage",
    "sources_from_context",
    "ticker_snapshot",
    "validate_vn30_subset",
]
