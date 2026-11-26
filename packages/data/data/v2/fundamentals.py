"""Sector peer statistics and the read-side Fundamentals service (V2b).

The precompute job stores each ticker's trimmed ratios and a precomputed default
("all peers") sector statistic. This module has two jobs:

1. Pure aggregation: turn a bag of per-ticker ratio values into the spec's peer
   statistics (median, mean, winsorized mean, quantiles, N) plus a per-ticker
   percentile rank, excluding non-positive valuation multiples as "n/m".
2. Read-side peer variants: the Fundamentals service selects the peer set (all
   peers, the active liquidity preset, or VN100) for one ICB level-2 sector and
   compares a ticker's value against it. Financials are never compared with
   non-financials because the peer set is always the same ICB level-2 sector.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from statistics import fmean
from statistics import median as _median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import session_scope
from data.v2.analytics.liquidity import (
    DEFAULT_PRESET_ID,
    UniverseFilterSpec,
    filter_universe,
    get_preset,
)
from data.v2.analytics.universe_reader import UniverseSnapshot, load_universe_snapshot
from data.v2.precompute_schemas import RatioRecord, SectorStatisticRecord
from data.v2.ratios import (
    RATIO_SETS,
    category_label,
    direction_for,
    include_in_stats,
    is_percentage_ratio,
    percentile,
    percentile_rank,
    ratio_category,
    ratio_group_for,
    ratio_label,
    winsorized_mean,
)
from data.v2.store import V2Store

#: Peer-set variants the Fundamentals toggle offers.
PeerVariant = Literal["all", "liquidity", "vn100"]


def _usable_values(
    ratio: str, ticker_values: Mapping[str, float | None]
) -> list[float]:
    """Return the sorted usable values for ``ratio`` (excluding missing and "n/m").

    Mirrors the filtering inside :func:`compute_sector_statistic` so the box-plot
    quartiles describe exactly the same peer set as the median and N.
    """
    return sorted(
        value
        for value in ticker_values.values()
        if value is not None and include_in_stats(ratio, value)
    )


def compute_sector_statistic(
    sector: str,
    ratio: str,
    period: date,
    period_type: str,
    ticker_values: Mapping[str, float | None],
    *,
    source: str,
    data_as_of: date,
) -> SectorStatisticRecord:
    """Aggregate one (sector, ratio, period) into the spec's peer statistics.

    Missing values and non-positive valuation multiples (P/E, P/B) are excluded from
    every statistic; a ticker with no usable value is simply absent from the
    percentile ranks. ``percentile_ranks`` maps each included ticker to its
    percentile rank (0-100) within the peer set, and ``n`` is that included count.
    """
    kept = {
        ticker: value
        for ticker, value in ticker_values.items()
        if value is not None and include_in_stats(ratio, value)
    }
    ordered = sorted(kept.values())
    n = len(ordered)
    ranks = {ticker: percentile_rank(ordered, value) for ticker, value in kept.items()}
    if n == 0:
        return SectorStatisticRecord(
            sector=sector,
            ratio=ratio,
            period=period,
            period_type=period_type,  # type: ignore[arg-type]
            n=0,
            percentile_ranks={},
            source=source,
            data_as_of=data_as_of,
        )
    return SectorStatisticRecord(
        sector=sector,
        ratio=ratio,
        period=period,
        period_type=period_type,  # type: ignore[arg-type]
        n=n,
        median=_median(ordered),
        mean=fmean(ordered),
        winsorized_mean=winsorized_mean(ordered),
        p5=percentile(ordered, 5.0),
        p95=percentile(ordered, 95.0),
        minimum=ordered[0],
        maximum=ordered[-1],
        percentile_ranks=ranks,
        source=source,
        data_as_of=data_as_of,
    )

def aggregate_sector_statistics(
    records: Sequence[RatioRecord],
    sector_by_ticker: Mapping[str, str],
    *,
    source: str,
    data_as_of: date,
) -> list[SectorStatisticRecord]:
    """Group per-ticker ratios by (sector, ratio, period, period_type) and aggregate."""
    grouped: dict[tuple[str, str, date, str], dict[str, float]] = {}
    for record in records:
        sector = sector_by_ticker.get(record.symbol)
        if not sector:
            continue
        for ratio, value in record.ratios.items():
            if value is None:
                continue
            grouped.setdefault((sector, ratio, record.period, record.period_type), {})[
                record.symbol
            ] = value
    return [
        compute_sector_statistic(
            sector, ratio, period, period_type, values, source=source, data_as_of=data_as_of
        )
        for (sector, ratio, period, period_type), values in sorted(grouped.items())
    ]


def select_peer_tickers(
    snapshot: UniverseSnapshot,
    sector: str,
    *,
    variant: PeerVariant = "all",
    preset_id: str = DEFAULT_PRESET_ID,
) -> list[str]:
    """Return the peer tickers for ``sector`` under a peer variant.

    ``all`` = every ticker in the sector; ``liquidity`` = sector peers passing the
    active liquidity preset; ``vn100`` = sector peers that are VN100 members. The
    sector is the whole peer universe, so banks/securities never mix with
    non-financials. Reuses :func:`data.v2.analytics.liquidity.filter_universe` so
    the Fundamentals and Optimize filters agree.
    """
    if variant == "all":
        preset, filters = "all_stocks", UniverseFilterSpec(sectors=frozenset({sector}))
    elif variant == "liquidity":
        get_preset(preset_id)  # validate the id (raises KeyError on an unknown one)
        preset, filters = preset_id, UniverseFilterSpec(sectors=frozenset({sector}))
    elif variant == "vn100":
        preset, filters = "all_stocks", UniverseFilterSpec(
            sectors=frozenset({sector}), indexes=frozenset({"VN100"})
        )
    else:
        raise ValueError(f"unknown peer variant {variant!r}; expected all, liquidity or vn100")
    result = filter_universe(snapshot.rows, preset, filters)
    return sorted(row.ticker for row in result.kept)


class PeerStatistic(BaseModel):
    """The peer distribution a ticker is compared against, for one ratio.

    The summary statistics feed the detail table; the quartiles and extremes let the
    UI draw a box plot of the sector distribution with the ticker marked.
    """

    model_config = ConfigDict(frozen=True)

    n: int = 0
    median: float | None = None
    mean: float | None = None
    winsorized_mean: float | None = None
    p5: float | None = None
    p95: float | None = None
    q1: float | None = None
    q3: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    percentile_rank: float | None = None


class RatioPeerComparison(BaseModel):
    """One ratio's value for a ticker plus its peer distribution and rank."""

    model_config = ConfigDict(frozen=True)

    ratio: str
    label: str
    category: str
    category_label: str
    is_percentage: bool = False
    direction: str = "neutral"
    value: float | None = None
    not_meaningful: bool = False
    peers: PeerStatistic = Field(default_factory=PeerStatistic)


