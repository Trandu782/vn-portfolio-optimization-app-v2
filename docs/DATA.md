# Data layer

The `packages/data` package fetches, validates and stores Vietnamese daily market
data **anonymously** (no account, login, API key or token for any data source).
This document covers the providers, the failover chain, the database, the sync
job and the API routes.

> All providers are **unofficial and undocumented**. They can change or start
> requiring authentication without notice. When that happens the provider raises a
> clear error and the failover chain moves on; it never silently mixes two
> providers into one series.

## What uses it (V1.1)

There is no standalone Universe page in V1.1. The **Optimize** page builds its
universe internally with fixed sensible filters (all boards allowed, minimum
history, minimum liquidity, suspended/delisted excluded) through
`POST /api/v1/universe/build`; the **Portfolio**, **P&L** and **Rebalance** pages
value holdings from the latest stored closes and backfill an unknown ticker on
demand; **Risk** loads the stored benchmark series; and the data-freshness badge
in the header shows where the latest prices came from. When providers are
unreachable, the cached database is served with a stale warning and the built-in
seed keeps ticker search and the VN30 button working on a cold deployment.

## Providers

| id | source | prices | adjusted? | notes |
| --- | --- | --- | --- | --- |
| `vci` | Viet Capital `trading.vietcap.com.vn` | raw OHLCV | no | Chart endpoint (`/chart/OHLCChart/gap-chart`) fetched over **POST** with `timeFrame`/`symbols`/`to`/`countBack`; response is TradingView UDF arrays (`t/h/o/l/c/v`). Some networks receive an HTML anti-bot page → treated as auth failure and skipped. Price history only. |
| `kbs` | KB Securities `kbbuddywts.kbsec.com.vn` | raw OHLCV | no | Primary source. `/stocks/{symbol}/data_day` (or `/index/{symbol}/data_day`) with `sdate`/`edate` in `DD-MM-YYYY`; rows use `t/o/h/l/c/v`. Anonymous reference data needs no token or header: `/stock/search/data` lists every security (`symbol`, `name`, `exchange`, `type`; only `type: stock` is kept) and `/index/{group}/stocks` returns one KBS group's members (VNINDEX→`HOSE`, VN30→`30`, VN100→`100`, HNXINDEX→`HNX`, HNX30→`HNX30`, UPCOMINDEX→`UPCOM`). |
| `dnse` | DNSE `services.entrade.com.vn` | raw OHLCV | no | Some endpoints now answer `INVALID_TOKEN` to anonymous callers → treated as auth failure and skipped. |
| `tcbs` | TCBS `apipubaws.tcbs.com.vn` | raw OHLCV | no | Browser `Referer`/`Origin` required; field names from the open-source vnstock TCBS adapter (`tradingDate`, `open`, `high`, `low`, `close`, `volume`). |
| `ssi_iboard` | SSI iBoard `iboard-query.ssi.com.vn` | raw OHLCV | no | TradingView UDF arrays (`t/h/o/l/c/v`). Price history only. |

KBS is the default primary provider because it is the only source here that
serves history, the symbol listing and index groups anonymously without a token,
API key or browser header. VCI and SSI iBoard contribute price history; DNSE and
TCBS also publish listings and (TCBS/DNSE) constituents where their anonymous
endpoints still answer.

Every provider implements the `DataProvider` protocol (`data/interfaces.py`) and
returns `list[PriceBar]` with the standard columns:

```
date, open, high, low, close, adj_close, volume, value, source
```

Because none of the anonymous providers adjust for dividends/splits,
`returns_adjusted_prices` is `False` for all five and `adj_close == close`.

### Adding a provider

Implement the protocol in one new file under `packages/data/data/providers/` and
register it with `@data_providers.register(...)`. No existing chain code changes;
`PROVIDER_ORDER` then selects where it sits in the failover order.

## Provider order and the probe

The failover order comes from `PROVIDER_ORDER` (default `kbs,vci,dnse,tcbs,ssi_iboard`).
Set it from what actually works on the **hosted** environment, because an endpoint
reachable from a laptop may be blocked from the cloud.

- Local: `python scripts/probe_providers.py` (3 tickers, 1 index, 5 years).
- Hosted: `GET /api/v1/data/probe` (protected).

The probe reports, per provider: success, latency, rows, history depth, whether
prices look adjusted, and the recommended `PROVIDER_ORDER` (healthy providers
fastest-first). It is an endpoint so it can be run from Vercel, not only a PC.

## Failover chain

`data.fallback.FallbackProvider` tries providers in `PROVIDER_ORDER`, retries each
with exponential backoff, then moves to the next on **any** failure: network,
timeout, HTTP error, auth/token, rate limit, empty result, wrong schema, or stale
data (latest bar behind the last trading day).

- **Validation**: required columns, no negative prices, non-negative volume,
  sorted unique dates.
- **Circuit breaker**: after `VNOPT_CIRCUIT_BREAKER_FAILURES` consecutive
  provider failures the provider is skipped for
  `VNOPT_CIRCUIT_BREAKER_COOLDOWN_SECONDS`.
