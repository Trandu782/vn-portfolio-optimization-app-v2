"""Unit tests for the optimization engine, registries, estimators and lot rounding.

The network is never touched: every test builds matrices by hand and calls the
pure engine directly.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from pydantic import BaseModel, ValidationError

from core.market_rules import DEFAULT_MARKET_RULES
from core.optimize import (
    HARD_MAX_STOCKS,
    ConstraintSpec,
    InfeasibleConstraintsError,
    OptimizeContext,
    OptimizeResult,
    build_constraint,
    build_covariance_estimator,
    build_objective,
    build_return_estimator,
    constraints,
    covariance_estimators,
    default_max_weight,
    exceeds_hard_max,
    feasible_max_weight,
    lot_size_for,
    objectives,
    optimize,
    return_estimators,
    round_to_lots,
    solvers,
    universe_size_warnings,
)
from core.optimize._math import sample_covariance

START = date(2024, 1, 2)
END = date(2024, 6, 28)
TRADING_DAYS = 252


def _two_asset_returns() -> np.ndarray:
    """Two assets: A is low variance (preferred), B is high variance."""
    t = np.arange(240, dtype=np.float64)
    return np.column_stack([0.006 * np.cos(t), 0.02 * np.sin(t)])


def _concentrated_returns() -> np.ndarray:
    """Three assets where minimum variance concentrates on the first."""
    t = np.arange(240, dtype=np.float64)
    return np.column_stack(
        [0.002 * np.sin(t), 0.02 * np.sin(t + 1.0), 0.02 * np.cos(t + 0.5)]
    )


def _symbols(count: int) -> tuple[str, ...]:
    return tuple(chr(ord("A") + index) for index in range(count))


def _engine(
    returns: np.ndarray,
    *,
    objective: str = "min_variance",
    covariance: str = "sample",
    constraint_specs: list[ConstraintSpec] | None = None,
    capital: int = 1_000_000_000,
    prices: dict[str, float] | None = None,
    risk_free_rate: float = 0.03,
) -> OptimizeResult:
    """Run the engine with sensible test defaults and return the result."""
    symbols = _symbols(returns.shape[1])
    return optimize(
        symbols=symbols,
        exchanges=dict.fromkeys(symbols, "HOSE"),
        returns=returns,
        prices=prices or dict.fromkeys(symbols, 10000.0),
        capital=capital,
        objective_id=objective,
        return_estimator_id="historical_mean",
        covariance_estimator_id=covariance,
        constraint_specs=constraint_specs or [],
        risk_free_rate=risk_free_rate,
        start=START,
        end=END,
    )


def test_analytical_min_variance_for_two_assets() -> None:
    returns = _two_asset_returns()
    sigma = sample_covariance(returns) * TRADING_DAYS
    s11, s12, s22 = float(sigma[0, 0]), float(sigma[0, 1]), float(sigma[1, 1])
    expected_a = (s22 - s12) / (s11 + s22 - 2.0 * s12)

    result = _engine(returns)

    assert result.weights["A"] == pytest.approx(expected_a, abs=1e-4)
    assert result.weights["A"] + result.weights["B"] == pytest.approx(1.0, abs=1e-8)


def test_output_is_deterministic() -> None:
    returns = _two_asset_returns()
    first = _engine(returns)
    second = _engine(returns)

    for code in first.symbols:
        assert first.weights[code] == pytest.approx(second.weights[code], abs=1e-12)
        assert first.lots[code] == second.lots[code]
    assert first.expected_return == pytest.approx(second.expected_return, abs=1e-12)


def test_max_weight_is_respected_and_binding() -> None:
    result = _engine(
        _concentrated_returns(),
        constraint_specs=[ConstraintSpec("max_weight", {"max_weight": 0.5})],
    )

    assert max(result.weights.values()) <= 0.5 + 1e-4
    assert "max_weight" in result.binding_constraints


def test_cash_reserve_carves_capital_and_reports_cash() -> None:
    result = _engine(
        _two_asset_returns(),
        capital=1_000_000_000,
        constraint_specs=[ConstraintSpec("cash_reserve", {"reserve": 0.2})],
    )

    assert result.cash_reserve == pytest.approx(0.2)
    assert result.cash_reserve_value == 200_000_000
    assert result.assumptions.investable_capital == 800_000_000


def test_infeasible_constraints_raise_clear_error() -> None:
    with pytest.raises(InfeasibleConstraintsError, match=r"could not satisfy|violated"):
        _engine(
            _two_asset_returns(),
            constraint_specs=[ConstraintSpec("max_weight", {"max_weight": 0.01})],
        )


def _context(returns: np.ndarray, *, capital: float = 1e9) -> OptimizeContext:
    """Build an OptimizeContext for direct objective/constraint tests."""
    count = returns.shape[1]
    symbols = _symbols(count)
    return OptimizeContext(
        expected_returns=np.zeros(count),
        covariance=sample_covariance(returns) * TRADING_DAYS,
        risk_free_rate=0.03,
        investable_capital=capital,
        prices=dict.fromkeys(symbols, 10000.0),
        symbols=symbols,
        exchanges=dict.fromkeys(symbols, "HOSE"),
    )


def test_return_estimators_annualize_the_mean() -> None:
    returns = _two_asset_returns()
    estimator = build_return_estimator("historical_mean", {"trading_days": TRADING_DAYS})
    assert np.allclose(estimator.estimate(returns), returns.mean(axis=0) * TRADING_DAYS)


def test_covariance_estimators_are_symmetric_and_finite() -> None:
    returns = _two_asset_returns()
    sample = build_covariance_estimator("sample").estimate(returns)
    assert np.allclose(sample, sample_covariance(returns) * TRADING_DAYS)


def test_all_objectives_produce_finite_values() -> None:
    context = _context(_two_asset_returns())
    weights = np.array([0.6, 0.4])
    for identifier in objectives.list():
        assert np.isfinite(build_objective(identifier).value(weights, context))


def test_inverse_volatility_is_one_file_and_one_registration() -> None:
    """Acceptance: the inverse_volatility objective plugs in with no engine change."""
    returns = _two_asset_returns()
    result = _engine(returns, objective="inverse_volatility")

    # The unconstrained minimum of ||w - target||^2 over the simplex is the
    # inverse-volatility target itself, and A has the lower variance.
    context = _context(returns)
    inverse = 1.0 / np.sqrt(np.diag(context.covariance))
    target = inverse / inverse.sum()
    assert build_objective("inverse_volatility").value(target, context) == pytest.approx(0.0)
    assert result.weights["A"] == pytest.approx(target[0], abs=1e-4)
    assert result.weights["A"] > result.weights["B"]
    assert result.weights["A"] + result.weights["B"] == pytest.approx(1.0, abs=1e-6)


def test_lot_rounding_uses_whole_lots_and_reports_residual() -> None:
    result = round_to_lots(
        weights={"A": 0.5, "B": 0.5},
        prices={"A": 10_000.0, "B": 20_000.0},
        capital=10_000_000.0,
        lot_sizes={"A": 100, "B": 100},
    )
    assert result.lots == {"A": 5, "B": 2}
    assert result.shares == {"A": 500, "B": 200}
    assert sum(result.values.values()) <= 10_000_000.0
    assert result.residual_cash == 1_000_000


def test_lot_rounding_never_exceeds_the_target_value() -> None:
    result = round_to_lots(
        weights={"A": 0.25},
        prices={"A": 33_333.0},
        capital=1_000_000.0,
        lot_sizes={"A": 100},
    )
    assert result.values["A"] <= 250_000.0
    assert result.shares["A"] % 100 == 0


def test_lot_size_lookup_is_case_insensitive() -> None:
    assert lot_size_for("HOSE", DEFAULT_MARKET_RULES) == 100
    assert lot_size_for("upcom", DEFAULT_MARKET_RULES) == 100
    assert lot_size_for("unknown", DEFAULT_MARKET_RULES) == 100


def test_builtin_registries_are_populated() -> None:
    assert set(return_estimators.list()) == {"historical_mean"}
    assert set(covariance_estimators.list()) == {"sample"}
    assert {"min_variance", "max_sharpe", "equal_weight", "inverse_volatility"} == set(
        objectives.list()
    )
    assert set(constraints.list()) == {"max_weight", "cash_reserve", "max_sector_weight"}
    assert "scipy_slsqp" in solvers.list()


def test_unknown_ids_raise_key_error() -> None:
    with pytest.raises(KeyError):
        build_objective("does-not-exist")
    with pytest.raises(KeyError):
        build_constraint("does-not-exist")
    with pytest.raises(KeyError):
        build_return_estimator("does-not-exist")
    with pytest.raises(KeyError):
        build_covariance_estimator("does-not-exist")


def test_invalid_constraint_parameters_are_rejected() -> None:
    with pytest.raises(ValidationError):
        build_constraint("max_weight", {"max_weight": 0.0})


def test_a_new_objective_is_one_registration() -> None:
    """Acceptance: a new objective is one class plus one registration."""

    class _NoParams(BaseModel):
        pass

    @objectives.register(
        id="test_min_first_weight",
        name="Test min first weight",
        description="Test-only objective that pushes every weight onto the last asset.",
        parameter_schema=_NoParams,
    )
    class MinFirstWeight:
        id = "test_min_first_weight"

        def __init__(self, params: dict[str, object] | None = None) -> None:
            _NoParams(**(params or {}))

        def value(self, weights: np.ndarray, context: OptimizeContext) -> float:
            return float(weights[0])

        def gradient(
            self, weights: np.ndarray, context: OptimizeContext
        ) -> np.ndarray:
            gradient = np.zeros_like(weights)
            gradient[0] = 1.0
            return gradient

    result = _engine(_two_asset_returns(), objective="test_min_first_weight")
    assert result.weights["A"] < 1e-3
    assert result.weights["B"] > 0.99




def test_default_max_weight_uses_max_of_floor_and_slices() -> None:
    assert default_max_weight(0) == 0.25
    assert default_max_weight(1) == 1.0
    assert default_max_weight(2) == 0.75
    assert default_max_weight(4) == 0.375
    assert default_max_weight(6) == 0.25
    assert default_max_weight(10) == 0.25


def test_feasible_max_weight_raises_an_infeasible_cap() -> None:
    value, raised = feasible_max_weight(5, 0.3)
    assert value == 0.3
    assert not raised

    value, raised = feasible_max_weight(10, 0.05)
    assert value == pytest.approx(0.1)
    assert raised

    value, raised = feasible_max_weight(3, 0.2)
    assert value == pytest.approx(1.0 / 3.0)
    assert raised


def test_universe_size_warnings_cover_both_edges() -> None:
    assert universe_size_warnings(4) == [
        "Only 4 stock(s): the efficient frontier is not meaningful below 5."
    ]
    assert universe_size_warnings(21) == [
        "21 stocks is a lot: the sample covariance becomes unreliable above 20."
    ]
    assert universe_size_warnings(8) == []


def test_exceeds_hard_max_flags_more_than_thirty() -> None:
    assert not exceeds_hard_max(HARD_MAX_STOCKS)
    assert exceeds_hard_max(HARD_MAX_STOCKS + 1)
