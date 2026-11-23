# V2 precompute validation (real data)

- Validated: 2026-11-22 (target trading day 2026-11-20)
- Environment: **local PC** (not a cloud runner; local results do not prove
  cloud-IP access to the Cloudflare-fronted SSI endpoints)
- Backfill window: `2023-01-01` .. `2026-11-22` (configured start), session window 20
- Pre-screen: **disabled** (`precompute_pre_screen_enabled=False`)
- Scratch database: `C:\Users\PC\AppData\Local\Temp\vnopt_v2_validate_j3ne356v\validation.db`
- Safety throttle on the validation client: 120 req/min; the pipeline client adds its own requests-per-second cap plus 429 backoff and a 403 cooldown (see section 1)
- Sample (20 tickers): VCB, BID, CTG, MBB, ACB, FPT, HPG, VNM, VHM, NLG, KDH, DGC, HCM, SSI, SHS, CEO, NVB, BSR, VGI, OIL

Method: the real `V2PrecomputeService` was run end to end against the scratch
database, with the symbol-master and sector inputs filtered to the sample so the
mix above is what gets backfilled (the pipeline's `--limit` selects alphabetically).
Every number below is read back from the stored V2 tables; nothing is estimated
except the explicit extrapolations in section 1.

## Outcome vs the requested expectations

- **Market cap present for the priced universe:** 20/20 ticker(s). HPG = 172,658,624,434,000 VND.
- **`adjusted_vs_raw_mismatch`:** 51 finding(s), all explained. The dated corporate-actions query reconciles the real ex-dates (section 2). The residual are SSI's adjusted-vs-raw daily drift on VGI/OIL, HPG bonus issues the feed omits entirely, and a few reconciliation differences at multi-action/odd ex-dates.
- **`missing_trading_days`:** 1 finding(s). The VN-Index-derived calendar removed the holiday-driven false positives; BSR's residual is a real pre-transfer trading halt (no bars 2025-01-07..2025-01-16, HOSE debut 2025-01-17).
- **Second (incremental) run price requests:** 0.

## 1. Time and requests per ticker

Backfill run mode=`full`: **686** per-ticker requests for 20 tickers in **346.4s** wall clock (243.6s summed HTTP latency).

| Ticker | OHLCV pages | Profile | Corp actions | Total | HTTP s |
|---|---|---|---|---|---|
| VCB | 27 | 3 | 4 | 34 | 11.88 |
| BID | 27 | 4 | 4 | 35 | 12.18 |
| CTG | 27 | 4 | 4 | 35 | 12.35 |
| MBB | 27 | 4 | 6 | 37 | 13.24 |
| ACB | 27 | 3 | 4 | 34 | 12.30 |
| FPT | 27 | 3 | 4 | 34 | 12.40 |
| HPG | 27 | 3 | 4 | 34 | 11.88 |
| VNM | 27 | 3 | 4 | 34 | 12.24 |
| VHM | 27 | 3 | 4 | 34 | 12.51 |
| NLG | 27 | 3 | 4 | 34 | 12.04 |
| KDH | 27 | 3 | 4 | 34 | 11.87 |
| DGC | 27 | 3 | 4 | 34 | 11.46 |
| HCM | 27 | 3 | 4 | 34 | 11.80 |
| SSI | 27 | 3 | 4 | 34 | 12.75 |
| SHS | 27 | 4 | 4 | 35 | 12.30 |
| CEO | 27 | 3 | 4 | 34 | 12.36 |
| NVB | 27 | 3 | 4 | 34 | 12.19 |
| BSR | 27 | 3 | 4 | 34 | 11.66 |
| VGI | 27 | 3 | 4 | 34 | 11.96 |
| OIL | 27 | 3 | 4 | 34 | 12.29 |

All request categories this run: corporate_actions=82, kbs=3, ohlcv=540, profile=64, sector_map=1, symbol_master=2, vci=12.

### Extrapolation to ~700 tickers

- Average per ticker: **34.3** requests (27.0 of them OHLCV pages).
- Projected for 700 tickers: **24,010** requests.
- At the documented 20 req/min: **1,200 min (~20.0 h)**.
- At this run's observed throughput (1.98 req/s, after the client's requests-per-second cap and the 120 req/min validation safety throttle): **202 min (~3.4 h)**.

Comparison with the `docs/V2_DATA_GAPS.md` budget (pageSize 40, 19 req/ticker, 13,300 requests, 665 min):

- Measured OHLCV pages/ticker is **27.0** vs the doc's **19**.
- The doc underestimates the page count: `get_ohlcv` splits the range into 366-day windows (4 windows for a 2023-01-01 start) and paginates each at pageSize 40, so the per-window page boundaries add requests.
- The precompute path calls the adapters with the shared client, which applies an explicit configurable requests-per-second cap (0.5 rps by default; this run used a higher override so the validation finished quickly) plus 429 backoff and a 403 cooldown.

## 2. Prices, date range, missing days and adjustment reconciliation

