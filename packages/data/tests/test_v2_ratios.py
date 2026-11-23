"""Ratio-set selection, group mapping, "n/m" rules and pure statistics."""

from __future__ import annotations

import pytest

from data.v2.ratios import (
    BANK_RATIOS,
    GENERAL_RATIOS,
    INSURANCE_RATIOS,
    RATIO_SETS,
    SECURITIES_RATIOS,
    direction_for,
    include_in_stats,
    percentile,
    percentile_rank,
    ratio_group_for,
    ratio_set_for,
    trim_ratios,
    winsorized_mean,
)


def test_group_mapping_by_icb_sector() -> None:
    assert ratio_group_for("Banks") == "banks"
    assert ratio_group_for("Financial Services") == "securities"
    assert ratio_group_for("Insurance") == "insurance"
    assert ratio_group_for("Real Estate") == "general"
    assert ratio_group_for("Oil & Gas") == "general"
    assert ratio_group_for(None) == "general"
    assert ratio_group_for("  Banks  ") == "banks"


def test_ratio_sets_match_the_spec() -> None:
    assert RATIO_SETS["banks"] == ("roe", "roa", "npl", "pe", "pb")
    assert RATIO_SETS["securities"] == ("roe", "roa", "pe", "pb")
    assert RATIO_SETS["insurance"] == ("roe", "roa", "pe", "pb")
    assert set(GENERAL_RATIOS) == {
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
    }
    assert "npl" not in GENERAL_RATIOS
    assert "npl" not in SECURITIES_RATIOS
    assert RATIO_SETS["banks"] == BANK_RATIOS
    assert RATIO_SETS["insurance"] == INSURANCE_RATIOS


def test_ratio_set_for_uses_the_group() -> None:
    assert ratio_set_for("Banks") == BANK_RATIOS
    assert ratio_set_for("Insurance") == INSURANCE_RATIOS
    assert ratio_set_for("Technology") == GENERAL_RATIOS


def test_trim_ratios_keeps_only_group_keys_and_fills_missing_with_none() -> None:
    raw = {"roe": 15.0, "npl": 1.2, "grossProfitMargin": 40.0, "currentRatio": 1.5}
    banks = trim_ratios(raw, "Banks")
    assert banks == {"roe": 15.0, "roa": None, "npl": 1.2, "pe": None, "pb": None}
    assert "grossProfitMargin" not in banks
    general = trim_ratios(raw, "Technology")
    assert general["grossProfitMargin"] == 40.0
    assert "npl" not in general  # the general set has no npl key at all
    insurance = trim_ratios(raw, "Insurance")
    assert insurance == {"roe": 15.0, "roa": None, "pe": None, "pb": None}
    assert "grossProfitMargin" not in insurance  # the safe default keeps four ratios


def test_direction_is_direction_aware() -> None:
    assert direction_for("roe") == "higher"
    assert direction_for("debtEquity") == "lower"
    assert direction_for("npl") == "lower"
    assert direction_for("pe") == "neutral"
    assert direction_for("pb") == "neutral"


def test_ratio_metadata_covers_every_group_ratio() -> None:
    from data.v2.ratios import (
        HIGHER_IS_BETTER,
        LOWER_IS_BETTER,
        NEUTRAL,
        RATIO_CATEGORIES,
        category_label,
        is_percentage_ratio,
        ratio_category,
        ratio_label,
    )

    # Every ratio in every set has a label, a category and a known direction.
    for ratios in RATIO_SETS.values():
        for ratio in ratios:
            assert ratio_label(ratio)
            assert ratio in RATIO_CATEGORIES
            assert ratio in HIGHER_IS_BETTER | LOWER_IS_BETTER | NEUTRAL
            assert isinstance(is_percentage_ratio(ratio), bool)

    assert ratio_label("roe") == "ROE"
    assert ratio_label("debtEquity") == "Debt/equity"
    assert ratio_category("roe") == "profitability"
    assert ratio_category("debtEquity") == "solvency"
    assert ratio_category("currentRatio") == "liquidity"
    assert ratio_category("pe") == "valuation"
    assert ratio_category("npl") == "asset_quality"
    assert category_label("asset_quality") == "Asset quality"
    assert is_percentage_ratio("roe") is True
    assert is_percentage_ratio("pe") is False


def test_include_in_stats_excludes_missing_and_non_positive_valuation() -> None:
    assert include_in_stats("roe", None) is False
    assert include_in_stats("roe", -5.0) is True  # a negative ROE is meaningful
    assert include_in_stats("pe", None) is False
    assert include_in_stats("pe", 0.0) is False
    assert include_in_stats("pe", -3.0) is False
    assert include_in_stats("pe", 12.0) is True
    assert include_in_stats("pb", -1.0) is False
    assert include_in_stats("dividendYield", 0.0) is True  # a 0 yield is real


def test_percentile_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 5.0
    assert percentile(values, 50) == 3.0
    assert percentile(values, 20) == 1.0
    assert percentile(values, 99) == 5.0
    with pytest.raises(ValueError):
        percentile([], 5)


def test_winsorized_mean_clips_extremes() -> None:
    base = [float(i) for i in range(1, 20)]  # 1..19
    with_outlier = [*base, 1000.0]
    # p5 = sorted[0] = 1, p95 = sorted[18] = 19, so 1000 clips to 19.
    assert winsorized_mean(with_outlier) == pytest.approx(10.45)
    assert winsorized_mean([]) is None


def test_percentile_rank_bounds() -> None:
    assert percentile_rank([10.0, 20.0, 30.0], 10.0) == pytest.approx(0.0)
    assert percentile_rank([10.0, 20.0, 30.0], 20.0) == pytest.approx(50.0)
    assert percentile_rank([10.0, 20.0, 30.0], 30.0) == pytest.approx(100.0)
    assert percentile_rank([5.0], 5.0) == 100.0
    assert percentile_rank([], 5.0) == 0.0
