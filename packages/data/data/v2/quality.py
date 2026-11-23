"""Data-quality checks for the V2 precompute datasets.

Like ``data.quality`` this is an interface plus a registry: adding a rule is one class
plus one registration. The checks run over the *raw* :class:`AdjustedOHLCV` series and
the ticker's corporate actions, and every problem is a finding with an explicit
severity.

Severity policy
---------------
Only *integrity* findings are ``error`` and fail the precompute step:

* ``no_data`` — a universe member has no bars at all;
* ``duplicate_dates`` — the same date twice.

Per-ticker *data-quality* findings are ``warning``: they are surfaced (and stored as
adjustment flags with reasons) but never fail the step, because they describe the
ticker rather than the integrity of the dataset:

* ``missing_trading_days`` — exchange-open days with no bar (a halt, suspension or late
  listing);
* ``zero_volume_streak`` — a run of zero-volume days (possible suspension);
* ``suspicious_returns`` — a daily move beyond the exchange limit that is *not* near a
  corporate-action ex-date (adjusted prices should never gap on an ordinary day);
* ``adjusted_vs_raw_mismatch`` — the adjusted/raw ratio jumps without a corporate
  action, or an ISS reconciliation looks like a spurious adjustment gain.

The job treats the report's ``ok`` flag (no ``error`` findings) as the gate and logs
every warning; the data already fetched is kept so a re-run can fill gaps.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol, cast

from pydantic import BaseModel

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from core.registry import Registry
from data.calendar import trading_days_between
from data.models import QualityFinding, QualityReport
from data.v2.adjustment_quality import widest_daily_limit
from data.v2.explained_findings import reclassify_findings
from data.v2.reconcile import reconcile_corporate_actions
from data.v2.schemas import AdjustedOHLCV, CorporateAction

#: Severity of a quality finding: ``error`` fails the step, ``warning`` is reported.
CheckSeverity = Literal["info", "warning", "error"]


class MissingDatesParams(BaseModel):
    """Options for the missing-trading-days check."""

    max_listed_dates: int = 20


class ZeroVolumeStreakParams(BaseModel):
    """Options for the zero-volume streak check."""

    min_streak: int = 5
    max_listed_dates: int = 20


class SuspiciousReturnsParams(BaseModel):
    """Options for the suspicious-return check."""

    limit_buffer: float = 0.005
    action_window_days: int = 1
    max_listed_dates: int = 20


class AdjustedRawParams(BaseModel):
    """Options for the adjusted-vs-raw mismatch check."""

    tolerance: float = 0.02
    action_window_days: int = 1
    max_listed_dates: int = 20


class NoDataParams(BaseModel):
    """Options for the no-data integrity check (none)."""


@dataclass
class V2QualityContext:
    """Everything a V2 check needs to inspect one ticker's series."""

    ticker: str
    exchange: str
    bars: Sequence[AdjustedOHLCV]
    actions: Sequence[CorporateAction] = ()
    rules: MarketRules = DEFAULT_MARKET_RULES
    trading_days: frozenset[date] | None = None
    extra: dict[str, object] = field(default_factory=dict)


class V2QualityCheck(Protocol):
    """A single V2 quality rule."""

    id: str
    display_name: str
    #: ``error`` for an integrity rule that fails the step, ``warning`` for a
    #: per-ticker data-quality note that is reported but never fails the step.
    severity: CheckSeverity

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        """Return the findings produced for ``context``."""


class V2QualityFactory(Protocol):
    """Callable shape of a registered V2 check class."""

    def __call__(self) -> V2QualityCheck: ...


#: Every registered V2 quality check, keyed by id.
v2_quality_checks: Registry[V2QualityCheck] = Registry()


def _ordered(bars: Sequence[AdjustedOHLCV]) -> list[AdjustedOHLCV]:
    """Return bars sorted by date with one bar per date (the last wins)."""
    by_date = {bar.date: bar for bar in bars}
    return [by_date[day] for day in sorted(by_date)]


def _action_dates(actions: Sequence[CorporateAction]) -> set[date]:
    """Return the corporate-action ex-dates that are known."""
    return {action.exright_date for action in actions if action.exright_date is not None}


def _near_action(day: date, action_dates: set[date], window_days: int) -> bool:
    """Return ``True`` when ``day`` is within ``window_days`` calendar days of an ex-date."""
    if window_days < 0:
        return False
    return any(abs((day - action_day).days) <= window_days for action_day in action_dates)


