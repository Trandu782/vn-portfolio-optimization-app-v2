"""Read-only probe of SSI ``finance-indicator`` for non-financial tickers.

Fetches exactly three responses (one first page per ticker: FPT, HPG, VNM), records
each real response under ``packages/data/tests/fixtures/v2/`` and reports, per ticker:

* the parsed periods and the ``(yearReport, lengthReport, ttmType) -> period/period_type``
  mapping (TTM vs annual vs quarter);
* which keys are populated vs ``null`` in the latest period;
* whether ``npl`` (a bank-only ratio) is absent or null for a non-financial;
* which ``GENERAL_RATIOS`` keys are empty across all three tickers.

Usage (repo root, venv active):

    python scripts/probe_v2_ratios.py

This is a one-off verification tool, not part of the pipeline. It never raises on a
network failure: it records the error next to the fixture and reports "unreachable".
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "data"))
from data.http import DEFAULT_ACCEPT
from data.settings import DEFAULT_USER_AGENT
from data.v2.providers.ssi_statistics import _period, parse_ssi_finance_rows
from data.v2.ratios import GENERAL_RATIOS

TICKERS: tuple[str, ...] = ("FPT", "HPG", "VNM")
URL = "https://iboard-api.ssi.com.vn/statistics/company/ssmi/finance-indicator"
OUT = Path("packages/data/tests/fixtures/v2")
HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": DEFAULT_ACCEPT,
    "Referer": "https://iboard.ssi.com.vn/",
    "Origin": "https://iboard.ssi.com.vn",
}
PAUSE = 0.4


def _save(ticker: str, payload: Any) -> Path:
    """Write a real response to its fixture file (never trims a ratio page)."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ssi_iboard_finance_indicator_{ticker.lower()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _error_path(ticker: str) -> Path:
    return OUT / f"ssi_iboard_finance_indicator_{ticker.lower()}_error.txt"


def _mapping_label(row: dict[str, Any]) -> str:
    """Return the stored ``period / period_type`` for one raw row, using the adapter rule."""
    period, period_type = _period(
        row.get("yearReport"), row.get("lengthReport"), row.get("ttmType")
    )
    return f"{period} / {period_type}" if period is not None else "(skipped)"


def _report(ticker: str, payload: Any) -> dict[str, float | None] | None:
    """Print one ticker's period mapping and key coverage; return its latest general values."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        code = payload.get("code") if isinstance(payload, dict) else "?"
        print(f"[{ticker}] no data list (code={code})")
        return None

    records = parse_ssi_finance_rows(rows, ticker=ticker, provider="ssi_statistics")
    print(f"[{ticker}] {len(rows)} rows -> {len(records)} periods")
    print("  period mapping (raw -> stored):")
    for row in rows:
        raw = (
            f"year={row.get('yearReport')} len={row.get('lengthReport')} "
            f"ttmType={row.get('ttmType')!r}"
        )
        print(f"    {raw:40} -> {_mapping_label(row)}")

    latest = max(records, key=lambda record: (record.period, record.period_type))
    populated = sorted(key for key, value in latest.ratios.items() if value is not None)
    empty = sorted(key for key, value in latest.ratios.items() if value is None)
    empty_general = [key for key in GENERAL_RATIOS if latest.ratios.get(key) is None]
    print(f"  latest period: {latest.period} / {latest.period_type}")
    print(f"    populated ({len(populated)}): {', '.join(populated) or '(none)'}")
    print(f"    null      ({len(empty)}): {', '.join(empty) or '(none)'}")
    print(
        f"    npl key present: {'npl' in latest.ratios}; "
        f"npl value: {latest.ratios.get('npl')!r}"
    )
    print(f"    GENERAL_RATIOS null in latest: {', '.join(empty_general) or '(none)'}")
    return {key: latest.ratios.get(key) for key in GENERAL_RATIOS}


def main() -> int:
    """Probe the three non-financial tickers and print the coverage report."""
    results: dict[str, dict[str, float | None]] = {}
    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        for ticker in TICKERS:
            try:
                response = client.get(
                    URL,
                    params={"symbol": ticker, "page": 1, "pageSize": 20},
                    headers=HEADERS,
                )
            except Exception as exc:
                print(f"[{ticker}] unreachable: {type(exc).__name__}: {str(exc)[:160]}")
                _error_path(ticker).write_text(str(exc), encoding="utf-8")
                continue
            time.sleep(PAUSE)
            content_type = response.headers.get("content-type", "")
            if response.status_code != 200 or "json" not in content_type:
                print(f"[{ticker}] HTTP {response.status_code} {content_type}; not JSON")
                _error_path(ticker).write_text(response.text[:2000], encoding="utf-8")
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                print(f"[{ticker}] invalid JSON: {exc}")
                _error_path(ticker).write_text(response.text[:2000], encoding="utf-8")
                continue
            path = _save(ticker, payload)
            print(f"[{ticker}] fixture written: {path}")
            presence = _report(ticker, payload)
            if presence is not None:
                results[ticker] = presence

    print("\n== shared findings ==")
    if not results:
        print("no ticker was reachable; no fixtures written")
        return 1
    empty_everywhere = [
        key for key in GENERAL_RATIOS if all(values.get(key) is None for values in results.values())
    ]
    print(f"tickers probed: {', '.join(results)}")
    print(
        "GENERAL_RATIOS empty for every probed ticker: "
        + (", ".join(empty_everywhere) if empty_everywhere else "(none)")
    )
    print("npl: see each ticker's 'npl key present' line (absent or null for non-financials)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
