# VN Portfolio Optimizer

Personal portfolio optimizer for Vietnamese equities (HOSE, HNX, UPCoM).
Decision support only, **not financial advice**.

## What it does (V1.1)

Six pages share one persisted client store, so leaving a page and coming back
never loses the portfolio, the selected stocks, the optimization result or the
mix you chose:

| Page | Purpose |
| --- | --- |
| **Portfolio** | Enter holdings (shares, average cost), cash, optional buy dates; live valuation, weights and a liquidity warning. Saved portfolios and CSV/JSON import/export. |
| **P&L** | Unrealized profit and loss from holdings plus average cost alone, net of the sell tax and your brokerage fee, with a per-stock breakdown. |
| **Optimize** | Pick stocks (seeded from the portfolio or VN30), money, a timeframe (6M, 1Y, 2Y, 3Y, 5Y, Max or a custom range) and one of three plain goals. Shows the Monte Carlo cloud, the exact efficient frontier, the minimum-variance and maximum-Sharpe points and your current portfolio, with an interactive chart, a risk slider and "Use this portfolio". |
| **Risk** | Volatility, beta, Sharpe, Treynor, Jensen's alpha, maximum drawdown and historical VaR for the current, optimized, equal-weight and benchmark portfolios over its own timeframe, plus interactive performance and drawdown charts and a hoverable correlation heatmap. |
| **Rebalance** | Target weights start from the optimized mix (or the current weights) and stay editable; the page returns a lot-rounded order list with costs, using the `full` or `threshold_band` policy. |
| **Settings** | Your brokerage fee rate and risk-free rate, sent with every calculation and stored in the browser. |

### Timeframe and charts

The Optimize and Risk pages each keep a **timeframe** (6M, 1Y, 2Y, 3Y, 5Y, Max, or a
custom start/end). Optimize defaults to 3Y and Risk to 1Y; the choice is stored in
the same persisted browser store as the universe, so it survives switching tabs
and reloads. Each tab also offers a "Use same as ..." link to copy the other
tab's window.

The timeframe is resolved to an explicit `start` / `end` date against the latest
available data date and sent with `POST /api/v1/optimize/frontier` and
`POST /api/v1/risk/compare` (both already accept ISO `start` and `end`); the same
window drives returns, covariance, the frontier, the random cloud, every risk
metric, the benchmark and the performance chart. A window is validated in the
browser before any request: the start must be before the end, the end must not be
after the latest data, and it needs at least ~60 trading days. A symbol with too
little history in the chosen window is dropped with a plain-language reason.

Charts are built with **Recharts**. Every chart shows labelled tick values and
units, and the interactive views support hover/tap tooltips, a clickable frontier
that keeps the risk slider in sync, show/hide toggles, a performance brush with a
reset button and a correlation heatmap that highlights the hovered row/column. The
P&L by-stock / market-value charts and the Rebalance current-versus-target weights
are built the same way, with VND and percent axes.

Only CFA Level 1/2 methods are implemented: mean, variance, covariance,
correlation, beta, Sharpe, Treynor, Jensen's alpha, maximum drawdown, historical
VaR, minimum-variance and tangency portfolios and the efficient frontier (with
sample mean and sample covariance estimates). Everything else was removed in
V1.1; `docs/ROADMAP.md` lists what may return in V2.

## V2 — precomputed sector & fundamentals analysis

V2 adds a precomputed pipeline (run on a GitHub Actions runner, not a serverless
function) that stores ICB level-2 sectors, index membership, adjusted daily prices,
20-session ADTV/ADV medians, full market cap and TTM financial ratios in
additive `v2_*` tables (`docs/V2_SPEC.md`, `docs/DECISIONS.md`). On top of that:

- **Optimize tab** gains a sector/index/liquidity universe filter (`GET /v2/universe`,
  `GET /v2/sectors`) backed by the same `filter_universe` the Sector tab uses, so
  both return the same tickers for the same settings.
- **Sector Analysis** (Market sub-tab) — relative sector returns, beta, R²,
  volatility and correlation against a chosen benchmark (`GET /v2/analytics`).
- **Sector Analysis** (Fundamentals sub-tab) — a ticker's ratios compared with its
  sector peers (median, winsorized mean, percentile rank) with an
  all/liquidity/VN100 peer toggle (`GET /v2/fundamentals/{symbol}`).
- The Optimize and Frontier price paths read **V2 adjusted closes** when available
  (falling back to V1 raw closes), so corporate actions do not create fake returns.

Precompute commands, provider setup/failover and how to add a provider or ratio are
in `docs/DATA.md` and `docs/V2_PRECOMPUTE_VALIDATION.md`. Run the V2 jobs with:

```sh
python -m data.v2.jobs.precompute --incremental        # daily update (1 page/ticker)
python -m data.v2.jobs.precompute --full --start 2023-01-01 --limit 150   # chunked backfill
python -m data.v2.jobs.precompute --incremental --recompute-flags --members VN30
```

## Layout

```
apps/web      Next.js + TypeScript + Tailwind UI (one persisted client store)
apps/api      Thin FastAPI layer (deploys to Vercel as a Python function)
packages/core Pure domain logic (optimizer, frontier, risk, P&L, rebalance)
packages/data Data providers, repositories and sync jobs
docs/         Architecture, extension guide, roadmap, deployment, changelog, ADRs
```

