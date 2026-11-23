# Cline Prompt: VN Portfolio Optimizer V1.1 — Fix, Simplify, Frontier, P&L

Work in the existing monorepo (packages/core, packages/data, API, web). Keep the registry pattern, the KBS-first data layer with failover, UserSettings (fee rate, risk-free rate) and the disclaimer on every results page. Do the steps in order. After each step run ruff, mypy, pytest and the web lint/type check, fix failures, and add a line to docs/CHANGELOG.md. Do not ask me questions; where something is ambiguous, pick the simplest option and note it in the changelog.

Target user: a non-financial person. Target methods: only what is taught in CFA Level 1/2 (mean, variance, covariance, correlation, beta, Sharpe, Treynor, Jensen's alpha, max drawdown, historical VaR, minimum-variance and tangency portfolios, efficient frontier). Anything more complex is removed.

---

## Step 1 — Fix shared state and known bugs (do this first)

Problem: the built universe disappears when I leave the Universe page and come back; the saved portfolio "Test" is marked active with 3 holdings but the Portfolio table, Optimize capital (shows 0 VND) and Rebalance are empty. Pages keep their own state and the shared store only holds a summary.

1. Create ONE persisted client store (Zustand with persist, or equivalent) that holds: active portfolio (holdings, cash), selected symbols, date range, last universe result, last optimization/frontier result, chosen portfolio ("optimized"), and settings. Every page reads from it on mount; no page keeps its own copy of this data.
2. Handle Next.js hydration: do not render stateful content until the store has hydrated (show a loading state), so nothing flashes empty and nothing overwrites saved data.
3. Add a schema version and a migration that discards the old incompatible stored universe instead of crashing.
4. Loading a saved portfolio must fill the working portfolio everywhere.
5. If a saved config exists but no result is cached, rebuild automatically on mount.
6. Fix: ticker search returns HTTP 500 (find the root cause in the API logs; the offline fallback symbol list from the data layer must make search work even when providers fail); the "Trading Days" field is shown twice on Optimize; grammar such as "This universe are"; missing section headings on Risk & Backtest.
7. Tests: build the universe, navigate away and back, tickers and results are still there; load a saved portfolio and check the Portfolio, Optimize and Rebalance pages see its holdings and capital.

## Step 2 — Remove complex methods

Delete (code, registry entries, API options, UI, tests, docs) rather than hiding:
- Ledoit-Wolf and EWMA estimators, and the estimator dropdowns. Use sample mean and sample covariance only (annualized with 252 days).
- Risk parity objective; Euler risk contribution; CVaR.
- Max-holdings and ADV-cap constraints. Replace the ADV cap with a simple liquidity warning on the Portfolio page (flag a holding whose average daily traded value is below a threshold, default 1 billion VND).
- block_bootstrap, multivariate_student_t, resampled optimization, forward simulation and the old Monte Carlo modes/endpoints.
- The walk-forward backtest engine, rebalance schedules, slippage and lookback parameters.
- The Universe page (folded into Optimize, see Step 3) and the Simulation page (folded into Optimize, see Step 4).
Keep: Objective, Constraint, RiskMetric and CostModel registries, with only the entries listed below. Update docs/EXTENDING.md and ROADMAP.md (list removed items as "removed in V1.1, may return in V2"). Keep inverse_volatility only if it is already registered and tested; it is not required.

## Step 3 — Simple mode and navigation

Navigation: Portfolio · P&L · Optimize · Risk · Rebalance · Settings.

1. Optimize is one guided page, in plain language, top to bottom:
   a. Stocks to consider: defaults to the portfolio's tickers; ticker search to add more; a "Start from VN30" button. The universe builds automatically (no Build button). Apply fixed sensible filters (HOSE/HNX/UPCoM allowed, at least 2 years of history preferred, exclude suspended or delisted) and show dropped tickers with a one-line reason. Date range defaults to the last 3 years.
   b. Money: "Use my holdings (including cash)" or "New money" with a typed amount.
   c. Goal, three plain choices: "Lowest risk" (minimum variance), "Best return for the risk" (maximum Sharpe), "Equal split" (equal weight baseline).
   d. A single "Find my portfolio" button that runs everything.
2. An "Advanced settings" toggle (off by default) reveals: max weight per stock, benchmark, VaR confidence, number of random portfolios, seed. Nothing else.
3. Use plain labels with a (?) tooltip for every metric (e.g. "Volatility: how much the value swings", "Worst expected day: loss you should only exceed on 1 in 20 days", "Sharpe: return per unit of risk, higher is better"). Add one plain-English summary sentence above every result.
4. Max weight default = max(25%, 1.5 / number of stocks). If n × cap < 100%, raise the cap automatically and tell the user. Guardrails: warn below 5 stocks (frontier is not meaningful) and above 20 (sample covariance gets unreliable); hard cap 30 stocks with a clear message.

## Step 4 — Efficient frontier with Monte Carlo (core of Optimize)

Implement in packages/core/optimize (and remove packages/core/montecarlo old code):
1. Objectives (registry): min_variance, max_sharpe (risk-free rate from UserSettings), equal_weight. Constraints (registry): long_only and fully_invested (always on), max_weight. scipy.optimize solver behind the existing Solver interface.
2. Random portfolios: Dirichlet-sampled long-only weights that respect max_weight (rejection sampling or iterative capping), default 5,000, hard cap 20,000, explicit seed, vectorized numpy, time budget from config. For each, compute annual return, volatility and Sharpe.
3. Exact efficient frontier: sweep ~40 target returns between the min-variance return and the best single-stock return, solving minimum variance for each target. This curve is "the efficient frontier"; the random cloud shows why it is the upper-left edge. If the optimizer fails for a target, skip it and report how many points were skipped.
4. Mark on the chart: minimum-variance portfolio, maximum-Sharpe (tangency) portfolio, equal-weight portfolio, and the user's current portfolio. Show the capital allocation line from the risk-free rate to the tangency portfolio.
5. Risk slider: moving along the frontier updates weights, lots (using lot sizes from market_rules and the money chosen), residual cash, expected return, volatility and Sharpe. Presets jump to min-variance and max-Sharpe.
6. "Use this portfolio" button saves the chosen weights to the store as the optimized portfolio used by Risk and Rebalance.
7. Result schema includes an assumptions block (data source, date range, raw/unadjusted prices, risk-free rate, sample estimates, seed) and an in-sample warning.
8. API: POST /api/v1/optimize/frontier and GET /api/v1/optimize/options. Regenerate the typed web client.
9. Tests: analytical two-asset minimum-variance weights; every frontier and random portfolio sums to 1 and respects max_weight; frontier volatility is non-decreasing in return; same seed gives identical results; infeasible settings return a clear error; the tangency portfolio's Sharpe is at least as high as every random portfolio's.

## Step 5 — Risk page (replaces Risk & Backtest)

1. RiskMetric registry with only: annualized volatility, beta vs benchmark, Sharpe, Treynor, Jensen's alpha, max drawdown (with series), historical VaR (confidence configurable, default 95%), correlation matrix.
2. Benchmark defaults to VN-Index (selector offers VN-Index, VN30, HNX-Index, UPCoM-Index in Advanced).
3. Compare side by side: current portfolio, optimized portfolio, equal weight, and the benchmark. Metric cards with plain-language tooltips, drawdown chart, correlation heatmap.
4. Replace the backtest with a simple "historical performance" chart: growth of 100 for each portfolio vs the benchmark using fixed weights over the selected date range (state the assumption: weights held constant, no costs, raw prices, in-sample). Show total return, annualized return and max drawdown.
5. Tests against hand-computed examples for each metric (Sharpe, Treynor and alpha included, with the risk-free rate from Settings).

## Step 6 — P&L page (assume I have NO trade log)

Do not build a transaction log or any CSV trade import. P&L is computed from the Portfolio holdings only.

1. packages/core/pnl: for each holding with shares > 0 and avg_cost > 0 compute cost basis (shares × avg_cost), market value (latest close), unrealized P&L in VND and %, weight, and share of total P&L. Include cash. Also compute "P&L if sold today, net of costs" using the fee rate from UserSettings and the 0.1% sell tax from market_rules. Holdings without avg_cost show a clear "enter your average cost" prompt and are excluded from totals, with a count of how many are excluded.
2. Add an optional buy date to each holding (Portfolio page and CSV: symbol, shares, avg_cost, buy_date). When a buy date exists, show the stock's price return since that date vs VN-Index over the same period ("beat the market?").
3. API: POST /api/v1/pnl/evaluate. Page "P&L": summary cards (market value, cost basis, unrealized P&L VND and %, P&L after sell costs, cash, total value), a per-holding table, a bar chart of P&L by stock, a market value vs cost chart. Winners and losers highlighted with colour plus a sign (+/−), not colour alone.
4. Notes shown on the page: realized profit and dividends are not tracked; enter average cost as shown in your broker app (brokers already adjust it for stock dividends); prices are the latest close.
5. Tests: P&L maths with hand-computed numbers, net-of-cost calculation, missing avg_cost handling, buy-date comparison, cash included in totals.

## Step 7 — Finish

1. Update Rebalance to read the chosen optimized weights from the store (still editable); keep its cost model and full-rebalance/threshold policies as they are.
2. Update docs (DATA.md, EXTENDING.md, ARCHITECTURE.md, ROADMAP.md, README), CHANGELOG.md and `.clinerules` to reflect the simplified scope and the single persisted store.
3. Regenerate the typed API client; make check must pass.

Acceptance:
- Leaving a page and coming back never loses the universe, portfolio, results or chosen portfolio; a saved portfolio loads everywhere.
- A non-financial user can go Portfolio → Optimize → pick a goal → see a plain-language result without touching any advanced setting.
- Optimize shows the Monte Carlo cloud, the exact efficient frontier, min-variance and max-Sharpe points, the user's current portfolio, and a risk slider; "Use this portfolio" feeds Risk and Rebalance.
- Only the methods listed above exist in the code and UI.
- The P&L page works from holdings plus average cost alone.
- ruff, mypy, pytest, web lint/types and make check all pass. No new V2/V3 feature is added.

## Step 8 — Redeploy all updates to Vercel
 
Run this only after Step 7 passes (`make check`, ruff, mypy, pytest, web lint/types). Deploy from the local folder with the Vercel CLI (no Git needed). Never print or commit secrets.
 
1. Pre-flight:
   - Confirm `vercel whoami` works and the folder is linked to the existing projects (web and Python API). If not linked, run `vercel link` and use the existing project names.
   - Review `vercel.json` (web and API): remove routes, rewrites and function entries for deleted pages and endpoints (Universe, Simulation, old Monte Carlo, backtest); add the new ones (`/api/v1/optimize/frontier`, `/api/v1/pnl/evaluate`). Keep the nightly data-sync cron and confirm its path and schedule still exist.
   - Check `requirements`/pyproject for the API: remove packages that are no longer used (for example anything only needed by the removed methods) to keep the bundle small. Verify the current Vercel Python function limits (bundle size and max duration) and report the new bundle size. If the bundle is over the limit, fix it before deploying.
   - Run `vercel env ls` for production and preview and confirm the variables from the README exist, including `PROVIDER_ORDER=kbs,vci,dnse,tcbs,ssi_iboard`. Add any missing variable with `vercel env add` (ask me for values; do not invent them).
2. Preview deploy first: run `vercel` (not `--prod`). Wait for it to finish and note the preview URL.
3. Smoke test the preview URL with curl or a script (save it as `scripts/smoke_test.py` so it can be reused):
   - the probe endpoint shows `kbs` working;
   - `GET /api/v1/symbols?q=VNM` returns results (no 500);
   - POST `/api/v1/optimize/frontier` with 5 VN30 tickers returns a frontier, min-variance and max-Sharpe points;
   - POST `/api/v1/risk`, `/api/v1/pnl/evaluate` and `/api/v1/rebalance` return valid responses;
   - removed endpoints (old montecarlo, backtest) return 404;
   - the web app routes `/portfolio`, `/pnl`, `/optimize`, `/risk`, `/rebalance`, `/settings` load, and the removed `/universe` and `/simulation` routes redirect to Optimize or return a friendly not-found page.
   If anything fails, fix it, redeploy a preview and retest. Do not promote a failing build.
4. Production deploy: run `vercel --prod`. Re-run the smoke test against the production URL. Trigger the cron sync once manually (or confirm it is scheduled) and check the data freshness badge shows a recent date with `kbs`.
5. Record the result: add the date, production URL, bundle size and test results to `docs/CHANGELOG.md` and the deploy section of `README.md`. Include the rollback command (`vercel rollback` or promoting the previous deployment) in the README.
6. Report back: preview URL, production URL, bundle size, which smoke tests passed, and anything I must do manually (for example, clearing old browser localStorage if the schema migration did not apply).
Acceptance:
- The latest code is live on the production URL and the smoke test passes there.
- Leaving a page and coming back never loses the universe, portfolio, results or chosen portfolio; a saved portfolio loads everywhere.
- A non-financial user can go Portfolio → Optimize → pick a goal → see a plain-language result without touching any advanced setting.
- Optimize shows the Monte Carlo cloud, the exact efficient frontier, min-variance and max-Sharpe points, the user's current portfolio, and a risk slider; "Use this portfolio" feeds Risk and Rebalance.
- Only the methods listed above exist in the code and UI.
- The P&L page works from holdings plus average cost alone.
- ruff, mypy, pytest, web lint/types and make check all pass. No new V2/V3 feature is added.
- The production deployment works end to end: data from kbs, frontier, risk, P&L and rebalance all respond, and the nightly sync is still scheduled.
 
