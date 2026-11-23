"""Group-index construction: coverage rule, cap redistribution, rebalance, gaps."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from data.v2.analytics.index import (
    WEIGHTING_EQUAL,
    WEIGHTING_MARKET_CAP,
    GroupConstituent,
    apply_cap,
    build_group_index,
    target_weights,
)


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _returns(days: list[date], value: float = 0.0) -> dict[date, float]:
    return dict.fromkeys(days, value)


def _proportions(scores: Mapping[str, float]) -> dict[str, float]:
    total = sum(scores.values())
    return {key: value / total for key, value in scores.items()}


def test_apply_cap_sums_to_one_and_respects_the_cap() -> None:
    values = [100, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    raw = _proportions({f"S{index}": value for index, value in enumerate(values)})
    weights, applied = apply_cap(raw, 0.15)
    assert applied
    assert abs(sum(weights.values()) - 1.0) < 1e-12
    assert max(weights.values()) <= 0.15 + 1e-12


def test_an_infeasible_cap_is_left_off() -> None:
    raw = _proportions({"A": 1.0, "B": 1.0, "C": 1.0})
    weights, applied = apply_cap(raw, 0.15)
    assert not applied
    assert all(abs(weight - 1.0 / 3.0) < 1e-12 for weight in weights.values())


def test_no_cap_returns_the_proportional_weights() -> None:
    weights, applied = apply_cap(_proportions({"A": 3.0, "B": 1.0}), None)
    assert not applied
    assert weights["A"] == 0.75
    assert weights["B"] == 0.25


def test_target_weights_equal_and_market_cap() -> None:
    constituents = [
        GroupConstituent("A", {}, 100.0),
        GroupConstituent("B", {}, 300.0),
    ]
    equal, applied, _ = target_weights(constituents, WEIGHTING_EQUAL, None)
    assert applied is False
    assert equal == {"A": 0.5, "B": 0.5}
    market_cap, _, _ = target_weights(constituents, WEIGHTING_MARKET_CAP, None)
    assert abs(market_cap["A"] - 0.25) < 1e-12
    assert abs(market_cap["B"] - 0.75) < 1e-12


def test_target_weights_warn_when_the_cap_is_infeasible() -> None:
    constituents = [GroupConstituent(name, {}, 1.0) for name in ("A", "B", "C")]
    weights, applied, warnings = target_weights(constituents, WEIGHTING_EQUAL, 0.15)
    assert not applied
    assert weights == {"A": 1.0 / 3.0, "B": 1.0 / 3.0, "C": 1.0 / 3.0}
    assert warnings and "infeasible" in warnings[0]


def test_coverage_rule_excludes_a_partial_history_and_renormalizes() -> None:
    days = _weekdays(date(2024, 1, 2), 10)
    index = build_group_index(
        "Banks",
        [
            GroupConstituent("FULL", _returns(days), 400.0),
            GroupConstituent("PARTIAL", _returns(days[:7]), 100.0),
            GroupConstituent("B", _returns(days), 300.0),
            GroupConstituent("C", _returns(days), 300.0),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert index.status == "ok"
    assert "PARTIAL" in index.excluded
    assert index.constituents == ["B", "C", "FULL"]
    assert abs(sum(index.weights.values()) - 1.0) < 1e-12


def test_market_cap_weighting_drops_a_constituent_without_market_cap() -> None:
    days = _weekdays(date(2024, 1, 2), 10)
    index = build_group_index(
        "G",
        [
            GroupConstituent("A", _returns(days), 100.0),
            GroupConstituent("B", _returns(days), 100.0),
            GroupConstituent("C", _returns(days), 100.0),
            GroupConstituent("D", _returns(days), None),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_MARKET_CAP,
        single_stock_cap=None,
    )
    assert index.status == "ok"
    assert "D" in index.excluded
    assert index.constituent_count == 3


def test_fewer_than_three_constituents_is_insufficient() -> None:
    days = _weekdays(date(2024, 1, 2), 10)
    index = build_group_index(
        "Banks",
        [
            GroupConstituent("A", _returns(days), 1.0),
            GroupConstituent("B", _returns(days), 1.0),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert index.status == "insufficient"
    assert index.constituent_count == 2
    assert index.cumulative_returns == []
    assert index.warnings


def test_equal_weight_index_matches_a_hand_computation() -> None:
    days = _weekdays(date(2024, 1, 2), 4)
    a = {days[0]: 0.0, days[1]: 0.10, days[2]: 0.10, days[3]: 0.10}
    zero = _returns(days, 0.0)
    index = build_group_index(
        "G",
        [
            GroupConstituent("A", a, 1.0),
            GroupConstituent("B", zero, 1.0),
            GroupConstituent("C", zero, 1.0),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert index.cumulative_returns[0].value == 0.0
    assert abs(index.cumulative_returns[1].value - 3.3333333) < 1e-6
    # Buy-and-hold: (1.21 + 1 + 1) / 3 - 1 = 7.0% after two +10% days on A.
    assert abs(index.cumulative_returns[2].value - 7.0) < 1e-9


def test_quarterly_rebalance_re_applies_the_target_weights() -> None:
    # 2024-03-31 is a Sunday, so the quarter-end rebalance lands on Fri 2024-03-29.
    days = _weekdays(date(2024, 3, 27), 5)
    a = _returns(days, 0.10)
    zero = _returns(days, 0.0)
    index = build_group_index(
        "G",
        [
            GroupConstituent("A", a, 1.0),
            GroupConstituent("B", zero, 1.0),
            GroupConstituent("C", zero, 1.0),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert abs(index.daily_returns[date(2024, 3, 29)] - 0.10 / 3.0) < 1e-12
    assert index.daily_returns[date(2024, 4, 1)] > 0.10 / 3.0


def test_a_single_missing_day_renormalizes_among_available_names() -> None:
    days = _weekdays(date(2024, 1, 2), 10)
    a = {day: 0.0 for day in days if day != days[5]}
    ten = _returns(days, 0.10)
    index = build_group_index(
        "G",
        [
            GroupConstituent("A", a, 1.0),
            GroupConstituent("B", ten, 1.0),
            GroupConstituent("C", ten, 1.0),
        ],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert "A" not in index.excluded
    assert abs(index.daily_returns[days[5]] - 0.10) < 1e-12
    assert index.excluded == {}


def test_the_cumulative_path_starts_at_zero_with_one_point_per_day() -> None:
    days = _weekdays(date(2024, 1, 2), 6)
    index = build_group_index(
        "G",
        [GroupConstituent(name, _returns(days, 0.01), 1.0) for name in ("A", "B", "C")],
        trading_days=frozenset(days),
        start=days[0],
        end=days[-1],
        weighting=WEIGHTING_EQUAL,
        single_stock_cap=None,
    )
    assert [point.date for point in index.cumulative_returns] == days
    assert index.cumulative_returns[0].value == 0.0


def test_market_cap_target_weights_apply_a_feasible_cap_and_sum_to_one() -> None:
    # Regression: raw market caps must be normalised before the cap, otherwise every
    # name is "over" the cap and the result collapses to equal, non-normalised weights.
    market_caps = [100.0, 50.0, 30.0, 20.0, 15.0, 10.0, 8.0, 7.0, 5.0, 5.0]
    constituents = [
        GroupConstituent(f"S{index}", {}, value)
        for index, value in enumerate(market_caps)
    ]
    weights, applied, warnings = target_weights(constituents, WEIGHTING_MARKET_CAP, 0.15)
    assert applied is True
    assert abs(sum(weights.values()) - 1.0) < 1e-12
    assert max(weights.values()) <= 0.15 + 1e-12
    assert warnings == []
    # The market-cap ordering is preserved among the uncapped names (not equal weight).
    assert weights["S0"] == 0.15
    assert weights["S0"] > weights["S9"]

