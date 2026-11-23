"""Benchmark-relative metrics: beta, R², correlation, volatility, low reliability."""

from __future__ import annotations

from datetime import date, timedelta

from data.v2.analytics.metrics import benchmark_metrics, compound_return


def _weekdays(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _alternating(days: list[date], step: float = 0.01) -> dict[date, float]:
    return {day: step * (-1) ** index for index, day in enumerate(days)}


def test_a_group_that_is_1_3_times_the_benchmark_has_beta_1_3() -> None:
    days = _weekdays(100)
    benchmark = _alternating(days)
    group = {day: 1.3 * value for day, value in benchmark.items()}
    metrics = benchmark_metrics(
        "Banks", group, benchmark, benchmark="VNINDEX", constituent_count=10
    )
    assert abs(metrics.beta - 1.3) < 1e-9  # type: ignore[operator]
    assert abs(metrics.correlation - 1.0) < 1e-9  # type: ignore[operator]
    assert abs(metrics.r_squared - 1.0) < 1e-9  # type: ignore[operator]
    assert not metrics.low_reliability
    assert metrics.observation_count == 100


def test_period_and_excess_returns_are_percentages() -> None:
    days = _weekdays(2)
    group = {days[0]: 0.05, days[1]: 0.05}
    benchmark = {days[0]: 0.10, days[1]: 0.10}
    metrics = benchmark_metrics(
        "G", group, benchmark, benchmark="VNINDEX", constituent_count=3
    )
    assert abs(metrics.period_return - (1.05**2 - 1.0) * 100.0) < 1e-9  # type: ignore[operator]
    assert abs(metrics.benchmark_period_return - (1.10**2 - 1.0) * 100.0) < 1e-9  # type: ignore[operator]
    expected_excess = metrics.period_return - metrics.benchmark_period_return
    assert abs(metrics.excess_return - expected_excess) < 1e-9  # type: ignore[operator]


def test_annualized_volatility_is_a_percentage() -> None:
    days = _weekdays(40)
    group = _alternating(days, 0.02)
    benchmark = _alternating(days, 0.01)
    metrics = benchmark_metrics(
        "G", group, benchmark, benchmark="VNINDEX", constituent_count=3
    )
    assert metrics.annualized_volatility is not None
    assert metrics.annualized_volatility > 0.0


def test_low_reliability_below_sixty_observations() -> None:
    short_days = _weekdays(30)
    short_metrics = benchmark_metrics(
        "G",
        _alternating(short_days),
        _alternating(short_days, 0.005),
        benchmark="VNINDEX",
        constituent_count=3,
    )
    assert short_metrics.low_reliability
    assert short_metrics.observation_count == 30

    long_days = _weekdays(80)
    long_metrics = benchmark_metrics(
        "G",
        _alternating(long_days),
        _alternating(long_days, 0.005),
        benchmark="VNINDEX",
        constituent_count=3,
    )
    assert not long_metrics.low_reliability


def test_short_history_has_no_beta_and_is_low_reliability() -> None:
    days = _weekdays(1)
    metrics = benchmark_metrics(
        "G", {days[0]: 0.01}, {days[0]: 0.01}, benchmark="VNINDEX", constituent_count=1
    )
    assert metrics.beta is None
    assert metrics.correlation is None
    assert metrics.r_squared is None
    assert metrics.observation_count == 1
    assert metrics.low_reliability


def test_empty_benchmark_is_reported_not_invented() -> None:
    days = _weekdays(5)
    metrics = benchmark_metrics(
        "G", dict.fromkeys(days, 0.01), {}, benchmark="VN100", constituent_count=3
    )
    assert metrics.benchmark_period_return is None
    assert metrics.excess_return is None
    assert metrics.beta is None
    assert any("no returns" in warning for warning in metrics.warnings)


def test_zero_variance_benchmark_has_no_beta() -> None:
    days = _weekdays(5)
    benchmark = dict.fromkeys(days, 0.0)
    group = dict.fromkeys(days, 0.01)
    metrics = benchmark_metrics(
        "G", group, benchmark, benchmark="VNINDEX", constituent_count=3
    )
    assert metrics.beta is None
    assert any("zero variance" in warning for warning in metrics.warnings)


def test_compound_return_compounds_simple_returns() -> None:
    assert compound_return({date(2024, 1, 2): 0.10, date(2024, 1, 3): 0.10}) == (
        1.10 * 1.10 - 1.0
    )
