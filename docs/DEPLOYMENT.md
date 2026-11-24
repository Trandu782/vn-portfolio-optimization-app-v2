# Deployment

The app deploys as two Vercel projects from this folder with the **Vercel CLI**
(no Git remote required). Both projects run in `sin1` (Singapore), the closest
region to Vietnam.

- **API** — Root Directory **the repository root**, FastAPI framework preset.
  Vercel only auto-detects FastAPI at a supported root entrypoint (`app.py`,
  `index.py`, `server.py`, `main.py`, `wsgi.py` or `asgi.py`, or the same names
  inside `src/` or `app/`), so the repository root holds `asgi.py`: it puts
  `apps/api`, `packages/core` and `packages/data` on `sys.path` and re-exports
  the real `app` from `apps/api/app/main.py`. Deploying from the root is
  required because the API imports those sibling packages.
- **Web** — Root Directory `apps/web`, Next.js. Its `next.config.mjs` rewrite
  proxies `/api/*` to `API_URL`. Keep `next` on the newest `15.5.x` security
  release (currently `15.5.29`): Vercel refuses to deploy a Next.js version with
  a known vulnerability, and `postcss` is pinned to `8.5.33` via `overrides` so
  Next's nested copy is patched too — `npm audit` in `apps/web` must stay clean.

The FastAPI preset serves the whole application from that one function with the
original request paths, so `vercel.json` has no `rewrites`; `functions` is keyed
by the resolved entrypoint (`asgi.py`) and only customises its bundle and
`maxDuration`. Do not move the entrypoint under `apps/api`: file-based Python
functions are only discovered in a root `api/` directory, and a catch-all
rewrite to one function would rewrite the path FastAPI routes on.

### Python dependencies

The runtime dependencies live in the root `pyproject.toml`
(`[project].dependencies`). There is no `requirements.txt` on purpose: Vercel
resolves the manifest from the entrypoint directory upward and stops at the
first `pyproject.toml` it finds, so a tooling-only `pyproject.toml` (or an
`-r`/local-path `requirements.txt`) can leave the deployed function without
packages and the import fails with `ModuleNotFoundError`. Keep the whole
runtime set in that one list — `apps/api`, `packages/core` and `packages/data`
all import from it — and let `asgi.py` provide the workspace source
directories, which are not installed as distributions.

### Postgres pooler (pgBouncer)

Production points `DATABASE_URL` at Supabase's transaction-mode pooler (port
6543). That pooler cannot keep server-side prepared statements between
transactions, so `data/db/base.py` sets psycopg3's `prepare_threshold=None` for
`postgresql+psycopg` URLs through the `connect_args_for` helper. Without it,
repeated queries fail intermittently with
`psycopg.errors.DuplicatePreparedStatement` and the API returns 500 on
data-heavy routes (frontier, risk, P&L, rebalance, probe). Keep that setting if
the connection string ever changes to another pooler.

## Verified Vercel limits (August 2026 docs)

Sources: `vercel.com/docs/functions/limitations` and
`vercel.com/docs/functions/runtimes/python`.

| Limit | Value |
| --- | --- |
| Function bundle, uncompressed | **250 MB**; **500 MB for the Python runtime**; up to 5 GB with Large Functions (beta) |
| Maximum duration | Hobby **300 s** (default and max); Pro/Enterprise 300 s default, **800 s** max, 1800 s extended (beta) |
| Maximum memory | Hobby **2 GB**; Pro/Enterprise **4 GB** |
| Request body | 4.5 MB (`FUNCTION_PAYLOAD_TOO_LARGE` beyond) |
| Response body | 4.5 MB unless streamed |
| File descriptors | 1,024 shared across concurrent executions |
| Python dependencies | Installed from `requirements.txt` / `pyproject.toml` at build time; no automatic tree-shaking |

The API depends on `scipy`, so it relies on the **500 MB Python-specific**
bundle limit (scipy alone is ~110 MB uncompressed). The root `vercel.json`
excludes `apps/web`, `node_modules`, tests and caches from the function bundle.

## Measured bundle size

Measured from the project's virtualenv (Windows, uncompressed) as the sum of the
runtime dependency directories declared in the root `pyproject.toml` plus the app
source:

| Component | Size |
| --- | --- |
| `scipy` | 109.7 MB |
| `numpy` | 31.4 MB |
| `sqlalchemy` | 19.5 MB |
| `pydantic` + `pydantic_core` + settings | 10.5 MB |
| `alembic` + `mako` + `markupsafe` | 2.9 MB |
| `fastapi` + `starlette` | 2.4 MB |
| `httpx` + `httpcore` + `h11` + `anyio` + `certifi` + `idna` | 4.2 MB |
| other (click, colorama, annotated_types, greenlet-ish) | ~1.2 MB |
| **Runtime dependencies** | **≈ 182 MB** |
| App + workspace source (`apps/api`, `packages/core`, `packages/data`) | ≈ 0.5 MB |
| **Projected function bundle** | **≈ 183 MB** uncompressed (plus optional `.pyc` bytecode) |

That is comfortably inside the 500 MB Python limit and just under the 250 MB
general limit that applies to other runtimes. The local measurement is a
projection: run `vercel build` and check the deploy log for the exact figure.
Keep the bundle lean by not adding pandas, scikit-learn, cvxpy or torch.

## What Vercel uploads (`.vercelignore`)

Two projects share this repository, and each has its own ignore file because the
patterns are relative to the deployed directory:

- **API project** (Root Directory = repository root) — the root `.vercelignore`.
  It drops everything that is not runtime code: the SQLite database and its
  sidecars (`*.db`, `*.db-wal`, `*.db-shm`, `*.db-journal`, `*.sqlite*`, `*.dump`),
  `.venv/`, `apps/web/`, `docs/`, `scripts/`, `data/reference/`, `tests/` (and
  `**/tests/`) and the ruff/mypy/pytest caches. It also keeps the local
  secrets and scratch notes off the upload (`Deployment prerequisite.txt`,
  `V2 update.txt`, `.env*`): those are gitignored, but a CLI upload is not git.
- **Web project** (Root Directory = `apps/web`) — `apps/web/.vercelignore`. A
  project-level file takes precedence over the repository-root one, which Vercel
  only falls back to when the project has none. Having it guarantees the root
  file's `apps/web/` entry (there for the API project) cannot blank out the
  Next.js upload. `node_modules` would be skipped by Vercel's defaults anyway; the
  file also keeps `.next/`, `*.tsbuildinfo` and `.env.local` out.

`vercel.json`'s `functions.asgi.excludeFiles` is the second line of defence: it
strips tests, fixtures and caches from the Python function bundle even if a file
reaches the build context. `apps/api/openapi.json` (195 KB, the generated typed
client schema) is deliberately left in — it is negligible next to scipy.

Local sizes measured for the excluded artifacts:

| Excluded path | Size on this machine |
| --- | --- |
| `apps/web/node_modules` | 415.9 MB |
| `apps/web/.next` | 368.0 MB |
| `.venv` | 406.2 MB |
| `vnopt.db` | 18.2 MB |

What remains for the API is the app plus workspace source (≈ 0.8 MB) on top of the
≈ 182 MB dependency set, i.e. the ≈ 183 MB bundle measured above.

## Deploy with the Vercel CLI (no Git)

```sh
npm i -g vercel
vercel login
```

### 1. API project (from the repository root)

```sh
# stay in the repository root: this includes packages/core and packages/data
vercel link                      # create a new project or link an existing one
vercel env add DATABASE_URL production     # Postgres URL, e.g. from Neon/Supabase
vercel env add PROVIDER_ORDER production   # kbs,vci,dnse,tcbs,ssi_iboard
vercel env add REFRESH_TOKEN production    # long random secret
vercel env add CRON_SECRET production      # same value as REFRESH_TOKEN
vercel --prod
```

The root `pyproject.toml` declares both the runtime dependencies
(`[project].dependencies`, installed by Vercel) and the developer tooling config
(ruff/mypy/pytest). Select Python 3.12 in the project settings (matching
`.python-version`).

`DATABASE_URL` must point at a persistent database. A local SQLite file does not
survive a serverless deploy; use Postgres and run the migration once from your
machine against it:

```sh
DATABASE_URL=postgresql+psycopg://... python -m alembic -c packages/data/alembic.ini upgrade head
```

The cron schedule lives in the root `vercel.json`
(`30 8 * * 1-5` = 15:30 Asia/Ho_Chi_Minh, after the 15:00 close, Monday–Friday).
Vercel sends `Authorization: Bearer ${CRON_SECRET}`; the endpoint is idempotent
and returns `cursor`/`remaining` so an external scheduler can loop it when a
single batch is not enough.