- **No silent splicing**: when a different provider starts serving new days for a
  symbol, the sync compares overlapping closes. If they differ by more than
  `VNOPT_PRICE_MISMATCH_TOLERANCE` (default 0.5%) it refetches the full history
  from the new provider and replaces the series (logged).
- Every price row stores its `source`; every failover is written to `sync_log`.

`GET /api/v1/data/providers/status` returns each provider's health, last error and
circuit-breaker state. `GET /api/v1/data/freshness` combines that with the freshest
stored price date across both the V1 (`prices_daily`) and V2 (`v2_daily_prices`)
stores and the provider that owns that bar — the V2 source (e.g. `ssi_statistics`)
when V2 is current, else the first healthy provider in `PROVIDER_ORDER` (KBS by
default). The web app's **data-freshness badge** shows that date, the source and
any failover or stale warnings, so it matches the source the Portfolio page values
against.

If **every** provider fails, the API serves the cached database rows with a
`stale: true` flag and a "data may be stale" warning instead of failing the page.

## Built-in seed fallback

Ticker search and the Optimize page's "Start from VN30" button must survive a
cold, offline or restricted deployment. `data/seed.py` holds a deliberately small
built-in snapshot:

- liquid stock codes for HOSE, HNX and UPCoM (names are omitted; only codes and
  the exchange are stored);
- the recorded VN30 membership (VN30 is the only index with seed constituents —
  a partial board list cannot honestly claim to be VNINDEX/HNXINDEX/UPCoM).

`SyncService.sync_reference_data()` asks the failover chain first and writes the
snapshot **only** when every provider failed and the table is still empty. It is
called by `GET /api/v1/symbols` on an empty database, by `sync_benchmark` when the
constituent lookup fails, and explicitly via
`python -m data.jobs.sync --reference`. Seeded rows store `source: "seed"`; a later
successful provider listing replaces them, and existing rows are never overwritten
by the seed.

## Database

SQLAlchemy 2 + Alembic. SQLite locally, Postgres in production, selected by
`DATABASE_URL`.

Tables: `symbols`, `prices_daily`, `indices_daily`, `index_constituents`,
`sync_log`, and an empty `corporate_actions` reserved for V2. All access goes
through repository classes behind `Protocol` interfaces
(`data/db/repositories.py`); upserts are idempotent.

```sh
make migrate          # alembic upgrade head (runs from packages/data)
```

## Sync

Two entry points share `data.sync.SyncService`:

- **Manual** (developer): `python -m data.jobs.sync`
  ```sh
  python -m data.jobs.sync --backfill VNM --backfill FPT --backfill ACB --benchmarks
  python -m data.jobs.sync --symbols VNM,FPT --benchmarks
  python -m data.jobs.sync --reference
  ```
- **Scheduled** (production): `POST` (or `GET`) `/api/v1/data/refresh`, protected
  by `REFRESH_TOKEN`.

The sync is incremental (only missing days), idempotent, processes a bounded batch
within a time budget, records progress in `sync_log`, and returns `remaining` +
`cursor` so a run that hits the function time limit can resume (call again with
`cursor=<value>`).

### Vercel Cron

The root `vercel.json` sets the function region to **`sin1` (Singapore)** — the
closest Vercel region to Vietnam — and schedules:

```json
{ "path": "/api/v1/data/refresh", "schedule": "30 8 * * 1-5" }
```

- `08:30 UTC` = **15:30 Asia/Ho_Chi_Minh (UTC+7)**, 30 minutes after the 15:00
  Vietnam market close, Monday–Friday.
- Vercel Cron sends a `GET` request with `Authorization: Bearer ${CRON_SECRET}`.
  Set `CRON_SECRET` to the same value as `REFRESH_TOKEN` (the endpoint also
  accepts `X-Refresh-Token`).

Vercel plans differ in cron frequency and function duration; check your plan's
current limits. If they are not enough, use a **backup scheduler**: any external
cron service (cron-job.org, UptimeRobot, a small GitHub Action, ...) that sends

```
POST https://<your-api>/api/v1/data/refresh
Authorization: Bearer <REFRESH_TOKEN>
```

on the same weekday schedule, looping with `?cursor=<next_cursor>` until `done`
is `true`. The endpoint is idempotent, so extra or repeated calls are safe.

## API routes

```
GET  /api/v1/symbols?exchange=            stored symbols (HOSE/HNX/UPCoM)
GET  /api/v1/prices/{symbol}?start=&end=  daily prices (backfills once if unknown)
GET  /api/v1/data/index/{index_code}      benchmark daily prices
GET  /api/v1/data/quality/{symbol}        QualityReport
GET  /api/v1/data/providers/status        provider health + failover state
GET  /api/v1/data/freshness               latest price date + active provider
GET  /api/v1/data/probe                   (protected) run the probe
POST /api/v1/data/refresh                 (protected) incremental sync batch
GET  /api/v1/data/refresh                 (protected) same, for Vercel Cron
```

