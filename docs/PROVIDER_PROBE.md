# Provider probe (V2 adapter layer)

- Generated: 2026-11-22 10:29 UTC on the local PC
- Tool: `scripts/probe_v2.py`
- Tickers: VCB, FPT, HPG
- Range: 2024-11-22 to 2026-11-22

> Failures on a local PC are reported as "unreachable from this environment, unverified" and are never marked deprecated or blocked. Local results do not prove cloud-IP access; re-run the manual workflow on a GitHub Actions runner for cloud results.

## Summary

| Data type | Provider | Status |
| --- | --- | --- |
| ohlcv | kbs | 3/3 ok |
| index_ohlcv | kbs | 3/3 ok |
| constituents | kbs | 5/5 ok |
| ratios | kbs | 0/3 ok |
| ohlcv | vci | 3/3 ok |
| index_ohlcv | vci | 3/3 ok |
| constituents | vci | 0/5 ok |
| sector_map | vci | 0/3 ok |
| ratios | vci | 0/3 ok |
| ohlcv | dnse | 0/3 ok |
| index_ohlcv | dnse | 0/3 ok |
| ohlcv | ssi_iboard | 0/3 ok |
| index_ohlcv | ssi_iboard | 0/3 ok |
| ratios | tcbs | 0/3 ok |
| free_float | vci/tcbs | 0/3 ok |

## ohlcv - kbs

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | ok | 496 rows; 2024-11-22..2026-11-20; last_close=50200; max_daily_gap=7.00%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 1.0000) |
| FPT | ok | 496 rows; 2024-11-22..2026-11-20; last_close=45000; max_daily_gap=6.99%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 1.0000) |
| HPG | ok | 496 rows; 2024-11-22..2026-11-20; last_close=20450; max_daily_gap=6.99%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 1.0000) |

## index_ohlcv - kbs

| Subject | Status | Detail |
| --- | --- | --- |
| VNINDEX | ok | 496 rows; 2024-11-22..2026-11-20; last_close=1688.79; max_daily_gap=6.77%; matched_volume=no (total only); adjustment=unknown (no reference series) |
| VN30 | ok | 495 rows; 2024-11-22..2026-11-20; last_close=1786.84; max_daily_gap=6.90%; matched_volume=no (total only); adjustment=unknown (no reference series) |
| VN100 | ok | 1 rows; 2026-11-20..2026-11-20; last_close=1716.84; max_daily_gap=0.00%; matched_volume=no (total only); adjustment=unknown (no reference series) |

## constituents - kbs

| Subject | Status | Detail |
| --- | --- | --- |
| VN30 | ok | 30 members; e.g. ACB, BID, BSR, CTG, FPT |
| VN100 | ok | 100 members; e.g. ACB, ANV, BAF, BID, BMP |
| HOSE | ok | 412 members; e.g. AAA, AAM, AAN, AAT, ABR |
| HNX | ok | 299 members; e.g. ADC, ALT, AMC, AME, AMV |
| UPCOM | ok | 808 members; e.g. A32, AAH, AAS, AAV, ABB |

## ratios - kbs

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (schema) |
| FPT | unverified | unreachable from this environment, unverified (schema) |
| HPG | unverified | unreachable from this environment, unverified (schema) |

## ohlcv - vci

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | ok | 496 rows; 2024-11-22..2026-11-20; last_close=50200; max_daily_gap=7.00%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 0.9990) |
| FPT | ok | 496 rows; 2024-11-22..2026-11-20; last_close=45000; max_daily_gap=6.99%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 0.9997) |
| HPG | ok | 496 rows; 2024-11-22..2026-11-20; last_close=20450; max_daily_gap=6.99%; matched_volume=no (total only); adjustment=raw (matches reference, ratio 1.0002) |

## index_ohlcv - vci