class FundamentalsComparison(BaseModel):
    """The full per-ratio peer comparison for one ticker, period and peer variant."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    sector: str | None = None
    ratio_group: str
    period: date
    period_type: str
    variant: str
    provider: str | None = None
    data_as_of: date | None = None
    ratios: list[RatioPeerComparison] = Field(default_factory=list)


class FundamentalsService:
    """Serve peer comparisons for one ticker under a selectable peer variant."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def periods(self, symbol: str) -> list[tuple[date, str]]:
        """Return the stored ``(period, period_type)`` pairs for ``symbol``, newest first."""
        with session_scope(self._session_factory) as session:
            return V2Store(session).list_ratio_periods(symbol)

    def compare(
        self,
        symbol: str,
        *,
        period: date,
        period_type: str,
        variant: PeerVariant = "all",
        preset_id: str = DEFAULT_PRESET_ID,
    ) -> FundamentalsComparison:
        """Compare ``symbol`` against its sector peers under ``variant``.

        Raises:
            ValueError: When the ticker has no ICB level-2 sector (peer comparison
                is impossible without a peer group), or the variant is unknown.
        """
        code = symbol.strip().upper()
        snapshot = load_universe_snapshot(
            self._session_factory, include_price_bases=False
        )
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            sector_record = store.get_sector(code)
            target = store.get_ratio(code, period, period_type)
        if sector_record is None or not sector_record.icb_level2_name:
            raise ValueError(
                f"{code} has no ICB level-2 sector; peer comparison is unavailable"
            )
        sector = sector_record.icb_level2_name
        group = ratio_group_for(sector)
        peer_tickers = select_peer_tickers(
            snapshot, sector, variant=variant, preset_id=preset_id
        )
        with session_scope(self._session_factory) as session:
            records = V2Store(session).list_ratios_for_symbols(
                peer_tickers, period=period, period_type=period_type
            )
        values_by_ratio: dict[str, dict[str, float | None]] = {}
        for record in records:
            for ratio, value in record.ratios.items():
                values_by_ratio.setdefault(ratio, {})[record.symbol] = value
        target_ratios = target.ratios if target is not None else {}
        source = target.source if target is not None else "ssi_statistics"
        data_as_of = target.data_as_of if target is not None else date.today()
        comparisons: list[RatioPeerComparison] = []
        for ratio in RATIO_SETS[group]:
            stat = compute_sector_statistic(
                sector,
                ratio,
                period,
                period_type,
                values_by_ratio.get(ratio, {}),
                source=source,
                data_as_of=data_as_of,
            )
            ordered = _usable_values(ratio, values_by_ratio.get(ratio, {}))
            target_value = target_ratios.get(ratio)
            category = ratio_category(ratio)
            comparisons.append(
                RatioPeerComparison(
                    ratio=ratio,
                    label=ratio_label(ratio),
                    category=category,
                    category_label=category_label(category),
                    is_percentage=is_percentage_ratio(ratio),
                    direction=direction_for(ratio),
                    value=target_value,
                    not_meaningful=not include_in_stats(ratio, target_value),
                    peers=PeerStatistic(
                        n=stat.n,
                        median=stat.median,
                        mean=stat.mean,
                        winsorized_mean=stat.winsorized_mean,
                        p5=stat.p5,
                        p95=stat.p95,
                        q1=percentile(ordered, 25.0) if ordered else None,
                        q3=percentile(ordered, 75.0) if ordered else None,
                        minimum=stat.minimum,
                        maximum=stat.maximum,
                        percentile_rank=stat.percentile_ranks.get(code),
                    ),
                )
            )
        return FundamentalsComparison(
            symbol=code,
            sector=sector,
            ratio_group=group,
            period=period,
            period_type=period_type,
            variant=variant,
            provider=source,
            data_as_of=data_as_of,
            ratios=comparisons,
        )


__all__ = [
    "FundamentalsComparison",
    "FundamentalsService",
    "PeerStatistic",
    "PeerVariant",
    "RatioPeerComparison",
    "aggregate_sector_statistics",
    "compute_sector_statistic",
    "select_peer_tickers",
]
