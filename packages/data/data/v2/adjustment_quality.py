"""Per-ticker adjustment-quality flag for the analytics payload.

The flag examines a ticker's **adjusted** series for anomalies that the adjustment should
have removed: an adjusted move beyond the widest exchange limit (15%) away from a known
ex-date, an adjusted-vs-raw ratio drift away from a known ex-date, or a reconciliation
difference at an ex-date. The threshold is the *widest* exchange limit, not the ticker's
current board limit, because a listing transfer (for example BSR from UPCoM to HOSE) makes
the current limit wrong for historical sessions.

A flagged ticker is reported as a payload warning with an ``exclude_from_group_indices``
hint; whether to exclude it is the caller's choice. An anomaly already documented in
:data:`data.v2.explained_findings.EXPLAINED_FINDINGS` is labelled ``explained`` in its
reason, the rest ``unexplained``.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Final

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from data.v2.analytics.schemas import AdjustmentQualityFlag
from data.v2.explained_findings import match_explained
from data.v2.precompute_schemas import AdjustmentAnomalyRecord
from data.v2.reconcile import reconcile_corporate_actions
from data.v2.schemas import AdjustedOHLCV, CorporateAction

#: Version of the flag policy (``docs/DECISIONS.md`` D-019). Stamped into every stored
#: flag row's ``source`` so a reader can detect rows computed under an older rule set
#: without a schema change. Bumped from D-017 when the flag gained per-anomaly
#: categories (data glitch vs thin trading) and the Sector tab became window-aware.
FLAGS_POLICY_VERSION: Final[str] = "D-019"
#: Delimiter between the price source and the policy marker in a stored flag's source.
_POLICY_MARKER: Final[str] = "|policy="

#: Buffer above the widest limit so an ordinary limit-up day does not flag.
DEFAULT_LIMIT_BUFFER = 0.005
#: Absolute adjusted/raw ratio change treated as drift.
DEFAULT_RATIO_TOLERANCE = 0.02
#: Absolute reconciliation difference treated as a mismatch.
DEFAULT_RECONCILIATION_TOLERANCE = 0.02
#: Calendar-day window around an ex-date inside which a move is "explained".
DEFAULT_ACTION_WINDOW_DAYS = 1
#: Minimum size of each leg of a two-session adjusted move that largely reverses.
REVERSING_MOVE_THRESHOLD = 0.07
#: The two legs must cancel: the net move is at most this fraction of the gross move.
REVERSING_NET_FRACTION = 0.5
#: A session is "thin trading" rather than a data glitch when the matched volume/value
#: on the anomaly day is below this fraction of the ticker's typical (median) level. A
#: big move on a near-zero-volume day is a stale/bad print, not a real return.
THIN_TRADING_FRACTION = 0.10


def widest_daily_limit(rules: MarketRules = DEFAULT_MARKET_RULES) -> float:
    """Return the widest exchange daily price limit (UPCoM 15%) as a fraction."""
    return max(float(rule.daily_price_limit) for rule in rules.exchanges.values())


def flag_source(price_source: str) -> str:
    """Return the provenance stored on a flag row: the price source plus the policy version.

    Encoding the policy version in the existing ``source`` column keeps the stored
    flags self-describing without a schema change, so a row produced under an older
    rule set is detectable by comparing :func:`policy_from_source` with
    :data:`FLAGS_POLICY_VERSION`.
    """
    return f"{price_source}{_POLICY_MARKER}{FLAGS_POLICY_VERSION}"


def policy_from_source(source: str) -> str | None:
    """Return the policy version embedded in a stored flag's ``source`` (or ``None``)."""
    if _POLICY_MARKER not in source:
        return None
    return source.split(_POLICY_MARKER, 1)[1]


@dataclass(frozen=True)
class AdjustmentAnomaly:
    """One anomaly found in a ticker's adjusted series.

    ``exclude`` marks a return-corrupting anomaly (a spurious adjusted move, or an
    adjustment that injects a gain) that the group indices drop by default. A plain
    adjusted-vs-raw drift is reported (``exclude=False``) but does not exclude the name
    unless the caller opts into ``exclude_adjustment_flagged``. ``category`` separates a
    genuine data glitch from a move on a very-low-liquidity ("thin trading") session.
    ``reason`` is plain-language (no jargon).
    """

    reason: str
    day: date | None
    explained: str | None
    exclude: bool = False
    category: str = "data_glitch"