| Subject | Status | Detail |
| --- | --- | --- |
| VNINDEX | ok | 496 rows; 2024-11-22..2026-11-20; last_close=1688.79; max_daily_gap=6.77%; matched_volume=no (total only); adjustment=unknown (no reference series) |
| VN30 | ok | 496 rows; 2024-11-22..2026-11-20; last_close=1786.84; max_daily_gap=6.90%; matched_volume=no (total only); adjustment=unknown (no reference series) |
| VN100 | ok | 496 rows; 2024-11-22..2026-11-20; last_close=1716.84; max_daily_gap=6.84%; matched_volume=no (total only); adjustment=unknown (no reference series) |

## constituents - vci

| Subject | Status | Detail |
| --- | --- | --- |
| VN30 | unverified | unreachable from this environment, unverified (auth) |
| VN100 | unverified | unreachable from this environment, unverified (auth) |
| HOSE | unverified | unreachable from this environment, unverified (auth) |
| HNX | unverified | unreachable from this environment, unverified (auth) |
| UPCOM | unverified | unreachable from this environment, unverified (auth) |

## sector_map - vci

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (auth) |
| FPT | unverified | unreachable from this environment, unverified (auth) |
| HPG | unverified | unreachable from this environment, unverified (auth) |

## ratios - vci

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (auth) |
| FPT | unverified | unreachable from this environment, unverified (auth) |
| HPG | unverified | unreachable from this environment, unverified (auth) |

## ohlcv - dnse

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (auth) |
| FPT | unverified | unreachable from this environment, unverified (auth) |
| HPG | unverified | unreachable from this environment, unverified (auth) |

## index_ohlcv - dnse

| Subject | Status | Detail |
| --- | --- | --- |
| VNINDEX | unverified | unreachable from this environment, unverified (auth) |
| VN30 | unverified | unreachable from this environment, unverified (auth) |
| VN100 | unverified | unreachable from this environment, unverified (auth) |

## ohlcv - ssi_iboard

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (http) |
| FPT | unverified | unreachable from this environment, unverified (http) |
| HPG | unverified | unreachable from this environment, unverified (http) |

## index_ohlcv - ssi_iboard

| Subject | Status | Detail |
| --- | --- | --- |
| VNINDEX | unverified | unreachable from this environment, unverified (http) |
| VN30 | unverified | unreachable from this environment, unverified (http) |
| VN100 | unverified | unreachable from this environment, unverified (http) |

## ratios - tcbs

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | unreachable from this environment, unverified (blocked) |
| FPT | unverified | unreachable from this environment, unverified (blocked) |
| HPG | unverified | unreachable from this environment, unverified (blocked) |

## free_float - vci/tcbs

| Subject | Status | Detail |
| --- | --- | --- |
| VCB | unverified | VCI: blocked/unverified (HTTP 200); TCBS: blocked/unverified (HTTP 403) |
| FPT | unverified | VCI: blocked/unverified (HTTP 200); TCBS: blocked/unverified (HTTP 403) |
| HPG | unverified | VCI: blocked/unverified (HTTP 200); TCBS: blocked/unverified (HTTP 403) |

## Open items (docs/V2_SPEC.md section 10)

- **1. Matched-only vs put-through volume**: No verified OHLCV provider exposes matched-only volume separately; volume is treated as total and put-through cannot be split out. VCI also returns accumulatedVolume/accumulatedValue, but matched-only semantics are unconfirmed.
- **2. Free-float data without login**: Not verified from this environment: VCI: blocked/unverified (HTTP 200); TCBS: blocked/unverified (HTTP 403)
- **3. Prices truly adjusted for corporate actions**: Raw prices confirmed for: kbs, vci
- **4. VN100 history and VN30/VN100 membership source**: history via vci; membership via kbs
- **5. Full ratio set and TCBS status**: No ratios endpoint verified from this environment (TCBS is Cloudflare-gated; the KBS/VCI candidates were unreachable).
- **6. Cloud-IP access**: Probe ran on the local PC. Local results do not prove access from Vercel/GitHub cloud IPs; re-run the workflow on a GitHub runner.

