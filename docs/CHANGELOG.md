# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### V2 precompute pipeline

- **Backfill candidates are prioritized and `--limit` is spent after the
  pre-screen.** `V2PrecomputeService._order_price_candidates` now returns three
  tiers: already-tracked tickers (stored bars or a positive checkpoint count),
  then unpriced `VN100`/`VN30` members from `v2_index_membership`, then the
  remaining unpriced symbols alphabetically. The limit is applied by the new
  `_select_candidates`/`_passes_pre_screen` pair (which also absorbs the old
  `_pending_tickers` scan), so candidates are screened while the budget is being
  spent and the loop stops as soon as enough survive: a rejected symbol costs no
  slot. Previously `LIMIT=150` filled its first 104 slots with
  tracked names and spent the rest on alphabetical unpriced symbols (`E`-`Z`)
  that the 10k-share median-volume floor rejected, leaving 78 of 100 `VN100`
  members without prices; now every run makes real backfill progress. The
  per-ticker body moved to `_backfill_ticker` so the loop stays small, and the
  ordering/screen rules are covered by new `test_v2_precompute.py` tests.
- **Unsettled upstream EOD bars no longer fail the quality gate.** `run()` accepts
  an optional `as_of`; without it the pipeline resolves today in Vietnam time
  (`data.calendar.vietnam_today`, fixed UTC+7 — the runner clock is UTC) and, when
  the stored `VNINDEX` series has no bar for that session yet (a daytime manual
  run, a holiday, or a provider that publishes late), `_settle_target` retargets
  the run to the last published session and logs `as-of fallback: VNINDEX has no
  bar for ... yet`, so `quality: stale benchmark` / `quality: stale dataset`
  (`quality_errors=2`) report a real defect instead. An explicit `--as-of`
  keeps the strict errors. New `--as-of YYYY-MM-DD` CLI flag in
  `data.v2.jobs.precompute` (and the job now passes `today_provider=vietnam_today`
  so a 19:13 UTC run uses the Vietnam calendar date), wired as the `as_of`
  `workflow_dispatch` input in `precompute_v2.yml`.
- **Both per-ticker loops log live progress.** `_backfill_prices` and
  `_sync_ratios` print `[prices] 37/150 FPT (+968 bars)` / `[ratios] 37/150 FPT
  (+305 rows)` every `PROGRESS_LOG_EVERY` (10) tickers and for the final one, so
  the Actions log shows progress instead of staying silent until `ratio_quality`.

### Infrastructure / deployment

- **`precompute_v2.yml` schedules moved off the busiest GitHub minutes.** The
  post-close cron is now `37 9 * * 1-5` (16:37 ICT) and the nightly cron
  `13 19 * * *` (02:13 ICT), with the adjacent comments updated, so scheduled
  runs avoid the `:00`/`:30` queue congestion that delays them by many minutes.
  The dispatch inputs are unchanged apart from the new `as_of`.

- **`precompute_v2.yml` bounds a scheduled run and streams its log live.** A cron
  trigger now caps the job at `LIMIT=150`
  (`github.event_name == 'schedule' && '150' || inputs.limit`), so the post-close
  and nightly passes refresh every tracked ticker plus a bounded batch of new ones
  instead of walking the whole universe into the 350-minute job timeout; a manual
  dispatch still accepts a blank (no cap) or custom limit. The
  `actions/setup-python@v5` step now sets `cache: "pip"` keyed on
  `packages/core/pyproject.toml` and `packages/data/pyproject.toml`, the
  `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND` fallback moved from `0.5` to `1.5`, and
  `PYTHONUNBUFFERED: "1"` plus `python -u` make every progress line reach the
  Actions log as it is written instead of at exit. `concurrency` (`group:
  precompute-v2`, `cancel-in-progress: false`) and the four `workflow_dispatch`
  inputs are unchanged. `docs/DATA.md` notes the scheduled limit.
- **`precompute_v2.yml` now runs nightly as well as after the close, with the
  concurrency guard documented.** The workflow had only the post-close cron
  `30 9 * * 1-5` (09:30 UTC = 16:30 ICT); it now also runs `0 19 * * *`
  (19:00 UTC = 02:00 ICT), so a weekday run that failed, hit the 350-minute job
  timeout or missed late provider corrections is repaired the same night. Because
  a scheduled run sets `MODE=incremental` (`github.event_name == 'schedule'`), the
  second pass only fetches new dates. Both crons and manual dispatches stay
  serialized by the existing `concurrency: group: precompute-v2,
  cancel-in-progress: false`: a second trigger queues behind the active job
  instead of cancelling it or writing the same tickers in parallel, and dropping a
  *pending* run is harmless because the pipeline resumes from `v2_progress`.
  `workflow_dispatch` and its four inputs (`mode`, `start`, `limit`, `profiles`)
  are untouched. Docs updated: `docs/DECISIONS.md` (D-004), `docs/DEPLOYMENT.md`
  and `docs/DATA.md`.
- **Vercel deployment configuration verified and hardened before a Preview deploy.**
  The root `.vercelignore` now covers what the API project must never upload:
  `*.db` plus the SQLite sidecars (`*.db-wal`, `*.db-shm`, `*.db-journal`),
  `*.sqlite*`, `*.dump`, `tests/` and `**/tests/`, `.venv/`, `apps/web/` (415.9 MB
  of `node_modules` + 368.0 MB of `.next` locally), `docs/`, `scripts/`,
  `data/reference/` and the tool caches — plus the gitignored local secrets
  (`Deployment prerequisite.txt`, `V2 update.txt`, `.env*`), which a CLI upload
  would otherwise ship because it does not read `.gitignore`. New
  `apps/web/.vercelignore` gives the web project (Root Directory `apps/web`) its
  own list; Vercel only falls back to the repository-root file when the project has
  none, so the root `apps/web/` entry can no longer blank out the Next.js upload.
  What stays in the build context is the app + workspace source (≈ 0.8 MB) on top
  of the ≈ 182 MB dependency set, i.e. the ≈ 183 MB bundle already measured
  against Vercel's 500 MB Python limit. `docs/DEPLOYMENT.md` gains a "What Vercel
  uploads" section with the measured sizes.
- **Preview environment checklist documented** (`docs/DEPLOYMENT.md`): a preview
  reads only Preview-scoped variables, so the same values must be added there —
  `DATABASE_URL` on the Supabase **transaction pooler** (port `6543`,
  `prepare_threshold=None`), `PROVIDER_ORDER`, the seven `VNOPT_V2_*_ORDER` chains
  and their seven `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` budgets, `REFRESH_TOKEN` /
  `VNOPT_REFRESH_TOKEN` / `CRON_SECRET` (all three equal — the cron secret is
  compared against `refresh_token` by `require_token`), and `API_URL` for the web
  project (build-time rewrite).
- **`scripts/smoke_test.py` now covers the V2-backed views.** Added checks for
  `/data/freshness` (latest stored session + serving source), Portfolio valuation of
  the six V2 reference tickers (`FPT, HPG, VHM, LPB, PVD, DCM`, no `stale`/
  `suspended` warning), the Max-Sharpe marker being one of the plotted
  `frontier` points, and `/v2/coverage`, `/v2/sectors`, `/v2/analytics`,
  `/v2/fundamentals/{symbol}` answering 200 with `data_as_of` inside a 2 s warm
  budget. Verified against the migrated database (2026-11-23 session): freshness
  `primary=ssi_statistics`, all six holdings at spot prices with `warnings: []`,
  `on_line=True`, V2 routes 11-420 ms.

- **`precompute_v2.yml` audited and fixed for the Supabase daily sync.** The job
  installed `vnopt-data` without its `[postgres]` extra, so `psycopg` was absent
  on the runner and a Postgres `DATABASE_URL` would have failed at connect with
  `ModuleNotFoundError`; it now installs `"packages/data[postgres]"`. The
  documented V2 tunables are forwarded explicitly with `||` defaults
  (`VNOPT_V2_BACKFILL_START_DATE`, `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND`,
  `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED`,
  `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_MIN_MEDIAN_VOLUME`), and a new
  `Verify stored rows` step runs the read-only `scripts/verify_v2_db.py` (with
  `::add-mask::` on the URL) whose output joins `precompute_report.txt` in the
  `precompute-report` artifact. Docs now state that `DATABASE_URL` is the only
  secret the workflow reads and that `VNOPT_V2_*_ORDER` /
  `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` configure the API runner but not the
  precompute job (it wires one adapter per data need in
  `sources_from_context`). Verified: `30 9 * * 1-5` = 09:30 UTC = 16:30 ICT,
  1.5 h after the 15:00 ICT close; a scheduled run executes
  `python -m data.v2.jobs.precompute --incremental` (prices, profiles, liquidity,
  ratios, sector statistics, ratio/quality checks, adjustment flags).

- **Supabase Postgres provisioned, migrated, secured and seeded (V2 start).** Ran
  Alembic `0001_initial`→`0005_v2_financial_ratios` against the Supabase
  **session-pooler** (port 5432) database; all 17 V1/V2 application tables, their
  indexes and `server_default` values applied cleanly. On Postgres the `0004` revision
  id (`0004_v2_adjustment_flag_anomalies`, 33 chars) does not fit Alembic's default
  `alembic_version.version_num VARCHAR(32)` (SQLite ignores the limit), so that column
  is widened to `VARCHAR(255)` before upgrading — an operational bootstrap on Alembic's
  own bookkeeping table, not an application schema change.
- **Row-level security enabled on every public table** (18 tables incl.
  `alembic_version`). No permissive policies are created and all residual privileges
  are revoked from `anon` and `authenticated`, so both roles have zero read/write/
  truncate access; `postgres` (owner, `BYPASSRLS`) and `service_role` (`BYPASSRLS`, with
  full table + sequence grants) keep full access. Verified with `SET ROLE` probes.
- **V2 universe synced across HOSE, HNX and UPCOM**: `v2_ticker_master` holds **1,519**
  tradable stocks (HOSE 412, HNX 299, UPCOM 808), 1,516 with an ICB level-2 sector
  (HAX, HPG, ITS are SSI coverage gaps), plus VN30 (30) / VN100 (100) membership and the
  VNINDEX/VN30/VN100 benchmarks. The full per-ticker bar + ratio backfill is a
  multi-hour **resumable** job (~1 ticker/min at the conservative client rate cap),
  driven in `--limit` chunks with `python -m data.v2.jobs.precompute --full --limit N`
  (or the `precompute_v2.yml` workflow). Six reference tickers (FPT, HPG, VHM, LPB, PVD,
  DCM) were backfilled end-to-end (968 bars each + 305 ratio rows + liquidity + flags)
  to validate the pipeline.

### Security

- **`scripts/verify_v2_db.py` masks the database password.** The `database` line
  of the readiness report used to print `DATABASE_URL` verbatim, so
  `verify_report.txt` (uploaded as the `precompute-report` artifact) would carry
  a Supabase password whenever the workflow's `::add-mask::` step was skipped or
  the script was run locally. The line now renders the SQLAlchemy URL with
  `hide_password=True`, i.e. `***` in place of the password.

- **Repository prepared for the first push to a private remote.** `.gitignore`
  now blocks `Deployment prerequisite.txt` (the local cheatsheet holding a
  plaintext `DATABASE_URL` with its password plus a `REFRESH_TOKEN`), local
  scratch notes, SQLite sidecars (`*.db-wal`, `*.db-shm`, `*.db-journal`) and
  `*.dump`, and re-includes `!.env.example` after the `.env*` catch-all so the
  placeholder template stays the only committed env file. `git status
  --ignored` confirms `vnopt.db` (~19 MB), `packages/data/vnopt.db`, `.env`,
  `.env.local` (root and `apps/web`), `.venv/`, `node_modules/`, `.next/` and
  the tool caches are ignored and neither staged nor untracked. A scan of all
  434 non-ignored text files and of the staged tree found no credentials, JWTs
  or live database URLs once ignored files were excluded; the remaining matches
  are the `change-me` / `sqlite:///./vnopt.db` placeholders in `.env.example`,
  the `test-token` and `postgresql://user:pass@host:5432/db` test fixtures, the
  `INVALID_TOKEN` provider fixtures, env-var names in code and docs, the
  `x-refresh-token` header in the generated OpenAPI schema and the `js-tokens`
  npm dependency. **Rotate the Supabase database password and the refresh token
  that were stored in `Deployment prerequisite.txt`.**