| Ticker | Rows | First | Last | Price basis | Missing sessions | Duplicates |
|---|---|---|---|---|---|---|
| VCB | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| BID | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| CTG | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| MBB | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| ACB | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| FPT | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| HPG | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| VNM | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| VHM | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| NLG | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| KDH | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| DGC | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| HCM | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| SSI | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| SHS | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| CEO | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| NVB | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| BSR | 959 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 8 (2025-01-07, 2025-01-08, 2025-01-09, 2025-01-10 ...) | 0 |
| VGI | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |
| OIL | 967 | 2023-01-03 | 2026-11-20 | ssi_adjusted | 0 | 0 |

The missing-session count uses the real trading calendar derived from the stored VN-Index bar dates (a session with an index bar was open), so exchange holidays are not counted as gaps.

### Adjusted-vs-raw at ex-dates (reconciliation)

Ex-dates are the DIV/ISS `exrightDate`s from the SSI corporate-actions feed whose date falls inside each ticker's stored price window. `adj/raw` is `close / close_raw` on the bar before and after the ex-date; a cash dividend should drop the ratio at the ex-date and the adjusted series should remove the gap.

| Ticker | Ex-date | Type | Ratio | Value | adj/raw before -> after | raw gap | adj gap | removed | expected | diff | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| VCB | 2023-07-25 | ISS | 0.181 | 0.0 | 0.5576 -> 0.6586 | -12.33% | +3.54% | -15.87% | -15.33% | -0.55% | ok |
| VCB | 2025-03-12 | ISS | 0.495 | 0.0 | 0.6586 -> 0.9846 | -31.10% | +3.01% | -34.11% | -33.11% | -1.00% | ok |
| VCB | 2025-10-03 | DIV | 0.045 | 450.0 | 0.9846 -> 0.9917 | -0.64% | +0.08% | -0.72% | -0.72% | +0.00% | ok |
| VCB | 2026-07-23 | DIV | 0.045 | 450.0 | 0.9917 -> 1.0000 | -0.92% | -0.09% | -0.83% | -0.83% | -0.00% | ok |
| BID | 2023-11-28 | ISS | 0.1269 | 0.0 | 0.6711 -> 0.7562 | -9.65% | +1.81% | -11.46% | -11.26% | -0.20% | ok |
| BID | 2024-12-23 | ISS | 0.21 | 0.0 | 0.7562 -> 0.9151 | -16.90% | +0.56% | -17.46% | -17.36% | -0.10% | ok |
| BID | 2025-10-14 | DIV | 0.045 | 450.0 | 0.9151 -> 0.9252 | -3.18% | -2.10% | -1.08% | -1.10% | +0.02% | ok |
| BID | 2026-07-17 | DIV | 0.045 | 450.0 | 0.9252 -> 0.9360 | -1.27% | -0.12% | -1.15% | -1.15% | -0.00% | ok |
| BID | 2026-08-17 | ISS | 0.068433 | 0.0 | 0.9360 -> 1.0000 | -6.14% | +0.27% | -6.42% | -6.40% | -0.01% | ok |
| CTG | 2023-11-30 | ISS | 0.117415 | 0.0 | 0.6045 -> 0.6754 | -10.54% | -0.04% | -10.51% | -10.51% | +0.00% | ok |
| CTG | 2025-10-14 | DIV | 0.045 | 450.0 | 0.6754 -> 0.6809 | -2.86% | -2.07% | -0.78% | -0.80% | +0.02% | ok |
| CTG | 2025-12-17 | ISS | 0.44636584 | 0.0 | 0.6809 -> 0.9848 | -31.96% | -1.59% | -30.37% | -30.86% | +0.49% | ok |
| CTG | 2026-07-23 | DIV | 0.045 | 450.0 | 0.9848 -> 1.0000 | -2.19% | -0.68% | -1.51% | -1.52% | +0.01% | ok |
| MBB | 2023-06-14 | DIV | 0.05 | 500.0 | 0.4339 -> 0.4448 | -2.71% | -0.26% | -2.45% | -2.46% | +0.01% | ok |
| MBB | 2023-07-14 | ISS | 0.15 | 0.0 | 0.4448 -> 0.5115 | -11.61% | +1.64% | -13.25% | -13.04% | -0.21% | ok |
| MBB | 2024-05-23 | DIV | 0.05 | 500.0 | 0.5115 -> 0.5228 | -1.72% | +0.45% | -2.17% | -2.16% | -0.01% | ok |
| MBB | 2025-01-07 | ISS | 0.15 | 0.0 | 0.5228 -> 0.6012 | -11.27% | +2.03% | -13.31% | -13.04% | -0.26% | ok |
| MBB | 2025-08-13 | DIV/ISS | 0.35 | 300.0 | 0.6012 -> 0.8009 | -20.37% | +6.09% | -26.46% | -24.94% | -1.51% | ok |
| MBB | 2026-07-09 | DIV | 0.1 | 1000.0 | 0.8009 -> 0.8330 | -5.38% | -1.60% | -3.79% | -3.85% | +0.06% | ok |
| MBB | 2026-08-11 | ISS/ISS | 0.25 | 0.0 | 0.8330 -> 1.0000 | -16.08% | +0.74% | -16.82% | -20.95% | +4.12% | difference |
| ACB | 2023-06-01 | ISS/DIV | 0.25 | 1000.0 | 0.5051 -> 0.6047 | -15.75% | +0.86% | -16.61% | -16.47% | -0.15% | ok |
| ACB | 2024-05-31 | ISS/DIV | 0.25 | 1000.0 | 0.6047 -> 0.7199 | -16.16% | -0.19% | -15.97% | -16.00% | +0.03% | ok |
| ACB | 2025-05-23 | DIV/ISS | 0.25 | 1000.0 | 0.7199 -> 0.8616 | -15.46% | +1.19% | -16.64% | -16.45% | -0.20% | ok |
| ACB | 2026-06-15 | ISS/DIV | 0.2 | 700.0 | 0.8616 -> 1.0000 | -14.15% | -0.36% | -13.79% | -13.84% | +0.05% | ok |
| FPT | 2023-07-05 | ISS/DIV | 0.25 | 1000.0 | 0.5576 -> 0.6487 | -14.02% | +0.02% | -14.04% | -14.04% | +0.00% | ok |
| FPT | 2023-08-24 | DIV | 0.1 | 1000.0 | 0.6487 -> 0.6563 | +4.05% | +5.27% | -1.22% | -1.16% | -0.07% | ok |
| FPT | 2024-06-12 | ISS/DIV | 0.25 | 1000.0 | 0.6563 -> 0.7599 | -9.90% | +4.33% | -14.23% | -13.64% | -0.59% | ok |
| FPT | 2024-12-02 | DIV | 0.1 | 1000.0 | 0.7599 -> 0.7652 | -1.46% | -0.77% | -0.68% | -0.69% | +0.01% | ok |
| FPT | 2025-06-12 | DIV | 0.1 | 1000.0 | 0.7652 -> 0.7718 | -0.76% | +0.09% | -0.85% | -0.85% | -0.00% | ok |
| FPT | 2025-07-21 | ISS | 0.15 | 0.0 | 0.7718 -> 0.8875 | -12.46% | +0.67% | -13.13% | -13.04% | -0.08% | ok |
| FPT | 2025-12-01 | DIV | 0.1 | 1000.0 | 0.8875 -> 0.8967 | -0.51% | +0.52% | -1.04% | -1.03% | -0.01% | ok |
| FPT | 2026-05-28 | DIV | 0.1 | 1000.0 | 0.8967 -> 0.9091 | -3.26% | -1.93% | -1.33% | -1.36% | +0.02% | ok |
| FPT | 2026-09-21 | ISS | 0.1 | 0.0 | 0.9091 -> 1.0000 | -7.39% | +1.87% | -9.26% | -9.09% | -0.17% | ok |
| VNM | 2023-08-03 | DIV/DIV | 0.245 | 2450.0 | 0.7772 -> 0.8031 | -4.60% | -1.43% | -3.17% | -3.19% | +0.02% | ok |
| VNM | 2023-12-27 | DIV | 0.05 | 500.0 | 0.8031 -> 0.8090 | -0.74% | +0.00% | -0.74% | -0.74% | -0.00% | ok |
| VNM | 2024-03-15 | DIV | 0.09 | 900.0 | 0.8090 -> 0.8195 | -2.41% | -1.15% | -1.27% | -1.28% | +0.01% | ok |
| VNM | 2024-09-24 | DIV/DIV | 0.245 | 2450.0 | 0.8195 -> 0.8480 | -3.57% | -0.21% | -3.35% | -3.33% | -0.02% | ok |
| VNM | 2024-12-26 | DIV | 0.05 | 500.0 | 0.8480 -> 0.8547 | -0.93% | -0.15% | -0.78% | -0.78% | -0.00% | ok |
| VNM | 2025-05-14 | DIV | 0.2 | 2000.0 | 0.8547 -> 0.8850 | -3.93% | -0.53% | -3.40% | -3.42% | +0.02% | ok |
| VNM | 2025-10-16 | DIV/DIV | 0.28500000000000003 | 2850.0 | 0.8850 -> 0.9265 | -3.77% | +0.74% | -4.51% | -4.46% | -0.05% | ok |
| VNM | 2026-06-26 | DIV | 0.185 | 1850.0 | 0.9265 -> 0.9568 | -3.43% | -0.27% | -3.16% | -3.17% | +0.01% | ok |
| VNM | 2026-11-11 | DIV | 0.25 | 2500.0 | 0.9568 -> 1.0000 | -5.87% | -1.62% | -4.25% | -4.32% | +0.07% | ok |
| VHM | 2026-06-29 | DIV | 0.6 | 6000.0 | 0.4815 -> 0.5000 | -7.22% | -3.66% | -3.56% | -3.70% | +0.14% | ok |
| VHM | 2026-08-06 | ISS | 1.0 | 0.0 | 0.5000 -> 1.0000 | -49.61% | +0.78% | -50.39% | -50.00% | -0.39% | ok |
| NLG | 2023-05-29 | DIV | 0.02 | 200.0 | 0.8717 -> 0.8772 | +0.31% | +0.94% | -0.63% | -0.62% | -0.00% | ok |
| NLG | 2024-05-29 | DIV | 0.0499 | 499.0 | 0.8772 -> 0.8872 | +0.45% | +1.60% | -1.15% | -1.13% | -0.02% | ok |
| NLG | 2025-06-05 | DIV | 0.0499 | 499.0 | 0.8872 -> 0.8990 | -3.16% | -1.87% | -1.29% | -1.31% | +0.03% | ok |
| NLG | 2025-10-17 | ISS | 0.26 | 0.0 | 0.8990 -> 0.9811 | -8.09% | +0.31% | -8.40% | -20.63% | +12.24% | difference |
| NLG | 2026-06-12 | DIV | 0.05 | 500.0 | 0.9811 -> 1.0000 | -3.97% | -2.12% | -1.85% | -1.89% | +0.04% | ok |
| KDH | 2023-10-03 | ISS | 0.1 | 0.0 | 0.6830 -> 0.7513 | -11.69% | -2.86% | -8.83% | -9.09% | +0.26% | ok |
| KDH | 2024-10-17 | ISS | 0.1 | 0.0 | 0.7513 -> 0.8265 | -8.38% | +0.78% | -9.16% | -9.09% | -0.07% | ok |
| KDH | 2025-07-17 | ISS | 0.1 | 0.0 | 0.8265 -> 0.9091 | -6.91% | +2.39% | -9.31% | -9.09% | -0.22% | ok |
| KDH | 2026-10-07 | ISS | 0.1 | 0.0 | 0.9091 -> 1.0000 | -8.75% | +0.37% | -9.12% | -9.09% | -0.03% | ok |
| DGC | 2023-04-13 | DIV | 0.1 | 1000.0 | 0.7342 -> 0.7484 | +3.02% | +5.00% | -1.98% | -1.89% | -0.10% | ok |
| DGC | 2023-12-19 | DIV | 0.3 | 3000.0 | 0.7484 -> 0.7731 | -1.60% | +1.65% | -3.25% | -3.20% | -0.05% | ok |
| DGC | 2024-11-19 | DIV | 0.3 | 3000.0 | 0.7731 -> 0.7942 | -5.75% | -3.19% | -2.57% | -2.65% | +0.09% | ok |
| DGC | 2025-12-24 | DIV | 0.3 | 3000.0 | 0.7942 -> 0.8289 | -9.22% | -5.25% | -3.97% | -4.19% | +0.22% | ok |
| DGC | 2026-09-14 | DIV/DIV | 0.8 | 8000.0 | 0.8289 -> 1.0000 | -20.00% | -3.49% | -16.51% | -16.43% | -0.09% | ok |
| HCM | 2023-01-17 | DIV/DIV | 0.05 | 500.0 | 0.4187 -> 0.4278 | +1.92% | +4.14% | -2.22% | -2.12% | -0.10% | ok |
| HCM | 2023-06-08 | DIV | 0.05 | 500.0 | 0.4278 -> 0.4357 | -5.26% | -3.52% | -1.75% | -1.81% | +0.07% | ok |
| HCM | 2024-01-02 | ISS/ISS | 0.65 | 0.0 | 0.4357 -> 0.6271 | -27.78% | +3.96% | -31.74% | -42.03% | +10.29% | difference |
| HCM | 2024-07-15 | DIV/DIV | 0.11780000000000002 | 1178.0 | 0.6271 -> 0.6549 | -4.68% | -0.46% | -4.22% | -4.19% | -0.03% | ok |
| HCM | 2025-02-04 | DIV | 0.05 | 500.0 | 0.6549 -> 0.6664 | +0.34% | +2.10% | -1.76% | -1.72% | -0.03% | ok |
| HCM | 2025-05-13 | DIV | 0.04 | 400.0 | 0.6664 -> 0.6768 | -0.77% | +0.78% | -1.55% | -1.54% | -0.01% | ok |
| HCM | 2025-06-24 | ISS | 0.5 | 0.0 | 0.6768 -> 0.8479 | -17.75% | +3.04% | -20.79% | -33.33% | +12.54% | difference |
| HCM | 2026-02-05 | DIV | 0.04 | 400.0 | 0.8479 -> 0.8622 | -3.94% | -2.32% | -1.62% | -1.66% | +0.04% | ok |
| HCM | 2026-07-16 | ISS/DIV | 0.29 | 400.0 | 0.8622 -> 1.0000 | -7.78% | +6.96% | -14.74% | -21.19% | +6.45% | difference |
| SSI | 2023-06-20 | DIV | 0.1 | 1000.0 | 0.5333 -> 0.5543 | -2.65% | +1.18% | -3.83% | -3.79% | -0.05% | ok |
| SSI | 2024-09-23 | ISS/DIV/ISS | 0.4 | 1000.0 | 0.5543 -> 0.7100 | -20.83% | +1.40% | -22.24% | -26.50% | +4.26% | difference |
| SSI | 2025-09-25 | DIV | 0.1 | 1000.0 | 0.7100 -> 0.7281 | -3.11% | -0.64% | -2.46% | -2.48% | +0.02% | ok |
| SSI | 2025-12-08 | ISS | 0.2 | 0.0 | 0.7281 -> 0.7993 | -8.84% | +0.08% | -8.92% | -16.67% | +7.75% | difference |
| SSI | 2026-08-17 | DIV/ISS | 0.30000000000000004 | 1000.0 | 0.7993 -> 1.0000 | -19.18% | +1.11% | -20.29% | -20.07% | -0.22% | ok |
| SHS | 2025-04-24 | DIV/ISS/ISS | 0.2 | 1000.0 | 0.8119 -> 0.9603 | -13.99% | +1.73% | -15.72% | -15.64% | -0.08% | ok |
| SHS | 2026-10-08 | DIV | 0.05 | 500.0 | 0.9603 -> 1.0000 | -7.94% | -4.13% | -3.81% | -3.97% | +0.16% | ok |
| CEO | 2023-07-19 | ISS | 0.98 | 0.0 | 0.6459 -> 0.8639 | -17.65% | +10.14% | -27.79% | -49.49% | +21.71% | difference |
| CEO | 2024-07-25 | ISS | 0.05 | 0.0 | 0.8639 -> 0.9071 | -3.12% | +1.72% | -4.84% | -4.76% | -0.08% | ok |
| CEO | 2025-08-07 | ISS | 0.05 | 0.0 | 0.9071 -> 0.9524 | +0.42% | +5.44% | -5.02% | -4.76% | -0.26% | ok |
| CEO | 2026-06-09 | ISS | 0.05 | 0.0 | 0.9524 -> 1.0000 | -3.27% | +1.57% | -4.83% | -4.76% | -0.07% | ok |
| BSR | 2023-08-22 | DIV | 0.07 | 700.0 | 0.5651 -> 0.5947 | -3.65% | +1.41% | -5.05% | -3.65% | -1.41% | ok |
| BSR | 2024-10-14 | DIV | 0.07 | 700.0 | 0.5947 -> 0.6123 | -3.28% | -0.42% | -2.86% | -2.87% | +0.01% | ok |
| BSR | 2025-10-29 | ISS/ISS | 0.615 | 0.0 | 0.6123 -> 0.9888 | -33.85% | +6.83% | -40.68% | -41.50% | +0.82% | ok |
| BSR | 2026-08-11 | DIV | 0.03 | 300.0 | 0.9888 -> 1.0000 | -3.16% | -2.06% | -1.10% | -1.12% | +0.02% | ok |
| VGI | 2025-09-08 | DIV | 0.075 | 750.0 | 0.9516 -> 0.9611 | -4.26% | -3.30% | -0.96% | -1.00% | +0.04% | ok |
| VGI | 2026-09-17 | DIV | 0.33 | 3300.0 | 0.9611 -> 1.0000 | -3.08% | +0.84% | -3.92% | -3.91% | -0.01% | ok |
| OIL | 2023-08-23 | DIV | 0.02 | 200.0 | 0.9120 -> 0.9510 | -2.86% | +1.30% | -4.16% | -1.90% | -2.26% | difference |
| OIL | 2024-09-05 | DIV | 0.02 | 200.0 | 0.9450 -> 0.9625 | -5.37% | -3.62% | -1.75% | -1.34% | -0.41% | ok |
| OIL | 2025-08-21 | DIV | 0.025 | 250.0 | 0.9625 -> 0.9820 | -2.40% | -0.42% | -1.98% | -2.00% | +0.02% | ok |
| OIL | 2026-09-04 | DIV | 0.025 | 250.0 | 0.9820 -> 1.0000 | -1.44% | +0.37% | -1.81% | -1.80% | -0.01% | ok |

