"""Quality checks registry."""

from __future__ import annotations

from datetime import date

from support import make_bar

from data.quality import quality_checks, run_quality_checks


def test_registry_exposes_all_checks() -> None:
    assert set(quality_checks.list()) == {
        "missing_trading_days",
        "stale_price_runs",
        "zero_volume",
        "price_limit_move",
    }
    described = {info.id: info for info in quality_checks.describe()}
    assert described["missing_trading_days"].parameter_schema is not None


def test_clean_weekday_series_has_no_findings() -> None:
    days = [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
    ]
    bars = [make_bar(day, 10.0 + index * 0.1) for index, day in enumerate(days)]
    report = run_quality_checks("VNM", bars, exchange="HOSE")
    assert report.ok
    assert report.findings == []


def test_missing_trading_day_is_flagged() -> None:
    bars = [make_bar(date(2024, 1, 2), 10.0), make_bar(date(2024, 1, 4), 11.0)]
    report = run_quality_checks("VNM", bars, exchange="HOSE")
    finding = next(f for f in report.findings if f.check == "missing_trading_days")
    assert finding.dates == [date(2024, 1, 3)]
    assert not report.ok


def test_stale_price_run_is_flagged() -> None:
    days = [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
    ]
    bars = [make_bar(day, 10.0) for day in days]
    report = run_quality_checks("VNM", bars, exchange="HOSE")
    assert any(f.check == "stale_price_runs" for f in report.findings)


def test_zero_volume_is_flagged() -> None:
    bars = [make_bar(date(2024, 1, 2), 10.0, volume=0)]
    report = run_quality_checks("VNM", bars, exchange="HOSE")
    assert any(f.check == "zero_volume" for f in report.findings)


def test_move_beyond_price_limit_is_flagged() -> None:
    bars = [make_bar(date(2024, 1, 2), 100.0), make_bar(date(2024, 1, 3), 120.0)]
    report = run_quality_checks("VNM", bars, exchange="HOSE")
    finding = next(f for f in report.findings if f.check == "price_limit_move")
    assert finding.severity == "error"
    assert not report.ok
