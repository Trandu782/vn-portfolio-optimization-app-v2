"""V2 data-quality checks that fail loudly."""

from __future__ import annotations

from datetime import date, timedelta

from data.v2.quality import run_v2_quality_checks, v2_quality_checks
from data.v2.schemas import AdjustedOHLCV, CorporateAction


def _bar(
    day: date,
    close: float,
    *,
    close_raw: float | None = None,
    volume: int = 1000,
) -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        close_raw=close_raw,
        volume=volume,
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


def _checks(report) -> set[str]:
    return {finding.check for finding in report.findings if finding.severity == "error"}


def _warnings(report) -> set[str]:
    return {finding.check for finding in report.findings if finding.severity == "warning"}


def test_registry_exposes_every_check() -> None:
    assert set(v2_quality_checks.list()) == {
        "no_data",
        "missing_trading_days",
        "duplicate_dates",
        "zero_volume_streak",
        "suspicious_returns",
        "adjusted_vs_raw_mismatch",
    }


def test_clean_series_has_no_findings() -> None:
    days = _weekdays(5)
    bars = [
        _bar(day, 100.0 + index, close_raw=(100.0 + index) * 1.001)
        for index, day in enumerate(days)
    ]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert report.ok
    assert report.findings == []


def test_no_data_is_an_integrity_error() -> None:
    report = run_v2_quality_checks("VCB", [], exchange="HOSE")
    assert "no_data" in _checks(report)
    assert report.ok is False


def test_missing_trading_day_is_a_warning() -> None:
    bars = [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 4), 101.0)]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert "missing_trading_days" in _warnings(report)
    assert report.ok


def test_duplicate_dates_are_an_error() -> None:
    bars = [
        _bar(date(2024, 1, 2), 100.0),
        _bar(date(2024, 1, 2), 101.0),
        _bar(date(2024, 1, 3), 102.0),
    ]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert "duplicate_dates" in _checks(report)


def test_zero_volume_streak_is_a_warning() -> None:
    days = _weekdays(6)
    bars = [_bar(day, 100.0, volume=0) for day in days]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert "zero_volume_streak" in _warnings(report)
    assert report.ok


def test_suspicious_return_away_from_an_ex_date_is_a_warning() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 120.0), _bar(days[2], 121.0)]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert "suspicious_returns" in _warnings(report)
    assert report.ok


def test_suspicious_return_at_an_ex_date_is_not_flagged() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 90.0), _bar(days[2], 91.0)]
    action = CorporateAction(
        ticker="VCB", event_type="ISS", exright_date=days[1], ratio=0.1, source="ssi"
    )
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE", actions=[action])
    assert "suspicious_returns" not in _checks(report)


def test_adjusted_vs_raw_ratio_jump_without_action_is_a_warning() -> None:
    bars = [
        _bar(date(2024, 1, 2), 100.0, close_raw=110.0),
        _bar(date(2024, 1, 3), 100.0, close_raw=100.0),
    ]
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE")
    assert "adjusted_vs_raw_mismatch" in _warnings(report)
    assert report.ok


def test_adjusted_vs_raw_ratio_jump_explained_by_a_dividend_is_ok() -> None:
    bars = [
        _bar(date(2024, 1, 2), 100.0, close_raw=110.0),
        _bar(date(2024, 1, 3), 100.0, close_raw=100.0),
    ]
    action = CorporateAction(
        ticker="VCB", event_type="DIV", exright_date=date(2024, 1, 3), value=10.0, source="ssi"
    )
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE", actions=[action])
    assert "adjusted_vs_raw_mismatch" not in _checks(report)


def test_missing_trading_days_uses_a_supplied_calendar() -> None:
    bars = [_bar(date(2024, 1, 2), 100.0), _bar(date(2024, 1, 4), 101.0)]
    calendar = frozenset({date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)})
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE", trading_days=calendar)
    finding = next(f for f in report.findings if f.check == "missing_trading_days")
    assert finding.dates == [date(2024, 1, 3)]


def test_supplied_calendar_days_outside_the_series_are_ignored() -> None:
    bars = [_bar(date(2024, 1, 3), 100.0), _bar(date(2024, 1, 4), 101.0)]
    calendar = frozenset({date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)})
    report = run_v2_quality_checks("VCB", bars, exchange="HOSE", trading_days=calendar)
    assert "missing_trading_days" not in _checks(report)


def _weekdays_between(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _ratio_jump_bars() -> list:
    return [
        _bar(date(2024, 1, 2), 100.0, close_raw=110.0),
        _bar(date(2024, 1, 3), 100.0, close_raw=100.0),
    ]


def test_an_explained_finding_is_a_warning_and_keeps_the_step_ok() -> None:
    report = run_v2_quality_checks("VGI", _ratio_jump_bars(), exchange="HOSE")
    finding = next(f for f in report.findings if f.check == "adjusted_vs_raw_mismatch")
    assert finding.severity == "warning"
    assert finding.details["explained"]
    assert report.ok


def test_an_unexplained_finding_stays_a_warning() -> None:
    report = run_v2_quality_checks("VCB", _ratio_jump_bars(), exchange="HOSE")
    finding = next(f for f in report.findings if f.check == "adjusted_vs_raw_mismatch")
    assert finding.severity == "warning"
    assert "explained" not in finding.details
    assert report.ok


def test_the_bsr_halt_is_explained_as_a_warning() -> None:
    bars = [_bar(date(2025, 1, 6), 100.0), _bar(date(2025, 1, 17), 101.0)]
    calendar = frozenset(_weekdays_between(date(2025, 1, 6), date(2025, 1, 17)))
    report = run_v2_quality_checks("BSR", bars, exchange="HOSE", trading_days=calendar)
    missing = next(f for f in report.findings if f.check == "missing_trading_days")
    assert missing.severity == "warning"
    assert report.ok


def test_an_eight_percent_move_is_not_suspicious_under_the_widest_limit() -> None:
    days = _weekdays(3)
    bars = [_bar(days[0], 100.0), _bar(days[1], 108.0), _bar(days[2], 108.0)]
    report = run_v2_quality_checks("BSR", bars, exchange="HOSE")
    assert "suspicious_returns" not in _checks(report)
    assert report.ok

