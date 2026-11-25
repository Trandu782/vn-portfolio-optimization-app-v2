# Architecture

The VN Portfolio Optimizer is a personal, decision-support tool for Vietnamese
equities (HOSE, HNX, UPCoM). It never provides financial advice.

The codebase follows a **ports-and-adapters** layout. Dependencies point inward:
the domain has no knowledge of the web, the database or the network.

```
                    ┌─────────────────────────────────────────────────┐
                    │ apps/web  Next.js + TypeScript + Tailwind       │
                    │ pages: Portfolio · P&L · Optimize · Risk ·      │
                    │        Rebalance · Settings                     │
                    │ one persisted store (app-store): portfolio,     │
                    │ library, universe, timeframes, optimize,        │
                    │ chosen, settings                                │
                    └───────────────┬─────────────────────────────────┘
                                    │ typed client (schema.d.ts, generated)
                                    │ /api/* rewrite via API_URL
                    ┌───────────────▼─────────────────────────────────┐
                    │ apps/api  FastAPI (/api/v1, thin routes)        │
                    │ health · settings · universe · portfolio ·      │
                    │ pnl · optimize/frontier · risk · rebalance ·    │
                    │ data (probe/refresh/freshness)                  │
                    └───────┬───────────────────────┬─────────────────┘
                            │                       │
            ┌───────────────▼──────────┐   ┌────────▼─────────────────┐
            │ packages/core            │   │ packages/data            │
            │ registries: objectives,  │   │ DataProvider registry    │
            │ constraints, estimators, │◄──┤ failover chain (KBS→…)   │
            │ risk metrics, cost       │   │ SQLAlchemy repos + sync  │
            │ models and policies      │   │ SQLite / Postgres        │
            └──────────────────────────┘   └────────┬─────────────────┘
                                                    │ HTTPS (anonymous)
                                          ┌─────────▼─────────┐
                                          │ KBS · VCI · DNSE · │
                                          │ TCBS · SSI iBoard  │
                                          └───────────────────┘
```

V1.1 implements only CFA Level 1/2 methods: mean, variance, covariance,
correlation, beta, Sharpe, Treynor, Jensen's alpha, maximum drawdown, historical
VaR, minimum-variance and tangency portfolios and the efficient frontier, using
the sample mean and sample covariance (252 trading days). Ledoit-Wolf/EWMA, risk
parity, CVaR, the Monte Carlo simulators and the walk-forward backtester were
removed in V1.1; `docs/ROADMAP.md` records them for a possible V2.

## Components

| Path | Role | Allowed dependencies |
| --- | --- | --- |
| `packages/core` | Pure domain logic: optimizer and efficient frontier, risk metrics, P&L, rebalance, universe filters. | numpy, pandas, scipy, pydantic, pydantic-settings |
| `packages/data` | Data providers (VCI, KBS, DNSE, TCBS, SSI iBoard), repositories, DB models, sync jobs. | pydantic; network/DB clients |
| `apps/api` | Thin FastAPI layer. Routes validate input, call core/data, return typed responses. | FastAPI, core, data |
| `apps/web` | Next.js + TypeScript UI with one persisted store. Talks to the API only. | The typed API |

## Extensibility: the registry

Every *variable concept* is an **interface plus a registry**, never an
`if/else` or `switch` chain. The kinds of concept include `DataProvider`,
`ReturnEstimator`, `CovarianceEstimator`, `Objective`, `Constraint`,
`RiskMetric`, `CostModel`, `RebalancePolicy` and `UniverseFilter`.

`packages/core/core/registry.py` provides a generic `Registry[T]`:

```python
from pydantic import BaseModel
from core.registry import Registry

class Params(BaseModel):
    trading_days: int = 252

covariance: Registry[CovarianceEstimator] = Registry()

@covariance.register(
    id="sample",
    name="Sample covariance",
    description="Plain historical sample covariance (pairwise-complete), annualized.",
    parameter_schema=Params,
)
class SampleCovariance:
    ...
```

- `get(id)` returns the registered implementation class.
- `list()` returns the registered ids.
- `describe()` returns `id`, `name`, `description` and the JSON schema derived
  from the Pydantic parameter model, so the API can publish the options and the
  UI can render them without hardcoding.

Adding a feature means **one new file implementing the interface plus one
registration** — see `docs/EXTENDING.md`. Deferred features
(`docs/ROADMAP.md`) keep their extension point ready but are not implemented.

