"""Read-only aggregation helpers for the V2b ratio verification script.

The precompute job stores per-ticker trimmed ratios and precomputed sector
statistics. This module turns those stored records into the summary that
``scripts/verify_v2_ratios.py`` prints: coverage, per-group null shares, sector
peer counts and ratio-quality warnings. It is pure (no I/O), so the script stays a
thin read-only wrapper and the summary is unit-testable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from data.v2.precompute_schemas import RatioRecord, SectorStatisticRecord
from data.v2.ratio_quality import missing_ratio_tickers, run_ratio_quality_checks
from data.v2.ratios import RATIO_SETS, RatioGroup
from data.v2.schemas import FinancialRatios

#: Period types stored by the SSI ratio adapter, in display order.
PERIOD_TYPES: tuple[str, ...] = ("ttm", "annual", "quarter")


@dataclass(frozen=True)
class RatioVerification:
    """A compact, printable summary of the stored V2b ratio dataset."""

    tickers_with_ratios: list[str]
    latest_periods: dict[str, tuple[date, str]]
    latest_min: date | None
    latest_max: date | None
    latest_period_counts: dict[date, int]
    group_tickers: dict[str, int]
    null_share_latest_by_group: dict[str, dict[str, float]]
    null_share_by_period_type: dict[str, dict[str, dict[str, float]]]
    period_type_counts: dict[str, dict[str, int]]
    sector_peer_counts: dict[str, int]
    min_peers: int
    sectors_with_enough_peers: list[str]
    sector_statistic_rows: int
    quality_warning_counts: dict[str, int]
    tickers_without_ratios: list[str]


def latest_periods(records: Sequence[RatioRecord]) -> dict[str, tuple[date, str]]:
    """Return each ticker's newest ``(period, period_type)``."""
    latest: dict[str, tuple[date, str]] = {}
    for record in records:
        key = (record.period, record.period_type)
        current = latest.get(record.symbol)
        if current is None or key > current:
            latest[record.symbol] = key
    return latest


def latest_period_counts(records: Sequence[RatioRecord]) -> dict[date, int]:
    """Return how many tickers have each period as their newest stored period."""
    counts: dict[date, int] = {}
    for period, _period_type in latest_periods(records).values():
        counts[period] = counts.get(period, 0) + 1
    return dict(sorted(counts.items()))


def group_ticker_counts(records: Sequence[RatioRecord]) -> dict[str, int]:
    """Return the number of distinct tickers stored in each ratio group."""
    tickers: dict[str, set[str]] = {}
    for record in records:
        tickers.setdefault(record.ratio_group, set()).add(record.symbol)
    return {group: len(members) for group, members in sorted(tickers.items())}


def _null_shares(records: Sequence[RatioRecord]) -> dict[str, dict[str, float]]:
    """Return, per group and ratio, the share of ``records`` whose value is null."""
    rows_by_group: dict[RatioGroup, int] = {}
    nulls: dict[RatioGroup, dict[str, int]] = {}
    for record in records:
        group = record.ratio_group
        rows_by_group[group] = rows_by_group.get(group, 0) + 1
        group_nulls = nulls.setdefault(group, {})
        for ratio in RATIO_SETS[group]:
            if record.ratios.get(ratio) is None:
                group_nulls[ratio] = group_nulls.get(ratio, 0) + 1
    shares: dict[str, dict[str, float]] = {}
    for group, total in rows_by_group.items():
        shares[str(group)] = {
            ratio: nulls[group].get(ratio, 0) / total for ratio in RATIO_SETS[group]
        }
    return shares


def null_shares_by_group(records: Sequence[RatioRecord]) -> dict[str, dict[str, float]]:
    """Return, per group and ratio, the share of stored rows whose value is null."""
    return _null_shares(records)


def _latest_records(records: Sequence[RatioRecord]) -> list[RatioRecord]:
    """Return each ticker's record(s) at its newest stored period."""
    newest: dict[str, date] = {}
    for record in records:
        current = newest.get(record.symbol)
        if current is None or record.period > current:
            newest[record.symbol] = record.period
    return [record for record in records if record.period == newest[record.symbol]]


def null_shares_latest_by_group(records: Sequence[RatioRecord]) -> dict[str, dict[str, float]]:
    """Return the null share per group/ratio over each ticker's latest period only.

    Only the newest stored period of each ticker contributes, so the older
    quarter/annual rows (where SSI publishes many expected nulls) do not dilute
    the readiness figure the Fundamentals tab relies on.
    """
    return _null_shares(_latest_records(records))


