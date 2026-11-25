# Decisions

This is the decision log for the V2 precompute pipeline. Each entry states the
choice, why it was made, and what was rejected, so a later change can see the
context instead of rediscovering it.

## D-001 — Storage: the existing SQLAlchemy + SQLite/Postgres + Alembic stack

**Decision.** Persist every V2 precompute dataset in the repository's existing
SQLAlchemy 2 ORM, using SQLite locally (`vnopt.db`) and Postgres in deployment,
with schema changes through Alembic. The V2 data lives in additive tables
(`v2_ticker_master`, `v2_sector_map`, `v2_index_membership`, `v2_daily_prices`,
`v2_liquidity`, `v2_market_cap`, `v2_corporate_actions`, `v2_progress`) so V1's
`prices_daily` / `indices_daily` / `sync_log` behaviour is untouched. Benchmarks
reuse `indices_daily`.

**Why.** It is the simplest option already compatible with the repo and Vercel:
the settings module already selects `DATABASE_URL`, the deployment already points
at Postgres, migrations already run through Alembic, and the repositories already
do idempotent upserts. No new dependency and no second storage system.

**Rejected.** A Parquet/object-store lake (needs a bucket and a reader dependency,
and Vercel functions would need signed URLs); DuckDB (a new dependency and a
single-writer file); a separate database (extra ops for a personal project).

**Migration.** `packages/data/alembic/versions/0002_v2_precompute.py`. Tests use
`data.db.base.create_all` only to build a throwaway database.

## D-002 — Basis and provenance flags on every dataset

**Decision.** Every stored/returned dataset carries `data_as_of` and `provider`,
and the basis that produced it:

- `price_adjustment_basis` ∈ `ssi_adjusted` | `corporate_actions` |
  `price_gap_heuristic` | `raw`. SSI `stock-info` publishes an adjusted `close`
  next to `closeRaw`, so the primary path is `ssi_adjusted`. A raw provider's
  series is back-adjusted from corporate actions, or (last resort) with
  `data.v2.adjustment.adjust_price_gaps`, which is always labelled
  `price_gap_heuristic`.
- `volume_basis` ∈ `matched` | `total`. `matched` uses SSI `totalMatchVol` /
  `totalMatchVal`; `total` is the fallback when the provider does not separate
  put-through. A ticker is `matched` only when the whole 20-session window has
  matched volume and value.
- `market_cap_basis` = `full`. Free-float is unavailable keyless, so V2 labels
  market cap as full and never claims a free-float weighting.

**Why.** The spec requires the UI to label "data as of", volume basis and
price-adjustment basis. Storing the flags with the rows means a later consumer
cannot lose them, and a fallback can never masquerade as the primary source.

## D-003 — Returns are derived, not stored

**Decision.** Store adjusted daily bars and compute simple daily returns on read
(`data.v2.returns.daily_returns`). Do not persist a separate returns table.

**Why.** A return is fully determined by two consecutive adjusted closes, so a
stored copy would be redundant and could drift if a bar is corrected. The reader
and the quality checks both use the same pure function, so they cannot disagree.
Only simple returns are used (CFA Level 1/2), matching the rest of the app.

## D-004 — Scheduler: GitHub Actions primary, manual CLI for local use

**Decision.** Run the pipeline in `.github/workflows/precompute_v2.yml` (a runner,
not a short serverless function), scheduled at `37 9 * * 1-5` UTC = 16:37 ICT on
weekdays (after the 15:00 ICT close) and nightly at `13 19 * * *` UTC = 02:13 ICT,
with `workflow_dispatch` for manual and heavy-backfill runs. Provide the manual
equivalent `python -m data.v2.jobs.precompute`. The Vercel cron keeps the V1
`/api/v1/data/refresh` only; heavy backfill must never run in the 120-second
serverless function.