@v2_quality_checks.register(
    id="no_data",
    name="No data",
    description="A universe member has no price bars at all (an integrity error).",
    parameter_schema=NoDataParams,
)
class NoDataCheck:
    """Flag a ticker that has no stored bars at all."""

    id = "no_data"
    display_name = "No data"
    severity: CheckSeverity = "error"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        if context.bars:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity=self.severity,
                message="no price bars stored for this ticker",
                dates=[],
                details={},
            )
        ]


@v2_quality_checks.register(
    id="missing_trading_days",
    name="Missing trading days",
    description="Exchange-open days inside the series with no bar.",
    parameter_schema=MissingDatesParams,
)
class MissingTradingDaysCheck:
    """Flag exchange-open days with no bar."""

    id = "missing_trading_days"
    display_name = "Missing trading days"
    severity: CheckSeverity = "warning"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        ordered = _ordered(context.bars)
        if len(ordered) < 2:
            return []
        params = MissingDatesParams()
        present = {bar.date for bar in ordered}
        first, last = ordered[0].date, ordered[-1].date
        if context.trading_days:
            # Real exchange calendar derived from stored VN-Index bar dates.
            expected = [day for day in sorted(context.trading_days) if first <= day <= last]
        else:
            expected = trading_days_between(first, last, context.rules.trading_holidays)
        missing = [day for day in expected if day not in present]
        if not missing:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity=self.severity,
                message=f"{len(missing)} trading days have no bar",
                dates=missing[: params.max_listed_dates],
                details={"count": len(missing)},
            )
        ]


@v2_quality_checks.register(
    id="duplicate_dates",
    name="Duplicate dates",
    description="Two or more bars share the same trading date.",
    parameter_schema=MissingDatesParams,
)
class DuplicateDatesCheck:
    """Flag duplicated trading dates in the raw series."""

    id = "duplicate_dates"
    display_name = "Duplicate dates"
    severity: CheckSeverity = "error"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        params = MissingDatesParams()
        counts: dict[date, int] = {}
        for bar in context.bars:
            counts[bar.date] = counts.get(bar.date, 0) + 1
        duplicates = sorted(day for day, count in counts.items() if count > 1)
        if not duplicates:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity=self.severity,
                message=f"{len(duplicates)} trading dates appear more than once",
                dates=duplicates[: params.max_listed_dates],
                details={"count": len(duplicates)},
            )
        ]


@v2_quality_checks.register(
    id="zero_volume_streak",
    name="Zero-volume streak",
    description="A run of consecutive zero-volume days, a common suspension sign.",
    parameter_schema=ZeroVolumeStreakParams,
)
class ZeroVolumeStreakCheck:
    """Flag consecutive zero-volume runs of at least ``min_streak`` days."""

    id = "zero_volume_streak"
    display_name = "Zero-volume streak"
    severity: CheckSeverity = "warning"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        params = ZeroVolumeStreakParams()
        ordered = _ordered(context.bars)
        streaks: list[list[date]] = []
        current: list[date] = []
        for bar in ordered:
            if bar.volume == 0:
                current.append(bar.date)
            else:
                if len(current) >= params.min_streak:
                    streaks.append(current)
                current = []
        if len(current) >= params.min_streak:
            streaks.append(current)
        findings: list[QualityFinding] = []
        for streak in streaks:
            findings.append(
                QualityFinding(
                    check=self.id,
                    severity=self.severity,
                    message=(
                        f"{len(streak)} consecutive zero-volume days starting "
                        f"{streak[0].isoformat()}"
                    ),
                    dates=streak[: params.max_listed_dates],
                    details={"count": len(streak)},
                )
            )
        return findings


@v2_quality_checks.register(
    id="suspicious_returns",
    name="Suspicious returns",
    description="A daily move beyond the exchange limit away from any ex-date.",
    parameter_schema=SuspiciousReturnsParams,
)
class SuspiciousReturnsCheck:
    """Flag adjusted-close moves beyond the limit that no ex-date explains."""

    id = "suspicious_returns"
    display_name = "Suspicious returns"
    severity: CheckSeverity = "warning"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        params = SuspiciousReturnsParams()
        widest = widest_daily_limit(context.rules)
        threshold = widest + params.limit_buffer
        action_dates = _action_dates(context.actions)
        ordered = _ordered(context.bars)
        findings: list[QualityFinding] = []
        for previous, current in itertools.pairwise(ordered):
            if previous.close <= 0:
                continue
            move = current.close / previous.close - 1.0
            if abs(move) <= threshold:
                continue
            if _near_action(current.date, action_dates, params.action_window_days):
                continue
            findings.append(
                QualityFinding(
                    check=self.id,
                    severity=self.severity,
                    message=(
                        f"{move:.1%} move on {current.date.isoformat()} exceeds the "
                        f"{widest:.0%} widest exchange limit "
                        "and is not near a corporate action"
                    ),
                    dates=[current.date],
                    details={"move": move},
                )
            )
        return findings[: params.max_listed_dates]


