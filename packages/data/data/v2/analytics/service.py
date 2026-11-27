"""Assemble the Sector Analysis analytics payload from the stored V2 tables.

The service is the only analytics module that touches the database. It reads stock data
exclusively through :class:`data.v2.store.V2Store` (the V2 tables), benchmark index bars
through :class:`data.db.repositories.SqlIndexRepository` (``indices_daily``, the D-001
benchmark store), and the trading calendar from the stored VN-Index bar dates. Returns
are derived on read from the adjusted close (D-003). Nothing here fetches from the network.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from data.calendar import trading_days_from_dates
from data.db.base import session_scope
from data.db.repositories import SqlIndexRepository
from data.models import PriceBar
from data.v2.analytics.cache import cached_build
from data.v2.analytics.correlation import correlation_matrix
from data.v2.analytics.grouping import build_grouping, group_rows
from data.v2.analytics.index import (
    DEFAULT_SINGLE_STOCK_CAP,
    WEIGHTING_MARKET_CAP,
    GroupConstituent,
    GroupIndex,
    build_group_index,
)
from data.v2.analytics.liquidity import (
    DEFAULT_PRESET_ID,
    UniverseFilterSpec,
    filter_universe,
)
from data.v2.analytics.metrics import benchmark_metrics
from data.v2.analytics.schemas import (
    AdjustmentQualityFlag,
    AnalyticsPayload,
    DefaultExcludedTicker,
    GroupAnalytics,
    GroupIndexResult,
    UniverseRow,
    Window,
)
from data.v2.analytics.timeframes import resolve_window
from data.v2.analytics.universe_reader import (
    join_labels,
    load_adjustment_flags,
    load_universe_snapshot,
)
from data.v2.precompute_schemas import AdjustmentAnomalyRecord, ReturnPoint
from data.v2.returns import calendar_returns
from data.v2.schemas import AdjustedOHLCV
from data.v2.store import V2Store

#: Canonical benchmark codes and accepted aliases.
_BENCHMARK_ALIASES: dict[str, str] = {
    "VNINDEX": "VNINDEX",
    "VN-INDEX": "VNINDEX",
    "VN30": "VN30",
    "VN100": "VN100",
}


def _normalize_benchmark(value: str) -> str:
    """Return the canonical benchmark code for ``value``.

    Raises:
        ValueError: When ``value`` is not a supported benchmark.
    """
    key = value.strip().upper().replace(" ", "")
    try:
        return _BENCHMARK_ALIASES[key]
    except KeyError:
        expected = ", ".join(sorted(set(_BENCHMARK_ALIASES.values())))
        raise ValueError(
            f"unknown benchmark {value!r}; expected one of {expected}"
        ) from None


class AnalyticsRequest(BaseModel):
    """The user's Sector Analysis controls."""

    benchmark: str = "VNINDEX"
    timeframe: str = "1Y"
    custom_start: date | None = None
    grouping: str = "sector"
    liquidity_preset: str = DEFAULT_PRESET_ID
    sectors: list[str] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)
    exchange: str | None = None
    weighting: str = WEIGHTING_MARKET_CAP
    single_stock_cap: float | None = DEFAULT_SINGLE_STOCK_CAP
    end_date: date | None = None
    exclude_adjustment_flagged: bool = False
    include_default_excluded: bool = False


def _to_result(index: GroupIndex) -> GroupIndexResult:
    """Convert a built group index to its payload model."""
    return GroupIndexResult(
        group=index.group,
        status=index.status,
        constituent_count=index.constituent_count,
        constituents=index.constituents,
        excluded=index.excluded,
        weights=index.weights,
        cumulative_returns=index.cumulative_returns,
        warnings=index.warnings,
    )


def _benchmark_returns(bars: Sequence[PriceBar]) -> dict[date, float]:
    """Return the benchmark's simple daily returns keyed by date."""
    result: dict[date, float] = {}
    previous: float | None = None
    for bar in bars:
        if previous is not None and previous > 0:
            result[bar.date] = bar.close / previous - 1.0
        previous = bar.close
    return result


def _anomalies_in_range(
    anomalies: Sequence[AdjustmentAnomalyRecord],
    start: date,
    end: date,
) -> list[AdjustmentAnomalyRecord]:
    """Return the return-corrupting anomalies whose date falls in ``[start, end]``."""
    return [
        anomaly
        for anomaly in anomalies
        if anomaly.exclude and start <= anomaly.date <= end
    ]