**Why.** A 3-year backfill of ~700 tickers is ~13,300 pages (about 11 h at the
app's 20 requests/minute), which fits neither a serverless timeout nor one runner
job. The pipeline is resumable and chunked, so repeated `mode=full` runs with a
`--limit` make progress and the daily `mode=incremental` run costs about one page
per ticker. This satisfies "host heavy backfill on a runner".

**Off-peak minutes.** GitHub's scheduler queue is busiest on `:00` and `:30`, where
a cron can be delayed by many minutes, so both schedules use an odd minute
(`:37`, `:13`); the market-relative timing (a few minutes earlier or later than
the original 16:30/02:00 ICT) is irrelevant because a run processes whatever the
providers have published when it starts.

**Concurrency.** The job joins the `precompute-v2` concurrency group with
`cancel-in-progress: false`, so the two crons and manual dispatches never overlap:
a second trigger queues behind the active run instead of cancelling it or writing
the same tickers in parallel. Losing a *pending* run is harmless because
scheduled runs are `incremental` and resume from the committed `v2_progress`.
The nightly pass exists for the same reason — it repairs a weekday run that
failed or was truncated by the timeout, and catches late provider corrections.

## D-005 — Pre-screen, resumable chunks and incremental runs

**Decision.** Pre-screen the universe with a cheap KBS recent-volume screen
(configurable; on by default with a 100,000-share median threshold, switch it off
with `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED=false`) before per-ticker SSI calls.
Commit each ticker in its own session and record `v2_progress`. An incremental run
fetches only `latest_stored_date + 1 .. today`; a full run re-fetches from the
configured `backfill_start_date`.

**Why.** The call budget in `docs/V2_DATA_GAPS.md` makes the pre-screen and the
chunked, resumable backfill mandatory. Per-ticker commit is what makes an
interrupted run resume instead of restarting.

**Empty symbols and row counts.** `v2_progress.rows` holds the cumulative
`v2_daily_prices` bar count and is never blanked by an incremental fetch that
returns no new bars, while `state`, `last_date` and `updated_at` still advance. An
`incremental` run then drops the tickers whose checkpoint is `done` with `rows = 0`
and no stored bar, so a symbol that never trades stops costing a daily request; a
`--full` run or `--profiles` re-checks them.

**Backfill priority and the `--limit` budget.** Candidates are ordered
already-priced tickers first, then unpriced `VN100`/`VN30` members, then the
remaining unpriced names alphabetically, so `--limit` updates tracked stocks
before it backfills a new one and fills the index universes before the long tail.
The limit is spent *after* the pre-screen: the screen runs while the budget is
being spent and a rejected symbol consumes no slot. Before that, the first 150
alphabetical candidates were screened first, so on a real run 46 of the 150 slots
went to symbols the 10k-share volume floor rejected and the run left most `VN100`
members unpriced.

**As-of resolution.** The runner clock is UTC, so the automatic run resolves
"today" in Vietnam time (`Asia/Ho_Chi_Minh`, a fixed UTC+7 with no DST). If the
upstream `VNINDEX` series has no bar for that session — a daytime manual dispatch,
a holiday, or a provider that has not published EOD bars yet — the run logs an
`as-of fallback` warning and processes the last published session. The quality gate
therefore keeps failing only on real defects; an explicit `--as-of` (workflow input
`as_of`) disables the fallback so a stale benchmark or dataset still fails loudly.

**Why.** The daily pass must spend its request budget on the stocks that have
data, and a zeroed count made the checkpoint unable to tell "no bar ever" from
"no new bar today", so a suspended or newly listed name was polled forever.

## D-006 — Sector coverage gaps are reported, never guessed

**Decision.** Keep a ticker with no ICB level-2 sector in the universe (so its
prices, market cap and liquidity still exist), report it as a coverage gap, and
exclude it from sector features. Never infer a sector from the name or the
exchange. ETFs, funds, covered warrants and bonds are excluded explicitly by
exchange and security type.

**Why.** `docs/V2_DATA_GAPS.md` requires a missing sector to hide or disable the
feature rather than invent one.

## D-007 — Corporate actions are stored for quality checks and fallbacks

**Decision.** Store DIV/ISS events in `v2_corporate_actions` (refreshed in the
profile step) so the quality checks can distinguish a legitimate ex-date gap from
a suspicious move, and so the raw-provider adjustment fallback can use them.

**Why.** "Suspicious returns outside known corporate-action days" needs the known
ex-dates; without them every dividend would look like a bad data point on a raw
series, and the adjusted-series reconciliation could not run.

## D-008 — Cloud-IP access to SSI remains unverified until the probe runs

**Status (2026-11-22).** A read-only probe from the local PC returned HTTP 200 for
`iboard-api.ssi.com.vn/statistics/company/sectors-data` (Cloudflare `cf-ray`
present), so local reachability is good. The project is local-only and has not run
on a GitHub runner, and Cloudflare fronts SSI, so **cloud-IP access is
unverified**. The pipeline is designed for that: the conservative 20 req/min
budget, the KBS pre-screen, resumable chunks, and the labelled fallbacks.

**When pushing to GitHub:**

1. Run `.github/workflows/probe_v2.yml` first and confirm SSI answers from the
   runner before enabling the scheduled backfill.
2. Add a repository secret `DATABASE_URL` pointing at a persistent Postgres (a
   runner's SQLite file is discarded after the job).
3. Enable `precompute_v2.yml`; leave the weekday cron for incremental runs and
   dispatch `mode=full` with a `limit` (e.g. 150) until the backfill completes.
4. If SSI blocks cloud IPs, the pipeline still produces KBS raw prices labelled
   `raw` or `price_gap_heuristic`; the limits are visible in the flags.

## D-009 — Fallback plan if the SSI call budget is too large

**Plan.** The primary path uses SSI `stock-info` adjusted prices + matched flow. If a
full 3-year backfill is too slow or blocked (`docs/V2_DATA_GAPS.md`: ~19 pages per
ticker, ~13,300 requests, about 11 h at 20 requests/minute), the alternative is KBS
raw bulk history adjusted from SSI corporate actions, cross-checked against SSI
adjusted prices on a sample.

- Raw KBS bars adjusted with `data.v2.adjustment.adjust_price_gaps` are always
  labelled `price_gap_heuristic`; the corporate-actions path uses the stored DIV/ISS
  events in `v2_corporate_actions`.
- The sample cross-check reuses `data.v2.reconcile.reconcile_corporate_actions`,
  which reports the removed gap, the expected gap and the difference at each
  ex-date; the default 2% tolerance labels each ex-date `ok` or `difference`, and
  the result is logged, never hidden.
- The pipeline already stores the corporate actions and labels the basis, so
  switching the primary source later is a config/adapter change, not a schema
  change.

## D-010 — Pre-screen is a backfill-cost floor, not a liquidity filter

**Decision.** `precompute_pre_screen_min_median_volume` defaults to **10,000
shares** (30-session median), and the config docstring and `_pre_screen` docstring
label it a **backfill-cost floor, not a liquidity filter**.

**Why.** The pre-screen runs before any price rows exist, so a ticker it drops
never appears in the priced universe and the UI's "All Stocks" preset (no
liquidity floor) is silently filtered. A 100k-share floor dropped genuinely
tradable small caps, so the cost-control step was changing what "All Stocks"
means. 10k shares excludes only effectively untraded/suspended names (the long
tail of UPCoM shells). It stays switchable with
`VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED=false` and can be disabled entirely by
setting the threshold to 0.

**Rejected.** Keeping 100k and labelling the preset (still filters "All Stocks");
disabling the pre-screen by default (larger backfill).

## D-011 — Trading calendar is derived from stored VN-Index bar dates

**Decision.** The missing-trading-days quality check derives the exchange calendar
from the stored VN-Index bars (`V2Store.list_index_dates("VNINDEX")` ->
`data.calendar.trading_days_from_dates`) instead of the illustrative 2025-only
holiday set in `core.market_rules`. When no index bars are available it falls back
to `rules.trading_holidays`.

**Why.** A session with a VN-Index bar was open; one without was a weekend or
holiday. The illustrative set lists only 2025, so every 2023/2024/2026 exchange
holiday was counted as a missing bar and the quality step failed on every ticker.
The derived calendar is real, needs no maintenance, and the returned set is the
denominator for the planned "80% of trading days" coverage rule.

**Rejected.** Loading a full official holiday calendar (manual upkeep, drifts);
treating every weekday as a trading day (misclassifies holidays as gaps).

## D-012 — The precompute path gets an explicit requests-per-second throttle

**Decision.** The shared `HttpxHttpClient` applies a configurable
`client_requests_per_second` cap (default **0.5 rps ~ 30/min**), retries HTTP 429
with exponential backoff (`client_rate_limit_retry_attempts`,
`client_rate_limit_backoff_seconds`), and starts a per-host cooldown on HTTP 403
(reusing `blocked_cooldown_seconds`).

**Why.** The precompute path calls the adapters directly and does not go through
the failover runner's per-type limiter, so it used the 10,000/min safety net and
was effectively unthrottled. The explicit rps cap keeps a real backfill inside the
endpoints' tolerance, and the 429/403 handling stops one rate-limit or block from
failing a whole ticker. Everything is configurable per environment via `VNOPT_V2_*`.

**Rejected.** Routing the precompute path through the runner (larger change,
duplicates the runner's cache/health semantics); leaving it unthrottled (risks
blocks during a multi-hour backfill).

## D-013 — Analytics engine: pure helpers in `data/v2/analytics` + a thin DB service

**Decision.** The Sector Analysis engine lives in `packages/data/data/v2/analytics/`.
Every piece except `service.py` is pure (no SQLAlchemy, no network) and unit-tested
without a database; `AnalyticsService` is the only DB-touching module. It reads stock
data only through `V2Store` (the V2 tables), benchmark index bars through
`SqlIndexRepository` (`indices_daily`, D-001), and the calendar from the stored VN-Index
dates (D-011). Returns are derived on read from the adjusted close (D-003). Groupings,
like every variable concept, are an interface plus a `core.registry.Registry`.

**Why.** It keeps the analytics math pure and fast to test while respecting the
architecture rule that `packages/core` has no DB imports: the engine is V2-specific and
reads V2 data, so it belongs in the data layer beside `returns`, `liquidity`,
`universe` and `quality`. Reusing `core.risk._math` for beta/volatility and
`core.registry` for the grouping registry avoids duplicating logic.

**Market-cap weighting with one stored snapshot.** `v2_market_cap` holds one market cap
per ticker (the latest reported period), not a time series. The index is therefore a
*current-constituents index*: target weights are proportional to that single snapshot,
and the quarterly rebalance re-applies the same cap-cleaned target to the drifted
weights. Between rebalances the index compounds the drifted weights (a buy-and-hold
basket), which is the honest reading of the available data.

**Single-stock cap infeasibility.** A 15% cap over fewer than seven names cannot sum to
one. Rather than silently violate the cap or drop names, the engine leaves the weights
uncapped (proportional) and adds a warning; the group is still shown. The cap bites only
when it is feasible. This keeps the "at least 3 constituents" rule and the cap rule
compatible.

**Widest-limit return sanity (15%).** The adjustment-quality flag and the
`suspicious_returns` check use the widest exchange limit (UPCoM 15%) plus a small buffer
as the sanity threshold, not the ticker's current board limit. A listing transfer (BSR
moved from UPCoM to HOSE) makes the current 7% limit wrong for historical sessions; the
BSR 2024-05-22 8% move was a false positive under the old current-exchange rule.