## Domain modules

- **`core.optimize`** — `interfaces` defines the registries
  (`return_estimators`, `covariance_estimators`, `objectives`, `constraints`,
  `solvers`) with the sample mean, sample covariance, `min_variance`,
  `max_sharpe`, `equal_weight` and `inverse_volatility` objectives, the
  `max_weight` and `cash_reserve` constraints and the SciPy SLSQP solver.
  Long-only and fully invested are always enforced; lot rounding uses
  `market_rules`. `engine.optimize` runs the single-shot path, while
  `frontier.build_efficient_frontier` draws a long-only, `max_weight`-capped
  Dirichlet cloud (default 5,000 portfolios, hard cap 100,000, explicit seed),
  sweeps target returns between the minimum-variance and best single-stock
  returns to build the exact frontier, and returns the minimum-variance,
  maximum-Sharpe (tangency), equal-weight and current-portfolio points with
  integer lots and residual cash. A large cloud is simulated in full and the API
  plots a stratified sample of it (`frontier.stratified_cloud_indices`, default
  6,000 points): the statistics and the marked portfolios use every draw, only the
  scatter is sampled. `guardrails` holds the default cap and size
  warnings.
- **`core.risk`** — a `RiskMetric` registry (annualized volatility, maximum
  drawdown with its series, beta, Sharpe, Treynor, Jensen's alpha, historical
  VaR and the correlation matrix) plus `compute_risk` / `compute_benchmark_risk`
  and a growth-of-100 `Performance` block. The risk-free rate is a parameter
  supplied from `UserSettings`, never a module constant.
- **`core.pnl`** — `compute_pnl` (cost basis, market value, unrealized P&L in VND
  and percent, weight, share of total P&L and the net-of-costs figure) and
  `compare_buy_return` for dated holdings against a benchmark. Pure functions
  over holdings plus prices.
- **`core.rebalance`** — `CostModel` registry (`vn`: the user's brokerage fee on
  both sides plus the market sell tax on sells) and `RebalancePolicy` registry
  (`full`, `threshold_band`). The `rebalance` engine plans sells before buys,
  never oversells, rounds to lots, skips orders below a minimum notional and
  funds buys from cash plus proceeds.
- **`core.universe`** — `UniverseFilter` registry (`exchange`, `min_adv`,
  `exclude_suspended`, `exclude_stale_prices`, `min_history`) and `build_universe`,
  returning aligned price/returns matrices plus ADV, quality flags (suspension,
  delisting, staleness, missing data, liquidity) and dropped-ticker reasons.
  `exclude_suspended` drops only an authoritative suspension or delisting; a trailing
  price bar is `stale` and is dropped as `stale_price_data`, never `suspended`.
- **`core.portfolio`** — holdings and cash valuation shared by the Portfolio,
  P&L and Rebalance pages.

## Data layer

`packages/data` loads Vietnamese daily prices anonymously (no account, login, API
key or token) and stores them for the optimizer. See `docs/DATA.md` for the full
guide and ADR 0002 for the rationale.

- **Providers** (`data/providers/`): KBS (primary), VCI, DNSE, TCBS and SSI iBoard, each one
  file implementing the `DataProvider` protocol and registered in `data.registry`.
  All are unofficial and return raw (unadjusted) prices.
- **Reference data** (`data/seed.py`): a small stock/VN30 snapshot written by
  `SyncService.sync_reference_data()` only when every provider fails
  `list_symbols`/`get_index_constituents` on an empty table, so ticker search and
  the Optimize page's "Start from VN30" button work offline or on restricted
  networks.
- **Failover chain** (`data/fallback.py`): tries providers in `PROVIDER_ORDER`
  (settings, default `kbs,vci,dnse,tcbs,ssi_iboard`), retries with backoff, validates each
  response, detects stale data, skips a repeatedly failing provider for a cooldown
  (circuit breaker) and never splices two providers into one series.
- **Persistence** (`data/db/`): SQLAlchemy 2 models behind repository interfaces,
  with an Alembic migration; SQLite locally, Postgres in production via
  `DATABASE_URL`.
- **Sync** (`data/sync.py`, `data/jobs/sync.py`): incremental, idempotent; driven
  by `python -m data.jobs.sync` or the protected `POST /api/v1/data/refresh`
  endpoint, which Vercel Cron calls after the Vietnam close.
