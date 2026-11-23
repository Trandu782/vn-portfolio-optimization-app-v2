# VN Portfolio Optimizer: V2 Spec (rev 2)

Status: draft for implementation. V1 is live (Vercel). This document explains **what V2 adds and why**. The Cline prompts are in `V2_CLINE_PROMPTS.md`. Data findings are in `docs/V2_DATA_GAPS.md` and `docs/PROVIDER_PROBE.md`.

## 0. What changed since rev 1

Live keyless probes (local PC, 2026-11-22) showed:
- KBS and VCI return **raw** (unadjusted) prices. No keyless provider among them separates matched volume or gives sectors, market cap or ratios.
- SSI iBoard's `statistics` service is keyless and fills most gaps: adjusted prices, corporate actions, ICB **level 2** sectors (19 groups), shares outstanding and market cap, matched volume, and a quarterly ratio set.
- Still missing: **free-float ratio** and ICB **level 1**.
- DNSE and TCBS are auth-gated or blocked; VNDirect was unreachable from the local PC (unverified).

Consequences for the spec:
- ICB **level 2 only** (19 groups). The level 1/2 toggle is dropped.
- The **free-float** criterion and the minimum free-float ratio are removed. Presets use **full market cap**, labelled as such.
- Sector-index weighting uses **full market cap** (with the optional 15% single-stock cap) or equal weight.
- Matched volume is real (SSI `totalMatchVol`), with a labelled fallback to total volume.
- Fundamentals (V2b) is unblocked, but the ratio set is trimmed to what SSI provides (section 6).
- **Single-source risk:** SSI's `statistics` endpoints are undocumented (found through SSI's public web bundles), sit behind Cloudflare and paginate per ticker. A cloud-IP probe and a call budget are now required before building the pipeline.

## 1. Goals

- Help individual Vietnamese retail investors (up to about 10 billion VND) pick stocks by **sector** and **index membership** (VN30 / VN100) before optimizing.
- Show how sectors have moved against the market, how sensitive they are (beta), and how they correlate.
- Show a ticker's **fundamentals compared with its sector** (mean and median).
- Stay simple: every screen readable by non-financial users; CFA Level 1/2 level metrics only.

## 2. Phasing

| Phase | Contents |
|---|---|
| **V2a-1** | Provider adapters (done: prompt 1), SSI adapters + chains, precompute pipeline, analytics engine, shared state, Optimize filter (index + liquidity + sector) |
| **V2a-2** | Sector Analysis: Market sub-tab |
| **V2b** | Financials pipeline, Fundamentals sub-tab, ticker drawer |

Gate before V2a-1 pipeline work: cloud-IP probe of the SSI endpoints (section 8).

## 3. What is added

### 3.1 Optimize tab: universe filter
- Multi-select **sector** (ICB level 2, 19 groups).
- **Index chips**: VN30, VN100 (AND with sector; VN30 is a subset of VN100).
- **Liquidity preset** (shared with the Sector tab).
- Live counter "N tickers pass"; manual add/remove after filtering.
- Optional constraints: max weight per stock and per sector (for example 30%).
- Sector tag in results, small sector allocation chart.
- Fix V1 bug: the built universe persists across tab switches and reloads.

### 3.2 Sector Analysis tab (new), Market sub-tab
Control header: benchmark (VN-Index default, VN30, VN100), timeframe (1M, 3M, 6M, YTD, 1Y, 3Y, custom), liquidity preset, weighting (full market cap with optional 15% cap, or equal weight).

Components:
1. **Relative Sector Movement chart**: multi-line normalized return (base 0%), benchmark emphasized, legend toggles, labelled axes, tooltips.
2. **Sector Beta & Performance table**: period return, excess return, beta, R², volatility, constituent count; sortable; optional risk/return vs beta scatter.
3. **Cross-Sector Correlation heatmap**: N×N, -1 to +1, hover tooltips, clustered order, average correlation as a diversification indicator.
4. Plain-language captions and "how to read this" tooltips.
5. **"Send sectors to Optimizer"** button.
6. "Data as of", weighting basis, volume basis and price-adjustment basis labels; not-investment-advice disclaimer.