**Two-level quality severity.** Findings that are documented as known and explained
(SSI's adjusted-vs-raw drift on VGI/OIL, HPG's omitted bonus issues, the BSR
2025-01-07..16 halt) are downgraded from `error` to `warning` by a documented config in
`data/v2/explained_findings.py`; unexplained findings stay errors, and the quality step
fails only on errors. Adding a new known case is a config edit, not a code change.

**Test-only pandas.** The acceptance criterion compares beta/correlation with an
independent pandas computation on three sectors, so `pandas` is added to the API dev
extras only. It is **not** in the runtime deployment manifest, so the serverless bundle
is unchanged.

## D-014 — Adjustment-quality flags are precomputed, not read-time

**Decision.** Compute each ticker's adjustment-quality flag once in the precompute
pipeline (step 8, `_compute_adjustment_flags`) and store it in the additive
`v2_adjustment_flags` table (migration `0003_v2_adjustment_flags`). Every checked
ticker gets a row, flagged or clean. The read endpoints load the rows and expose
`flags_available`; the Sector Analysis service reads them too instead of recomputing.

**Why.** Recomputing `adjustment_quality_flag` per request reads every kept ticker's
bars and corporate actions, which is too slow for a ~1,500-ticker universe. A stored
row survives restarts and needs no invalidation, and the "row exists but is clean"
distinction lets the UI tell "not computed yet" apart from "no flags".

