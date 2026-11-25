"""Unit tests for the efficient frontier and the random-portfolio cloud.

The network is never touched: every test builds a returns matrix by hand and calls
the pure frontier engine directly. Deterministic sinusoids stand in for prices so
the same seed always produces the same cloud.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from core.optimize import (
    MAX_RANDOM_PORTFOLIOS,
    InfeasibleConstraintsError,
    RandomCloud,
    build_efficient_frontier,
    sample_random_portfolios,
    stratified_cloud_indices,
)
from core.optimize._math import sample_covariance

RISK_FREE_RATE = 0.03
TRADING_DAYS = 252


def _two_asset_returns() -> np.ndarray:
    """Two assets: A is low variance (preferred), B is high variance."""
    t = np.arange(240, dtype=np.float64)
    return np.column_stack([0.006 * np.cos(t), 0.02 * np.sin(t)])


def _five_asset_returns() -> np.ndarray:
    """Five assets with different drifts and cycles (no NaN)."""
    t = np.arange(300, dtype=np.float64)
    return np.column_stack(
        [
            0.0004 + 0.010 * np.sin(t / 7.0),
            0.0006 + 0.012 * np.cos(t / 9.0),
            0.0003 + 0.008 * np.sin(t / 5.0 + 0.7),
            0.0005 + 0.011 * np.cos(t / 11.0 + 1.3),
            0.0007 + 0.013 * np.sin(t / 13.0 + 2.1),
        ]
    )


def _symbols(count: int) -> list[str]:
    return [chr(ord("A") + index) for index in range(count)]


def _frontier(
    returns: np.ndarray,
    *,
    max_weight: float = 0.5,
    num_portfolios: int = 400,
    seed: int | None = 11,
    frontier_points: int = 20,
    current_weights: dict[str, float] | None = None,
):
    """Build a frontier with fast test defaults."""
    symbols = _symbols(returns.shape[1])
    return build_efficient_frontier(
        returns=returns,
        symbols=symbols,
        risk_free_rate=RISK_FREE_RATE,
        max_weight=max_weight,
        num_portfolios=num_portfolios,
        seed=seed,
        frontier_points=frontier_points,
        current_weights=current_weights,
    )


def test_analytical_two_asset_min_variance_portfolio() -> None:
    returns = _two_asset_returns()
    sigma = sample_covariance(returns) * TRADING_DAYS
    s11, s12, s22 = float(sigma[0, 0]), float(sigma[0, 1]), float(sigma[1, 1])
    expected_a = (s22 - s12) / (s11 + s22 - 2.0 * s12)

    result = _frontier(returns, max_weight=1.0)

    assert result.min_variance.weights["A"] == pytest.approx(expected_a, abs=1e-4)
    weights = result.min_variance.weights
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-8)


def test_random_cloud_sums_to_one_and_respects_the_cap() -> None:
    returns = _five_asset_returns()
    expected = np.asarray(returns.mean(axis=0) * TRADING_DAYS, dtype=np.float64)
    covariance = np.asarray(sample_covariance(returns) * TRADING_DAYS, dtype=np.float64)

    cloud = sample_random_portfolios(
        expected_returns=expected,
        covariance=covariance,
        risk_free_rate=RISK_FREE_RATE,
        num_portfolios=500,
        max_weight=0.4,
        seed=3,
    )

    assert cloud.generated == 500
    assert cloud.weights.shape == (500, 5)
    assert np.allclose(cloud.weights.sum(axis=1), 1.0, atol=1e-10)
    assert float(np.max(cloud.weights)) <= 0.4 + 1e-10
    assert cloud.returns.shape == (500,)
    assert cloud.volatilities.shape == (500,)
    assert np.all(cloud.volatilities >= 0.0)


def test_frontier_points_sum_to_one_and_respect_the_cap() -> None:
    result = _frontier(_five_asset_returns(), max_weight=0.4)

    points = [
        *result.frontier,
        result.min_variance,
        result.tangency,
        result.equal_weight,
    ]
    assert len(result.frontier) >= 2
    for point in points:
        total = sum(point.weights.values())
        assert total == pytest.approx(1.0, abs=1e-6)
        assert max(point.weights.values()) <= 0.4 + 1e-4


def test_frontier_volatility_is_non_decreasing_in_return() -> None:
    result = _frontier(_five_asset_returns(), max_weight=0.4)

    ordered = sorted(result.frontier, key=lambda point: point.expected_return)
    returns = [point.expected_return for point in ordered]
    volatilities = [point.volatility for point in ordered]
    assert all(
        later >= earlier - 1e-9 for earlier, later in itertools.pairwise(volatilities)
    )
    assert all(later >= earlier - 1e-9 for earlier, later in itertools.pairwise(returns))


def test_same_seed_gives_identical_results() -> None:
    returns = _five_asset_returns()
    first = _frontier(returns, num_portfolios=200, seed=99)
    second = _frontier(returns, num_portfolios=200, seed=99)

    assert np.array_equal(first.random_cloud.returns, second.random_cloud.returns)
    assert np.array_equal(first.random_cloud.weights, second.random_cloud.weights)
    assert first.tangency.sharpe == pytest.approx(second.tangency.sharpe, abs=1e-12)
    assert [point.expected_return for point in first.frontier] == pytest.approx(
        [point.expected_return for point in second.frontier], abs=1e-12
    )


def test_infeasible_max_weight_raises_a_clear_error() -> None:
    with pytest.raises(InfeasibleConstraintsError, match=r"cannot reach"):
        _frontier(_five_asset_returns(), max_weight=0.15)


def test_random_portfolio_count_bounds_are_enforced() -> None:
    returns = _five_asset_returns()
    with pytest.raises(ValueError, match=r"at least 1"):
        _frontier(returns, num_portfolios=0)
    with pytest.raises(ValueError, match=r"at most"):
        _frontier(returns, num_portfolios=MAX_RANDOM_PORTFOLIOS + 1)


def test_tangency_sharpe_beats_every_random_portfolio() -> None:
    result = _frontier(_five_asset_returns(), max_weight=0.5, num_portfolios=800, seed=5)

    assert result.random_cloud.generated == 800
    assert result.tangency.sharpe >= float(np.max(result.random_cloud.sharpes)) - 1e-9


def test_tangency_lies_on_the_efficient_frontier() -> None:
    """The Max-Sharpe marker must sit on the plotted frontier, not float apart from it."""
    result = _frontier(_five_asset_returns(), max_weight=0.5, num_portfolios=400, seed=5)

    frontier_returns = np.array([point.expected_return for point in result.frontier])
    frontier_vols = np.array([point.volatility for point in result.frontier])

    # The tangency point is on the frontier when its (return, volatility) equals one of
    # the frontier points (an SLSQP drift off the minimum-variance envelope would show a
    # clearly higher volatility at the same return, or no matching frontier point).
    d_return = np.abs(frontier_returns - result.tangency.expected_return)
    d_vol = np.abs(frontier_vols - result.tangency.volatility)
    matched = np.min(np.hypot(d_return, d_vol))
    assert matched < 1e-4, (
        f"Max-Sharpe point is off the frontier (closest frontier distance {matched:.2e})"
    )

    # The tangency point must also be the best-Sharpe point on the frontier itself.
    frontier_sharpes = [point.sharpe for point in result.frontier]
    assert result.tangency.sharpe >= max(frontier_sharpes) - 1e-12


def test_current_portfolio_is_projected_onto_the_universe() -> None:
    result = _frontier(
        _five_asset_returns(),
        max_weight=0.5,
        current_weights={"A": 2.0, "B": 2.0, "Z": 6.0},
    )

    current = result.current
    assert current is not None
    assert sum(current.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert current.weights["A"] == pytest.approx(0.5, abs=1e-9)
    assert current.weights["B"] == pytest.approx(0.5, abs=1e-9)
    assert "Z" not in current.weights
    assert set(current.weights) == {"A", "B", "C", "D", "E"}


def test_current_point_is_omitted_without_overlap() -> None:
    result = _frontier(
        _five_asset_returns(), max_weight=0.5, current_weights={"Z": 1.0}
    )
    assert result.current is None


def test_targets_are_either_accepted_or_skipped() -> None:
    result = _frontier(_five_asset_returns(), max_weight=0.4, frontier_points=20)

    assumptions = result.assumptions
    assert assumptions.frontier_points + assumptions.skipped_targets == 20
    assert assumptions.portfolios_requested == 400
    assert assumptions.portfolios_generated == 400
    assert assumptions.seed == 11
    assert math.isfinite(assumptions.max_weight)


# -- cloud sampling (server-side downsampling of the plotted scatter) ---------


def _cloud(num_portfolios: int = 4_000, seed: int = 21) -> RandomCloud:
    """A deterministic cloud with a spread of volatilities and returns."""
    returns = _five_asset_returns()
    expected = np.asarray(returns.mean(axis=0) * TRADING_DAYS, dtype=np.float64)
    covariance = np.asarray(sample_covariance(returns) * TRADING_DAYS, dtype=np.float64)
    return sample_random_portfolios(
        expected_returns=expected,
        covariance=covariance,
        risk_free_rate=RISK_FREE_RATE,
        num_portfolios=num_portfolios,
        max_weight=1.0,
        seed=seed,
    )


def test_the_hard_cap_allows_a_full_hundred_thousand_portfolio_run() -> None:
    """The simulation ceiling is 100k; the payload cap is a separate concern."""
    assert MAX_RANDOM_PORTFOLIOS == 100_000


def test_cloud_sample_returns_the_whole_cloud_when_it_fits() -> None:
    cloud = _cloud(600)
    indices = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=600)

    assert np.array_equal(indices, np.arange(600))


def test_cloud_sample_respects_the_budget_and_is_sorted_and_unique() -> None:
    cloud = _cloud()
    indices = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=1_500)

    assert indices.size <= 1_500
    assert indices.size >= 1_000  # the budget is actually spent
    assert np.all(np.diff(indices) > 0)  # ascending and unique
    assert int(indices.max()) < cloud.generated


def test_cloud_sample_keeps_the_global_extremes_of_the_cloud() -> None:
    cloud = _cloud()
    indices = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=1_500)
    kept = set(indices.tolist())

    for index in (
        int(np.argmax(cloud.returns)),
        int(np.argmin(cloud.returns)),
        int(np.argmax(cloud.volatilities)),
        int(np.argmin(cloud.volatilities)),
    ):
        assert index in kept


def test_cloud_sample_keeps_the_upper_envelope_of_every_volatility_slice() -> None:
    """The efficient edge of the scatter must survive the sample."""
    cloud = _cloud()
    indices = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=1_500)
    kept_returns = cloud.returns[indices]

    order = np.argsort(cloud.volatilities)
    slices = np.array_split(order, 10)
    for slice_indices in slices:
        full_best = float(np.max(cloud.returns[slice_indices]))
        sampled_best = float(np.max(kept_returns))
        # The slice's best portfolio is kept (its cell takes its own extreme), so a
        # max over the whole sample is at least as good as the slice's own best.
        assert sampled_best >= full_best - 1e-12


def test_cloud_sample_is_deterministic() -> None:
    cloud = _cloud()
    first = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=900)
    second = stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=900)

    assert np.array_equal(first, second)


def test_cloud_sample_falls_back_to_a_stride_for_a_tiny_budget() -> None:
    cloud = _cloud()
    indices = stratified_cloud_indices(
        cloud.returns, cloud.volatilities, max_points=10, bins=25
    )

    assert indices.size == 10
    assert indices[0] == 0
    assert indices[-1] == cloud.generated - 1


def test_cloud_sample_validates_its_inputs() -> None:
    cloud = _cloud(400)
    with pytest.raises(ValueError, match=r"same length"):
        stratified_cloud_indices(cloud.returns, cloud.volatilities[:-1])
    with pytest.raises(ValueError, match=r"at least 1"):
        stratified_cloud_indices(cloud.returns, cloud.volatilities, max_points=0)
    with pytest.raises(ValueError, match=r"at least 1"):
        stratified_cloud_indices(cloud.returns, cloud.volatilities, bins=0)

