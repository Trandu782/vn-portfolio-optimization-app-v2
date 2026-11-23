"""Ratio-set configuration and pure statistics for V2b fundamentals.

The SSI ``finance-indicator`` feed publishes a superset of the spec's trimmed ratio
set (``docs/V2_SPEC.md`` section 6). This module is the single source of truth for:

* the four peer groups (general, banks, securities, insurance) and their ratio sets;
* the ICB level-2 sectors that belong to each group;
* direction-aware colouring metadata (higher-better / lower-better / neutral);
* the valuation multiples where a non-positive value is not meaningful ("n/m");
* pure winsorized-mean, percentile and percentile-rank helpers shared by the
  precompute sector statistics and the read-side fundamentals service.

Units: ratios keep the adapter normalization, so every percentage is a 0-100
number (ROE ``17.3`` means 17.3%) and P/E, P/B are dimensionless multiples.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import fmean
from typing import Literal

RatioGroup = Literal["general", "banks", "securities", "insurance"]

#: Profitability, solvency, liquidity and valuation ratios for a general company.
GENERAL_RATIOS: tuple[str, ...] = (
    "grossProfitMargin",
    "netProfitMargin",
    "roe",
    "roa",
    "roic",
    "debtEquity",
    "debtAsset",
    "currentRatio",
    "quickRatio",
    "pe",
    "pb",
    "dividendYield",
)

#: Bank set: NPL replaces the margins/liquidity SSI reports as 0 for banks.
BANK_RATIOS: tuple[str, ...] = ("roe", "roa", "npl", "pe", "pb")

#: Securities-company set (SSI publishes no NPL, NIM, CAR, LDR or CIR for them).
SECURITIES_RATIOS: tuple[str, ...] = ("roe", "roa", "pe", "pb")

#: Safe default for financial sectors that fit neither the general, bank nor
#: securities template (e.g. insurers: no cost-of-goods margin, no working-capital
#: liquidity, and SSI publishes no combined ratio). ROE, ROA, P/E and P/B are the
#: four multiples that are meaningful for any financial company.
INSURANCE_RATIOS: tuple[str, ...] = ("roe", "roa", "pe", "pb")

#: The ratio set for each peer group.
RATIO_SETS: dict[RatioGroup, tuple[str, ...]] = {
    "general": GENERAL_RATIOS,
    "banks": BANK_RATIOS,
    "securities": SECURITIES_RATIOS,
    "insurance": INSURANCE_RATIOS,
}

#: ICB level-2 sectors that are banks (compared only with banks).
BANK_SECTORS: frozenset[str] = frozenset({"Banks"})
#: ICB level-2 sectors that are securities firms (compared only with securities).
SECURITIES_SECTORS: frozenset[str] = frozenset({"Financial Services"})
#: ICB level-2 sectors that use the safe-default financial ratio set.
INSURANCE_SECTORS: frozenset[str] = frozenset({"Insurance"})

#: Ratios where a higher value is better.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {
        "grossProfitMargin",
        "netProfitMargin",
        "roe",
        "roa",
        "roic",
        "currentRatio",
        "quickRatio",
        "dividendYield",
    }
)
#: Ratios where a lower value is better.
LOWER_IS_BETTER: frozenset[str] = frozenset({"debtEquity", "debtAsset", "npl"})
#: Valuation multiples: neutral (neither higher nor lower is inherently better).
NEUTRAL: frozenset[str] = frozenset({"pe", "pb"})

#: Ratios the adapter normalizes to a 0-100 percentage (the rest are multiples).
PERCENTAGE_RATIOS: frozenset[str] = frozenset(
    {"roe", "roa", "roic", "grossProfitMargin", "netProfitMargin", "dividendYield", "npl"}
)

#: Ratios where a non-positive value is not meaningful: excluded from the peer
#: statistics and shown "n/m". A loss-maker has a negative or undefined P/E, not a
#: cheap one.
NON_POSITIVE_IS_NM: frozenset[str] = frozenset({"pe", "pb", "dilutedPe"})

#: Display category of each ratio, grouping the scorecard cards. ``asset_quality``
#: exists only in the bank set (NPL); the general set has no such ratio.
RatioCategory = Literal["profitability", "solvency", "liquidity", "valuation", "asset_quality"]

#: Category display names, published to the UI so it never hardcodes a label.
RATIO_CATEGORY_LABELS: dict[RatioCategory, str] = {
    "profitability": "Profitability",
    "solvency": "Solvency",
    "liquidity": "Liquidity",
    "valuation": "Valuation",
    "asset_quality": "Asset quality",
}

#: Short human-readable name of each ratio key.
RATIO_LABELS: dict[str, str] = {
    "grossProfitMargin": "Gross margin",
    "netProfitMargin": "Net margin",
    "roe": "ROE",
    "roa": "ROA",
    "roic": "ROIC",
    "debtEquity": "Debt/equity",
    "debtAsset": "Debt/assets",
    "currentRatio": "Current ratio",
    "quickRatio": "Quick ratio",
    "pe": "P/E",
    "pb": "P/B",
    "dividendYield": "Dividend yield",
    "npl": "NPL ratio",
}

#: Category of each ratio key. Every ratio in every group set has an entry; a key
#: missing here would be a configuration bug, so :func:`ratio_category` raises.
RATIO_CATEGORIES: dict[str, RatioCategory] = {
    "grossProfitMargin": "profitability",
    "netProfitMargin": "profitability",
    "roe": "profitability",
    "roa": "profitability",
    "roic": "profitability",
    "debtEquity": "solvency",
    "debtAsset": "solvency",
    "currentRatio": "liquidity",
    "quickRatio": "liquidity",
    "pe": "valuation",
    "pb": "valuation",
    "dividendYield": "valuation",
    "npl": "asset_quality",
}

RatioDirection = Literal["higher", "lower", "neutral"]


def ratio_group_for(sector_name: str | None) -> RatioGroup:
    """Return the peer group implied by an ICB level-2 sector name.

    ``Banks`` uses the bank set, ``Financial Services`` (the securities
    supersector) uses the securities set and ``Insurance`` uses the safe-default
    financial set (ROE, ROA, P/E, P/B): an insurer has no cost-of-goods margin, no
    working-capital liquidity and no SSI-published combined ratio, so the full
    general set would be mostly null. Every other sector, including real estate,
    uses the general set.
    """
    if not sector_name:
        return "general"
    normalized = sector_name.strip()
    if normalized in BANK_SECTORS:
        return "banks"
    if normalized in SECURITIES_SECTORS:
        return "securities"
    if normalized in INSURANCE_SECTORS:
        return "insurance"
    return "general"


def ratio_set_for(sector_name: str | None) -> tuple[str, ...]:
    """Return the ratio keys relevant to a ticker's sector group."""
    return RATIO_SETS[ratio_group_for(sector_name)]


