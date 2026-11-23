"""Cross-provider overlap comparison."""

from __future__ import annotations

from datetime import date

import pytest
from support import make_bar

from data.consistency import compare_overlap


def test_within_tolerance_is_consistent() -> None:
    existing = [make_bar(date(2024, 1, 2), 100.0), make_bar(date(2024, 1, 3), 101.0)]
    incoming = [make_bar(date(2024, 1, 2), 100.2), make_bar(date(2024, 1, 3), 101.0)]
    result = compare_overlap(existing, incoming, tolerance=0.005)
    assert result.has_overlap
    assert result.consistent
    assert result.mismatched_days == 0


def test_large_difference_is_detected() -> None:
    existing = [make_bar(date(2024, 1, 2), 100.0)]
    incoming = [make_bar(date(2024, 1, 2), 110.0)]
    result = compare_overlap(existing, incoming, tolerance=0.005)
    assert not result.consistent
    assert result.mismatched_days == 1
    assert result.max_relative_diff == pytest.approx(0.1)
    assert result.examples[0].day == date(2024, 1, 2)


def test_no_overlap_is_reported_as_consistent_but_empty() -> None:
    existing = [make_bar(date(2024, 1, 2), 100.0)]
    incoming = [make_bar(date(2024, 2, 2), 200.0)]
    result = compare_overlap(existing, incoming, tolerance=0.005)
    assert not result.has_overlap
    assert result.consistent