def _triples(
    items: Sequence[AdjustedOHLCV],
) -> list[tuple[AdjustedOHLCV, AdjustedOHLCV, AdjustedOHLCV]]:
    """Return every consecutive ``(previous, current, following)`` bar triple."""
    return list(zip(items, items[1:], items[2:], strict=False))


def _ordered(bars: Sequence[AdjustedOHLCV]) -> list[AdjustedOHLCV]:
    """Return bars sorted by date with one bar per date (the last wins)."""
    by_date = {bar.date: bar for bar in bars}
    return [by_date[day] for day in sorted(by_date)]


def _action_dates(actions: Sequence[CorporateAction]) -> set[date]:
    """Return the known corporate-action ex-dates."""
    return {action.exright_date for action in actions if action.exright_date is not None}


def _near(day: date, action_dates: set[date], window_days: int) -> bool:
    """Return ``True`` when ``day`` is within ``window_days`` of a known ex-date."""
    return any(abs((day - action_day).days) <= window_days for action_day in action_dates)


def _liquidity_field(
    ordered: Sequence[AdjustedOHLCV],
) -> tuple[str | None, float | None]:
    """Return the stored liquidity field to use and the ticker's typical (median) level.

    Prefers the matched order-matching value (VND), then matched volume (shares), then
    the reported total value, then total volume. One field is used for both the anomaly
    day and the typical level, so the units never mix.
    """
    for attribute in ("matched_value", "matched_volume", "value", "volume"):
        levels = [
            float(value)
            for bar in ordered
            if (value := getattr(bar, attribute)) is not None and value > 0
        ]
        if levels:
            return attribute, median(levels)
    return None, None


def _is_thin_trading(
    bar: AdjustedOHLCV, attribute: str | None, typical: float | None
) -> bool:
    """Return ``True`` when ``bar`` traded far below the ticker's typical level.

    A large adjusted move on a near-zero-volume session is a stale/bad print rather
    than a real return, so it is labelled "thin trading" instead of a "data glitch".
    """
    if attribute is None or typical is None or typical <= 0:
        return False
    value = getattr(bar, attribute)
    return value is not None and value > 0 and float(value) < THIN_TRADING_FRACTION * typical


def _category_for(
    bar: AdjustedOHLCV, attribute: str | None, typical: float | None
) -> str:
    """Return ``"thin_trading"`` for a very-low-liquidity day, else ``"data_glitch"``."""
    return "thin_trading" if _is_thin_trading(bar, attribute, typical) else "data_glitch"


