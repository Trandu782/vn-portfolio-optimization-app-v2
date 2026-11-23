"""Rolling 20-session medians of matched ADTV and ADV."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from data.v2.liquidity import liquidity_stats, rolling_median
from data.v2.schemas import AdjustedOHLCV


def _bar(
    day: date,
    close: float = 100.0,
    *,
    volume: int = 1000,
    matched_volume: int | None = 1000,
    matched_value: float | None = 100_000.0,
    value: float | None = None,
) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        matched_volume=matched_volume,
        matched_value=matched_value,
        value=value,
        source="ssi_statistics",
    )


def _weekdays(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_rolling_median_trailing_window() -> None:
    assert rolling_median([1.0, 2.0, 3.0, 4.0], 2) == [1.0, 1.5, 2.5, 3.5]


def test_rolling_median_full_window_on_tail() -> None:
    values = [float(index) for index in range(1, 31)]  # 1..30
    medians = rolling_median(values, 20)
    assert len(medians) == 30
    # The last 20 values are 11..30, whose median is 20.5.
    assert medians[-1] == 20.5


def test_rolling_median_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError):
        rolling_median([1.0], 0)


def test_matched_basis_uses_matched_volume_and_value() -> None:
    days = _weekdays(3)
    bars = [
        _bar(day, matched_volume=1000 + index, matched_value=100_000.0 + index)
        for index, day in enumerate(days)
    ]
    stats = liquidity_stats(bars, window=20)
    assert stats.volume_basis == "matched"
    assert stats.adv_median == 1001.0
    assert stats.adtv_median == 100_001.0
    assert stats.observations == 3
    assert stats.as_of == days[-1]


def test_total_basis_falls_back_when_matched_missing() -> None:
    days = _weekdays(2)
    bars = [
        _bar(days[0], volume=500, matched_volume=None, matched_value=None),
        _bar(days[1], volume=700, matched_volume=None, matched_value=None),
    ]
    stats = liquidity_stats(bars, window=20)
    assert stats.volume_basis == "total"
    assert stats.adv_median == 600.0
    assert stats.adtv_median is None  # no traded value published


def test_total_basis_uses_total_value_when_present() -> None:
    days = _weekdays(2)
    bars = [
        _bar(days[0], volume=500, matched_volume=None, matched_value=None, value=50_000.0),
        _bar(days[1], volume=700, matched_volume=None, matched_value=None, value=90_000.0),
    ]
    stats = liquidity_stats(bars, window=20)
    assert stats.volume_basis == "total"
    assert stats.adtv_median == 70_000.0


def test_partial_matched_window_falls_back_to_total() -> None:
    days = _weekdays(2)
    bars = [
        _bar(days[0], matched_volume=1000, matched_value=100_000.0),
        _bar(days[1], matched_volume=None, matched_value=None, volume=800),
    ]
    stats = liquidity_stats(bars, window=20)
    assert stats.volume_basis == "total"
    assert stats.adv_median == 900.0  # median(1000, 800)


def test_window_only_uses_the_last_sessions() -> None:
    days = _weekdays(25)
    bars = [
        _bar(day, volume=index + 1, matched_volume=index + 1, matched_value=float(index + 1))
        for index, day in enumerate(days)
    ]
    stats = liquidity_stats(bars, window=20)
    assert stats.observations == 20
    # volumes for the last 20 sessions are 6..25, median = 15.5
    assert stats.adv_median == 15.5
    assert stats.as_of == days[-1]


def test_empty_series_is_null_not_an_error() -> None:
    stats = liquidity_stats([], window=20)
    assert stats.adv_median is None
    assert stats.adtv_median is None
    assert stats.observations == 0