**Rejected.** A process cache keyed by `data_as_of` (lost on restart, needs
invalidation); computing on read (too slow).

## D-015 — Sector cap in the frontier and the cloud; configurable stock cap

**Decision.** The `max_sector_weight` constraint is registered like the others and is
threaded through `build_efficient_frontier` and `sample_random_portfolios` (the
per-stock cap already applies to both). The ticker -> sector map travels with the
request (the Optimize tab already has it from `/v2/universe`); unknown tickers bucket
as `Unknown` and a malformed or oversized map is a 422. `Settings.max_optimize_stocks`
(default 30, `VNOPT_MAX_OPTIMIZE_STOCKS`) is the configurable ceiling on how many
tickers the Optimize tab sends; it is published on `GET /optimize/options`.

**Why.** Requirement 3.1 asks for optional per-stock and per-sector caps that hold for
both the plotted frontier and the random cloud, so the same rule must be enforced in
both places. Keeping the sector map on the request keeps `packages/core` DB-free and
the API thin; the configurable ceiling lets a heavier run be enabled without a code
change while the sample covariance stays trustworthy by default.

**Rejected.** Server-side sector lookup inside the optimizer (couples core to the V2
store); capping only the frontier (the cloud would then show portfolios the cap
forbids).

## D-016 — `--members` dev backfill and overlap-based re-base detection

