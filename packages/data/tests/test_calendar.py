"""Trading-calendar helpers."""

from __future__ import annotations

from datetime import date, datetime, time

from data.calendar import (
    VIETNAM_UTC_OFFSET,
    is_trading_day,
    last_completed_session,
    last_trading_day,
    trading_days_between,
    trading_days_from_dates,
    vietnam_today,
)

HOLIDAYS = frozenset({date(2024, 1, 1)})
CLOSE = time(15, 0)


def test_weekend_is_not_a_trading_day() -> None:
    assert not is_trading_day(date(2024, 1, 6), HOLIDAYS)  # Saturday
    assert is_trading_day(date(2024, 1, 8), HOLIDAYS)  # Monday


def test_holiday_is_not_a_trading_day() -> None:
    assert not is_trading_day(date(2024, 1, 1), HOLIDAYS)


def test_last_trading_day_skips_weekend_and_holiday() -> None:
    assert last_trading_day(date(2024, 1, 7), HOLIDAYS) == date(2024, 1, 5)
    assert last_trading_day(date(2024, 1, 1), HOLIDAYS) == date(2023, 12, 29)


def test_trading_days_between_excludes_weekends_and_holidays() -> None:
    days = trading_days_between(date(2024, 1, 1), date(2024, 1, 8), HOLIDAYS)
    assert date(2024, 1, 1) not in days
    assert date(2024, 1, 6) not in days
    assert days[0] == date(2024, 1, 2)
    assert days[-1] == date(2024, 1, 8)


def test_trading_days_between_reversed_range_is_empty() -> None:
    assert trading_days_between(date(2024, 1, 8), date(2024, 1, 1), HOLIDAYS) == []


def test_trading_days_from_dates_keeps_the_observed_sessions() -> None:
    observed = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 2)]
    calendar = trading_days_from_dates(observed)
    assert calendar == frozenset({date(2024, 1, 2), date(2024, 1, 3)})
    assert trading_days_from_dates([]) == frozenset()


def _ict(day: date, hour: int, minute: int = 0) -> datetime:
    """Return an aware Vietnam moment on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=VIETNAM_UTC_OFFSET)


def test_last_completed_session_waits_for_the_close() -> None:
    """Before 15:00 ICT today's session has no official close, so yesterday is used."""
    # 2024-01-03 is a Wednesday, 2024-01-02 a Tuesday.
    assert last_completed_session(
        _ict(date(2024, 1, 3), 10, 2), holidays=HOLIDAYS, session_close=CLOSE
    ) == date(2024, 1, 2)
    assert last_completed_session(
        _ict(date(2024, 1, 3), 15, 0), holidays=HOLIDAYS, session_close=CLOSE
    ) == date(2024, 1, 3)


def test_last_completed_session_rolls_back_over_a_holiday_and_the_weekend() -> None:
    """A pre-close run on the day after a holiday targets the session before it."""
    holiday = frozenset({date(2024, 1, 1), date(2024, 1, 2)})
    assert last_completed_session(
        _ict(date(2024, 1, 3), 10, 2), holidays=holiday, session_close=CLOSE
    ) == date(2023, 12, 29)
    # A Monday-morning run targets Friday, not the closed weekend.
    assert last_completed_session(
        _ict(date(2024, 1, 8), 9, 37), holidays=HOLIDAYS, session_close=CLOSE
    ) == date(2024, 1, 5)


def test_vietnam_today_accepts_a_utc_moment() -> None:
    """The runner clock is UTC: 19:13 UTC is already the next Vietnam date."""
    moment = datetime(2024, 1, 1, 19, 13)
    assert vietnam_today(moment) == date(2024, 1, 2)

