"""Liquidity presets and the universe filter (``docs/V2_SPEC.md`` section 4)."""

from __future__ import annotations

from datetime import date

from data.v2.analytics.liquidity import (
    DEFAULT_PRESET_ID,
    LIQUIDITY_PRESETS,
    UniverseFilterSpec,
    filter_universe,
    get_preset,
    suggest_preset,
)
from data.v2.analytics.schemas import UniverseRow

_BN = 1_000_000_000.0


def _row(
    ticker: str,
    *,
    exchange: str = "HOSE",
    sector: str = "Banks",
    indexes: tuple[str, ...] = ("VN30", "VN100"),
    adtv: float | None = 20 * _BN,
    adv: float | None = 200_000.0,
    market_cap: float | None = 1_000 * _BN,
) -> UniverseRow:
    return UniverseRow(
        ticker=ticker,
        exchange=exchange,
        sector=sector,
        index_memberships=frozenset(indexes),
        adtv_median=adtv,
        adv_median=adv,
        market_cap=market_cap,
    )


def test_presets_are_config_with_the_spec_thresholds() -> None:
    by_id = {preset.id: preset for preset in LIQUIDITY_PRESETS}
    assert list(by_id) == ["small_retail", "standard_retail", "high_liquidity", "all_stocks"]
    assert DEFAULT_PRESET_ID == "standard_retail"
    assert (by_id["small_retail"].min_adtv, by_id["small_retail"].min_adv) == (3 * _BN, 100_000.0)
    assert (by_id["standard_retail"].min_adtv, by_id["standard_retail"].min_adv) == (
        10 * _BN,
        150_000.0,
    )
    assert (by_id["high_liquidity"].min_adtv, by_id["high_liquidity"].min_adv) == (
        30 * _BN,
        300_000.0,
    )
    assert by_id["all_stocks"].min_adtv is None
    assert by_id["all_stocks"].min_market_cap is None


def test_suggest_preset_matches_the_retail_size_bands() -> None:
    assert suggest_preset(0.5 * _BN).id == "small_retail"
    assert suggest_preset(1 * _BN).id == "standard_retail"
    assert suggest_preset(9.9 * _BN).id == "standard_retail"
    assert suggest_preset(10 * _BN).id == "high_liquidity"


def test_standard_preset_keeps_only_liquid_rows() -> None:
    result = filter_universe(
        [
            _row("LIQUID"),
            _row("THIN_VALUE", adtv=5 * _BN),
            _row("THIN_VOLUME", adv=100_000.0),
            _row("TOO_SMALL", market_cap=400 * _BN),
        ]
    )
    assert [row.ticker for row in result.kept] == ["LIQUID"]
    assert {row.ticker for row, _ in result.rejected} == {
        "THIN_VALUE",
        "THIN_VOLUME",
        "TOO_SMALL",
    }


def test_all_stocks_has_no_liquidity_floor() -> None:
    result = filter_universe(
        [_row("TINY", adtv=None, adv=None, market_cap=None)], preset_id="all_stocks"
    )
    assert [row.ticker for row in result.kept] == ["TINY"]


def test_missing_liquidity_is_rejected_under_a_threshold_preset() -> None:
    result = filter_universe([_row("NO_DATA", adtv=None)])
    assert result.kept == []
    assert result.rejected[0][1] == "no ADTV"


def test_sector_and_index_facets_are_anded() -> None:
    candidates = [
        _row("BANK_VN30", sector="Banks", indexes=("VN30", "VN100")),
        _row("BANK_NOINDEX", sector="Banks", indexes=()),
        _row("TECH_VN30", sector="Technology", indexes=("VN30", "VN100")),
    ]
    result = filter_universe(
        candidates,
        filters=UniverseFilterSpec(sectors=frozenset({"Banks"}), indexes=frozenset({"VN30"})),
    )
    assert [row.ticker for row in result.kept] == ["BANK_VN30"]


def test_index_facet_matches_any_selected_index() -> None:
    candidates = [
        _row("IN_VN30", indexes=("VN30", "VN100")),
        _row("IN_VN100_ONLY", indexes=("VN100",)),
        _row("NOT_INDEXED", indexes=()),
    ]
    result = filter_universe(candidates, filters=UniverseFilterSpec(indexes=frozenset({"VN100"})))
    assert {row.ticker for row in result.kept} == {"IN_VN30", "IN_VN100_ONLY"}


def test_exchange_facet_is_case_insensitive() -> None:
    candidates = [_row("HOSE_ONE", exchange="HOSE"), _row("HNX_ONE", exchange="HNX")]
    result = filter_universe(candidates, filters=UniverseFilterSpec(exchange="hose"))
    assert [row.ticker for row in result.kept] == ["HOSE_ONE"]


def test_filter_result_stamps_the_snapshot_date_and_preset() -> None:
    result = filter_universe([_row("X")], preset_id="high_liquidity", as_of=date(2026, 11, 20))
    assert result.as_of == date(2026, 11, 20)
    assert result.preset_id == "high_liquidity"
    assert get_preset("standard_retail").id == "standard_retail"