def _flag_affects_window(
    flag: AdjustmentQualityFlag, start: date, end: date
) -> bool:
    """Return ``True`` when ``flag`` should exclude its ticker for ``[start, end]``.

    With structured, dated anomalies the exclusion is window-aware: a name is dropped
    only when a return-corrupting anomaly falls inside the window (plus the first return
    day's source session). A stale flag written under an older policy carries no dated
    anomalies, so it falls back to the whole-history ``exclude_from_group_indices`` hint
    and the UI shows the "outdated" caveat until it is refreshed.
    """
    if flag.anomalies:
        return bool(_anomalies_in_range(flag.anomalies, start, end))
    return flag.exclude_from_group_indices


def _excluded_ticker(
    row: UniverseRow,
    flag: AdjustmentQualityFlag,
    hits: Sequence[AdjustmentAnomalyRecord],
    *,
    fallback_reasons: Sequence[str] = (),
) -> DefaultExcludedTicker:
    """Build one excluded-ticker panel entry from the in-window anomaly hits."""
    if hits:
        return DefaultExcludedTicker(
            ticker=row.ticker,
            sector=row.sector,
            severity=flag.severity,
            reason=hits[0].reason,
            category=hits[0].category,
            affected_dates=sorted({anomaly.date for anomaly in hits}),
            reasons=[
                f"{anomaly.reason} on {anomaly.date.isoformat()}" for anomaly in hits
            ],
        )
    reasons = list(fallback_reasons)
    return DefaultExcludedTicker(
        ticker=row.ticker,
        sector=row.sector,
        severity=flag.severity,
        reason=reasons[0] if reasons else "adjustment-quality flag",
        reasons=reasons,
    )