---

## Deep endpoint investigation (manual addendum, 2026-11-22)

Added by hand after the generated report above, to resolve the six open items before
the V2 precompute pipeline. The full analysis and recommendations are in
`docs/V2_DATA_GAPS.md`. All calls were keyless (no API key, login or token) using the
app's browser User-Agent + `Accept: application/json` — KBS rejects a bare `curl`
User-Agent with `400 Request Blocked`. Real responses were recorded under
`packages/data/tests/fixtures/v2/`.

| Provider | Live verdict (2026-11-22) | Notes |
|---|---|---|
| KBS | ✅ reachable | raw OHLCV (`/stocks/{sym}/data_day`), index groups, symbol search (~3,329 rows). No sector/shares/financials; `financial-ratio` is a chart route. |
| VCI | ⚠️ partial | `POST /chart/OHLCChart/gap-chart` works (raw). `companyProfile`, `financial/ratio`, `constituents` return SPA HTML / 400, not JSON. |
| DNSE | ❌ auth-gated | `401 INVALID_TOKEN` / `Unauthorized` on every endpoint. |
| TCBS | ❌ blocked | `404 {"status":404,"message":"Service not found"}` (or a Cloudflare "Just a moment…" challenge). |
| SSI iBoard | ✅ reachable (new query endpoints) | `iboard-api.ssi.com.vn/statistics/*` (sectors, ratios, stock-info, corporate-actions, charts) and `iboard-query.ssi.com.vn/stock/stock-info` answer 200 JSON; the old `/dchart/api/history` is 404. |

Resolution of the six open items (details in `docs/V2_DATA_GAPS.md`):

1. **Matched-only volume** — SSI iBoard `statistics/company/ssmi/stock-info` exposes `totalMatchVol` (matched) vs `totalDealVol` (put-through); otherwise fall back to total `volume` with a UI label.
2. **Free-float / shares / market cap** — SSI `finance-indicator` gives `sharesOutstanding` + `marketCap`; no free-float ratio, so use full market cap and label it.
3. **Adjusted prices** — SSI `stock-info` returns adjusted `close` vs raw `closeRaw`, and `corporate-actions` returns DIV/ISS with `exrightDate` + `ratio`; keep the labelled price-gap heuristic as a fallback.
4. **VN100 history / membership** — KBS constituents verified (`30`, `100` groups); history raw via KBS/VCI (SSI `charts/history` is an additional fallback).
5. **Ratios / TCBS status** — SSI `finance-indicator` gives a full quarterly ratio set; TCBS remains 404/Cloudflare and is not needed.
6. **Cloud-IP access** — re-run `scripts/probe_v2.py` and `scripts/probe_v2_candidates.py` on the GitHub runner; local results do not prove cloud access.

Fixtures recorded: `kbs_data_day_sample.json`, `kbs_search_data_sample.json`,
`kbs_financial_ratio_err.json`, `dnse_unauthorized.json`,
`tcbs_service_not_found_404.json`, `ssi_iboard_404.json`.

## Additional keyless candidate sweep (2026-11-22, later)

Tool: `scripts/probe_v2_candidates.py`. Same browser `User-Agent` + `Accept` as
`HttpxHttpClient`; candidate URLs were read from the providers' own public web
bundles (SSI iBoard `_nWOZ_Ql.js`, CafeF/Vietstock page handlers), not guessed.
Fixtures: `packages/data/tests/fixtures/v2/`.

