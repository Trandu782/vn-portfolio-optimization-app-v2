"""Probe additional keyless candidate sources for the V2 data gaps.

Runs live, anonymous calls with the *same* ``User-Agent`` + ``Accept`` the app's
``HttpxHttpClient`` sends (``DEFAULT_USER_AGENT`` / ``DEFAULT_ACCEPT``), records the
real responses under ``packages/data/tests/fixtures/v2/`` and prints, per candidate:
status code, content-type, schema, whether one call returns many tickers (bulk),
rate-limit signals and which ``docs/V2_DATA_GAPS.md`` gap (if any) it fills.

Discovery method: the candidate URLs were read out of the providers' own public web
bundle (SSI iBoard's ``_nWOZ_Ql.js``, CafeF/Vietstock page handlers), not guessed. A
candidate that times out or returns HTML is reported as "unreachable from this
environment, unverified" — never "blocked".

Usage:
    python scripts/probe_v2_candidates.py [--out fixtures-dir]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "data"))
from data.http import DEFAULT_ACCEPT
from data.settings import DEFAULT_USER_AGENT

DEFAULT_OUT = Path("packages/data/tests/fixtures/v2")
BASE_HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Accept": DEFAULT_ACCEPT}
SSI_HEADERS = {**BASE_HEADERS, "Referer": "https://iboard.ssi.com.vn/", "Origin": "https://iboard.ssi.com.vn"}
VCI_HEADERS = {**BASE_HEADERS, "Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn"}
PAUSE = 0.3
SSI = "https://iboard-api.ssi.com.vn/statistics"
SSI_STOCK = "https://iboard-query.ssi.com.vn"


@dataclass
class Candidate:
    """One endpoint to probe."""

    key: str
    provider: str
    gap: str
    method: str
    url: str
    params: dict[str, Any] | None = None
    json_body: Any = None
    form_body: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    fixture: str | None = None
    trim_list_key: str | None = None
    trim_limit: int | None = None
    note: str = ""


@dataclass
class Result:
    """One probe observation."""

    candidate: Candidate
    ok: bool
    status: int | None
    content_type: str
    size: int
    schema: str
    bulk: str
    ratelimit: str
    gap_verdict: str
    detail: str = ""


URL_SSI_CORP = f"{SSI}/company/ssmi/corporate-actions"
URL_SSI_RATIOS = f"{SSI}/company/ssmi/finance-indicator"
URL_SSI_STOCK = f"{SSI}/company/ssmi/stock-info"
URL_SSI_HISTORY = f"{SSI}/charts/history"
URL_CAFEF_COMPANY = "https://cafefnew.mediacdn.vn/Search/company.json"
URL_CAFEF_SEARCH = "https://search.cafef.vn/api/searching/v1/Companies/SearchByKeyWord"
URL_CAFEF_ANALYSIS = "https://apiweb.cafef.vn/api/v1/StockPrice/AnalysisReport/smallsreach"
URL_VCI_PROFILE = "https://trading.vietcap.com.vn/api/company/companyProfile"
URL_VCI_RATIOS = "https://trading.vietcap.com.vn/api/financial/ratio"
URL_VCI_CONSTITUENTS = "https://trading.vietcap.com.vn/api/market/index/constituents"
URL_VND_STOCKS = "https://finfo-api.vndirect.com.vn/v4/stocks"
URL_VND_INDUSTRY = "https://finfo-api.vndirect.com.vn/v4/industry"


def _get(key: str, provider: str, gap: str, url: str, **kwargs: Any) -> Candidate:
    """Build a GET candidate (the method is always GET here)."""
    return Candidate(key, provider, gap, "GET", url, **kwargs)


CANDIDATES: list[Candidate] = [
    _get("ssi_sectors", "ssi_iboard", "2 ICB sector map", f"{SSI}/company/sectors-data",
         headers=SSI_HEADERS, fixture="ssi_iboard_sectors_data.json",
         note="bulk industry list (industryName + industryCode + listCompany)"),
    _get("ssi_corporate", "ssi_iboard", "1 corporate actions", URL_SSI_CORP,
         params={"symbol": "VCB", "page": 1, "pageSize": 10}, headers=SSI_HEADERS,
         fixture="ssi_iboard_corporate_actions.json", note="no date filter"),
    _get("ssi_corporate_dated", "ssi_iboard", "1 corporate actions", URL_SSI_CORP,
         params={"symbol": "VCB", "fromDate": "01/01/2026", "toDate": "31/12/2026",
                 "page": 1, "pageSize": 10},
         headers=SSI_HEADERS, fixture="ssi_iboard_corporate_actions_dated.json",
         note="dated window covering the 2026 dividend"),
    _get("ssi_ratios", "ssi_iboard", "4 financial ratios", URL_SSI_RATIOS,
         params={"symbol": "VCB"}, headers=SSI_HEADERS,
         fixture="ssi_iboard_finance_indicator.json",
         note="per-ticker quarterly ratios incl. sharesOutstanding + marketCap"),
    _get("ssi_stock_info", "ssi_iboard", "3 shares / 5 matched volume", URL_SSI_STOCK,
         params={"symbol": "VCB", "fromDate": "01/01/2025", "toDate": "31/12/2025",
                 "page": 1, "pageSize": 10},
         headers=SSI_HEADERS, fixture="ssi_iboard_stock_info.json",
         note="daily OHLC + totalMatchVol/totalDealVol + closePriceAdjusted"),
    _get("ssi_stock_info_page40", "ssi_iboard", "pagination probe", URL_SSI_STOCK,
         params={"symbol": "VCB", "fromDate": "01/01/2025", "toDate": "31/12/2025",
                 "page": 1, "pageSize": 40},
         headers=SSI_HEADERS, note="pageSize=40 (documented default)"),
    _get("ssi_stock_info_page100", "ssi_iboard", "pagination probe", URL_SSI_STOCK,
         params={"symbol": "VCB", "fromDate": "01/01/2025", "toDate": "31/12/2025",
                 "page": 1, "pageSize": 100},
         headers=SSI_HEADERS, note="pageSize=100 (does SSI honor a larger page?)"),
    _get("ssi_stock_info_page500", "ssi_iboard", "pagination probe", URL_SSI_STOCK,
         params={"symbol": "VCB", "fromDate": "01/01/2025", "toDate": "31/12/2025",
                 "page": 1, "pageSize": 500},
         headers=SSI_HEADERS, note="pageSize=500 (does SSI honor a larger page?)"),
    _get("ssi_stock_info_window", "ssi_iboard", "date-window probe", URL_SSI_STOCK,
         params={"symbol": "VCB", "fromDate": "01/01/2025", "toDate": "31/01/2025",
                 "page": 1, "pageSize": 40},
         headers=SSI_HEADERS,
         note="narrow 1-month window; compare paging.total with the full-year probe"),
    _get("ssi_history", "ssi_iboard", "ohlcv (fallback)", URL_SSI_HISTORY,
         params={"symbol": "VCB", "resolution": "D", "from": 1700000000, "to": 1730000000},
         headers=SSI_HEADERS, fixture="ssi_iboard_history.json",
         note="TradingView UDF document"),
    _get("ssi_symbols", "ssi_iboard", "symbol master", f"{SSI_STOCK}/stock/stock-info",
         headers=SSI_HEADERS, fixture="ssi_iboard_stock_info_all.json",
         trim_list_key="data", trim_limit=50, note="bulk list of every listed security"),
    _get("cafef_company", "cafef", "symbol master", URL_CAFEF_COMPANY,
         fixture="cafef_company_sample.json", trim_limit=100,
         note="bulk company directory, no sector/shares fields"),
    _get("cafef_search", "cafef", "symbol search", URL_CAFEF_SEARCH,
         params={"keyword": "VCB"}, fixture="cafef_search_vcb.json",
         note="company search only"),
    _get("cafef_analysis", "cafef", "none", URL_CAFEF_ANALYSIS,
         fixture="cafef_analysis_report.json", note="analysis articles, not ratios"),
    _get("vci_company", "vci", "2/3 sector+shares", URL_VCI_PROFILE,
         params={"symbol": "VCB"}, headers=VCI_HEADERS, fixture="vci_company_profile.json",
         note="candidate from the existing V2 adapter"),
    _get("vci_ratios", "vci", "4 ratios", URL_VCI_RATIOS,
         params={"symbol": "VCB"}, headers=VCI_HEADERS, fixture="vci_financial_ratio.json"),
    _get("vci_constituents", "vci", "index membership", URL_VCI_CONSTITUENTS,
         params={"index": "VN30"}, headers=VCI_HEADERS, fixture="vci_index_constituents.json"),
    _get("vndirect_stocks", "vndirect_finfo", "2/3 sector+shares", URL_VND_STOCKS,
         params={"q": "status:listed", "size": 2}, note="candidate to confirm the host"),
    _get("vndirect_industry", "vndirect_finfo", "2 ICB sector map", URL_VND_INDUSTRY,
         params={"size": 2}),
]

VIETSTOCK_PAGE = "https://finance.vietstock.vn/VCB/tong-quan.htm"
VIETSTOCK_DATA = "https://finance.vietstock.vn/data"
TOKEN_PAT = re.compile(r'name=__RequestVerificationToken[^>]*value=([A-Za-z0-9_\-]+)')


def _schema_summary(payload: Any) -> str:
    """Return a compact description of a decoded payload's shape."""
    if isinstance(payload, list):
        keys = sorted(payload[0].keys()) if payload and isinstance(payload[0], dict) else []
        return f"list[{len(payload)}]" + (f" keys={keys}" if keys else "")
    if isinstance(payload, dict):
        keys = list(payload.keys())
        data = payload.get("data", payload.get("value"))
        paging = payload.get("paging")
        extra = f"; paging={paging}" if isinstance(paging, dict) else ""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return f"dict keys={keys}; data[0] keys={sorted(data[0].keys())}{extra}"
        return f"dict keys={keys}{extra}"
    return type(payload).__name__