### 2. Web project

```sh
cd apps/web
vercel link
vercel env add API_URL production   # the API project's production URL
vercel --prod
```

`API_URL` is read by `next.config.mjs` at build time; redeploy the web project
after changing it.

## Preview deployment checklist

A preview deployment reads only **Preview**-scoped environment variables. The four
API secrets were production-only for a while, which is why a preview showed an
empty database and 500s on every data route. Add every variable below to
**Preview** as well as Production (`vercel env add NAME preview`, or both scopes in
the dashboard UI).

### API project (Root Directory: repository root)

| Variable | Value | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres.<ref>:<password>@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres` | Supabase **transaction pooler**, port **6543**. `data/db/base.py` sets psycopg3's `prepare_threshold=None` for pooled URLs; without it repeated queries die with `DuplicatePreparedStatement` (500s on frontier/risk/P&L/rebalance). Alembic is the exception: migrate over the **session pooler** (5432). |
| `PROVIDER_ORDER` | `kbs,vci,dnse,tcbs,ssi_iboard` | V1 failover chain, KBS first. |
| `VNOPT_V2_OHLCV_ORDER` | `ssi_statistics,vci,kbs` | V2 prices; the adjusted closes feed Optimize/Frontier. |
| `VNOPT_V2_CONSTITUENTS_ORDER` | `kbs` | Index membership. |
| `VNOPT_V2_SECTOR_MAP_ORDER` | `ssi_statistics` | ICB level-2 sector map. |
| `VNOPT_V2_RATIOS_ORDER` | `ssi_statistics` | Financial ratios (Fundamentals). |
| `VNOPT_V2_COMPANY_PROFILE_ORDER` | `ssi_statistics` | Company profiles. |
| `VNOPT_V2_CORPORATE_ACTIONS_ORDER` | `ssi_statistics` | Corporate actions. |
| `VNOPT_V2_SYMBOL_MASTER_ORDER` | `ssi_statistics,kbs` | Symbol master. |
| `VNOPT_V2_OHLCV_RATE_LIMIT_PER_MINUTE` | `20` | Per-data-type request budget of the V2 failover runner. |
| `VNOPT_V2_CONSTITUENTS_RATE_LIMIT_PER_MINUTE` | `20` | Same, constituents. |
| `VNOPT_V2_SECTOR_MAP_RATE_LIMIT_PER_MINUTE` | `20` | Same, sector map. |
| `VNOPT_V2_RATIOS_RATE_LIMIT_PER_MINUTE` | `10` | Same, ratios. |
| `VNOPT_V2_COMPANY_PROFILE_RATE_LIMIT_PER_MINUTE` | `10` | Same, company profile. |
| `VNOPT_V2_CORPORATE_ACTIONS_RATE_LIMIT_PER_MINUTE` | `10` | Same, corporate actions. |
| `VNOPT_V2_SYMBOL_MASTER_RATE_LIMIT_PER_MINUTE` | `10` | Same, symbol master. |
| `REFRESH_TOKEN` | long random secret | Protects `/data/refresh` and `/data/probe`. |
| `VNOPT_REFRESH_TOKEN` | the same value | The `VNOPT_`-prefixed spelling named by `require_token`'s 503 detail; both are accepted (`AliasChoices`), the bare name wins when both are set. |
| `CRON_SECRET` | the same value | Never read by the app: Vercel Cron sends `Authorization: Bearer $CRON_SECRET` and `require_token` compares it with `refresh_token`, so all three must match. |

The seven V2 chains (and their seven rate-limit budgets) default to exactly these
values on the server (`data/v2/config.py::VERIFIED_PROVIDERS`); set them explicitly
anyway so a preview cannot silently inherit a stale dashboard value.
`VNOPT_V2_BACKFILL_START_DATE`, `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND` and the
`VNOPT_V2_PRECOMPUTE_*` knobs belong to the GitHub Actions precompute job, not to
Vercel.

Optional API variables (all have in-code defaults): `VNOPT_ENVIRONMENT=production`,
`VNOPT_SYNC_BATCH_SIZE`, `VNOPT_SYNC_TIME_BUDGET_SECONDS`,
`VNOPT_ON_DEMAND_HISTORY_DAYS`, `VNOPT_FRONTIER_MAX_PORTFOLIOS`,
`VNOPT_FRONTIER_TIME_BUDGET`, `VNOPT_MAX_OPTIMIZE_STOCKS`.

Vercel Cron runs against production only; a preview never triggers
`/api/v1/data/refresh` by itself.

### Web project (Root Directory: `apps/web`)

| Variable | Value | Notes |
| --- | --- | --- |
| `API_URL` | the API deployment's base URL, no trailing slash | `next.config.mjs` reads it **at build time** to rewrite `/api/*`, so changing it requires a redeploy. For a preview, point it at the preview API URL (or at production if the preview UI should exercise the production backend). |

### Preview smoke test

A protected preview needs the automation bypass header on every request; the script
reads it from `--bypass` or `VERCEL_AUTOMATION_BYPASS_SECRET` (`vercel curl` injects
the same header automatically). Neither the refresh token nor the bypass secret is
ever printed.

```sh
VNOPT_REFRESH_TOKEN=... VERCEL_AUTOMATION_BYPASS_SECRET=... \
  python scripts/smoke_test.py \
    --api-url https://<api-preview-host> \
    --web-url https://<web-preview-host> \
    --start 2023-11-24
```

`--end` defaults to today. Expected results — every line below was reproduced
locally against the migrated database (2026-11-23 session):

| Check | Expect |
| --- | --- |
| `GET /api/v1/data/freshness` | 200; `latest_date` = the newest stored session, `primary: "ssi_statistics"` (V2 owns the freshest bar), `stale: false` |
| `POST /api/v1/portfolio/evaluate` with `FPT, HPG, VHM, LPB, PVD, DCM` | 200; every holding has `latest_price` and `latest_date` = the global latest session, `source: "ssi_statistics"`, `warnings: []` — no `stale (…)` and no `suspended` note |
| `POST /api/v1/optimize/frontier` with the same six | 200; `tangency` is one of the plotted `frontier` points (identical `volatility` and `expected_return`), so the Max-Sharpe marker sits on the line; the returns come from the V2 adjusted closes (`get_prices_preferring_v2_adjusted`) |
| `GET /v2/coverage`, `/v2/sectors`, `/v2/analytics?benchmark=VNINDEX&timeframe=1Y`, `/v2/fundamentals/FPT` | 200 with `data_as_of`; 11-420 ms warm (budget 2 s), zero 500s |

`assumptions.prices_adjusted` still echoes `false` and `data_sources` is read from
the V1 store even though the frontier consumes V2 adjusted closes; the API tests pin
that behaviour, so verify the marker geometry rather than the flag.

## Post-deploy verification

```sh
# Health
curl https://<api>/api/v1/health

# The hosted probe must list kbs (KBS) as a working provider
curl -H "Authorization: Bearer $REFRESH_TOKEN" \
  "https://<api>/api/v1/data/probe?tickers=VNM,FPT,ACB&index_code=VNINDEX&years=5"

# Freshness badge data (latest stored price date + active provider)
curl https://<api>/api/v1/data/freshness

# Trigger the nightly sync by hand (same path the cron calls)
curl -H "Authorization: Bearer $REFRESH_TOKEN" https://<api>/api/v1/data/refresh
```

Then open the deployed web app and complete the vertical slice: Portfolio (live
spot prices for the holdings), Optimize (efficient frontier with the Max-Sharpe
marker), Risk, Sector Analysis, Fundamentals and Rebalance. Every page shows the
inline disclaimer; the header badge shows the latest price date and the active
provider (`ssi_statistics` once the V2 precompute is current). The
`scripts/smoke_test.py` run in the Preview checklist above automates this.

## Environment variables

| Variable | Scope | Required | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | API | yes | SQLAlchemy URL; Postgres in production (transaction pooler, port 6543). |
| `PROVIDER_ORDER` | API | recommended | `kbs,vci,dnse,tcbs,ssi_iboard` (KBS first). |
| `REFRESH_TOKEN` | API | yes | Protects `/data/refresh` and `/data/probe`. |
| `VNOPT_REFRESH_TOKEN` | API | yes | Same value as `REFRESH_TOKEN`; both spellings are accepted. |
| `CRON_SECRET` | API | yes | Vercel Cron auth; equal to `REFRESH_TOKEN`. |
| `VNOPT_V2_*_ORDER` | API | recommended | Seven V2 failover chains; defaults in `data/v2/config.py`. |
| `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` | API | no | Per-data-type budget for the V2 runner (defaults 10-20/min). |
| `API_URL` | Web | yes | Base URL for the `/api/*` rewrite (build time). |
| `VNOPT_ENVIRONMENT` | API | no | `production` on Vercel. |
| `VNOPT_SYNC_BATCH_SIZE` | API | no | Symbols per sync batch (default 50). |
| `VNOPT_SYNC_TIME_BUDGET_SECONDS` | API | no | Wall-clock budget per batch (default 45). |
| `VNOPT_ON_DEMAND_HISTORY_DAYS` | API | no | History depth for first fetch (default 365). |
| `VNOPT_FRONTIER_MAX_PORTFOLIOS` | API | no | Hard cap on the random-portfolio cloud (default 20000). |
| `VNOPT_FRONTIER_TIME_BUDGET` | API | no | Wall-clock budget for a frontier run (default 30s). |

Every API variable must be present in **both** the Production and Preview scopes;
see the Preview deployment checklist above for the exact values (including the V2
chains and their rate-limit budgets).

No credential is needed for any data source: KBS, VCI, DNSE, TCBS and SSI
iBoard are anonymous public endpoints. If one starts requiring a login the
failover chain logs it and moves to the next provider.

## V2 first deployment runbook (Supabase + GitHub Actions + Vercel)

V2 reads precomputed `v2_*` tables that a GitHub Actions runner fills. The
scheduled job needs a persistent Postgres (a runner's local SQLite is discarded
after the job), so use the same Supabase database as the API.

1. **Provision a persistent Postgres** (e.g. Supabase) and note its
   transaction-pooler URL (port `6543`) and session-pooler URL (port `5432`).
2. **Migrate** — run Alembic `0001`…`0005` against the database. From a shell
   with `DATABASE_URL` set to the **session** URL (DML/DDL over a transaction
   pooler is unreliable):
   ```sh
   cd packages/data && python -m alembic upgrade head
   ```
   On Postgres, first widen Alembic's bookkeeping column: revision
   `0004_v2_adjustment_flag_anomalies` (33 chars) exceeds the default
   `alembic_version.version_num VARCHAR(32)` (SQLite ignores the limit; Postgres
   raises `value too long for type character varying(32)`). Run
   `ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255);` once
   before `alembic upgrade head`.

3. **Set the GitHub repository secret** used by `precompute_v2.yml`:
   - `DATABASE_URL` — the Supabase URL the runner will use, as
     `postgresql+psycopg://postgres.<ref>:<password>@aws-<region>.pooler.supabase.com:5432/postgres`
     (the **session pooler**, port `5432`), with `?sslmode=require` appended.
   This is the only secret the workflow references. It installs
   `packages/data[postgres]`, so `psycopg` is present on the runner (without
   that extra a Postgres URL fails at connect with `ModuleNotFoundError`).

   Optional repo **variables** are forwarded to the job explicitly:
   `VNOPT_V2_BACKFILL_START_DATE`, `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND` and
   the pre-screen knobs `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED` /
   `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_MIN_MEDIAN_VOLUME`. `VNOPT_V2_*_ORDER` and
   `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` are **not** read by the precompute job —
   `data/v2/precompute.py::sources_from_context` wires one adapter per data
   need (SSI `statistics` for prices/sectors/ratios/profiles, KBS for the
   pre-screen and membership, VCI for the benchmark bars) — so those two
   families only configure the API's failover runner.

   Every run uploads the `precompute-report` artifact with
   `precompute_report.txt` (per-step counts and failures) and
   `verify_report.txt` (the read-only `scripts/verify_v2_db.py` table/date
   summary).
4. **Confirm cloud-IP access** — run the `probe_v2.yml` workflow first; SSI sits
   behind Cloudflare, so only promote `ssi_statistics` into the active V2 chains
   after the probe passes on the runner.
5. **Backfill in chunks** — dispatch `precompute_v2.yml` with `mode=full` and a
   `limit` (e.g. `150`) repeatedly; each run resumes from `v2_progress`. Then let
   the schedule run `--incremental`: weekdays at `37 9 * * 1-5`
   (09:37 UTC = 16:37 ICT, after the close) and nightly at `13 19 * * *`
   (19:13 UTC = 02:13 ICT), which repairs a failed weekday run. Both share the
   `precompute-v2` concurrency group with `cancel-in-progress: false`, so they
   queue instead of overlapping. The odd minutes keep the crons out of GitHub's
   busiest scheduler slots, which otherwise delay a run by many minutes.
6. **Read the progress lines** — each per-ticker loop prints a
   `[prices] 37/150 FPT (+968 bars)` style line every 10 tickers, so the job log
   shows live progress instead of staying silent, and `[ratios]` does the same
   for the ratios step. A run dispatched while the upstream EOD bars of the
   session are still unpublished logs `as-of fallback: VNINDEX has no bar ...`
   and processes the last published session instead of failing
   `quality: stale benchmark` / `quality: stale dataset`. Pass the `as_of`
   input (or `--as-of`) to force a date and keep those errors strict.

   Budget: SSI `stock-info` pages 40 rows and the adapter walks 366-day windows,
   so a first history from `2023-01-01` costs roughly 25 requests per ticker
   (~50 s at the default `0.5` req/s throttle). A full ~1,500-name backfill is
   therefore ~20 h and must be chunked (`limit=150` ≈ 2 h, inside the
   350-minute job timeout), while a steady-state incremental day is about three
   requests per ticker (~2.5 h, one run). Until the chunked backfill finishes,
   a scheduled `--incremental` will keep working through the unpriced names
   instead of only fetching the new session; the `v2_progress` rows and the
   `verify_report.txt` `unfinished progress rows` count show how far it got.
6. **Deploy the API and web** as before (`vercel --prod` from the repo root and
   `apps/web`). The API reads the same `DATABASE_URL` (transaction-pooler URL is
   fine for its read path) and needs the `VNOPT_V2_*_ORDER` vars only if you
   override the defaults.
7. **Verify** — `GET /api/v1/v2/coverage` (sector coverage), `GET /api/v1/v2/sectors`
   and `GET /api/v1/v2/analytics` should return populated payloads; the Sector
   Analysis tab should render within a couple of seconds.

### V2 environment variables

| Variable | Where | Required | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | API + precompute job | yes | Postgres in production; migrations use the session-pooler URL. |
| `VNOPT_V2_OHLCV_ORDER` | API | no | V2 price failover chain, default `ssi_statistics,vci,kbs`. |
| `VNOPT_V2_CONSTITUENTS_ORDER` | API | no | Index membership chain, default `kbs`. |
| `VNOPT_V2_SECTOR_MAP_ORDER` | API | no | Sector map chain, default `ssi_statistics`. |
| `VNOPT_V2_RATIOS_ORDER` | API | no | Ratios chain, default `ssi_statistics`. |
| `VNOPT_V2_BACKFILL_START_DATE` | precompute job (repo variable) | no | Backfill start (`2023-01-01`); also `--start`. |
| `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND` | precompute job (repo variable) | no | Shared-client throttle, default `0.5` (30/min). |
| `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_ENABLED` / `..._MIN_MEDIAN_VOLUME` | precompute job (repo variables) | no | Backfill pre-screen, defaults `true` / `10000`. |
| `VNOPT_V2_*_RATE_LIMIT_PER_MINUTE` | API | no | Per-data-type request budget for the failover runner (defaults 10-20/min); the precompute job throttles through the shared client instead. |

### Row-level security on Supabase

The V2 tables are reference data, not per-user rows, so per-row `auth.uid()` RLS
does not apply. Instead the deployment **denies the public API roles entirely**:
RLS is enabled on every table in `public` with **no permissive policies**, and all
residual privileges are revoked from `anon` and `authenticated`, so both have zero
read/write/truncate access. The FastAPI backend connects as `postgres` (the table
owner, which bypasses RLS) and `service_role` has `BYPASSRLS` plus full table and
sequence grants, so the service side keeps full access. Run once after migrating:

```sql
-- Enable RLS on every public table (default-deny: no policies are added).
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
  END LOOP;
END $$;

-- Public API roles: remove every privilege (incl. TRUNCATE, which RLS does not filter).
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- Service role keeps full access, now and for future migrations.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO service_role;
```

Verify: `SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';`
(all `true`) and `SELECT count(*) FROM pg_policies WHERE schemaname = 'public';`
(zero). `anon`/`authenticated` then receive `permission denied` for reads, writes
and truncates, while `postgres`/`service_role` read and write normally.