Ex-dates tested inside the price window: **88**.

**Finding.**

- For the 79 ex-date(s) the feed returned inside the window, the adjusted/raw gap removal matches the corporate-action ratio (all status `ok`, worst |difference| = 1.51 pp). SSI's adjusted close is therefore internally consistent with its own corporate-action ratios.
- 43 `adjusted_vs_raw_mismatch` finding(s) are the adjusted/raw ratio changing on an ordinary session. They are either (a) SSI's adjusted `close` drifting daily from `closeRaw` — 40 findings on VGI (20) and OIL (20), which have far more ratio-change sessions than feed actions (VGI ~80 sessions vs 2 actions; OIL ~33 vs 4; verified in the raw SSI payload) — or (b) a real corporate action the feed omits entirely — HPG's 3 bonus issues (2024-05-23 +10%, 2025-06-26 +20%, 2026-05-25 +10%), where the feed returns **0 rows** for HPG. These are not missing-window artefacts; the dated query now returns each ticker's real ex-dates.
- 9 reconciliation finding(s) at real ex-dates have status `difference` (MBB 2026-08-11, NLG 2025-10-17, HCM 2024-01-02, 2025-06-24, 2026-07-16; SSI 2024-09-23, 2025-12-08; CEO 2023-07-19; OIL 2023-08-23) — the combined multi-action / odd-ratio cases where the removed gap does not match the implied gap. OIL's 2023-08-23 DIV (-2.26%) does not appear in section 5 because OIL's 20 drift findings fill the 20-item per-ticker quality cap.
- 20 ex-date(s) carry more than one corporate action (MBB 2025-08-13 (DIV/ISS); MBB 2026-08-11 (ISS/ISS); ACB 2023-06-01 (ISS/DIV); ACB 2024-05-31 (ISS/DIV); ACB 2025-05-23 (DIV/ISS); ACB 2026-06-15 (ISS/DIV); FPT 2023-07-05 (ISS/DIV); FPT 2024-06-12 (ISS/DIV)). `reconcile_corporate_actions` now combines every action on one ex-date into a single finding and compares the compounded implied gap with the total removed gap, so each such ex-date yields one row instead of one per action.
- 1 `missing_trading_days` finding(s) remain even with the VN-Index-derived trading calendar; these are ticker-specific gaps (for example a suspension or a late first bar), not exchange holidays.

