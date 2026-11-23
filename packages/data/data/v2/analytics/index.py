"""Group-index construction (``docs/V2_SPEC.md`` section 5).

The built index is a **current-constituents index**: the constituents are fixed at the
end date (there is no rolling re-screen), the current ICB sector map is applied to
history, and the stored market-cap snapshot is a single value. Consequently the
market-cap target weights are constant across the window and the quarterly rebalance
re-applies the same cap-cleaned target to the drifted weights at each quarter end.

Gap handling
------------
* A constituent with fewer than ``min_coverage`` (default 80%) of the window's trading
  days is excluded and the weights renormalise. The trading-day denominator comes from
  the stored VN-Index bar dates, so a real halt or a mid-window listing is handled
  honestly (the payload documents this).
* On a day where an included constituent has no bar, that constituent is dropped from
  that day's weighted return and the remaining weights renormalise, so a halt cannot
  fabricate a return.

A group with fewer than ``min_constituents`` (default 3) after the rules returns
``status="insufficient"`` with an empty path rather than a misleading line.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import ceil
from typing import Literal

from data.v2.precompute_schemas import ReturnPoint

#: Default trailing-coverage floor for the 80%-of-trading-days rule.
DEFAULT_COVERAGE = 0.80
#: Default optional single-stock cap.
DEFAULT_SINGLE_STOCK_CAP = 0.15
#: A group needs at least this many constituents to publish an index.
MIN_CONSTITUENTS = 3
#: Market-cap weighting, or equal weight.
WEIGHTING_MARKET_CAP = "market_cap"
WEIGHTING_EQUAL = "equal"

#: A built index is either publishable or too thin to publish.
GroupIndexStatus = Literal["ok", "insufficient"]


@dataclass(frozen=True)
class GroupConstituent:
    """One candidate constituent with its derived daily returns and market cap."""

    ticker: str
    returns: Mapping[date, float]
    market_cap: float | None = None


@dataclass(frozen=True)
class GroupIndex:
    """A built group index with its daily paths (internal; the payload drops the daily)."""

    group: str
    status: GroupIndexStatus
    constituent_count: int
    constituents: list[str]
    excluded: dict[str, str]
    weights: dict[str, float]
    daily_returns: dict[date, float]
    cumulative_returns: list[ReturnPoint]
    warnings: list[str]


def _proportional(scores: Mapping[str, float]) -> dict[str, float]:
    """Return ``scores`` normalised to sum to one (equal split when all are zero)."""
    if not scores:
        return {}
    total = sum(scores.values())
    if total <= 0:
        share = 1.0 / len(scores)
        return dict.fromkeys(scores, share)
    return {key: value / total for key, value in scores.items()}


def apply_cap(
    weights: Mapping[str, float], cap: float | None
) -> tuple[dict[str, float], bool]:
    """Return ``(weights, cap_applied)`` with a single-name cap redistributed.

    The excess above ``cap`` is redistributed proportionally among the names still below
    the cap (water-filling) until no name exceeds it, so the result sums to one and
    respects the cap whenever the cap is feasible (``cap * n >= 1``). An infeasible cap
    (for example 15% over only three names) is left off and reported as not applied.
    """
    if not weights:
        return {}, False
    if cap is None or cap <= 0 or cap >= 1.0:
        return _proportional(weights), False
    if cap * len(weights) < 1.0 - 1e-12:
        return _proportional(weights), False
    capped_weights = dict(weights)
    capped: set[str] = set()
    for _ in range(len(capped_weights) + 1):
        over = [
            key
            for key, value in capped_weights.items()
            if key not in capped and value > cap + 1e-12
        ]
        if not over:
            break
        for key in over:
            capped.add(key)
            capped_weights[key] = cap
        remaining = 1.0 - cap * len(capped)
        free_total = sum(
            value for key, value in capped_weights.items() if key not in capped
        )
        if free_total <= 0:
            break
        for key in capped_weights:
            if key not in capped:
                capped_weights[key] = capped_weights[key] / free_total * remaining
    return capped_weights, True


def target_weights(
    constituents: Sequence[GroupConstituent],
    weighting: str,
    cap: float | None,
) -> tuple[dict[str, float], bool, list[str]]:
    """Return ``(weights, cap_applied, warnings)`` for the group's constituents.

    Market-cap weighting uses the stored full market cap. A constituent without a
    market cap is dropped by the caller before this call, so the scores here are
    complete.
    """
    warnings: list[str] = []
    if weighting == WEIGHTING_EQUAL:
        raw: dict[str, float] = dict.fromkeys(
            (item.ticker for item in constituents), 1.0
        )
    elif weighting == WEIGHTING_MARKET_CAP:
        raw = {
            item.ticker: float(item.market_cap)
            for item in constituents
            if item.market_cap is not None
        }
    else:
        raise ValueError(f"unknown weighting {weighting!r}")
    weights, applied = apply_cap(_proportional(raw), cap)
    if cap is not None and not applied and len(weights) > 0:
        warnings.append(
            f"single-stock cap {cap:.0%} is infeasible with {len(weights)} constituents; "
            "weights are left uncapped"
        )
    return weights, applied, warnings


def _window_days(trading_days: frozenset[date], start: date, end: date) -> list[date]:
    """Return the trading days in ``[start, end]``, ascending."""
    return sorted(day for day in trading_days if start <= day <= end)


def _quarter_end_candidates(start: date, end: date) -> list[date]:
    """Return the calendar quarter-end dates strictly after ``start`` and up to ``end``."""
    boundaries: list[date] = []
    for year in range(start.year, end.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            boundary = date(year, month, day)
            if start < boundary <= end:
                boundaries.append(boundary)
    return boundaries


def _rebalance_days(window: Sequence[date]) -> set[date]:
    """Return the first window day plus the last trading day on/before each quarter end."""
    days: set[date] = {window[0]}
    for boundary in _quarter_end_candidates(window[0], window[-1]):
        eligible = [day for day in window if day <= boundary]
        if eligible:
            days.add(eligible[-1])
    return days


def _insufficient(
    group: str,
    eligible: Sequence[GroupConstituent],
    excluded: dict[str, str],
    reason: str,
) -> GroupIndex:
    """Return an ``insufficient`` group index with a plain-language reason."""
    return GroupIndex(
        group=group,
        status="insufficient",
        constituent_count=len(eligible),
        constituents=sorted(item.ticker for item in eligible),
        excluded=excluded,
        weights={},
        daily_returns={},
        cumulative_returns=[],
        warnings=[reason],
    )


def build_group_index(
    group: str,
    constituents: Sequence[GroupConstituent],
    *,
    trading_days: frozenset[date],
    start: date,
    end: date,
    weighting: str = WEIGHTING_MARKET_CAP,
    single_stock_cap: float | None = DEFAULT_SINGLE_STOCK_CAP,
    min_coverage: float = DEFAULT_COVERAGE,
    min_constituents: int = MIN_CONSTITUENTS,
    pre_excluded: Mapping[str, str] | None = None,
) -> GroupIndex:
    """Build a current-constituents group index for ``[start, end]``.

    Args:
        group: The display label for the group (for example a sector name).
        constituents: Candidate constituents with derived daily returns and market cap.
        trading_days: The exchange calendar derived from the stored VN-Index bars.
        start: Window start (inclusive).
        end: Window end (inclusive).
        weighting: :data:`WEIGHTING_MARKET_CAP` or :data:`WEIGHTING_EQUAL`.
        single_stock_cap: Optional cap applied at every rebalance (``None`` disables it).
        min_coverage: Fraction of the window's trading days a stock must cover.
        min_constituents: Minimum surviving constituents for a published index.
        pre_excluded: Tickers already excluded by the caller, with their reasons.

    Returns:
        A :class:`GroupIndex`. When fewer than ``min_constituents`` survive the
        coverage/market-cap rules the status is ``insufficient`` and the path is empty.
    """
    window = _window_days(trading_days, start, end)
    excluded = dict(pre_excluded or {})
    if len(window) < 2:
        return _insufficient(group, [], excluded, "the window has fewer than two trading days")

    required = ceil(min_coverage * len(window))
    eligible: list[GroupConstituent] = []
    for item in constituents:
        coverage = sum(1 for day in window if day in item.returns)
        if coverage < required:
            excluded[item.ticker] = (
                f"coverage {coverage}/{len(window)} is below {min_coverage:.0%}"
            )
            continue
        eligible.append(item)

    if weighting == WEIGHTING_MARKET_CAP:
        with_cap = [
            item for item in eligible if item.market_cap is not None and item.market_cap > 0
        ]
        for item in eligible:
            if item not in with_cap:
                excluded[item.ticker] = "no market cap for market-cap weighting"
        eligible = with_cap

    if len(eligible) < min_constituents:
        return _insufficient(
            group,
            eligible,
            excluded,
            f"only {len(eligible)} constituent(s) pass; at least {min_constituents} are needed",
        )

    target, _cap_applied, weight_warnings = target_weights(
        eligible, weighting, single_stock_cap
    )
    returns_by_ticker: dict[str, Mapping[date, float]] = {
        item.ticker: item.returns for item in eligible
    }
    rebalance_days = _rebalance_days(window)
    weights = dict(target)
    cumulative: list[ReturnPoint] = [ReturnPoint(date=window[0], value=0.0)]
    daily: dict[date, float] = {}
    level = 1.0

    for day in window[1:]:
        if day in rebalance_days:
            weights = dict(target)
        contributions = [
            (weights[ticker], returns_by_ticker[ticker][day])
            for ticker in weights
            if day in returns_by_ticker[ticker]
        ]
        available_weight = sum(weight for weight, _ in contributions)
        day_return = (
            sum(weight * value for weight, value in contributions) / available_weight
            if available_weight > 0
            else 0.0
        )
        daily[day] = day_return
        level *= 1.0 + day_return
        cumulative.append(ReturnPoint(date=day, value=(level - 1.0) * 100.0))
        drifted = {
            ticker: (
                weight * (1.0 + returns_by_ticker[ticker][day])
                if day in returns_by_ticker[ticker]
                else weight
            )
            for ticker, weight in weights.items()
        }
        total = sum(drifted.values())
        if total > 0:
            weights = {ticker: value / total for ticker, value in drifted.items()}

    return GroupIndex(
        group=group,
        status="ok",
        constituent_count=len(eligible),
        constituents=sorted(item.ticker for item in eligible),
        excluded=excluded,
        weights=target,
        daily_returns=daily,
        cumulative_returns=cumulative,
        warnings=weight_warnings,
    )


__all__ = [
    "DEFAULT_COVERAGE",
    "DEFAULT_SINGLE_STOCK_CAP",
    "MIN_CONSTITUENTS",
    "WEIGHTING_EQUAL",
    "WEIGHTING_MARKET_CAP",
    "GroupConstituent",
    "GroupIndex",
    "apply_cap",
    "build_group_index",
    "target_weights",
]


