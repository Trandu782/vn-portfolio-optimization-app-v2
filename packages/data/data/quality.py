"""Data-quality checks as a registry of pluggable rules.

Each check is one class registered with ``@quality_checks.register(...)`` and
implements the same ``run(context) -> list[QualityFinding]`` contract, so adding a
new rule is one file plus one registration. :func:`run_quality_checks` runs every
registered check for a symbol and returns a single ``QualityReport``.

The checks use the exchange rules (holiday calendar and daily price limit) from
``core.market_rules`` rather than hardcoding them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol, cast

from pydantic import BaseModel

from core.market_rules import DEFAULT_MARKET_RULES, MarketRules
from core.registry import Registry
from data.calendar import trading_days_between
from data.models import PriceBar, QualityFinding, QualityReport


class MissingDaysParams(BaseModel):
    """Options for the missing-trading-days check."""

    max_listed_dates: int = 20


class StaleRunParams(BaseModel):
    """Options for the repeated-close (stale price run) check."""

    min_run: int = 5


class ZeroVolumeParams(BaseModel):
    """Options for the zero-volume / suspected-suspension check."""

    min_days: int = 1
    max_listed_dates: int = 20


class PriceLimitParams(BaseModel):
    """Options for the daily-price-limit check."""

    buffer: float = 0.005


@dataclass
class QualityContext:
    """Everything a check needs to inspect one symbol's series."""

    symbol: str
    exchange: str
    bars: Sequence[PriceBar]
    rules: MarketRules = DEFAULT_MARKET_RULES
    as_of: date | None = None
    extra: dict[str, object] = field(default_factory=dict)


class QualityCheck(Protocol):
    """A single quality rule."""

    id: str
    display_name: str

    def run(self, context: QualityContext) -> list[QualityFinding]:
        """Return the findings produced for ``context``."""


class QualityFactory(Protocol):
    """Callable shape of a registered check class."""

    def __call__(self) -> QualityCheck: ...


#: Every registered quality check, keyed by id.
quality_checks: Registry[QualityCheck] = Registry()


@quality_checks.register(
    id="missing_trading_days",
    name="Missing trading days",
    description="Trading days inside the series with no bar (weekends/holidays excluded).",
    parameter_schema=MissingDaysParams,
)
class MissingTradingDaysCheck:
    """Flag gaps on days the exchange was open."""

    id = "missing_trading_days"
    display_name = "Missing trading days"

    def run(self, context: QualityContext) -> list[QualityFinding]:
        if len(context.bars) < 2:
            return []
        present = {bar.date for bar in context.bars}
        expected = trading_days_between(
            context.bars[0].date, context.bars[-1].date, context.rules.trading_holidays
        )
        missing = [day for day in expected if day not in present]
        if not missing:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity="warning",
                message=f"{len(missing)} trading days have no bar",
                dates=missing[:MissingDaysParams().max_listed_dates],
                details={"missing_count": len(missing)},
            )
        ]


@quality_checks.register(
    id="stale_price_runs",
    name="Stale price runs",
    description="Consecutive days with an identical close price (suspected stale feed).",
    parameter_schema=StaleRunParams,
)
class StalePriceRunsCheck:
    """Flag runs of identical closes longer than the threshold."""

    id = "stale_price_runs"
    display_name = "Stale price runs"

    def run(self, context: QualityContext) -> list[QualityFinding]:
        bars = context.bars
        min_run = StaleRunParams().min_run
        findings: list[QualityFinding] = []
        index = 0
        while index < len(bars):
            end = index
            while end + 1 < len(bars) and bars[end + 1].close == bars[index].close:
                end += 1
            length = end - index + 1
            if length >= min_run:
                findings.append(
                    QualityFinding(
                        check=self.id,
                        severity="warning",
                        message=(
                            f"{length} consecutive days close at {bars[index].close}"
                        ),
                        dates=[bars[index].date, bars[end].date],
                        details={"length": length},
                    )
                )
            index = end + 1
        return findings


@quality_checks.register(
    id="zero_volume",
    name="Zero-volume days",
    description="Days with zero volume, a common sign of a trading suspension.",
    parameter_schema=ZeroVolumeParams,
)
class ZeroVolumeCheck:
    """Flag zero-volume days that look like a suspension."""

    id = "zero_volume"
    display_name = "Zero-volume days"

    def run(self, context: QualityContext) -> list[QualityFinding]:
        params = ZeroVolumeParams()
        zero_days = [bar.date for bar in context.bars if bar.volume == 0]
        if len(zero_days) < params.min_days or not zero_days:
            return []
        return [
            QualityFinding(
                check=self.id,
                severity="warning",
                message=(
                    f"{len(zero_days)} zero-volume day(s), possible trading suspension"
                ),
                dates=zero_days[: params.max_listed_dates],
                details={"count": len(zero_days)},
            )
        ]


@quality_checks.register(
    id="price_limit_move",
    name="Price-limit moves",
    description="Daily moves beyond the exchange limit (often a sign of unadjusted data).",
    parameter_schema=PriceLimitParams,
)
class PriceLimitMoveCheck:
    """Flag day-on-day moves larger than the exchange daily price limit."""

    id = "price_limit_move"
    display_name = "Price-limit moves"

    def run(self, context: QualityContext) -> list[QualityFinding]:
        exchange = context.rules.exchanges.get(context.exchange.upper())
        if exchange is None:
            return []
        threshold = float(exchange.daily_price_limit) + PriceLimitParams().buffer
        findings: list[QualityFinding] = []
        for previous, current in zip(context.bars, context.bars[1:], strict=False):
            if previous.close <= 0:
                continue
            move = abs(current.close - previous.close) / previous.close
            if move > threshold:
                findings.append(
                    QualityFinding(
                        check=self.id,
                        severity="error",
                        message=(
                            f"{move:.1%} move on {current.date.isoformat()} exceeds the "
                            f"{float(exchange.daily_price_limit):.0%} {exchange.code} limit"
                        ),
                        dates=[current.date],
                        details={"move": move},
                    )
                )
        return findings


def run_quality_checks(
    symbol: str,
    bars: Sequence[PriceBar],
    *,
    exchange: str,
    rules: MarketRules = DEFAULT_MARKET_RULES,
    as_of: date | None = None,
) -> QualityReport:
    """Run every registered check for ``symbol`` and return one report."""
    context = QualityContext(
        symbol=symbol.upper(), exchange=exchange.upper(), bars=bars, rules=rules, as_of=as_of
    )
    findings: list[QualityFinding] = []
    checks_run: list[str] = []
    for check_id in quality_checks.list():
        factory = cast(QualityFactory, quality_checks.get(check_id))
        check = factory()
        checks_run.append(check_id)
        findings.extend(check.run(context))
    ok = not any(finding.severity in ("warning", "error") for finding in findings)
    return QualityReport(
        symbol=symbol.upper(),
        ok=ok,
        checked_at=datetime.now(UTC),
        checks_run=checks_run,
        findings=findings,
    )