Exclusion handling: the default group-index exclusion is **window-aware** — a ticker is dropped only when a return-corrupting anomaly falls inside the selected window (plus the first return day's source session). The excluded panel shows one plain-language line per ticker (main reason, category, affected-date count) with an expandable detail list, and lists "flagged earlier, not affecting this window" separately; a thin-trading day is labelled as such. A sector with fewer than 3 constituents shows "Too few stocks (needs 3)"; an infeasible single-stock cap is marked "cap off". Chart date ticks are unambiguous ("May 2026", or "20 May" for short windows), the benchmark is "VN-Index" drawn as a dashed grey line, and the scatter/heatmap share the sector colours with a readable neutral stop.


Engine design: the analytics engine works on a pluggable **grouping** (sector, exchange, index bucket), so other groupings can be added without UI changes.

### 3.3 Sector Analysis tab, Fundamentals sub-tab (V2b)
Ticker, period (TTM / annual / quarterly), peer group toggle, scorecard cards (better / similar / worse than sector), detail table (ticker value, sector median, winsorized mean, percentile rank, N), box plot, ticker drawer from Optimize results.

## 4. Liquidity presets

Order-matching volume (SSI `totalMatchVol` / `totalMatchVal`), 20-session **medians**.

| Preset | Portfolio size | Median ADTV | Median ADV | Market cap (full, not free-float) |
|---|---|---|---|---|
| Small Retail | < 1B VND | ≥ 3B VND | ≥ 100,000 sh | ≥ 200B VND |
| **Standard Retail (default)** | [1B, 10B) | ≥ 10B VND | ≥ 150,000 sh | ≥ 500B VND |
| High-Liquidity | ≥ 10B | ≥ 30B VND | ≥ 300,000 sh | ≥ 1,500B VND |
| All Stocks | any | none | none | none |

Notes:
- Thresholds live in config. A free-float criterion is intentionally absent (no keyless free-float source). The market cap filter can admit low-float stocks; ADTV and ADV are the real liquidity guards. State this in the UI.
- Optional helper: user enters portfolio size, app suggests a preset; warn when a position exceeds about 1-2% of median ADTV.
- If a ticker lacks matched volume, fall back to total volume and flag it.

## 5. Methodology (Market sub-tab)

- **Prices**: adjusted. Primary source SSI adjusted `close` (vs `closeRaw`). Do not use SSI `closePriceAdjusted` alone (equal to `close` in tests). Fallbacks: raw prices adjusted with SSI corporate actions, then the price-gap heuristic (labelled "adjusted via a price-gap heuristic"). Validate adjusted vs raw around known ex-dates.
- **Returns**: simple daily returns throughout.
- **Universe**: exclude ETFs, funds, covered warrants, bonds.
- **Constituents**: fixed at the end date ("current-constituents index", labelled). No rolling re-screen in V2. Sector classification is the current one applied to history.
- **Partial history**: exclude stocks with less than about 80% of the window's trading days; renormalize.
- **Minimum constituents**: at least 3 per sector, otherwise greyed out or merged into "Other".
- **Sector index**: full-market-cap weight with optional single-stock cap (default 15%, excess redistributed) or equal weight; quarterly rebalance, cap re-applied each rebalance.
- **Beta** = Cov(R_sector, R_benchmark) / Var(R_benchmark); also R², correlation, annualized volatility, observation count. Do not use SSI's own `beta`.
- **Low-reliability badge** when observations < about 60.
- **Benchmark overlap tooltip**: banks and real estate are a large share of VN30/VN100, so beta against them is mechanically inflated.
- **Correlation**: pairwise Pearson on daily simple returns.
- **Benchmarks**: VN-Index / VN30 / VN100 series from VCI index bars (verified); membership from KBS.

## 6. Methodology (Fundamentals sub-tab)

Source: SSI `finance-indicator` (quarterly, 20 periods per page). Keys seen so far: eps, dilutedEPS, pe, pb, roe, roa, roic, grossProfitMargin, netProfitMargin, debtEquity, debtAsset, currentRatio, quickRatio, dividendYield, npl, marketCap, sharesOutstanding, yearReport, lengthReport.

Trimmed ratio set (confirmed against the VCB fixture: every listed ratio is present and no activity/turnover ratios exist):
- Profitability: gross margin, net margin, ROE, ROA, ROIC
- Solvency: debt/equity, debt/assets
- Liquidity: current ratio, quick ratio
- Valuation: P/E, P/B, dividend yield
- Activity: dropped unless the full key list shows turnover ratios
- Banks: ROE, ROA, NPL, P/E, P/B (NIM, CAR, LDR, CIR not seen)
- Securities: ROE, ROA, P/E, P/B
- Insurance: ROE, ROA, P/E, P/B (safe default: no cost-of-goods margin, no
  working-capital liquidity and no insurance-specific combined ratio in the feed)

Rules:
- Peer group = same ICB level-2 sector. Default all peers; toggle to peers in the active liquidity preset or VN100.
- **Median primary**, mean secondary (winsorized 5th/95th percentile).
- Negative or missing P/E and similar: excluded from stats, shown "n/m". Show peer count N; warn when N < about 5.
- Percentile rank; direction-aware colouring (higher better for ROE, lower better for debt/equity; valuation neutral).
- Verify whether values are quarterly or TTM before comparing; compare peers at the same reporting period; show the period.
- One provider's table for the whole peer set (SSI); store the provider name.
- Banks and securities are only compared with their own group, never with non-financial companies.

## 7. Data sources and failover (subject to the cloud probe)

No API keys, no login, no vnstock. Endpoints are unofficial and can change or block without notice.

| Data type | Primary | Fallback |
|---|---|---|
| Index constituents (VN30, VN100, exchanges) | KBS | VCI (unverified) |
| Index series (VN-Index, VN30, VN100) | VCI | KBS (VN100 history too short) |
| Ticker master / symbol list | KBS search + SSI iboard-query stock-info | – |
| Adjusted daily prices | SSI `stock-info` (`close` vs `closeRaw`) | KBS/VCI raw + SSI corporate actions, then price-gap heuristic |
| Corporate actions | SSI `corporate-actions` | – |
| Matched volume / value | SSI `stock-info` (`totalMatchVol`, `totalMatchVal`) | total volume (labelled) |
| ICB level 2 sectors | SSI `sectors-data` (bulk) | static cited CSV |
| Shares outstanding, market cap | SSI `finance-indicator` | – |
| Ratios | SSI `finance-indicator` | – |

Out of active chains until verified: DNSE (401), TCBS (404/Cloudflare), VNDirect (unreachable here), Vietstock (needs CSRF token), CafeF (no sector or ratio fields).

## 8. Architecture

- **Cloud probe first.** Run `probe_v2.py` and `probe_v2_candidates.py` from the environment that will run the nightly job (GitHub runner or Vercel). Local results only prove access from a home IP; Cloudflare fronts SSI.
- **Call budget.** SSI `stock-info` returns 40 rows per page, so 3Y of daily data is about 19 pages per ticker. For about 700 tickers at 20 requests per minute, a full backfill is about 11 hours. Therefore:
  - pre-screen the universe cheaply (for example KBS volume) before per-ticker SSI calls;
  - backfill in resumable chunks across several scheduled runs, or use KBS raw bulk history plus SSI corporate actions, cross-checked against SSI adjusted prices on a sample;
  - daily updates after the backfill need only 1 page per ticker.
  - The 20 requests/minute is the app's own throttle. Test higher rates carefully and respect the endpoint.
- **Precompute online** (scheduled job): per-ticker adjusted daily returns, matched ADTV/ADV with 20-session medians, market cap, sector map, index membership (with as-of date), ratios (refreshed after reporting deadlines). Idempotent, with retries.
- **Storage**: simplest option compatible with the repo; decision recorded in `docs/DECISIONS.md`.
- **Hosting of jobs**: heavy backfill belongs on a runner (GitHub Actions or similar), not in short serverless functions. If cloud IPs are blocked, fallback is KBS-only data (raw prices + heuristic), with the limits labelled.
- **Shared global state** (preset, universe, timeframe, benchmark) persisted to URL params or localStorage.
- Keep V1 settings: user-set risk-free rate and broker fee.
- Personal-use project: be polite to the endpoints and do not redistribute the data.

## 9. Risks

1. Single-source dependence on SSI for adjusted prices, sectors, market cap, matched volume and ratios. Mitigation: adapter interface, stored snapshots, labelled fallbacks, health checks.
2. Cloudflare may challenge cloud IPs.
3. Per-ticker pagination makes backfill slow.
4. No free-float data: low-float large caps can look more investable than they are.
5. Undocumented endpoints can change schema; contract tests with recorded fixtures catch this.

## 10. Out of scope (V3)

Rolling beta/correlation, relative-rotation charts, rolling liquidity re-screening, ICB level 1, free-float weighting, activity ratios if unavailable, historical valuation trends.

## 11. Open items

1. Cloud-IP access to SSI (GitHub runner / Vercel).
2. Whether SSI `stock-info` supports larger pages or date-window parameters.
3. ~~Full `finance-indicator` key list; whether ratios are quarterly or TTM.~~
   **Resolved:** the recorded VCB fixture exposes the full key list, all spec ratios
   are present (no activity/turnover ratios), and the ratios are **TTM** for interim
   quarters (`ttmType="1"`) and **annual** for the audited full year (`ttmType="0"`).
   The stored set is the general/banks/securities split from section 6.
4. SSI adjustment method (cash dividends and bonus shares) validated against corporate actions.
5. Coverage: SSI sectors-data (~1,975 tickers) vs the cleaned universe.

## 12. Acceptance criteria (high level)

- Optimize filter and Sector tab give the same universe for the same settings; universe persists across tabs and reloads.
- Beta and correlation match an independent pandas check for at least 3 sectors; adjusted-price returns match SSI's adjusted series within tolerance.
- Sector tab loads in a few seconds from precomputed data.
- Every chart has labelled axes and interactivity; every table has a plain-language caption.
- Failover works with the primary provider disabled; labels appear whenever a fallback is used.
- Fundamentals show "n/m" instead of misleading values and never compare financials with non-financials.
