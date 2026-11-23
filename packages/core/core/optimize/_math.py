"""Numeric helpers shared by the return and covariance estimators.

This module is numpy-only. Missing observations are ``NaN``; every helper is
deterministic and never draws random numbers, so optimizations are reproducible.
Missing observations are dropped per column (and per pair for covariance) rather
than imputed with a fabricated return.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

type Matrix = NDArray[np.float64]
type Vector = NDArray[np.float64]


def column_mean(returns: Matrix) -> Vector:
    """Return the mean of each column, ignoring ``NaN`` (0 for an empty column)."""
    n_columns = returns.shape[1]
    if returns.size == 0:
        return np.zeros(n_columns, dtype=np.float64)
    finite = np.isfinite(returns)
    counts = finite.sum(axis=0).astype(np.float64)
    safe_counts = np.where(counts > 0.0, counts, 1.0)
    totals = np.where(finite, returns, 0.0).sum(axis=0)
    means = totals / safe_counts
    return np.where(counts > 0.0, means, 0.0)


def sample_covariance(returns: Matrix) -> Matrix:
    """Return the pairwise-complete sample covariance (``ddof=1``), unannualized.

    Each pair uses only the rows where both assets have a return, so a gap in one
    symbol does not fabricate a return for another.
    """
    n_columns = returns.shape[1]
    covariance = np.zeros((n_columns, n_columns), dtype=np.float64)
    finite = np.isfinite(returns)
    for i in range(n_columns):
        for j in range(i, n_columns):
            mask = finite[:, i] & finite[:, j]
            if int(mask.sum()) <= 1:
                value = 0.0
            else:
                value = float(np.cov(returns[mask, i], returns[mask, j], ddof=1)[0, 1])
            covariance[i, j] = value
            covariance[j, i] = value
    return covariance

