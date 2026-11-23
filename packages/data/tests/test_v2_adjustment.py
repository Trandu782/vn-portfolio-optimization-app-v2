"""Price-gap adjustment heuristic: safeguards and back-adjustment."""

from __future__ import annotations

from datetime import date, timedelta

from data.v2.adjustment import HEURISTIC_LABEL, adjust_price_gaps, exchange_daily_limit
from data.v2.schemas import AdjustedOHLCV


def _bar(day: date, close: float, *, volume: int = 1000) -> AdjustedOHLCV:
    """Build a daily bar with O=H=L=C for simple arithmetic."""
    return AdjustedOHLCV(
        date=day, open=close, high=close, low=close, close=close, volume=volume, source="kbs"
    )


def _weekdays(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    """Return ``count`` consecutive weekday dates from ``start``."""
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def test_split_gap_back_adjusts_earlier_closes() -> None:
    days = _weekdays(4)
    bars = [_bar(days[0], 100), _bar(days[1], 100), _bar(days[2], 100), _bar(days[3], 50)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert [bar.close for bar in result.bars] == [50.0, 50.0, 50.0, 50.0]
    assert len(result.events) == 1
    assert result.events[0].implied_factor == 0.5
    assert result.heuristic is True
    assert result.label == HEURISTIC_LABEL


def test_normal_move_is_not_adjusted() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100), _bar(days[1], 103), _bar(days[2], 106)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert [bar.close for bar in result.bars] == [100.0, 103.0, 106.0]
    assert result.events == []


def test_ipo_first_day_is_skipped() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100), _bar(days[1], 200), _bar(days[2], 206)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    # The 100 -> 200 pair starts at the first bar (IPO), so it is never a gap;
    # 200 -> 206 is an ordinary +3% move.
    assert result.events == []
    assert [bar.close for bar in result.bars] == [100.0, 200.0, 206.0]


def test_post_suspension_resumption_is_skipped() -> None:
    days = _weekdays(2)  # 2024-01-02, 2024-01-03
    resume = days[1] + timedelta(days=14)  # many missing trading days
    bars = [_bar(days[0], 100), _bar(days[1], 100), _bar(resume, 40)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert result.events == []


def test_zero_volume_prior_bar_is_skipped() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100), _bar(days[1], 100, volume=0), _bar(days[2], 40)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert result.events == []


def test_implausible_factor_is_skipped() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100), _bar(days[1], 100), _bar(days[2], 1)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert result.events == []


def test_per_exchange_limit() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100), _bar(days[1], 100), _bar(days[2], 92)]  # -8%
    assert len(adjust_price_gaps(bars, exchange="HOSE").events) == 1
    assert adjust_price_gaps(bars, exchange="HNX").events == []
    assert adjust_price_gaps(bars, exchange="UPCoM").events == []


def test_multiple_events_are_cumulative() -> None:
    days = _weekdays(4)
    bars = [_bar(days[0], 100), _bar(days[1], 100), _bar(days[2], 50), _bar(days[3], 25)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert len(result.events) == 2
    assert [round(bar.close, 6) for bar in result.bars] == [25.0, 25.0, 25.0, 25.0]


def test_volume_is_unchanged() -> None:
    days = _weekdays(4)
    bars = [_bar(days[0], 100, volume=11), _bar(days[1], 100, volume=12),
            _bar(days[2], 100, volume=13), _bar(days[3], 50, volume=14)]
    result = adjust_price_gaps(bars, exchange="HOSE")
    assert [bar.volume for bar in result.bars] == [11, 12, 13, 14]


def test_exchange_daily_limit_is_case_insensitive() -> None:
    assert exchange_daily_limit("hose") == 0.07
    assert exchange_daily_limit("HNX") == 0.10
    assert exchange_daily_limit("upcom") == 0.15
    assert exchange_daily_limit("unknown") == 0.07
