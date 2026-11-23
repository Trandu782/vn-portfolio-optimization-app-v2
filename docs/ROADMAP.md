# Roadmap

Features are grouped by release. Items listed here are **deferred**: they are
not implemented yet. Where an item implies a new variable concept, its extension
point (an interface plus a `Registry`) is added ahead of the implementation, but
the feature itself waits.

## V1.1 — current

- Monorepo: `apps/web`, `apps/api`, `packages/core`, `packages/data`.
- Generic `Registry[T]` with `register`, `get`, `list`, `describe`.
- Settings (`pydantic-settings`), user settings and market rules.
- User-controlled brokerage fee and risk-free rate: validated `UserSettings`,
  core `sharpe_ratio` / `commission` functions, settings echo in API responses,
  and a web Settings page backed by the persisted store.
- `GET /api/v1/health`; web home page shows the API health.
- **One persisted client store** (`apps/web/lib/app-store.ts`, schema-versioned,
  hydrated through `app-store-context.tsx`): active portfolio and named library,
  built universe, per-tab timeframes, optimization result, chosen (optimized)
  portfolio and user settings. Every page reads it on mount, an incompatible
  payload is discarded instead of crashing, and leaving a page and coming back
  loses nothing.
- Six pages (Portfolio, P&L, Optimize, Risk, Rebalance, Settings), shared layout,
  navigation and the disclaimer on every results page.
- **Universe selection**: `UniverseFilter` registry (`exchange`, `min_adv`,
  `exclude_suspended`, `min_history`), `build_universe` returning aligned price /
  returns matrices plus ADV, quality flags and dropped-ticker reasons, curated
  index presets (VN30) from `data.presets`, `POST /api/v1/universe/build`,
  `GET /api/v1/universe/options`, `GET /api/v1/universe/presets/{code}` and
  `POST /api/v1/data/backfill`. The standalone Universe page was folded into
  Optimize in V1.1; the endpoints remain because Optimize calls them.
- **Shared portfolio**: `core.portfolio` (`Holding`, `Portfolio`,
  `portfolio_value_and_weights`), `POST /api/v1/portfolio/evaluate`, a web Portfolio
  page (persisted store, CSV/JSON import/export, live value/weight table, optional
  buy dates and a liquidity warning below 1 billion VND average daily value).
- **P&L**: `core.pnl.compute_pnl` values holdings at the latest close from
  average cost alone and returns cost basis, unrealized P&L in VND and percent,
  weight, share of total P&L, cash and the "P&L if sold today" figure net of the
  user's brokerage fee and the market sell tax; `compare_buy_return` compares a
  dated holding with a benchmark; `POST /api/v1/pnl/evaluate`; and a P&L page with
  summary cards, a per-holding table and charts. Realized P&L, dividends and a
  transaction log stay deferred.
- **Rebalance engine**: `core.rebalance` with a `CostModel` registry (the `vn` model
  charges the brokerage fee from `UserSettings` on both sides and the 0.1% sell tax
  from `market_rules` on sells) and a `RebalancePolicy` registry (`full` and
  `threshold_band` with a drift band and an optional turnover cap); the pure
  `rebalance` engine plans sells before buys, never oversells, rounds to lots, skips
  orders below a minimum notional and funds buys from cash plus proceeds;
  `GET /api/v1/rebalance/options` and `POST /api/v1/rebalance`; and a web Rebalance
  page with editable pre-filled holdings, target weights that start from the chosen
  optimized mix (still editable), CSV import/export, a current-versus-target chart,
  an orders table and a cost summary. T+2 settlement stays deferred.
- **Optimization engine**: `core.optimize` registries for sample return and
  covariance estimators, objectives, constraints and solvers; a SciPy SLSQP solver
  that always enforces long-only and fully invested; lot rounding from
  `market_rules`; `core.optimize.frontier` (Dirichlet cloud, exact frontier and
  the minimum-variance, tangency, equal-weight and current-portfolio points);
  `POST /api/v1/optimize/frontier`, `POST /api/v1/optimize` and
  `GET /api/v1/optimize/options`; and a guided web Optimize page with a risk
  slider, a "Use this portfolio" button and an in-sample warning. See
  `docs/EXTENDING.md`.
- **Risk analytics**: `core.risk` with a `RiskMetric` interface plus the
  `risk_metrics` registry (annualized volatility, maximum drawdown with the
  drawdown series, beta against a benchmark, Sharpe, Treynor and Jensen's alpha
  using the user's risk-free rate, historical VaR with a configurable confidence
  and the correlation matrix), the pure `compute_risk` engine with a growth-of-100
  performance block, `GET /api/v1/risk/options`, `POST /api/v1/risk` and
  `POST /api/v1/risk/compare`, and a Risk page that compares the current,
  optimized, equal-weight and benchmark portfolios side by side with metric cards,
  a historical performance chart, a drawdown chart and a correlation heatmap.
- **Data layer**: anonymous VCI / KBS / DNSE / TCBS / SSI iBoard providers behind a
  `DataProvider` protocol and registry; a failover chain with retry, validation,
  stale detection, a circuit breaker and cross-provider overlap checks; SQLAlchemy
  2 + Alembic persistence in SQLite/Postgres; incremental sync via
  `python -m data.jobs.sync` and the protected `/api/v1/data/refresh` endpoint
  (Vercel Cron); data-quality checks; `/api/v1/symbols`, `/api/v1/prices`,
  `/api/v1/data/quality`, `/api/v1/data/providers/status` and `/api/v1/data/probe`;
  a web data-freshness badge. See `docs/DATA.md` and ADR 0002.

