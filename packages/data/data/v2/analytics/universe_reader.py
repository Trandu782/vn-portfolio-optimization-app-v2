"""Shared assembly of the scored universe from the stored V2 tables.

Both the Sector Analysis service and the read-only ``/v2/universe`` endpoint build
the same :class:`UniverseRow` candidates here, so identical settings hand
:func:`data.v2.analytics.liquidity.filter_universe` identical inputs and therefore
return identical tickers. This module is also the one place that reads the
persisted adjustment-quality flags (computed once by the precompute job), so a
read endpoint never recomputes them per request.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from data.db.base import session_scope
from data.v2.adjustment_quality import FLAGS_POLICY_VERSION, policy_from_source
from data.v2.analytics.schemas import AdjustmentQualityFlag, UniverseRow
from data.v2.precompute_schemas import (
    AdjustmentFlagRecord,
    LiquidityRecord,
    MarketCapRecord,
    TickerRecord,
)
from data.v2.store import V2Store


@dataclass(frozen=True)
class UniverseSnapshot:
    """The stored bulk inputs, the scored rows and the flag availability.

    ``flags_available`` is False when the ``v2_adjustment_flags`` table is empty
    (the job has not run yet), which lets a caller distinguish "not computed yet"
    from "computed and clean".
    """

    master: list[TickerRecord]
    rows: list[UniverseRow]
    sector_by_ticker: dict[str, str]
    liquidity: dict[str, LiquidityRecord]
    market_caps: dict[str, MarketCapRecord]
    price_adjustment_bases: dict[str, str]
    latest_price_date: date | None
    sector_gaps: list[str]
    flags_available: bool


def build_universe_row(
    record: TickerRecord,
    sector_by_ticker: Mapping[str, str],
    membership: Mapping[str, set[str]],
    liquidity: Mapping[str, LiquidityRecord],
    market_caps: Mapping[str, MarketCapRecord],
) -> UniverseRow:
    """Build one scored universe row from the stored per-ticker records."""
    ticker = record.ticker.strip().upper()
    liquidity_record = liquidity.get(ticker)
    market_cap_record = market_caps.get(ticker)
    return UniverseRow(
        ticker=ticker,
        exchange=record.exchange.strip().upper(),
        sector=sector_by_ticker.get(ticker),
        index_memberships=frozenset(membership.get(ticker, set())),
        adtv_median=liquidity_record.adtv_median if liquidity_record else None,
        adv_median=liquidity_record.adv_median if liquidity_record else None,
        market_cap=market_cap_record.market_cap if market_cap_record else None,
        volume_basis=liquidity_record.volume_basis if liquidity_record else None,
        market_cap_basis=market_cap_record.basis if market_cap_record else "full",
    )


def join_labels(values: Sequence[str]) -> str | None:
    """Join distinct non-empty labels with ``+`` (``None`` when there are none)."""
    unique = sorted({value for value in values if value})
    return "+".join(unique) if unique else None


def load_universe_snapshot(session_factory: sessionmaker[Session]) -> UniverseSnapshot:
    """Load the bulk V2 inputs once and score every candidate into a row."""
    with session_scope(session_factory) as session:
        store = V2Store(session)
        master = store.list_ticker_master()
        sector_by_ticker = {
            sector.ticker.strip().upper(): sector.icb_level2_name
            for sector in store.list_sectors()
            if sector.icb_level2_name
        }
        membership: dict[str, set[str]] = {}
        for index_code in ("VN30", "VN100"):
            for ticker in store.get_membership(index_code):
                membership.setdefault(ticker.strip().upper(), set()).add(index_code)
        liquidity = {
            record.symbol.strip().upper(): record for record in store.list_liquidity()
        }
        market_caps = {
            record.symbol.strip().upper(): record for record in store.list_market_cap()
        }
        bases = store.price_adjustment_bases()
        latest_price = store.overall_latest_price_date()
        flags_available = store.adjustment_flags_available()

    rows = [
        build_universe_row(record, sector_by_ticker, membership, liquidity, market_caps)
        for record in master
    ]
    sector_gaps = sorted(
        record.ticker.strip().upper()
        for record in master
        if record.ticker.strip().upper() not in sector_by_ticker
    )
    return UniverseSnapshot(
        master=master,
        rows=rows,
        sector_by_ticker=sector_by_ticker,
        liquidity=liquidity,
        market_caps=market_caps,
        price_adjustment_bases=bases,
        latest_price_date=latest_price,
        sector_gaps=sector_gaps,
        flags_available=flags_available,
    )


def _to_flag(record: AdjustmentFlagRecord) -> AdjustmentQualityFlag:
    """Convert a stored flag record to the analytics payload model."""
    return AdjustmentQualityFlag(
        ticker=record.ticker,
        severity=record.severity,
        flagged=record.flagged,
        exclude_from_group_indices=record.exclude_from_group_indices,
        reasons=list(record.reasons),
        dates=list(record.dates),
        anomalies=list(record.anomalies),
    )


def flags_policy_current(records: Sequence[AdjustmentFlagRecord]) -> bool:
    """Return ``True`` when every stored flag row was produced by the current policy.

    The policy version is embedded in each row's ``source`` (see
    :func:`data.v2.adjustment_quality.flag_source`), so rows written under an older rule
    set — or before versioning existed — are detected as stale without a schema change.
    An empty table is not "current": there is nothing to trust yet.
    """
    return bool(records) and all(
        policy_from_source(record.source) == FLAGS_POLICY_VERSION for record in records
    )


def load_adjustment_flags(
    session_factory: sessionmaker[Session],
) -> tuple[dict[str, AdjustmentQualityFlag], bool, bool]:
    """Return the stored flags, whether they were computed, and whether they are current."""
    with session_scope(session_factory) as session:
        records = V2Store(session).list_adjustment_flags()
    return (
        {record.ticker: _to_flag(record) for record in records},
        bool(records),
        flags_policy_current(records),
    )


__all__ = [
    "UniverseSnapshot",
    "build_universe_row",
    "flags_policy_current",
    "join_labels",
    "load_adjustment_flags",
    "load_universe_snapshot",
]