def _save(
    out: Path,
    name: str,
    payload: Any,
    *,
    trim_list_key: str | None,
    trim_limit: int | None,
) -> None:
    """Write a fixture, trimming oversized lists to ``trim_limit`` real rows."""
    out.mkdir(parents=True, exist_ok=True)
    if trim_limit is not None:
        if isinstance(payload, list):
            payload = {
                "_truncated": True,
                "_note": f"first {trim_limit} of {len(payload)} real rows",
                "data": payload[:trim_limit],
            }
        elif isinstance(payload, dict) and isinstance(payload.get(trim_list_key or "data"), list):
            key = trim_list_key or "data"
            original = payload[key]
            payload = {**payload, key: original[:trim_limit], "_truncated": True,
                       "_note": f"first {trim_limit} of {len(original)} real rows"}
    (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _verdict(candidate: Candidate, result: Result) -> str:
    """Derive a gap verdict from the live observation."""
    if not result.ok:
        if result.status == 200 and "html" in result.content_type.lower():
            return "reachable but not a JSON API (SPA HTML) — unverified"
        if result.status is None:
            return "unreachable from this environment, unverified"
        return f"HTTP {result.status} but not usable JSON — unverified"
    if candidate.key == "ssi_sectors":
        return "FILLS Gap 2 at ICB level 2 (bulk 19 groups); level 1 not exposed here"
    if candidate.key == "ssi_ratios":
        return "FILLS Gap 4 (ratios) and Gap 3 (sharesOutstanding, marketCap)"
    if candidate.key == "ssi_stock_info":
        return "FILLS Gap 1 (adjusted close vs closeRaw) and Gap 5 (totalMatchVol vs totalDealVol)"
    if candidate.key.startswith("ssi_stock_info_page"):
        requested = (candidate.params or {}).get("pageSize", "?")
        return (
            f"pagination probe: requested pageSize={requested}; larger pages are "
            "honored only if Bulk matches it (see Schema paging)"
        )
    if candidate.key == "ssi_stock_info_window":
        return (
            "date-window probe: compare paging.total with the full-year probe to "
            "confirm fromDate/toDate filtering"
        )
    if candidate.key in {"ssi_corporate", "ssi_corporate_dated"}:
        return "FILLS Gap 1 partially: DIV/ISS events with exrightDate + ratio"
    if candidate.key == "ssi_history":
        return "OHLCV fallback only"
    if candidate.key in {"ssi_symbols", "cafef_company"}:
        return "symbol master only (no sector/shares)"
    if candidate.provider == "vci":
        return "PARTIAL/UNVERIFIED (see detail)"
    return "no gap filled"


def _record(
    candidate: Candidate,
    response: httpx.Response | None,
    error: str | None,
    out: Path,
) -> Result:
    """Turn a response (or error) into a result row and save the fixture."""
    if response is None:
        return Result(candidate, False, None, "", 0, "", "n/a", "n/a",
                      "unreachable from this environment, unverified", error or "")
    ctype = response.headers.get("content-type", "")
    text = response.text
    ratelimit = "; ".join(
        f"{h}={response.headers[h]}"
        for h in ("x-ratelimit-limit", "x-ratelimit-remaining", "retry-after", "cf-ray")
        if h in response.headers
    ) or "no rate-limit headers"
    ok = response.status_code == 200 and "json" in ctype
    payload: Any = None
    detail = ""
    if ok:
        try:
            payload = response.json()
            if candidate.fixture:
                _save(
                    out,
                    candidate.fixture,
                    payload,
                    trim_list_key=candidate.trim_list_key,
                    trim_limit=candidate.trim_limit,
                )
        except Exception as exc:
            ok = False
            detail = f"invalid JSON: {exc}"
    else:
        detail = f"body head: {text[:120].replace(chr(10), ' ')}"
        if candidate.fixture:
            error_path = out / candidate.fixture.replace(".json", "_error.txt")
            error_path.write_text(text[:2000], encoding="utf-8")
    schema = _schema_summary(payload) if payload is not None else (detail or "not JSON")
    data = payload.get("data", payload.get("value")) if isinstance(payload, dict) else payload
    if isinstance(data, list):
        bulk = f"{len(data)} rows (single call)" if len(data) > 1 else "1 row"
    elif isinstance(data, dict):
        bulk = f"object keys={list(data.keys())[:6]}"
    else:
        bulk = "n/a"
    result = Result(
        candidate,
        ok,
        response.status_code,
        ctype,
        len(response.content),
        schema,
        bulk,
        ratelimit,
        "",
        candidate.note,
    )
    result.gap_verdict = _verdict(candidate, result)
    return result


def _run(client: httpx.Client, candidate: Candidate, out: Path) -> Result:
    """Probe one candidate, never raising."""
    headers = {**BASE_HEADERS, **candidate.headers}
    try:
        if candidate.method == "POST":
            if candidate.form_body is not None:
                response = client.post(candidate.url, data=candidate.form_body, headers=headers)
            else:
                response = client.post(candidate.url, json=candidate.json_body, headers=headers)
        else:
            response = client.get(candidate.url, params=candidate.params, headers=headers)
    except Exception as exc:
        return _record(candidate, None, f"{type(exc).__name__}: {str(exc)[:160]}", out)
    time.sleep(PAUSE)
    return _record(candidate, response, None, out)


def _vietstock(client: httpx.Client, out: Path) -> list[Result]:
    """Vietstock data calls need the anonymous page CSRF token + session cookie."""
    try:
        page = client.get(VIETSTOCK_PAGE, headers=BASE_HEADERS)
    except Exception as exc:
        failed = Candidate("vietstock_page", "vietstock", "1/4", "GET", VIETSTOCK_PAGE)
        return [_record(failed, None, type(exc).__name__, out)]
    token_match = TOKEN_PAT.search(page.text)
    token = token_match.group(1) if token_match else None
    results: list[Result] = []
    specs = (
        ("vietstock_finance", "/financeinfo", {"stockCode": "VCB"},
         "vietstock_financeinfo.json"),
        ("vietstock_prices", "/GetStockDeal_EODChart_ByCode",
         {"stockCode": "VCB", "duration": 60}, "vietstock_eod_chart.json"),
    )
    for key, path, body, fixture in specs:
        cand = Candidate(
            key,
            "vietstock",
            "4 ratios / ohlcv",
            "POST",
            VIETSTOCK_DATA + path,
            form_body={**body, "__RequestVerificationToken": token or ""},
            fixture=fixture,
            note=f"page token={'found' if token else 'missing'}",
        )
        results.append(_run(client, cand, out))
    return results


def render(results: list[Result], generated_at: datetime) -> str:
    """Render the probe results as a Markdown report."""
    lines = [
        "# Additional keyless candidate sweep (V2 data gaps)",
        "",
        f"- Generated: {generated_at:%Y-%m-%d %H:%M UTC} from the local PC",
        "- Tool: `scripts/probe_v2_candidates.py`",
        "- Method: anonymous GET/POST with the app's browser `User-Agent` + `Accept`;",
        "  candidate URLs read from the providers' own public web bundles (not guessed).",
        "",
        "| Candidate | Provider | Gap | Status | Bulk | Rate limits | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        cand = result.candidate
        if result.status:
            status = f"{result.status} {result.content_type.split(';')[0]}"
        else:
            status = "error"
        cells = (
            f"`{cand.key}`",
            cand.provider,
            cand.gap,
            status,
            result.bulk,
            result.ratelimit,
            result.gap_verdict,
        )
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Schemas", ""]
    for result in results:
        lines.append(f"### `{result.candidate.key}` — {result.candidate.url}")
        lines.append(f"- Schema: {result.schema}")
        if result.detail:
            lines.append(f"- Note: {result.detail}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run every candidate probe and print the report."""
    parser = argparse.ArgumentParser(description="Probe additional keyless candidate sources.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="fixture output directory")
    args = parser.parse_args(argv)
    out = Path(args.out)
    results: list[Result] = []
    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        for candidate in CANDIDATES:
            result = _run(client, candidate, out)
            results.append(result)
            status = result.status if result.status else "ERR"
            print(f"[{status}] {candidate.key:20} {result.gap_verdict}")
        results.extend(_vietstock(client, out))
        for result in results[-2:]:
            status = result.status if result.status else "ERR"
            print(f"[{status}] {result.candidate.key:20} {result.gap_verdict}")
    print("\n" + render(results, datetime.now(UTC)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
