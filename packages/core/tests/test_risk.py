"""Unit tests for the risk metrics, with hand-computed examples."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from core.registry import Registry
from core.risk import build_risk_metric, compute_risk, risk_metrics, sharpe_ratio
from core.risk.interfaces import RiskContext, RiskMetric

_BASE = date(2024, 1, 2)


def _dates(count: int) -> tuple[date, ...]:
    """Return ``count`` consecutive calendar dates starting at ``_BASE``."""
    return tuple(_BASE + timedelta(days=offset) for offset in range(count))


def _report(
    returns: Any,
    weights: dict[str, float],
    *,
    benchmark: Any = None,
    metric_ids: list[str] | None = None,
    params: dict[str, dict[str, Any]] | None = None,
    risk_free_rate: float = 0.0,
    trading_days: int = 252,
) -> Any:
    """Build a risk report from a returns matrix (one column per asset A, B, ...)."""
    matrix = np.asarray(returns, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    symbols = tuple(chr(ord("A") + index) for index in range(matrix.shape[1]))
    bench = np.zeros(matrix.shape[0]) if benchmark is None else np.asarray(benchmark)
    return compute_risk(
        symbols=symbols,
        dates=_dates(matrix.shape[0]),
        returns=matrix,
        benchmark_returns=bench,
        weights=weights,
        risk_free_rate=risk_free_rate,
        metric_ids=metric_ids,
        metric_params=params,
        trading_days=trading_days,
    )


# -- Sharpe ratio -------------------------------------------------------------


def test_higher_risk_free_rate_lowers_sharpe() -> None:
    low_rate = sharpe_ratio(mean_return=0.12, volatility=0.20, risk_free_rate=0.03)
    high_rate = sharpe_ratio(mean_return=0.12, volatility=0.20, risk_free_rate=0.06)
    assert high_rate < low_rate


def test_sharpe_matches_definition() -> None:
    value = sharpe_ratio(mean_return=0.12, volatility=0.20, risk_free_rate=0.03)
    assert value == pytest.approx((0.12 - 0.03) / 0.20)


def test_sharpe_rejects_non_positive_volatility() -> None:
    with pytest.raises(ValueError, match="volatility"):
        sharpe_ratio(mean_return=0.12, volatility=0.0, risk_free_rate=0.03)


# -- registry -----------------------------------------------------------------


def test_registry_is_populated() -> None:
    assert {
        "annualized_volatility",
        "max_drawdown",
        "beta",
        "historical_var",
        "correlation_matrix",
        "sharpe",
        "treynor",
        "jensens_alpha",
    } <= set(risk_metrics.list())


def test_a_new_metric_is_one_registration() -> None:
    local: Registry[RiskMetric] = Registry()

    @local.register(id="always_one", name="One", description="Always returns one.")
    class AlwaysOne:
        id = "always_one"

        def __init__(self, params: dict[str, Any] | None = None) -> None:
            self._params = params

        def compute(self, context: RiskContext) -> dict[str, Any]:
            return {"one": 1.0}

    metric = build_risk_metric("always_one", registry=local)
    context = RiskContext(
        symbols=("A",),
        dates=_dates(3),
        returns=np.zeros((3, 1), dtype=np.float64),
        weights=np.array([1.0]),
        benchmark_returns=np.zeros(3),
        risk_free_rate=0.0,
    )
    assert metric.id == "always_one"
    assert metric.compute(context) == {"one": 1.0}


# -- annualized volatility ----------------------------------------------------


def test_annualized_volatility_matches_definition() -> None:
    returns = np.array([0.01, -0.01, 0.01, -0.01])
    report = _report(returns, {"A": 1.0}, metric_ids=["annualized_volatility"])
    expected = float(np.std(returns, ddof=1) * np.sqrt(252))
    assert report.metrics["annualized_volatility"]["volatility"] == pytest.approx(expected)
    assert expected == pytest.approx(0.01 * np.sqrt(336.0))


# -- maximum drawdown ---------------------------------------------------------


def test_max_drawdown_and_series_match_hand_computation() -> None:
    returns = np.array([0.10, -0.20, 0.05])
    report = _report(returns, {"A": 1.0}, metric_ids=["max_drawdown"])
    drawdown = report.metrics["max_drawdown"]
    assert drawdown["max_drawdown"] == pytest.approx(0.20)
    assert drawdown["drawdown"] == pytest.approx([0.0, -0.20, -0.16])
    assert len(drawdown["dates"]) == len(drawdown["drawdown"]) == 3


# -- beta ---------------------------------------------------------------------


def test_beta_of_double_exposure_is_two() -> None:
    benchmark = np.array([0.01, 0.005, -0.005, 0.015])
    portfolio = 2.0 * benchmark
    report = _report(portfolio, {"A": 1.0}, benchmark=benchmark, metric_ids=["beta"])
    assert report.metrics["beta"]["beta"] == pytest.approx(2.0)


def test_beta_with_zero_variance_benchmark_raises() -> None:
    returns = np.array([0.01, -0.01, 0.02])
    with pytest.raises(ValueError, match="zero variance"):
        _report(returns, {"A": 1.0}, benchmark=np.zeros(3), metric_ids=["beta"])


# -- Sharpe ratio (metric) ----------------------------------------------------

#: Daily returns with mean 0.01 and a non-zero spread; trading_days=1 below so the
#: "annualized" values equal the daily ones and the arithmetic is easy to check.
_SHARPE_RETURNS = np.array([0.02, -0.01, 0.03, 0.00])


def test_sharpe_metric_matches_definition() -> None:
    # std(ddof=1) of the four returns is sqrt(1e-3 / 3) = 0.018257...
    report = _report(
        _SHARPE_RETURNS,
        {"A": 1.0},
        metric_ids=["sharpe"],
        risk_free_rate=0.0,
        trading_days=1,
    )
    sharpe = report.metrics["sharpe"]
    assert sharpe["mean_return"] == pytest.approx(0.01)
    assert sharpe["sharpe"] == pytest.approx(0.01 / 0.01825741858)


def test_sharpe_metric_uses_the_risk_free_rate() -> None:
    # When the mean return equals the risk-free rate the excess return is zero.
    report = _report(
        _SHARPE_RETURNS,
        {"A": 1.0},
        metric_ids=["sharpe"],
        risk_free_rate=0.01,
        trading_days=1,
    )
    sharpe = report.metrics["sharpe"]
    assert sharpe["risk_free_rate"] == pytest.approx(0.01)
    assert sharpe["sharpe"] == pytest.approx(0.0)


def test_sharpe_metric_is_none_for_a_flat_series() -> None:
    report = _report(
        np.array([0.01, 0.01, 0.01]),
        {"A": 1.0},
        metric_ids=["sharpe"],
        trading_days=1,
    )
    assert report.metrics["sharpe"]["sharpe"] is None


# -- Treynor ratio ------------------------------------------------------------

#: A portfolio that is exactly twice the benchmark has beta 2.
_TREYNOR_BENCHMARK = np.array([0.01, -0.005, 0.015, 0.00])
_TREYNOR_PORTFOLIO = 2.0 * _TREYNOR_BENCHMARK


def test_treynor_metric_matches_definition() -> None:
    # The benchmark's mean is 0.005, so the doubled portfolio's mean is 0.01 and
    # its beta is 2; Treynor = (0.01 - 0) / 2 = 0.005.
    report = _report(
        _TREYNOR_PORTFOLIO,
        {"A": 1.0},
        benchmark=_TREYNOR_BENCHMARK,
        metric_ids=["treynor"],
        risk_free_rate=0.0,
        trading_days=1,
    )
    treynor = report.metrics["treynor"]
    assert treynor["beta"] == pytest.approx(2.0)
    assert treynor["mean_return"] == pytest.approx(0.01)
    assert treynor["treynor"] == pytest.approx(0.01 / 2.0)


def test_treynor_metric_uses_the_risk_free_rate() -> None:
    report = _report(
        _TREYNOR_PORTFOLIO,
        {"A": 1.0},
        benchmark=_TREYNOR_BENCHMARK,
        metric_ids=["treynor"],
        risk_free_rate=0.01,
        trading_days=1,
    )
    assert report.metrics["treynor"]["treynor"] == pytest.approx(0.0)


# -- Jensen's alpha -----------------------------------------------------------


def test_jensens_alpha_is_zero_for_a_scaled_benchmark() -> None:
    # A portfolio that is exactly twice the benchmark earns its CAPM expectation.
    report = _report(
        _TREYNOR_PORTFOLIO,
        {"A": 1.0},
        benchmark=_TREYNOR_BENCHMARK,
        metric_ids=["jensens_alpha"],
        risk_free_rate=0.0,
        trading_days=1,
    )
    alpha = report.metrics["jensens_alpha"]
    assert alpha["beta"] == pytest.approx(2.0)
    assert alpha["benchmark_return"] == pytest.approx(0.005)
    assert alpha["alpha"] == pytest.approx(0.0)


def test_jensens_alpha_detects_a_constant_excess_return() -> None:
    # Adding a constant 0.001/day keeps beta at 2 but lifts the mean return to
    # 0.011, so alpha = 0.011 - (0 + 2*0.005) = 0.001.
    portfolio = _TREYNOR_PORTFOLIO + 0.001
    report = _report(
        portfolio,
        {"A": 1.0},
        benchmark=_TREYNOR_BENCHMARK,
        metric_ids=["jensens_alpha"],
        risk_free_rate=0.0,
        trading_days=1,
    )
    assert report.metrics["jensens_alpha"]["alpha"] == pytest.approx(0.001)


# -- historical performance ---------------------------------------------------


def test_performance_growth_series_and_stats() -> None:
    returns = np.array([0.10, -0.20, 0.05])
    report = _report(returns, {"A": 1.0}, metric_ids=["annualized_volatility"])
    performance = report.performance
    assert list(performance.growth) == pytest.approx([110.0, 88.0, 92.4])
    assert performance.total_return == pytest.approx(0.924 - 1.0)
    assert performance.max_drawdown == pytest.approx(0.20)
    assert len(performance.dates) == 3


def test_performance_annualized_return_is_geometric() -> None:
    returns = np.array([0.10, -0.20, 0.05])
    report = _report(
        returns, {"A": 1.0}, metric_ids=["annualized_volatility"], trading_days=1
    )
    # growth ends at 92.4, so annualized over one period per row is 0.924**(1/3)-1.
    expected = 0.924 ** (1.0 / 3.0) - 1.0
    assert report.performance.annualized_return == pytest.approx(expected)


def test_performance_skips_missing_returns() -> None:
    returns = np.array([0.10, np.nan, -0.20])
    report = _report(returns, {"A": 1.0}, metric_ids=["annualized_volatility"])
    performance = report.performance
    assert list(performance.growth) == pytest.approx([110.0, 88.0])
    assert len(performance.dates) == 2


# -- benchmark analysis -------------------------------------------------------


def test_benchmark_risk_has_beta_one_and_zero_alpha() -> None:
    from core.risk import compute_benchmark_risk

    benchmark = np.array([0.01, -0.005, 0.015, 0.00])
    report = compute_benchmark_risk(
        dates=_dates(benchmark.size),
        benchmark_returns=benchmark,
        risk_free_rate=0.0,
        trading_days=1,
    )
    assert report.metrics["beta"]["beta"] == pytest.approx(1.0)
    assert report.metrics["jensens_alpha"]["alpha"] == pytest.approx(0.0)


# -- historical VaR -----------------------------------------------------------


def test_historical_var_matches_hand_computation() -> None:
    returns = np.array([-0.10, -0.05, 0.00, 0.05, 0.10])
    report = _report(
        returns,
        {"A": 1.0},
        metric_ids=["historical_var"],
        params={"historical_var": {"confidence": 0.6}},
    )
    assert report.metrics["historical_var"]["value_at_risk"] == pytest.approx(0.02)
    assert report.metrics["historical_var"]["confidence"] == pytest.approx(0.6)


def test_var_defaults_to_95_percent() -> None:
    returns = np.array([-0.10, -0.05, 0.00, 0.05, 0.10])
    report = _report(returns, {"A": 1.0}, metric_ids=["historical_var"])
    assert report.metrics["historical_var"]["confidence"] == pytest.approx(0.95)


def test_invalid_confidence_is_rejected() -> None:
    returns = np.array([0.01, -0.01])
    with pytest.raises(ValidationError, match=r"less than"):
        _report(
            returns,
            {"A": 1.0},
            metric_ids=["historical_var"],
            params={"historical_var": {"confidence": 1.5}},
        )


# -- orthogonal assets helper -------------------------------------------------


def _orthogonal_assets() -> np.ndarray:
    """Two zero-mean, uncorrelated daily return columns of equal variance."""
    asset_a = np.array([0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01])
    asset_b = np.array([0.01, 0.01, -0.01, -0.01, 0.01, 0.01, -0.01, -0.01])
    return np.column_stack([asset_a, asset_b])


# -- correlation matrix -------------------------------------------------------


def test_correlation_matrix_is_identity_for_orthogonal_assets() -> None:
    report = _report(
        _orthogonal_assets(), {"A": 0.5, "B": 0.5}, metric_ids=["correlation_matrix"]
    )
    matrix = report.metrics["correlation_matrix"]["matrix"]
    assert matrix[0][0] == pytest.approx(1.0)
    assert matrix[1][1] == pytest.approx(1.0)
    assert matrix[0][1] == pytest.approx(0.0, abs=1e-9)


def test_correlation_matrix_detects_perfect_correlation() -> None:
    asset_a = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    returns = np.column_stack([asset_a, 2.0 * asset_a])
    report = _report(returns, {"A": 0.5, "B": 0.5}, metric_ids=["correlation_matrix"])
    matrix = report.metrics["correlation_matrix"]["matrix"]
    assert matrix[0][1] == pytest.approx(1.0)


# -- engine -------------------------------------------------------------------


def test_compute_risk_returns_every_registered_metric() -> None:
    returns = _orthogonal_assets()
    report = _report(returns, {"A": 0.6, "B": 0.4}, benchmark=returns[:, 0])
    assert set(report.metrics) == set(risk_metrics.list())
    assert report.symbols == ("A", "B")


def test_unknown_metric_raises_key_error() -> None:
    with pytest.raises(KeyError):
        _report(np.array([0.01, -0.01]), {"A": 1.0}, metric_ids=["does-not-exist"])


def test_zero_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        _report(np.array([0.01, -0.01]), {})


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        _report(np.array([0.01, -0.01]), {"A": -0.5})