- **Quality checks** (`data/quality.py`): a registry of checks producing a
  `QualityReport` per symbol.

## Configuration

Configuration has three distinct homes:

1. **Process settings** — `core.settings.Settings`, a `pydantic-settings`
   model that reads environment variables prefixed `VNOPT_` (see
   `.env.example`). This is the only place environment values are read.
2. **User settings** — `core.settings.UserSettings`: the brokerage fee rate
   (per side, validated to 0–0.01) and the annual risk-free rate (validated to
   0–0.20), both with placeholder defaults. These are *user* values: they travel
   with every API request and are stored in the browser, never hardcoded as
   constants.
3. **Market rules** — `core.market_rules.DEFAULT_MARKET_RULES`: lot size per
   exchange (100), sell tax (0.1%), daily price limits (HOSE 7%, HNX 10%,
   UPCoM 15%) and the trading-holiday set. The price limits and holidays are
   recorded for V1 but not yet consumed by any feature.

## API

The API is versioned under `/api/v1`:

```
GET  /api/v1/health                 ->  { "status": "ok", ... }
GET  /api/v1/settings               ->  default settings + allowed bounds
POST /api/v1/risk                   ->  one portfolio's metrics + performance
POST /api/v1/risk/compare           ->  current / optimized / equal-weight / benchmark blocks
GET  /api/v1/risk/options           ->  metric catalogue, benchmarks and defaults
POST /api/v1/risk/sharpe            ->  Sharpe ratio + assumptions
POST /api/v1/portfolio/evaluate     ->  holdings valued at latest prices (+ freshness, warnings)
POST /api/v1/pnl/evaluate           ->  cost basis, unrealized P&L, net-of-costs value, per-holding rows
POST /api/v1/rebalance/cost         ->  brokerage cost + assumptions
GET  /api/v1/rebalance/options      ->  cost-model + policy catalogue + defaults
POST /api/v1/rebalance              ->  order list, positions, costs, turnover, residual cash
GET  /api/v1/optimize/options       ->  optimizer catalogue + frontier defaults
POST /api/v1/optimize/frontier      ->  cloud, exact frontier and marked points (lots, residual cash)
POST /api/v1/optimize               ->  single-shot weights, integer lots, statistics, assumptions
GET  /api/v1/symbols?exchange=      ->  stored symbols
GET  /api/v1/prices/{symbol}        ->  daily prices (on-demand backfill)
GET  /api/v1/data/index/{code}      ->  benchmark daily prices
POST /api/v1/data/backfill          ->  per-symbol on-demand backfill
GET  /api/v1/universe/options       ->  universe filter catalogue + presets
POST /api/v1/universe/build         ->  aligned universe (+ dropped reasons)
GET  /api/v1/universe/presets/{id}  ->  index preset constituents
GET  /api/v1/data/quality/{symbol}  ->  QualityReport
GET  /api/v1/data/providers/status  ->  provider health + failover state
GET  /api/v1/data/freshness         ->  latest price date + freshest source (V1/V2)
GET  /api/v1/data/probe             ->  (protected) provider probe
POST /api/v1/data/refresh           ->  (protected) incremental sync batch
```

The compute `POST` routes (`risk`, `risk/compare`, `pnl/evaluate`, `rebalance`,
`optimize`, `optimize/frontier`) accept an optional `settings` object (defaults
apply when it is missing) and echo the values and data assumptions they used in an
`assumptions` block. Routes hold no business logic: they validate input, call into
`core`/`data` and return typed (Pydantic) responses.

## Web

The Next.js app (App Router) renders six pages — `Portfolio`, `P&L`, `Optimize`,
`Risk`, `Rebalance` and `Settings` — behind a shared layout with navigation and
the footer disclaimer. The home page calls `GET /api/v1/health` through a Next.js
rewrite that proxies `/api/*` to the FastAPI server, so no CORS setup is required
during development. A data-freshness badge in the header reads
`GET /api/v1/data/freshness` and shows the latest stored price date (across the V1
and V2 stores), the provider that owns that freshest bar and any failover or stale
warnings.

### One persisted store

