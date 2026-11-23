"""Ratio data-quality checks for the V2b fundamentals dataset.

Mirrors ``data/v2/quality.py``: an interface plus a registry, so adding a rule is one
class plus one registration. Every check runs over one ticker's stored
:class:`FinancialRatios` list and its sector context.

Severity policy: every ratio finding is a ``warning`` (a coverage or quality note
about one ticker), never an ``error``. The dataset keeps whatever was fetched so a
re-run can fill gaps; a ticker SSI does not cover is a coverage gap, not an integrity
failure. The dataset-level "missing tickers" report is a helper
(:func:`missing_ratio_tickers`) rather than a per-ticker check because it compares the
whole universe against the tickers that actually have ratios.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, cast

from pydantic import BaseModel

from core.registry import Registry
from data.models import QualityFinding
from data.v2.ratios import PERCENTAGE_RATIOS
from data.v2.schemas import FinancialRatios

CheckSeverity = Literal["info", "warning", "error"]

#: A percentage ratio whose magnitude is below this per-ratio value (and not zero)
#: is a *candidate* unit error. It is only flagged when a prior period was at least
#: ``UnitMismatchParams.collapse_factor`` times larger, so a genuinely low value (a
#: sub-1% ROE or a ~1% net margin) is not flagged on its own. It is per-ratio because
#: a sub-1% ROE is unusual while a sub-1% dividend yield is normal, so one global
#: threshold would either miss the ROE error or flag the yield.
FRACTION_LIKE_THRESHOLDS: dict[str, float] = {
    "roe": 1.0,
    "roic": 1.0,
    "grossProfitMargin": 1.0,
    "netProfitMargin": 1.0,
    "roa": 0.25,
    "npl": 0.25,
    "dividendYield": 0.1,
}


class NoRatiosParams(BaseModel):
    """Options for the no-ratios coverage check (none)."""


class StalePeriodParams(BaseModel):
    """Options for the stale-latest-period check."""

    max_age_days: int = 200


class OutlierParams(BaseModel):
    """Options for the coarse absolute-bound outlier check.

    The bounds are generous guards against clearly implausible values (a data glitch
    or a unit error), not a precise anomaly detector; the sector statistics
    winsorize the real distribution.
    """

    abs_bounds: dict[str, float] = {
        "pe": 500.0,
        "pb": 200.0,
        "roe": 300.0,
        "roa": 150.0,
        "roic": 300.0,
        "grossProfitMargin": 100.0,
        "netProfitMargin": 500.0,
        "debtEquity": 300.0,
        "debtAsset": 20.0,
        "npl": 100.0,
        "dividendYield": 100.0,
    }


class UnitMismatchParams(BaseModel):
    """Options for the unit-mismatch check (per-ratio fraction thresholds).

    A value below its ratio's threshold is only treated as a unit error when a
    prior period was at least ``collapse_factor`` times larger, so a genuinely low
    ratio (a sub-1% ROE or a ~1% net margin) is not flagged.
    """

    thresholds: dict[str, float] = dict(FRACTION_LIKE_THRESHOLDS)
    collapse_factor: float = 100.0


@dataclass
class RatioQualityContext:
    """One ticker's stored ratios plus the reference date for the checks."""

    ticker: str
    sector: str | None
    ratios: Sequence[FinancialRatios]
    as_of: date


class RatioQualityCheck(Protocol):
    """A single ratio quality rule."""

    id: str
    display_name: str
    severity: CheckSeverity

    def run(self, context: RatioQualityContext) -> list[QualityFinding]:
        """Return the findings produced for ``context``."""


class RatioQualityFactory(Protocol):
    """Callable shape of a registered ratio check class."""

    def __call__(self) -> RatioQualityCheck: ...


#: Every registered ratio quality check, keyed by id.
ratio_quality_checks: Registry[RatioQualityCheck] = Registry()


def _latest(context: RatioQualityContext) -> FinancialRatios | None:
    """Return the newest ratio record, or ``None`` when none are stored."""
    if not context.ratios:
        return None
    return max(context.ratios, key=lambda record: record.period)


def _prior_value(
    ratios: Sequence[FinancialRatios], latest: FinancialRatios, ratio: str
) -> float | None:
    """Return the most recent non-null ``ratio`` value before ``latest``'s period."""
    best_period: date | None = None
    best_value: float | None = None
    for record in ratios:
        if record.period >= latest.period:
            continue
        value = record.ratios.get(ratio)
        if value is None:
            continue
        if best_period is None or record.period > best_period:
            best_period = record.period
            best_value = value
    return best_value


@ratio_quality_checks.register(
    id="no_ratios",
    name="No ratios",
    description="A ticker has no stored financial ratios (a coverage gap).",
    parameter_schema=NoRatiosParams,
)
class NoRatiosCheck:
    """Flag a ticker with no stored ratio periods."""

    id = "no_ratios"
    display_name = "No ratios"
    severity: CheckSeverity = "warning"

    def run(self, context: RatioQualityContext) -> list[QualityFinding]:
        if context.ratios:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity=self.severity,
                message="no financial ratios stored for this ticker",
                dates=[],
                details={},
            )
        ]