**Decision.** Two additive changes to the precompute pipeline, with no schema
change:

- `python -m data.v2.jobs.precompute --members {VN30,VN100}` runs the master,
  membership and benchmark steps over the full universe but restricts the price,
  profile, liquidity, quality and adjustment-flag steps to that index's stored
  members (`V2PrecomputeService._processing_universe`). Omitting the flag keeps
  today's behaviour exactly. A full-universe setup-only run remains possible with
  `--limit 0`, which the price and profile steps treat as "process no tickers".
- The incremental price step detects SSI's retroactive re-bases by overlap rather
  than by the corporate-actions feed: when a ticker has new dates it also re-fetches
  a tail overlap (`precompute_rebase_overlap_sessions`, default 40 sessions) and
  compares the overlapping adjusted closes with the stored ones
  (`precompute_rebase_tolerance`, relative, default 0.0001 = 0.01%). On a mismatch
  it re-fetches the full history from the backfill start and upserts it (the
  `(symbol_code, date)` upsert replaces the old rows) in the same run.

**Why.** The CLI had no membership filter, so a VN100-only dev backfill was
impossible without pricing the whole universe, and incremental runs fetched only
`latest + 1 .. today`. SSI's adjusted series changes retroactively when a new
ex-date lands, so those old rows went stale. Detecting the change from the
corporate-actions feed is unreliable: routine incremental runs skip `done`
profiles, and the feed omits some bonus issues (HPG). Comparing prices directly is
independent of the feed and catches the HPG case. The overlap is part of the
normal incremental fetch, so a no-change run makes no extra request.

**Rejected.** A stale marker written by `_sync_profiles` (profiles are skipped in
routine runs and the feed is incomplete); storing raw prices plus adjustment
factors and recomputing on read (SSI's exact adjustment method is still an open
item, so this would drift from the authoritative adjusted series, and it is a
larger reader/schema change).

## D-017 — Quality severity policy, ISS reconciliation and calendar-aligned returns

**Decision.** From the VN100 backfill triage (62 findings, of which 5 are
return-corrupting), the quality gate and the analytics engine change as follows,
with **no price or schema change**:

- **Only integrity findings fail the precompute step.** `no_data` (a universe
  member with no bars), `duplicate_dates`, a stale latest bar (`latest < target`),
  an empty benchmark calendar, and schema errors are `error`. Every per-ticker
  data-quality finding (`missing_trading_days`, `zero_volume_streak`,
  `suspicious_returns`, `adjusted_vs_raw_mismatch`) is a `warning`: it is logged
  and stored in `v2_adjustment_flags` but never fails the step.
- **A `no_data` check only applies to tickers the run attempted.** `_run_quality`
  skips tickers without a `prices` progress record (a chunked `--limit` backfill
  or a pre-screened name) and `failed` states (the prices step already reported
  them), so a partial run stays OK.
- **An ISS ex-date is unverifiable.** SSI publishes an issuance ratio but no
  subscription price, so the bonus-share model (`-ratio/(1+ratio)`) overstates the
  gap for a rights issue and turns genuine rights issues (NVL, VIX, HCM, ...) into
  false differences. `reconcile_corporate_actions` now marks any ex-date carrying
  an ISS (including a mixed DIV/ISS date) `unsupported`. Only an **all-DIV** group
  with a published value is checked (`ok`/`difference`). A positive adjusted gap
  (>5%) on a flat raw close (|gap|<2%) at an ISS ex-date is `adjustment_suspect`
  (a spurious adjusted gain: EVF 2023-09-21, NVL 2026-06-10).
