# V2 data gaps and recommended options

- Investigated: 2026-11-22 (live, keyless calls from the local PC)
- Method: direct HTTPS GET/POST with the same browser `User-Agent` + `Accept` headers
  the app's `HttpxHttpClient` sends (`DEFAULT_USER_AGENT` in `data/settings.py`);
  KBS blocks a bare `curl` User-Agent with `400 Request Blocked`, so the browser UA
  is required.
- Recorded responses: `packages/data/tests/fixtures/v2/`
- Scope: keyless only — no API key, login, registered token or `vnstock`. The first
  sweep covered the five V1 providers (KBS, VCI, DNSE, TCBS, SSI iBoard) and every
  endpoint already coded in `packages/data/data/providers/` and
  `packages/data/data/v2/providers/`. A second sweep (see the Update below) tested
  additional public candidates: VNDirect finfo, SSI iBoard's newer query endpoints,
  VCI IQ/insight, and the JSON used by CafeF and Vietstock pages.

This document resolves the six open items from `docs/V2_SPEC.md` §10 before the
precompute pipeline is built. Per data gap it states what was tested, the live
result, the recommended option, and which V2a/V2b feature is affected.

## Provider reachability (live, 2026-11-22)

| Provider | Verdict | Evidence (browser UA, anonymous) |
|---|---|---|
| **KBS** | ✅ reachable | `GET /stocks/VCB/data_day` → **200** JSON `{"symbol","data_day":[{t,o,h,l,c,v}]}` (raw VND); `/index/{group}/stocks` → 200; `/stock/search/data` → 200 JSON array (~3,329 rows) |
| **VCI** | ⚠️ partial | `POST /chart/OHLCChart/gap-chart` → 200 UDF arrays (raw OHLCV); `GET /company/companyProfile`, `/financial/ratio`, `/market/index/constituents` → **200 text/html (SPA shell) / 400** — not JSON APIs |
| **DNSE** | ❌ auth-gated | `price-history` and `index-constituents` → **401** `{"code":"INVALID_TOKEN"}`; `/dnse-order-service/securities` → **401** `{"message":"Unauthorized"}` |
| **TCBS** | ❌ blocked | `company/overview`, `finance/ratio`, `dividend` → **404** `{"status":404,"message":"Service not found"}` (earlier attempts hit a Cloudflare "Just a moment…" challenge) |
| **SSI iBoard** | ✅ reachable (new query endpoints) | `GET https://iboard-api.ssi.com.vn/statistics/company/sectors-data` → 200 JSON; `/statistics/company/ssmi/{finance-indicator,stock-info,corporate-actions}` → 200 JSON; `/statistics/charts/history` → 200 UDF; `https://iboard-query.ssi.com.vn/stock/stock-info` → 200 JSON (2,171 rows). The old `/dchart/api/history` → 404. |
| **VNDirect finfo** | ❌ unreachable from this environment, unverified | `finfo-api.vndirect.com.vn` connect timeout (`WinError 10060`) on the root and `/v4/stocks` |
| **CafeF** | ⚠️ partial | `GET cafefnew.mediacdn.vn/Search/company.json` → 200 JSON (3,133 rows); search and analysis JSON; no sector/shares/ratios fields |
| **Vietstock** | ⚠️ unverified | pages reachable; `POST finance.vietstock.vn/data/GetStockDeal_EODChart_ByCode` → 200 `{"data":[]}`; `POST /data/financeinfo` → 200 non-JSON; needs the page CSRF token |

**Systemic finding (first sweep):** KBS was the only provider that answered
anonymously with a rich, structured payload (OHLCV + index constituents + symbol
list); VCI served OHLCV via POST and the rest was gated or absent.

