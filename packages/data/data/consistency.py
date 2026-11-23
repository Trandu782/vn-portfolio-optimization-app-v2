"""Cross-provider consistency for a symbol whose source changes.

The failover chain never splices two providers into one series. When a fallback
starts serving new days for a symbol whose stored history came from another
provider, the sync job compares the overlapping trading days. If the closing
prices differ by more than the configured tolerance the provider is adjusting
dividends/splits differently, so the caller either refetches the whole history
from the new provider or flags the symbol. This module only does the comparison.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from data.models import PriceBar


@dataclass(frozen=True)
class OverlapExample:
    """One day where two providers disagree, for the log/diagnostics."""

    day: date
    existing_close: float
    incoming_close: float
    relative_diff: float


@dataclass
class OverlapResult:
    """Result of comparing an incoming series against an existing one."""

    matched_days: int
    mismatched_days: int
    max_relative_diff: float
    consistent: bool
    examples: list[OverlapExample] = field(default_factory=list)

    @property
    def has_overlap(self) -> bool:
        """Return ``True`` when the two series share at least one day."""
        return self.matched_days > 0


def compare_overlap(
    existing: Sequence[PriceBar],
    incoming: Sequence[PriceBar],
    *,
    tolerance: float,
) -> OverlapResult:
    """Compare closing prices on shared days.

    Args:
        existing: Bars already stored (from the previous provider).
        incoming: Bars from the provider now serving the symbol.
        tolerance: Maximum acceptable relative close difference (0.005 == 0.5%).

    Returns:
        An :class:`OverlapResult`. ``consistent`` is ``True`` when no shared day
        exceeds ``tolerance`` (including when there is no overlap at all).
    """
    by_date = {bar.date: bar for bar in existing}
    matched = 0
    mismatched = 0
    max_diff = 0.0
    examples: list[OverlapExample] = []
    for bar in incoming:
        previous = by_date.get(bar.date)
        if previous is None:
            continue
        matched += 1
        denominator = abs(previous.close) if previous.close else 1.0
        diff = abs(bar.close - previous.close) / denominator
        max_diff = max(max_diff, diff)
        if diff > tolerance:
            mismatched += 1
            if len(examples) < 5:
                examples.append(
                    OverlapExample(
                        day=bar.date,
                        existing_close=previous.close,
                        incoming_close=bar.close,
                        relative_diff=diff,
                    )
                )
    return OverlapResult(
        matched_days=matched,
        mismatched_days=mismatched,
        max_relative_diff=max_diff,
        consistent=mismatched == 0,
        examples=examples,
    )