- **Returns are derived on the benchmark calendar.** `data.v2.returns.calendar_returns`
  produces a return for day `t` only when the ticker has a bar on both `t` and the
  preceding benchmark trading day. A halt/suspension/late-listing gap therefore
  contributes no return instead of a multi-day return placed on the resume date,
  which previously got aligned with the benchmark's single-day return and corrupted
  beta, correlation and volatility. The Sector Analysis service uses it.
- **Default exclusion rule.** `adjustment_quality_flag` sets
  `exclude_from_group_indices=True` only for return-corrupting anomalies: a >15%
  adjusted move, a **spurious reversing adjusted move** (a >7% one-bar jump that
  largely reverses the next session, e.g. GEE), a `difference`/`adjustment_suspect`
  reconciliation, or a >15% suspicious move (TAL 2025-04-10, impossible under the
  7% HOSE band). The Sector Analysis service drops those tickers by default; plain
  adjusted-vs-raw drift (MCH/NAB/VTP, HPG) is flagged as a warning but included
  unless the caller sets `exclude_adjustment_flagged=True`.
- **`EXPLAINED_FINDINGS` is kept and extended** with the documented VN100 cases
  (GEE/MCH/NAB/TAL/VTP one-day adjusted-close glitches; GEE/TAL/VTP/NAB/MCH/SIP
  halt/gap days) so they are annotated `explained`, not silently dropped.

**Why.** A backfill that priced 100/100 tickers correctly should not fail because
SSI's own adjusted series has a handful of one-day glitches or real trading halts.
Failing only on dataset integrity, surfacing the rest as flags, and excluding only
the return-corrupting names keeps the step meaningful while making the Sector tab
trustworthy. The ISS model limitation was the dominant false-positive source (42 of
the original 97 "errors").

**Rejected.** Treating every ISS as a bonus issue (42 false differences); keeping
per-ticker findings as `error` (the step can never pass on real SSI data);
computing returns from a ticker's own consecutive bars in the analytics engine
(mixes multi-day and daily returns).

## D-018 — Flag policy versioning, offline recompute and staleness surfacing

**Decision.** Make the persisted adjustment-quality flags self-describing and
refreshable without a network round-trip, with **no schema change**:

- **The policy version is stored in each flag row's `source`.** The precompute job
  (and the new offline recompute) writes `source = "<price_source>|policy=D-017"`
  via `data.v2.adjustment_quality.flag_source`. `policy_from_source` reads it back,
  and `flags_policy_current(records)` is `True` only when the table is non-empty and
  every row carries `FLAGS_POLICY_VERSION` (`"D-017"`). Rows written under an older
  rule set — or before versioning existed — compare unequal and are reported stale.
- **`--recompute-flags` recomputes only the flags, offline.** `python -m
  data.v2.jobs.precompute --recompute-flags --members VN100` re-runs just step 8 from
  the stored prices and corporate actions (it builds no `V2DataContext` and fetches
  nothing), so a policy change is applied without re-downloading a price. It is
  idempotent and restricted to the index's stored members.
- **Staleness is surfaced, not hidden.** `flags_policy_current` is exposed on the
  analytics payload and on `GET /v2/universe`; both add a warning, and the UI shows
  "adjustment checks are outdated; rerun the update" when flags exist but are stale.
  `scripts/verify_v2_db.py` prints the flagged/excluded/flagged-but-included counts,
  the excluded tickers and whether the policy is current.

**Why.** The VN100 backfill wrote its flags before D-017 changed the ISS
reconciliation and the default exclusion rule, so 38 of 100 names were excluded
under the old policy (only 5 are return-corrupting under D-017). Re-running the full
precompute would re-download every series for a pure recomputation; embedding the
version in the existing `source` column lets a reader prove the rows are current and
lets the flags be refreshed offline.

**Rejected.** A new `policy_version` column (works, but the task preferred no schema
change and the value is derivable from an existing field); recomputing the flags on
every read (defeats the precompute) or forcing a full network run to refresh them.




## D-019 — Window-aware default exclusion and thin-trading classification

**Decision.** Apply the group-index default exclusion per analysis window, and label
very-low-liquidity anomalies as thin trading:

