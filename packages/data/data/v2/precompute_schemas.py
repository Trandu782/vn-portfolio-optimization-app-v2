"""Typed records produced and returned by the V2 precompute pipeline.

These are the persisted/returned value objects for the online precompute datasets.
They deliberately carry provenance (``source``), the observation date (``as_of``) and
the basis flags so every consumer can label what it shows:

* ``price_adjustment_basis`` — ``ssi_adjusted`` | ``corporate_actions`` |
  ``price_gap_heuristic`` | ``raw``.
* ``volume_basis`` — ``matched`` | ``total``.
* ``market_cap_basis`` — always ``full`` in V2 (no keyless free-float source).

Units: money is VND, ``market_cap`` is VND, ADTV is VND per session, ADV is shares per
session. Percentages never appear here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Supported price-adjustment bases, most authoritative first.
PriceAdjustmentBasis = Literal[
    "ssi_adjusted", "corporate_actions", "price_gap_heuristic", "raw"
]
#: Volume bases (matched order-matching flow vs total reported volume).
VolumeBasis = Literal["matched", "total"]
#: Market-cap basis; full market cap because free-float is unavailable.
MarketCapBasis = Literal["full"]


class TickerRecord(BaseModel):
    """One tradable stock in the cleaned universe, with its exchange."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str
    name: str | None = None
    security_type: str | None = None
    source: str
    data_as_of: date


class AdjustmentAnomalyRecord(BaseModel):
    """One dated anomaly behind a ticker's adjustment-quality flag.

    ``exclude`` marks a return-corrupting anomaly (the group indices drop it by
    default). ``category`` separates a genuine data glitch from a move on a
    very-low-liquidity session ("thin trading"), so the Sector tab can explain what
    happened in plain language. ``reason`` is plain-language (no jargon).
    """

    model_config = ConfigDict(frozen=True)

    date: date
    exclude: bool = False
    category: Literal["data_glitch", "thin_trading"] = "data_glitch"
    reason: str = ""


class AdjustmentFlagRecord(BaseModel):
    """Persisted adjustment-quality flag for one ticker (computed by the job).

    Every ticker in the universe gets a row, flagged or not, so a reader can tell
    "flags were computed and this ticker is clean" (``flagged=False``) apart from
    "flags were never computed" (the table is empty). ``dates`` are stored as ISO
    strings on disk and returned as ``date`` objects. ``anomalies`` carries the
    per-anomaly dates/categories the Sector tab uses for window-aware exclusion.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    severity: Literal["ok", "warning"] = "ok"
    flagged: bool = False
    exclude_from_group_indices: bool = False
    reasons: list[str] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    anomalies: list[AdjustmentAnomalyRecord] = Field(default_factory=list)
    source: str
    data_as_of: date


class LiquidityRecord(BaseModel):
    """Rolling-median liquidity for one ticker at ``as_of``."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date
    adtv_median: float | None = None
    adv_median: float | None = None
    window: int = 20
    volume_basis: VolumeBasis = "total"
    source: str
    data_as_of: date


class MarketCapRecord(BaseModel):
    """Shares outstanding and full market cap at the latest reported period."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date
    shares_outstanding: int | None = None
    market_cap: float | None = None
    basis: MarketCapBasis = "full"
    source: str
    data_as_of: date


class MembershipRecord(BaseModel):
    """One (index, ticker) membership observation with its as-of date and source."""

    model_config = ConfigDict(frozen=True)

    index_code: str
    symbol_code: str
    as_of: date
    source: str


class ProgressRecord(BaseModel):
    """Checkpoint for one (dataset kind, ticker) unit of resumable work."""

    model_config = ConfigDict(frozen=True)

    kind: str
    symbol: str
    state: str = "pending"
    last_date: date | None = None
    rows: int = 0
    error: str | None = None


class CoverageSummary(BaseModel):
    """Sector coverage for the cleaned universe (never guessed)."""

    covered: int = 0
    missing: int = 0
    missing_tickers: list[str] = Field(default_factory=list)


class StepResult(BaseModel):
    """Outcome of one precompute step."""

    name: str
    ok: bool = True
    processed: int = 0
    message: str | None = None
    elapsed_seconds: float | None = None


class PrecomputeReport(BaseModel):
    """Aggregate result of one pipeline run (full or incremental)."""

    mode: str
    as_of: date
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[StepResult] = Field(default_factory=list)
    coverage: CoverageSummary = Field(default_factory=CoverageSummary)
    quality_errors: int = 0
    ok: bool = True


class ReturnPoint(BaseModel):
    """One serialisable daily simple return."""

    model_config = ConfigDict(frozen=True)

    date: date
    value: float


class TickerSnapshot(BaseModel):
    """The acceptance helper's answer for one ticker and range.

    Bundles adjusted simple returns, liquidity medians, market cap and the ICB
    level-2 sector, plus the provenance/basis flags for every dataset.
    """

    symbol: str
    start: date
    end: date
    sector: str | None = None
    sector_source: str | None = None
    market_cap: float | None = None
    shares_outstanding: int | None = None
    market_cap_basis: MarketCapBasis | None = None
    liquidity: LiquidityRecord | None = None
    price_adjustment_basis: PriceAdjustmentBasis | None = None
    volume_basis: VolumeBasis | None = None
    data_as_of: date | None = None
    source: str | None = None
    returns: list[ReturnPoint] = Field(default_factory=list)




class RatioRecord(BaseModel):
    """One ticker's trimmed financial ratios for one reporting period.

    ``period_type`` distinguishes a TTM (trailing-twelve-month) interim quarter from
    the audited annual filing; ``ratio_group`` records which ratio set applied
    (general, banks, securities or insurance). ``ratios`` holds only that group's
    keys, with percentage values normalised to a 0-100 scale.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    period: date
    period_type: Literal["annual", "quarter", "ttm"]
    ratio_group: Literal["general", "banks", "securities", "insurance"]
    ratios: dict[str, float | None] = Field(default_factory=dict)
    source: str
    data_as_of: date


class SectorStatisticRecord(BaseModel):
    """Precomputed peer statistics for one (sector, ratio, period, period_type).

    ``n`` is the number of peers with a usable value after excluding missing values
    and non-positive valuation multiples (P/E, P/B). ``percentile_ranks`` maps each
    included ticker to its percentile rank (0-100) within the peer set.
    """

    model_config = ConfigDict(frozen=True)

    sector: str
    ratio: str
    period: date
    period_type: Literal["annual", "quarter", "ttm"]
    n: int = 0
    median: float | None = None
    mean: float | None = None
    winsorized_mean: float | None = None
    p5: float | None = None
    p95: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    percentile_ranks: dict[str, float] = Field(default_factory=dict)
    source: str
    data_as_of: date


__all__ = [
    "AdjustmentAnomalyRecord",
    "AdjustmentFlagRecord",
    "CoverageSummary",
    "LiquidityRecord",
    "MarketCapBasis",
    "MarketCapRecord",
    "MembershipRecord",
    "PrecomputeReport",
    "PriceAdjustmentBasis",
    "ProgressRecord",
    "RatioRecord",
    "ReturnPoint",
    "SectorStatisticRecord",
    "StepResult",
    "TickerRecord",
    "TickerSnapshot",
    "VolumeBasis",
]
