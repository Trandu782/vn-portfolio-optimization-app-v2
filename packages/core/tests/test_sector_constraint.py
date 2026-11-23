"""The maximum-sector-weight constraint in the frontier and the random cloud."""

from __future__ import annotations

import numpy as np
import pytest

from core.optimize import (
    InfeasibleConstraintsError,
    OptimizeContext,
    build_constraint,
    build_efficient_frontier,
    sample_random_portfolios,
)
from core.optimize.sector_caps import group_indices_by_sector

#: Two stocks per sector across three sectors.
_SECTORS = {
    "BANKA": "Banks",
    "BANKB": "Banks",
    "TECHA": "Technology",
    "TECHB": "Technology",
    "ENERA": "Energy",
    "ENERB": "Energy",
}


def _returns(rows: int = 120) -> np.ndarray:
    """Return a deterministic non-degenerate daily returns matrix (6 columns)."""
    rng = np.random.default_rng(20261122)
    return rng.normal(0.0005, 0.01, size=(rows, len(_SECTORS)))


def _sector_sums(weights: dict[str, float]) -> dict[str, float]:
    sums: dict[str, float] = {}
    for symbol, weight in weights.items():
        sector = _SECTORS.get(symbol, "Unknown")
        sums[sector] = sums.get(sector, 0.0) + weight
    return sums


def test_constraint_returns_headroom_per_sector() -> None:
    constraint = build_constraint("max_sector_weight", {"max_sector_weight": 0.4})
    context = OptimizeContext(
        expected_returns=np.zeros(2),
        covariance=np.eye(2),
        risk_free_rate=0.03,
        investable_capital=1.0,
        prices={},
        symbols=("BANKA", "BANKB"),
        exchanges={},
        sectors={"BANKA": "Banks", "BANKB": "Banks"},
    )
    values = constraint.fun(np.array([0.2, 0.3]), context)
    assert float(values[0]) == pytest.approx(0.4 - 0.5)


def test_frontier_respects_the_sector_cap() -> None:
    cap = 0.50
    result = build_efficient_frontier(
        returns=_returns(),
        symbols=list(_SECTORS),
        risk_free_rate=0.03,
        max_weight=0.50,
        sectors=_SECTORS,
        max_sector_weight=cap,
        num_portfolios=50,
        seed=1,
        frontier_points=12,
    )
    for point in (*result.frontier, result.min_variance, result.tangency):
        for sector, total in _sector_sums(point.weights).items():
            assert total <= cap + 1e-4, f"{sector} exceeded the cap: {total:.4f}"


def test_random_cloud_respects_the_sector_cap() -> None:
    cap = 0.50
    returns = _returns()
    symbols = list(_SECTORS)
    cloud = sample_random_portfolios(
        expected_returns=returns.mean(axis=0) * 252,
        covariance=np.cov(returns, rowvar=False) * 252,
        risk_free_rate=0.03,
        num_portfolios=200,
        max_weight=0.50,
        seed=2,
        sector_groups=group_indices_by_sector(symbols, _SECTORS),
        max_sector_weight=cap,
    )
    assert cloud.weights.shape[0] == 200
    for row in cloud.weights:
        for indices in group_indices_by_sector(symbols, _SECTORS).values():
            assert float(np.sum(row[list(indices)])) <= cap + 1e-9


def test_infeasible_sector_cap_raises_a_clear_error() -> None:
    with pytest.raises(InfeasibleConstraintsError) as error:
        build_efficient_frontier(
            returns=_returns(),
            symbols=list(_SECTORS),
            risk_free_rate=0.03,
            max_weight=0.50,
            sectors=_SECTORS,
            max_sector_weight=0.10,
            num_portfolios=10,
            seed=1,
            frontier_points=5,
        )
    assert "maximum sector weight" in str(error.value)
