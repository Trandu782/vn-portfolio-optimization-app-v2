"""Heuristic back-adjustment for corporate-action price gaps.

No anonymous provider returns a complete, verified corporate-actions feed for every
ex-date (SSI iBoard exposes DIV/ISS events but not a complete feed), so this pure
helper infers split / bonus / large dividend adjustments from a single
close-to-close gap larger than the exchange daily limit and back-adjusts the earlier
OHLC by the implied factor.

It is a **heuristic**, not a corporate-action feed. It reliably catches large
split/bonus gaps; small cash-dividend gaps are indistinguishable from normal moves
and stay raw. :class:`PriceGapAdjustment` carries ``heuristic=True`` and a
``label`` the UI must show.

Safeguards
----------
* the daily limit is per exchange (HOSE 7%, HNX 10%, UPCoM 15%), with a buffer;
* the implied factor must be plausible (finite and inside ``[min_factor, max_factor]``);
* the first bar (IPO day) never starts a gap;
* a pair after a suspension is skipped (zero volume on the prior bar, or missing
  trading days between the two dates).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from data.calendar import trading_days_between
from data.v2.schemas import AdjustedOHLCV

HEURISTIC_LABEL = "adjusted via a price-gap heuristic (not a verified corporate-action feed)"

DEFAULT_MIN_FACTOR = 0.05
DEFAULT_MAX_FACTOR = 20.0
DEFAULT_BUFFER = 0.005


@dataclass(frozen=True)
class AdjustmentEvent:
    """One inferred corporate-action gap."""

    date: date
    move: float
    implied_factor: float
    reason: str = "close move beyond the exchange daily limit"


@dataclass(frozen=True)
class PriceGapAdjustment:
    """Back-adjusted bars plus the events that were applied."""

    bars: list[AdjustedOHLCV]
    events: list[AdjustmentEvent]
    heuristic: bool = True
    label: str = HEURISTIC_LABEL


def exchange_daily_limit(exchange: str, rules: MarketRules = DEFAULT_MARKET_RULES) -> float:
    """Return the daily price limit for ``exchange`` (HOSE when the code is unknown)."""
    wanted = exchange.strip().upper()
    for code, rule in rules.exchanges.items():
        if code.upper() == wanted:
            return float(rule.daily_price_limit)
    return float(rules.exchanges["HOSE"].daily_price_limit)


def _is_gap(
    prev: AdjustedOHLCV,
    curr: AdjustedOHLCV,
    *,
    limit: float,
    holidays: frozenset[date],
    skip_zero_volume: bool,
    min_factor: float,
    max_factor: float,
) -> bool:
    """Return ``True`` when the pair looks like a plausible corporate-action gap."""
    if prev.close <= 0 or curr.close <= 0:
        return False
    move = curr.close / prev.close - 1.0
    if abs(move) <= limit:
        return False
    if skip_zero_volume and prev.volume <= 0:
        return False
    if len(trading_days_between(prev.date, curr.date, holidays)) > 2:
        return False
    factor = curr.close / prev.close
    return isfinite(factor) and min_factor <= factor <= max_factor


def adjust_price_gaps(
    bars: Sequence[AdjustedOHLCV],
    *,
    exchange: str,
    rules: MarketRules = DEFAULT_MARKET_RULES,
    holidays: Iterable[date] | None = None,
    min_factor: float = DEFAULT_MIN_FACTOR,
    max_factor: float = DEFAULT_MAX_FACTOR,
    buffer: float = DEFAULT_BUFFER,
    skip_zero_volume: bool = True,
) -> PriceGapAdjustment:
    """Back-adjust earlier OHLC around inferred split/bonus gaps.

    The input is sorted by date defensively. Volume, ``matched_volume`` and
    ``value`` are left untouched; only open/high/low/close of bars *before* an
    inferred event are scaled, so each bar's return matches its neighbour.

    Args:
        bars: Daily bars for one symbol (any order).
        exchange: HOSE / HNX / UPCoM (case-insensitive; unknown falls back to HOSE).
        rules: Market rules supplying the per-exchange limits and holidays.
        holidays: Override the holiday calendar used for the suspension check.
        min_factor: Smallest plausible implied factor (rejects absurd gaps).
        max_factor: Largest plausible implied factor.
        buffer: Added to the daily limit so ordinary limit-up days do not trigger.
        skip_zero_volume: Treat a zero-volume prior bar as suspended and skip it.

    Returns:
        A :class:`PriceGapAdjustment` with the adjusted bars and recorded events.
    """
    ordered = sorted(bars, key=lambda bar: bar.date)
    if len(ordered) < 2:
        return PriceGapAdjustment(bars=list(ordered), events=[])

    limit = exchange_daily_limit(exchange, rules) + buffer
    holiday_set = frozenset(holidays if holidays is not None else rules.trading_holidays)
    factors = [1.0] * len(ordered)
    events: list[AdjustmentEvent] = []
    cumulative = 1.0

    # Walk from the latest bar backwards. An event on the boundary between i-1 and
    # i scales every bar before i; ``factors[i]`` is the product of later events.
    for i in range(len(ordered) - 1, 0, -1):
        prev, curr = ordered[i - 1], ordered[i]
        # ``i > 1`` skips the pair that starts at the first bar (IPO-day guard).
        if i > 1 and _is_gap(
            prev,
            curr,
            limit=limit,
            holidays=holiday_set,
            skip_zero_volume=skip_zero_volume,
            min_factor=min_factor,
            max_factor=max_factor,
        ):
            factor = curr.close / prev.close
            cumulative *= factor
            events.append(
                AdjustmentEvent(
                    date=curr.date,
                    move=curr.close / prev.close - 1.0,
                    implied_factor=factor,
                )
            )
        factors[i - 1] = cumulative

    adjusted = [
        bar.model_copy(
            update={
                "open": bar.open * factors[index],
                "high": bar.high * factors[index],
                "low": bar.low * factors[index],
                "close": bar.close * factors[index],
            }
        )
        for index, bar in enumerate(ordered)
    ]
    events.sort(key=lambda event: event.date)
    return PriceGapAdjustment(bars=adjusted, events=events)


__all__ = [
    "DEFAULT_BUFFER",
    "DEFAULT_MAX_FACTOR",
    "DEFAULT_MIN_FACTOR",
    "HEURISTIC_LABEL",
    "AdjustmentEvent",
    "PriceGapAdjustment",
    "adjust_price_gaps",
    "exchange_daily_limit",
]