| Candidate | Endpoint | Status | Bulk | Rate limits | Gap verdict |
|---|---|---|---|---|---|
| SSI sectors | `GET https://iboard-api.ssi.com.vn/statistics/company/sectors-data` | 200 `application/json` | 19 rows (ICB level-2 groups, ~1,975 tickers) | `cf-ray` only | Fills Gap 2 at level 2 |
| SSI corporate actions | `GET .../statistics/company/ssmi/corporate-actions` | 200 `application/json` | 5-10 rows per ticker | `cf-ray` only | Fills Gap 1 partially (DIV/ISS with `exrightDate` + `ratio`) |
| SSI ratios | `GET .../statistics/company/ssmi/finance-indicator` | 200 `application/json` | 20 periods/page (58 for VCB) | `cf-ray` only | Fills Gap 4 + Gap 3 (`sharesOutstanding`, `marketCap`) |
| SSI daily info | `GET .../statistics/company/ssmi/stock-info` | 200 `application/json` | 40 rows/page | `cf-ray` only | Fills Gap 1 (adjusted `close` vs raw `closeRaw`) + Gap 5 (`totalMatchVol` vs `totalDealVol`) |
| SSI history | `GET .../statistics/charts/history` | 200 `application/json` | per ticker | `cf-ray` only | OHLCV fallback |
| SSI symbols | `GET https://iboard-query.ssi.com.vn/stock/stock-info` | 200 `application/json` | 2,171 rows | `cf-ray` only | Symbol master |
| CafeF company | `GET https://cafefnew.mediacdn.vn/Search/company.json` | 200 `application/json` | 3,133 rows | none advertised | None (no sector/shares) |
| CafeF search | `GET https://search.cafef.vn/api/searching/v1/Companies/SearchByKeyWord` | 200 `application/json` | per query | none advertised | None |
| CafeF analysis | `GET https://apiweb.cafef.vn/api/v1/StockPrice/AnalysisReport/smallsreach` | 200 `application/json` | article list | none advertised | None (articles, not ratios) |
| VCI profile/ratios/constituents | `https://trading.vietcap.com.vn/api/...` | 200 `text/html` | n/a | none | Reachable but not a JSON API (SPA shell) — unverified |
| VNDirect finfo | `https://finfo-api.vndirect.com.vn/v4/...` | connect timeout | n/a | n/a | Unreachable from this environment, unverified |
| Vietstock data | `POST https://finance.vietstock.vn/data/...` | 200 empty/non-JSON | n/a | none | Not usable in this test |

Key evidence (real fixtures):

- `ssi_iboard_sectors_data.json`: 19 ICB level-2 groups, e.g. `industryCode` 0500
  Oil & Gas with `industryName.{vi,vn,en}` and `listCompany[].symbol`.
- `ssi_iboard_stock_info.json`: VCB 31/12/2025 adjusted `close` 57,022.75 vs raw
  `closeRaw` 57,500; `totalMatchVol` 2,530,800 vs `totalDealVol` null.
- `ssi_iboard_finance_indicator.json`: VCB Q3 2026 `sharesOutstanding`
  8,355,675,094, `marketCap`, `eps`, `pe`, `pb`, `roe`, `roa`, `roic`, margins,
  `debtEquity`, `currentRatio`, `quickRatio`, `beta`, `dividendYield`, `npl`.
- `ssi_iboard_finance_indicator_{fpt,hpg,vnm}.json`: recorded non-financial pages
  (`scripts/probe_v2_ratios.py`). Interim Q1-Q3 rows carry `ttmType="1"` (TTM), the
  audited full year `lengthReport=5`/`ttmType="0"` (annual) and Q4 `ttmType=null`
  (quarter). Every `GENERAL_RATIOS` key is populated; `npl` is present but `0.0`
  for non-financials, so the general set trims it out.
- `ssi_iboard_corporate_actions.json`: VCB DIV `ratio` 0.045, `exrightDate`
  23/07/2026, `value` 450.
- `cafef_company_sample.json`: 3,133-row directory with only
  `Symbol/Title/RedirectUrl/CenterId/IsVn30/IsHnx30` — no sector or shares.

Findings are folded into `docs/V2_DATA_GAPS.md` (per-gap Update blocks and the
effect table). Local results do not prove cloud-IP access; re-run
`scripts/probe_v2_candidates.py` on the deployed / GitHub runner.
