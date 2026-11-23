"""Per-ticker simple daily returns from adjusted closes."""

from __future__ import annotations

from datetime import date

from data.v2.returns import calendar_returns, daily_returns, return_series
from data.v2.schemas import AdjustedOHLCV


def _bar(day: date, close: float) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day, open=close, high=close, low=close, close=close, volume=1000, source="ssi"
    )


def test_simple_returns_use_adjusted_close() -> None:
    bars = [
        _bar(date(2025, 1, 2), 100.0),
        _bar(date(2025, 1, 3), 110.0),
        _bar(date(2025, 1, 6), 99.0),
    ]
    returns = daily_returns(bars)
    assert [item.date for item in returns] == [date(2025, 1, 3), date(2025, 1, 6)]
    assert round(returns[0].value, 6) == 0.1
    assert round(returns[1].value, 6) == -0.1


def test_daily_returns_sort_and_de_duplicate() -> None:
    bars = [
        _bar(date(2025, 1, 3), 110.0),
        _bar(date(2025, 1, 2), 100.0),
        _bar(date(2025, 1, 3), 121.0),  # the last bar for a duplicated date wins
    ]
    (only,) = daily_returns(bars)
    assert only.date == date(2025, 1, 3)
    assert round(only.value, 6) == 0.21


def test_non_positive_prior_close_is_skipped() -> None:
    bars = [_bar(date(2025, 1, 2), 0.0), _bar(date(2025, 1, 3), 10.0)]
    assert daily_returns(bars) == []


def test_return_series_is_keyed_by_date() -> None:
    bars = [_bar(date(2025, 1, 2), 100.0), _bar(date(2025, 1, 3), 105.0)]
    series = return_series(bars)
    assert set(series) == {date(2025, 1, 3)}
    assert round(series[date(2025, 1, 3)], 6) == 0.05


def test_calendar_returns_skip_a_gap() -> None:
    # The ticker has bars on 2025-01-02 and 2025-01-06 but not on the calendar day
    # between them, so neither produces a multi-day return on the resume date.
    bars = [_bar(date(2025, 1, 2), 100.0), _bar(date(2025, 1, 6), 110.0)]
    calendar = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
    assert calendar_returns(bars, calendar) == {}


def test_calendar_returns_align_to_adjacent_sessions() -> None:
    bars = [
        _bar(date(2025, 1, 2), 100.0),
        _bar(date(2025, 1, 3), 110.0),
        _bar(date(2025, 1, 6), 99.0),
    ]
    calendar = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
    returns = calendar_returns(bars, calendar)
    assert set(returns) == {date(2025, 1, 3), date(2025, 1, 6)}
    assert round(returns[date(2025, 1, 3)], 6) == 0.1
    assert round(returns[date(2025, 1, 6)], 6) == -0.1