Actions with an ex-date outside the stored window:

- FPT: 2026-11-27 DIV ratio=0.1 value=1000.0 (outside the stored price window)

## 3. Liquidity (median ADTV / ADV, volume basis)

| Ticker | ADTV median | ADV median | Basis | Last close | ADV x last close | Median matched vol | Median matched val |
|---|---|---|---|---|---|---|---|
| VCB | 224.80B | 4,142,950 | matched | 50200.0 | 207.98B | 4,142,950 | 224.80B |
| BID | 137.73B | 4,273,200 | matched | 30050.0 | 128.41B | 4,273,200 | 137.73B |
| CTG | 186.23B | 6,027,300 | matched | 30100.0 | 181.42B | 6,027,300 | 186.23B |
| MBB | 188.25B | 9,626,550 | matched | 18250.0 | 175.68B | 9,626,550 | 188.25B |
| ACB | 162.91B | 8,009,350 | matched | 19600.0 | 156.98B | 8,009,350 | 162.91B |
| FPT | 597.31B | 11,493,850 | matched | 45000.0 | 517.22B | 11,493,850 | 597.31B |
| HPG | 343.35B | 16,467,550 | matched | 20450.0 | 336.76B | 16,467,550 | 343.35B |
| VNM | 138.56B | 2,437,650 | matched | 51400.0 | 125.30B | 2,437,650 | 138.56B |
| VHM | 317.37B | 5,103,300 | matched | 60400.0 | 308.24B | 5,103,300 | 317.37B |
| NLG | 31.57B | 1,369,100 | matched | 23200.0 | 31.76B | 1,369,100 | 31.57B |
| KDH | 157.37B | 10,816,300 | matched | 15400.0 | 166.57B | 10,816,300 | 157.37B |
| DGC | 10.00B | 305,650 | matched | 31000.0 | 9.48B | 305,650 | 10.00B |
| HCM | 81.90B | 3,552,800 | matched | 23000.0 | 81.71B | 3,552,800 | 81.90B |
| SSI | 285.92B | 14,430,350 | matched | 20000.0 | 288.61B | 14,430,350 | 285.92B |
| SHS | 104.09B | 7,947,550 | matched | 13200.0 | 104.91B | 7,947,550 | 104.09B |
| CEO | 93.07B | 7,841,200 | matched | 11500.0 | 90.17B | 7,841,200 | 93.07B |
| NVB | 14.96B | 979,950 | matched | 14600.0 | 14.31B | 979,950 | 14.96B |
| BSR | 181.87B | 7,048,450 | matched | 23600.0 | 166.34B | 7,048,450 | 181.87B |
| VGI | 9.88B | 131,850 | matched | 66700.0 | 8.79B | 131,850 | 9.88B |
| OIL | 18.53B | 1,546,000 | matched | 11800.0 | 18.24B | 1,546,000 | 18.53B |

