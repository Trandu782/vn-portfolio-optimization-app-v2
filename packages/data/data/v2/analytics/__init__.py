"""V2 analytics engine: pure grouping, group-index, metric and correlation helpers.

Importing this package registers the built-in groupings (``sector``, ``exchange``,
``index``). :class:`AnalyticsService` reads the stored V2 tables and assembles the JSON
payload for the Sector Analysis UI; everything else here is pure and DB-free.
"""

from __future__ import annotations

from data.v2.analytics.correlation import correlation_matrix
from data.v2.analytics.grouping import (
    Grouping,
    IndexBucketGrouping,
    SectorGrouping,
    build_grouping,
    group_rows,
    groupings,
)
from data.v2.analytics.index import (
    DEFAULT_SINGLE_STOCK_CAP,
    WEIGHTING_EQUAL,
    WEIGHTING_MARKET_CAP,
    GroupConstituent,
    GroupIndex,
    apply_cap,
    build_group_index,
    target_weights,
)
from data.v2.analytics.liquidity import (
    DEFAULT_PRESET_ID,
    LIQUIDITY_PRESETS,
    LiquidityPreset,
    UniverseFilterResult,
    UniverseFilterSpec,
    filter_universe,
    get_preset,
    suggest_preset,
)
from data.v2.analytics.metrics import benchmark_metrics, compound_return
from data.v2.analytics.schemas import (
    AdjustmentQualityFlag,
    AnalyticsPayload,
    BenchmarkMetrics,
    CorrelationResult,
    GroupAnalytics,
    GroupIndexResult,
    UniverseRow,
    Window,
)
from data.v2.analytics.service import AnalyticsRequest, AnalyticsService
from data.v2.analytics.timeframes import TIMEFRAMES, resolve_window, subtract_months

__all__ = [
    "DEFAULT_PRESET_ID",
    "DEFAULT_SINGLE_STOCK_CAP",
    "LIQUIDITY_PRESETS",
    "TIMEFRAMES",
    "WEIGHTING_EQUAL",
    "WEIGHTING_MARKET_CAP",
    "AdjustmentQualityFlag",
    "AnalyticsPayload",
    "AnalyticsRequest",
    "AnalyticsService",
    "BenchmarkMetrics",
    "CorrelationResult",
    "GroupAnalytics",
    "GroupConstituent",
    "GroupIndex",
    "GroupIndexResult",
    "Grouping",
    "IndexBucketGrouping",
    "LiquidityPreset",
    "SectorGrouping",
    "UniverseFilterResult",
    "UniverseFilterSpec",
    "UniverseRow",
    "Window",
    "apply_cap",
    "benchmark_metrics",
    "build_group_index",
    "build_grouping",
    "compound_return",
    "correlation_matrix",
    "filter_universe",
    "get_preset",
    "group_rows",
    "groupings",
    "resolve_window",
    "subtract_months",
    "suggest_preset",
    "target_weights",
]