**Systemic finding (second sweep):** **SSI iBoard's `iboard-api.ssi.com.vn/statistics`
service is keyless and fills four of the five gaps** — adjusted prices, corporate
actions, ICB level-2 sectors, shares/market cap, ratios and matched volume. It
paginates per ticker (`stock-info` 40 rows/page, `finance-indicator` 20 periods/page)
and sits behind Cloudflare (no advertised rate-limit headers). KBS remains the
OHLCV/symbol/constituents backbone; VNDirect finfo was unreachable from here.

## Update — additional keyless candidate sweep (2026-11-22, later)

`scripts/probe_v2_candidates.py` re-tested candidates discovered from the providers'
own public web bundles (not guessed). Fixtures: `packages/data/tests/fixtures/v2/`.

| Endpoint | Status | Bulk? | Fills |
|---|---|---|---|
| `GET .../statistics/company/sectors-data` | 200 JSON | yes: 19 ICB level-2 groups, ~1,975 tickers | Gap 2 (level 2; level 1 not exposed) |
| `GET .../statistics/company/ssmi/corporate-actions` | 200 JSON | per ticker | Gap 1: DIV/ISS events with `exrightDate` + `ratio` (VCB DIV 0.045, ex 23/07/2026) |
| `GET .../statistics/company/ssmi/finance-indicator` | 200 JSON | per ticker, 20 periods/page | Gap 4 (eps, pe, pb, roe, roa, roic, margins, debt/equity, current/quick, beta, dividendYield, npl) + Gap 3 (`sharesOutstanding`, `marketCap`) |
| `GET .../statistics/company/ssmi/stock-info` | 200 JSON | per ticker, 40 rows/page | Gap 1 (`close`/`closePriceAdjusted` vs raw `closeRaw`) + Gap 5 (`totalMatchVol` vs `totalDealVol`) |
| `GET .../statistics/charts/history` | 200 JSON | per ticker | OHLCV fallback (`t,o,h,l,c,v`) |
| `GET iboard-query.ssi.com.vn/stock/stock-info` | 200 JSON | yes: 2,171 rows | symbol master |
| `GET cafefnew.mediacdn.vn/Search/company.json` | 200 JSON | yes: 3,133 rows | none (no sector/shares) |
| VCI `companyProfile` / `financial/ratio` / `constituents` | 200 text/html | n/a | none (SPA shell, not JSON) |
| `finfo-api.vndirect.com.vn/v4/...` | connect timeout | n/a | unreachable from this environment, unverified |
| Vietstock `/data/...` POST | 200 empty/non-JSON | n/a | not usable in this test |

Cloudflare fronts SSI (`cf-ray` present) and no `x-ratelimit-*`/`retry-after`
headers were advertised; the app's client already throttles to 20 req/min.

## Gap 1 — Adjusted prices and corporate actions

**Question:** does any provider/endpoint/parameter return prices adjusted for
dividends, bonus shares and splits, or expose a keyless corporate-actions feed
(ex-dates, ratios)?

**Finding (first sweep):** no. All five return **raw** prices, and no keyless events feed exists.

**Update (second sweep):** SSI iBoard **does** expose adjusted prices and a
corporate-actions feed, keyless:
- `statistics/company/ssmi/stock-info` returns adjusted `open/high/low/close` (equal
  to `closePriceAdjusted`) alongside raw `openRaw/highRaw/lowRaw/closeRaw`. Example
  VCB 31/12/2025: adjusted `close` 57,022.75 vs raw `closeRaw` 57,500 (ratio 0.9917),
  consistent with the 450 VND cash dividend.
- `statistics/company/ssmi/corporate-actions` returns `DIV`/`ISS` events with
  `exrightDate`, `recordDate`, `value` and `ratio` (VCB DIV `ratio` 0.045,
  `exrightDate` 23/07/2026).
- `closePriceAdjusted` on its own is **not** the adjusted series: across 997 rows
  each of FPT/HPG/VCB (2022-2025) it equalled `close`, so use `close` (adjusted) vs
  `closeRaw` (raw), not `closePriceAdjusted` in isolation.

