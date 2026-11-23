"""SQLAlchemy 2 ORM models.

Tables match the task: ``symbols``, ``prices_daily``, ``indices_daily``,
``index_constituents``, ``sync_log`` and an intentionally empty
``corporate_actions`` reserved for V2. Prices use a composite primary key so
upserts are idempotent, and every price row stores the provider ``source`` so the
UI can show provenance and the sync can detect a source change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base shared by every table."""


class Symbol(Base):
    """A tradable symbol and the provider that first reported it."""

    __tablename__ = "symbols"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PriceDaily(Base):
    """One daily bar for a stock symbol (composite key ``symbol_code`` + date)."""

    __tablename__ = "prices_daily"

    symbol_code: Mapped[str] = mapped_column(
        ForeignKey("symbols.code", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class IndexDaily(Base):
    """One daily bar for a market index (composite key ``index_code`` + date)."""

    __tablename__ = "indices_daily"

    index_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class IndexConstituent(Base):
    """Membership of a symbol in an index at the time of the last sync."""

    __tablename__ = "index_constituents"

    index_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="unknown")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SyncLog(Base):
    """One sync attempt (per symbol or per benchmark), for progress and audit."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CorporateAction(Base):
    """Reserved for V2. Deliberately has no business columns yet."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class V2TickerMaster(Base):
    """Cleaned V2 universe: one tradable stock per row, with its board."""

    __tablename__ = "v2_ticker_master"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    security_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date, index=True)


class V2SectorMap(Base):
    """ICB level-2 sector for a universe ticker (no sector row = a coverage gap)."""

    __tablename__ = "v2_sector_map"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    icb_level2_name: Mapped[str] = mapped_column(String(128))
    icb_level2_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(48))
    as_of: Mapped[date] = mapped_column(Date)


class V2Membership(Base):
    """Index membership with its as-of date and source."""

    __tablename__ = "v2_index_membership"

    index_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(48))


class V2DailyPrice(Base):
    """Adjusted daily bar with raw close, matched flow and basis flags."""

    __tablename__ = "v2_daily_prices"

    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    data_as_of: Mapped[date] = mapped_column(Date, index=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close_adj: Mapped[float] = mapped_column(Float)
    close_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger)
    matched_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    matched_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_adjustment_basis: Mapped[str] = mapped_column(String(32))
    volume_basis: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(48))


class V2Liquidity(Base):
    """Rolling-median liquidity for one ticker at its latest session."""

    __tablename__ = "v2_liquidity"

    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    adtv_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    adv_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    window: Mapped[int] = mapped_column(Integer)
    volume_basis: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date)


class V2MarketCap(Base):
    """Shares outstanding and full market cap at the latest reported period."""

    __tablename__ = "v2_market_cap"

    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    basis: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date)


class V2CorporateAction(Base):
    """A DIV/ISS corporate action stored for the quality checks and fallbacks."""

    __tablename__ = "v2_corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(16))
    exright_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date)


class V2Progress(Base):
    """Resumable checkpoint for one (dataset kind, ticker) unit of work."""

    __tablename__ = "v2_progress"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class V2AdjustmentFlag(Base):
    """Persisted adjustment-quality flag per ticker (one row, computed by the job).

    The row exists for every checked ticker, flagged or clean, so the reader can
    distinguish "no anomaly" from "flags were never computed" (empty table).
    """

    __tablename__ = "v2_adjustment_flags"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), default="ok")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    exclude_from_group_indices: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Per-anomaly dated records: {date, exclude, category, reason}. Nullable for rows
    #: written before the flag policy carried per-anomaly categories (D-019).
    anomalies: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date, index=True)


class V2FinancialRatio(Base):
    """One ticker's trimmed financial ratios for one reporting period."""

    __tablename__ = "v2_financial_ratios"

    symbol_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    period_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    ratio_group: Mapped[str] = mapped_column(String(16))
    ratios: Mapped[dict[str, float | None]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date, index=True)


class V2SectorStatistic(Base):
    """Precomputed peer statistics for one (sector, ratio, period, period_type)."""

    __tablename__ = "v2_sector_statistics"

    sector: Mapped[str] = mapped_column(String(128), primary_key=True)
    ratio: Mapped[str] = mapped_column(String(48), primary_key=True)
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    period_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, default=0)
    median: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    winsorized_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    p5: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_ranks: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(48))
    data_as_of: Mapped[date] = mapped_column(Date, index=True)
