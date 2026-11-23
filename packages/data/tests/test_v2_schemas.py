"""V2 schemas validate their fields and are frozen."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
)


def _bar() -> AdjustedOHLCV:
    return AdjustedOHLCV(
        date=date(2024, 1, 2),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=1000,
        matched_volume=None,
        value=1500.0,
        source="vci",
    )


def test_adjusted_ohlcv_allows_missing_matched_volume() -> None:
    bar = _bar()
    assert bar.matched_volume is None
    assert bar.close == 1.5


def test_models_are_frozen() -> None:
    bar = _bar()
    with pytest.raises(ValidationError):
        bar.close = 2.0  # type: ignore[misc]


def test_financial_ratios_period_type_is_a_literal() -> None:
    record = FinancialRatios(
        ticker="VCB",
        period=date(2023, 12, 31),
        period_type="annual",
        provider="kbs",
        ratios={"roe": 15.2},
    )
    assert record.ratios["roe"] == 15.2
    with pytest.raises(ValidationError):
        FinancialRatios(
            ticker="VCB",
            period=date(2023, 12, 31),
            period_type="weekly",  # type: ignore[arg-type]
            provider="kbs",
            ratios={},
        )


def test_company_profile_and_sector_map_fields() -> None:
    profile = CompanyProfile(
        ticker="VCB",
        free_float_ratio=85.0,
        shares_outstanding=5_000_000_000,
        market_cap=3_000_000_000_000,
        source="vci",
    )
    assert profile.free_float_ratio == 85.0
    sector = SectorMap(
        ticker="VCB",
        exchange="HOSE",
        icb_level1_name="Banks",
        icb_level1_code="8300",
        icb_level2_name="Banks",
        icb_level2_code="8355",
        security_type="stock",
        source="vci",
    )
    assert sector.icb_level1_code == "8300"


def test_index_constituents_members() -> None:
    members = IndexConstituents(
        index="VN30", members=["VCB", "FPT"], as_of=None, source="kbs"
    )
    assert members.members == ["VCB", "FPT"]