- KBS: every `/stocks/{symbol}/{sub}` path is a technical-chart route, not
  fundamentals. `/stocks/VCB/financial-ratio?timeFrame=data_year` returns
  `{"st":"err","msg":["timeFrame must be one of … data_day, data_week …"]}`; the
  `finance`/`profile`/`company`/`events`/`dividend`/`ratio`/`overview` sub-paths return
  the same error, and `/company/VCB`, `/stock/VCB` are `Cannot GET`.
- VCI: no events/corporate-action endpoint; `financial/ratio` is not JSON.
- TCBS: `dividend` → 404 / Cloudflare.
- DNSE: 401; SSI: 404.

**Recommended option (updated):** prefer SSI's adjusted `close` + corporate-actions
feed for V2a returns/beta. The price-gap heuristic is now implemented as
`data.v2.adjustment.adjust_price_gaps`: it detects a single-day move beyond the
exchange daily limit (HOSE ±7%, HNX ±10%, UPCoM ±15%) and back-adjusts earlier OHLC,
with safeguards (plausible implied factor, skip IPO first day, skip post-suspension
resumptions, per-exchange limits). Keep it as a cross-check/fallback for raw-price
providers (KBS/VCI) and missing ex-dates. It reliably catches large split/bonus gaps
only; small cash-dividend gaps are indistinguishable from normal moves. The UI must
show `HEURISTIC_LABEL` ("adjusted via a price-gap heuristic (not a verified
corporate-action feed)") whenever it is used.