@ratio_quality_checks.register(
    id="stale_period",
    name="Stale period",
    description="The latest stored ratio period is older than the expected filing.",
    parameter_schema=StalePeriodParams,
)
class StalePeriodCheck:
    """Flag a ticker whose newest ratio period is too old to be current."""

    id = "stale_period"
    display_name = "Stale period"
    severity: CheckSeverity = "warning"

    def run(self, context: RatioQualityContext) -> list[QualityFinding]:
        latest = _latest(context)
        if latest is None:
            return []
        params = StalePeriodParams()
        age = (context.as_of - latest.period).days
        if age <= params.max_age_days:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity=self.severity,
                message=(
                    f"latest ratio period {latest.period.isoformat()} is {age} days old "
                    f"(max {params.max_age_days})"
                ),
                dates=[latest.period],
                details={"age_days": age},
            )
        ]


@ratio_quality_checks.register(
    id="ratio_outlier",
    name="Ratio outlier",
    description="A ratio value is beyond a generous plausible bound.",
    parameter_schema=OutlierParams,
)
class RatioOutlierCheck:
    """Flag latest-period ratios beyond the plausible absolute bounds."""

    id = "ratio_outlier"
    display_name = "Ratio outlier"
    severity: CheckSeverity = "warning"

    def run(self, context: RatioQualityContext) -> list[QualityFinding]:
        latest = _latest(context)
        if latest is None:
            return []
        params = OutlierParams()
        findings: list[QualityFinding] = []
        for ratio, value in latest.ratios.items():
            bound = params.abs_bounds.get(ratio)
            if value is None or bound is None:
                continue
            if abs(value) > bound:
                findings.append(
                    QualityFinding(
                        check=self.id,
                        severity=self.severity,
                        message=(
                            f"{ratio}={value:.3f} exceeds the plausible bound {bound:.0f}"
                        ),
                        dates=[latest.period],
                        details={"ratio": ratio, "value": value, "bound": bound},
                    )
                )
        return findings


@ratio_quality_checks.register(
    id="unit_mismatch",
    name="Unit mismatch",
    description="A percentage ratio looks like a raw fraction (not multiplied by 100).",
    parameter_schema=UnitMismatchParams,
)
class UnitMismatchCheck:
    """Flag a percentage ratio that collapsed ~100x versus its own prior periods."""

    id = "unit_mismatch"
    display_name = "Unit mismatch"
    severity: CheckSeverity = "warning"

    def run(self, context: RatioQualityContext) -> list[QualityFinding]:
        latest = _latest(context)
        if latest is None:
            return []
        params = UnitMismatchParams()
        findings: list[QualityFinding] = []
        for ratio, value in latest.ratios.items():
            if ratio not in PERCENTAGE_RATIOS or value is None:
                continue
            threshold = params.thresholds.get(ratio)
            if threshold is None:
                continue
            if value == 0.0 or abs(value) >= threshold:
                continue
            prior = _prior_value(context.ratios, latest, ratio)
            if prior is None or abs(prior) < params.collapse_factor * abs(value):
                continue
            findings.append(
                QualityFinding(
                    check=self.id,
                    severity=self.severity,
                    message=(
                        f"{ratio}={value:.4f} collapsed from {prior:.4f}; looks like a "
                        "fraction that was not multiplied by 100"
                    ),
                    dates=[latest.period],
                    details={"ratio": ratio, "value": value, "prior": prior},
                )
            )
        return findings


def run_ratio_quality_checks(
    ticker: str,
    ratios: Sequence[FinancialRatios],
    *,
    sector: str | None,
    as_of: date,
) -> list[QualityFinding]:
    """Run every registered ratio check for one ticker and return its findings."""
    context = RatioQualityContext(
        ticker=ticker.upper(), sector=sector, ratios=ratios, as_of=as_of
    )
    findings: list[QualityFinding] = []
    for check_id in ratio_quality_checks.list():
        factory = cast(RatioQualityFactory, ratio_quality_checks.get(check_id))
        findings.extend(factory().run(context))
    return findings


def missing_ratio_tickers(
    universe: Sequence[str], have_ratios: Sequence[str]
) -> list[str]:
    """Return the universe tickers with no stored ratios, sorted."""
    have = {ticker.strip().upper() for ticker in have_ratios}
    return sorted(
        ticker.strip().upper()
        for ticker in universe
        if ticker.strip().upper() not in have
    )


__all__ = [
    "FRACTION_LIKE_THRESHOLDS",
    "NoRatiosCheck",
    "NoRatiosParams",
    "OutlierParams",
    "RatioOutlierCheck",
    "RatioQualityCheck",
    "RatioQualityContext",
    "StalePeriodCheck",
    "StalePeriodParams",
    "UnitMismatchCheck",
    "UnitMismatchParams",
    "missing_ratio_tickers",
    "ratio_quality_checks",
    "run_ratio_quality_checks",
]