- Each stored flag now carries a dated `anomalies` list `{date, exclude, category,
  reason}` (new JSON column, Alembic `0004`). The Sector service drops a ticker only
  when one of its return-corrupting anomalies falls in `[prior_trading_day,
  window.end]` (the window plus the first return day's source close). A name flagged
  only for an out-of-window anomaly is included and listed separately as "flagged
  earlier, not affecting this window".
- A price-move anomaly on a day whose stored matched value/volume is below
  `THIN_TRADING_FRACTION` (10%) of the ticker's median is categorised `thin_trading`;
  other return-corrupting anomalies stay `data_glitch`.
- `FLAGS_POLICY_VERSION` is `D-019`; `flags_policy_current` reports older rows stale.
  Flags written before the change (no dated anomalies) keep the whole-history
  exclusion so nothing silently changes until `--recompute-flags` runs.

**Why.** A ticker with a one-day adjusted-close glitch in 2023-2024 (GEE) was excluded
from a clean 2026 window, shrinking the sector for no reason. Dated anomalies make the
exclusion honest per window, and "thin trading" explains a big move on a near-zero
volume day without calling it a data glitch.

**Rejected.** Parsing dates out of the free-text reasons (fragile); excluding on the
whole-history flag (the bug this fixes).

## D-020 — Normalise market caps before applying the single-stock cap

**Decision.** `target_weights` passes `_proportional(market_cap)` to `apply_cap`
instead of the raw market caps. `apply_cap` was written for normalised weights (its
unit tests pass proportions); feeding it raw VND caps made every name exceed the cap,
so a sector with at least 7 names collapsed to equal, un-normalised weights. The
return hid it because the index divides by the available weight, but the market-cap
weighting was lost.

**Why.** Full-market-cap weighting with a 15% cap must keep the cap and the market-cap
ordering while summing to one. `scripts/reconcile_sector_analytics.py` surfaced it on
real Banks/Real Estate data.

**Rejected.** Capping in equal-weight space (wrong: loses market-cap differentiation);
relying on the return normalisation to hide the scale.

## D-021 — Insurance uses a safe-default financial ratio set

**Decision.** Add a fourth ratio group, `insurance`, used by the ICB level-2
`Insurance` sector, with the safe default `roe`, `roa`, `pe`, `pb`
(`INSURANCE_RATIOS`). `Banks` keeps `roe/roa/npl/pe/pb`, `Financial Services` keeps
the securities set `roe/roa/pe/pb`, and every other sector (including Real Estate)
keeps the full general set.

**Why.** A non-financial probe (FPT/HPG/VNM, recorded as fixtures) confirmed the
general set is fully populated for ordinary companies, so it stays unchanged. An
insurer, however, publishes no cost-of-goods margin and no working-capital
liquidity, and the feed carries no insurance-specific ratio (combined ratio), so the
general set would be mostly null for `Insurance`. ROE, ROA, P/E and P/B are the four
multiples that are meaningful for any financial company. Peers are always the same
ICB level-2 sector, so the group only selects which keys are shown/stored, not who is
compared with whom.

**Rejected.** Mapping `Insurance` to `securities` (same keys but a misleading stored
label); keeping the full general set (mostly-null columns in the Fundamentals UI).


## D-022 — `as_of` is the last *completed* session, and a backfill can select unpriced tickers

**Decision.** An automatic run resolves its target with
`data.calendar.last_completed_session`: the current Vietnam date only at or after
`MarketRules.session_close` (15:00 ICT), otherwise the previous calendar day, rolled
back over weekends and known holidays. `_settle_target` then falls back to the last
published `VNINDEX` session, and every price and benchmark fetch ends at that target
instead of `now`. A run may also select its price candidates with
`only_unpriced=True` (`--unpriced`, the `unpriced` dispatch input), which keeps only
the tickers with no stored bar.

**Why.** A 2026-11-25 dispatch at 10:02 ICT (2026-11-24 was a holiday) stored a
provisional intraday `VNINDEX` bar for 11-25, so `_settle_target` saw
`benchmark_latest >= target`, kept 11-25 as the target and the gate failed with
`quality: stale dataset, latest price bar 2026-11-23` — while all 150 `--limit` slots
went to already-priced tickers that could only return `+0 bars`, so the 1,025
unpriced tickers never got one. Clamping the fetch window to the target is what keeps
an unsettled intraday bar out of the dataset; a clock that knows the close is what
makes the target correct before the run starts.

**Rejected.** Treating `today` as the target and widening the staleness tolerance
(the default stays `0`, strict; the env knob exists only for a known upstream lag);
inferring the session from the *stock* series' max date (one fresh ticker would hide
a dataset that stopped updating); recording a pre-screen rejection as a `done`
checkpoint (it would silently exclude the ticker forever, so the rejection is logged
and `--unpriced` overrides the selection instead).

