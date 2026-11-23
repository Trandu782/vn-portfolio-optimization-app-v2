"""Documented, explained data-quality findings (``docs/V2_PRECOMPUTE_VALIDATION.md``).

Some findings are real but understood and already documented: SSI's adjusted-vs-raw
daily drift on VGI/OIL, HPG bonus issues the feed omits, the one-day adjusted-close
glitches on GEE/MCH/NAB/TAL/VTP, the halt/gap days on GEE/TAL/VTP/NAB/MCH/SIP, and BSR's
real pre-transfer trading halt (no bars 2025-01-07..16, HOSE debut 2025-01-17). These
are annotated as ``explained`` by :func:`reclassify_findings`; per-ticker findings are
warnings regardless (see the severity policy in :mod:`data.v2.quality`). Adding a new
known case is a config edit here, not a code change. A finding is matched by ticker +
check + the overlap of its dates with the entry's range (``None`` range means any date).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from data.models import QualityFinding


@dataclass(frozen=True)
class ExplainedFinding:
    """One documented, understood quality finding."""

    ticker: str
    check: str
    start: date | None
    end: date | None
    explanation: str


#: Tickers with a documented one-day adjusted-close glitch (SSI `close` vs `closeRaw`).
_ADJUSTMENT_GLITCH_TICKERS: tuple[str, ...] = ("GEE", "MCH", "NAB", "TAL", "VTP")
#: Tickers with a documented halt/suspension or late-listing gap.
_HALT_TICKERS: tuple[str, ...] = ("GEE", "TAL", "VTP", "NAB", "MCH", "SIP")

#: Known, documented findings. ``start``/``end`` of ``None`` mean "any date".
EXPLAINED_FINDINGS: tuple[ExplainedFinding, ...] = (
    ExplainedFinding(
        ticker="VGI",
        check="adjusted_vs_raw_mismatch",
        start=None,
        end=None,
        explanation=(
            "SSI adjusted-vs-raw daily drift (docs/V2_PRECOMPUTE_VALIDATION.md)"
        ),
    ),
    ExplainedFinding(
        ticker="OIL",
        check="adjusted_vs_raw_mismatch",
        start=None,
        end=None,
        explanation=(
            "SSI adjusted-vs-raw daily drift (docs/V2_PRECOMPUTE_VALIDATION.md)"
        ),
    ),
    ExplainedFinding(
        ticker="HPG",
        check="adjusted_vs_raw_mismatch",
        start=None,
        end=None,
        explanation=(
            "SSI feed omits HPG bonus issues (docs/V2_PRECOMPUTE_VALIDATION.md)"
        ),
    ),
    ExplainedFinding(
        ticker="BSR",
        check="missing_trading_days",
        start=date(2025, 1, 7),
        end=date(2025, 1, 16),
        explanation=(
            "real pre-transfer trading halt; BSR first traded on HOSE 2025-01-17"
        ),
    ),
    ExplainedFinding(
        ticker="BSR",
        check="suspicious_returns",
        start=date(2024, 5, 22),
        end=date(2024, 5, 22),
        explanation=(
            "2024-05-22 session was still under UPCoM's 15% band before the HOSE transfer"
        ),
    ),
    *(
        ExplainedFinding(
            ticker=ticker,
            check="adjusted_vs_raw_mismatch",
            start=None,
            end=None,
            explanation=(
                "SSI one-day adjusted-close glitch / feed-omitted action "
                "(docs/V2_PRECOMPUTE_VALIDATION.md)"
            ),
        )
        for ticker in _ADJUSTMENT_GLITCH_TICKERS
    ),
    *(
        ExplainedFinding(
            ticker=ticker,
            check="missing_trading_days",
            start=None,
            end=None,
            explanation=(
                "documented halt/suspension or late-listing gap "
                "(docs/V2_PRECOMPUTE_VALIDATION.md)"
            ),
        )
        for ticker in _HALT_TICKERS
    ),
)


def _in_range(day: date, start: date | None, end: date | None) -> bool:
    """Return ``True`` when ``day`` falls inside the inclusive ``[start, end]`` range."""
    if start is not None and day < start:
        return False
    return end is None or day <= end


def match_explained(
    ticker: str, check: str, dates: Sequence[date] = ()
) -> str | None:
    """Return the explanation when a finding matches a documented case, else ``None``."""
    code = ticker.strip().upper()
    for item in EXPLAINED_FINDINGS:
        if item.ticker.upper() != code or item.check != check:
            continue
        if item.start is None and item.end is None:
            return item.explanation
        if not dates or any(_in_range(day, item.start, item.end) for day in dates):
            return item.explanation
    return None


def reclassify_findings(
    ticker: str, findings: Sequence[QualityFinding]
) -> list[QualityFinding]:
    """Annotate explained findings and keep them from failing the step."""
    result: list[QualityFinding] = []
    for finding in findings:
        explanation = match_explained(ticker, finding.check, finding.dates)
        if explanation is None:
            result.append(finding)
            continue
        details = dict(finding.details)
        details["explained"] = explanation
        result.append(
            finding.model_copy(update={"severity": "warning", "details": details})
        )
    return result


__all__ = [
    "EXPLAINED_FINDINGS",
    "ExplainedFinding",
    "match_explained",
    "reclassify_findings",
]