def trim_ratios(
    ratios: dict[str, float | None], sector_name: str | None
) -> dict[str, float | None]:
    """Return only the ratios that matter for ``sector_name``'s group.

    Missing keys become ``None`` so a consumer can always read every group ratio.
    """
    return {key: ratios.get(key) for key in ratio_set_for(sector_name)}


def direction_for(ratio: str) -> RatioDirection:
    """Return whether higher, lower or neither direction is "better" for ``ratio``."""
    if ratio in HIGHER_IS_BETTER:
        return "higher"
    if ratio in LOWER_IS_BETTER:
        return "lower"
    return "neutral"


def ratio_label(ratio: str) -> str:
    """Return the short display name of ``ratio`` (falls back to the raw key)."""
    return RATIO_LABELS.get(ratio, ratio)


def ratio_category(ratio: str) -> RatioCategory:
    """Return the display category of ``ratio``.

    Raises:
        KeyError: When ``ratio`` has no category, which means the ratio sets and the
            metadata tables disagree (a configuration bug, not user input).
    """
    return RATIO_CATEGORIES[ratio]


def category_label(category: RatioCategory) -> str:
    """Return the display name of a ratio category."""
    return RATIO_CATEGORY_LABELS[category]


def is_percentage_ratio(ratio: str) -> bool:
    """Return True when ``ratio`` is a 0-100 percentage (else it is a multiple)."""
    return ratio in PERCENTAGE_RATIOS


def include_in_stats(ratio: str, value: float | None) -> bool:
    """Return whether ``value`` participates in the peer statistics for ``ratio``.

    A missing value is always excluded. For P/E and P/B (and diluted P/E) a
    non-positive value is not meaningful and is excluded too ("n/m"); every other
    ratio keeps negative values because they are meaningful (a loss-making company
    has a negative ROE).
    """
    if value is None:
        return False
    if ratio in NON_POSITIVE_IS_NM:
        return value > 0.0
    return True


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Return the ``pct``-th percentile of an already-sorted, non-empty sequence.

    Uses the nearest-rank method (rank = ceil(pct/100 * n), 1-based), which is simple
    to reproduce by hand and stable for small peer sets.
    """
    if not sorted_values:
        raise ValueError("percentile of an empty sequence")
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[rank - 1]


def winsorized_mean(
    values: Sequence[float], *, lower: float = 5.0, upper: float = 95.0
) -> float | None:
    """Return the mean after clipping to the ``lower``/``upper`` percentiles.

    The spec's "winsorized mean (5th/95th percentile)" is a mean with extreme values
    pulled in to the 5th and 95th percentiles, so one outlier cannot move the peer
    average. Returns ``None`` for an empty sequence.
    """
    if not values:
        return None
    ordered = sorted(values)
    low = percentile(ordered, lower)
    high = percentile(ordered, upper)
    return fmean(min(max(value, low), high) for value in ordered)


def percentile_rank(values: Sequence[float], value: float) -> float:
    """Return ``value``'s percentile rank (0-100) among ``values``.

    The rank is the fraction of peers strictly below ``value`` over ``n - 1``, so the
    best of many peers is 100 and the worst is 0. A single peer is 100.
    """
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        return 100.0
    below = sum(1 for peer in values if peer < value)
    return below / (n - 1) * 100.0


__all__ = [
    "BANK_RATIOS",
    "BANK_SECTORS",
    "GENERAL_RATIOS",
    "HIGHER_IS_BETTER",
    "INSURANCE_RATIOS",
    "INSURANCE_SECTORS",
    "LOWER_IS_BETTER",
    "NEUTRAL",
    "NON_POSITIVE_IS_NM",
    "PERCENTAGE_RATIOS",
    "RATIO_CATEGORIES",
    "RATIO_CATEGORY_LABELS",
    "RATIO_LABELS",
    "RATIO_SETS",
    "SECURITIES_RATIOS",
    "SECURITIES_SECTORS",
    "RatioCategory",
    "RatioDirection",
    "RatioGroup",
    "category_label",
    "direction_for",
    "include_in_stats",
    "is_percentage_ratio",
    "percentile",
    "percentile_rank",
    "ratio_category",
    "ratio_group_for",
    "ratio_label",
    "ratio_set_for",
    "trim_ratios",
    "winsorized_mean",
]
