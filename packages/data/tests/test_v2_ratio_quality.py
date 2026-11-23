"""Ratio quality checks: stale periods, outliers, unit mismatches, missing tickers."""

from __future__ import annotations

from datetime import date

from data.v2.ratio_quality import missing_ratio_tickers, run_ratio_quality_checks
from data.v2.schemas import FinancialRatios

AS_OF = date(2026, 11, 23)


def _ratios(
    period: date = date(2026, 9, 30), ratios: dict[str, float | None] | None = None
) -> list[FinancialRatios]:
    return [
        FinancialRatios(
            ticker="VCB",
            period=period,
            period_type="ttm",
            provider="ssi_statistics",
            ratios=ratios if ratios is not None else {"roe": 17.0},
        )
    ]


def _checks(findings) -> set[str]:
    return {finding.check for finding in findings}


def test_no_ratios_is_a_warning() -> None:
    findings = run_ratio_quality_checks("VCB", [], sector="Banks", as_of=AS_OF)
    assert _checks(findings) == {"no_ratios"}
    assert findings[0].severity == "warning"


def test_stale_period_flags_an_old_latest() -> None:
    findings = run_ratio_quality_checks(
        "VCB", _ratios(period=date(2025, 9, 30)), sector="Banks", as_of=AS_OF
    )
    assert "stale_period" in _checks(findings)


def test_fresh_period_is_not_stale() -> None:
    findings = run_ratio_quality_checks(
        "VCB", _ratios(period=date(2026, 9, 30)), sector="Banks", as_of=AS_OF
    )
    assert "stale_period" not in _checks(findings)


def test_outlier_flags_an_implausible_value() -> None:
    findings = run_ratio_quality_checks(
        "VCB", _ratios(ratios={"roe": 5000.0}), sector="Banks", as_of=AS_OF
    )
    assert "ratio_outlier" in _checks(findings)


def test_outlier_ignores_a_high_but_genuine_net_margin() -> None:
    # A net margin over 100% is possible for a company with large non-operating
    # gains (PDR), so it is not an outlier under the raised bound.
    findings = run_ratio_quality_checks(
        "PDR", _ratios(ratios={"netProfitMargin": 100.5}), sector="Real Estate", as_of=AS_OF
    )
    assert "ratio_outlier" not in _checks(findings)


def _two_periods(ratio: str, prior: float, latest: float) -> list[FinancialRatios]:
    return [
        FinancialRatios(
            ticker="VCB",
            period=date(2026, 6, 30),
            period_type="ttm",
            provider="ssi_statistics",
            ratios={ratio: prior},
        ),
        FinancialRatios(
            ticker="VCB",
            period=date(2026, 9, 30),
            period_type="ttm",
            provider="ssi_statistics",
            ratios={ratio: latest},
        ),
    ]


def test_unit_mismatch_flags_a_fraction_like_percentage() -> None:
    # A ~100x collapse versus the prior period is a real unit error.
    findings = run_ratio_quality_checks(
        "VCB", _two_periods("roe", 20.0, 0.17), sector="Banks", as_of=AS_OF
    )
    assert "unit_mismatch" in _checks(findings)


def test_unit_mismatch_ignores_a_genuine_low_value() -> None:
    # A sub-1% ROE that declined gradually is a genuine value, not a unit error.
    findings = run_ratio_quality_checks(
        "VCB", _two_periods("roe", 1.39, 0.80), sector="Banks", as_of=AS_OF
    )
    assert "unit_mismatch" not in _checks(findings)


def test_unit_mismatch_ignores_a_normal_percentage() -> None:
    findings = run_ratio_quality_checks(
        "VCB", _ratios(ratios={"roe": 17.0}), sector="Banks", as_of=AS_OF
    )
    assert "unit_mismatch" not in _checks(findings)


def test_missing_ratio_tickers() -> None:
    assert missing_ratio_tickers(["VCB", "BID", "FPT"], ["vcb"]) == ["BID", "FPT"]
    assert missing_ratio_tickers(["VCB"], ["VCB", "BID"]) == []
