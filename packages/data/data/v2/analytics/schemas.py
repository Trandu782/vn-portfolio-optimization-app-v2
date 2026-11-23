"""Typed, JSON-serialisable schemas for the V2 analytics engine.

Units and conventions
---------------------
* ``UniverseRow`` carries the stored per-ticker inputs the filter and groupings
  consume. ``index_memberships`` holds canonical upper-case index codes (VN30,
  VN100). Money is VND and ``adv_median`` is shares per session.
* Return fields in the payload are **percentages** (``10.0`` means 10%), because the
  Sector Analysis chart is drawn as a "base 0%" normalised line. ``beta``, ``r_squared``
  and ``correlation`` are dimensionless, and ``annualized_volatility`` is an
  annualised percentage.
* Every model is frozen so a payload cannot be mutated after it is built.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from data.v2.precompute_schemas import AdjustmentAnomalyRecord, ReturnPoint


class UniverseRow(BaseModel):
    """One scored universe candidate for filtering and grouping."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str
    sector: str | None = None
    index_memberships: frozenset[str] = Field(default_factory=frozenset)
    adtv_median: float | None = None
    adv_median: float | None = None
    market_cap: float | None = None
    volume_basis: str | None = None
    market_cap_basis: str = "full"


class Window(BaseModel):
    """The effective analysis window, in trading days."""

    model_config = ConfigDict(frozen=True)

    label: str
    start: date
    end: date


class GroupIndexResult(BaseModel):
    """A built group index: its constituents, target weights and cumulative path."""

    model_config = ConfigDict(frozen=True)

    group: str
    status: Literal["ok", "insufficient"]
    constituent_count: int
    constituents: list[str] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    cumulative_returns: list[ReturnPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkMetrics(BaseModel):
    """A group's performance and risk against the selected benchmark."""

    model_config = ConfigDict(frozen=True)

    group: str
    benchmark: str
    period_return: float | None = None
    benchmark_period_return: float | None = None
    excess_return: float | None = None
    beta: float | None = None
    r_squared: float | None = None
    correlation: float | None = None
    annualized_volatility: float | None = None
    observation_count: int = 0
    constituent_count: int = 0
    low_reliability: bool = True
    warnings: list[str] = Field(default_factory=list)


class GroupAnalytics(BaseModel):
    """One group's index plus its benchmark metrics."""

    model_config = ConfigDict(frozen=True)

    index: GroupIndexResult
    metrics: BenchmarkMetrics
    default_excluded_count: int = 0


class CorrelationResult(BaseModel):
    """Pairwise Pearson correlation of the group return series.

    ``labels`` is the stable order of both ``matrix`` rows/columns; ``ordered_labels``
    is the hierarchical-clustering display order (the UI reorders with it).
    """

    model_config = ConfigDict(frozen=True)

    labels: list[str] = Field(default_factory=list)
    matrix: list[list[float]] = Field(default_factory=list)
    ordered_labels: list[str] = Field(default_factory=list)
    average_pairwise_correlation: float | None = None


class AdjustmentQualityFlag(BaseModel):
    """Per-ticker adjustment-quality flag surfaced in the analytics payload."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    severity: Literal["ok", "warning"] = "ok"
    flagged: bool = False
    exclude_from_group_indices: bool = False
    reasons: list[str] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    anomalies: list[AdjustmentAnomalyRecord] = Field(default_factory=list)


class DefaultExcludedTicker(BaseModel):
    """A ticker the engine excludes from group indices by default.

    The precompute job marks return-corrupting anomalies with
    ``exclude_from_group_indices=True``; the Sector tab lists them here so the user can
    see what was dropped and opt back in with ``include_default_excluded``.

    The Sector tab is **window-aware**: a ticker is only listed in this model when one of
    its return-corrupting anomalies falls inside the analysis window. ``reason`` is the
    plain-language main reason, ``category`` separates a data glitch from thin trading,
    and ``affected_dates`` are the anomaly dates inside the window.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    sector: str | None = None
    severity: Literal["ok", "warning"] = "ok"
    reason: str = ""
    category: Literal["data_glitch", "thin_trading"] = "data_glitch"
    affected_dates: list[date] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AnalyticsPayload(BaseModel):
    """One JSON-serialisable payload for the Sector Analysis UI."""

    model_config = ConfigDict(frozen=True)

    data_as_of: date
    generated_at: datetime
    grouping: str
    weighting: str
    benchmark: str
    window: Window
    benchmark_returns: list[ReturnPoint] = Field(default_factory=list)
    liquidity_preset: str
    price_adjustment_basis: str | None = None
    volume_basis: str | None = None
    market_cap_basis: str = "full"
    market_cap_note: str = (
        "Full market cap (free-float is unavailable keyless; ADTV and ADV are the "
        "real liquidity guards)."
    )
    groups: list[GroupAnalytics] = Field(default_factory=list)
    correlation: CorrelationResult | None = None
    adjustment_flags: list[AdjustmentQualityFlag] = Field(default_factory=list)
    default_excluded: list[DefaultExcludedTicker] = Field(default_factory=list)
    default_excluded_outside_window: list[DefaultExcludedTicker] = Field(
        default_factory=list
    )
    flags_available: bool = False
    flags_policy_current: bool = False
    include_default_excluded: bool = False
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "AdjustmentQualityFlag",
    "AnalyticsPayload",
    "BenchmarkMetrics",
    "CorrelationResult",
    "DefaultExcludedTicker",
    "GroupAnalytics",
    "GroupIndexResult",
    "UniverseRow",
    "Window",
]