## Prerequisites

- Python 3.12+
- Node.js 22+ and npm
- GNU `make` (Linux/macOS ship it; on Windows install it with
  `winget install --id ezwinports.make -e` or `choco install make`)

## Local setup

```sh
make install
```

This installs the Python packages in editable mode (`core`, `data`, `api`) and
the web dependencies (including `openapi-typescript`).

## Development

```sh
make dev          # run the API (port 8000) and web app (port 3000) together
make test         # run the Python test suite
make test-web     # run the web unit tests (Node test runner)
make lint         # ruff + web lint
make typecheck    # mypy + web typecheck
make client       # regenerate apps/api/openapi.json and apps/web/lib/schema.d.ts
make client-check # fail if the generated typed client is out of date
make check        # lint + typecheck + client-check + tests (the full gate)
```

The web app calls `GET /api/v1/health`; the Next.js dev server proxies `/api/*`
to the FastAPI server so no CORS configuration is needed during development.

### Typed web client

`apps/web/lib/api.ts` is the runtime client; every payload type is derived from
`apps/web/lib/schema.d.ts`, which is generated from the FastAPI OpenAPI schema
(`apps/api/openapi.json`) by `make client`. `make check` runs `make client-check`,
which regenerates both artefacts and fails (with a diff) when they drift, so a
change to an API model cannot silently desynchronise the UI.

## Deploy from this folder (Vercel CLI, no Git)

Two Vercel projects share one database:

1. **API** — Root Directory **the repository root** (so `packages/core` and
   `packages/data` are included); the Vercel FastAPI preset loads the root
   `asgi.py`, which re-exports the app from `apps/api/app/main.py`; region
   `sin1`.
2. **Web** — Root Directory `apps/web`, Next.js, region `sin1`.

```sh
npm i -g vercel

# API project — run from the repository root
vercel link            # create/select the API project
vercel env add DATABASE_URL production      # e.g. a Postgres URL (Neon/Supabase)
vercel env add PROVIDER_ORDER production    # kbs,vci,dnse,tcbs,ssi_iboard
vercel env add REFRESH_TOKEN production     # long random string
vercel env add CRON_SECRET production       # same value as REFRESH_TOKEN
vercel --prod

# Web project
cd apps/web
vercel link            # create/select the web project
vercel env add API_URL production   # the API project URL from the step above
vercel --prod
```

### Live deployments (2026-11-22)

- **API** — https://vn-portfolio-optimizer-re.vercel.app (FastAPI function, `sin1`,
  bundles to ~73 MB)
- **Web** — https://vn-portfolio-web.vercel.app (Next.js, `sin1`)

After deploying, run the reusable smoke test from the repository root. It reads
the refresh token from the environment so the secret is never printed (pass
`--bypass` only for a protected preview):

```sh
VNOPT_REFRESH_TOKEN=... python scripts/smoke_test.py \
  --api-url https://vn-portfolio-optimizer-re.vercel.app \
  --web-url https://vn-portfolio-web.vercel.app
```

Roll back a bad deploy with `vercel rollback` (run from the project directory);
it promotes the previous production deployment.

See `docs/DEPLOYMENT.md` for the verified Vercel Python limits, the measured
bundle size, the cron schedule and the full environment-variable table.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | API, migrations, jobs | SQLAlchemy URL (SQLite locally, Postgres in production). GitHub Actions reads it from the `DATABASE_URL` **secret**. |
| `PROVIDER_ORDER` | API | V1 failover order, default `kbs,vci,dnse,tcbs,ssi_iboard` (KBS first). |
| `VNOPT_V2_*_ORDER` | API | V2 failover chains per data type (`ohlcv`, `constituents`, `sector_map`, `ratios`, ...); default `ssi_statistics` first (see `data/v2/config.py`). The precompute job wires its adapters explicitly, so it ignores these. |
| `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` | API | Per-data-type request budget for the V2 failover runner (defaults 10-20/min). |
| `VNOPT_V2_BACKFILL_START_DATE` | precompute job | Backfill start date (`2023-01-01`). |
| `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND` | precompute job | Shared-client throttle (`0.5` = 30 requests/min); set as a repo variable. |
| `REFRESH_TOKEN` / `VNOPT_REFRESH_TOKEN` | API | Shared secret for `/data/refresh` and `/data/probe`. |
| `CRON_SECRET` | API | Vercel Cron sends it as `Authorization: Bearer`; set it equal to `REFRESH_TOKEN`. |
| `API_URL` | Web | Base URL the Next.js server proxies `/api/*` to. |

Optional tuning keys (`VNOPT_SYNC_BATCH_SIZE`, `VNOPT_SYNC_TIME_BUDGET_SECONDS`,
`VNOPT_ON_DEMAND_HISTORY_DAYS`, `VNOPT_FRONTIER_MAX_PORTFOLIOS`, ...) are
documented in `.env.example` and `docs/DATA.md`.

## Documentation

- `docs/ARCHITECTURE.md` — components, diagram, request flow.
- `docs/EXTENDING.md` — worked examples for each registry.
- `docs/ROADMAP.md` — V2/V3 items and the extension point each plugs into.
- `docs/DATA.md` — providers, failover, sync and cron.
- `docs/DEPLOYMENT.md` — Vercel CLI deploy, limits, bundle size.
- `docs/CHANGELOG.md` — release history.