def find_adjustment_anomalies(
    ticker: str,
    bars: Sequence[AdjustedOHLCV],
    actions: Sequence[CorporateAction] = (),
    *,
    rules: MarketRules = DEFAULT_MARKET_RULES,
    limit_buffer: float = DEFAULT_LIMIT_BUFFER,
    ratio_tolerance: float = DEFAULT_RATIO_TOLERANCE,
    reconciliation_tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
    action_window_days: int = DEFAULT_ACTION_WINDOW_DAYS,
) -> list[AdjustmentAnomaly]:
    """Return every adjustment anomaly found in ``ticker``'s series.

    The widest exchange limit (15%) plus ``limit_buffer`` is the adjusted-move sanity
    threshold; a move near a known ex-date is treated as explained by the action.
    """
    ordered = _ordered(bars)
    action_dates = _action_dates(actions)
    threshold = widest_daily_limit(rules) + limit_buffer
    liquidity_attribute, typical_level = _liquidity_field(ordered)
    anomalies: list[AdjustmentAnomaly] = []

    for previous, current in itertools.pairwise(ordered):
        if previous.close <= 0:
            continue
        move = current.close / previous.close - 1.0
        if abs(move) <= threshold or _near(current.date, action_dates, action_window_days):
            continue
        anomalies.append(
            AdjustmentAnomaly(
                reason=(
                    f"price moved {move:+.1%} in a single session with no corporate "
                    "action to explain it"
                ),
                day=current.date,
                explained=match_explained(ticker, "suspicious_returns", [current.date]),
                exclude=True,
                category=_category_for(current, liquidity_attribute, typical_level),
            )
        )

    # A one-bar adjusted excursion that largely reverses on the next session is a bad
    # adjusted bar, not a market move (GEE, EVF). It fires at an ex-date too, because a
    # spurious adjustment is exactly what we want to catch there.
    for previous, current, following in _triples(ordered):
        if previous.close <= 0 or current.close <= 0:
            continue
        move_in = current.close / previous.close - 1.0
        move_out = following.close / current.close - 1.0
        if move_in * move_out >= 0:
            continue
        if (
            abs(move_in) < REVERSING_MOVE_THRESHOLD
            or abs(move_out) < REVERSING_MOVE_THRESHOLD
        ):
            continue
        if abs(move_in + move_out) > REVERSING_NET_FRACTION * (abs(move_in) + abs(move_out)):
            continue
        anomalies.append(
            AdjustmentAnomaly(
                reason=(
                    f"price moved {move_in:+.1%} then reversed {move_out:+.1%} "
                    "over two sessions"
                ),
                day=current.date,
                explained=match_explained(ticker, "suspicious_returns", [current.date]),
                exclude=True,
                category=_category_for(current, liquidity_attribute, typical_level),
            )
        )

    for previous, current in itertools.pairwise(ordered):
        if not previous.close_raw or not current.close_raw:
            continue
        if previous.close_raw <= 0 or current.close_raw <= 0:
            continue
        previous_ratio = previous.close / previous.close_raw
        current_ratio = current.close / current.close_raw
        if abs(current_ratio - previous_ratio) <= ratio_tolerance:
            continue
        if _near(current.date, action_dates, action_window_days):
            continue
        anomalies.append(
            AdjustmentAnomaly(
                reason=(
                    f"adjusted and raw prices drifted apart by "
                    f"{current_ratio - previous_ratio:+.3f}"
                ),
                day=current.date,
                explained=match_explained(ticker, "adjusted_vs_raw_mismatch", [current.date]),
            )
        )

    for finding in reconcile_corporate_actions(
        ordered, actions, tolerance=reconciliation_tolerance
    ):
        if finding.status not in {"difference", "adjustment_suspect"}:
            continue
        if finding.status == "adjustment_suspect":
            reason = (
                f"adjusted price rose {finding.adjusted_gap:+.1%} on a flat raw price at "
                f"the {finding.event_type} ex-date (a possible spurious adjustment)"
            )
        else:
            reason = (
                f"adjusted price did not match the {finding.event_type} "
                "dividend/share-issue calculation on this ex-date"
            )
        anomalies.append(
            AdjustmentAnomaly(
                reason=reason,
                day=finding.ex_date,
                explained=match_explained(
                    ticker, "adjusted_vs_raw_mismatch", [finding.ex_date]
                ),
                exclude=True,
            )
        )
    return anomalies


def adjustment_quality_flag(
    ticker: str,
    bars: Sequence[AdjustedOHLCV],
    actions: Sequence[CorporateAction] = (),
    *,
    rules: MarketRules = DEFAULT_MARKET_RULES,
) -> AdjustmentQualityFlag:
    """Return the per-ticker adjustment-quality flag for the payload."""
    anomalies = find_adjustment_anomalies(ticker, bars, actions, rules=rules)
    if not anomalies:
        return AdjustmentQualityFlag(ticker=ticker.strip().upper())
    reasons: list[str] = []
    dates: list[date] = []
    records: list[AdjustmentAnomalyRecord] = []
    for anomaly in anomalies:
        when = f" on {anomaly.day.isoformat()}" if anomaly.day is not None else ""
        reasons.append(f"{anomaly.reason}{when}")
        if anomaly.day is not None:
            dates.append(anomaly.day)
            records.append(
                AdjustmentAnomalyRecord(
                    date=anomaly.day,
                    exclude=anomaly.exclude,
                    category=anomaly.category,  # type: ignore[arg-type]
                    reason=anomaly.reason,
                )
            )
    return AdjustmentQualityFlag(
        ticker=ticker.strip().upper(),
        severity="warning",
        flagged=True,
        exclude_from_group_indices=any(anomaly.exclude for anomaly in anomalies),
        reasons=reasons,
        dates=sorted(set(dates)),
        anomalies=records,
    )


__all__ = [
    "DEFAULT_ACTION_WINDOW_DAYS",
    "DEFAULT_LIMIT_BUFFER",
    "DEFAULT_RATIO_TOLERANCE",
    "DEFAULT_RECONCILIATION_TOLERANCE",
    "FLAGS_POLICY_VERSION",
    "REVERSING_MOVE_THRESHOLD",
    "REVERSING_NET_FRACTION",
    "AdjustmentAnomaly",
    "adjustment_quality_flag",
    "find_adjustment_anomalies",
    "flag_source",
    "policy_from_source",
    "widest_daily_limit",
]

