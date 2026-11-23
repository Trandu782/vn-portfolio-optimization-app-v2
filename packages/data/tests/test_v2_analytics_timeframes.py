"""Timeframe resolution (1M/3M/6M/YTD/1Y/3Y/custom) with short-history grace."""

from __future__ import annotations

from datetime import date

import pytest

from data.v2.analytics.timeframes import TIMEFRAMES, resolve_window, subtract_months


def test_supported_timeframes() -> None:
    assert TIMEFRAMES == ("1M", "3M", "6M", "YTD", "1Y", "3Y", "custom")


def test_relative_windows_end_on_the_as_of_date() -> None:
    as_of = date(2026, 11, 20)
    assert resolve_window("1M", as_of).start == date(2026, 10, 20)
    assert resolve_window("3M", as_of).start == date(2026, 8, 20)
    assert resolve_window("6M", as_of).start == date(2026, 5, 20)
    assert resolve_window("1Y", as_of).start == date(2025, 11, 20)
    assert resolve_window("3Y", as_of).start == date(2023, 11, 20)
    assert resolve_window("3m", as_of).end == as_of


def test_ytd_starts_on_january_first() -> None:
    window = resolve_window("YTD", date(2026, 11, 20))
    assert window.start == date(2026, 1, 1)
    assert window.end == date(2026, 11, 20)


def test_custom_requires_a_start() -> None:
    with pytest.raises(ValueError):
        resolve_window("custom", date(2026, 11, 20))
    window = resolve_window("custom", date(2026, 11, 20), custom_start=date(2024, 1, 2))
    assert (window.label, window.start, window.end) == (
        "custom",
        date(2024, 1, 2),
        date(2026, 11, 20),
    )


def test_unknown_timeframe_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_window("7D", date(2026, 11, 20))


def test_subtract_months_clamps_to_the_month_end() -> None:
    assert subtract_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert subtract_months(date(2024, 3, 31), 1) == date(2024, 2, 29)  # leap year
    assert subtract_months(date(2026, 1, 31), 1) == date(2025, 12, 31)


def test_a_window_before_the_stored_history_is_returned_unchanged() -> None:
    # Resolution is pure; the service clamps to the stored history and warns.
    window = resolve_window("3Y", date(2026, 11, 20))
    assert window.start == date(2023, 11, 20)
