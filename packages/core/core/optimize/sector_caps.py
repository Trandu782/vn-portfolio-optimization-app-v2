"""Sector grouping helpers shared by the sector constraint, frontier and cloud.

A sector cap limits the total weight invested in each sector. The same grouping
and feasibility logic is used by the registered ``max_sector_weight`` constraint
(the single-portfolio path) and by the efficient-frontier / random-cloud code, so
a cap is enforced identically everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

#: Numerical slack tolerated when checking a sector cap.
FEASIBILITY_TOLERANCE = 1e-9

#: Sector label used for a ticker with no stored ICB level-2 sector.
UNKNOWN_SECTOR = "Unknown"


def group_indices_by_sector(
    symbols: Sequence[str], sectors: Mapping[str, str]
) -> dict[str, tuple[int, ...]]:
    """Return the column indices of ``symbols`` grouped by sector label."""
    groups: dict[str, list[int]] = {}
    for index, symbol in enumerate(symbols):
        label = sectors.get(symbol.strip().upper()) or UNKNOWN_SECTOR
        groups.setdefault(label, []).append(index)
    return {label: tuple(indices) for label, indices in groups.items()}


def sector_headroom(
    weights: NDArray[np.float64],
    groups: Mapping[str, Sequence[int]],
    max_sector_weight: float,
) -> NDArray[np.float64]:
    """Return ``max_sector_weight - sum(weights in sector)`` per sector."""
    return np.array(
        [
            max_sector_weight - float(np.sum(weights[list(indices)]))
            for indices in groups.values()
        ],
        dtype=np.float64,
    )


def violates_sector_cap(
    weights: NDArray[np.float64],
    groups: Mapping[str, Sequence[int]],
    max_sector_weight: float,
) -> bool:
    """Return ``True`` when any sector exceeds the cap (within tolerance)."""
    headroom = sector_headroom(weights, groups, max_sector_weight)
    return bool((headroom < -FEASIBILITY_TOLERANCE).any())


def sector_cap_error(
    groups: Mapping[str, Sequence[int]],
    max_weight: float,
    max_sector_weight: float,
) -> str | None:
    """Return a clear message when the sector cap cannot be fully invested.

    The most a sector can hold is ``min(cap, size * max_weight)``; the portfolio is
    feasible only when those maxima add up to at least 100%. Returns ``None`` when
    the caps are feasible.
    """
    if max_sector_weight <= 0.0:
        return "the maximum sector weight must be positive"
    capacity = sum(
        min(max_sector_weight, len(indices) * max_weight) for indices in groups.values()
    )
    if capacity < 1.0 - 1e-6:
        return (
            f"a maximum sector weight of {max_sector_weight:.0%} across the selected "
            f"sectors (with a {max_weight:.0%} per-stock cap) cannot reach 100%; "
            "raise the sector or per-stock cap"
        )
    return None


__all__ = [
    "FEASIBILITY_TOLERANCE",
    "UNKNOWN_SECTOR",
    "group_indices_by_sector",
    "sector_cap_error",
    "sector_headroom",
    "violates_sector_cap",
]
