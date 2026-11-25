"""Trading-calendar helpers built on the market holiday set.

Weekends and the exchange holidays in ``core.market_rules`` are non-trading days.
These helpers are used for staleness detection (last trading day) and the
missing-trading-days quality check. They are pure functions so they are trivial
to test with a fixed calendar.

:func:`trading_days_from_dates` is the alternative to the illustrative holiday set:
it derives the real calendar from a reference series' bar dates (the stored VN-Index
bars), and its output is also the denominator for the planned "80% of trading days"
coverage rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, timezone

#: Vietnam's fixed offset from UTC. The country has observed UTC+7 all year with no
#: daylight saving since 1975, so a fixed offset is exact and needs no tzdata package
#: (which a Windows runner does not ship with :mod:`zoneinfo`).
VIETNAM_UTC_OFFSET = timezone(timedelta(hours=7))

#: Exchange time zone name, for log lines and docs.
VIETNAM_TIME_ZONE = "Asia/Ho_Chi_Minh"


def _vietnam_moment(now: datetime | None) -> datetime:
    """Return ``now`` (default: the current instant) as a Vietnam wall-clock moment.

    A naive datetime is read as UTC, which is what a runner's ``datetime.now()``
    returns when it has no timezone attached.
    """
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(VIETNAM_UTC_OFFSET)


def vietnam_today(now: datetime | None = None) -> date:
    """Return the current calendar date in Vietnam (UTC+7).

    The scheduled precompute job runs on a UTC runner, so ``date.today()`` there is
    the UTC date: 19:13 UTC is already 02:13 ICT on the *next* Vietnam calendar day,
    while a morning UTC run is still the same Vietnam date. Market sessions are
    defined by the Vietnam calendar, so the pipeline resolves "today" here.
    """
    return _vietnam_moment(now).date()


def is_trading_day(day: date, holidays: Iterable[date]) -> bool:
    """Return ``True`` when ``day`` is a weekday and not an exchange holiday."""
    return day.weekday() < 5 and day not in holidays


def last_trading_day(as_of: date, holidays: Iterable[date]) -> date:
    """Return the most recent trading day on or before ``as_of``."""
    holidays = frozenset(holidays)
    day = as_of
    while not is_trading_day(day, holidays):
        day -= timedelta(days=1)
    return day


def last_completed_session(
    now: datetime | None, *, holidays: Iterable[date], session_close: time
) -> date:
    """Return the most recent session whose end-of-day bars can already exist.

    A run *before* ``session_close`` (15:00 ICT) cannot have today's official close,
    so it targets the previous calendar day; a run at or after it targets today. The
    result is then rolled back over weekends and ``holidays``, so a market holiday
    yields the session before it instead of a date that never traded.

    This is the definition the precompute pipeline resolves its ``as_of`` with: a
    pre-close or holiday run then reports data defects instead of an upstream timing
    problem. It is not a substitute for the observed calendar — a holiday missing
    from ``holidays`` still yields a weekday, which the stored ``VNINDEX`` series
    settles further (see ``V2PrecomputeService._settle_target``).
    """
    moment = _vietnam_moment(now)
    day = moment.date()
    if moment.time() < session_close:
        day -= timedelta(days=1)
    return last_trading_day(day, holidays)


def trading_days_between(start: date, end: date, holidays: Iterable[date]) -> list[date]:
    """Return every trading day in ``[start, end]`` inclusive."""
    holidays = frozenset(holidays)
    if start > end:
        return []
    result: list[date] = []
    day = start
    while day <= end:
        if is_trading_day(day, holidays):
            result.append(day)
        day += timedelta(days=1)
    return result


def trading_days_from_dates(dates: Iterable[date]) -> frozenset[date]:
    """Return the observed trading days (distinct dates) of a reference series.

    The stored VN-Index bar dates are the exchange's real trading calendar: a session
    with an index bar was open, one without was a weekend or holiday. Deriving the
    calendar this way avoids a hardcoded holiday set, and the returned set is the
    denominator for the planned "80% of trading days" coverage rule.
    """
    return frozenset(dates)