`apps/web/lib/app-store.ts` defines the whole shared state — active portfolio and
the named-portfolio library, the built universe (symbols, dates, filters and the
full result), the last optimization result, the chosen ("optimized") portfolio and
the user's settings — under a single `localStorage` key (`vnopt.app`) with
`APP_STORAGE_SCHEMA_VERSION`. `app-store-context.tsx` hydrates it before rendering
page content (a loading state prevents an empty flash), saves on every change and
migrates the legacy per-feature keys once. A payload with a different version or an
unreadable shape is discarded instead of crashing, and `resolveWorkingPortfolio`
fills the working portfolio from the active saved snapshot when the working copy is
empty. Pages consume typed selector hooks — `usePortfolio`, `useUniverse`,
`useOptimize` (which also exposes the chosen weights) and `useUserSettings` — and
never keep their own copy of shared data.

### Pages

`Portfolio` is the first entry: holdings (ticker, whole shares, optional average
cost and buy date) and cash are edited there, `POST /api/v1/portfolio/evaluate` is
debounced to value them at the latest closes, and the page offers CSV/JSON
import/export, a live value/weight table, a liquidity warning (average daily traded
value below 1 billion VND) and saved portfolios that load into every other page.

`P&L` posts the same holdings (plus optional buy dates) to
`POST /api/v1/pnl/evaluate` and shows summary cards (market value, cost basis,
unrealized P&L in VND and percent, P&L after sell costs, cash and total value), a
per-holding table, P&L-by-stock and market-value-versus-cost charts and
winners/losers. It needs holdings plus average cost only; a missing cost or price
is listed with a prompt instead of failing the page.

`Optimize` is one guided flow: stocks (seeded from the portfolio, ticker search or
"Start from VN30", with fixed sensible filters applied by
`POST /api/v1/universe/build`), money (portfolio value including cash, or new
money), a timeframe (6M, 1Y, 2Y, 3Y, 5Y, Max or a custom range), a goal
(`min_variance`, `max_sharpe` or `equal_weight`) and a single "Find my portfolio"
button that calls `POST /api/v1/optimize/frontier`. The resolved `start`/`end`
are used for the universe build and the frontier, so the kept/dropped tickers and
the estimates describe the same window. The result shows the Monte Carlo cloud,
the exact frontier, the minimum-variance, maximum-Sharpe, equal-weight and
current-portfolio markers, a capital allocation line from the user's risk-free
rate, and a risk slider that updates weights, lots (built from `market_rules` lot
sizes), residual cash, expected return, volatility and Sharpe; clicking a point
on the frontier moves the slider. Advanced settings (max weight, benchmark, VaR
confidence, portfolio count and seed) sit behind a toggle. "Use this portfolio"
writes the chosen mix to the store for Risk and Rebalance.

`Risk` calls `POST /api/v1/risk/compare` with its own timeframe (6M..Max or
custom, independent of Optimize) and the current and optimized weights, and shows
the current, optimized, equal-weight and benchmark portfolios side by side: metric
cards for volatility, beta, Sharpe, Treynor, Jensen's alpha, maximum drawdown and
historical VaR (with plain-language tooltips), a growth-of-100 chart, a drawdown
chart and a correlation heatmap. The risk-free rate travels with the request from
`UserSettings`. Both tabs keep their timeframe in the shared persisted store and
validate it in the browser before calling the API; charts use Recharts with
labelled axes, tooltips and click/zoom interactions.

`Rebalance` pre-fills holdings and cash from the store and starts its target
weights from the chosen optimized mix (`chosenPortfolio`) or, when there is none,
from the current weights; both stay editable and a "Use optimized weights" button
re-applies the saved mix. `GET /api/v1/rebalance/options` publishes the cost models
(`vn`) and policies (`full`, `threshold_band`) with their parameter schemas, and
`POST /api/v1/rebalance` returns current-versus-target positions, a placeable order
list (sells before buys, whole lots, reference price, value, fee, tax), the total
cost, turnover and residual cash, plus an assumptions block. CSV import and order
export are supported; prices are the latest close and T+2 settlement is not modeled
in V1.

`Settings` edits the brokerage fee and risk-free rate in percent. The values live
in the same persisted store, are attached to every compute request, and the
defaults and bounds come from `GET /api/v1/settings`, so the UI never hardcodes
them. Every results page shows an active-settings badge.

## Typed web client

`apps/web/lib/api.ts` is the runtime client and its payload types are derived
from `apps/web/lib/schema.d.ts`, which is generated from the FastAPI OpenAPI
document (`apps/api/openapi.json`) by `make client`. `make check` includes
`make client-check`, which regenerates both and fails on any difference. A change
to an API model therefore reaches the UI as a TypeScript error instead of a
runtime surprise.