class AnalyticsService:
    """Assemble the Sector Analysis payload from the stored V2 tables."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        rules: MarketRules = DEFAULT_MARKET_RULES,
    ) -> None:
        self._session_factory = session_factory
        self._rules = rules

    def build(self, request: AnalyticsRequest) -> AnalyticsPayload:
        """Return one serialisable analytics payload for ``request``.

        Raises:
            ValueError: When there is no stored data, the window has fewer than two
                trading days, or an option id is unknown.
        """
        benchmark_code = _normalize_benchmark(request.benchmark)
        warnings: list[str] = []

        # 1. Read the bulk inputs through the shared universe reader.
        snapshot = load_universe_snapshot(self._session_factory)
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            calendar = trading_days_from_dates(store.list_index_dates("VNINDEX"))
            benchmark_latest = SqlIndexRepository(session).latest_date(benchmark_code)

        stored_dates = [
            day for day in (snapshot.latest_price_date, benchmark_latest) if day is not None
        ]
        if not stored_dates:
            raise ValueError("no stored price or benchmark data to analyse")
        data_as_of = max(stored_dates)

        # 2. Resolve and clamp the window to the stored history.
        requested = resolve_window(
            request.timeframe,
            request.end_date or data_as_of,
            custom_start=request.custom_start,
        )
        calendar_in_range = sorted(day for day in calendar if day <= requested.end)
        if not calendar_in_range:
            raise ValueError("no stored trading days in the requested window")
        earliest = calendar_in_range[0]
        effective_start = max(requested.start, earliest)
        if effective_start > requested.start:
            warnings.append(
                f"requested {requested.label} window starts "
                f"{requested.start.isoformat()} but stored history begins "
                f"{earliest.isoformat()}; using the available data"
            )
        effective_days = sorted(
            day for day in calendar if effective_start <= day <= requested.end
        )
        if len(effective_days) < 2:
            raise ValueError("fewer than two stored trading days in the requested window")
        window = Window(
            label=requested.label, start=effective_days[0], end=effective_days[-1]
        )
        # Window-aware flag exclusion. The first in-window return is computed from the
        # close on the session just before the window start, so include that session's
        # anomaly dates too ("the analysis window plus the first return day").
        _prior_days = [day for day in calendar if day < window.start]
        exclusion_start = max(_prior_days) if _prior_days else window.start

        # 3. Score, filter and group the universe (rows come from the shared reader).
        rows = snapshot.rows
        filtered = filter_universe(
            rows,
            request.liquidity_preset,
            UniverseFilterSpec(
                sectors=frozenset(request.sectors),
                indexes=frozenset(request.indexes),
                exchange=request.exchange,
            ),
            as_of=data_as_of,
        )
        kept = filtered.kept
        if not kept:
            warnings.append("no tickers pass the selected filters")

        # 4. Load per-ticker closes (3 columns in one batched query) and benchmark bars.
        price_from = window.start - timedelta(days=14)
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            close_pairs = store.get_close_prices_batch(
                [row.ticker for row in kept], price_from, window.end
            )
            benchmark_bars = SqlIndexRepository(session).get_range(
                benchmark_code, price_from, window.end
            )
        bars_by_ticker: dict[str, list[AdjustedOHLCV]] = {
            row.ticker: [
                AdjustedOHLCV(
                    date=bar_date,
                    open=close_val,
                    high=close_val,
                    low=close_val,
                    close=close_val,
                    volume=0,
                    source="",
                )
                for bar_date, close_val in close_pairs.get(row.ticker.upper(), [])
            ]
            for row in kept
        }

        returns_by_ticker: dict[str, dict[date, float]] = {}
        stored_flags, flags_available, flags_policy_current = load_adjustment_flags(
            self._session_factory
        )
        flags: dict[str, AdjustmentQualityFlag] = {}
        for row in kept:
            returns_by_ticker[row.ticker] = {
                day: value
                for day, value in calendar_returns(
                    bars_by_ticker[row.ticker], calendar_in_range
                ).items()
                if window.start <= day <= window.end
            }
            flags[row.ticker] = stored_flags.get(
                row.ticker, AdjustmentQualityFlag(ticker=row.ticker)
            )
        benchmark_series = {
            day: value
            for day, value in _benchmark_returns(benchmark_bars).items()
            if window.start <= day <= window.end
        }
        if not benchmark_series:
            warnings.append(f"benchmark {benchmark_code} has no stored bars in the window")

        benchmark_level = 1.0
        benchmark_returns: list[ReturnPoint] = [ReturnPoint(date=window.start, value=0.0)]
        for day in effective_days[1:]:
            value = benchmark_series.get(day)
            if value is not None:
                benchmark_level *= 1.0 + value
            benchmark_returns.append(ReturnPoint(date=day, value=(benchmark_level - 1.0) * 100.0))

        # -- build group indices and the correlation matrix -----------------
        grouping = build_grouping(request.grouping)
        groups = group_rows(kept, grouping)
        group_analytics: list[GroupAnalytics] = []
        correlation_series: dict[str, dict[date, float]] = {}
        default_excluded: list[DefaultExcludedTicker] = []
        default_excluded_outside_window: list[DefaultExcludedTicker] = []
        for row in kept:
            flag = flags[row.ticker]
            if row.sector is None or not flag.exclude_from_group_indices:
                continue
            if flag.anomalies:
                window_hits = _anomalies_in_range(
                    flag.anomalies, exclusion_start, window.end
                )
                if window_hits:
                    default_excluded.append(_excluded_ticker(row, flag, window_hits))
                    continue
                outside_hits = [
                    anomaly
                    for anomaly in flag.anomalies
                    if anomaly.exclude
                    and not (exclusion_start <= anomaly.date <= window.end)
                ]
                if outside_hits:
                    default_excluded_outside_window.append(
                        _excluded_ticker(row, flag, outside_hits)
                    )
                continue
            # Legacy (pre-D-019) flag with no dated anomalies: keep excluding whole-history
            # and show the "outdated" caveat until the flags are recomputed.
            default_excluded.append(
                _excluded_ticker(row, flag, [], fallback_reasons=flag.reasons)
            )
        for label in sorted(groups):
            constituents: list[GroupConstituent] = []
            pre_excluded: dict[str, str] = {}
            default_excluded_count = 0
            for row in groups[label]:
                flag = flags[row.ticker]
                if _flag_affects_window(
                    flag, exclusion_start, window.end
                ) and not request.include_default_excluded:
                    pre_excluded[row.ticker] = (
                        "excluded: adjustment-quality flag (return-corrupting glitch "
                        "in this window)"
                    )
                    default_excluded_count += 1
                    continue
                if request.exclude_adjustment_flagged and flag.flagged:
                    pre_excluded[row.ticker] = "excluded: adjustment-quality flag"
                    continue
                constituents.append(
                    GroupConstituent(
                        ticker=row.ticker,
                        returns=returns_by_ticker[row.ticker],
                        market_cap=row.market_cap,
                    )
                )
            index = build_group_index(
                label,
                constituents,
                trading_days=calendar,
                start=window.start,
                end=window.end,
                weighting=request.weighting,
                single_stock_cap=request.single_stock_cap,
                pre_excluded=pre_excluded,
            )
            metrics = benchmark_metrics(
                label,
                index.daily_returns,
                benchmark_series,
                benchmark=benchmark_code,
                constituent_count=index.constituent_count,
            )
            group_analytics.append(
                GroupAnalytics(
                    index=_to_result(index),
                    metrics=metrics,
                    default_excluded_count=default_excluded_count,
                )
            )
            if index.status == "ok":
                correlation_series[label] = index.daily_returns
            else:
                warnings.append(f"group {label}: insufficient constituents")

        correlation = (
            correlation_matrix(correlation_series)
            if len(correlation_series) >= 2
            else None
        )

        flagged = [flags[row.ticker] for row in kept if flags[row.ticker].flagged]
        if flagged:
            warnings.append(
                f"{len(flagged)} ticker(s) have adjustment-quality flags; set "
                "exclude_adjustment_flagged=True to drop them from the indices"
            )
        elif not flags_available:
            warnings.append(
                "Adjustment-quality flags have not been computed yet; run the "
                "precompute job to populate them."
            )
        if flags_available and not flags_policy_current:
            warnings.append(
                "Adjustment-quality flags were computed under an older policy; rerun "
                "the update (or the --recompute-flags job) to refresh them."
            )
        warnings.append(
            "Constituents are fixed at the end date (current-constituents index). A stock "
            "with less than 80% of the window's trading days is excluded and weights "
            "renormalise; a remaining gap (halt or new listing) is dropped from that day's "
            "return and the other weights renormalise."
        )
        price_basis = join_labels(
            [snapshot.price_adjustment_bases.get(row.ticker, "") for row in kept]
        )
        volume_basis = join_labels(
            [
                snapshot.liquidity[row.ticker].volume_basis
                for row in kept
                if row.ticker in snapshot.liquidity
            ]
        )
        return AnalyticsPayload(
            data_as_of=data_as_of,
            generated_at=datetime.now(UTC),
            grouping=request.grouping,
            weighting=request.weighting,
            benchmark=benchmark_code,
            window=window,
            benchmark_returns=benchmark_returns,
            liquidity_preset=filtered.preset_id,
            price_adjustment_basis=price_basis,
            volume_basis=volume_basis,
            market_cap_basis="full",
            groups=group_analytics,
            correlation=correlation,
            adjustment_flags=flagged,
            default_excluded=default_excluded,
            default_excluded_outside_window=default_excluded_outside_window,
            flags_available=flags_available,
            flags_policy_current=flags_policy_current,
            include_default_excluded=request.include_default_excluded,
            warnings=warnings,
        )

    def build_cached(
        self, request: AnalyticsRequest
    ) -> tuple[AnalyticsPayload, bool, float]:
        """Return (payload, served_from_cache, elapsed_ms) for request.

        The cache key is the request settings; the stored data_as_of invalidates it, so a
        precompute that advances the data date evicts the entry. The elapsed time is 0.0
        on a hit.
        """
        benchmark_code = _normalize_benchmark(request.benchmark)
        data_as_of = self._latest_data_as_of(benchmark_code)
        return cached_build(
            _request_key(request, benchmark_code),
            data_as_of,
            lambda: self.build(request),
        )

    def _latest_data_as_of(self, benchmark_code: str) -> date | None:
        """Return the newest stored stock/benchmark date (a cheap two-read probe)."""
        with session_scope(self._session_factory) as session:
            store = V2Store(session)
            price_latest = store.overall_latest_price_date()
            benchmark_latest = SqlIndexRepository(session).latest_date(benchmark_code)
        dates = [day for day in (price_latest, benchmark_latest) if day is not None]
        return max(dates) if dates else None


def _request_key(
    request: AnalyticsRequest, benchmark_code: str
) -> tuple[object, ...]:
    """Return a hashable cache key from the request settings (no per-request fields)."""
    return (
        benchmark_code,
        request.timeframe,
        request.custom_start,
        request.end_date,
        request.grouping,
        request.liquidity_preset,
        tuple(sorted(set(request.sectors))),
        tuple(sorted(set(request.indexes))),
        request.exchange,
        request.weighting,
        round(request.single_stock_cap, 4) if request.single_stock_cap is not None else None,
        request.exclude_adjustment_flagged,
        request.include_default_excluded,
    )


__all__ = ["AnalyticsRequest", "AnalyticsService"]



