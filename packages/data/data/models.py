"""Typed value objects shared by providers, the sync job and the API.

Providers normalise every upstream shape into ``list[PriceBar]`` with the exact
standard columns in :data:`STANDARD_PRICE_COLUMNS`. Keeping the canonical records
as frozen Pydantic models (rather than a DataFrame) keeps the serverless bundle
small and lets mypy check the whole data path; a DataFrame is only materialised
when a consumer needs one.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Canonical column order of every price series, regardless of the provider.
STANDARD_PRICE_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "value",
    "source",
)


class PriceBar(BaseModel):
    """One daily bar in the standard format."""

    model_config = ConfigDict(frozen=True)

    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    value: float | None = None
    source: str

    def as_record(self) -> dict[str, Any]:
        """Return the bar as a dict in :data:`STANDARD_PRICE_COLUMNS` order."""
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adj_close": self.adj_close,
            "volume": self.volume,
            "value": self.value,
            "source": self.source,
        }


class SymbolInfo(BaseModel):
    """A tradable symbol and the provider that reported it."""

    code: str
    exchange: str
    name: str | None = None
    type: str | None = None
    source: str


class ProviderStatus(BaseModel):
    """Health snapshot for one provider in the failover chain."""

    id: str
    name: str
    unofficial: bool
    returns_adjusted_prices: bool
    supports_indexes: bool
    healthy: bool
    state: Literal["closed", "open", "half_open"]
    consecutive_failures: int
    in_cooldown: bool
    cooldown_until: datetime | None = None
    last_error: str | None = None
    last_error_type: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    in_order: bool = True


class DataFreshness(BaseModel):
    """Latest stored price date plus every provider's current health."""

    latest_date: date | None = None
    primary: str | None = None
    stale: bool = False
    providers: list[ProviderStatus] = Field(default_factory=list)


class FailoverEvent(BaseModel):
    """A recorded failover from one provider to the next."""

    provider: str
    error_type: str
    symbol: str | None = None
    message: str
    at: datetime


class QualityFinding(BaseModel):
    """One problem (or note) produced by a quality check."""

    check: str
    severity: Literal["info", "warning", "error"]
    message: str
    dates: list[date] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """Aggregated quality findings for one symbol."""

    symbol: str
    ok: bool
    checked_at: datetime
    checks_run: list[str]
    findings: list[QualityFinding] = Field(default_factory=list)


class ProbeSample(BaseModel):
    """Outcome of probing one provider for one symbol/index."""

    label: str
    ok: bool
    latency_ms: float | None = None
    rows: int = 0
    first_date: date | None = None
    last_date: date | None = None
    history_depth_days: int | None = None
    looks_adjusted: bool | None = None
    error: str | None = None
    error_type: str | None = None


class ProviderProbe(BaseModel):
    """Probe results for a single provider."""

    provider: str
    ok: bool
    samples: list[ProbeSample]


class ProbeReport(BaseModel):
    """Probe results across every provider, plus the recommended order."""

    generated_at: datetime
    tickers: list[str]
    index_code: str
    start: date
    end: date
    providers: list[ProviderProbe]
    recommended_order: list[str]


class PriceSeries(BaseModel):
    """A price series returned by the API, with provenance and warnings."""

    symbol: str
    source: str | None
    stale: bool
    status: str = "ok"
    warnings: list[str] = Field(default_factory=list)
    rows: list[PriceBar] = Field(default_factory=list)


class RefreshResult(BaseModel):
    """Progress of one incremental refresh batch."""

    done: bool
    status: str
    processed: int
    remaining: int
    cursor: int
    symbols_done: list[str] = Field(default_factory=list)
    failures: dict[str, str] = Field(default_factory=dict)
    message: str | None = None