- Local backup of the pre-git tree kept outside the repository at
  `../vnopt_backup_20261124` (436 files, 21.5 MB, `vnopt.db` byte-identical,
  SHA-256 verified).

### Fixed

- **Incremental V2 runs keep the historical `v2_progress` row count and stop
  re-polling known-empty tickers.** `V2Store.set_progress` (`data/v2/store.py`)
  keeps a ticker's stored `rows` when a checkpoint arrives with `0`: an
  incremental fetch that brought no new bar for a ticker that already had stored
  rows reported `0` and blanked the count (the success path also wrote only the
  incremental delta instead of the cumulative count). The count is now the
  `v2_daily_prices` bar total read with `count_prices`, while `state`,
  `last_date`, `error` and `updated_at` still advance — the conflict update now
  sets `updated_at` explicitly because `insert().on_conflict_do_update()` does not
  apply the column's `onupdate`. `_backfill_prices` also filters and orders its
  candidates through a new `_order_price_candidates` helper: tickers that already
  have prices come first, so `--limit` updates the tracked stocks before it
  backfills a new one, and an `incremental` run without `--profiles` drops the
  tickers whose checkpoint is `done` with no stored bar, so a symbol that never
  trades no longer costs a daily API call. A `--full` run or an explicit
  `--profiles` keeps them, so the periodic refresh still re-checks them, and
  emptiness is decided by `v2_daily_prices` so a legacy `0` cannot hide a priced
  ticker. Covered by four new `test_v2_precompute.py` tests (row-count
  preservation, `updated_at` refresh, known-empty skip/re-check and `--limit`
  priority).
- **V2 ratio sync no longer aborts on a provider's duplicate period.** The
  GitHub Actions run failed on `AAH` with
  `psycopg.errors.CardinalityViolation: ON CONFLICT DO UPDATE command cannot
  affect row a second time`, because SSI's `finance-indicator` response repeated
  one `(symbol, period, period_type)` inside a single batch. `_bulk_upsert`
  (`data/db/repositories.py`) now merges rows that share a conflict key through a
  new `_dedupe_rows` helper before the statement is built — the last value wins,
  a `None` never blanks a populated value, and mapping values (ratios,
  percentile ranks) are merged — so `V2Store.upsert_ratios` stores one row per
  key. The same guard covers every other upsert that receives provider-shaped
  batches (`prices`, `sectors`, `ticker_master`, `adjustment_flags`,
  `sector_statistics`, plus the V1 price/index repositories);
  `V2PrecomputeService._sync_ratios` also collapses repeated periods before it
  builds its records, so the checkpoint's row count is the stored count. Covered
  by `test_upsert_ratios_merges_duplicate_periods_in_one_batch`.
- **Portfolio values from the V2 spot close and flags trailing bars.** A holding
  could show a stale Friday close (e.g. FPT 45,000 and HPG 20,450 on 2026-11-20)
  while the header badge implied the latest session was current and `Notes` said
  `ok`, because the Portfolio endpoint read the V1 `prices_daily` table that had
  lagged one session. The endpoint now reads
  `DataService.get_prices_preferring_v2_spot` — the V2 **raw** (`close_raw`) close
  for a symbol with V2 bars, falling back to V1 only when V2 has none — so a holding
  values at the freshest actual market price (FPT → 46,850, HPG → 20,400 at
  2026-11-23) and reports the true V2 source/date (`ssi_statistics`) instead of a
  stale V1 `kbs` bar. Each holding's latest bar date is now compared against the
  global latest session across **both** price stores, so a ticker that trails the
  market is flagged `stale (YYYY-MM-DD)` in `Notes` rather than `ok`.
  `GET /api/v1/data/freshness` likewise spans V1 and V2 and reports the V2 source
  when it owns the latest bar, so the header badge matches the Portfolio page.
  Covered by new `test_portfolio_endpoint.py` V2-preference and stale-bar tests, a
  `test_data_endpoint.py` V2-source test, and `test_sync.py` spot-reader and
  overall-latest-date tests.

### Added

- **V2 review hardening and correctness fixes** (acceptance review against
  `docs/V2_SPEC.md` section 12): the Max-Sharpe marker now sits on the efficient
  frontier; the Optimize and Frontier prices use V2 adjusted closes
  (`DataService.get_prices_preferring_v2_adjusted`); Portfolio/P&L data wording is
  clearer; migrations 0001-0005 use `sa.text("0")` for integer server defaults so
  they run on Postgres; and new tests cover the V2 price path, the fundamentals 404
  drill and the migration upgrade/downgrade chain.
- **Sector Analysis — Fundamentals sub-tab (V2b UI)** (`docs/V2_SPEC.md`
  section 3.3). The sector page's placeholder "Fundamentals (soon)" tab is now live:
  - ticker search, a period selector (TTM only; annual/quarterly disabled with a
    "not enough data yet" tooltip) and an all/liquidity/VN100 peer toggle;
  - scorecard cards grouped by ratio category, each with a direction-aware
    better/similar/worse verdict (within 10% of the sector median is "similar";
    valuation multiples are neutral; fewer than 5 peers shows
    "insufficient peers (N < 5)");
  - a detail table (ticker value, sector median, winsorized mean, percentile rank,
    N) that renders "n/m" for not-meaningful values, repeats the reporting period
    under every value column and warns when N < 5;
  - a box plot of the sector distribution with the ticker marked, labelled axes and
    tooltips;
  - the reporting period, provider and data-as-of metadata;
  - a shared ticker detail drawer opened from each Optimize result row.
  - `GET /api/v1/v2/fundamentals/{symbol}` now returns per-ratio `label`,
    `category`, `category_label` and `is_percentage`, the box-plot quartiles
    (`q1`/`q3`) and extremes, and the `provider`, so the UI renders the registry
    instead of hardcoding it. Group labels read "Banks", "Financial services"
    (not "Securities"), "Insurance" and "General companies".

- **V2b fundamentals pipeline: ratios, sector statistics and peer variants**
  (`docs/V2_SPEC.md` section 6). The SSI `finance-indicator` ratio path is persisted
  and peer-compared:
  - `data.v2.ratios` is the single source of truth for the three peer groups
    (general, banks, securities) and their trimmed ratio sets, the ICB level-2 →
    group mapping (`Banks` → banks, `Financial Services` → securities), the
    direction-aware colouring (higher/lower/neutral), the P/E–P/B "n/m" rule for
    non-positive multiples, and the pure winsorized-mean (5th/95th), percentile and
    percentile-rank helpers.
  - **Quarterly-vs-TTM resolved** (`docs/V2_SPEC.md` open item 3): the recorded
    `finance-indicator` fixture marks interim quarters `ttmType="1"` (trailing 12
    months) and the audited full year `ttmType="0"`; `_period` now maps those to
    `ttm`/`annual` (Q4, which publishes no ratios, stays `quarter`), and
    `get_latest_ratios` fetches only the first page for the incremental refresh
    (~1 request per ticker, the section-8 budget).
  - New tables `v2_financial_ratios` (per ticker/period, trimmed to the group) and
    `v2_sector_statistics` (median, mean, winsorized mean, p5/p95, min/max, N and
    per-ticker percentile ranks), migration `0005`.
  - `data.v2.fundamentals` aggregates the per-(sector, ratio, period) statistics and
    exposes `FundamentalsService` with peer variants (`all`, the active liquidity
    preset, or VN100) that reuse `filter_universe`, so financials are never compared
    with non-financials.
  - `data.v2.ratio_quality` runs warning-only ratio checks (stale periods, outliers,
    unit mismatches, missing tickers); the precompute pipeline gains `ratios`,
    `sector_statistics` and `ratio_quality` steps.
  - `GET /api/v1/v2/fundamentals/{symbol}` returns a ticker's ratio comparison
    against its sector peers.
  - **Non-financial ratio probe**: `scripts/probe_v2_ratios.py` records real
    `finance-indicator` pages for FPT/HPG/VNM under
    `packages/data/tests/fixtures/v2/` (3 requests). It confirmed the TTM / annual /
    quarter period mapping and that every general-set ratio is populated; `npl` is
    present in the feed but `0.0` for non-financials, and the general set trims it
    out, so `GENERAL_RATIOS` needed no change.
  - **Insurance safe-default group** (`insurance`: ROE, ROA, P/E, P/B) for the ICB
    level-2 `Insurance` sector, which fits neither the general, bank nor securities
    template (`docs/DECISIONS.md` D-021). The other 18 sectors keep general / banks /
    securities as before.
  - `scripts/verify_v2_ratios.py` (plus the pure `data.v2.ratio_verify` module)
    prints the tickers with ratios, the latest period per ticker (min/max), the
    group counts, per-sector peer counts and how many sectors reach N >= 5, the null
    share per ratio for each group, the `v2_sector_statistics` row count and the
    ratio-quality warnings.


### Changed

- **V2b ratio quality calibration and quieter verification output** (triaged from a
  live precomputed ratio dataset):
  - `unit_mismatch` now fires only when a percentage ratio is below its fraction-like
    threshold **and** collapsed at least `UnitMismatchParams.collapse_factor` (100x)
    versus the most recent prior period. Genuine low values (a sub-1% ROE, a ~1% net
    margin) are no longer flagged; a real 100x unit error still is.
  - `ratio_outlier`'s `netProfitMargin` bound is raised from 100 to 500: a net margin
    over 100% is possible for a company with large non-operating gains.
  - The `ratio_quality` precompute step only checks (and emits `no_ratios` for)
    priced tickers or tickers that already have ratios; tickers with no prices are
    reported as one count line, and other findings are logged individually up to
    `RATIO_WARNING_LOG_LIMIT` (30) with a count for the remainder.
  - `scripts/verify_v2_ratios.py` prints the null share per group for the **latest
    period only** and a per-period-type table (instead of one overall figure), and
    replaces the per-ticker latest-period list with a min/max plus a histogram of
    tickers per latest period. Sector statistics, percentiles and peer counts `N`
    already use only non-null usable values, so they are unchanged.
