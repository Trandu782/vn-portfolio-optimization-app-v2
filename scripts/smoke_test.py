"""End-to-end smoke test for a deployed VN Portfolio Optimizer (V1.1).

Checks that every live endpoint responds, that the endpoints removed in V1.1 are
gone, and that the V2 precomputed tables back the Portfolio, Optimize, Sector and
Fundamentals views (the Preview checklist in ``docs/DEPLOYMENT.md``). Run it after
a deploy::

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
import time
from datetime import date, timedelta
from typing import Any

import httpx

# Five liquid VN30 tickers that always have several years of history.
SAMPLE_TICKERS = ("VNM", "FPT", "ACB", "VIC", "HPG")
# The six reference tickers the V2 precompute backfilled end to end (968 adjusted
# bars each), so they are the ones the Portfolio and Optimize spot checks use.
PREVIEW_TICKERS = ("FPT", "HPG", "VHM", "LPB", "PVD", "DCM")
#: Warm-function budget for a V2 read route (the first call after a cold start can
#: exceed it once; re-run to confirm).
V2_LATENCY_BUDGET_SECONDS = 2.0
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


def _timed(
    client: httpx.Client,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[httpx.Response, float]:
    """Send one request and return it together with its elapsed milliseconds."""
    started = time.perf_counter()
    response = _send(client, method, url, headers, body)
    return response, (time.perf_counter() - started) * 1000.0


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

    # Preview checklist (docs/DEPLOYMENT.md): the V2-backed views. These run last so
    # the function is warm and the latency numbers mean something.
    _run_freshness(client, checks, headers, api)
    _run_portfolio(client, checks, headers, api)
    _run_preview_frontier(client, checks, headers, api, start, end)
    _run_v2(client, checks, headers, api)


def _close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    """Return ``True`` when both values are numbers within ``tolerance``."""
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        return False
    return abs(float(left) - float(right)) <= tolerance


def _run_freshness(
    client: httpx.Client, checks: Checks, headers: dict[str, str], api: str
) -> None:
    """Verify /data/freshness reads the Postgres store and owns the latest session."""
    response, elapsed = _timed(client, "GET", f"{api}/api/v1/data/freshness", headers)
    body = _json(response)
    latest = body.get("latest_date")
    primary = body.get("primary")
    checks.record(
        "GET /data/freshness returns the latest stored session and its source",
        response.status_code == 200 and bool(latest) and bool(primary),
        (
            f"HTTP {response.status_code} latest_date={latest} primary={primary} "
            f"stale={body.get('stale')} {elapsed:.0f}ms"
        ),
    )
    checks.record(
        "GET /data/freshness names ssi_statistics as the freshest price source",
        primary == "ssi_statistics",
        f"primary={primary} (expected ssi_statistics once the V2 precompute is current)",
    )


def _run_portfolio(
    client: httpx.Client, checks: Checks, headers: dict[str, str], api: str
) -> None:
    """Verify the Portfolio endpoint values the six V2 reference tickers."""
    request: dict[str, Any] = {
        "holdings": [{"symbol": code, "shares": 100} for code in PREVIEW_TICKERS],
        "cash": 1_000_000,
    }
    response, elapsed = _timed(
        client, "POST", f"{api}/api/v1/portfolio/evaluate", headers, request
    )
    rows = {row.get("symbol"): row for row in _json(response).get("holdings", [])}
    missing = [
        code
        for code in PREVIEW_TICKERS
        if code not in rows or rows[code].get("latest_price") is None
    ]
    checks.record(
        "POST /portfolio/evaluate prices all six V2 reference tickers",
        response.status_code == 200 and not missing,
        f"HTTP {response.status_code} missing={missing or 'none'} {elapsed:.0f}ms",
    )
    flagged = [
        f"{code}: {warning}"
        for code, row in rows.items()
        for warning in row.get("warnings", [])
        if warning.startswith(("stale", "suspended"))
    ]
    checks.record(
        "POST /portfolio/evaluate raises no stale/suspended warning for them",
        response.status_code == 200 and not flagged,
        "; ".join(flagged) or "every bar matches the latest session",
    )


def _run_preview_frontier(
    client: httpx.Client,
    checks: Checks,
    headers: dict[str, str],
    api: str,
    start: str,
    end: str,
) -> None:
    """Verify the Max-Sharpe marker is plotted on the efficient frontier itself.

    ``core.optimize.frontier`` takes the tangency portfolio as the best-Sharpe point
    of the plotted sweep, so its risk/return must match one of the ``frontier``
    entries; a drifting separate solve used to place the marker off the line.
    """
    request: dict[str, Any] = {
        "symbols": list(PREVIEW_TICKERS),
        "start": start,
        "end": end,
        "capital": 100_000_000,
        "seed": 7,
        "num_portfolios": 1500,
    }
    response, elapsed = _timed(
        client, "POST", f"{api}/api/v1/optimize/frontier", headers, request
    )
    body = _json(response)
    frontier = body.get("frontier", [])
    tangency = body.get("tangency") or {}
    on_line = any(
        _close(point.get("volatility"), tangency.get("volatility"))
        and _close(point.get("expected_return"), tangency.get("expected_return"))
        for point in frontier
    )
    checks.record(
        "POST /optimize/frontier keeps the Max-Sharpe marker on the frontier (V2 tickers)",
        response.status_code == 200 and len(frontier) >= 2 and on_line,
        f"HTTP {response.status_code} points={len(frontier)} on_line={on_line} "
        f"{elapsed:.0f}ms",
    )


def _run_v2(client: httpx.Client, checks: Checks, headers: dict[str, str], api: str) -> None:
    """Verify the V2 precomputed routes: HTTP 200, populated, inside the budget."""
    analytics = "/api/v1/v2/analytics?benchmark=VNINDEX&timeframe=1Y"
    paths = (
        "/api/v1/v2/coverage",
        "/api/v1/v2/sectors",
        analytics,
        "/api/v1/v2/fundamentals/FPT",
        analytics,
    )
    warm_elapsed = 0.0
    for index, path in enumerate(paths):
        response, elapsed = _timed(client, "GET", f"{api}{path}", headers)
        body = _json(response)
        detail = f"HTTP {response.status_code} {elapsed:.0f}ms"
        if body.get("data_as_of"):
            detail += f" data_as_of={body['data_as_of']}"
        checks.record(
            f"GET {path.removeprefix('/api/v1')} answers 200 with data",
            response.status_code == 200 and bool(body),
            detail,
        )
        if index == len(paths) - 1:
            warm_elapsed = elapsed
    budget_ms = V2_LATENCY_BUDGET_SECONDS * 1000.0
    checks.record(
        "GET /v2/analytics answers inside the warm latency budget",
        warm_elapsed <= budget_ms,
        f"{warm_elapsed:.0f}ms (budget {budget_ms:.0f}ms)",
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
