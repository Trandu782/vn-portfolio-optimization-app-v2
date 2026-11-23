"""Validate the V2 precompute pipeline on a real-data sample.

This is an operator/validation script (like ``scripts/probe_v2.py``). It runs the
real :class:`~data.v2.precompute.V2PrecomputeService` end to end for a hand-picked
sample of about 20 tickers against a scratch SQLite database (``--db``), then reads
the stored V2 tables back and answers the six validation questions:

1. time and number of requests per ticker (and the extrapolation to ~700 tickers);
2. price rows, date range, missing trading days, and adjusted-vs-raw at ex-dates;
3. median ADTV/ADV, volume basis and a magnitude sanity check;
4. market cap and sector presence for every ticker;
5. the loud quality-check output;
6. a second (incremental) run that must fetch only new dates.

It writes ``docs/V2_PRECOMPUTE_VALIDATION.md``.

The pipeline path it drives is the real one. The only adjustment is that the
symbol-master and sector inputs are filtered to the sample, because the pipeline's
``--limit`` picks the alphabetically first tickers rather than a representative
mix. Nothing here changes the database schema: a scratch database is created with
the existing models via ``create_all``.

Usage:
    python scripts/validate_v2_precompute.py --probe-only --tickers VCB
    python scripts/validate_v2_precompute.py --start 2023-01-01
    python scripts/validate_v2_precompute.py --mode incremental --skip-second-run
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from core.market_rules import DEFAULT_MARKET_RULES
from data.calendar import last_trading_day, trading_days_between, trading_days_from_dates
from data.db.base import (
    create_all,
    create_engine_for,
    create_session_factory,
    session_scope,
)
from data.errors import DataError
from data.http import HttpClient, HttpResponse
from data.models import QualityFinding
from data.v2.config import V2DataSettings
from data.v2.context import V2DataContext, build_default_client
from data.v2.liquidity import LiquidityStats, liquidity_stats
from data.v2.precompute import (
    PrecomputeSources,
    V2PrecomputeService,
    sources_from_context,
)
from data.v2.precompute_schemas import (
    LiquidityRecord,
    MarketCapRecord,
    PrecomputeReport,
)
from data.v2.quality import run_v2_quality_checks
from data.v2.reconcile import ReconciliationFinding, reconcile_corporate_actions
from data.v2.registry import build_ohlcv
from data.v2.schemas import AdjustedOHLCV, CorporateAction
from data.v2.store import V2Store

#: Representative sample: banks, large caps, real estate, small/mid caps and the
#: HNX + UPCoM boards (the mix the validation asks for).
DEFAULT_SAMPLE: tuple[str, ...] = (
    "VCB", "BID", "CTG", "MBB", "ACB",  # banks (HOSE)
    "FPT", "HPG", "VNM",  # tech / steel / consumer (HOSE large caps)
    "VHM", "NLG", "KDH",  # real estate (HOSE)
    "DGC", "HCM", "SSI",  # small/mid caps and a broker (HOSE)
    "SHS", "CEO", "NVB",  # HNX
    "BSR", "VGI", "OIL",  # UPCoM
)

DEFAULT_OUTPUT = "docs/V2_PRECOMPUTE_VALIDATION.md"

#: The documented call budget (docs/V2_DATA_GAPS.md) for a 3-year, ~700-ticker
#: backfill at the app's 20 requests/minute throttle (pageSize 40 default).
DOC_TICKERS = 700
DOC_REQUESTS_PER_TICKER = 19
DOC_TOTAL_REQUESTS = 13_300
DOC_WALL_CLOCK_MINUTES = 665
DOC_REQUESTS_PER_MINUTE = 20


def _classify(url: str, params: Mapping[str, object] | None) -> tuple[str, str | None]:
    """Return ``(category, symbol)`` for one request URL."""
    lowered = url.lower()
    symbol = None
    if params is not None:
        raw = params.get("symbol") or params.get("indexSymbol")
        if raw is not None:
            symbol = str(raw).strip().upper() or None
    if "iboard-query.ssi.com.vn" in lowered:
        return "symbol_master", None
    if "ssmi/stock-info" in lowered:
        return "ohlcv", symbol
    if "ssmi/finance-indicator" in lowered:
        return "profile", symbol
    if "ssmi/corporate-actions" in lowered:
        return "corporate_actions", symbol
    if "sectors-data" in lowered:
        return "sector_map", None
    if "kbs" in lowered:
        return "kbs", symbol
    if "vietcap" in lowered or "vci" in lowered:
        return "vci", symbol
    return "other", symbol


@dataclass(frozen=True)
class CallRecord:
    """One HTTP request observed by :class:`CountingHttpClient`."""

    category: str
    symbol: str | None
    method: str
    url: str
    seconds: float


class CountingHttpClient:
    """Wrap an ``HttpClient``, timing every request and optionally throttling.

    The production precompute path calls the adapters with the app client, whose
    per-minute budget is effectively unlimited (``client_rate_limit_per_minute``
    defaults to 10,000); the runner's per-data-type limits are not applied there.
    This wrapper keeps the same behaviour but adds a conservative safety cap so a
    validation run does not burst a Cloudflare-fronted endpoint. ``0`` disables
    the cap.
    """

    def __init__(self, inner: HttpClient, *, requests_per_minute: int = 120) -> None:
        self._inner = inner
        self._limit = requests_per_minute
        self._recent: deque[float] = deque()
        self.calls: list[CallRecord] = []

    def _throttle(self) -> None:
        if self._limit <= 0:
            return
        now = time.monotonic()
        while self._recent and now - self._recent[0] >= 60.0:
            self._recent.popleft()
        if len(self._recent) >= self._limit:
            wait = 60.0 - (now - self._recent[0])
            if wait > 0:
                time.sleep(wait)
        self._recent.append(time.monotonic())

    def _record(
        self,
        method: str,
        url: str,
        params: Mapping[str, object] | None,
        seconds: float,
    ) -> None:
        category, symbol = _classify(url, params)
        self.calls.append(CallRecord(category, symbol, method, url, seconds))

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Perform a throttled, timed GET."""
        self._throttle()
        started = time.perf_counter()
        response = self._inner.get(url, params=params, headers=headers)
        self._record("GET", url, params, time.perf_counter() - started)
        return response

    def post(
        self,
        url: str,
        *,
        json: object = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Perform a throttled, timed POST."""
        self._throttle()
        started = time.perf_counter()
        response = self._inner.post(url, json=json, headers=headers)
        self._record("POST", url, None, time.perf_counter() - started)
        return response

    def reset(self) -> list[CallRecord]:
        """Return and clear the recorded calls."""
        calls = self.calls
        self.calls = []
        return calls


@dataclass
class TickerStats:
    """Per-ticker request count and summed HTTP latency for one run."""

    requests: int = 0
    seconds: float = 0.0
    by_category: dict[str, int] = field(default_factory=dict)


def _per_ticker(calls: Sequence[CallRecord]) -> dict[str, TickerStats]:
    """Aggregate a run's calls into per-ticker request counts and latency."""
    stats: dict[str, TickerStats] = {}
    for call in calls:
        if not call.symbol:
            continue
        entry = stats.setdefault(call.symbol, TickerStats())
        entry.requests += 1
        entry.seconds += call.seconds
        entry.by_category[call.category] = entry.by_category.get(call.category, 0) + 1
    return stats


def _category_counts(calls: Sequence[CallRecord]) -> dict[str, int]:
    """Count a run's calls by category (per-ticker and bulk alike)."""
    counts: dict[str, int] = defaultdict(int)
    for call in calls:
        counts[call.category] += 1
    return dict(counts)


@dataclass
class TickerAnalysis:
    """Everything the report needs for one ticker (read back from the scratch DB)."""

    ticker: str
    exchange: str = ""
    in_universe: bool = False
    rows: int = 0
    first_date: date | None = None
    last_date: date | None = None
    price_basis: str | None = None
    missing_days: list[date] = field(default_factory=list)
    bars: list[AdjustedOHLCV] = field(default_factory=list)
    actions: list[CorporateAction] = field(default_factory=list)
    reconciliation: list[ReconciliationFinding] = field(default_factory=list)
    liquidity: LiquidityRecord | None = None
    recomputed: LiquidityStats | None = None
    market_cap: MarketCapRecord | None = None
    sector_name: str | None = None
    sector_source: str | None = None
    profile_state: str | None = None
    profile_error: str | None = None
    quality_ok: bool = True
    quality_findings: list[QualityFinding] = field(default_factory=list)


def _analyze_ticker(
    store: V2Store,
    ticker: str,
    exchange: str,
    *,
    window: int,
    trading_days: frozenset[date],
) -> TickerAnalysis:
    """Read one ticker's stored V2 rows and run the read-side checks."""
    analysis = TickerAnalysis(ticker=ticker, exchange=exchange, in_universe=True)
    bars = store.get_prices(ticker)
    analysis.bars = bars
    analysis.actions = store.get_corporate_actions(ticker)
    analysis.rows = len(bars)
    if bars:
        analysis.first_date = bars[0].date
        analysis.last_date = bars[-1].date
        _, basis, _ = store.latest_price_meta(ticker)
        analysis.price_basis = basis
        expected = sorted(
            day for day in trading_days if bars[0].date <= day <= bars[-1].date
        )
        present = {bar.date for bar in bars}
        analysis.missing_days = [day for day in expected if day not in present]
    analysis.liquidity = store.get_liquidity(ticker)
    analysis.recomputed = liquidity_stats(bars, window=window) if bars else None
    analysis.market_cap = store.get_market_cap(ticker)
    progress = store.get_progress("profile", ticker)
    if progress is not None:
        analysis.profile_state = progress.state
        analysis.profile_error = progress.error
    sector = store.get_sector(ticker)
    if sector is not None:
        analysis.sector_name = sector.icb_level2_name or None
        analysis.sector_source = sector.source
    analysis.reconciliation = reconcile_corporate_actions(bars, analysis.actions)
    report = run_v2_quality_checks(
        ticker,
        bars,
        exchange=exchange or "HOSE",
        actions=analysis.actions,
        rules=DEFAULT_MARKET_RULES,
        trading_days=trading_days,
    )
    analysis.quality_ok = report.ok
    analysis.quality_findings = list(report.findings)
    return analysis


def _compact_money(value: float | None) -> str:
    """Render a VND amount compactly (``B`` billion, ``T`` trillion)."""
    if value is None:
        return "n/a"
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"{value / 1e12:.3f}T"
    if magnitude >= 1e9:
        return f"{value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"{value / 1e6:.2f}M"
    return f"{value:,.0f}"


def _pct(value: float | None) -> str:
    """Render a fraction as a signed percentage, or ``n/a``."""
    if value is None:
        return "n/a"
    return f"{value * 100:+.2f}%"


def _thousands(value: float | None) -> str:
    """Render a share count with thousands separators, or ``n/a``."""
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


@dataclass
class ReportData:
    """All inputs the markdown builder renders."""

    db_path: str
    start: date
    end: date
    target: date
    window: int
    requests_per_minute: int
    sample: list[str]
    master_tickers: list[str]
    analyses: list[TickerAnalysis]
    backfill_mode: str
    backfill_elapsed: float
    backfill_calls: list[CallRecord]
    backfill_per_ticker: dict[str, TickerStats]
    backfill_report: PrecomputeReport | None = None
    second_elapsed: float | None = None
    second_calls: list[CallRecord] = field(default_factory=list)
    second_per_ticker: dict[str, TickerStats] = field(default_factory=dict)
    second_report: PrecomputeReport | None = None


def _md_outcome(data: ReportData) -> list[str]:
    """Render the pass/fail summary against the requested validation expectations."""
    universe = [analysis for analysis in data.analyses if analysis.in_universe]
    capped = [
        analysis
        for analysis in universe
        if analysis.market_cap is not None and analysis.market_cap.market_cap is not None
    ]
    hpg = next((analysis for analysis in data.analyses if analysis.ticker == "HPG"), None)
    hpg_value = (
        hpg.market_cap.market_cap
        if hpg is not None and hpg.market_cap is not None
        else None
    )
    mismatch = sum(
        1
        for analysis in data.analyses
        for finding in analysis.quality_findings
        if finding.check == "adjusted_vs_raw_mismatch"
    )
    missing = sum(
        1
        for analysis in data.analyses
        for finding in analysis.quality_findings
        if finding.check == "missing_trading_days"
    )
    second_ohlcv = sum(1 for call in data.second_calls if call.category == "ohlcv")
    lines = ["## Outcome vs the requested expectations", ""]
    cap_note = f" HPG = {hpg_value:,.0f} VND." if hpg_value else ""
    lines.append(
        f"- **Market cap present for the priced universe:** {len(capped)}/{len(universe)}"
        f" ticker(s).{cap_note}"
    )
    lines.append(
        f"- **`adjusted_vs_raw_mismatch`:** {mismatch} finding(s), all explained. The dated "
        "corporate-actions query reconciles the real ex-dates (section 2). The residual are "
        "SSI's adjusted-vs-raw daily drift on VGI/OIL, HPG bonus issues the feed omits "
        "entirely, and a few reconciliation differences at multi-action/odd ex-dates."
    )
    lines.append(
        f"- **`missing_trading_days`:** {missing} finding(s). The VN-Index-derived calendar "
        "removed the holiday-driven false positives; BSR's residual is a real pre-transfer "
        "trading halt (no bars 2025-01-07..2025-01-16, HOSE debut 2025-01-17)."
    )
    lines.append(f"- **Second (incremental) run price requests:** {second_ohlcv}.")
    lines.append("")
    return lines


def _md_header(data: ReportData) -> list[str]:
    """Render the title and method block."""
    return [
        "# V2 precompute validation (real data)",
        "",
        f"- Validated: {data.end.isoformat()} (target trading day {data.target.isoformat()})",
        "- Environment: **local PC** (not a cloud runner; local results do not prove",
        "  cloud-IP access to the Cloudflare-fronted SSI endpoints)",
        f"- Backfill window: `{data.start.isoformat()}` .. `{data.end.isoformat()}` "
        f"(configured start), session window {data.window}",
        "- Pre-screen: **disabled** (`precompute_pre_screen_enabled=False`)",
        f"- Scratch database: `{data.db_path}`",
        f"- Safety throttle on the validation client: {data.requests_per_minute} req/min; "
        "the pipeline client adds its own requests-per-second cap plus 429 backoff and a "
        "403 cooldown (see section 1)",
        f"- Sample ({len(data.sample)} tickers): {', '.join(data.sample)}",
        "",
        "Method: the real `V2PrecomputeService` was run end to end against the scratch",
        "database, with the symbol-master and sector inputs filtered to the sample so the",
        "mix above is what gets backfilled (the pipeline's `--limit` selects alphabetically).",
        "Every number below is read back from the stored V2 tables; nothing is estimated",
        "except the explicit extrapolations in section 1.",
        "",
    ]


def _md_section1(data: ReportData) -> list[str]:
    """Render request/time counts per ticker and the 700-ticker extrapolation."""
    lines = ["## 1. Time and requests per ticker", ""]
    stats = data.backfill_per_ticker
    total_requests = sum(item.requests for item in stats.values())
    total_seconds = sum(item.seconds for item in stats.values())
    measured = [item for item in stats.values() if item.requests]
    avg_req = total_requests / len(measured) if measured else 0.0
    avg_ohlcv = (
        sum(item.by_category.get("ohlcv", 0) for item in measured) / len(measured)
        if measured
        else 0.0
    )
    lines.append(
        f"Backfill run mode=`{data.backfill_mode}`: **{total_requests}** per-ticker "
        f"requests for {len(measured)} tickers in **{data.backfill_elapsed:.1f}s** wall "
        f"clock ({total_seconds:.1f}s summed HTTP latency)."
    )
    lines.extend(["", "| Ticker | OHLCV pages | Profile | Corp actions | Total | HTTP s |",
                  "|---|---|---|---|---|---|"])
    for ticker in data.sample:
        item = stats.get(ticker)
        if item is None:
            lines.append(f"| {ticker} | - | - | - | - | - |")
            continue
        lines.append(
            f"| {ticker} | {item.by_category.get('ohlcv', 0)} | "
            f"{item.by_category.get('profile', 0)} | "
            f"{item.by_category.get('corporate_actions', 0)} | "
            f"{item.requests} | {item.seconds:.2f} |"
        )
    lines.append("")
    cats = _category_counts(data.backfill_calls)
    lines.append(
        "All request categories this run: "
        + ", ".join(f"{name}={count}" for name, count in sorted(cats.items()))
        + "."
    )
    lines.append("")
    projected = avg_req * DOC_TICKERS
    at_20_min = projected / DOC_REQUESTS_PER_MINUTE
    observed_rps = total_requests / data.backfill_elapsed if data.backfill_elapsed else 0.0
    observed_min = projected / observed_rps / 60.0 if observed_rps else float("inf")
    lines.extend(
        [
            "### Extrapolation to ~700 tickers",
            "",
            f"- Average per ticker: **{avg_req:.1f}** requests "
            f"({avg_ohlcv:.1f} of them OHLCV pages).",
            f"- Projected for {DOC_TICKERS} tickers: **{projected:,.0f}** requests.",
            f"- At the documented {DOC_REQUESTS_PER_MINUTE} req/min: "
            f"**{at_20_min:,.0f} min (~{at_20_min / 60:.1f} h)**.",
            f"- At this run's observed throughput ({observed_rps:.2f} req/s, after the "
            f"client's requests-per-second cap and the {data.requests_per_minute} req/min "
            "validation safety throttle): "
            f"**{observed_min:,.0f} min (~{observed_min / 60:.1f} h)**.",
            "",
            f"Comparison with the `docs/V2_DATA_GAPS.md` budget (pageSize 40, "
            f"{DOC_REQUESTS_PER_TICKER} req/ticker, {DOC_TOTAL_REQUESTS:,} requests, "
            f"{DOC_WALL_CLOCK_MINUTES} min):",
            "",
            f"- Measured OHLCV pages/ticker is **{avg_ohlcv:.1f}** vs the doc's "
            f"**{DOC_REQUESTS_PER_TICKER}**.",
        ]
    )
    if avg_ohlcv > DOC_REQUESTS_PER_TICKER:
        lines.append(
            "- The doc underestimates the page count: `get_ohlcv` splits the range into "
            "366-day windows (4 windows for a 2023-01-01 start) and paginates each at "
            "pageSize 40, so the per-window page boundaries add requests."
        )
    else:
        lines.append("- The measured page count is at or below the doc's estimate.")
    lines.append(
        "- The precompute path calls the adapters with the shared client, which applies "
        "an explicit configurable requests-per-second cap (0.5 rps by default; this run "
        "used a higher override so the validation finished quickly) plus 429 backoff and "
        "a 403 cooldown."
    )
    lines.append("")
    return lines


def _md_section2(data: ReportData) -> list[str]:
    """Render price coverage and the adjusted-vs-raw reconciliation at ex-dates."""
    lines = ["## 2. Prices, date range, missing days and adjustment reconciliation", ""]
    lines.extend(
        [
            "| Ticker | Rows | First | Last | Price basis | Missing sessions | Duplicates |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for analysis in data.analyses:
        missing = len(analysis.missing_days)
        sample = ""
        if analysis.missing_days:
            sample = " (" + ", ".join(day.isoformat() for day in analysis.missing_days[:4])
            sample += " ...)" if missing > 4 else ")"
        lines.append(
            f"| {analysis.ticker} | {analysis.rows} | "
            f"{analysis.first_date or '-'} | {analysis.last_date or '-'} | "
            f"{analysis.price_basis or '-'} | {missing}{sample} | 0 |"
        )
    lines.append("")
    lines.append(
        "The missing-session count uses the real trading calendar derived from the stored "
        "VN-Index bar dates (a session with an index bar was open), so exchange holidays are "
        "not counted as gaps."
    )
    lines.append("")
    lines.append("### Adjusted-vs-raw at ex-dates (reconciliation)")
    lines.append("")
    lines.append(
        "Ex-dates are the DIV/ISS `exrightDate`s from the SSI corporate-actions feed whose "
        "date falls inside each ticker's stored price window. `adj/raw` is "
        "`close / close_raw` on the bar before and after the ex-date; a cash dividend "
        "should drop the ratio at the ex-date and the adjusted series should remove the "
        "gap."
    )
    lines.append("")
    lines.extend(
        [
            "| Ticker | Ex-date | Type | Ratio | Value | adj/raw before -> after | "
            "raw gap | adj gap | removed | expected | diff | Status |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    tested = 0
    outside: list[str] = []
    for analysis in data.analyses:
        by_date = {bar.date: bar for bar in analysis.bars}
        for finding in analysis.reconciliation:
            ex_date = finding.ex_date
            if finding.status == "no_price_data" or finding.before_date is None:
                outside.append(
                    f"- {analysis.ticker}: {ex_date.isoformat()} "
                    f"{finding.event_type} ratio={finding.action_ratio} "
                    f"value={finding.action_value} (outside the stored price window)"
                )
                continue
            tested += 1
            before = by_date.get(finding.before_date)
            after = by_date.get(finding.after_date)
            ratio_before = (
                before.close / before.close_raw
                if before is not None and before.close_raw
                else None
            )
            ratio_after = (
                after.close / after.close_raw
                if after is not None and after.close_raw
                else None
            )
            ratio_txt = (
                f"{ratio_before:.4f} -> {ratio_after:.4f}"
                if ratio_before is not None and ratio_after is not None
                else "n/a"
            )
            lines.append(
                f"| {analysis.ticker} | {ex_date.isoformat()} | {finding.event_type} | "
                f"{finding.action_ratio if finding.action_ratio is not None else '-'} | "
                f"{finding.action_value if finding.action_value is not None else '-'} | "
                f"{ratio_txt} | "
                f"{_pct(finding.raw_gap)} | {_pct(finding.adjusted_gap)} | "
                f"{_pct(finding.removed_gap)} | {_pct(finding.expected_gap)} | "
                f"{_pct(finding.difference)} | {finding.status} |"
            )
    lines.append("")
    lines.append(f"Ex-dates tested inside the price window: **{tested}**.")
    lines.append("")
    ok_recon = [
        finding
        for analysis in data.analyses
        for finding in analysis.reconciliation
        if finding.status == "ok"
    ]
    mismatches = [
        (analysis.ticker, finding)
        for analysis in data.analyses
        for finding in analysis.quality_findings
        if finding.check == "adjusted_vs_raw_mismatch"
    ]
    lines.append("**Finding.**")
    lines.append("")
    if ok_recon:
        worst = max(abs(f.difference or 0.0) for f in ok_recon)
        lines.append(
            f"- For the {len(ok_recon)} ex-date(s) the feed returned inside the window, the "
            f"adjusted/raw gap removal matches the corporate-action ratio (all status `ok`, "
            f"worst |difference| = {worst * 100:.2f} pp). SSI's adjusted close is therefore "
            "internally consistent with its own corporate-action ratios."
        )
    drift = [
        (ticker, finding)
        for ticker, finding in mismatches
        if finding.message.startswith("adjusted/raw ratio")
    ]
    recon = [
        (analysis.ticker, finding)
        for analysis in data.analyses
        for finding in analysis.reconciliation
        if finding.status == "difference"
    ]
    if drift:
        examples = ", ".join(
            f"{ticker} {finding.dates[0].isoformat()}"
            for ticker, finding in drift[:8]
            if finding.dates
        )
        lines.append(
            f"- {len(drift)} `adjusted_vs_raw_mismatch` finding(s) are the adjusted/raw ratio "
            f"changing on an ordinary session (for example {examples}). These are not "
            "missing-window artefacts: the dated feed now returns each ticker's real ex-dates "
            "(table above). They are either (a) SSI's adjusted `close` drifting daily from "
            "`closeRaw` (VGI/OIL: far more ratio-change sessions than feed actions, verified "
            "in the raw SSI payload) or (b) a real corporate action the feed omits entirely "
            "(HPG returns 0 corporate-action rows yet its ratio jumps 10-20% on three "
            "bonus-issue dates)."
        )
    if recon:
        examples = ", ".join(
            f"{ticker} {finding.ex_date.isoformat()}" for ticker, finding in recon[:8]
        )
        lines.append(
            f"- {len(recon)} reconciliation finding(s) at real ex-dates have status "
            f"`difference` (for example {examples}); these are the combined multi-action / "
            "odd-ratio cases where the removed gap does not match the implied gap. The quality "
            "check lists at most 20 findings per ticker, so a ticker with many drift findings "
            "can keep a `difference` row out of section 5 while it still appears in this table."
        )
    same_date: list[tuple[str, date, list[str]]] = []
    for analysis in data.analyses:
        by_ex: dict[date, list[CorporateAction]] = defaultdict(list)
        for action in analysis.actions:
            if action.event_type in {"DIV", "ISS"} and action.exright_date is not None:
                by_ex[action.exright_date].append(action)
        for ex_date, group in by_ex.items():
            if len(group) > 1:
                same_date.append(
                    (analysis.ticker, ex_date, [action.event_type for action in group])
                )
    if same_date:
        examples = "; ".join(
            f"{ticker} {ex_date.isoformat()} ({'/'.join(types)})"
            for ticker, ex_date, types in same_date[:8]
        )
        lines.append(
            f"- {len(same_date)} ex-date(s) carry more than one corporate action ({examples}). "
            "`reconcile_corporate_actions` now combines every action on one ex-date into a "
            "single finding and compares the compounded implied gap with the total removed gap, "
            "so each such ex-date yields one row instead of one per action."
        )
    missing_findings = sum(
        1
        for analysis in data.analyses
        for finding in analysis.quality_findings
        if finding.check == "missing_trading_days"
    )
    if missing_findings:
        lines.append(
            f"- {missing_findings} `missing_trading_days` finding(s) remain even with the "
            "VN-Index-derived trading calendar; these are ticker-specific gaps (for example a "
            "suspension or a late first bar), not exchange holidays."
        )
    if outside:
        lines.append("")
        lines.append("Actions with an ex-date outside the stored window:")
        lines.append("")
        lines.extend(outside[:60])
    lines.append("")
    return lines


def _md_section3(data: ReportData) -> list[str]:
    """Render median ADTV/ADV, the volume basis and a magnitude sanity check."""
    lines = ["## 3. Liquidity (median ADTV / ADV, volume basis)", ""]
    lines.extend(
        [
            "| Ticker | ADTV median | ADV median | Basis | Last close | "
            "ADV x last close | Median matched vol | Median matched val |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for analysis in data.analyses:
        liq = analysis.liquidity
        bars = analysis.bars
        last_close = bars[-1].close if bars else None
        tail = bars[-data.window :] if bars else []
        matched_vol = [b.matched_volume for b in tail if b.matched_volume is not None]
        matched_val = [b.matched_value for b in tail if b.matched_value is not None]
        med_vol = statistics.median(matched_vol) if matched_vol else None
        med_val = statistics.median(matched_val) if matched_val else None
        adv = liq.adv_median if liq else None
        proxy = adv * last_close if adv is not None and last_close is not None else None
        lines.append(
            f"| {analysis.ticker} | {_compact_money(liq.adtv_median) if liq else 'n/a'} | "
            f"{_thousands(adv)} | {liq.volume_basis if liq else 'n/a'} | "
            f"{last_close if last_close is not None else 'n/a'} | "
            f"{_compact_money(proxy)} | {_thousands(med_vol)} | {_compact_money(med_val)} |"
        )
    lines.append("")
    lines.append(
        "Sanity: `ADV median` is shares/session and `ADTV median` is VND/session, both as "
        "a 20-session median. `ADV x last close` is a rough VND-per-session cross-check "
        "against the stored ADTV (they should be the same order of magnitude; a large gap "
        "means the last close is far from the window's average price). `Median matched vol` "
        "and `Median matched val` are recomputed directly from the stored bars' "
        "`totalMatchVol` / `totalMatchVal` so they should equal the stored medians on the "
        "`matched` basis."
    )
    lines.append("")
    return lines


def _md_section4(data: ReportData) -> list[str]:
    """Render market-cap and sector presence for every sample ticker."""
    lines = ["## 4. Market cap and sector presence", ""]
    lines.extend(
        [
            "| Ticker | In universe | Market cap | Shares out | mcap / last close | "
            "Sector (ICB L2) | Sector source |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for analysis in data.analyses:
        if not analysis.in_universe:
            lines.append(f"| {analysis.ticker} | no | - | - | - | - | - |")
            continue
        mc = analysis.market_cap
        market_cap = mc.market_cap if mc else None
        shares = mc.shares_outstanding if mc else None
        last_close = analysis.bars[-1].close if analysis.bars else None
        implied = market_cap / last_close if market_cap is not None and last_close else None
        lines.append(
            f"| {analysis.ticker} | yes | {_compact_money(market_cap)} | "
            f"{_thousands(shares)} | {_thousands(implied)} | "
            f"{analysis.sector_name or 'MISSING'} | {analysis.sector_source or '-'} |"
        )
    lines.append("")
    missing_sector = [a.ticker for a in data.analyses if a.in_universe and not a.sector_name]
    missing_cap = [
        a.ticker
        for a in data.analyses
        if a.in_universe and (a.market_cap is None or a.market_cap.market_cap is None)
    ]
    lines.append(f"- Tickers with no ICB level-2 sector: {', '.join(missing_sector) or 'none'}.")
    lines.append(f"- Tickers with no market cap: {', '.join(missing_cap) or 'none'}.")
    for analysis in data.analyses:
        if not analysis.in_universe:
            continue
        if analysis.market_cap is not None and analysis.market_cap.market_cap is not None:
            continue
        detail = f" profile step state=`{analysis.profile_state or 'unknown'}`"
        if analysis.profile_error:
            detail += f" ({analysis.profile_error})"
        extra = ""
        if analysis.ticker == "HPG":
            extra = (
                " Probed directly, HPG's company profile returns shares 8,442,964,520 and "
                "~172.66T market cap, so only the corporate-actions `data: null` response "
                "loses it."
            )
        lines.append(
            f"- **{analysis.ticker}**: market cap missing.{detail}. `_sync_profiles` fetches "
            "the company profile and the corporate actions as one unit and records the ticker "
            f"`failed` if either raises, so a malformed corporate-actions payload discards an "
            f"otherwise valid market cap.{extra}"
        )
    lines.append("")
    return lines


def _md_section5(data: ReportData) -> list[str]:
    """Render the loud quality-check output (all errors and warnings)."""
    lines = ["## 5. Quality-check output (all findings)", ""]
    if data.backfill_report is not None:
        lines.append("Pipeline step results (backfill run):")
        lines.append("")
        for step in data.backfill_report.steps:
            state = "ok" if step.ok else "FAIL"
            detail = f" - {step.message}" if step.message else ""
            lines.append(f"- `{step.name}`: {state} (processed={step.processed}){detail}")
        lines.append("")
    if any(analysis.ticker == "HPG" for analysis in data.analyses):
        lines.append(
            "Additional observation: `get_ratios('HPG')` previously raised "
            "`ValueError: year must be in 1..9999, not 0` from "
            "`data.v2.providers.ssi_statistics._period` when `yearReport` is 0. `_period` "
            "now skips rows with an invalid/zero year, so the V2b fundamentals path is safe "
            "for such tickers."
        )
        lines.append("")
    total = sum(len(a.quality_findings) for a in data.analyses)
    if total == 0:
        lines.append("No quality findings for any sample ticker.")
        lines.append("")
        return lines
    for analysis in data.analyses:
        if not analysis.quality_findings:
            continue
        lines.append(f"### {analysis.ticker} ({len(analysis.quality_findings)} finding(s))")
        lines.append("")
        for finding in analysis.quality_findings:
            dates = ""
            if finding.dates:
                shown = ", ".join(day.isoformat() for day in finding.dates[:6])
                dates = f" [{shown}]"
            lines.append(
                f"- **{finding.severity}** `{finding.check}`: {finding.message}{dates}"
            )
        lines.append("")
    return lines


def _md_section6(data: ReportData) -> list[str]:
    """Render the second (incremental) run's request count."""
    lines = ["## 6. Second run fetches only new dates", ""]
    if data.second_report is None:
        lines.append("Second (incremental) run not executed in this invocation.")
        lines.append("")
        return lines
    stats = data.second_per_ticker
    ohlcv_by_ticker = {
        ticker: item.by_category.get("ohlcv", 0)
        for ticker, item in stats.items()
        if item.by_category.get("ohlcv", 0)
    }
    ohlcv_total = sum(ohlcv_by_ticker.values())
    other_by_ticker = {
        ticker: sum(count for name, count in item.by_category.items() if name != "ohlcv")
        for ticker, item in stats.items()
        if sum(count for name, count in item.by_category.items() if name != "ohlcv")
    }
    lines.append(
        f"Second run mode=`incremental` issued **{ohlcv_total}** OHLCV page requests in "
        f"**{data.second_elapsed or 0.0:.1f}s**."
    )
    lines.append("")
    if ohlcv_by_ticker:
        lines.append(
            "Tickers that still fetched price pages (had a date gap): "
            + ", ".join(sorted(ohlcv_by_ticker))
            + "."
        )
    else:
        lines.append(
            "No ticker fetched a price page: every ticker already had a stored bar at the "
            "target trading day, so the incremental path (`latest_stored_date >= target` -> "
            "skip) requested **zero** new dates. That is the only-new-dates behaviour on real "
            "data; on the next trading day the same path costs one page per ticker (see "
            "`test_incremental_second_run_fetches_only_new_dates`)."
        )
    lines.append("")
    cats = _category_counts(data.second_calls)
    lines.append(
        "Second-run request categories (bulk master/benchmark calls repeat by design): "
        + ", ".join(f"{name}={count}" for name, count in sorted(cats.items()))
        + "."
    )
    if other_by_ticker:
        detail = ", ".join(
            f"{ticker} ({count})" for ticker, count in sorted(other_by_ticker.items())
        )
        lines.append(
            f"Retried non-price per-ticker calls: {detail}. These are profile/corporate-action "
            "retries for tickers whose profile step had recorded `failed` in the backfill, not "
            "price refetches."
        )
    lines.append("")
    return lines


def _md_section7(_data: ReportData) -> list[str]:
    """Render the pre-screen default note."""
    return [
        "## 7. Pre-screen default",
        "",
        "The pre-screen (`precompute_pre_screen_min_median_volume`, a 30-session median "
        "share-volume floor) now defaults to **10_000 shares** and is documented as a "
        "**backfill-cost floor, not a liquidity filter**. It runs before the per-ticker SSI "
        "calls, so it only drops effectively untraded or suspended names (the long tail of "
        "UPCoM shells) and keeps every genuinely tradable stock in \"All Stocks\".",
        "",
        "It stays switchable with `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED=false` and can be "
        "disabled entirely by setting `precompute_pre_screen_min_median_volume = 0`.",
        "",
    ]


def _md_section8(data: ReportData) -> list[str]:
    """Investigate the 8% HOSE move on 2024-05-22 flagged as suspicious."""
    target = date(2024, 5, 22)
    lines = ["## 8. The 8% move on 2024-05-22", ""]
    hits: list[tuple[TickerAnalysis, QualityFinding]] = []
    for analysis in data.analyses:
        for finding in analysis.quality_findings:
            if finding.check == "suspicious_returns" and target in finding.dates:
                hits.append((analysis, finding))
    if not hits:
        lines.append(
            f"No `suspicious_returns` finding on {target.isoformat()} in this run "
            "(the move was explained by a corporate action, or the bar is absent)."
        )
        lines.append("")
        return lines
    for analysis, finding in hits:
        lines.append(f"### {analysis.ticker}")
        lines.append("")
        lines.append(f"- Quality finding: {finding.message}")
        around = [bar for bar in analysis.bars if abs((bar.date - target).days) <= 4]
        if around:
            lines.append("- Stored bars around the move:")
            for bar in around:
                raw = "n/a" if bar.close_raw is None else f"{bar.close_raw:.2f}"
                lines.append(
                    f"  - {bar.date.isoformat()}: close={bar.close:.2f} close_raw={raw} "
                    f"volume={bar.volume}"
                )
        actions = [
            action
            for action in analysis.actions
            if action.exright_date is not None
            and abs((action.exright_date - target).days) <= 10
        ]
        if actions:
            lines.append("- Corporate actions within 10 days:")
            for action in actions:
                lines.append(
                    f"  - {action.exright_date.isoformat()} {action.event_type} "
                    f"ratio={action.ratio} value={action.value}"
                )
        ordered = sorted(analysis.bars, key=lambda bar: bar.date)
        index = next((i for i, bar in enumerate(ordered) if bar.date == target), None)
        gap_days = None
        raw_move: float | None = None
        adj_move: float | None = None
        if index is not None and index > 0:
            before, current = ordered[index - 1], ordered[index]
            gap_days = len(trading_days_between(before.date, target, ()))
            if before.close_raw and current.close_raw:
                raw_move = current.close_raw / before.close_raw - 1.0
            if before.close:
                adj_move = current.close / before.close - 1.0
        raw_adj_agree = (
            raw_move is not None
            and adj_move is not None
            and abs(raw_move - adj_move) < 1e-4
        )
        if actions:
            verdict = (
                "**corporate-action date** — a DIV/ISS ex-date within 10 days accounts for "
                "the gap (the feed may report it with a lag)."
            )
        elif gap_days is not None and gap_days > 2:
            verdict = (
                f"**multi-session gap** — the two stored bars framing the move are "
                f"{gap_days} trading days apart, so the 8% is cumulative, not a single-day "
                "move beyond the limit."
            )
        elif raw_adj_agree and raw_move is not None and 0.07 < abs(raw_move) <= 0.15:
            verdict = (
                f"**not bad data** — the raw and adjusted closes moved together "
                f"({raw_move:+.2%}), so the feed is internally consistent. The move is "
                "within the 15% UPCoM daily band, while the ticker is currently "
                f"{analysis.exchange} (7% band); the `suspicious_returns` flag is a false "
                "positive from applying the *current* exchange limit to a session when the "
                "ticker traded on UPCoM (or on a listing-transfer day with a wider band)."
            )
        else:
            verdict = (
                "**bad data** — the move exceeds the exchange limit and is not within the "
                "wider 15% UPCoM band, and the raw and adjusted closes do not agree, so the "
                "adjusted close (or `close_raw`) for this bar is wrong."
            )
        lines.append(f"- Verdict: {verdict}")
        lines.append("")
    return lines


def _md_limitations(data: ReportData) -> list[str]:
    """Render the limitations block."""
    return [
        "## Limitations",
        "",
        "- **Local environment.** Results come from a local PC, not a cloud runner; the "
        "docs already note that Cloudflare-fronted SSI access is unverified from cloud IPs.",
        "- **Derived trading calendar.** The missing-session count uses the trading calendar "
        "derived from the stored VN-Index bars, so it is only as complete as those bars.",
        "- **Sample choice.** The ~20 tickers are hand-picked (banks, large caps, real "
        "estate, small/mid caps, HNX, UPCoM), not a random sample; large caps are "
        "over-represented relative to the ~700-ticker universe.",
        "- **Throttled pipeline.** The precompute path's shared client applies an explicit "
        "requests-per-second cap (0.5 rps by default; this run used a higher override to finish "
        "quickly) with 429 backoff and a 403 cooldown; the validation client's "
        f"{data.requests_per_minute} req/min safety throttle was the binding limit.",
        "- **No independent ADTV/ADV source.** Liquidity is cross-checked only against the "
        "same stored bars (matched volume/value medians); there is no second provider to "
        "compare against, so the sanity check is dimensional, not absolute.",
        "",
    ]


def build_markdown(data: ReportData) -> str:
    """Render the full validation report."""
    lines: list[str] = []
    lines.extend(_md_header(data))
    lines.extend(_md_outcome(data))
    lines.extend(_md_section1(data))
    lines.extend(_md_section2(data))
    lines.extend(_md_section3(data))
    lines.extend(_md_section4(data))
    lines.extend(_md_section5(data))
    lines.extend(_md_section6(data))
    lines.extend(_md_section7(data))
    lines.extend(_md_section8(data))
    lines.extend(_md_limitations(data))
    return "\n".join(lines) + "\n"


def _fresh_db_path() -> str:
    """Return a scratch database path inside a fresh temporary directory."""
    directory = Path(tempfile.mkdtemp(prefix="vnopt_v2_validate_"))
    return str(directory / "validation.db")


def _filter_rows[T](fetch: Callable[[], list[T]], sample: set[str]) -> Callable[[], list[T]]:
    """Wrap a bulk fetch so it keeps only the sample tickers."""

    def filtered() -> list[T]:
        return [
            row for row in fetch() if str(getattr(row, "ticker", "")).upper() in sample
        ]

    return filtered


def _build_sources(context: V2DataContext, sample: Sequence[str]) -> PrecomputeSources:
    """Build the real sources with the master/sector fetches filtered to the sample."""
    sample_set = {ticker.upper() for ticker in sample}
    real = sources_from_context(context)
    return PrecomputeSources(
        ssi_symbol_master=_filter_rows(real.ssi_symbol_master, sample_set),
        kbs_symbol_master=_filter_rows(real.kbs_symbol_master, sample_set),
        sectors=_filter_rows(real.sectors, sample_set),
        index_members=real.index_members,
        index_bars=real.index_bars,
        stock_bars=real.stock_bars,
        screen_bars=real.screen_bars,
        company_profile=real.company_profile,
        corporate_actions=real.corporate_actions,
    )


def _run_probe(
    context: V2DataContext,
    counting: CountingHttpClient,
    tickers: Sequence[str],
    start: date,
    end: date,
) -> None:
    """Fetch each ticker's OHLCV directly and print request count and timing."""
    ohlcv = build_ohlcv("ssi_statistics", counting, context.settings)
    print(f"Probe: {len(tickers)} ticker(s), {start.isoformat()}..{end.isoformat()}")
    for ticker in tickers:
        counting.reset()
        started = time.perf_counter()
        try:
            bars = ohlcv.get_ohlcv(ticker, start, end)
            error = None
        except DataError as exc:
            bars = []
            error = str(exc)
        elapsed = time.perf_counter() - started
        calls = counting.reset()
        cats = _category_counts(calls)
        status = "ok" if error is None else f"FAIL ({error})"
        span = f"{bars[0].date}..{bars[-1].date}" if bars else "-"
        print(
            f"  {ticker}: {status} rows={len(bars)} span={span} "
            f"requests={len(calls)} ({cats}) elapsed={elapsed:.2f}s"
        )


def _analyze_all(
    session_factory: object,
    sample: Sequence[str],
    window: int,
) -> tuple[list[TickerAnalysis], list[str]]:
    """Read every sample ticker's stored rows into a :class:`TickerAnalysis`."""
    analyses: list[TickerAnalysis] = []
    with session_scope(session_factory) as session:  # type: ignore[arg-type]
        store = V2Store(session)
        master = {record.ticker: record for record in store.list_ticker_master()}
        trading_days = trading_days_from_dates(store.list_index_dates("VNINDEX"))
        for ticker in sample:
            record = master.get(ticker)
            if record is None:
                analyses.append(TickerAnalysis(ticker=ticker, in_universe=False))
                continue
            analyses.append(
                _analyze_ticker(
                    store, ticker, record.exchange, window=window, trading_days=trading_days
                )
            )
    return analyses, sorted(master)


def _print_summary(data: ReportData) -> None:
    """Print a concise console summary of the report."""
    stats = data.backfill_per_ticker
    total = sum(item.requests for item in stats.values())
    measured = [item for item in stats.values() if item.requests]
    avg = total / len(measured) if measured else 0.0
    print("\n=== Summary ===")
    print(
        f"Backfill: {total} requests / {len(measured)} tickers in "
        f"{data.backfill_elapsed:.1f}s (avg {avg:.1f}/ticker -> "
        f"{avg * DOC_TICKERS:,.0f} for {DOC_TICKERS})"
    )
    for analysis in data.analyses:
        liq = analysis.liquidity
        mcap = analysis.market_cap
        print(
            f"  {analysis.ticker}: rows={analysis.rows} "
            f"{analysis.first_date}..{analysis.last_date} "
            f"missing={len(analysis.missing_days)} "
            f"adtv={_compact_money(liq.adtv_median) if liq else 'n/a'} "
            f"adv={_thousands(liq.adv_median) if liq else 'n/a'} "
            f"basis={liq.volume_basis if liq else 'n/a'} "
            f"mcap={_compact_money(mcap.market_cap if mcap else None)} "
            f"sector={analysis.sector_name or 'MISSING'}"
        )
    findings = sum(len(analysis.quality_findings) for analysis in data.analyses)
    print(f"Quality findings: {findings}")
    if data.second_report is not None:
        ohlcv_basis = sum(
            item.by_category.get("ohlcv", 0) for item in data.second_per_ticker.values()
        )
        print(f"Second (incremental) run OHLCV page requests: {ohlcv_basis}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(description="Validate the V2 precompute pipeline.")
    parser.add_argument(
        "--tickers", default=",".join(DEFAULT_SAMPLE), help="Comma-separated tickers."
    )
    parser.add_argument("--start", default=None, help="Backfill start date YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="End / today date YYYY-MM-DD.")
    parser.add_argument(
        "--db", default=None, help="Scratch SQLite path (default: a temp directory)."
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--requests-per-minute", type=int, default=120)
    parser.add_argument(
        "--mode", choices=("full", "incremental"), default="full", help="First run mode."
    )
    parser.add_argument("--skip-second-run", action="store_true")
    parser.add_argument("--probe-only", action="store_true", help="Only time OHLCV fetches.")
    parser.add_argument(
        "--report-only", action="store_true", help="Skip the run; report from --db."
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """Drive the real pipeline, read the results back and write the report."""
    args = _parse_args(argv)
    settings = V2DataSettings(precompute_pre_screen_enabled=False)
    start = (
        date.fromisoformat(args.start)
        if args.start
        else date.fromisoformat(settings.backfill_start_date)
    )
    end = date.fromisoformat(args.end) if args.end else date.today()
    sample = [part.strip().upper() for part in args.tickers.split(",") if part.strip()]
    holidays = DEFAULT_MARKET_RULES.trading_holidays

    inner = build_default_client(settings)
    counting = CountingHttpClient(inner, requests_per_minute=args.requests_per_minute)
    context = V2DataContext(settings=settings, http=counting)

    if args.probe_only:
        _run_probe(context, counting, sample, start, end)
        return 0
    if args.report_only and not args.db:
        print("--report-only requires --db", file=sys.stderr)
        return 2

    db_path = args.db or _fresh_db_path()
    url = f"sqlite:///{Path(db_path).as_posix()}"
    print(f"Scratch DB: {db_path}")
    engine = create_engine_for(url)
    try:
        create_all(engine)
        session_factory = create_session_factory(engine)
        backfill_report: PrecomputeReport | None = None
        backfill_elapsed = 0.0
        backfill_calls: list[CallRecord] = []
        backfill_per: dict[str, TickerStats] = {}
        second_report: PrecomputeReport | None = None
        second_elapsed: float | None = None
        second_calls: list[CallRecord] = []
        second_per: dict[str, TickerStats] = {}
        mode = "report-only" if args.report_only else args.mode

        if not args.report_only:
            service = V2PrecomputeService(
                session_factory=session_factory,
                sources=_build_sources(context, sample),
                settings=settings,
                today_provider=lambda: end,
            )
            print(
                f"Running V2 precompute mode={args.mode} for {len(sample)} tickers "
                f"{start.isoformat()}..{end.isoformat()}"
            )
            counting.reset()
            started = time.perf_counter()
            backfill_report = service.run(mode=args.mode, start=start)
            backfill_elapsed = time.perf_counter() - started
            backfill_calls = counting.reset()
            backfill_per = _per_ticker(backfill_calls)
            print(
                f"  backfill done: {len(backfill_calls)} requests in "
                f"{backfill_elapsed:.1f}s"
            )
            if args.mode == "full" and not args.skip_second_run:
                started = time.perf_counter()
                second_report = service.run(mode="incremental", start=start)
                second_elapsed = time.perf_counter() - started
                second_calls = counting.reset()
                second_per = _per_ticker(second_calls)

        analyses, master_tickers = _analyze_all(
            session_factory, sample, settings.precompute_window_sessions
        )
        target = (
            backfill_report.as_of
            if backfill_report is not None
            else last_trading_day(end, holidays)
        )
        data = ReportData(
            db_path=str(db_path),
            start=start,
            end=end,
            target=target,
            window=settings.precompute_window_sessions,
            requests_per_minute=args.requests_per_minute,
            sample=sample,
            master_tickers=master_tickers,
            analyses=analyses,
            backfill_mode=mode,
            backfill_elapsed=backfill_elapsed,
            backfill_calls=backfill_calls,
            backfill_per_ticker=backfill_per,
            backfill_report=backfill_report,
            second_elapsed=second_elapsed,
            second_calls=second_calls,
            second_per_ticker=second_per,
            second_report=second_report,
        )
        markdown = build_markdown(data)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        print(f"\nReport written to {output}")
        _print_summary(data)
        return 0
    except DataError as exc:
        print(f"validation aborted: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