- **Sector Analysis polish — window-aware exclusion, plain reasons and clarity**
  (`docs/V2_SPEC.md` section 3.2, `docs/DECISIONS.md` D-019/D-020):
  - Default exclusion is **window-aware**: a ticker is dropped only when a
    return-corrupting anomaly falls inside the analysis window (plus the first return
    day's source session). The excluded panel lists the in-window anomaly dates and
    category per ticker and a separate "flagged earlier, not affecting this window"
    list.
  - Anomalies on a very-low-liquidity day (stored matched volume/value far below the
    ticker's median) are labelled **thin trading**, not a data glitch.
  - Flags gain a per-anomaly `anomalies` JSON column (migration `0004`) and
    `FLAGS_POLICY_VERSION` moves to `D-019`; `flags_policy_current` marks old rows
    stale and `--recompute-flags` refreshes them.
  - The excluded panel shows one plain-language line per ticker (main reason +
    affected-date count) with expandable details; jargon ("adjusted/raw ratio
    drifted", "reconciliation difference") is replaced.
  - A greyed sector with < 3 constituents says "Too few stocks (needs 3)"; "Low
    reliability" is reserved for < 60 observations. Infeasible single-stock caps show
    a "cap off" marker and a footnote.
  - The movement chart uses "May 2026" / "20 May" date ticks, a "VN-Index" legend and
    a dashed grey benchmark line; the scatter is coloured/labelled per sector; the
    heatmap's neutral stop is an opaque grey on the same -1..+1 scale.
  - The Sector tab drops the duplicate footer disclaimer (fixing the "is are" typo).


- **Adjustment-flag policy versioning and offline recompute** (`docs/DECISIONS.md`
  D-018). No schema change:
  - Each stored flag row's `source` now carries `|policy=D-017`; `flags_policy_current`
    (analytics payload and `GET /v2/universe`) is `false` for rows written under an
    older policy, and the Optimize filter panel shows "adjustment checks are outdated;
    rerun the update".
  - `python -m data.v2.jobs.precompute --recompute-flags --members VN100` refreshes
    only the flags from the stored prices and corporate actions (no network,
    idempotent).
  - `scripts/verify_v2_db.py` prints the flagged, excluded and flagged-but-included
    counts, the excluded tickers and whether the flags policy is current.
- **Quality severity policy, ISS reconciliation and calendar-aligned returns**
  (`docs/DECISIONS.md` D-017, triaged from the VN100 backfill). No price or schema
  change:
  - Only integrity findings fail the quality/precompute step: `no_data`,
    `duplicate_dates`, a stale latest bar, an empty benchmark calendar and schema
    errors. Per-ticker findings (`missing_trading_days`, `zero_volume_streak`,
    `suspicious_returns`, `adjusted_vs_raw_mismatch`) are now `warning` and are
    stored as adjustment flags with reasons.
  - `reconcile_corporate_actions` marks any ex-date carrying an ISS `unsupported`
    (the `-ratio/(1+ratio)` model is the bonus-share model and is wrong for rights
    issues); only all-DIV events are verified. A positive adjusted gap on a flat raw
    close at an ISS ex-date is `adjustment_suspect` (a spurious gain, EVF/NVL).
  - `data.v2.returns.calendar_returns` derives returns on the benchmark calendar, so
    a halt/suspension does not become a multi-day return on the resume date mixed
    with the benchmark's daily return. The Sector Analysis service uses it.
  - `adjustment_quality_flag` sets `exclude_from_group_indices` only for
    return-corrupting anomalies (a reversing adjusted move, a >15% move, a
    reconciliation difference/suspect); the Sector service drops those names by
    default and leaves plain adjusted-vs-raw drift as a warning.
  - `EXPLAINED_FINDINGS` extended with the GEE/MCH/NAB/TAL/VTP one-day glitch and the
    GEE/TAL/VTP/NAB/MCH/SIP halt cases.

### Fixed

- **Market-cap weighting collapsed to equal weight once the 15% cap applied**
  (`data.v2.analytics.index.target_weights`). Raw market caps were passed to
  `apply_cap` before normalising, so every name looked over the cap and was set to it,
  giving un-normalised equal weights (the return hid it by dividing by the available
  weight). Weights are now normalised before the cap, so they sum to one and keep the
  market-cap ordering. A regression test and the reconciliation script cover it.


- **V2 precompute validation fixes** (see `docs/V2_PRECOMPUTE_VALIDATION.md` and
  `docs/DECISIONS.md` D-010..D-012):
  - `corporate-actions` is now queried with `fromDate`/`toDate` = the backfill
    window, and a `data: null` body reads as an empty result instead of a
    `SchemaError` (recovers HPG's market cap).
  - `_sync_profiles` persists market cap/shares even when the corporate-action
    fetch fails, and reports such partial failures separately (a `partial`
    progress state, retried next run) instead of discarding the profile.
  - `reconcile_corporate_actions` combines every action on one ex-date into a
    single finding and compares the compounded implied gap with the total removed
    gap.
  - The missing-trading-days check uses the trading calendar derived from the
    stored VN-Index bars (`trading_days_from_dates`) instead of the illustrative
    2025-only holiday set.
  - The precompute path gets an explicit configurable requests-per-second cap
    (0.5 rps default) with 429 backoff and a 403 host cooldown.
  - `_period` skips rows with `yearReport = 0` instead of raising.
  - The pre-screen default drops to 10,000 shares and is documented as a
    backfill-cost floor, not a liquidity filter.
- **Retroactive price re-base detection in the incremental price step.** SSI
  re-adjusts a ticker's whole adjusted history when a new corporate action's
  ex-date lands, so an incremental run that fetched only new dates left old rows
  stale. The incremental fetch now also re-fetches a tail overlap
  (`precompute_rebase_overlap_sessions`, default 40 sessions) and compares the
  overlapping adjusted closes with the stored ones (`precompute_rebase_tolerance`,
  default 0.01%); on a mismatch it re-fetches the full history and replaces the
  old rows in the same run. Detection uses prices only, never the corporate-actions
  feed (which omits some bonus issues), so HPG-like cases are covered.

### Added

- **`scripts/reconcile_sector_analytics.py` — read-only Sector reconciliation.**
  Prints the engine's Banks/Real Estate constituents, weights, excluded tickers and
  metrics and compares them with an independent pandas computation from the stored
  prices (weights derived from stored market caps + the cap), reporting any difference
  above a tolerance. No network.


- **Sector Analysis tab — Market sub-tab** (`docs/V2_SPEC.md` section 3.2):
  - `GET /api/v1/v2/analytics` exposes the analytics engine's `AnalyticsPayload`
    (sector-beta groups, correlation matrix, benchmark path, default-excluded
    tickers). A settings + `data_as_of` cache serves a repeat request from memory
    (`served_from_cache`, `elapsed_ms`) and a data-date change invalidates it; the
    cached payload carries no per-request fields.
  - Explicit 422s for an unknown benchmark/preset/grouping, a custom window without
    both dates, a start after the end, a window outside the stored data, a
    `cap_percent` outside (0, 100] (or null), and an unknown weighting.
  - `include_default_excluded` (default false) includes the tickers the adjustment
    checks drop; the payload lists them (`default_excluded`) with a per-sector
    `default_excluded_count`, and `benchmark_returns` feeds the chart.
  - New web page `/sector`: benchmark / Sector timeframe / liquidity preset /
    weighting controls from the shared store (never filtering by `v2Filter.sectors`),
    a Relative Sector Movement chart (benchmark emphasised, legend toggles), a
    sortable beta & performance table with low-reliability badges, greyed
    `insufficient` rows and per-row send checkboxes, an optional return-vs-beta
    scatter, a clustered cross-sector correlation heatmap with the average
    correlation, an always-visible excluded-tickers panel (with the Optimize
    stale-flag caveat), data/basis labels, the current-constituents note, a
    limitations note and the disclaimer. "Send sectors to Optimizer" writes the
    ticked sectors to the shared `v2Filter` and navigates to Optimize.
  - The store gains `weighting`, `capPercent` and `includeDefaultExcluded` plus a
    Sector timeframe (`1M/3M/6M/YTD/1Y/3Y/custom`); `APP_STORAGE_SCHEMA_VERSION` is 4
    and a version-3 payload migrates by filling the defaults.

- **`--members {VN30,VN100}` precompute option and a V2 DB verification script.**
  `--members` restricts the price/profile/liquidity/quality/adjustment-flag steps
  to one index's stored members while the master, membership and benchmark steps
  stay full-universe (used to populate a dev database with VN100 only).
  `scripts/verify_v2_db.py` prints, for `vnopt.db`, the per-table row counts, the
  database file size, tickers (and VN100 members) with prices, sector and
  market-cap coverage, benchmark bar counts, the price date range, the
  adjustment-flag count, the latest `data_as_of`, unfinished progress rows and the
  sectors with at least 3 tickers passing the Standard Retail preset.
- **V2 universe filter endpoints + Optimize filter panel** (spec sections 3.1 and 8):
  - `GET /api/v1/v2/universe` calls the same `filter_universe` the analytics engine
    uses (sector ICB level 2, VN30/VN100, exchange, preset, `as_of`) and returns
    `data_as_of`, the basis flags, kept/rejected tickers, stored adjustment-quality
    flags and warnings. It reads only the V2 tables and returns `available: false`
    with a clear "V2 data not available" message on an empty database instead of
    failing, so V1 keeps working.
  - `GET /api/v1/v2/sectors` returns each ICB level-2 sector with total and
    preset-passing constituent counts.
  - The Optimize tab's new `UniverseFilterPanel` reads/writes the shared `v2Filter`
    in the app store (preset, sectors, indexes, exchange, benchmark, exclude-flagged),
    renders the multi-select, the VN30/VN100 chips, the live "N tickers pass" counter
    and "Add all passing" (top N by ADTV, capped by the configurable
    `max_optimize_stocks`). Manual add/remove stays available.
  - Adjustment-quality flags are precomputed by the pipeline and stored in the
    additive `v2_adjustment_flags` table (migration `0003_v2_adjustment_flags`); the
    endpoints read them instead of recomputing per request, and `flags_available`
    distinguishes "not computed yet" from "no flags". Excluding flagged tickers is
    opt-in (default off).
  - Results show a sector tag and a small sector-allocation chart; market cap is
    labelled full (not free-float) and a note states the optimizer still uses V1 raw
    prices (feeding V2 adjusted prices to the optimizer is a follow-up).
  - `Settings.max_optimize_stocks` (default 30, `VNOPT_MAX_OPTIMIZE_STOCKS`) is
    published on `GET /optimize/options` and enforced with a clear 422.
- **Maximum-sector-weight constraint** (`max_sector_weight`): registered like the
  other constraints and applied to both the exact efficient frontier and the random
  cloud (per-stock and per-sector caps), with a clear infeasible-cap error. The
  sector map is validated server-side (unknown tickers bucket as "Unknown", a size
  limit, and a 422 on malformed input).
- **The built universe now persists fully.** `UniverseSelection` stores the raw
  `selected` tickers alongside the kept `symbols`, so manual edits and the built
  universe survive tab switches and reloads (the V1 bug).
- **V2 analytics engine** (`packages/data/data/v2/analytics/`, no UI): the
  Sector Analysis backend on the stored V2 tables. It reads stock data only through
  `V2Store` (the V2 tables), benchmark index bars through `SqlIndexRepository`
  (`indices_daily`), and the calendar from the stored VN-Index bar dates; returns are
  derived on read from the adjusted close (D-003). Pieces:
  - **Liquidity presets as config** (`liquidity.py`): Small Retail, Standard Retail
    (default), High-Liquidity and All Stocks with median ADTV/ADV/full-market-cap
    thresholds (spec section 4), plus `filter_universe` with sector, index (VN30/VN100)
    and exchange facets (OR within a facet, AND across facets).
  - **Pluggable grouping** (`grouping.py`): a `Grouping` interface plus a registry, so
    sector is one grouping beside exchange and index bucket.
  - **Current-constituents group index** (`index.py`): the 80%-of-trading-days rule
    (renormalising), full-market-cap weighting with an optional single-stock cap
    (default 15%, excess redistributed) or equal weight, quarterly rebalance with the
    cap re-applied, a minimum of three constituents (`insufficient` below that), and
    gap handling that drops a halted constituent from that day's return.
  - **Benchmark metrics** (`metrics.py`): cumulative return series (base 0%), period
    and excess return, beta (Cov/Var), R², correlation, annualized volatility,
    observation count and a `low_reliability` flag below 60 observations.
  - **Cross-group correlation** (`correlation.py`): pairwise Pearson matrix (symmetric,
    unit diagonal), hierarchical-clustering display order and average pairwise
    correlation.
  - **Timeframes** (`timeframes.py`): 1M/3M/6M/YTD/1Y/3Y/custom with graceful short
    history (the service clamps to the available data and warns).
  - **One JSON payload** (`schemas.py`, `service.py`): `AnalyticsPayload` with
    `data_as_of`, weighting, benchmark, window, price-adjustment/volume/market-cap
    bases and warnings.
- **Adjustment-quality flag** (`data/v2/adjustment_quality.py`): per-ticker flag for
  unexplained adjusted jumps or adjusted-vs-raw ratio drift and reconciliation
  differences, using the widest exchange limit (15%) as the sanity threshold. Flagged
  tickers are reported as a payload warning and can be excluded from group indices.
- **Two-level quality severity** (`data/v2/explained_findings.py`, `quality.py`): the
  documented known cases (SSI adjusted drift on VGI/OIL, HPG missing bonus issues, the
  BSR 2025-01-07..16 halt) are downgraded to warnings; unexplained findings stay errors
  and the quality step fails only on errors. The `suspicious_returns` check now uses the
  widest (15%) limit, removing the BSR 2024-05-22 false positive.
- Tests: synthetic beta = 1.3 for a 1.3x benchmark, cap redistribution summing to one
  and respecting the cap, partial-history/insufficient groups, symmetric unit-diagonal
  correlation, quarterly rebalance, the 80% rule, low reliability, end-to-end payload
  over a seeded SQLite database, and an independent `pandas` correlation cross-check on
  three sectors. `pandas` is a **test-only** dev dependency (not in the runtime bundle).

- **Real-data validation of the V2 precompute pipeline**
  (`scripts/validate_v2_precompute.py`, `docs/V2_PRECOMPUTE_VALIDATION.md`): runs the
  real `V2PrecomputeService` over a hand-picked ~20-ticker sample (banks, large caps,
  real estate, small/mid caps, HNX, UPCoM) for a 3-year window on a scratch SQLite
  database with the pre-screen disabled, instruments the HTTP client for per-ticker
  request counts/timing, and reports the six validation questions. Measured **27 OHLCV
  pages/ticker** (not the doc's 19) because `get_ohlcv` splits the range into 366-day
  windows; ~32.6 requests/ticker total, 653 requests for 20 tickers in 240 s, which
  extrapolates to ~22,855 requests for 700 tickers (~19 h at 20/min, ~2.3 h at the
  observed unthrottled throughput - the precompute path does not apply the runner's
  20/min limit). SSI's adjusted close reconciles with the corporate-action ratios it
  returns (all `ok`; `difference` rows are multiple actions sharing one ex-date and the
  reconciler compares them one-by-one), but `corporate-actions` is queried without a
  date window so only recent events come back and older ex-dates surface as
  `adjusted_vs_raw_mismatch`. HPG's market cap is lost because `_sync_profiles` discards
  a valid market cap when `corporate-actions` returns `data: null`; `get_ratios` also
  raises on `yearReport = 0`. The second (incremental) run fetched **zero** OHLCV pages.
  The report proposes lowering the pre-screen default from 100k to 10k median shares so
  "All Stocks" is not silently filtered (or labelling it if it must stay).

- **V2 resumable precompute pipeline** (`packages/data/data/v2/`, additive V2
  tables, `docs/DECISIONS.md`): builds the cleaned HOSE/HNX/UPCoM ticker master
  (ETFs, funds, covered warrants and bonds excluded; ICB level-2 sectors attached;
  sector coverage gaps reported and the gaps excluded from sector features, never
  guessed), VN30/VN100 membership with `as_of` + `source` (VN30⊆VN100 validated),
  VN-Index/VN30/VN100 benchmark series (VCI index bars → `indices_daily`), adjusted
  daily prices with matched volume/value and per-bar basis flags, rolling
  20-session ADTV/ADV medians, shares outstanding + full market cap, and DIV/ISS
  corporate actions for the quality checks. **Storage** reuses the repo's
  SQLAlchemy + SQLite/Postgres + Alembic stack (new migration
  `0002_v2_precompute`) with each dataset carrying `data_as_of`, `provider` and
  `price_adjustment_basis`/`volume_basis`/`market_cap_basis`. **Resumable and
  incremental**: cheap KBS volume pre-screen, per-ticker commits, `v2_progress`
  checkpoints; a second run fetches only new dates and an interrupted backfill
  resumes. **Quality checks fail loudly** (`missing_trading_days`,
  `duplicate_dates`, `zero_volume_streak`, `suspicious_returns` outside known
  ex-dates, `adjusted_vs_raw_mismatch`). New `V2Reader`/`ticker_snapshot` helper
  plus `GET /api/v1/v2/ticker/{symbol}` and `GET /api/v1/v2/coverage`; manual
  command `python -m data.v2.jobs.precompute`; scheduled
  `.github/workflows/precompute_v2.yml` (runner, weekdays after the close, with
  `workflow_dispatch` for chunked backfills). `docs/DECISIONS.md` records the
  storage, basis, scheduler and GitHub setup, and notes cloud-IP access to SSI
  remains **unverified** until `probe_v2.yml` runs on a runner. Tests cover rolling
  medians, incremental updates, resume/chunk logic, universe filtering/coverage,
  returns and the quality checks.

- **SSI iBoard `statistics` promoted into the V2 adapter layer** (new provider
  `ssi_statistics`, `packages/data/data/v2/providers/ssi_statistics.py`): one
  keyless adapter serves six data types from the recorded fixtures — adjusted
  daily OHLCV (`close` adjusted vs `closeRaw` raw, never `closePriceAdjusted`) with
  matched flow (`totalMatchVol`/`totalMatchVal`) and total `volume`; the bulk ICB
  **level-2** sector map (`sectors-data`, level 1 stays `None`) with `exchange`
  filled from the symbol master; normalized ratios (`finance-indicator`,
  percentages as fractions ×100, `yearReport`/`lengthReport` mapped to
  `period`/`period_type`); company profile (`sharesOutstanding`/`marketCap`,
  free-float stays `None`); DIV/ISS corporate actions (`exrightDate`, `ratio`,
  `value`); and the bulk ticker→exchange symbol master (stocks only). New typed
  schemas `CorporateAction` and `SymbolMaster`; `AdjustedOHLCV` gained optional
  `close_raw` and `matched_value`. New interfaces/registries/runner methods for
  `corporate_actions` and `symbol_master`, and `company_profile` is now wired into
  the chains (it was a stub). Active chains per `V2_SPEC.md` section 7 put
  `ssi_statistics` first for OHLCV/sectors/ratios/profile/corporate actions/symbol
  master, keep KBS for constituents, and keep the unverified providers out; per
  data-type rate limits are configurable. New `data.v2.pagination` (date windows +
  page crawl with page/row caps), `data.v2.symbols.merge_symbol_master` (SSI
  exchange + KBS tradable-stock merge) and `data.v2.reconcile.reconcile_corporate_actions`
  (reports adjusted-vs-raw ex-date differences, never hides them). Tests cover
  adjusted-vs-raw, matched volume/value, sectors, ratios, profile, actions, symbol
  master/merge, pagination and reconciliation. `scripts/probe_v2_candidates.py`
  gained `pageSize` 40/100/500 + date-window probes and the manual
  `.github/workflows/probe_v2.yml` now runs it too. `docs/V2_DATA_GAPS.md` records
  the pagination findings and the 3-year backfill call budget. Cloud-IP access to
  SSI (behind Cloudflare), larger page sizes and FPT/HPG reconciliation remain
  **unverified**.

- **V2 second keyless sweep + sector loader + price-gap adjustment** (docs, fixtures
  and two new data modules): `scripts/probe_v2_candidates.py` re-tested additional
  public candidates discovered from the providers' own web bundles (2026-11-22) and
  recorded real fixtures under `packages/data/tests/fixtures/v2/`. **SSI iBoard's
  `iboard-api.ssi.com.vn/statistics` service answers anonymously and fills four of the
  five gaps**: bulk ICB level-2 sectors (`/company/sectors-data`, 19 groups, ~1,975
  tickers), adjusted prices (`stock-info` `close` vs `closeRaw`) plus corporate actions
  (`/company/ssmi/corporate-actions`, DIV/ISS with `exrightDate` + `ratio`), shares
  outstanding + market cap and the full quarterly ratio set
  (`/company/ssmi/finance-indicator`), and matched vs put-through volume
  (`totalMatchVol` / `totalDealVol`). Free-float ratio is still unavailable, so
  market-cap weighting replaces equal weight. **VNDirect finfo** timed out (unreachable
  from this environment, unverified); **CafeF** serves JSON but no sector/shares;
  **VCI** profile/ratio/constituents remain SPA HTML; **Vietstock** data calls returned
  empty or non-JSON. New `data.v2.static_sector` loads an optional cited
  `data/reference/sector_map.csv` (columns `ticker,icb_level1,icb_level2,source,as_of`),
  validates it against the KBS symbol list and fails loudly on unknown tickers. New
  `data.v2.adjustment.adjust_price_gaps` is a clearly labelled heuristic that
  back-adjusts earlier OHLC around inferred split/bonus gaps with plausible-factor,
  IPO-day, post-suspension and per-exchange-limit safeguards. `SectorMap` gained an
  optional `as_of`. Updated `docs/V2_DATA_GAPS.md` and `docs/PROVIDER_PROBE.md`.

- **V2 data-gap investigation** (docs + fixtures, no code changes): a live, keyless
  sweep of all five V1 providers (2026-11-22) resolved the six open items from
  `docs/V2_SPEC.md` §10. New `docs/V2_DATA_GAPS.md` states, per gap (adjusted prices /
  corporate actions, ICB sector map, shares-free-float-market-cap, financial ratios and
  matched-only volume), the live finding, the recommended fallback and the affected
  V2a/V2b feature. `docs/PROVIDER_PROBE.md` gained a "Deep endpoint investigation"
  addendum. Real responses were recorded under `packages/data/tests/fixtures/v2/`
  (`kbs_data_day_sample.json`, `kbs_search_data_sample.json`,
  `kbs_financial_ratio_err.json`, `dnse_unauthorized.json`,
  `tcbs_service_not_found_404.json`, `ssi_iboard_404.json`). Outcome: only **KBS**
  (raw OHLCV + index constituents + symbol list) and **VCI** (POST chart OHLCV) answer
  keyless; **DNSE** is 401 auth-gated, **TCBS** is 404/Cloudflare-gated and **SSI
  iBoard** is 404. No keyless source exists for ICB sectors, shares/free-float,
  corporate actions or financial ratios, so those features need a static cited data
  file or are deferred.

- **V2 provider adapter layer** (`packages/data/data/v2`, no V1 changes): typed
  normalized schemas (`IndexConstituents`, `SectorMap`, `AdjustedOHLCV`,
  `FinancialRatios`, `CompanyProfile`), one adapter protocol per data type
  (`ConstituentsProvider`, `SectorMapProvider`, `OHLCVProvider` with
  `get_index_ohlcv` and bulk `get_sector_map_all`, `RatiosProvider`, and a
  `CompanyProfileProvider` stub) plus registries. Adapters: KBS (constituents,
  OHLCV, ratios), VCI (adjusted-or-raw OHLCV, ICB sector map, ratios,
  constituents), DNSE (OHLCV), SSI iBoard (OHLCV fallback) and TCBS (ratios).
  Per-data-type failover chains and all tunables live in `data.v2.config`
  (single source of order); `FailoverRunner` adds retry with exponential backoff
  plus jitter, an in-memory TTL cache, per-data-type rate limits, provider health
  tracking, request logging and a clear all-failed error. HTTP 429 is retried and
  HTTP 403 becomes a cached `BlockedError`. `scripts/probe_v2.py` writes
  `docs/PROVIDER_PROBE.md`; `.github/workflows/probe_v2.yml` is a manual,
  artifact-only runner. Only providers verified against a real response are in
  the active defaults (KBS OHLCV + constituents, VCI OHLCV); ratios, sector map,
  DNSE, SSI iBoard and TCBS are implemented but unverified and excluded.

- **Timeframe selector on Optimize and Risk** (`apps/web`): each tab now has a
  compact `TimeframePicker` (6M, 1Y, 2Y, 3Y, 5Y, Max, or a custom start/end) with
  a resolved-window readout ("start to end · ≈ N trading days"), an inline
  validation message and a "Use same as Optimize/Risk" copy link. Optimize
  defaults to 3Y and Risk to 1Y (the previous behaviour). The selection lives in
  the shared persisted store (`app-store.ts`, schema version bumped to **2**;
  version-1 payloads are migrated by filling the defaults instead of being
  discarded), so it survives tab switches and reloads. The resolved `start`/`end`
  drive `buildUniverse`, `runFrontier` and `compareRisk` end to end, so returns,
  covariance, the frontier, the random cloud, every risk metric, the benchmark and
  the performance chart share one window. Windows are validated before any
  request (start before end, end not after the latest data, at least ~60 trading
  days), and a changed timeframe marks existing results as outdated instead of
  wiping them. New pure helpers and tests: `lib/timeframe.ts`,
  `lib/timeframe.test.ts`.
- **Interactive charts with labelled axes** (`apps/web`): migrated the efficient
  frontier, historical performance, drawdown and correlation heatmap to
  **Recharts** (React 19 compatible, ~100 KB gzipped). Shared styling and
  formatters live in `lib/chart-theme.ts`. The frontier has hover tooltips
  (volatility, return, Sharpe and weights), clickable points that keep the risk
  slider in sync, a highlighted selected point and chips to show/hide the random
  cloud and the capital line. The performance chart has a crosshair tooltip
  (level and percent versus the start), clickable legend toggles, a dashed
  baseline at 100 and a brush with a "Reset zoom" button; its summary table is
  labelled "Full timeframe". The drawdown chart has a crosshair tooltip and marks
  the maximum-drawdown point, and the heatmap names the hovered pair
  ("VHM vs LPB: 0.32"), highlights its row/column and shows a -1..+1 colour
  legend. Every chart is responsive and carries an aria-label. The P&L bars
  (P&L by stock, market value vs cost) and the Rebalance current-versus-target
  weights are now horizontal Recharts bars with VND / percent axes too.

### Fixed

- **Risk tab ignored the selected timeframe** (`packages/data`, `apps/api`): the
  picker sent the resolved `start`/`end`, but the data layer only backfilled a
  symbol when it had *no* stored bars, and always fetched
  `VNOPT_ON_DEMAND_HISTORY_DAYS` (default 365) with no way to extend an existing
  series backwards. A 3Y/5Y/Max request therefore returned the ~1 year that was
  already cached (and the benchmark index was truncated the same way), so the
  Risk result sentence, performance chart and metrics all matched the 1Y window.
  `SyncService.sync_symbol`/`sync_benchmark` now accept a `start` date and extend
  the stored history backwards to cover it (fetching up to today so the bars
  overlap and the existing cross-provider consistency check still applies), and
  `DataService.get_prices`/`get_index_prices` pass the requested window through
  when it is explicit. Optimize and Risk already shared `_load_symbol_series`, so
  both tabs now reach the full available history. New tests in
  `packages/data/tests/test_sync.py` and `apps/api/tests/test_risk_endpoint.py`;
  the response window is the actual data window. **Deployed 2026-11-22** to
  `vn-portfolio-optimizer-re` (`A7UxCMn46CtdkrFu9eupTLXVsLcp`, alias
  `https://vn-portfolio-optimizer-re.vercel.app`). Live check on VNM/FPT/ACB:
  6M → 126 returns, 1Y → 247, 3Y → 745, Max → 2495 (2016-11-23..2026-11-19),
  Custom → 716, each with distinct volatility/Sharpe/drawdown. Caveat: the first
  *cold* 10Y fetch can exceed the 120 s function limit (504); the partial fetch
  is committed per symbol, so a retry completes (~6 s). Raise `maxDuration` or let
  the nightly sync warm deep history if cold Max requests are common. The
  production smoke test passed 17/17.

### Changed

- **V1.1 Step 8 — Deployed to Vercel; pgBouncer prepared-statement fix**
  (`packages/data`, `scripts/smoke_test.py`, `README.md`, `docs/DEPLOYMENT.md`):
  - **Deploy (2026-11-22)**: API → `https://vn-portfolio-optimizer-re.vercel.app`
    (`dpl_CLNNa3qgDrGFqbKtMGxZFZ4dvzzV`), web →
    `https://vn-portfolio-web.vercel.app` (`dpl_36V6HZibs14RT8buuxck5GovQ3kw`), both
    region `sin1`. The FastAPI function bundles to **73.3 MB** (scipy-dominated, well
    under the 500 MB Python limit) and `maxDuration` stays `120` (< Hobby 300).
    `vercel.json` needed no route changes (framework presets, no rewrites) and the
    nightly cron `/api/v1/data/refresh @ 30 8 * * 1-5` is intact (triggered once by
    hand). The four API secrets (`DATABASE_URL`, `PROVIDER_ORDER`, `REFRESH_TOKEN`,
    `CRON_SECRET`) and the web `API_URL` were copied from production to the
    **Preview** environment (they were Production-only) so the preview smoke could
    run.
  - **Fixed — intermittent `DuplicatePreparedStatement` 500s**
    (`data/db/base.py`): the first frontier/P&L requests returned data, then later
    ones failed with `psycopg.errors.DuplicatePreparedStatement`. The API connects
    through Supabase's transaction pooler (pgBouncer, port 6543), which cannot keep
    server-side prepared statements between transactions, while psycopg3 creates
    them automatically. `create_engine_for` now takes `connect_args` from a new
    `connect_args_for(url)` helper that sets `prepare_threshold=None` for
    `postgresql+psycopg` URLs (SQLite keeps `check_same_thread=False`). New unit
    tests in `test_db_base.py`. This removes a production-only 500 on every
    data-heavy endpoint (frontier, risk, P&L, rebalance, probe).
  - **New `scripts/smoke_test.py`**: reusable post-deploy check (httpx; token from
    `--token`/`VNOPT_REFRESH_TOKEN`, optional `--bypass` for protected previews;
    never prints secrets). It covers `/health`, `/data/probe` (kbs), `/symbols`,
    `/optimize/frontier` (frontier + min-variance + max-Sharpe), `/risk`,
    `/pnl/evaluate`, `/rebalance`, the removed `/backtest` and `/montecarlo` (must
    404) and the six web pages.
  - **Results**: preview smoke **9/9 twice**; production smoke **17/17 twice**
    (health, probe→kbs, symbols ×1519, frontier, risk, P&L, rebalance,
    backtest/montecarlo 404, `/portfolio` `/pnl` `/optimize` `/risk` `/rebalance`
    `/settings` 200, `/universe` `/simulation` 404). The cron refresh returned 200
    (bounded batch) and the freshness badge shows `2026-11-20` with `primary: kbs`.
  - **Decisions/notes**: the default `/data/probe` (three tickers, every provider,
    five years) exceeds the 120 s function limit (504), so the smoke test probes one
    ticker over one year (still proves kbs). The **web preview** sits behind Vercel
    Authentication (302 → `sso-api`) with no automation bypass, so the page checks
    run on the public production alias. When a partial sync ends on a failing
    symbol, the in-memory circuit breaker marks every provider unhealthy
    (`freshness.primary` → null) until a successful fetch resets it; a subsequent
    `VNM/FPT/ACB` backfill restored `primary: kbs`. Rollback: `vercel rollback`.
    `Deployment prerequisite.txt` (repo root) holds plaintext `DATABASE_URL` and
    `REFRESH_TOKEN` and is not git-ignored — rotate and remove it. Ruff, mypy, the
    web linter/type-check and `make check` all pass (pytest **268**).

- **V1.1 Step 7 — Rebalance reads the chosen mix; docs and rules refreshed**
  (`apps/web`, docs, `.clinerules`):
  - **Rebalance** (`RebalanceCalculator`, `lib/rebalance-targets.ts`,
    `lib/optimize-context.tsx`): target weights now start from the optimized mix
    saved with "Use this portfolio" on the Optimize page (the store's
    `chosenPortfolio`, exposed as `chosenWeights`) and fall back to the current
    portfolio weights when no mix is saved. Targets stay editable, a "Use
    optimized weights" button re-applies the saved mix, and a short note states
    which starting point is in effect (it switches to manual after an edit, an
    added row or a CSV import). The cost model and the `full` /
    `threshold_band` policies are unchanged. The conversion is a pure helper
    (percentages truncated to two decimals so a fully invested mix never exceeds
    100%) with Node unit tests added to `npm test`.
  - **Docs**: `ARCHITECTURE.md` now describes the V1.1 components, the six pages,
    the single persisted store (hydration, schema version, legacy migration), the
    domain modules and the actual `/api/v1` routes instead of the removed
    Universe/Simulation pages, Monte Carlo, backtest and Ledoit-Wolf. `ROADMAP.md`
    lists the V1.1 state (P&L shipped, frontier, chosen-weight rebalance) and the
    removed items as V2 candidates; `README.md` gains a plain-language page table
    and the method scope; `DATA.md` explains what the data layer feeds in V1.1
    (Optimize builds the universe internally, the Universe page is gone);
    `EXTENDING.md` drops the stale `risk_parity` import from the registration
    example.
  - **Rules**: `.clinerules/01-project-rules.md` now records the active registry
    set, the CFA Level 1/2 scope, the removed methods, the one-persisted-store
    rule and sample-only estimators.
  - **Typed client**: regenerated with `make client`; no schema change.
  - **Decisions noted**: Rebalance keeps the user's own cash for the order plan
    and only takes the weights from the store; percentages are truncated rather
    than rounded to guarantee a total at or below 100%; `docs/DEPLOYMENT.md` was
    left for the deploy step (Step 8) since it is not in the Step 7 document list.

- **V1.1 Step 6 — P&L page from holdings only** (`packages/core`, `apps/api`,
  `apps/web`, tests, docs):
  - **Core** (new `core/pnl.py`): `compute_pnl` values each owned holding at the
    latest close and returns the cost basis (`shares × avg_cost`), market value,
    unrealized P&L in VND and percent, weight, share of total P&L, cash and the
    "P&L if sold today, net of costs" figure (the user's brokerage fee via
    `core.costs.commission` plus the 0.1% `market_rules.sell_tax`).
    `compare_buy_return` measures a stock's price return since a buy date against a
    benchmark over the same window, and `first_close_on_or_after` resolves a
    weekend/holiday buy date to the next trading day. `Holding` gains an optional
    `buy_date`. The module is pure: no network or database access.
  - **API** (`POST /pnl/evaluate`): accepts holdings (with optional `avg_cost` and
    `buy_date`), cash and `settings`, backfills prices on demand, compares dated
    holdings with VN-Index, and returns summary figures plus per-holding rows.
    Holdings missing an average cost are listed with a prompt but excluded from
    the P&L totals (counted in `excluded_count`); missing prices are flagged too.
    Regenerated the typed client.
  - **Web**: new `P&L` navigation entry and page. Portfolio holdings gain an
    optional buy date in the table, JSON library and CSV (`symbol, shares,
    avg_cost, buy_date`; the old three-column header still imports). The page
    shows summary cards (market value, cost basis, unrealized P&L VND/%, P&L
    after sell costs, cash, total value), a per-holding table, a P&L-by-stock bar
    chart, a market-value-vs-cost chart, winners/losers with colour **and** a
    +/− sign, and notes on realized profit/dividends, broker average cost and the
    latest close.
  - **Tests**: hand-computed P&L and net-of-costs, missing `avg_cost`/price
    exclusion and counts, wishlist handling, buy-date comparison, cash in totals,
    CSV buy-date round trip and validation, and API tests for the endpoint.
  - **Decisions noted**: `core/pnl` is a single module (P&L has no registry);
    buy-date comparisons use VN-Index with no selector; weight is market value
    divided by holdings plus cash while the P&L totals exclude incomplete
    holdings; buy dates are optional and backward compatible, so the stored-store
    schema version is unchanged.

- **V1.1 Step 5 — Risk page replaces Risk & Backtest** (`packages/core`,
  `apps/api`, `apps/web`, tests, docs):
  - **Core** (`core/risk`): `RiskContext` now carries the user's
    `risk_free_rate`, and `compute_risk(..., risk_free_rate=...)` takes it as an
    explicit parameter (never read from settings). Three metrics join the
    registry: `sharpe`, `treynor` and `jensens_alpha` (annualized excess return
    over the user's risk-free rate, divided by total volatility, by beta and as
    the CAPM-implied excess). `compute_risk` now also returns a `Performance`
    block (growth of 100 with total return, geometric annualized return and max
    drawdown) via the new `core.risk.performance.compute_performance`. A new
    `compute_benchmark_risk` models the index as a one-asset portfolio so it runs
    through the same metric code (beta is 1, Jensen's alpha is 0).
  - **API** (`POST /risk`, new `POST /risk/compare`): the single-portfolio
    endpoint accepts `settings`, echoes `assumptions` and now returns the
    `performance` block. The new compare endpoint takes the shared universe and
    window plus optional current/optimized weights and returns four blocks
    (current, optimized, equal weight, benchmark), each with weights, metrics and
    its growth series. Regenerated the typed client.
  - **Web**: `RiskCalculator` rewrites the page as a side-by-side comparison of
    the current, optimized, equal-weight and benchmark portfolios, with plain
    language metric tooltips, an SVG historical performance chart (growth of 100
    for all four, with total/annualized return and max drawdown), the drawdown
    chart and the correlation heatmap. The benchmark selector and VaR confidence
    sit behind an "Advanced settings" toggle (benchmark defaults to VN-Index). It
    re-runs once on mount when a saved universe and portfolio exist.
  - **Tests**: hand-computed Sharpe, Treynor and Jensen's-alpha examples (with the
    risk-free rate), growth/total/annualized/max-drawdown performance checks, the
    benchmark beta-1/alpha-0 identity, and API tests for the compare endpoint and
    the echoed risk-free rate.
  - **Decisions noted**: Sharpe, Treynor and Jensen's alpha return `null` (shown as
    a dash) instead of failing the whole comparison when volatility or beta is
    degenerate; equal weight is `1 / n` over the kept universe; the benchmark is a
    one-asset portfolio; the risk-free rate travels with every request as a user
    setting. Realized P&L and any transaction log are out of scope (Step 6 only).

- **V1.1 Step 4 — efficient frontier with Monte Carlo** (`packages/core`,
  `apps/api`, `apps/web`, tests, docs):
  - **Core** (`core/optimize/frontier.py`): `build_efficient_frontier` draws a
    long-only, `max_weight`-capped Dirichlet cloud (default 5,000, hard cap 20,000,
    explicit seed, vectorized numpy, `Settings.frontier_time_budget`), sweeps ~40
    target returns from the minimum-variance return to the best single-stock return
    (minimum variance per target; solver failures and monotone-violating targets are
    skipped and counted), and returns the minimum-variance, tangency (maximum-Sharpe,
    refined and checked against every random portfolio), equal-weight and
    current-portfolio points. It reuses the registered `min_variance`/`max_sharpe`
    objectives; long-only and fully invested are the SLSQP bounds/equality and
    `max_weight` is a per-position box bound. The old `core.montecarlo` code was
    already removed in Step 2, so there was nothing left to delete.
  - **Settings**: replaced the now-dead `montecarlo_max_simulations` /
    `montecarlo_time_budget` with `frontier_max_portfolios` (20,000) and
    `frontier_time_budget` (30.0); updated `.env.example`, `README.md` and
    `docs/DEPLOYMENT.md`.
  - **API**: `GET /optimize/options` now publishes `frontier_defaults`; new
    `POST /optimize/frontier` returns the cloud, the exact frontier and the marked
    points, each with integer lots/shares/values/residual cash for the chosen
    capital, plus a frontier assumptions block (data sources, dates, raw prices,
    risk-free rate, sample estimators, seed, counts, skipped targets) and the
    in-sample warning. Empty symbols, more than 30 stocks, `start > end`, an
    infeasible cap or more than 20,000 portfolios return 422. Typed client
    regenerated.
  - **Web**: new hand-rolled SVG `FrontierChart` (no new dependency) with the random
    cloud, frontier line, capital allocation line and minimum-variance /
    maximum-Sharpe / equal-weight / current markers. `OptimizeBuilder` now calls the
    frontier endpoint and shows a risk slider ("Lowest risk" / "Best return for the
    risk" presets) that updates weights, lots, residual cash, return, volatility and
    Sharpe, plus a "Use this portfolio" button that saves the chosen mix as the
    optimized portfolio for Risk and Rebalance. The random-portfolio default moves
    from 2,000 to 5,000 (input capped at 20,000).
  - **Tests**: `packages/core/tests/test_frontier.py` covers the analytical
    two-asset minimum variance, the cloud/frontier summing to one and respecting
    the cap, the monotone frontier, seed reproducibility, an infeasible cap, the
    count bounds, the tangency beating every random portfolio, the current-portfolio
    projection and the accepted/skipped target accounting; `test_optimize_endpoint.py`
    covers the frontier endpoint, the options defaults, reproducibility and the 422s.
  - **Decisions noted**: the target-return equality is frontier-specific and solved
    directly with `scipy.optimize.minimize` because the `Solver` interface models
    only inequality constraints; the current-portfolio marker is projected onto the
    frontier universe and renormalized (cash excluded); the random cloud is not
    persisted to localStorage (size) while the chosen portfolio is; lot rounding is
    computed server-side (the web client has no lot-size data).

- **V1.1 Step 3 — simple mode and navigation** (`packages/core`, `apps/api`,
  `apps/web`, tests, docs):
  - **Navigation**: the header is now Portfolio · Optimize · Risk · Rebalance ·
    Settings. The standalone Universe page is removed and its job folded into
    Optimize; "Risk & Backtest" is renamed "Risk". P&L joins between Portfolio
    and Optimize in Step 6, so it is intentionally absent for now.
  - **Guided Optimize page** (`apps/web/components/OptimizeBuilder.tsx`): one
    top-to-bottom flow in plain language — (1) Stocks to consider (seeds from the
    portfolio, ticker search, a "Start from VN30" button, no Build button),
    (2) Money ("Use my holdings (including cash)" or "New money"), (3) Goal
    (three plain choices mapped to `min_variance` / `max_sharpe` /
    `equal_weight`), and (4) a single "Find my portfolio" button that builds the
    universe with fixed sensible filters (everything except the single-exchange
    filter, i.e. all boards allowed, minimum history, minimum liquidity, exclude
    suspended/delisted) and runs the optimizer. A plain-English summary sentence
    sits above every result and each metric has a (?) tooltip.
  - **Advanced settings** (off by default): max weight per stock, benchmark, VaR
    confidence, number of random portfolios and seed. Only max weight affects the
    current run; the other four are captured for the frontier (Step 4) and risk
    (Step 5) views.
  - **Guardrails** (`core/optimize/guardrails.py` plus a mirrored
    `apps/web/lib/optimize-guardrails.ts`): the default max weight is
    `max(25%, 1.5 / n)` (raised to `1 / n` when the requested cap cannot fully
    invest, with a message), a warning below 5 stocks (frontier not meaningful)
    and above 20 (sample covariance unreliable), and a hard cap of 30 stocks —
    enforced both in the UI and in `POST /api/v1/optimize` (422 with a clear
    message). Simplest interpretation noted: "HOSE/HNX/UPCoM allowed" is
    implemented by not applying the single-exchange filter, and the date range
    defaults to (and is fixed at) the last three years.
  - **Tests**: `test_optimize.py` and `apps/web/lib/optimize-guardrails.test.ts`
    cover the default cap, the feasibility raise, the size warnings and the hard
    cap; `test_optimize_endpoint.py` covers the 31-symbol 422.

### Removed

- **V1.1 Step 2 — remove complex methods** (`packages/core`, `apps/api`,
  `apps/web`, tests, docs). Deleted rather than hidden, per the V1.1 simplification
  to CFA Level 1/2 methods:
  - **Estimators**: removed the `ledoit_wolf` and `ewma` covariance estimators and
    the `ewma` return estimator (`core/optimize/covariance_estimators/{ledoit_wolf,ewma}.py`,
    `core/optimize/return_estimators/ewma.py`); the optimizer now uses the sample
    mean and sample covariance only (`DEFAULT_COVARIANCE_ESTIMATOR = "sample"`,
    252-day annualization). The estimator dropdowns and the
    `return_estimators` / `covariance_estimators` option lists are gone from the
    API and the Optimize page; dead helpers (`ledoit_wolf_covariance`,
    `ewma_mean`, `ewma_covariance`, `demean_filled`) were deleted from
    `core/optimize/_math.py`.
  - **Objectives / risk**: removed the `risk_parity` objective, the
    `historical_cvar` (CVaR) and `risk_contribution` (Euler) risk metrics, and
    their now-dead helpers (`expected_shortfall`, `risk_contributions`) from
    `core/risk/_math.py`. The `inverse_volatility` objective is kept because it is
    registered and tested.
  - **Constraints**: removed the `max_holdings` and `adv_cap` constraint modules.
    The optimizer's ADV plumbing (`OptimizeContext.adv_by_symbol`,
    `OptimizeAssumptions.adv_sessions`, the `adv_sessions` request field and the
    `adv_by_symbol` engine argument) was removed because the ADV cap was its only
    consumer. The capital-reserve carve-out and its `cash_reserve` constraint stay
    (they belong to the money flow Step 3 revisits).
  - **Monte Carlo**: deleted the `core/montecarlo` package (`block_bootstrap`,
    `multivariate_student_t`, the random-portfolio / resampled / forward modes),
    the `/api/v1/montecarlo/*` routes, the `MonteCarlo` API client, and the
    Simulation page + `SimulationCalculator`. The replacement (a Dirichlet
    random-portfolio cloud plus the exact efficient frontier) lands in Optimize in
    Step 4.
  - **Backtest**: deleted the `core/backtest` package (walk-forward engine,
    `RebalanceSchedule` / `SlippageModel` / `BacktestMetric` registries, lookback
    and slippage parameters), the `/api/v1/backtest/*` routes, the `Backtest`
    API client, `BacktestCalculator`, and the backtest section on the Risk page.
    A simple "historical performance" chart replaces it in Step 5.
  - **Liquidity warning (new)**: the ADV cap is replaced by a Portfolio-page
    liquidity warning in `apps/api/app/api/v1/portfolio.py` — a holding whose
    average daily traded value is below `_LIQUIDITY_WARNING_THRESHOLD`
    (1,000,000,000 VND) is flagged "low liquidity: …". It renders through the
    existing per-holding warning badges in `HoldingsTable`, and is covered by
    `test_evaluate_warns_for_low_liquidity`.
  - **Docs**: `docs/EXTENDING.md` and `docs/ROADMAP.md` drop the removed
    registries and worked example and list the removals as "removed in V1.1, may
    return in V2".
  - **Tests**: deleted `test_montecarlo.py`, `test_backtest.py`,
    `test_montecarlo_endpoint.py` and `test_backtest_endpoint.py`; updated
    `test_optimize.py`, `test_risk.py`, `test_optimize_endpoint.py`,
    `test_risk_endpoint.py` and `test_portfolio_endpoint.py`. The generated typed
    client (`apps/api/openapi.json`, `apps/web/lib/schema.d.ts`) is regenerated.
  - **Out of scope (later steps)**: the Universe page stays (folded in Step 3) and
    the Risk page keeps its existing name until Step 5 rebuilds it.

### Fixed

- **V1.1 Step 1 — one persisted store and known bugs** (`apps/web`, `apps/api`,
  `packages/data`):
  - **One persisted client store** (`apps/web/lib/app-store.ts` +
    `app-store-context.tsx`): a single versioned `vnopt.app` payload now holds the
    active portfolio (holdings + cash), the named-portfolio library, the universe
    selection (symbols, date range, filters, result), the last optimization
    result, the chosen "optimized" weights and user settings. It hydrates once on
    mount behind a loading state (so nothing flashes empty and saved data is never
    overwritten), migrates the legacy `vnopt.portfolio` / `vnopt.portfolios` /
    `vnopt.user-settings` keys, and discards an incompatible payload instead of
    crashing. One `AppStoreProvider` plus small selector hooks replace the four
    old providers, so no page keeps its own copy of shared data.
  - **Universe survives navigation and reload**: `UniverseBuilder` initialises its
    tickers, date range, filters and result from the store and writes the built
    selection back, so leaving and returning keeps everything.
  - **Saved portfolio loads everywhere**: on hydration the working portfolio is
    filled from the active named snapshot when it is empty, so the Portfolio
    table, Optimize capital and Rebalance see its holdings and cash instead of
    0 VND / an empty table. Clearing the portfolio also clears the active id.
  - **Ticker search HTTP 500**: root cause was the CWD-relative default SQLite
    URL. The API runs from `apps/api`, so `sqlite:///./vnopt.db` created an empty,
    unmigrated `apps/api/vnopt.db` while Alembic migrated the repository-root
    file; `/api/v1/symbols` then failed with "no such table: symbols". The default
    is now anchored at the repository root (`packages/data/data/settings.py`), so
    the API, Alembic and the seed share one database.
    `apps/api/tests/test_symbols_endpoint.py` proves the route returns the
    built-in symbol snapshot (HTTP 200) when every provider fails.
  - **Optimize**: the duplicate "Trading days" field now renders once (the return
    estimator omits it; the covariance estimator keeps it).
  - **Grammar**: `Disclaimer` takes an explicit verb, so "This universe is" and
    "This order list is" replace "This universe are".
  - **Risk & Backtest**: the backtest section now has a "Historical backtest"
    heading.
  - **Tests**: `apps/web/lib/app-store.test.ts` covers the save/load round trip,
    the saved-portfolio auto-load, edits surviving a reload, and discarding an
    incompatible schema.

### Added

- **V1 finish — integration, deployment and extensibility proof**
  (`packages/core`, `packages/data`, `apps/api`, `apps/web`, docs):
  - **Extensibility proof**: a new objective,
    `packages/core/core/optimize/objectives/inverse_volatility.py` (39 lines),
    registered with one import in `objectives/__init__.py` and covered by
    `test_optimize.py`. It is the worked example in `docs/EXTENDING.md`.
  - **Named saved portfolios** in `apps/web/lib/portfolio.ts` (a
    `PortfolioLibrary` with `upsert`/`remove`/JSON round-trip, schema version 1),
    exposed through `usePortfolio` and the Portfolio page, with saved-portfolio
    JSON export/import in addition to the active portfolio's JSON/CSV.
  - **Data freshness**: `GET /api/v1/data/freshness` returns the latest stored
    price date, the active (first healthy) provider and the provider health list;
    the header badge now shows `data: kbs · <latest date>` with failover and stale
    warnings. `SqlPriceRepository.overall_latest_date()` and `DataService.data_freshness()`
    back it; `apps/api/tests/test_data_endpoint.py` covers it.
  - **Typed web client generation**: `openapi-typescript` (dev dependency),
    `scripts/client.py generate|check`, `Makefile` targets `client` and
    `client-check`, and `make check` now fails when `apps/api/openapi.json` or
    `apps/web/lib/schema.d.ts` are out of date. `apps/web/lib/api.ts` derives its
    payload types from the generated schema.
  - **Disclaimer** on every results page (`components/Disclaimer.tsx`).
  - **Deployment**: `apps/web/vercel.json`, explicit `maxDuration` on the API
    function, `docs/DEPLOYMENT.md` (verified Vercel Python limits, the measured
    ~183 MB projected bundle, CLI deploy without Git, env-var table, cron) and a
    README with local setup and deploy steps.
  - **Docs**: `docs/EXTENDING.md` rewritten with five worked examples and real
    paths (Objective, Constraint, DataProvider, RiskMetric, ReturnSimulator),
    `docs/ARCHITECTURE.md` gained an architecture diagram, and `docs/ROADMAP.md`
    maps every V2/V3 item to the interface or registry it will use. No V2/V3
    feature was implemented.

- **Monte Carlo simulation** (`packages/core`, `apps/api`, `apps/web`):
  - `core.montecarlo` package with a `ReturnSimulator` interface plus the
    `return_simulators` registry: `block_bootstrap` (circular block bootstrap,
    default) and `multivariate_student_t` (Ledoit-Wolf scale, fat tails). Adding a
    simulator is a new file plus one registration; every draw uses an explicit seed
    and vectorized numpy.
  - Three pure engine modes: `run_random_portfolios` samples long-only, fully
    invested Dirichlet weights and keeps them inside the active constraints,
    highlighting the optimizer and the current portfolio; `run_resampled_optimization`
    runs the existing optimizer on bootstrapped histories and returns mean weights plus
    per-symbol 5/25/50/75/95 percentile bands; `run_forward_simulation` compounds
    chunked portfolio paths and returns percentile paths, loss probability, horizon
    VaR/CVaR and the maximum-drawdown distribution.
  - A hard simulation cap and wall-clock budget are settings
    (`VNOPT_MONTECARLO_MAX_SIMULATIONS`, `VNOPT_MONTECARLO_TIME_BUDGET`) enforced by
    every engine call; `MonteCarloBudgetExceeded` maps to 422.
  - `GET /api/v1/montecarlo/options` publishes the simulators and defaults;
    `POST /api/v1/montecarlo/{mode}` runs one of the three modes and returns a typed
    result with an assumptions block. Unknown modes/ids, infeasible constraints, empty
    universes and over-budget runs return 422.
  - Web Simulation page: an efficient-frontier scatter with the optimizer and current
    portfolio highlighted, a per-stock weight-range chart, a fan chart, summary loss
    cards and controls for mode, simulations, seed, horizon, confidence and simulator.
  - Tests: the same seed reproduces every mode, resampled weights sum to one and
    respect the caps, forward statistics are sane on synthetic data (positive drift
    never loses, negative drift always does), the multivariate Student-t matches the
    fitted moments, the hard cap is enforced, one-file-one-registration, plus API tests
    over a seeded database.

- **Walk-forward backtester** (`packages/core`, `apps/api`, `apps/web`):
  - `core.backtest` package with interface-plus-registry concepts: `RebalanceSchedule`
    (`monthly`, `quarterly`), `SlippageModel` (`flat_bps`) and `BacktestMetric`
    (`cagr`, `sharpe`, `max_drawdown`, `turnover`). Adding one is a new file plus one
    registration; the `Objective`, `Constraint` and `CostModel` registries are reused.
  - The pure `run_backtest` engine loops over rebalance dates and, at each date,
    estimates inputs from returns whose date is strictly earlier (the last `lookback`
    observations), runs the configured optimizer, trades through the `vn` cost model
    (the user's fee rate plus the market sell tax) with whole-lot rounding and
    side-aware slippage, and holds to the next date. Missing prices are carried
    forward and flagged. It returns the equity curve, weights history, trade log,
    metrics and benchmarks (VN-Index, VN30, a cost-free equal-weight portfolio, and
    — when current weights are supplied — "my weights, held fixed"). A configurable
    time and rebalance budget fails with a clear `BacktestBudgetExceeded` instead of
    timing out.
  - `GET /api/v1/backtest/options` publishes every concept and the defaults;
    `POST /api/v1/backtest` builds a look-ahead-free daily traded-value matrix for the
    ADV, loads the benchmarks and returns the curves plus an assumptions block (fee
    rate, risk-free rate, sell tax, slippage, lookback, schedule, cost model and a
    raw-price note). Unknown ids, invalid input and an over-budget run return 422.
  - Web Risk & Backtest page: a parameters form, the equity curve versus the
    benchmarks, a drawdown chart, a metrics table, the trade log and the weights
    history. Options are rendered from the API and the portfolio's current weights
    are offered as a benchmark when a portfolio exists.
  - Tests: a zero-cost equal-weight buy-and-hold matches a manual calculation, higher
    costs always reduce the result, a spike after a rebalance date does not change
    any earlier decision (no look-ahead), a suspended price is carried and flagged, the
    rebalance budget is enforced, one-file-one-registration, plus API tests over a
    seeded database.

- **Rebalance engine** (`packages/core`, `apps/api`, `apps/web`):
  - `core.rebalance` package with interface-plus-registry concepts: `CostModel`
    (`vn`: brokerage fee on both sides from `UserSettings` plus the 0.1% sell tax
    from `market_rules`) and `RebalancePolicy` (`full`, and `threshold_band` with a
    drift band and an optional turnover cap). Adding one is a new file plus one
    registration.
  - The pure `rebalance` engine plans sells before buys, never sells more than
    held, rounds both sides down to whole lots, skips orders below a minimum
    notional and funds buys from starting cash plus sell proceeds so residual cash
    is never negative. It returns current-versus-target positions, a placeable
    order list (lots, shares, reference price, value, fee, tax), the total cost,
    the gross turnover and the residual cash.
  - `GET /api/v1/rebalance/options` publishes the cost-model and policy catalogues
    and the defaults; `POST /api/v1/rebalance` values the holdings at the latest
    close and returns the order list plus an `assumptions` block (brokerage fee,
    sell tax, data source and latest date). Unknown ids and invalid inputs return
    422; a missing price is a warning.
  - Web Rebalance page: holdings and cash pre-filled from the shared portfolio and
    still editable, holdings and target-weight CSV import, order-list CSV export, a
    policy selector with schema-driven parameters, a current-versus-target chart,
    an orders table and a cost summary. It states that prices are the latest close
    and that T+2 settlement is not modeled in V1.
  - Tests: cost math, never oversell, lot rounding, the minimum notional, the
    threshold band and turnover cap, buy funding (residual cash >= 0), the
    registries and one-file-one-registration, plus API tests over a seeded
    database.

- **Risk analytics** (`packages/core`, `apps/api`, `apps/web`):
  - `core.risk` is now a package with an interface-plus-registry design: a
    `RiskMetric` protocol and a `risk_metrics` registry. Adding a metric is one
    new file plus one registration.
  - Built-in metrics: `annualized_volatility`, `max_drawdown` (with the drawdown
    series), `beta` against a benchmark, `historical_var` and `historical_cvar`
    (confidence configurable, default 95%), `risk_contribution` (Euler
    decomposition) and `correlation_matrix`. `sharpe_ratio` is unchanged.
  - The pure `compute_risk` engine takes the aligned returns matrix, the weights
    and the benchmark returns; missing weights are zero and extra weights are
    ignored. Metrics use pairwise-complete observations for gaps.
  - `GET /api/v1/risk/options` publishes the metric catalogue, the four
    benchmarks (VNINDEX, VN30, HNXINDEX, UPCOMINDEX) and the defaults, and
    `POST /api/v1/risk` returns every selected metric plus the catalogue. Errors
    (unknown metric or benchmark, no price data, degenerate beta) return 422.
  - Web Risk & Backtest page: metric cards, a risk-contribution bar chart, a
    correlation heatmap and a drawdown chart. A shared `optimize-context` stores
    the latest optimizer result so the page compares the current and the
    optimized portfolio side by side, with a toggle for the detailed charts. The
    benchmark list, the metric list and the defaults all come from the API.
  - Tests: hand-computed examples for volatility, drawdown, beta, VaR/CVaR,
    Euler contributions and correlation, plus registry and
    one-file-one-registration tests and API tests over a seeded database and
    benchmark.

- **Optimization engine** (`packages/core`, `apps/api`, `apps/web`):
  - `core.optimize` package with interface-plus-registry concepts: `ReturnEstimator`
    (`historical_mean`, `ewma`), `CovarianceEstimator` (`sample`, `ledoit_wolf`
    implemented directly in numpy, `ewma`), `Objective` (`min_variance`,
    `max_sharpe`, `risk_parity`, `equal_weight`), `Constraint` (`max_weight`,
    `max_holdings`, `cash_reserve`, `adv_cap`), a swappable `Solver` and a
    `RiskFreeRateProvider` (user settings today; auto-fetch extension point for
    V2). Adding an objective or constraint is one new file plus one registration.
  - The engine always enforces long-only and fully invested, takes the risk-free
    rate from `UserSettings` (never a constant), and supports cash reserve as a
    capital carve-out. `lot_rounding` converts weights to integer lots using the
    `market_rules` lot sizes and reports residual cash.
  - `GET /api/v1/optimize/options` publishes every concept plus the conservative
    defaults; `POST /api/v1/optimize` returns weights, lots, residual cash,
    expected return, volatility, Sharpe, solver status, binding constraints and an
    assumptions block (data source and raw/unadjusted prices). Infeasible
    constraints return 422 with a clear message.
  - Web Optimize page renders every option from the API, selects capital from the
    portfolio value or a typed amount, and shows a weights table, a weights chart,
    lots, residual cash, statistics and an in-sample warning.
  - Tests: analytical two-asset minimum variance, constraints respected
    (`max_weight`, `max_holdings`, `adv_cap`), infeasible constraints → clear
    error, deterministic output, Ledoit-Wolf/EWMA/lot-rounding units and a
    one-file-one-registration objective test.
  - Added `scipy>=1.11` (used for `scipy.optimize`; sanctioned by the project
    rules).

- **Shared portfolio** (`packages/core`, `packages/data`, `apps/api`, `apps/web`):
  - `Holding` / `Portfolio` Pydantic models in `core.portfolio` validate unique
    symbols, whole-number shares (0 == wishlist) and non-negative VND amounts, and
    `portfolio_value_and_weights` returns market value per holding, the total
    including cash, and holding/cash weights (a missing price contributes zero).
    Average cost is stored only; P/L stays deferred to V2.
  - `POST /api/v1/portfolio/evaluate` values the portfolio at the latest prices,
    triggering the existing on-demand backfill for holdings without stored prices
    (symbols that cannot be fetched are reported as "queued for backfill"), and
    returns values, weights, data freshness with the serving provider (KBS first)
    and warnings for missing price, illiquid, suspended, stale and queued tickers.
  - Web Portfolio page (first in the navigation): ticker autocomplete, one row per
    holding with a whole-share input and optional average cost, a cash input,
    add/remove, CSV import/export (`symbol,shares,avg_cost`), JSON import/export and
    a live price/value/weight table with totals. Holdings and cash persist in
    `localStorage` with a schema version and are shared through
    `lib/portfolio-context.tsx`.
  - The other pages consume the shared portfolio: Universe starts with the
    portfolio's tickers (more can be added), Optimize selects capital from the
    portfolio value or a typed amount, Risk & Backtest analyse the current portfolio
    as-is, and Rebalance pre-fills its notional from the portfolio.
  - Tests: core validation and weight math (including cash and wishlist holdings),
    API evaluate (prices, weights, warnings, queued backfill, validation) and a CSV
    round-trip test run with Node's built-in test runner (`make test-web`).

- **Universe selection** (`packages/core`, `packages/data`, `apps/api`, `apps/web`):
  - `UniverseFilter` interface plus a `universe_filters` registry in `core.universe`,
    with one-file implementations: `exchange`, `min_adv` (minimum average daily
    traded value over the last N sessions), `exclude_suspended` (suspended/delisted)
    and `min_history` (minimum sessions). Adding a filter is one new file plus one
    registration; `build_universe` never learns about a specific filter.
  - `build_universe(symbols, filters, start, end)` returns numpy-aligned price and
    returns matrices, per-symbol average daily traded value, quality flags
    (suspended, delisted, missing data, illiquid) and every dropped ticker with its
    reason. A symbol with no data in range is always dropped with a reason.
  - Curated index presets in `data.presets` (VN30 today); adding VN100 is a
    data-only change because the KBS provider already resolves it.
    `DataService.get_index_constituents` and `DataService.get_symbol` read the cache
    and populate constituents on first use.
  - API `GET /api/v1/universe/options` (filter catalogue + presets from their
    registries), `POST /api/v1/universe/build`,
    `GET /api/v1/universe/presets/{index_code}` and `POST /api/v1/data/backfill`
    (the Universe page's Refresh data action).
  - Web Universe page: ticker search/autocomplete, preset buttons, filter controls
    rendered from the API parameter schemas, a three-year default date range, results
    with liquidity and quality flags, dropped tickers with reasons, and a shared
    client store (`lib/universe-context.tsx`) for the other pages.
  - `packages/core` now depends on `numpy`.

- **Data layer (`packages/data`)**:
  - `DataProvider` protocol plus `KbsProvider`, `VciProvider`, `DnseProvider`,
    `TcbsProvider` and `SsiIboardProvider`, each registered in a provider
    registry and implemented against anonymous public endpoints (all
    unofficial, all raw/unadjusted). KBS is the default primary provider: it
    also serves the symbol listing (`/stock/search/data`) and index groups
    (`/index/{group}/stocks`, VNINDEX→HOSE, VN30→30, HNXINDEX→HNX,
    UPCOMINDEX→UPCOM) anonymously, so `list_symbols` and
    `get_index_constituents` now work there too. VCI's OHLC chart endpoint is
    fetched over POST, so the shared `HttpClient`/`ProviderBase` gained POST
    support alongside GET (the failover chain itself is unchanged). The default
    `PROVIDER_ORDER` is now `kbs,vci,dnse,tcbs,ssi_iboard`.
  - Built-in reference seed (`data/seed.py`): a small stock snapshot plus the
    recorded VN30 membership, written by `SyncService.sync_reference_data()`
    only when every live provider fails `list_symbols` /
    `get_index_constituents` and the table is still empty, so ticker search and
    the VN30 preset work offline; seeded rows are marked `source: "seed"` and
    never overwrite existing rows. New recorded fixtures cover KBS's symbol and
    group responses.
  - `FallbackProvider` failover chain with per-provider retry/backoff, response
    validation, stale-data detection, a circuit breaker and no-silent-splicing
    overlap checks; every failover is logged and every row stores its `source`.
  - SQLAlchemy 2 models (`symbols`, `prices_daily`, `indices_daily`,
    `index_constituents`, `sync_log`, reserved empty `corporate_actions`) behind
    repository interfaces, with an Alembic initial migration.
  - Incremental, idempotent sync (`python -m data.jobs.sync`, `--backfill` /
    `--benchmarks`) shared with the protected `POST/GET /api/v1/data/refresh`
    endpoint; Vercel Cron (`sin1`, weekdays 08:30 UTC after the VN close) and a
    documented external-cron backup.
  - Quality-check registry (`missing_trading_days`, `stale_price_runs`,
    `zero_volume`, `price_limit_move`) returning a `QualityReport`.
  - API routes `GET /api/v1/symbols`, `GET /api/v1/prices/{symbol}`,
    `GET /api/v1/data/quality/{symbol}`, `GET /api/v1/data/providers/status`,
    `GET /api/v1/data/probe` and `POST /api/v1/data/refresh`; on-demand backfill
    and a "queued for next sync" status when providers are unreachable.
  - `scripts/probe_providers.py` and `scripts/check_adjustment.py`, plus
    `docs/DATA.md` and ADR 0002.
  - Web data-freshness badge showing the current provider and failover warnings.
  - Data tests use recorded fixtures only (failover chain 1→2→3, empty/bad-schema
    failover, circuit-breaker cooldown, price-mismatch detection, cached-stale
    fallback, end-to-end refresh + read via the API).

- Monorepo skeleton with `apps/web` (Next.js + TypeScript + Tailwind),
  `apps/api` (FastAPI, Vercel-ready Python function), and the installable
  `packages/core` / `packages/data` Python packages.
- Generic `Registry[T]` in `packages/core` with a `register` decorator and
  `get`, `list` and `describe` methods, plus unit tests.
- `Settings` (`pydantic-settings`), `UserSettings` and `DEFAULT_MARKET_RULES`
  (lot size 100, sell tax 0.1%, daily price limits HOSE 7% / HNX 10% / UPCoM
  15%, illustrative trading holidays).
- `GET /api/v1/health` endpoint.
- Web pages Universe, Optimize, Risk & Backtest and Rebalance, with a shared
  layout, navigation and a global "decision support, not financial advice"
  footer. The home page displays the API health.
- `Makefile` and `scripts/dev.py` for install, dev, test, lint, typecheck and
  the combined `check` gate.
- Documentation: architecture, extension stub, roadmap, changelog and the first
  ADR on the registry pattern.
- User-controlled brokerage fee and risk-free rate:
  - `UserSettings` now validates a fee of 0–0.01 per side and a risk-free rate of
    0–0.20 per year with clear error messages; both defaults are documented as
    placeholders.
  - Core `sharpe_ratio` (`core.risk`) and `commission` / `round_trip_commission`
    (`core.costs`) take the user's values as explicit parameters — no module
    reads them from global configuration or market rules.
  - `GET /api/v1/settings` publishes the defaults and bounds, and
    `POST /api/v1/risk/sharpe` / `POST /api/v1/rebalance/cost` accept an optional
    `settings` object (defaults apply when missing) and echo the values used in
    an `assumptions` block.
  - Web Settings page (percent inputs, help text, Reset to defaults) stores the
    values in `localStorage` with a schema version, exposes them through a shared
    client store, attaches them to every compute request, and shows an
    active-settings badge on the Optimize, Risk and Rebalance pages.

### Fixed

- **Vercel API deployment** (`vercel.json`, `asgi.py`, docs): the root
  `vercel.json` keyed `functions` by `apps/api/api/index.py`, which Vercel never
  treats as a function — the Python runtime only discovers file-based functions
  in a root `api/` directory, so the build failed with “The pattern
  `apps/api/api/index.py` defined in `functions` doesn't match any Serverless
  Functions inside the `api` directory”. The API project now uses the
  zero-configuration FastAPI preset: the new root `asgi.py` (a supported
  entrypoint) re-exports the app from `apps/api/app/main.py`; `vercel.json` sets
  `"framework": "fastapi"` and keys `functions` by the resolved entrypoint
  (`asgi.py`), and the catch-all rewrite is gone because the preset serves every
  path with the original request URL that FastAPI routes on. The dead
  `apps/api/api/index.py` entrypoint and its directory are removed.

- **Vercel dependency installation** (`pyproject.toml`, `asgi.py`, docs): with
  the entrypoint fixed the function loaded but every request failed with
  `ModuleNotFoundError: No module named 'fastapi'`. Vercel discovers the Python
  manifest from the entrypoint directory upward and stops at the first
  `pyproject.toml`, which was tooling-only and had no `[project].dependencies`,
  so the install step had a manifest and installed nothing. The root
  `pyproject.toml` is now the single deployment manifest (fastapi, pydantic,
  pydantic-settings, sqlalchemy, alembic, httpx, numpy, scipy,
  psycopg[binary]), `asgi.py` puts `apps/api`, `packages/core` and
  `packages/data` on `sys.path` so the workspace packages need no pip install,
  and the redundant `requirements.txt` files are removed.

- **Web dependencies** (`apps/web/package.json`, `apps/web/package-lock.json`):
  Vercel refused the web deploy with “Vulnerable version of Next.js detected”.
  `next` and `eslint-config-next` move from `15.1.6` to the current security
  release `15.5.29` (same major, so no application changes), and `postcss` is
  pinned to `8.5.33` — both as the Tailwind dev dependency and for Next's nested
  copy through an `overrides` entry. `npm audit` goes from 1 critical + 2 high
  to 0 vulnerabilities; lint, typecheck, the web unit tests and `next build` all
  pass. React stays at `19.0.0`, which satisfies Next 15.5's peer range.

