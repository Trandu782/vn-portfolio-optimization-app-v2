"""End-to-end smoke test for a deployed VN Portfolio Optimizer (V1.1).

Checks that every live endpoint responds and that the endpoints removed in V1.1
are gone. Run it after a deploy::

    VNOPT_REFRESH_TOKEN=... python scripts/smoke_test.py --api-url https://api.example
    python scripts/smoke_test.py --api-url https://api.example --web-url https://web.example

The refresh token is read from ``--token``, ``VNOPT_REFRESH_TOKEN`` or
``REFRESH_TOKEN``; the optional ``x-vercel-protection-bypass`` secret required by a
Vercel *preview* comes from ``--bypass`` or ``VERCEL_AUTOMATION_BYPASS_SECRET``.
Neither value is ever printed. (The previews for this repo were checked with
``vercel curl``, which injects the same bypass automatically.)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from typing import Any

import httpx

# Five liquid VN30 tickers that always have several years of history.
SAMPLE_TICKERS = ("VNM", "FPT", "ACB", "VIC", "HPG")
# Endpoints deleted in V1.1; each must answer 404.
REMOVED_API_PATHS = ("/api/v1/backtest", "/api/v1/montecarlo")
# Web routes that must load.
WEB_PAGES = ("/portfolio", "/pnl", "/optimize", "/risk", "/rebalance", "/settings")
# Web routes removed in V1.1 (must be a friendly 404 or a redirect).
WEB_REMOVED = ("/universe", "/simulation")
TIMEOUT_SECONDS = 180.0


class Checks:
    """Accumulate pass/fail results and print one line per check."""

    def __init__(self) -> None:
        self.failures = 0

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        """Print the outcome of one check and remember any failure."""
        marker = "PASS" if ok else "FAIL"
        suffix = f" - {detail}" if detail else ""
        print(f"[{marker}] {name}{suffix}")
        if not ok:
            self.failures += 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Smoke test a deployed VN optimizer.")
    parser.add_argument("--api-url", required=True, help="API base URL, e.g. https://api.example")
    parser.add_argument("--web-url", default=None, help="Web app base URL (optional).")
    parser.add_argument("--token", default=None, help="Refresh token for /data/probe.")
    parser.add_argument("--bypass", default=None, help="x-vercel-protection-bypass secret.")
    parser.add_argument("--start", default=None, help="Override start date YYYY-MM-DD.")
    parser.add_argument("--end", default=None, help="Override end date YYYY-MM-DD.")
    return parser.parse_args(argv)


def _headers(args: argparse.Namespace) -> dict[str, str]:
    """Build the shared request headers without ever logging the secrets."""
    token = args.token or os.environ.get("VNOPT_REFRESH_TOKEN") or os.environ.get("REFRESH_TOKEN")
    bypass = args.bypass or os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass
    return headers


def _json(response: httpx.Response) -> dict[str, Any]:
    """Return the JSON object body, or an empty dict when it is not JSON."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _send(
    client: httpx.Client,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Send one request; a transport error is reported and fails the run."""
    try:
        return client.request(method, url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        print(f"[FAIL] {method} {url} - {exc}")
        raise SystemExit(1) from exc


def _run_api(
    client: httpx.Client, checks: Checks, headers: dict[str, str], api: str, start: str, end: str
) -> None:
    """Run every API check."""
    health = _send(client, "GET", f"{api}/api/v1/health", headers)
    checks.record("GET /health", health.status_code == 200, f"HTTP {health.status_code}")

    # The default probe (three tickers, every provider, five years) is heavier
    # than the function limit, so ask for one ticker over one year: it still
    # proves kbs works on the hosted network and finishes quickly.
    probe = _send(client, "GET", f"{api}/api/v1/data/probe?tickers=VNM&years=1", headers)
    kbs_ok = False
    if probe.status_code == 200:
        providers = _json(probe).get("providers", [])
        kbs_ok = any(item.get("provider") == "kbs" and item.get("ok") for item in providers)
    checks.record("GET /data/probe shows kbs working", kbs_ok, f"HTTP {probe.status_code}")

    symbols = _send(client, "GET", f"{api}/api/v1/symbols?q=VNM", headers)
    count = _json(symbols).get("count", 0) if symbols.status_code == 200 else 0
    checks.record(
        "GET /symbols?q=VNM returns results",
        symbols.status_code == 200 and count > 0,
        f"count={count}",
    )

    frontier = _send(
        client, "POST", f"{api}/api/v1/optimize/frontier", headers,
        {
            "symbols": list(SAMPLE_TICKERS), "start": start, "end": end,
            "capital": 100_000_000, "seed": 7, "num_portfolios": 1500,
        },
    )
    body = _json(frontier)
    points = len(body.get("frontier", []))
    marked = bool(body.get("min_variance")) and bool(body.get("tangency"))
    checks.record(
        "POST /optimize/frontier returns frontier + min-variance + max-Sharpe",
        frontier.status_code == 200 and points >= 1 and marked,
        f"HTTP {frontier.status_code} points={points}",
    )

    risk = _send(
        client, "POST", f"{api}/api/v1/risk", headers,
        {
            "symbols": list(SAMPLE_TICKERS),
            "weights": dict.fromkeys(SAMPLE_TICKERS, 0.2),
            "start": start, "end": end, "benchmark": "VNINDEX",
        },
    )
    checks.record(
        "POST /risk returns metrics",
        risk.status_code == 200 and bool(_json(risk).get("metrics")),
        f"HTTP {risk.status_code}",
    )

    pnl = _send(
        client, "POST", f"{api}/api/v1/pnl/evaluate", headers,
        {
            "holdings": [
                {"symbol": "VNM", "shares": 1000, "avg_cost": 70000},
                {"symbol": "FPT", "shares": 500, "avg_cost": 90000},
            ],
            "cash": 50_000_000,
        },
    )
    checks.record(
        "POST /pnl/evaluate returns rows",
        pnl.status_code == 200 and len(_json(pnl).get("holdings", [])) == 2,
        f"HTTP {pnl.status_code}",
    )

    rebalance = _send(
        client, "POST", f"{api}/api/v1/rebalance", headers,
        {
            "holdings": [{"symbol": "VNM", "shares": 1000}, {"symbol": "FPT", "shares": 500}],
            "cash": 50_000_000, "target_weights": {"VNM": 0.5, "FPT": 0.5},
        },
    )
    checks.record(
        "POST /rebalance returns an order plan",
        rebalance.status_code == 200 and isinstance(_json(rebalance).get("orders"), list),
        f"HTTP {rebalance.status_code}",
    )

    for path in REMOVED_API_PATHS:
        removed = _send(client, "POST", f"{api}{path}", headers, {})
        checks.record(
            f"POST {path} is gone (404)",
            removed.status_code == 404,
            f"HTTP {removed.status_code}",
        )


def _run_web(client: httpx.Client, checks: Checks, headers: dict[str, str], web: str) -> None:
    """Run the web-route checks."""
    for page in WEB_PAGES:
        response = _send(client, "GET", f"{web}{page}", headers)
        checks.record(
            f"GET {page} loads", 200 <= response.status_code < 400, f"HTTP {response.status_code}"
        )
    for page in WEB_REMOVED:
        response = _send(client, "GET", f"{web}{page}", headers)
        gone = response.status_code == 404 or 300 <= response.status_code < 400
        checks.record(f"GET {page} is gone (404/redirect)", gone, f"HTTP {response.status_code}")


def main(argv: list[str] | None = None) -> int:
    """Run the smoke test and return a process exit code."""
    args = _parse_args(argv)
    api = args.api_url.rstrip("/")
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=365 * 3)
    headers = _headers(args)
    checks = Checks()
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        _run_api(client, checks, headers, api, start.isoformat(), end.isoformat())
        if args.web_url:
            _run_web(client, checks, headers, args.web_url.rstrip("/"))
    print(f"\n{checks.failures} failure(s)")
    return 1 if checks.failures else 0


if __name__ == "__main__":
    sys.exit(main())