@v2_quality_checks.register(
    id="adjusted_vs_raw_mismatch",
    name="Adjusted-vs-raw mismatch",
    description="The adjusted/raw close ratio jumps without a corporate action.",
    parameter_schema=AdjustedRawParams,
)
class AdjustedVsRawMismatchCheck:
    """Flag inconsistent adjustment, plus reconciliation differences at ex-dates."""

    id = "adjusted_vs_raw_mismatch"
    display_name = "Adjusted-vs-raw mismatch"
    severity: CheckSeverity = "warning"

    def run(self, context: V2QualityContext) -> list[QualityFinding]:
        params = AdjustedRawParams()
        action_dates = _action_dates(context.actions)
        ordered = _ordered(context.bars)
        findings: list[QualityFinding] = []
        for previous, current in itertools.pairwise(ordered):
            if not previous.close_raw or not current.close_raw:
                continue
            if previous.close_raw <= 0 or current.close_raw <= 0:
                continue
            prev_ratio = previous.close / previous.close_raw
            curr_ratio = current.close / current.close_raw
            if abs(curr_ratio - prev_ratio) <= params.tolerance:
                continue
            if _near_action(current.date, action_dates, params.action_window_days):
                continue
            findings.append(
                QualityFinding(
                    check=self.id,
                    severity=self.severity,
                    message=(
                        f"adjusted/raw ratio changed by {curr_ratio - prev_ratio:+.3f} on "
                        f"{current.date.isoformat()} with no corporate action"
                    ),
                    dates=[current.date],
                    details={"prev_ratio": prev_ratio, "curr_ratio": curr_ratio},
                )
            )
        for finding in reconcile_corporate_actions(
            ordered, context.actions, tolerance=params.tolerance
        ):
            if finding.status not in {"difference", "adjustment_suspect"}:
                continue
            if finding.status == "adjustment_suspect":
                message = (
                    f"suspicious adjustment {finding.adjusted_gap:+.1%} at the "
                    f"{finding.event_type} ex-date {finding.ex_date.isoformat()} "
                    "(adjusted close jumped while the raw close did not fall)"
                )
            else:
                message = (
                    f"reconciliation difference {finding.difference:+.4f} at the "
                    f"{finding.event_type} ex-date {finding.ex_date.isoformat()}"
                )
            findings.append(
                QualityFinding(
                    check=self.id,
                    severity=self.severity,
                    message=message,
                    dates=[finding.ex_date],
                    details={"status": finding.status, "difference": finding.difference},
                )
            )
        return findings[: params.max_listed_dates]


def run_v2_quality_checks(
    ticker: str,
    bars: Sequence[AdjustedOHLCV],
    *,
    exchange: str,
    actions: Sequence[CorporateAction] = (),
    rules: MarketRules = DEFAULT_MARKET_RULES,
    trading_days: frozenset[date] | None = None,
) -> QualityReport:
    """Run every registered V2 check for one ticker and return one report.

    ``trading_days`` is the real exchange calendar derived from the stored VN-Index
    bars (see :func:`data.calendar.trading_days_from_dates`). When it is supplied the
    missing-days check uses it instead of the illustrative ``rules.trading_holidays``.
    """
    context = V2QualityContext(
        ticker=ticker.upper(),
        exchange=exchange.upper(),
        bars=bars,
        actions=actions,
        rules=rules,
        trading_days=trading_days,
    )
    findings: list[QualityFinding] = []
    checks_run: list[str] = []
    for check_id in v2_quality_checks.list():
        factory = cast(V2QualityFactory, v2_quality_checks.get(check_id))
        check = factory()
        checks_run.append(check_id)
        findings.extend(check.run(context))
    # Findings documented as known/explained are annotated; only an integrity error
    # fails the step (per-ticker data-quality findings are warnings, see the module
    # policy).
    findings = reclassify_findings(ticker.upper(), findings)
    ok = not any(finding.severity == "error" for finding in findings)
    return QualityReport(
        symbol=ticker.upper(),
        ok=ok,
        checked_at=datetime.now(UTC),
        checks_run=checks_run,
        findings=findings,
    )


__all__ = [
    "AdjustedRawParams",
    "AdjustedVsRawMismatchCheck",
    "MissingDatesParams",
    "NoDataCheck",
    "NoDataParams",
    "SuspiciousReturnsCheck",
    "SuspiciousReturnsParams",
    "V2QualityCheck",
    "V2QualityContext",
    "ZeroVolumeStreakCheck",
    "ZeroVolumeStreakParams",
    "run_v2_quality_checks",
    "v2_quality_checks",
]

