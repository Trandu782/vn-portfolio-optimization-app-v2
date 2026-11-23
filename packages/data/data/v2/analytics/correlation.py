"""Cross-group correlation matrix, hierarchical order and average correlation.

The matrix is the pairwise Pearson correlation of the group index daily simple returns,
computed with pairwise-complete observations (a day missing one group is skipped for
that pair). It is symmetric with a unit diagonal. The clustering display order comes
from an average-linkage hierarchy on the ``1 - correlation`` distance.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from core.risk._math import correlation_from_covariance, sample_covariance
from data.v2.analytics.schemas import CorrelationResult


def _aligned_matrix(
    series: Mapping[str, Mapping[date, float]],
) -> tuple[list[str], np.ndarray]:
    """Return the labels and a dates-by-groups matrix with ``NaN`` for a gap."""
    labels = list(series)
    dates = sorted({day for values in series.values() for day in values})
    matrix = np.full((len(dates), len(labels)), np.nan, dtype=np.float64)
    for column, label in enumerate(labels):
        values = series[label]
        for row, day in enumerate(dates):
            value = values.get(day)
            if value is not None:
                matrix[row, column] = value
    return labels, matrix


def _average_pairwise(correlation: np.ndarray) -> float | None:
    """Return the mean of the off-diagonal upper triangle (``None`` when < 2 groups)."""
    size = correlation.shape[0]
    if size < 2:
        return None
    values = [
        float(correlation[i, j]) for i in range(size) for j in range(i + 1, size)
    ]
    return float(np.mean(values)) if values else None


def _clustered_order(correlation: np.ndarray) -> list[int]:
    """Return the hierarchical-clustering leaf order for the correlation matrix."""
    size = correlation.shape[0]
    if size <= 2:
        return list(range(size))
    distance = np.clip(1.0 - correlation, 0.0, 2.0)
    np.fill_diagonal(distance, 0.0)
    tree = linkage(squareform(distance, checks=False), method="average")
    return [int(index) for index in leaves_list(tree)]


def correlation_matrix(
    series: Mapping[str, Mapping[date, float]],
) -> CorrelationResult:
    """Return the cross-group Pearson correlation matrix and its cluster order."""
    labels = list(series)
    if len(labels) < 2:
        return CorrelationResult(
            labels=labels,
            matrix=[[1.0]] if labels else [],
            ordered_labels=labels,
            average_pairwise_correlation=None,
        )
    _, matrix = _aligned_matrix(series)
    correlation = correlation_from_covariance(sample_covariance(matrix))
    order = _clustered_order(correlation)
    return CorrelationResult(
        labels=labels,
        matrix=[[float(value) for value in row] for row in correlation],
        ordered_labels=[labels[index] for index in order],
        average_pairwise_correlation=_average_pairwise(correlation),
    )


__all__ = ["correlation_matrix"]