## V2 precompute pipeline

`packages/data/data/v2/` holds the keyless adapter layer (SSI iBoard `statistics`,
KBS, VCI) and the failover runner. On top of it,
`data.v2.precompute.V2PrecomputeService` builds the online datasets into additive
V2 tables (migration `0002_v2_precompute`): the cleaned ticker master with ICB
level-2 sectors, VN30/VN100 membership with an as-of date, VN-Index/VN30/VN100
benchmarks, adjusted daily prices with matched volume/value, rolling 20-session
ADTV/ADV medians, shares outstanding + full market cap, and corporate actions.
Every row carries `data_as_of`, its provider and the adjustment/volume/market-cap
basis. The pipeline is resumable (per-ticker commits + `v2_progress`), incremental
(only new dates) and pre-screens the universe with KBS volume before the SSI
calls; the call budget is in `docs/V2_DATA_GAPS.md` and the choices are in
`docs/DECISIONS.md`. A limited run spends its slots on tracked tickers first, then
unpriced `VN100`/`VN30` members, then the rest, and only on tickers that survive
the pre-screen. Without an explicit `--as-of` the run retargets itself to the last
published `VNINDEX` session when today's upstream EOD bars have not settled yet,
so the quality gate keeps reporting real data defects. It runs from
`python -m data.v2.jobs.precompute` locally and
from `.github/workflows/precompute_v2.yml` on a GitHub runner (heavy backfill is
never placed in a short serverless function). `data.v2.reader.V2Reader` and the
`GET /api/v1/v2/ticker/{symbol}` route return a ticker's adjusted returns,
liquidity, market cap and sector for a range.

On top of those tables, `data.v2.analytics.universe_service.UniverseService` backs
two read-only routes: `GET /api/v1/v2/universe` (the preset plus sector ICB
level-2, VN30/VN100 and exchange facets, calling the same `filter_universe` the
analytics engine uses, and returning `data_as_of`, the basis flags, kept/rejected
tickers, stored adjustment-quality flags and warnings) and `GET /api/v1/v2/sectors`
(total and preset-passing constituent counts). Both read only the V2 tables and
return `available: false` with a clear "V2 data not available" message on an empty
database, so V1 keeps working. The Optimize tab's `UniverseFilterPanel` renders the
shared `v2Filter` (preset, sectors, indexes, exchange, benchmark, exclude-flagged)
from the single app store and calls those routes; the frontend never re-implements
filtering. Adjustment-quality flags are precomputed by the pipeline into
`v2_adjustment_flags` (migration `0003_v2_adjustment_flags`) so a read endpoint never
recomputes them per request; `flags_available` separates "not computed yet" from
"no flags". The `max_sector_weight` constraint is registered like the others and is
applied to both the exact frontier and the random cloud; `Settings.max_optimize_stocks`
(default 30) caps how many tickers the Optimize tab sends and is published on
`GET /api/v1/optimize/options`.

## Deployment

The app deploys as two Vercel projects from this folder (CLI, no Git); the full
steps, verified limits and the measured bundle size are in
`docs/DEPLOYMENT.md`.

- **API** (deployed from the repository root; Vercel FastAPI preset with the
  root entrypoint `asgi.py`, which re-exports `apps/api/app/main.py`): the
  preset serves the whole app from one function with the original request paths,
  so `vercel.json` needs no `rewrites`; it excludes
  `apps/web`/`node_modules`/tests from the bundle, sets `maxDuration` on the
  resolved entrypoint and schedules the nightly sync cron; the root
  `pyproject.toml` declares the runtime dependencies (Vercel prefers it over
  `requirements.txt`) and `asgi.py` adds the `apps/api`, `packages/core` and
  `packages/data` sources to `sys.path` (the Python runtime allows a 500 MB
  uncompressed bundle).
- **Web** (`apps/web`): `next.config.mjs` proxies `/api/*` to `API_URL`;
  `vercel.json` sets the framework and the `sin1` region.
- Set `DATABASE_URL` (Postgres in production), `PROVIDER_ORDER`,
  `REFRESH_TOKEN`/`CRON_SECRET` on the API and `API_URL` on the web project.

## Local workflow

```
make install     # editable Python installs + web dependencies
make dev         # uvicorn (8000) + Next.js (3000) together
make test        # pytest
make lint        # ruff + web lint
make typecheck   # mypy + tsc
make check       # the full gate used before committing
```
