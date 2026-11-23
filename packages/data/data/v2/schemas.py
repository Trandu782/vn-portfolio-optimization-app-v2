"""Typed, normalized schemas for the V2 provider adapter layer.

One module holds every normalized record the V2 adapters return, so the adapter
contracts, the failover runner, the probe and the tests all share the same types.

Units:
- Prices are VND per share. ``AdjustedOHLCV.close`` is the provider's close; only
  a provider with ``returns_adjusted=True`` actually adjusts it for corporate
  actions (none of the anonymous providers here do, so it mirrors the raw close).
- Every percentage is a 0-100 number (ROE ``15.0`` means 15%), never a fraction.
- Money is VND; ``market_cap`` is VND.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IndexConstituents(BaseModel):
    """Members of an index or exchange basket, versioned with an as-of date."""

    model_config = ConfigDict(frozen=True)

    index: str
    members: list[str]
    as_of: date | None = None
    source: str


class SectorMap(BaseModel):
    """One ticker's ICB classification and security type (one record per ticker)."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str
    icb_level1_name: str | None = None
    icb_level1_code: str | None = None
    icb_level2_name: str | None = None
    icb_level2_code: str | None = None
    security_type: str | None = None
    source: str
    as_of: date | None = None


class AdjustedOHLCV(BaseModel):
    """One daily bar.

    ``close`` is adjusted only when the serving provider sets ``returns_adjusted``;
    ``close_raw`` carries the provider's unadjusted close when it publishes both
    (SSI ``stock-info`` exposes ``close`` adjusted and ``closeRaw`` raw), so a
    consumer can reconcile adjustment or run the price-gap fallback. ``volume`` is
    the reported total; ``matched_volume`` / ``matched_value`` are populated only
    when the provider separates order-matching flow from put-through, and ``value``
    is the reported total value when the provider exposes one.
    """

    model_config = ConfigDict(frozen=True)

    date: date
    open: float
    high: float
    low: float
    close: float
    close_raw: float | None = None
    volume: int
    matched_volume: int | None = None
    matched_value: float | None = None
    value: float | None = None
    source: str


class FinancialRatios(BaseModel):
    """Normalized financial ratios for one ticker and one reporting period."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    period: date
    period_type: Literal["annual", "quarter", "ttm"]
    provider: str
    ratios: dict[str, float | None] = Field(default_factory=dict)


class CompanyProfile(BaseModel):
    """Company reference data used for free-float weighting."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    free_float_ratio: float | None = None  # percent, 0-100
    shares_outstanding: int | None = None
    market_cap: float | None = None  # VND
    source: str


class CorporateAction(BaseModel):
    """One corporate-action event (dividend or share issue) for a ticker.

    ``event_type`` is the provider's event list code normalised to ``DIV`` (cash
    or stock dividend) or ``ISS`` (share issuance); other event codes are dropped
    by the adapter. ``ratio`` is the provider's own ratio (``0.045`` for a 4.5%
    dividend) and ``value`` the cash amount per share when the event carries one,
    kept exactly as published (no recomputation).
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    event_type: str
    exright_date: date | None = None
    record_date: date | None = None
    issue_date: date | None = None
    ratio: float | None = None
    value: float | None = None
    exchange: str | None = None
    description: str | None = None
    source: str


class SymbolMaster(BaseModel):
    """One tradable security with its exchange, used to fill symbol metadata."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    exchange: str
    name: str | None = None
    security_type: str | None = None
    source: str


__all__ = [
    "AdjustedOHLCV",
    "CompanyProfile",
    "CorporateAction",
    "FinancialRatios",
    "IndexConstituents",
    "SectorMap",
    "SymbolMaster",
]
