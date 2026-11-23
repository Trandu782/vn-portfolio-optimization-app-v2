"""Cross-check SSI's adjusted close against its corporate-action feed.

SSI ``stock-info`` publishes both an adjusted ``close`` and a raw ``closeRaw``,
and ``corporate-actions`` publishes DIV/ISS events with their ex-date and ratio.
This pure helper reports, for each event whose ex-date falls inside the price
window, how much of the raw ex-date gap the adjusted series removed and how that
compares with the gap the corporate action implies.

It **reports differences and never hides them** because SSI's exact adjustment
method is unverified (``docs/V2_SPEC.md`` open item 4): the numeric ``difference``
is the useful output; ``status`` is only a convenience label. When the price
window does not span an ex-date the finding says so (``no_price_data``) instead of
guessing.

Only a cash ``DIV`` with a published per-share value is verifiable. ``ISS`` is
reported as ``unsupported``: SSI publishes an issuance ratio but no subscription
price, so the bonus-share model (``-ratio / (1 + ratio)``) overstates the gap for a
rights issue and would turn genuine rights issues (NVL, VIX, HCM, ...) into false
differences. An ISS ex-date whose *adjusted* close jumps up while the *raw* close does
not fall is instead flagged ``adjustment_suspect`` (a spurious adjustment gain, e.g.
EVF 2023-09-21).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from data.v2.schemas import AdjustedOHLCV, CorporateAction

#: Differences beyond this many percentage points are labelled ``difference``.
DEFAULT_TOLERANCE = 0.02
#: A positive adjusted gap beyond this on an ISS ex-date whose raw close did not move
#: is a spurious adjustment gain, not a rights issue.
SUSPECT_ADJUSTED_GAP = 0.05
#: The raw close must be within this band (flat) for the suspect rule to fire.
SUSPECT_RAW_MOVE = 0.02


@dataclass(frozen=True)
class ReconciliationFinding:
    """The reconciliation result for one corporate action's ex-date.

    ``raw_gap`` is the raw close change across the ex-date; ``adjusted_gap`` the
    adjusted close change; ``removed_gap = raw_gap - adjusted_gap`` is how much of
    the drop the adjustment removed; ``expected_gap`` is the gap the action implies
    under the documented convention (cash ``DIV``: ``-value / raw_close``; ``ISS``:
    ``-ratio / (1 + ratio)``); ``difference = removed_gap - expected_gap``.
    """

    ticker: str
    ex_date: date
    event_type: str
    action_ratio: float | None
    action_value: float | None
    before_date: date | None = None
    after_date: date | None = None
    raw_gap: float | None = None
    adjusted_gap: float | None = None
    removed_gap: float | None = None
    expected_gap: float | None = None
    difference: float | None = None
    status: str = "no_price_data"


def _expected_gap(action: CorporateAction, before_close_raw: float) -> float | None:
    """Return the ex-date gap the corporate action implies, or ``None`` if unknown.

    Only a cash ``DIV`` with a published per-share value is verifiable
    (``-value / raw_close``). ``ISS`` is deliberately left unverifiable: SSI publishes
    an issuance ratio with ``value`` = 0, which fits a *bonus* issue
    (``-ratio / (1 + ratio)``) but not a *rights* issue, whose ex-rights gap also
    depends on the subscription price the feed does not publish. Applying the bonus
    formula to every ISS overstates the expected gap and turns real rights issues into
    false differences, so ISS is reported ``unsupported`` instead.
    """
    if action.event_type == "DIV" and action.value is not None and before_close_raw:
        return -action.value / before_close_raw
    return None


def _combine_action_fields(group: Sequence[CorporateAction]) -> tuple[float | None, float | None]:
    """Return the summed ``(ratio, value)`` when every action in ``group`` carries one."""
    ratios = [action.ratio for action in group]
    values = [action.value for action in group]
    ratio: float | None = None
    if ratios and all(item is not None for item in ratios):
        ratio = sum(item for item in ratios if item is not None)
    value: float | None = None
    if values and all(item is not None for item in values):
        value = sum(item for item in values if item is not None)
    return ratio, value


def reconcile_corporate_actions(
    bars: Sequence[AdjustedOHLCV],
    actions: Sequence[CorporateAction],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[ReconciliationFinding]:
    """Reconcile each DIV/ISS ex-date against the adjusted/raw closes.

    Actions that share one ex-date (two share issues, or an issue and a dividend on
    the same day) are combined into **one** finding. The adjusted series removes the
    *total* ex-date gap once, so the comparison must use the combined implied gap,
    not any single action's. The per-action gaps are compounded
    (``prod(1 + gap) - 1``), which reduces to the single-action gap when there is
    only one action on the date.

    Args:
        bars: Daily bars for one ticker (adjusted ``close`` plus optional
            ``close_raw``); any order.
        actions: The ticker's corporate actions (DIV/ISS with ex-dates).
        tolerance: Absolute difference (fraction) within which a finding is ``ok``.

    Returns:
        One :class:`ReconciliationFinding` per ex-date that has a DIV/ISS action, in
        first-seen order. Statuses: ``ok`` / ``difference`` (cash ``DIV`` whose removed
        gap does not match the published value) / ``adjustment_suspect`` (an ISS ex-date
        whose adjusted close jumped up while the raw close did not fall) /
        ``unsupported`` (an ``ISS`` ratio with no subscription price, or a cash
        dividend without a per-share value) / ``no_raw_close`` / ``no_price_data``.
    """
    ordered = sorted(bars, key=lambda bar: bar.date)
    groups: dict[date, list[CorporateAction]] = {}
    for action in actions:
        if action.event_type not in {"DIV", "ISS"} or action.exright_date is None:
            continue
        groups.setdefault(action.exright_date, []).append(action)

    findings: list[ReconciliationFinding] = []
    for ex_date, group in groups.items():
        first = group[0]
        ratio, value = _combine_action_fields(group)
        base = ReconciliationFinding(
            ticker=first.ticker,
            ex_date=ex_date,
            event_type="/".join(action.event_type for action in group),
            action_ratio=ratio,
            action_value=value,
        )
        after_idx = next((i for i, bar in enumerate(ordered) if bar.date >= ex_date), None)
        if after_idx is None or after_idx == 0:
            findings.append(base)
            continue
        before, after = ordered[after_idx - 1], ordered[after_idx]
        located = replace(base, before_date=before.date, after_date=after.date)
        if before.close_raw is None or after.close_raw is None:
            findings.append(replace(located, status="no_raw_close"))
            continue
        if before.close_raw <= 0 or before.close <= 0:
            findings.append(replace(located, status="invalid_price"))
            continue
        raw_gap = after.close_raw / before.close_raw - 1.0
        adjusted_gap = after.close / before.close - 1.0
        removed_gap = raw_gap - adjusted_gap
        has_iss = any(action.event_type == "ISS" for action in group)
        verifiable = not has_iss and all(
            action.event_type == "DIV" and action.value is not None for action in group
        )
        if not verifiable:
            # An ISS has no subscription price, and a mixed DIV/ISS ex-date cannot be
            # checked from the DIV value alone, so the removed gap is unverifiable. A
            # positive adjusted gap on a flat raw close is a spurious gain (EVF, NVL).
            status = "unsupported"
            if (
                has_iss
                and adjusted_gap > SUSPECT_ADJUSTED_GAP
                and abs(raw_gap) < SUSPECT_RAW_MOVE
            ):
                status = "adjustment_suspect"
            findings.append(
                replace(
                    located,
                    raw_gap=raw_gap,
                    adjusted_gap=adjusted_gap,
                    removed_gap=removed_gap,
                    status=status,
                )
            )
            continue
        expected_gaps = [
            gap
            for gap in (_expected_gap(action, before.close_raw) for action in group)
            if gap is not None
        ]
        if not expected_gaps:
            findings.append(
                replace(
                    located,
                    raw_gap=raw_gap,
                    adjusted_gap=adjusted_gap,
                    removed_gap=removed_gap,
                    status="unsupported",
                )
            )
            continue
        combined_factor = 1.0
        for gap in expected_gaps:
            combined_factor *= 1.0 + gap
        expected_gap = combined_factor - 1.0
        difference = removed_gap - expected_gap
        status = "ok" if abs(difference) <= tolerance else "difference"
        findings.append(
            replace(
                located,
                raw_gap=raw_gap,
                adjusted_gap=adjusted_gap,
                removed_gap=removed_gap,
                expected_gap=expected_gap,
                difference=difference,
                status=status,
            )
        )
    return findings


__all__ = [
    "DEFAULT_TOLERANCE",
    "SUSPECT_ADJUSTED_GAP",
    "SUSPECT_RAW_MOVE",
    "ReconciliationFinding",
    "reconcile_corporate_actions",
]