## Removed in V1.1 (may return in V2)

V1.1 simplifies the product to CFA Level 1/2 methods. These V1 features were
deleted (code, registry entries, API options, UI, tests and docs) rather than
hidden; each may return in V2.

- **Walk-forward backtest** (`core.backtest`): the `RebalanceSchedule`,
  `SlippageModel` and `BacktestMetric` registries, `run_backtest`, lookback /
  slippage parameters, the `POST /api/v1/backtest` routes and the backtest UI.
- **Monte Carlo simulation** (`core.montecarlo`): the `ReturnSimulator` registry,
  `block_bootstrap`, `multivariate_student_t`, resampled optimization, forward
  simulation and the `POST /api/v1/montecarlo/{mode}` routes plus the Simulation
  page. (A fresh Dirichlet frontier + exact efficient frontier lands in Optimize.)
- **Ledoit-Wolf and EWMA estimators**: sample mean and sample covariance only.
- **Risk parity** objective; **Euler risk contribution** and **CVaR** risk metrics.
- **Max-holdings and ADV-cap** constraints; the ADV cap becomes a Portfolio-page
  liquidity warning.

## V2 — future extension points

Each item names the interface or registry it will plug into. V1 ships the
extension point where it already exists; the feature itself is not implemented.

- **Authenticated SSI FastConnect provider** → a new file in
  `packages/data/data/providers/` registered in `data.registry.data_providers`.
  It is opt-in; the anonymous providers stay the default and
  `data/fallback.py` needs no change.
- **Auto-fetched risk-free rate** → a new `RiskFreeRateProvider` registered in
  `core.optimize.interfaces.risk_free_rate_providers` (V1 ships
  `user_settings`).
- **Broker trade import and realized P/L** → a transaction log on
  `core.portfolio.Portfolio` plus a new function in
  `packages/core/core/pnl.py`; the API extends `POST /api/v1/pnl/evaluate`
  (unrealized P&L already ships in V1.1).
- **Market-cap filter** → a new `UniverseFilter` in
  `packages/core/core/filters/` registered in `core.universe.universe_filters`.
- **Sector data and sector caps** → a sector `UniverseFilter` (as above) plus a
  `Constraint` in `packages/core/core/optimize/constraints/` registered in
  `constraints`.
- **Fundamentals, free-float and foreign-room constraints** → new `Constraint`
  modules in `packages/core/core/optimize/constraints/` registered in
  `constraints`.
- **Target-return objective** → a new `Objective` in
  `packages/core/core/optimize/objectives/` registered in `objectives`.
- **Minimum-holdings constraint** → a new `Constraint` registered in
  `constraints` (a cardinality constraint; the solver may need a penalty form).
- **T+2 settlement and price-limit simulation** → a `CostModel` in
  `packages/core/core/rebalance/cost_models/` registered in `cost_models`, plus
  the existing `market_rules` price limits.
- **Stress tests** → new `RiskMetric` modules in
  `packages/core/core/risk/metrics/` registered in `risk_metrics`.
- **What-if analysis and strategy comparison** → depends on the walk-forward
  backtester removed in V1.1 (rebuilt as a `BacktestMetric` registry plus
  `run_backtest`); may return in V2.
- **Corporate-action calendar** → a new `DataProvider` capability and a
  `core.market_rules` helper; the reserved `corporate_actions` table exists.

## V3 — future

- **Black-Litterman return estimation** → a new `ReturnEstimator` in
  `packages/core/core/optimize/return_estimators/` registered in
  `return_estimators`.
- **Hierarchical Risk Parity (HRP)** → a new `Objective` in
  `packages/core/core/optimize/objectives/` registered in `objectives`.
- **CVaR optimization** → a new `Objective` in
  `packages/core/core/optimize/objectives/` registered in `objectives` (the CVaR
  `RiskMetric` was removed in V1.1 and may return in V2).
- **Additional Monte Carlo models** (regime-switching, copula) → depends on the
  `ReturnSimulator` registry and Monte Carlo engine removed in V1.1; may return
  in V2.
- **Saved scenarios** → a persisted store beside the named saved portfolios in
  `apps/web/lib/portfolio.ts`, and a repository in `packages/data/data/db/`.
- **PDF / Excel reports** → new routes in `apps/api/app/api/v1/` that reuse the
  existing core results; no registry change.
- **Accounts** → a persistence layer in `packages/data/data/db/` and auth
  middleware in `apps/api/app/main.py`; user settings move from `localStorage`.
- **Alerts** → a scheduled job beside `packages/data/data/jobs/sync.py` that
  reuses the `RiskMetric` registry (the `BacktestMetric` registry was removed in
  V1.1).
- **Job queue** → the existing `python -m data.jobs.sync` entry point becomes a
  worker; no registry change.
- **Factor-exposure analysis** → new `RiskMetric` modules in
  `packages/core/core/risk/metrics/` registered in `risk_metrics`.
