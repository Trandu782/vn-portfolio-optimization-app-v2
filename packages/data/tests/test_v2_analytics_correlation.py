"""Cross-group correlation matrix and the independent pandas cross-check.

The cross-check builds three real ICB level-2 sectors (Banks, Real Estate, Technology),
each an equal-weight basket of four stocks from a seeded synthetic factor model, then
compares the engine's group-return correlation matrix with an independent
``pandas.DataFrame.corr()`` computation.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from data.v2.analytics.correlation import correlation_matrix

_SECTORS = {
    "Banks": ["VCB", "BID", "CTG", "MBB"],
    "Real Estate": ["VHM", "VIC", "NLG", "KDH"],
    "Technology": ["FPT", "CMG", "VGI", "ITD"],
}


def _weekdays(count: int, start: date = date(2024, 1, 2)) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _sector_frame() -> tuple[list[date], pd.DataFrame]:
    """Return the dates and a days-by-sectors equal-weight return frame."""
    rng = np.random.default_rng(20261120)
    days = _weekdays(120)
    factor = rng.normal(0.0, 1.0, size=len(days))
    columns: list[np.ndarray] = []
    labels: list[str] = []
    sector_of: list[str] = []
    for sector_index, (sector, tickers) in enumerate(_SECTORS.items()):
        for ticker in tickers:
            loading = 0.2 + 0.2 * sector_index
            noise = rng.normal(0.0, 1.0, size=len(days))
            columns.append(0.0004 + 0.01 * (loading * factor + 0.7 * noise))
            labels.append(f"{sector}:{ticker}")
            sector_of.append(sector)
    stocks = pd.DataFrame(np.column_stack(columns), index=days, columns=labels)
    return days, stocks.T.groupby(sector_of).mean().T


def _series(days: list[date], frame: pd.DataFrame) -> dict[str, dict[date, float]]:
    return {
        sector: {day: float(frame.at[day, sector]) for day in days}
        for sector in frame.columns
    }


def test_correlation_matches_an_independent_pandas_computation_in_three_sectors() -> None:
    days, frame = _sector_frame()
    result = correlation_matrix(_series(days, frame))
    expected = frame.corr().loc[result.labels, result.labels]
    assert np.allclose(np.asarray(result.matrix), expected.to_numpy(), atol=1e-12)


def test_matrix_is_symmetric_with_a_unit_diagonal() -> None:
    days, frame = _sector_frame()
    result = correlation_matrix(_series(days, frame))
    matrix = np.asarray(result.matrix)
    assert np.allclose(matrix, matrix.T, atol=1e-12)
    assert np.allclose(np.diag(matrix), 1.0, atol=1e-12)


def test_average_pairwise_correlation_matches_the_upper_triangle() -> None:
    days, frame = _sector_frame()
    result = correlation_matrix(_series(days, frame))
    matrix = np.asarray(result.matrix)
    upper = [matrix[i, j] for i in range(matrix.shape[0]) for j in range(i + 1, matrix.shape[0])]
    assert abs(result.average_pairwise_correlation - float(np.mean(upper))) < 1e-12


def test_clustered_order_is_a_permutation_of_the_labels() -> None:
    days, frame = _sector_frame()
    result = correlation_matrix(_series(days, frame))
    assert sorted(result.ordered_labels) == sorted(result.labels)


def test_a_single_group_trivially_has_a_unit_diagonal() -> None:
    result = correlation_matrix({"Banks": {date(2024, 1, 2): 0.01}})
    assert result.matrix == [[1.0]]
    assert result.average_pairwise_correlation is None


def test_an_empty_mapping_returns_an_empty_result() -> None:
    result = correlation_matrix({})
    assert result.labels == []
    assert result.matrix == []
    assert result.average_pairwise_correlation is None

def test_beta_r2_and_correlation_match_pandas_in_three_sectors() -> None:
    from data.v2.analytics.metrics import benchmark_metrics

    days, frame = _sector_frame()
    benchmark = frame.mean(axis=1)
    series = _series(days, frame)
    bench = {day: float(benchmark.at[day]) for day in days}
    for sector in frame.columns:
        metrics = benchmark_metrics(
            sector, series[sector], bench, benchmark="VNINDEX", constituent_count=4
        )
        expected_beta = float(frame[sector].cov(benchmark) / benchmark.var(ddof=1))
        expected_corr = float(frame[sector].corr(benchmark))
        assert metrics.beta is not None and abs(metrics.beta - expected_beta) < 1e-10
        assert metrics.correlation is not None and abs(metrics.correlation - expected_corr) < 1e-10
        assert metrics.r_squared is not None and abs(metrics.r_squared - expected_corr**2) < 1e-10