Sanity: `ADV median` is shares/session and `ADTV median` is VND/session, both as a 20-session median. `ADV x last close` is a rough VND-per-session cross-check against the stored ADTV (they should be the same order of magnitude; a large gap means the last close is far from the window's average price). `Median matched vol` and `Median matched val` are recomputed directly from the stored bars' `totalMatchVol` / `totalMatchVal` so they should equal the stored medians on the `matched` basis.

## 4. Market cap and sector presence

| Ticker | In universe | Market cap | Shares out | mcap / last close | Sector (ICB L2) | Sector source |
|---|---|---|---|---|---|---|
| VCB | yes | 419.455T | 8,355,675,094 | 8,355,675,094 | Banks | ssi_statistics |
| BID | yes | 233.736T | 7,778,229,473 | 7,778,229,473 | Banks | ssi_statistics |
| CTG | yes | 233.785T | 7,766,944,637 | 7,766,944,637 | Banks | ssi_statistics |
| MBB | yes | 183.755T | 10,069,000,000 | 10,068,749,885 | Banks | ssi_statistics |
| ACB | yes | 113.767T | 5,804,421,957 | 5,804,421,957 | Banks | ssi_statistics |
| FPT | yes | 84.858T | 1,885,727,648 | 1,885,727,648 | Technology | ssi_statistics |
| HPG | yes | 172.659T | 8,442,964,520 | 8,442,964,520 | Basic Resources | ssi_statistics |
| VNM | yes | 107.424T | 2,089,955,445 | 2,089,955,445 | Food & Beverage | ssi_statistics |
| VHM | yes | 496.175T | 8,214,824,008 | 8,214,824,008 | Real Estate | ssi_statistics |
| NLG | yes | 11.254T | 485,097,383 | 485,097,383 | Real Estate | ssi_statistics |
| KDH | yes | 19.178T | 1,245,297,704 | 1,245,297,704 | Real Estate | ssi_statistics |
| DGC | yes | 11.773T | 379,778,413 | 379,778,413 | Chemicals | ssi_statistics |
| HCM | yes | 31.555T | 1,371,945,838 | 1,371,945,838 | Financial Services | ssi_statistics |
| SSI | yes | 60.010T | 3,000,500,833 | 3,000,500,833 | Financial Services | ssi_statistics |
| SHS | yes | 11.873T | 899,462,220 | 899,462,220 | Financial Services | ssi_statistics |
| CEO | yes | 6.851T | 595,775,755 | 595,775,755 | Real Estate | ssi_statistics |
| NVB | yes | 42.700T | 2,924,632,751 | 2,924,632,751 | Banks | ssi_statistics |
| BSR | yes | 118.172T | 5,007,299,686 | 5,007,299,686 | Oil & Gas | ssi_statistics |
| VGI | yes | 203.436T | 3,043,811,200 | 3,050,017,472 | Telecommunications | ssi_statistics |
| OIL | yes | 12.297T | 1,034,229,500 | 1,042,117,691 | Oil & Gas | ssi_statistics |

- Tickers with no ICB level-2 sector: none.
- Tickers with no market cap: none.

## 5. Quality-check output (all findings)

Pipeline step results (backfill run):

- `ticker_master`: ok (processed=20) - 0 without sector; 0 excluded
- `index_membership`: ok (processed=130)
- `benchmarks`: ok (processed=2901)
- `prices`: ok (processed=20) - 19332 bars for 20 tickers; 0 failed
- `profiles`: ok (processed=20)
- `liquidity`: ok (processed=20)
- `quality`: FAIL (processed=20) - 53 errors

Additional observation: `get_ratios('HPG')` previously raised `ValueError: year must be in 1..9999, not 0` from `data.v2.providers.ssi_statistics._period` when `yearReport` is 0. `_period` now skips rows with an invalid/zero year, so the V2b fundamentals path is safe for such tickers.

### MBB (1 finding(s))

- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.0412 at the ISS/ISS ex-date 2026-08-11 [2026-08-11]

### HPG (3 finding(s))

- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.068 on 2024-05-23 with no corporate action [2024-05-23]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.149 on 2025-06-26 with no corporate action [2025-06-26]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.091 on 2026-05-25 with no corporate action [2026-05-25]

### NLG (1 finding(s))

- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.1224 at the ISS ex-date 2025-10-17 [2025-10-17]

### HCM (3 finding(s))

- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.1029 at the ISS/ISS ex-date 2024-01-02 [2024-01-02]
- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.1254 at the ISS ex-date 2025-06-24 [2025-06-24]
- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.0645 at the ISS/DIV ex-date 2026-07-16 [2026-07-16]

### SSI (2 finding(s))

- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.0426 at the ISS/DIV/ISS ex-date 2024-09-23 [2024-09-23]
- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.0775 at the ISS ex-date 2025-12-08 [2025-12-08]

### CEO (1 finding(s))

- **error** `adjusted_vs_raw_mismatch`: reconciliation difference +0.2171 at the ISS ex-date 2023-07-19 [2023-07-19]

### BSR (2 finding(s))

- **error** `missing_trading_days`: 8 trading days have no bar [2025-01-07, 2025-01-08, 2025-01-09, 2025-01-10, 2025-01-13, 2025-01-14]
- **error** `suspicious_returns`: 8.0% move on 2024-05-22 exceeds the 7% HOSE limit and is not near a corporate action [2024-05-22]

### VGI (20 finding(s))

- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.023 on 2023-05-15 with no corporate action [2023-05-15]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.025 on 2023-06-08 with no corporate action [2023-06-08]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.028 on 2023-06-09 with no corporate action [2023-06-09]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.021 on 2023-06-29 with no corporate action [2023-06-29]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.022 on 2023-07-03 with no corporate action [2023-07-03]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.025 on 2023-08-18 with no corporate action [2023-08-18]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.026 on 2023-08-21 with no corporate action [2023-08-21]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.020 on 2023-08-23 with no corporate action [2023-08-23]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.021 on 2023-08-24 with no corporate action [2023-08-24]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.024 on 2023-09-12 with no corporate action [2023-09-12]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.023 on 2023-09-19 with no corporate action [2023-09-19]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.027 on 2023-09-27 with no corporate action [2023-09-27]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.037 on 2023-10-04 with no corporate action [2023-10-04]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.038 on 2023-10-05 with no corporate action [2023-10-05]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.034 on 2023-10-17 with no corporate action [2023-10-17]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.043 on 2023-10-18 with no corporate action [2023-10-18]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.028 on 2023-10-19 with no corporate action [2023-10-19]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.026 on 2023-10-20 with no corporate action [2023-10-20]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.029 on 2023-10-27 with no corporate action [2023-10-27]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.031 on 2023-10-30 with no corporate action [2023-10-30]

### OIL (20 finding(s))

- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.022 on 2023-04-26 with no corporate action [2023-04-26]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.025 on 2023-06-09 with no corporate action [2023-06-09]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.022 on 2023-08-01 with no corporate action [2023-08-01]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.026 on 2023-08-02 with no corporate action [2023-08-02]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.035 on 2023-08-21 with no corporate action [2023-08-21]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.031 on 2023-09-12 with no corporate action [2023-09-12]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.025 on 2023-09-27 with no corporate action [2023-09-27]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.025 on 2023-10-04 with no corporate action [2023-10-04]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.023 on 2023-10-06 with no corporate action [2023-10-06]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.026 on 2023-10-27 with no corporate action [2023-10-27]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.025 on 2023-11-01 with no corporate action [2023-11-01]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.020 on 2023-11-09 with no corporate action [2023-11-09]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.025 on 2023-11-23 with no corporate action [2023-11-23]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.021 on 2023-11-28 with no corporate action [2023-11-28]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.023 on 2024-02-07 with no corporate action [2024-02-07]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.030 on 2024-05-29 with no corporate action [2024-05-29]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.026 on 2024-05-30 with no corporate action [2024-05-30]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.022 on 2024-06-14 with no corporate action [2024-06-14]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by -0.024 on 2024-06-19 with no corporate action [2024-06-19]
- **error** `adjusted_vs_raw_mismatch`: adjusted/raw ratio changed by +0.021 on 2024-06-24 with no corporate action [2024-06-24]

## 6. Second run fetches only new dates

Second run mode=`incremental` issued **0** OHLCV page requests in **2.9s**.

No ticker fetched a price page: every ticker already had a stored bar at the target trading day, so the incremental path (`latest_stored_date >= target` -> skip) requested **zero** new dates. That is the only-new-dates behaviour on real data; on the next trading day the same path costs one page per ticker (see `test_incremental_second_run_fetches_only_new_dates`).

Second-run request categories (bulk master/benchmark calls repeat by design): kbs=3, sector_map=1, symbol_master=2.

## 7. Pre-screen default

The pre-screen (`precompute_pre_screen_min_median_volume`, a 30-session median share-volume floor) now defaults to **10_000 shares** and is documented as a **backfill-cost floor, not a liquidity filter**. It runs before the per-ticker SSI calls, so it only drops effectively untraded or suspended names (the long tail of UPCoM shells) and keeps every genuinely tradable stock in "All Stocks".

It stays switchable with `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED=false` and can be disabled entirely by setting `precompute_pre_screen_min_median_volume = 0`.

## 8. The 8% move on 2024-05-22

### BSR

- Quality finding: 8.0% move on 2024-05-22 exceeds the 7% HOSE limit and is not near a corporate action
- Stored bars around the move:
  - 2024-05-20: close=11834.96 close_raw=19900.00 volume=9512325
  - 2024-05-21: close=11894.44 close_raw=20000.00 volume=6688138
  - 2024-05-22: close=12845.99 close_raw=21600.00 volume=28952943
  - 2024-05-23: close=13381.24 close_raw=22500.00 volume=18968021
  - 2024-05-24: close=13440.71 close_raw=22600.00 volume=24207794
- BSR traded on UPCoM and first traded on HOSE on **2025-01-17** (Simplize listing history), so the 2024-05-22 session was still under UPCoM's 15% daily band.
- Verdict: **not bad data** — the raw and adjusted closes moved together (+8.00%), so the feed is internally consistent. The move is within the 15% UPCoM daily band, while the ticker is currently HOSE (7% band); the `suspicious_returns` flag is a false positive from applying the *current* exchange limit to a session when the ticker traded on UPCoM (or on a listing-transfer day with a wider band).

## Limitations

- **Local environment.** Results come from a local PC, not a cloud runner; the docs already note that Cloudflare-fronted SSI access is unverified from cloud IPs.
- **Derived trading calendar.** The missing-session count uses the trading calendar derived from the stored VN-Index bars, so it is only as complete as those bars.
- **Sample choice.** The ~20 tickers are hand-picked (banks, large caps, real estate, small/mid caps, HNX, UPCoM), not a random sample; large caps are over-represented relative to the ~700-ticker universe.
- **Throttled pipeline.** The precompute path's shared client applies an explicit requests-per-second cap (0.5 rps by default; this run used a higher override to finish quickly) with 429 backoff and a 403 cooldown; the validation client's 120 req/min safety throttle was the binding limit.
- **No independent ADTV/ADV source.** Liquidity is cross-checked only against the same stored bars (matched volume/value medians); there is no second provider to compare against, so the sanity check is dimensional, not absolute.