def null_shares_by_period_type(
    records: Sequence[RatioRecord],
) -> dict[str, dict[str, dict[str, float]]]:
    """Return the null share per group -> period_type -> ratio over all rows."""
    shares: dict[str, dict[str, dict[str, float]]] = {}
    for group in sorted({str(record.ratio_group) for record in records}):
        for period_type in PERIOD_TYPES:
            subset = [
                record
                for record in records
                if str(record.ratio_group) == group and record.period_type == period_type
            ]
            if not subset:
                continue
            shares.setdefault(group, {})[period_type] = _null_shares(subset)[group]
    return shares


def period_type_counts(records: Sequence[RatioRecord]) -> dict[str, dict[str, int]]:
    """Return the number of stored rows per group and period type."""
    counts: dict[str, dict[str, int]] = {}
    for group in sorted({str(record.ratio_group) for record in records}):
        for period_type in PERIOD_TYPES:
            n = sum(
                1
                for record in records
                if str(record.ratio_group) == group and record.period_type == period_type
            )
            if n:
                counts.setdefault(group, {})[period_type] = n
    return counts


def sector_peer_counts(
    statistics: Sequence[SectorStatisticRecord], *, ratio: str = "roe"
) -> dict[str, int]:
    """Return each sector's representative peer count at its newest period.

    Uses the ``ratio``'s ``n`` at the sector's latest period when present, else the
    largest ``n`` for that period. ``n`` is the number of peers with a usable value.
    """
    latest: dict[str, date] = {}
    for stat in statistics:
        if stat.sector not in latest or stat.period > latest[stat.sector]:
            latest[stat.sector] = stat.period
    counts: dict[str, int] = {}
    for sector, period in latest.items():
        at_period = [stat for stat in statistics if stat.sector == sector and stat.period == period]
        preferred = next((stat.n for stat in at_period if stat.ratio == ratio), None)
        counts[sector] = preferred if preferred is not None else max(stat.n for stat in at_period)
    return dict(sorted(counts.items()))


def summarize_ratios(
    records: Sequence[RatioRecord],
    statistics: Sequence[SectorStatisticRecord],
    *,
    master: Sequence[str],
    sector_by_ticker: Mapping[str, str],
    as_of: date,
    min_peers: int = 5,
) -> RatioVerification:
    """Build the printable ratio-dataset summary (pure; no I/O)."""
    latest = latest_periods(records)
    peer_counts = sector_peer_counts(statistics)
    enough = sorted(sector for sector, count in peer_counts.items() if count >= min_peers)

    by_ticker: dict[str, list[FinancialRatios]] = {}
    for record in records:
        by_ticker.setdefault(record.symbol, []).append(
            FinancialRatios(
                ticker=record.symbol,
                period=record.period,
                period_type=record.period_type,
                provider=record.source,
                ratios=dict(record.ratios),
            )
        )
    warning_counts: dict[str, int] = {}
    for ticker in master:
        for finding in run_ratio_quality_checks(
            ticker,
            by_ticker.get(ticker, []),
            sector=sector_by_ticker.get(ticker),
            as_of=as_of,
        ):
            warning_counts[finding.check] = warning_counts.get(finding.check, 0) + 1

    periods = [period for period, _ in latest.values()]
    return RatioVerification(
        tickers_with_ratios=sorted(latest),
        latest_periods=latest,
        latest_min=min(periods) if periods else None,
        latest_max=max(periods) if periods else None,
        latest_period_counts=latest_period_counts(records),
        group_tickers=group_ticker_counts(records),
        null_share_latest_by_group=null_shares_latest_by_group(records),
        null_share_by_period_type=null_shares_by_period_type(records),
        period_type_counts=period_type_counts(records),
        sector_peer_counts=peer_counts,
        min_peers=min_peers,
        sectors_with_enough_peers=enough,
        sector_statistic_rows=len(statistics),
        quality_warning_counts=dict(sorted(warning_counts.items())),
        tickers_without_ratios=missing_ratio_tickers(master, list(by_ticker)),
    )


__all__ = [
    "PERIOD_TYPES",
    "RatioVerification",
    "group_ticker_counts",
    "latest_period_counts",
    "latest_periods",
    "null_shares_by_group",
    "null_shares_by_period_type",
    "null_shares_latest_by_group",
    "period_type_counts",
    "sector_peer_counts",
    "summarize_ratios",
]