If a requested symbol is unknown it is backfilled on demand with a bounded
history (`VNOPT_ON_DEMAND_HISTORY_DAYS`, default 365). When a caller asks for an
explicit window (the Optimize/Risk timeframe) whose `start` is earlier than the
earliest stored bar, the missing older days are fetched too, so a 3Y/5Y/Max
window reaches the full available history instead of stopping at the first fetch
depth. If the providers are unreachable the response carries `status: "queued"`
and the next scheduled sync fetches it.

## Quality checks

A registry of checks (`data/quality.py`) runs per symbol and returns a
`QualityReport`:

| id | meaning |
| --- | --- |
| `missing_trading_days` | a weekday (excluding exchange holidays) with no bar |
| `stale_price_runs` | long runs of an identical close |
| `zero_volume` | zero-volume days (possible suspension) |
| `price_limit_move` | a daily move beyond the exchange limit (often unadjusted data) |

Adding a check is one class + one registration.

The V2 precompute checks (`data/v2/quality.py`) follow the severity policy in
`docs/DECISIONS.md` D-017: only integrity findings (`no_data`, `duplicate_dates`)
fail the precompute step; per-ticker findings (`missing_trading_days`,
`zero_volume_streak`, `suspicious_returns`, `adjusted_vs_raw_mismatch`) are warnings
stored as adjustment flags, and only a return-corrupting adjusted-close glitch
(reversing move, >15% move, reconciliation difference/suspect) excludes a ticker
from the group indices by default. See `docs/V2_VN100_TRIAGE.md` for the findings
that set the policy.

## Verifying adjustment

```sh
python scripts/check_adjustment.py VNM 2024-05-03
python scripts/check_adjustment.py VNM 2024-05-03 --window 15 --json
```

Text table columns:

```
provider  rows  adjusted  adj %   before / after (close/adj)     raw / adj move
tcbs      21    no        0.00%   100.00/100.00 -> 95.00/95.00   -5.00% / -5.00%
```

`adjusted` is `yes` when any `adj_close` differs from `close`; `adj %` is the
largest such gap; `before`/`after` are the nearest closes around the action date;
`raw / adj move` are the day-on-day moves. `--json` emits the same data as JSON.

## Tests

All tests use recorded fixtures (`packages/data/tests/fixtures/`) and a temporary
SQLite database; nothing touches the network. The suite covers the full failover
chain, empty/bad-schema failover, the circuit-breaker cooldown, cross-provider
price-mismatch detection, cached-data-with-stale-warning behaviour, KBS symbol
listing/group parsing from recorded responses, and the built-in seed used only
when every provider fails on an empty database.

## V2 precompute pipeline (sector, adjusted prices, ratios)

V2 adds a separate, precomputed dataset pipeline in `data/v2/` that populates the
additive `v2_*` tables. It runs on a GitHub Actions runner (or `python -m
data.v2.jobs.precompute` locally), not a serverless function, because a full
backfill is heavy. It uses the same `v2_daily_prices` adjusted closes, ICB level-2
sectors, index membership, 20-session ADTV/ADV medians, full market cap and TTM
financial ratios.

- **Sources / failover** — each V2 data type has its own chain
  (`VNOPT_V2_*_ORDER`, defaults in `data/v2/config.py`). SSI `statistics` is the
  primary source for adjusted OHLCV, sectors, ratios, market cap and corporate
  actions; KBS and VCI back up constituents and OHLCV. The active defaults include
  only providers verified from recorded fixtures; unverified providers stay out of
  the chain until the cloud-IP probe (`scripts/probe_v2.py`) confirms them.
- **Incremental vs full/backfill** — `--incremental` fetches only new dates (about
  one page per ticker per day); `--full` re-fetches the configured window
  (`VNOPT_V2_BACKFILL_START_DATE`, default `2023-01-01`). Heavy backfills are
  chunked with `--limit N`; each ticker commits its own session and the
  `v2_progress` checkpoint records the last committed date, so a run resumes where
  it stopped.
- **Daily jobs** — the scheduled GitHub Actions workflow (`precompute_v2.yml`)
  runs `--incremental` on trading days; the Vercel cron only refreshes the V1
  tables. Manual commands:

  ```sh
  python -m data.v2.jobs.precompute --incremental
  python -m data.v2.jobs.precompute --full --start 2023-01-01 --limit 150
  python -m data.v2.jobs.precompute --incremental --recompute-flags --members VN30
  ```

- **Refresh index membership** — re-running `--incremental` (or `--members VN30`
  to restrict the per-ticker steps) refreshes the stored VN30/VN100 membership from
  KBS and re-validates that VN30 is a subset of VN100.
- **Add a provider or ratio** — a new V2 provider is one class implementing the
  `data.v2.providers.base` protocol plus a `@v2_providers.register`; adding a ratio
  means editing `data/v2/ratios.py` (the ratio sets, labels, categories and
  direction metadata) and optionally a `data/v2/ratio_quality.py` check.
