# Project rules: VN Portfolio Optimizer 

Purpose: personal portfolio optimizer for Vietnamese stocks (HOSE, HNX, UPCoM). Decision support only, not financial advice.

## Architecture (ports and adapters)
- packages/core: pure Python domain logic (mean-variance optimization, efficient frontier, risk metrics, P&L, rebalance). No web, DB or network imports. Only numpy, pandas, scipy.
- packages/data: data providers (KBS primary, then VCI, DNSE, TCBS and SSI iBoard; all anonymous public endpoints), repositories, DB models, sync jobs.
- apps/api: thin FastAPI layer. Routes validate input, call core/data, return typed responses. No business logic here.
- apps/web: Next.js + TypeScript UI. Talks to the API only through a generated typed client. ONE persisted client store (`apps/web/lib/app-store.ts`, consumed through `apps/web/lib/app-store-context.tsx`) holds the active portfolio, the named-portfolio library, the built universe, the optimization result, the chosen (optimized) portfolio and the user settings; every page reads its shared inputs from there and no page keeps its own copy. Bump `APP_STORAGE_SCHEMA_VERSION` when the stored shape changes and discard or migrate incompatible payloads instead of crashing.
- docs/: ARCHITECTURE.md, EXTENDING.md, ROADMAP.md, CHANGELOG.md, adr/ for decisions.

## Extension rules (most important)
- Every variable concept is an interface plus a registry: DataProvider, ReturnEstimator (sample mean), CovarianceEstimator (sample covariance), Objective, Constraint, RiskMetric, CostModel, RebalancePolicy, UniverseFilter.
- Adding a feature = one new file implementing the interface + one registration. Never add a variant by editing an if/else or switch chain.
- Each registry entry exposes id, display name, description and a Pydantic parameter schema. The API publishes these so the UI renders options from the API instead of hardcoding them.
- Deferred features (docs/ROADMAP.md) get their extension point ready but are NOT implemented.
- Data providers must work anonymously: no registration, API key, token or login for any data source. If an endpoint starts requiring one, fail with a clear error and fail over to the next provider. The default failover order is `PROVIDER_ORDER=kbs,vci,dnse,tcbs,ssi_iboard` (KBS first); a small built-in symbol/VN30 seed may only be used when every live provider fails on an empty database.

## Scope
- Only CFA Level 1/2 methods: mean, variance, covariance, correlation, beta, Sharpe, Treynor, Jensen's alpha, maximum drawdown, historical VaR, minimum-variance and tangency (maximum-Sharpe) portfolios, the efficient frontier, plus equal weight and inverse volatility.
- Removed in V1.1 and not reintroduced without a roadmap change: Ledoit-Wolf/EWMA estimators, risk parity, Euler risk contribution, CVaR, max-holdings and ADV-cap constraints, Monte Carlo simulators and their modes, the walk-forward backtest, rebalance schedules/slippage/lookback, and the standalone Universe and Simulation pages.

## Code standards
- Python 3.12, full type hints, Pydantic v2 for every API and domain schema, ruff and mypy clean.
- Order amounts in VND as integers or Decimal; floats only for statistics.
- Every module has unit tests. Randomness uses explicit seeds. Tests never touch the network (use recorded fixtures).
- One settings module (pydantic-settings) reads env vars. No hardcoded secrets, URLs or magic numbers. Sell tax, lot size, price limits and holidays live in a market_rules config. The brokerage fee rate and the risk-free rate are USER SETTINGS, never constants: defaults live in UserSettings, the user's values travel with every API request and are saved in the browser, and core functions take them as parameters.
- API is versioned under /api/v1. DB changes only through Alembic migrations.
- Keep the serverless bundle small: no cvxpy, scikit-learn or torch. Use numpy/scipy; the estimators are the sample mean and sample covariance only (no Ledoit-Wolf, no EWMA).
- Small functions, docstrings that state assumptions, no dead code.

## Workflow
- Do only the requested task. State a short plan before coding.
- After coding: run lint, type check and tests; summarize files changed and anything left undone.
- Update docs/CHANGELOG.md and any affected docs in every task.
- Ask before adding a dependency and justify its size.