**Affected feature:** V2a returns and beta around ex-dates (methodology §5, "Prices
adjusted for dividends, bonus shares and splits").

**Fixtures:** `kbs_data_day_sample.json` (raw `o/h/l/c/v`, no adjustment field).

## Gap 2 — ICB sector map (level 1 and 2)

**Question:** any keyless, preferably bulk, endpoint mapping ticker → ICB L1/L2?

**Finding (first sweep):** no keyless endpoint returned ICB.

- VCI `company/companyProfile` → 200 text/html SPA shell (or 400), not JSON.
- KBS `/stock/search/data` rows carry only `symbol, nameEn, exchange, re, ceiling,
  floor, type, index, name` — **no sector/industry field**.
- TCBS `company/overview` has ICB fields but is 404 / Cloudflare.
- DNSE 401, SSI 404.

**Update (second sweep):** SSI `statistics/company/sectors-data` returns a **bulk
ICB level-2 map**: 19 groups (e.g. `industryCode` 0500 Oil & Gas) each with
`industryName.{vi,vn,en}` and `listCompany[].symbol` (~1,975 tickers). It does **not**
expose level 1 (a `level`/`industryLevel` query parameter had no effect). Combine it
with `iboard-query.ssi.com.vn/stock/stock-info` (bulk ticker → exchange, 2,171 rows)
to fill `SectorMap.exchange`.

**Recommended option (updated):** use SSI level-2 sectors live; derive level 1 from
the official ICB crosswalk or leave it null. The static loader
`data.v2.static_sector.load_sector_map_csv` still ships for a cited
`data/reference/sector_map.csv` (columns `ticker,icb_level1,icb_level2,source,as_of`)
when a level-1 or fully-cited map is wanted; it validates against the KBS symbol list
and fails loudly on unknown tickers.

**Affected feature:** V2a Optimize sector multi-select; V2a Sector Analysis (the
Market sub-tab is entirely sector-driven).

**Fixtures:** `kbs_search_data_sample.json` (60 real rows showing the fields and the
absent sector).

## Gap 3 — Shares outstanding / free-float / market cap

**Question:** any keyless source for shares outstanding, free-float ratio or market cap?

**Finding (first sweep):** no usable keyless source.

- VCI `company/companyProfile` → not JSON (SPA shell / 400).
- TCBS `company/overview` has `outstandingShare` / `issueShare` / `marketCap` but is
  404 / Cloudflare.
- KBS exposes none of these fields.

**Update (second sweep):** SSI `statistics/company/ssmi/finance-indicator` returns
`sharesOutstanding` and `marketCap` per ticker/period (VCB Q3 2026:
`sharesOutstanding` 8,355,675,094). A **free-float ratio** is still not exposed;
`stock-info` has `foreignCurrentRoom` / `foreignBuyVolMatched` (foreign room), not
free float.

**Recommended option (updated):** use SSI `sharesOutstanding` + `marketCap` for
market-cap weighting; where a free-float ratio is needed, use full market cap and
label it (the `V2_SPEC.md` §5 fallback) rather than inventing a ratio.

**Affected feature:** V2a liquidity presets' free-float-market-cap component; V2a
sector-index weighting (free-float cap weight → equal weight).

**Fixtures:** documented through the VCI/TCBS non-JSON responses above.

## Gap 4 — Financial ratios / statements

**Question:** any keyless source for normalized ratios or raw financial statements?

**Finding (first sweep):** no usable keyless source.

- TCBS `finance/ratio` → 404 / Cloudflare.
- KBS has no fundamentals: the `financial-ratio` path is a chart endpoint (see Gap 1).
- VCI `financial/ratio` → not JSON.
- DNSE 401.

**Update (second sweep):** SSI `statistics/company/ssmi/finance-indicator` returns a
full normalized ratio set per quarter (20 periods/page, 58 total for VCB): `eps`,
`dilutedEPS`, `pe`, `pb`, `roe`, `roa`, `roic`, `grossProfitMargin`,
`netProfitMargin`, `debtEquity`, `debtAsset`, `currentRatio`, `quickRatio`, `beta`,
`dividendYield`, `npl`, `marketCap`, `sharesOutstanding`, plus `yearReport` and
`lengthReport` (quarter).

**Recommended option (updated):** V2b fundamentals are unblocked for tickers SSI
covers; normalize percentages and map `yearReport`/`lengthReport` to `period` +
`period_type`. Keep VCI/KBS as fallbacks.

**Affected feature:** V2b Fundamentals sub-tab, ticker detail drawer, and the TTM /
quarterly pipeline.

**Fixtures:** `kbs_financial_ratio_err.json`, `tcbs_service_not_found_404.json`.

## Gap 5 — Matched-only volume

**Question:** does any endpoint expose order-matching (matched) volume separately
from put-through (negotiated) volume — e.g. an intraday/trade-level feed?

**Finding (first sweep):** no. No daily OHLCV endpoint separated matched from
put-through: KBS/VCI daily `v` is the reported volume, and VCI also returns
`accumulatedVolume` / `accumulatedValue` (still the total). No working
intraday/trade-level endpoint existed (SSI dchart intraday → 404).

**Update (second sweep):** SSI `statistics/company/ssmi/stock-info` separates
`totalMatchVol` / `totalMatchVal` (order-matched) from `totalDealVol` / `totalDealVal`
(put-through/deal); `totalDealVol` is null or 0 when there is no put-through, and
`foreignBuyVolMatched` / `foreignBuyVolDeal` split foreign flow the same way.

**Recommended option (updated):** use `totalMatchVol` as matched-only volume for
ADTV/ADV; fall back to total `volume` with the UI assumption label when a provider
does not expose it.

**Affected feature:** V2a liquidity presets (ADTV/ADV are computed from this volume).

**Fixtures:** `ssi_iboard_404.json` (no intraday source available).

## Fixtures index

All captured 2026-11-22 with the app's browser User-Agent + `Accept: application/json`.

| File | Proves | Capture |
|---|---|---|
| `kbs_data_day_sample.json` | KBS OHLCV is raw `{t,o,h,l,c,v}`, no adjustment field | `GET /stocks/VCB/data_day?sdate=01-12-2024&edate=05-12-2024` |
| `kbs_search_data_sample.json` | KBS symbol schema has no sector/shares (first 60 of 3,329 real rows) | `GET /stock/search/data` |
| `kbs_financial_ratio_err.json` | The "financial-ratio" path is a price-chart route, not fundamentals | `GET /stocks/VCB/financial-ratio?timeFrame=data_year` |
| `dnse_unauthorized.json` | DNSE requires a token | `GET /dnse-financial-products/v1/price-history?…` → 401 |
| `tcbs_service_not_found_404.json` | TCBS endpoints are gone / blocked | `GET /stock-insight/v2/company/overview?ticker=VCB` → 404 |
| `ssi_iboard_404.json` | SSI iBoard chart/intraday gateway not found | `GET /dchart/api/history?…` → 404 |
| `ssi_iboard_sectors_data.json` | SSI bulk ICB level-2 map (19 groups, ~1,975 tickers) | `GET .../statistics/company/sectors-data` |
| `ssi_iboard_corporate_actions.json` | DIV/ISS events with `exrightDate` + `ratio` | `GET .../statistics/company/ssmi/corporate-actions?symbol=VCB` |
| `ssi_iboard_corporate_actions_dated.json` | Same, date-windowed (2026) | `...fromDate=01/01/2026&toDate=31/12/2026` |
| `ssi_iboard_finance_indicator.json` | Full ratio set + `sharesOutstanding` + `marketCap` | `GET .../statistics/company/ssmi/finance-indicator?symbol=VCB` |
| `ssi_iboard_stock_info.json` | Adjusted `close` vs raw `closeRaw`; `totalMatchVol`/`totalDealVol` | `GET .../statistics/company/ssmi/stock-info?symbol=VCB&…` |
| `ssi_iboard_history.json` | OHLCV UDF document | `GET .../statistics/charts/history?symbol=VCB…` |
| `ssi_iboard_stock_info_all.json` | Bulk symbol master (first 50 of 2,171) | `GET iboard-query.ssi.com.vn/stock/stock-info` |
| `cafef_company_sample.json` | CafeF bulk directory (first 100 of 3,133; no sector) | `GET cafefnew.mediacdn.vn/Search/company.json` |
| `cafef_search_vcb.json` | CafeF company search | `GET search.cafef.vn/api/searching/v1/Companies/SearchByKeyWord` |
| `cafef_analysis_report.json` | CafeF analysis articles (not ratios) | `GET apiweb.cafef.vn/api/v1/StockPrice/AnalysisReport/smallsreach` |
| `vietstock_eod_chart.json` | Vietstock EOD call accepted but empty | `POST finance.vietstock.vn/data/GetStockDeal_EODChart_ByCode` |

Existing real fixtures (`kbs_bars.json`, `kbs_vn30.json`, `kbs_hose.json`,
`vci_bars.json`, `vci_index.json`) remain the verified OHLCV/constituents evidence.

## Effect on V2a / V2b

| Feature | Phase | Gaps | Status with the recommended options |
|---|---|---|---|
| Optimize index chips (VN30/VN100) | V2a | — | ✅ unblocked (KBS constituents verified) |
| Optimize sector multi-select (ICB L1/L2) | V2a | 2 | ✅ level 2 live via SSI; level 1 from the ICB crosswalk or the static file |
| Optimize liquidity presets | V2a | 5 (+3) | ✅ matched volume via SSI `totalMatchVol`; free-float ratio absent → market-cap weighting |
| Sector Analysis — Market sub-tab | V2a | 2, 3 (,1) | ✅ level-2 sectors + market cap; level 1 from the crosswalk |
| Returns/beta across ex-dates | V2a | 1 | ✅ SSI adjusted `close` + corporate actions; heuristic as fallback |
| Fundamentals sub-tab + ticker drawer | V2b | 4 | ✅ ratios via SSI `finance-indicator` |

## Rules for any static data file

- A static file is allowed **only** if copied from a real, cited source response or
  file (URL + retrieval date). No values from memory, no invented rows.
- Every static file records `source`, `as_of` and a schema version; the precompute job
  stamps them into the output so the UI can show "data as of".
- Missing market cap / free-float → equal weight (never fabricated).
- Missing sector → the feature is hidden or disabled, never guessed.

## Pagination and 3-year backfill call budget

Open item 2 (does `stock-info` accept larger pages or date windows?) and the
section 8 call budget, resolved against the recorded fixtures:

- **Date-window parameters (`fromDate`/`toDate`, `DD/MM/YYYY`): supported.** The
  recorded `ssi_iboard_stock_info.json` was captured with
  `fromDate=01/01/2025&toDate=31/12/2025&page=1&pageSize=10`, and the response's
  `paging` echoes `{total: 249, page: 1, pageSize: 10}` for VCB's 2025 window.
  `ssi_iboard_corporate_actions_dated.json` proves the same for corporate actions.
- **`page`/`pageSize`: supported.** The response echoes the requested page size.
- **Documented defaults:** `stock-info` 40 rows/page, `finance-indicator` 20
  periods/page, `corporate-actions` 10 rows/page (recorded `paging.pageSize`).
- **Larger page sizes (`pageSize` > 40): UNVERIFIED.** No recorded fixture tested
  more than 10 rows. `scripts/probe_v2_candidates.py` now probes `pageSize` 40,
  100 and 500 (plus a narrow date window) so the GitHub runner can settle it; do
  not assume a larger page works until that cloud run reproduces it.

Call budget for a 3-year backfill of about 700 tickers (~750 trading days each),
at the app's own 20 requests/minute throttle:

| `pageSize` honored | Pages / ticker | Requests (700) | Wall clock @ 20/min |
|---|---|---|---|
| 40 (documented default) | ceil(750 / 40) = 19 | 13,300 | ~665 min, about 11.1 h |
| 100 (unverified) | 8 | 5,600 | ~280 min, about 4.7 h |
| 250 (unverified) | 3 | 2,100 | ~105 min, about 1.75 h |
| 500 (unverified) | 2 | 1,400 | ~70 min, about 1.17 h |

Daily updates after the backfill need one page per ticker: 700 requests, about 35
min at 20/min. The `pageSize` 100/250/500 rows are **estimates that hold only if**
the endpoint honors a larger page; the 40-row default is what the adapter
requests today. Pre-screen the universe (for example KBS volume) before the
per-ticker SSI calls and backfill in resumable chunks, as section 8 requires.

## Next actions

1. **Done:** SSI iBoard's `statistics` service is promoted into the V2 adapter layer
   as provider `ssi_statistics` (adapter `data.v2.providers.ssi_statistics`) and the
   active chains for `ohlcv` (adjusted + matched volume/value), `sector_map` (level
   2), `ratios`, `company_profile`, `corporate_actions` and `symbol_master`; KBS
   stays the constituents/OHLCV backbone. KBS symbols are merged into the SSI
   symbol master by `data.v2.symbols.merge_symbol_master`.
2. Wire `data.v2.adjustment.adjust_price_gaps` for raw-price providers and as a
   cross-check; ship `data.v2.static_sector` for a cited level-1/static map.
   `data.v2.reconcile.reconcile_corporate_actions` reports adjusted-vs-raw ex-date
   differences (SSI's exact adjustment method is still open item 4). The recorded
   fixtures only cover VCB and the price window (Dec 2025) does not span the 2026
   dividend ex-date, and FPT/HPG have no SSI fixtures, so the real reconciliation
   is **unverified** until a cloud run captures matching price/corporate-action
   windows for those tickers.
3. Re-run `scripts/probe_v2.py` and `scripts/probe_v2_candidates.py` on the deployed /
   GitHub runner for cloud-IP confirmation — local results do not prove cloud access.
   The workflow `.github/workflows/probe_v2.yml` now runs both scripts and uploads
   `docs/PROVIDER_PROBE.md` and `docs/V2_CANDIDATES_PROBE.md`.
4. Keep VNDirect finfo, DNSE, TCBS and Vietstock out of the active chains until a
   probe verifies them from the target environment.

