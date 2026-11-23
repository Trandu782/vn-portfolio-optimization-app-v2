"""Probe the V2 market-data adapters and write docs/PROVIDER_PROBE.md.

Runnable locally (``python scripts/probe_v2.py``) and from the manual GitHub
Actions workflow (``.github/workflows/probe_v2.yml``). For the sample tickers it
reports, per provider: OHLCV works, whether prices look adjusted (compared with a
KBS reference series), whether volume exposes matched-only separately from
put-through, whether free-float fields exist, and whether ratios work.

Failure policy: on a local PC every failure is reported as "unreachable from this
environment, unverified" and is never called deprecated or blocked. Only the CI
environment may label a 403/auth wall "blocked". Local results do not prove
cloud-IP access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from data.errors import ProviderError
from data.http import HttpClient
from data.v2.config import get_v2_settings
from data.v2.context import build_default_client
from data.v2.interfaces import (
    ConstituentsProvider,
    OHLCVProvider,
    RatiosProvider,
    SectorMapProvider,
)
from data.v2.registry import build_adapter, registered_ids
from data.v2.schemas import AdjustedOHLCV

DEFAULT_TICKERS: tuple[str, ...] = ("VCB", "FPT", "HPG")
INDEX_CODES: tuple[str, ...] = ("VNINDEX", "VN30", "VN100")
CONSTITUENT_CODES: tuple[str, ...] = ("VN30", "VN100", "HOSE", "HNX", "UPCOM")
DEFAULT_OUTPUT = "docs/PROVIDER_PROBE.md"

FREE_FLOAT_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("VCI", "https://trading.vietcap.com.vn/api/company/companyProfile", "symbol"),
    ("TCBS", "https://apipubaws.tcbs.com.vn/stock-insight/v2/company/overview", "ticker"),
)


@dataclass
class CheckRow:
    """One probe observation for a provider/data-type/subject."""

    data_type: str
    provider: str
    subject: str
    ok: bool
    detail: str
    error_type: str | None = None


@dataclass
class ProbeRun:
    """Everything the report needs."""

    generated_at: datetime
    environment: str
    tickers: list[str]
    start: date
    end: date
    rows: list[CheckRow] = field(default_factory=list)


def _resolve_environment(requested: str) -> str:
    """Return ``local`` or ``ci`` from the flag or ``GITHUB_ACTIONS``."""
    if requested in ("local", "ci"):
        return requested
    return "ci" if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" else "local"


def _environment_label(environment: str) -> str:
    return "GitHub Actions runner" if environment == "ci" else "local PC"


def _etype(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return exc.error_type
    return type(exc).__name__


def _failure_text(exc: Exception, environment: str) -> str:
    etype = _etype(exc)
    if environment == "ci" and etype in {"blocked", "auth"}:
        return f"blocked ({etype})"
    return f"unreachable from this environment, unverified ({etype})"


def _max_daily_gap(bars: Sequence[AdjustedOHLCV]) -> float:
    gaps = [
        abs(current.close - previous.close) / previous.close
        for previous, current in pairwise(bars)
        if previous.close
    ]
    return max(gaps, default=0.0)


def _adjustment_inference(
    bars: Sequence[AdjustedOHLCV], reference: dict[date, float]
) -> str:
    """Infer raw vs adjusted by comparing closes with a KBS reference series."""
    if not reference:
        return "unknown (no reference series)"
    ratios = sorted(
        bar.close / ref for bar in bars if (ref := reference.get(bar.date))
    )
    if not ratios:
        return "unknown (no overlapping dates)"
    median = ratios[len(ratios) // 2]
    if abs(median - 1.0) <= 0.02:
        return f"raw (matches reference, ratio {median:.4f})"
    return f"differs from reference (ratio {median:.4f}); possibly adjusted"


def _describe_bars(bars: Sequence[AdjustedOHLCV], reference: dict[date, float]) -> str:
    if not bars:
        return "0 rows"
    matched = any(bar.matched_volume is not None for bar in bars)
    parts = [
        f"{len(bars)} rows",
        f"{bars[0].date}..{bars[-1].date}",
        f"last_close={bars[-1].close:g}",
        f"max_daily_gap={_max_daily_gap(bars):.2%}",
        "matched_volume=yes" if matched else "matched_volume=no (total only)",
        f"adjustment={_adjustment_inference(bars, reference)}",
    ]
    return "; ".join(parts)


def _reference_series(
    adapters: dict[str, Any], tickers: Sequence[str], start: date, end: date
) -> dict[str, dict[date, float]]:
    """Build a KBS close-by-date reference used to infer adjustment."""
    reference: dict[str, dict[date, float]] = {}
    kbs = adapters.get("kbs")
    if isinstance(kbs, OHLCVProvider):
        for ticker in tickers:
            try:
                bars = kbs.get_ohlcv(ticker, start, end)
            except Exception:
                continue
            reference[ticker] = {bar.date: bar.close for bar in bars}
    return reference


def _record(
    run: ProbeRun,
    check: Callable[[], str],
    *,
    data_type: str,
    provider: str,
    subject: str,
) -> None:
    try:
        detail = check()
    except Exception as exc:
        run.rows.append(
            CheckRow(
                data_type,
                provider,
                subject,
                False,
                _failure_text(exc, run.environment),
                _etype(exc),
            )
        )
        return
    run.rows.append(CheckRow(data_type, provider, subject, True, detail, None))


def _check_ohlcv(
    run: ProbeRun,
    provider_id: str,
    adapter: OHLCVProvider,
    ticker: str,
    start: date,
    end: date,
    reference: dict[str, dict[date, float]],
) -> None:
    def check() -> str:
        return _describe_bars(adapter.get_ohlcv(ticker, start, end), reference.get(ticker, {}))

    _record(run, check, data_type="ohlcv", provider=provider_id, subject=ticker)


def _check_index_ohlcv(
    run: ProbeRun, provider_id: str, adapter: OHLCVProvider, index_code: str, start: date, end: date
) -> None:
    def check() -> str:
        return _describe_bars(adapter.get_index_ohlcv(index_code, start, end), {})

    _record(run, check, data_type="index_ohlcv", provider=provider_id, subject=index_code)


def _check_constituents(
    run: ProbeRun, provider_id: str, adapter: ConstituentsProvider, index_code: str
) -> None:
    def check() -> str:
        result = adapter.get_index_constituents(index_code)
        return f"{len(result.members)} members; e.g. {', '.join(result.members[:5])}"

    _record(run, check, data_type="constituents", provider=provider_id, subject=index_code)


def _check_sector(
    run: ProbeRun, provider_id: str, adapter: SectorMapProvider, ticker: str
) -> None:
    def check() -> str:
        mapping = adapter.get_sector_map(ticker)
        return (
            f"icb1={mapping.icb_level1_name or mapping.icb_level1_code}; "
            f"icb2={mapping.icb_level2_name or mapping.icb_level2_code}; "
            f"type={mapping.security_type}"
        )

    _record(run, check, data_type="sector_map", provider=provider_id, subject=ticker)


def _check_ratios(run: ProbeRun, provider_id: str, adapter: RatiosProvider, ticker: str) -> None:
    def check() -> str:
        records = adapter.get_ratios(ticker)
        if not records:
            return "0 periods"
        return f"{len(records)} periods; keys={sorted(records[0].ratios)[:6]}"

    _record(run, check, data_type="ratios", provider=provider_id, subject=ticker)


def _free_float_probe(client: HttpClient, ticker: str) -> str:
    """Best-effort check for free-float fields on candidate company endpoints."""
    notes: list[str] = []
    for name, url, param in FREE_FLOAT_ENDPOINTS:
        try:
            response = client.get(url, params={param: ticker})
        except Exception as exc:
            notes.append(f"{name}: unreachable ({type(exc).__name__})")
            continue
        text = response.text.lower()
        if "freefloat" in text or "free_float" in text or "sharesoutstanding" in text:
            return f"present via {name}"
        if response.status_code == 403 or text.strip().startswith("<"):
            notes.append(f"{name}: blocked/unverified (HTTP {response.status_code})")
        else:
            notes.append(f"{name}: no free-float field (HTTP {response.status_code})")
    return "; ".join(notes) if notes else "not found (unverified)"


def run_probe(
    adapters: dict[str, Any],
    client: HttpClient,
    tickers: Sequence[str],
    start: date,
    end: date,
    environment: str,
) -> ProbeRun:
    """Probe every adapter for every data type and return a report structure."""
    run = ProbeRun(datetime.now(UTC), environment, list(tickers), start, end)
    reference = _reference_series(adapters, tickers, start, end)
    for provider_id, adapter in adapters.items():
        if isinstance(adapter, OHLCVProvider):
            for ticker in tickers:
                _check_ohlcv(run, provider_id, adapter, ticker, start, end, reference)
            for index_code in INDEX_CODES:
                _check_index_ohlcv(run, provider_id, adapter, index_code, start, end)
        if isinstance(adapter, ConstituentsProvider):
            for index_code in CONSTITUENT_CODES:
                _check_constituents(run, provider_id, adapter, index_code)
        if isinstance(adapter, SectorMapProvider):
            for ticker in tickers:
                _check_sector(run, provider_id, adapter, ticker)
        if isinstance(adapter, RatiosProvider):
            for ticker in tickers:
                _check_ratios(run, provider_id, adapter, ticker)
    for ticker in tickers:
        detail = _free_float_probe(client, ticker)
        run.rows.append(
            CheckRow("free_float", "vci/tcbs", ticker, detail.startswith("present"), detail, None)
        )
    return run


def _rows(run: ProbeRun, data_type: str) -> list[CheckRow]:
    return [row for row in run.rows if row.data_type == data_type]


def _ok_providers(rows: Sequence[CheckRow]) -> list[str]:
    return sorted({row.provider for row in rows if row.ok})


def _section10(run: ProbeRun) -> list[tuple[str, str]]:
    """Summarize the six open items from docs/V2_SPEC.md section 10."""
    ohlcv = _rows(run, "ohlcv")
    matched = [row for row in ohlcv if row.ok and "matched_volume=yes" in row.detail]
    adjusted_raw = [
        row for row in ohlcv if row.ok and "adjustment=raw (matches reference" in row.detail
    ]
    ratios = _rows(run, "ratios")
    free = _rows(run, "free_float")
    vn100_history = [
        row
        for row in run.rows
        if row.ok
        and row.subject == "VN100"
        and row.data_type == "index_ohlcv"
        and not row.detail.startswith(("0 rows", "1 rows"))
    ]
    vn100_members = [
        row
        for row in run.rows
        if row.ok and row.subject == "VN100" and row.data_type == "constituents"
    ]
    findings: list[tuple[str, str]] = []
    findings.append(
        (
            "1. Matched-only vs put-through volume",
            "Separate matched_volume exposed by: "
            + ", ".join(sorted({row.provider for row in matched}))
            if matched
            else (
                "No verified OHLCV provider exposes matched-only volume separately; volume is "
                "treated as total and put-through cannot be split out. VCI also returns "
                "accumulatedVolume/accumulatedValue, but matched-only semantics are unconfirmed."
            ),
        )
    )
    findings.append(
        (
            "2. Free-float data without login",
            "Available: " + ", ".join(f"{row.subject} ({row.detail})" for row in free if row.ok)
            if any(row.ok for row in free)
            else "Not verified from this environment: "
            + "; ".join(sorted({row.detail for row in free})),
        )
    )
    findings.append(
        (
            "3. Prices truly adjusted for corporate actions",
            "Raw prices confirmed for: " + ", ".join(sorted({row.provider for row in adjusted_raw}))
            if adjusted_raw
            else "Could not confirm adjustment from this environment.",
        )
    )
    vn100_parts: list[str] = []
    if vn100_history:
        vn100_parts.append(
            "history via " + ", ".join(sorted({row.provider for row in vn100_history}))
        )
    if vn100_members:
        vn100_parts.append(
            "membership via " + ", ".join(sorted({row.provider for row in vn100_members}))
        )
    findings.append(
        (
            "4. VN100 history and VN30/VN100 membership source",
            "; ".join(vn100_parts)
            if vn100_parts
            else "VN100 not verified from this environment.",
        )
    )
    findings.append(
        (
            "5. Full ratio set and TCBS status",
            "Ratios working via: " + ", ".join(_ok_providers(ratios))
            if any(row.ok for row in ratios)
            else (
                "No ratios endpoint verified from this environment (TCBS is Cloudflare-gated; "
                "the KBS/VCI candidates were unreachable)."
            ),
        )
    )
    findings.append(
        (
            "6. Cloud-IP access",
            f"Probe ran on the {_environment_label(run.environment)}. Local results do not prove "
            "access from Vercel/GitHub cloud IPs; re-run the workflow on a GitHub runner.",
        )
    )
    return findings


def _render_console(run: ProbeRun) -> str:
    lines = [
        f"V2 provider probe - {_environment_label(run.environment)} - "
        f"{run.generated_at:%Y-%m-%d %H:%M UTC}",
        f"tickers={run.tickers} range={run.start}..{run.end}",
    ]
    current: tuple[str, str] | None = None
    for row in run.rows:
        group = (row.data_type, row.provider)
        if group != current:
            current = group
            lines.append(f"\n[{row.data_type}] {row.provider}")
        status = "OK  " if row.ok else "FAIL"
        lines.append(f"  {status} {row.subject:10} {row.detail}")
    return "\n".join(lines)


def _group(run: ProbeRun) -> dict[tuple[str, str], list[CheckRow]]:
    groups: dict[tuple[str, str], list[CheckRow]] = {}
    for row in run.rows:
        groups.setdefault((row.data_type, row.provider), []).append(row)
    return groups


def _render_markdown(run: ProbeRun) -> str:
    lines = [
        "# Provider probe (V2 adapter layer)",
        "",
        f"- Generated: {run.generated_at:%Y-%m-%d %H:%M UTC} on the "
        f"{_environment_label(run.environment)}",
        "- Tool: `scripts/probe_v2.py`",
        f"- Tickers: {', '.join(run.tickers)}",
        f"- Range: {run.start} to {run.end}",
        "",
        "> Failures on a local PC are reported as \"unreachable from this environment, "
        "unverified\" and are never marked deprecated or blocked. Local results do not prove "
        "cloud-IP access; re-run the manual workflow on a GitHub Actions runner for cloud results.",
        "",
        "## Summary",
        "",
        "| Data type | Provider | Status |",
        "| --- | --- | --- |",
    ]
    groups = _group(run)
    for (data_type, provider), rows in groups.items():
        ok = sum(1 for row in rows if row.ok)
        lines.append(f"| {data_type} | {provider} | {ok}/{len(rows)} ok |")
    lines.append("")
    for (data_type, provider), rows in groups.items():
        lines.append(f"## {data_type} - {provider}")
        lines.append("")
        lines.append("| Subject | Status | Detail |")
        lines.append("| --- | --- | --- |")
        for row in rows:
            status = "ok" if row.ok else "unverified"
            lines.append(f"| {row.subject} | {status} | {row.detail} |")
        lines.append("")
    lines.append("## Open items (docs/V2_SPEC.md section 10)")
    lines.append("")
    for item, finding in _section10(run):
        lines.append(f"- **{item}**: {finding}")
    lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe the V2 market-data adapters.")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--start", default=None, help="Override start date YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Override end date YYYY-MM-DD.")
    parser.add_argument("--environment", choices=("auto", "local", "ci"), default="auto")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true", help="Also print the raw rows as JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe, print a table and write docs/PROVIDER_PROBE.md."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    environment = _resolve_environment(args.environment)
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = (
        date.fromisoformat(args.start)
        if args.start
        else end - timedelta(days=365 * args.years)
    )
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]

    settings = get_v2_settings()
    client = build_default_client(settings)
    adapters: dict[str, Any] = {
        provider_id: build_adapter(provider_id, client, settings)
        for provider_id in registered_ids()
    }
    run = run_probe(adapters, client, tickers, start, end, environment)

    print(_render_console(run))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(run), encoding="utf-8")
    print(f"\nreport written to {output}")

    if args.json:
        payload = {
            "generated_at": run.generated_at.isoformat(),
            "environment": environment,
            "tickers": run.tickers,
            "start": run.start.isoformat(),
            "end": run.end.isoformat(),
            "rows": [row.__dict__ for row in run.rows],
        }
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())



