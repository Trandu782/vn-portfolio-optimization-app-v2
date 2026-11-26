# Implement v2.0.2 — Supabase Egress & Precompute V2 Speed Optimization

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Supabase free-tier egress by ~95% (from >4 GB/week to <200 MB/week) and cut the daily `[Precompute V2 datasets]` GitHub Actions runtime by ~90% (from ~2 hours to ~5–10 minutes) with zero loss of data accuracy or API compatibility.

**Architecture:** Eliminate 3× full-table `v2_daily_prices` scans, 2× full-table `v2_financial_ratios` scans, ~19,000 sequential US↔Singapore N+1 DB round-trips, and 1,519 wasted daily pre-screen HTTP calls in `V2PrecomputeService`; add HTTP keep-alive connection pooling and bounded fetch concurrency in `HttpxHttpClient` / precompute; replace N+1 / full-column / duplicate DB reads in the FastAPI read path (`AnalyticsService`, `FundamentalsService`, `UniverseService`, `optimize.py`, `portfolio.py`, `rebalance.py`) with batched column-projected queries, `data_as_of`-keyed snapshot caching, DB indexes, and Vercel Edge CDN `Cache-Control` headers.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, psycopg3 (Supabase Postgres transaction/session pooler), FastAPI, httpx, Next.js 15 / TypeScript, GitHub Actions.

**Spec:** User diagnosis request (2026-11-26): solve (1) >4 GB / 5 GB 7-day Supabase free-tier egress and (2) ~2-hour `[Precompute V2 datasets]` daily workflow runtime.

---

## Root Cause Analysis (Verified Against Codebase & Run #11 Logs)

### Problem 1: >4 GB / 5 GB Supabase Free-Tier Egress in 7 Days

| # | Source & Exact Location | What Happens Today | Est. Egress Impact |
|---|---|---|---|
| **1A** | `V2PrecomputeService._compute_liquidity` (`packages/data/data/v2/precompute.py:994-1019`) | Loops over all 1,519 tickers calling `store.get_prices(ticker)` with **no start date** — downloads all **423,034 rows × 15 columns** (~85–100 MB on Postgres wire) just to take `ordered[-20:]` (last 20 sessions). | **~85–100 MB / run** |
| **1B** | `V2PrecomputeService._run_quality` (`packages/data/data/v2/precompute.py:1333-1343`) | Loops over all 1,519 tickers calling `store.get_prices(ticker)` (no start date) — downloads all **423,034 rows × 15 columns** a **2nd time** every run. | **~85–100 MB / run** |
| **1C** | `compute_adjustment_flags` (`packages/data/data/v2/precompute.py:193-199`) | Loops over all 1,519 tickers calling `store.get_prices(ticker)` (no start date) — downloads all **423,034 rows × 15 columns** a **3rd time** every run. | **~85–100 MB / run** |
| **1D** | `_compute_sector_statistics` & `_run_ratio_quality` (`packages/data/data/v2/precompute.py:1144,1171`) | Both unconditionally call `store.list_ratios()` — downloading all ~25,000 `v2_financial_ratios` rows (large JSON blobs) **twice per run** even when `ratios` wrote 0 rows. | **~35–45 MB / run** |
| **1E** | 12+ runs/week (`.github/workflows/precompute_v2.yml:37-41`) | Runs 5 weekday 20:07 ICT + 7 nightly 02:13 ICT (including weekends when VN market is closed) + manual dispatches. `13 runs × ~320 MB ≈ 4.16 GB/week` from the workflow alone. | **~3.8–4.5 GB / week** |
| **1F** | `AnalyticsService.build` (`packages/data/data/v2/analytics/service.py:271-279`) | N+1 loop of 130–496 `store.get_prices()` calls transferring all **15 columns** when only `(symbol_code, date, close_adj)` are used; `list_index_dates` fetches all 10 columns of 2,498 `IndexDaily` rows to keep only `date`. | **~7–90 MB / uncached hit** |
| **1G** | `FundamentalsService` (`packages/data/data/v2/fundamentals.py:240-286`) | `periods()` fetches 50 full JSON ratio rows just for `(period, period_type)`. `compare()` fetches ALL 496 tickers' ratio rows across all 19 sectors via `list_ratios()` and discards ~95% in Python, plus runs `price_adjustment_bases()` over 423k price rows unnecessarily. | **~2–4 MB / hit** |
| **1H** | `optimize.py` double-fetch (`apps/api/app/api/v1/optimize.py:361,391,576,682`) | Both `POST /optimize` and `POST /optimize/frontier` load every symbol's V2 prices once via `_load_symbol_series`, then call `_data_sources()` which re-fetches every symbol's full V2 price history **a second time** just to read `series.source`. | **2× DB egress per optimize** |
| **1I** | `portfolio.py` full-year fetch (`apps/api/app/api/v1/portfolio.py:98`) | `get_prices_preferring_v2_spot()` defaults to 365 days (~250 bars/holding) just to read latest close + 20-session ADV. | **~10× excess rows** |
| **1J** | Zero HTTP/CDN caching (`apps/web/lib/api.ts:27`, `apps/api/app/api/v1/v2.py`) | Frontend forces `cache: "no-store"` on every `GET`; FastAPI emits no `Cache-Control` / `s-maxage` headers; `UniverseFilterPanel.tsx` has no debounce on chip clicks; Vercel serverless instances lose in-memory caches on cold starts. | **Every page/tab/click hits Supabase** |

### Problem 2: `[Precompute V2 datasets]` Takes ~2 Hours Per Daily Run

| # | Bottleneck & Exact Location | Exact Math (Verified on Run #11) | Est. Time Cost |
|---|---|---|---|
| **2A** | **~19,000 sequential US↔Singapore DB round-trips** (`precompute.py:193,638,913,999,1119,1333`) | GitHub runner (US) ↔ Supabase (`aws-1-ap-southeast-1`, Singapore) RTT is ~230 ms per query. `_sync_profiles` (4,557 RTTs just to skip all 1,519 tickers), `_compute_liquidity` (~2,500 RTTs), `_sync_ratios` (992 RTTs), `_run_quality` (6,076 RTTs), `compute_adjustment_flags` (4,557 RTTs), `_backfill_prices` (~3,000 RTTs) + transferring ~280 MB over WAN. | **~85–95 min** |
| **2B** | **Pre-screening all 1,519 tickers every run** (`precompute.py:773-845`, confirmed in `precompute-report#11/precompute_report.txt:20-1043`) | Scheduled `LIMIT=1000` exceeds 496 priced tickers. `_select_candidates` runs live KBS HTTP pre-screen on all 496 already-priced tickers AND all 1,023 unpriced illiquid tickers (whose rejection is never saved in `v2_progress`). At 1.5 req/s: `1,519 calls × ~1.0s ≈ 25 min`. | **~20–25 min** |
| **2C** | **2 SSI pages/ticker for daily overlap** (`config.py:141`, `precompute.py:651-654`, `ssi_statistics.py:268`) | `precompute_rebase_overlap_sessions=40` → `2 * 40 = 80` calendar days (~56 trading sessions) > `STOCK_INFO_PAGE_SIZE=40`, forcing **2 HTTP requests/ticker** (992 calls) instead of 1 (496 calls). | **~10–15 min** |
| **2D** | **New TCP + TLS handshake per HTTP call + serial execution** (`packages/data/data/http.py:195`) | `httpx.request(...)` opens a fresh client/socket/TLS handshake on every call (~500–800 ms US↔VN overhead each) with global serial 1.5 req/s throttling. | **~10–15 min** |

### Expected Results After v2.0.2

| Metric | Before (Current) | After (v2.0.2) | Reduction |
|---|---|---|---|
| **Precompute egress (weekday update, 496 tickers +1 bar)** | ~300–350 MB / run | **~2–5 MB / run** | **~98–99%** |
| **Precompute egress (nightly no-op repair run)** | ~300–350 MB / run | **< 0.5 MB / run** | **~99.8%** |
| **Weekly Supabase egress (precompute + web app)** | **>4.0 GB / week** | **~50–150 MB / week** | **~96–98%** |
| **Daily precompute runtime (496 tickers +1 bar)** | **~120–140 min** | **~3–6 min** | **~95%** |
| **Nightly repair no-op runtime** | **~90–120 min** | **~15–30 sec** | **~99%** |

---

## Global Constraints

- Python 3.12, full type hints, Pydantic v2 for every API/domain schema; `ruff` and `mypy` must pass with zero warnings/errors.
- No new runtime dependencies (bundle stays lean on Vercel).
- Unit tests never touch the network (use recorded fixtures / fake sources and temporary SQLite databases).
- All DB schema/index changes go strictly through Alembic migrations (`packages/data/alembic/versions/`); keep revision IDs ≤ 32 characters.
- No breaking changes to `/api/v1` response schemas (`make client-check` must stay green without breaking `apps/web/lib/schema.d.ts`).
- Full verification gate before completion: `make check` (`lint`, `typecheck`, `client-check`, `test`, `test-web`).
- Update `docs/CHANGELOG.md`, `docs/DEPLOYMENT.md`, and `docs/DATA.md` with the v2.0.2 changes and new env variables.

## Review Focus

1. **Retroactive SSI rebase triggers full recomputation:** When an incremental price fetch detects an adjusted-close mismatch (`_needs_rebase == True`) and re-fetches full history for a ticker, Steps 6–8 MUST recompute full-history quality checks and full-history adjustment flags for that ticker (never skip via the incremental tail-only fast path).
2. **Pre-screen cooldown & already-priced protection:** Already-priced tickers (`latest is not None`) are NEVER screened or dropped by `_passes_pre_screen` even if their recent volume drops below the floor; unpriced tickers rejected by pre-screen are persisted as `state="pre_screen_rejected"` and skipped during incremental runs within `precompute_pre_screen_cooldown_days`, but re-screened on `mode="full"`, `--profiles`, or once cooldown expires.
3. **Thread-safety & isolated failures under concurrent fetch:** With `precompute_concurrency > 1`, per-host rate limits and 403 cooldowns in `HttpxHttpClient` are mutex-protected, DB writes happen safely without SQLite `database is locked` errors, and a single ticker's provider or upsert failure records a `failed` checkpoint without aborting remaining tickers.
4. **In-memory snapshot cache invalidation & test isolation:** `UniverseSnapshot` and `AdjustmentFlags` caches invalidate automatically whenever `overall_latest_price_date()` changes (or `clear_analytics_cache()` is called), preventing stale API responses after a precompute run and preventing cross-test leakage.
5. **Empty-batch safety & migration reversibility:** All new batch `V2Store` queries (`get_prices_batch`, `get_close_prices_batch`, `get_recent_prices_batch`, `list_ratios_for_symbols`) return `{}` / `[]` immediately on empty symbol sequences without executing invalid `IN ()` SQL, and migration `0006_v2_query_indexes.py` upgrades and downgrades cleanly on SQLite and Postgres.

---

### Task 1: Eliminate Redundant Pre-Screening & Shrink Incremental Rebase Overlap

**Files:**
- Modify: `packages/data/data/v2/config.py:114-145`
- Modify: `packages/data/data/v2/store.py:551-603`
- Modify: `packages/data/data/v2/precompute.py:584-656,753-887`
- Modify: `scripts/verify_v2_db.py:114-127,156-160`
- Test: `packages/data/tests/test_v2_precompute.py`

**Interfaces:**
- Produces:
  - `V2DataSettings.precompute_pre_screen_cooldown_days: int = 30` (env `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_COOLDOWN_DAYS`)
  - `V2DataSettings.precompute_rebase_overlap_sessions: int = 10` (reduced from `40`)
  - `V2DataSettings.precompute_ratios_refresh_days: int = 7` (env `VNOPT_V2_PRECOMPUTE_RATIOS_REFRESH_DAYS`)
  - `V2DataSettings.precompute_concurrency: int = 3` (env `VNOPT_V2_PRECOMPUTE_CONCURRENCY`)
  - `V2Store.set_progress_many(self, records: Sequence[ProgressRecord]) -> int`
  - `V2PrecomputeService._order_price_candidates(self, tickers: Sequence[str], *, skip_known_empty: bool, target: date | None = None) -> list[str]`

- [ ] **Step 1: Write failing tests in `packages/data/tests/test_v2_precompute.py`**

Add these four unit tests:
```python
def test_already_priced_tickers_bypass_pre_screen_even_if_volume_dips(
    factory: sessionmaker[Session],
) -> None:
    """An already-priced ticker must be updated without calling screen_bars."""
    # Seed VCB priced up to AS_OF - 1 day, then drop its volume below pre-screen floor
    # Run mode="incremental" with precompute_pre_screen_enabled=True, min_median_volume=500
    # Assert fake.screen_calls == []
    # Assert VCB received the new bar at AS_OF and latest_price_date("VCB") == AS_OF

def test_prescreen_rejections_are_persisted_and_skipped_during_cooldown(
    factory: sessionmaker[Session],
) -> None:
    """Rejected unpriced tickers get state='pre_screen_rejected' and are skipped on incremental runs within cooldown."""
    # Run 1 (incremental, limit=10): AAA has 0 volume -> screened once, rejected, persisted as state="pre_screen_rejected", last_date=AS_OF
    # Run 2 (incremental, next day, within 30d cooldown): fake.screen_calls == [] (AAA skipped)
    # Run 3 (incremental, profiles=True): AAA IS re-screened
    # Run 4 (incremental, AS_OF + 31 days): AAA IS re-screened after cooldown expires

def test_incremental_rebase_overlap_fits_in_single_ssi_page() -> None:
    """Default overlap (10 sessions -> 20 calendar days) stays well below SSI's 40-row page size."""
    settings = V2DataSettings()
    assert settings.precompute_rebase_overlap_sessions == 10
    assert settings.precompute_pre_screen_cooldown_days == 30
    assert settings.precompute_ratios_refresh_days == 7
    assert settings.precompute_concurrency == 3

def test_set_progress_many_preserves_nonzero_rows_and_upserts_in_bulk(
    factory: sessionmaker[Session],
) -> None:
    """Bulk progress upsert writes multiple rows in one call and never blanks historical row counts."""
    # Write ("prices", "VCB", state="done", rows=500)
    # Call store.set_progress_many with VCB rows=0 + AAA state="pre_screen_rejected" rows=0
    # Assert VCB rows == 500 and AAA state == "pre_screen_rejected"
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `python -m pytest packages/data/tests/test_v2_precompute.py -k "bypass_pre_screen or skipped_during_cooldown or single_ssi_page or set_progress_many" -v`
Expected: FAIL (missing settings/methods and current code calls `screen_bars` on every candidate).

- [ ] **Step 3: Implement config settings, `V2Store.set_progress_many`, pre-screen bypass/cooldown, and `verify_v2_db.py` update**

1. In `packages/data/data/v2/config.py`:
   - Add `precompute_pre_screen_cooldown_days: int = 30`, `precompute_ratios_refresh_days: int = 7`, and `precompute_concurrency: int = 3`.
   - Change `precompute_rebase_overlap_sessions: int = 10` (from `40`; `2 * 10 = 20` calendar days ≈ 14 trading sessions + new bars ≤ 40 SSI page size).
2. In `packages/data/data/v2/store.py`:
   - Add `set_progress_many(self, records: Sequence[ProgressRecord]) -> int`: fetch existing non-zero row counts for any incoming `rows <= 0` records in ONE `SELECT kind, symbol, rows FROM v2_progress WHERE ...` query, preserve `stored > 0`, and call `_bulk_upsert` once. Delegate `set_progress` to `set_progress_many([record])`.
3. In `packages/data/data/v2/precompute.py`:
   - In `_order_price_candidates(..., target: date | None = None)`: when `skip_known_empty` is `True`, skip checkpoints where `state == "done"` (existing behavior) OR (`state == "pre_screen_rejected"` and `checkpoint.last_date is not None` and `target is not None` and `(target - checkpoint.last_date).days < self._settings.precompute_pre_screen_cooldown_days`). Pass `target=target` from `_backfill_prices`.
   - In `_select_candidates`: for `(_latest, ticker)` in `pending`, if `_latest is not None` (already has stored prices), append directly to `selected` WITHOUT calling `_passes_pre_screen(ticker)`. Only call `_passes_pre_screen(ticker)` when `_latest is None` (unpriced candidate).
   - After the loop in `_select_candidates`, if `rejected` is non-empty, bulk-persist `[ProgressRecord(kind="prices", symbol=t, state="pre_screen_rejected", last_date=target, rows=0) for t in rejected]` via a single `session_scope` calling `store.set_progress_many(...)`.
4. In `scripts/verify_v2_db.py`:
   - Change the `unfinished` query (`line 116`) to `WHERE state NOT IN ('done', 'pre_screen_rejected')` so intentionally skipped illiquid names are not reported as unfinished errors (they still appear in `price progress states` as `pre_screen_rejected=1023`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest packages/data/tests/test_v2_precompute.py -v`
Expected: PASS (all existing + 4 new tests green).

- [ ] **Step 5: Commit**

```bash
git add packages/data/data/v2/config.py packages/data/data/v2/store.py packages/data/data/v2/precompute.py scripts/verify_v2_db.py packages/data/tests/test_v2_precompute.py
git commit -m "perf(v2): bypass prescreen for priced tickers, cache rejections, shrink rebase window"
```

---

### Task 2: HTTP Connection Pooling, Thread-Safe Per-Host Rate Limiting & Concurrent Price Fetching

**Files:**
- Modify: `packages/data/data/http.py:79-240`
- Modify: `packages/data/data/v2/precompute.py:557-725`
- Modify: `packages/data/data/v2/jobs/precompute.py:182-203`
- Test: `packages/data/tests/test_http.py` (create)
- Test: `packages/data/tests/test_v2_precompute.py`

**Interfaces:**
- Consumes: `V2DataSettings.precompute_concurrency` (Task 1), `V2Store.set_progress_many` (Task 1)
- Produces:
  - `HttpxHttpClient.close(self) -> None` and `__enter__` / `__exit__` context manager
  - Thread-safe per-host rate limiting and persistent `httpx.Client` connection pooling inside `HttpxHttpClient`
  - `V2Store.get_close_prices_batch(self, symbols: Sequence[str], start: date, end: date, *, chunk_size: int = 200) -> dict[str, list[tuple[date, float]]]`
  - `_PriceBackfillResult(step: StepResult, updated: set[str], rebased: set[str])` returned by `V2PrecomputeService._run_price_backfill(...)` (keeping `_backfill_prices(...) -> StepResult` as a thin wrapper for backward compatibility)

- [ ] **Step 1: Write failing tests in `packages/data/tests/test_http.py` and `packages/data/tests/test_v2_precompute.py`**

In `packages/data/tests/test_http.py`:
```python
def test_httpx_client_reuses_persistent_client_and_throttles_per_host() -> None:
    """Two different hosts do not block each other's rps slot; same host does; one httpx.Client is reused."""
    # Inject fake clock, sleep recorder, and httpx.MockTransport
    # Issue GET to host-a, GET to host-b (0 sleep), GET to host-a (sleeps 1/rps)
    # Assert persistent self._client was reused across all 3 calls and close() closes it

def test_httpx_client_rate_limiter_is_thread_safe_under_concurrent_requests() -> None:
    """Concurrent threads against the same host serialize slots cleanly without race conditions or negative sleeps."""
    # Run 6 requests from ThreadPoolExecutor(max_workers=3) against httpx.MockTransport
    # Assert all 6 return 200 and recorded sleeps are all >= 0
```
In `packages/data/tests/test_v2_precompute.py`:
```python
def test_concurrent_price_backfill_commits_all_tickers_and_isolates_failures(
    factory: sessionmaker[Session],
) -> None:
    """With precompute_concurrency=3, successful tickers commit cleanly even when one ticker raises ProviderError."""
    # 5 tickers, 1 raises ProviderError; run with precompute_concurrency=3
    # Assert 4 tickers stored with state="done", failing ticker has state="failed", no SQLite lock errors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest packages/data/tests/test_http.py packages/data/tests/test_v2_precompute.py -k "persistent_client or thread_safe or concurrent_price_backfill" -v`
Expected: FAIL.

- [ ] **Step 3: Implement pooled `HttpxHttpClient` and concurrent-fetch / batch-commit `_backfill_prices`**

1. In `packages/data/data/http.py`:
   - Add `transport: httpx.BaseTransport | None = None` optional kwarg to `HttpxHttpClient.__init__` (enables clean `httpx.MockTransport` testing).
   - Create a persistent `self._client = httpx.Client(timeout=self._timeout, follow_redirects=True, limits=httpx.Limits(max_connections=16, max_keepalive_connections=10), transport=transport)` and implement `close()`, `__enter__`, `__exit__`.
   - Protect rate-limit state and `_host_cooldowns` with `self._lock = threading.Lock()`.
   - Track `_last_request_by_host: dict[str, float]` and `_recent_by_host: dict[str, deque[float]]` keyed by `urlparse(url).netloc`. Compute any needed sleep duration *inside* the lock, reserve the next slot timestamp (`scheduled_at = max(now, last + 1/rps)`), release the lock, and sleep *outside* the lock so other hosts and in-flight I/O are never blocked while sleeping!
   - Replace `httpx.request(...)` with `self._client.request(...)`.
2. In `packages/data/data/v2/jobs/precompute.py`:
   - Close `context.http.close()` in a `finally:` block if `hasattr(context.http, "close")`.
3. In `packages/data/data/v2/precompute.py`:
   - Introduce internal dataclass `_PriceBackfillResult(step: StepResult, updated: set[str], rebased: set[str])` (keep `_backfill_prices` returning `StepResult` or add helper `_run_price_backfill` so any direct test calling `_backfill_prices` stays unaffected).
   - Pre-load `latest_by_ticker = store.latest_price_dates()` ONCE before the loop (eliminating 496 `latest_price_date` DB calls inside `_backfill_ticker`).
   - For overlap checks (`_needs_rebase`), pre-load the tail closes for all incremental candidate tickers in ONE bulk DB query (`V2Store.get_close_prices_batch` or `get_prices_batch` from `min_overlap_start` to `target` — defined in Task 3 or right here in `V2Store`, let's put `get_close_prices_batch` in `V2Store` here so Task 2 uses it directly and Task 4 reuses it!).
   - Run HTTP fetching (`stock_bars`, and rebase full re-fetch if overlap disagrees) using `concurrent.futures.ThreadPoolExecutor(max_workers=max(1, self._settings.precompute_concurrency))` when `precompute_concurrency > 1` and `len(tickers) > 1`, executing pure HTTP fetches on worker threads and committing DB upserts on the main thread in batches (every 25 tickers, or per ticker on `upsert_prices` failure fallback so one bad ticker can never roll back other tickers in the batch!). Keep per-ticker failure isolation identical to `test_price_upsert_failure_is_contained_to_one_ticker`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest packages/data/tests/test_http.py packages/data/tests/test_v2_precompute.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/data/data/http.py packages/data/data/v2/store.py packages/data/data/v2/precompute.py packages/data/data/v2/jobs/precompute.py packages/data/tests/test_http.py packages/data/tests/test_v2_precompute.py
git commit -m "perf(v2): pool HTTP connections, add per-host thread-safe throttling and concurrent price fetches"
```

---

### Task 3: Eliminate 3× Full `v2_daily_prices` Scans, 2× `v2_financial_ratios` Scans & ~19,000 N+1 DB Round-Trips in Precompute

**Files:**
- Modify: `packages/data/data/v2/store.py`
- Modify: `packages/data/data/v2/precompute.py:172-248,282-380,900-1380`
- Modify: `packages/data/data/v2/precompute_schemas.py` (add optional `elapsed_seconds: float | None = None` on `StepResult`)
- Modify: `packages/data/data/v2/jobs/precompute.py:133-145` (print step duration in `_print_report`)
- Test: `packages/data/tests/test_v2_precompute.py`

**Interfaces:**
- Consumes: `_PriceBackfillResult(step, updated, rebased)` (Task 2), `V2DataSettings.precompute_ratios_refresh_days` (Task 1)
- Produces:
  - `V2Store.get_prices_batch(self, symbols: Sequence[str], start: date | None = None, end: date | None = None) -> dict[str, list[AdjustedOHLCV]]`
  - `V2Store.upsert_liquidity_many(self, records: Sequence[LiquidityRecord]) -> int`
  - `V2Store.list_all_corporate_actions(self, symbols: Sequence[str] | None = None) -> dict[str, list[CorporateAction]]`
  - `V2Store.count_sector_statistics(self) -> int`
  - `V2Store.list_index_dates(self, index_code: str = "VNINDEX") -> list[date]` (projected single-column query)
  - `StepResult.elapsed_seconds: float | None = None`

- [ ] **Step 1: Write failing tests in `packages/data/tests/test_v2_precompute.py`**

Add tests that explicitly verify both correctness AND SQL query/row bounds (using SQLAlchemy `before_cursor_execute` event listener to count queries and assert no full-table N+1 scans!):
```python
def test_incremental_noop_run_skips_full_price_and_ratio_scans(
    factory: sessionmaker[Session],
) -> None:
    """A second incremental run on the same target date issues O(1) DB queries and skips liquidity/stats/flag rewrites."""
    # Run 1: full run for 3 tickers (VCB, FPT, HPG) with ratios
    # Attach SQLAlchemy before_cursor_execute counter on factory.kw["bind"]
    # Run 2: incremental run on same AS_OF
    # Assert report.ok
    # Assert total SQL queries < 30 (was 100+ even for 3 tickers, 19,000+ for 1,519 tickers)
    # Assert zero SELECTs against v2_financial_ratios during no-op run
    # Assert sector_statistics step message indicates skipped

def test_incremental_single_day_update_only_reads_tail_bars_unless_rebased(
    factory: sessionmaker[Session],
) -> None:
    """When +1 clean bar arrives on incremental run, liquidity/quality/flags read only tail bars; a rebased ticker triggers full-history recompute."""
    # Seed 2 tickers (VCB clean +1 bar, FPT rebased with 0.8x split factor)
    # Run incremental on AS_OF + 1 trading day
    # Assert liquidity updated for both VCB and FPT
    # Assert FPT's adjustment flag and quality checks reflect its full rebased series
    # Assert VCB did not trigger a full-history v2_daily_prices fetch (only tail window >= target - 45d)

def test_ratios_incremental_respects_refresh_days_cadence_and_loads_once(
    factory: sessionmaker[Session],
) -> None:
    """Incremental ratios skip tickers refreshed within precompute_ratios_refresh_days, refresh after cadence expires, and load v2_financial_ratios at most once across stats + quality."""
    # Run 1 at day 0 -> ratios written
    # Run 2 at day 2 (incremental, refresh_days=7) -> fake.ratio_calls == [], v2_financial_ratios NOT scanned
    # Run 3 at day 8 (incremental, refresh_days=7) -> fake.ratio_calls refreshes tickers, v2_financial_ratios queried ONCE total (not twice)

def test_batch_store_helpers_handle_empty_symbol_list(
    factory: sessionmaker[Session],
) -> None:
    """Empty symbol sequences return empty dicts without emitting invalid SQL."""
    with session_scope(factory) as session:
        store = V2Store(session)
        assert store.get_prices_batch([]) == {}
        assert store.get_close_prices_batch([], START, AS_OF) == {}
        assert store.list_all_corporate_actions([]) == {}
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `python -m pytest packages/data/tests/test_v2_precompute.py -k "noop_run_skips or tail_bars_unless_rebased or refresh_days_cadence or empty_symbol_list" -v`
Expected: FAIL.

- [ ] **Step 3: Implement bulk `V2Store` helpers and incremental/batched steps 5–8 in `V2PrecomputeService`**

1. In `packages/data/data/v2/store.py`:
   - Optimize `list_index_dates(index_code)`: query `select(IndexDaily.date).where(IndexDaily.index_code == index_code.upper()).order_by(IndexDaily.date)` (1 column, 1 query instead of 3 queries fetching all 10 columns).
   - Add `get_prices_batch(symbols, start=None, end=None, *, chunk_size=200)`: return `{}` immediately if `not symbols`; query `V2DailyPrice` with `V2DailyPrice.symbol_code.in_(chunk)` ordered by `(symbol_code, date)`, grouped into `dict[str, list[AdjustedOHLCV]]`.
   - Reuse `get_close_prices_batch` added in Task 2.
   - Add `upsert_liquidity_many(records: Sequence[LiquidityRecord]) -> int`: single `_bulk_upsert` call; delegate `upsert_liquidity(record)` to `upsert_liquidity_many([record])`.
   - Add `list_all_corporate_actions(symbols: Sequence[str] | None = None) -> dict[str, list[CorporateAction]]`: return `{}` if `symbols is not None and not symbols`; single bulk query ordered by `(ticker, exright_date)`.
   - Add `count_sector_statistics() -> int`: `SELECT COUNT(*) FROM v2_sector_statistics`.
2. In `packages/data/data/v2/precompute.py`:
   - **Step 5 (`_sync_profiles`):** Load `progress_by_symbol = {r.symbol: r for r in store.list_progress("profile")}` and `priced = set(store.latest_price_dates())` in **1 session** before the loop. Skip unpriced or `done` tickers in pure Python (0 DB queries per skipped ticker!).
   - **Step 6 (`_compute_liquidity`):** Accept `updated_tickers: set[str] | None = None` and `mode: str = "full"`.
     - Load existing `liquidity_symbols = {r.symbol for r in store.list_liquidity()}` and `priced = set(store.latest_price_dates())` once.
     - Determine `to_compute`: in `mode == "full"` or `updated_tickers is None`, all priced tickers in `master`; in `mode == "incremental"`, `priced & (updated_tickers | (priced - liquidity_symbols))`. If empty, return `StepResult(name="liquidity", ok=True, processed=0)` with **0 price queries**!
     - Fetch ONLY the tail window needed (`tail_start = target - timedelta(days=max(60, 3 * self.window))`) via `store.get_prices_batch(to_compute, start=tail_start, end=target)` (batched in chunks of 100 tickers). Compute `liquidity_stats` and persist all records in ONE `store.upsert_liquidity_many(records)` call!
   - **Step 6b (`_sync_ratios`):**
     - Replace `_pending_ratio_tickers` and `_ratio_refreshed_today` N+1 loops with **1 bulk load**: `ratio_progress = {r.symbol: r for r in store.list_progress("ratios")}`.
     - In `mode == "incremental"`, a ticker is due if it has no `"done"` progress OR `progress.last_date is None` OR `(target - progress.last_date).days >= self._settings.precompute_ratios_refresh_days` (still respects `limit`). Note: when `limit` is set on `mode == "full"`, preserve existing behavior (skip already `"done"` so chunked backfills advance).
   - **Steps 6c & 6d (`_compute_sector_statistics` & `_run_ratio_quality`):**
     - In `run()`, check if `ratios_step.processed == 0` AND `mode == "incremental"` AND `store.count_sector_statistics() > 0`: if so, skip both steps (zero `v2_financial_ratios` download!) and record `StepResult(..., ok=True, processed=0, message="skipped (no ratio changes)")`.
     - Otherwise, load `ratios = store.list_ratios()` and `sectors = store.list_sectors()` **ONCE** in `run()` and pass them into `_compute_sector_statistics` and `_run_ratio_quality` so `v2_financial_ratios` is NEVER downloaded twice!
   - **Steps 7 & 8 (`_run_quality` & `compute_adjustment_flags`):**
     - Load `progress_by_symbol = {r.symbol: r for r in store.list_progress("prices")}`, `existing_flags = {f.ticker: f for f in store.list_adjustment_flags()}`, and `actions_by_ticker = store.list_all_corporate_actions()` in **1 session** (eliminating 4,557 + 6,076 N+1 queries!).
     - Keep all dataset-level checks (`trading_days`, `benchmark_lag`, `dataset_lag`) identical in `_run_quality`.
     - For per-ticker quality + adjustment flags:
       - Filter to priced/done tickers in `master` (`code in priced` and `progress is not None and progress.state != "failed"`).
       - Determine which tickers require **full-history** evaluation (`full_needed`):
         - `mode == "full"` OR `only_unpriced` (for newly priced tickers) OR `ticker in rebased_tickers` OR `ticker not in existing_flags` OR `policy_from_source(existing_flags[ticker].source) != FLAGS_POLICY_VERSION` OR `ticker in profile_updated_tickers`.
       - For remaining `updated_tickers - full_needed` (normal incremental +1 bar, policy already current, not rebased):
         - Reuse the **already-fetched tail bars** (`tail_start .. target`, ≥20 sessions) to run tail quality checks (`no_data`, `duplicate_dates`, `zero_volume_streak`, `suspicious_returns`, `adjusted_vs_raw_mismatch`) AND `find_adjustment_anomalies(ticker, tail_bars, actions)`.
         - If ANY new tail anomaly is detected on a date not already recorded in `existing_flags[ticker].dates`, promote that ticker into `full_needed` so its full-history flag is accurately recomputed!
         - Otherwise, keep its existing flag row intact (zero full-history price download!).
       - For `full_needed` tickers (0–5 tickers on a normal weekday incremental run; all 496 on `mode="full"` or `--recompute-flags`):
         - Fetch full prices in chunks of 50 tickers via `store.get_prices_batch(chunk)` **ONCE** and share the loaded bars across BOTH `_run_quality` and `compute_adjustment_flags` (eliminating the duplicate full-table scan even in `mode="full"` and `recompute_adjustment_flags_offline`!).
       - Upsert only the newly computed `AdjustmentFlagRecord`s via `store.upsert_adjustment_flags(records)`.
3. In `packages/data/data/v2/precompute_schemas.py` & `packages/data/data/v2/jobs/precompute.py`:
   - Add `elapsed_seconds: float | None = None` to `StepResult`; time each step in `V2PrecomputeService.run()` with `time.perf_counter()` and print `({step.elapsed_seconds:.1f}s)` in `_print_report`.

- [ ] **Step 4: Run full data package tests to verify they pass**

Run: `python -m pytest packages/data/tests/test_v2_precompute.py packages/data/tests/test_v2_adjustment_flags.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/data/data/v2/store.py packages/data/data/v2/precompute.py packages/data/data/v2/precompute_schemas.py packages/data/data/v2/jobs/precompute.py packages/data/tests/test_v2_precompute.py
git commit -m "perf(v2): batch precompute DB reads and run incremental tail-only liquidity/quality/flags"
```

---

### Task 4: Optimize API Read Queries, Eliminate Double-Fetches, Add Snapshot Cache & DB Indexes

**Files:**
- Create: `packages/data/alembic/versions/0006_v2_query_indexes.py`
- Modify: `packages/data/data/v2/store.py` (add `list_ratios_for_symbols`, `list_ratio_periods`)
- Modify: `packages/data/data/v2/analytics/universe_reader.py` (add `data_as_of`-keyed cache + `include_price_bases: bool = True` + `clear_universe_cache`)
- Modify: `packages/data/data/v2/analytics/cache.py` (make `clear_analytics_cache` also call `clear_universe_cache`)
- Modify: `packages/data/data/v2/analytics/service.py:269-297` (use `store.get_close_prices_batch` instead of N+1 `get_prices`)
- Modify: `packages/data/data/v2/fundamentals.py:240-290` (use `list_ratio_periods`, `list_ratios_for_symbols`, and `include_price_bases=False`)
- Modify: `packages/data/data/service.py:224-287` (add `get_prices_v2_batch` and `get_prices_preferring_v2_spot_batch` with `recent_days` support)
- Modify: `apps/api/app/api/v1/optimize.py:360-405,470-480,575-623,680-686` (batch load prices and eliminate `_data_sources` double-fetch!)
- Modify: `apps/api/app/api/v1/universe.py:199-205,228-264` (batch load prices via `get_prices_v2_batch`)
- Modify: `apps/api/app/api/v1/risk.py:283-286,370-373` (batch load prices)
- Modify: `apps/api/app/api/v1/portfolio.py:97-105` (load only last 45 calendar days via `start=today - timedelta(days=45)` instead of 365 days!)
- Modify: `apps/api/app/api/v1/rebalance.py:289-313` (use `get_prices_preferring_v2_spot` with `start=service.today - timedelta(days=45)` so Rebalance uses fresh V2 spot closes and fetches 45 days instead of 365 days)
- Test: `packages/data/tests/test_v2_analytics_service.py`, `packages/data/tests/test_v2_fundamentals.py`, `packages/data/tests/test_v2_migrations.py`, `apps/api/tests/test_optimize_endpoint.py`, `apps/api/tests/test_portfolio_endpoint.py`

**Interfaces:**
- Consumes: `V2Store.get_close_prices_batch` and `V2Store.get_prices_batch` (Tasks 2–3)
- Produces:
  - Alembic revision `0006_v2_query_indexes` (`down_revision = "0005_v2_financial_ratios"`): creates `ix_v2_daily_prices_date` on `v2_daily_prices (date)` and `ix_v2_financial_ratios_period` on `v2_financial_ratios (period, period_type)`.
  - `V2Store.list_ratio_periods(self, symbol: str) -> list[tuple[date, str]]`
  - `V2Store.list_ratios_for_symbols(self, symbols: Sequence[str], *, period: date, period_type: str) -> list[RatioRecord]`
  - `load_universe_snapshot(session_factory, *, include_price_bases: bool = True) -> UniverseSnapshot` (cached by `overall_latest_price_date()` + `include_price_bases`)
  - `load_adjustment_flags(session_factory) -> tuple[dict[str, AdjustmentQualityFlag], bool, bool]` (cached by `overall_latest_price_date()`)
  - `clear_universe_cache() -> None`
  - `DataService.get_prices_v2_batch(self, symbols: Sequence[str], *, start: date | None = None, end: date | None = None) -> dict[str, PriceSeries]`

- [ ] **Step 1: Write failing tests across data & API test suites**

1. In `packages/data/tests/test_v2_analytics_service.py`:
   - `test_analytics_build_uses_single_batched_close_query`: attach SQLAlchemy `before_cursor_execute` listener, assert `AnalyticsService.build` queries `v2_daily_prices` at most twice total (not N times per ticker) and never selects `open`/`high`/`low`/`matched_volume` when loading bars for return calculation.
   - `test_universe_snapshot_cache_hits_and_invalidates_when_data_date_advances`: call `load_universe_snapshot` twice -> second call issues only the 1-query `overall_latest_price_date` probe; insert a newer price bar -> next call reloads fresh snapshot.
2. In `packages/data/tests/test_v2_fundamentals.py`:
   - `test_fundamentals_compare_only_queries_sector_peers`: seed tickers in two different sectors; attach SQL listener; assert `FundamentalsService.compare` filters `v2_financial_ratios` by `symbol_code IN (...)` (sector peers only) and never queries `price_adjustment_bases`.
3. In `apps/api/tests/test_optimize_endpoint.py`:
   - `test_frontier_loads_prices_once_without_double_fetching_data_sources`: spy on `DataService.get_prices_v2` / `get_prices_v2_batch` during `POST /api/v1/optimize` and `POST /api/v1/optimize/frontier`, assert each symbol's prices are loaded once (not twice) and `assumptions.data_sources` is still populated identically.
4. In `packages/data/tests/test_v2_migrations.py`:
   - Verify `upgrade head` creates `ix_v2_daily_prices_date` and `ix_v2_financial_ratios_period`, and `downgrade -1` drops both cleanly.

- [ ] **Step 2: Run new tests to verify they fail**

Run: `python -m pytest packages/data/tests/test_v2_analytics_service.py packages/data/tests/test_v2_fundamentals.py packages/data/tests/test_v2_migrations.py apps/api/tests/test_optimize_endpoint.py -k "batched_close_query or invalidates_when_data_date_advances or only_queries_sector_peers or without_double_fetching or 0006" -v`
Expected: FAIL.

- [ ] **Step 3: Implement migration, batched read queries, snapshot cache, and route optimizations**

1. Create `packages/data/alembic/versions/0006_v2_query_indexes.py`:
   - `revision = "0006_v2_query_indexes"`, `down_revision = "0005_v2_financial_ratios"`.
   - `upgrade()`: create `ix_v2_daily_prices_date` on `v2_daily_prices (date)` and `ix_v2_financial_ratios_period` on `v2_financial_ratios (period, period_type)`.
   - `downgrade()`: drop both indexes.
2. In `packages/data/data/v2/store.py`:
   - Add `list_ratio_periods(symbol)` selecting only `(V2FinancialRatio.period, V2FinancialRatio.period_type)` ordered by `period.desc(), period_type`.
   - Add `list_ratios_for_symbols(symbols, *, period, period_type)`: return `[]` if `not symbols`; query with `.where(V2FinancialRatio.symbol_code.in_(codes), V2FinancialRatio.period == period, V2FinancialRatio.period_type == period_type)`.
3. In `packages/data/data/v2/analytics/universe_reader.py` & `cache.py`:
   - Add module-level caches `_snapshot_cache` and `_flags_cache` keyed by `(id(session_factory), include_price_bases)` and validated against `data_as_of = V2Store(session).overall_latest_price_date()` (and flag row count or `MAX(data_as_of)` from `v2_adjustment_flags` so `--recompute-flags` also invalidates `_flags_cache`!).
   - When `include_price_bases=False`, skip `store.price_adjustment_bases()` and set `price_adjustment_bases={}`.
   - Expose `clear_universe_cache()` and invoke it inside `clear_analytics_cache()` so existing tests stay isolated.
4. In `packages/data/data/v2/analytics/service.py`:
   - Replace the per-ticker `store.get_prices(row.ticker, price_from, window.end)` loop (lines 273–276) with ONE `store.get_close_prices_batch([row.ticker for row in kept], price_from, window.end)` call, feeding lightweight `AdjustedOHLCV` or `(date, close)` into `calendar_returns` (note: check `calendar_returns` in `packages/data/data/v2/returns.py` — if it reads `.date` and `.close`, a tiny `dataclass` / `SimpleNamespace` or minimal `AdjustedOHLCV(date=d, open=c, high=c, low=c, close=c, volume=0, source="")` keeps `calendar_returns`'s signature untouched!).
5. In `packages/data/data/v2/fundamentals.py`:
   - In `periods()`, call `store.list_ratio_periods(symbol)`.
   - In `compare()`, call `load_universe_snapshot(self._session_factory, include_price_bases=False)` and `store.list_ratios_for_symbols(peer_tickers, period=period, period_type=period_type)`.
6. In `packages/data/data/service.py`, `apps/api/app/api/v1/universe.py`, `optimize.py`, `risk.py`, `portfolio.py`, `rebalance.py`:
   - Add `DataService.get_prices_v2_batch(symbols, start=None, end=None)` using `V2Store.get_prices_batch` in one session, returning `dict[str, PriceSeries]` with the exact same `PriceSeries` shape/warnings as `get_prices_v2`.
   - Add `_load_symbol_series_batch(service, codes, start, end) -> tuple[list[SymbolSeries], dict[str, str]]` in `universe.py` returning both the `SymbolSeries` list and `{code: source}` map; use it in `universe.py`, `optimize.py`, and `risk.py`.
   - In `optimize.py`, remove the redundant `_data_sources()` DB queries in `run_optimize` and `_frontier_to_response` and derive `data_sources = sorted({sources[code] for code in universe.symbols if code in sources})`.
   - In `portfolio.py`, pass `start=today - timedelta(days=45)` to `get_prices_preferring_v2_spot` (covers ≥25 trading days for the 20-session ADV check + latest close, cutting DB rows by ~85%).
   - In `rebalance.py`, switch `_market_data` to `service.get_prices_preferring_v2_spot(symbol, start=service.today - timedelta(days=45))` (falls back to V1 automatically when V2 has no bars, preserving all existing tests while reading fresh V2 spot closes in production!).

- [ ] **Step 4: Run data & API tests to verify they pass**

Run: `python -m pytest packages/data/tests apps/api/tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/data/alembic/versions/0006_v2_query_indexes.py packages/data/data/v2/store.py packages/data/data/v2/analytics/universe_reader.py packages/data/data/v2/analytics/cache.py packages/data/data/v2/analytics/service.py packages/data/data/v2/fundamentals.py packages/data/data/service.py apps/api/app/api/v1/universe.py apps/api/app/api/v1/optimize.py apps/api/app/api/v1/risk.py apps/api/app/api/v1/portfolio.py apps/api/app/api/v1/rebalance.py packages/data/tests apps/api/tests
git commit -m "perf(api): batch V2 read queries, cache universe snapshot, fix optimize double-fetch, add DB indexes"
```

---

### Task 5: HTTP Edge/Browser Cache Headers & Frontend Request Hygiene

**Files:**
- Modify: `apps/api/app/api/v1/v2.py`
- Modify: `apps/api/app/api/v1/data.py`
- Modify: `apps/api/app/api/v1/optimize.py` (`/optimize/options`)
- Modify: `apps/api/app/api/v1/risk.py` (`/risk/options`)
- Modify: `apps/api/app/api/v1/rebalance.py` (`/rebalance/options`)
- Modify: `apps/api/app/api/v1/universe.py` (`/universe/options`)
- Modify: `apps/web/lib/api.ts:24-35,253-256,312-315`
- Modify: `apps/web/components/UniverseFilterPanel.tsx:92-137`
- Test: `apps/api/tests/test_v2_analytics_endpoint.py`
- Test: `apps/web/lib/api.test.ts` (or existing web unit test suite)

**Interfaces:**
- Produces:
  - `Cache-Control` response headers on read-only precomputed GET routes:
    - V2 read routes (`/v2/universe`, `/v2/sectors`, `/v2/analytics`, `/v2/fundamentals/{symbol}`, `/v2/coverage`, `/v2/ticker/{symbol}`): `public, max-age=300, s-maxage=1800, stale-while-revalidate=3600`
    - `/data/freshness`: `public, max-age=60, s-maxage=300, stale-while-revalidate=600`
    - `/symbols` and `/*/options`: `public, max-age=300, s-maxage=3600, stale-while-revalidate=7200`
  - `apps/web/lib/api.ts`: omit `cache: "no-store"` on `GET` requests so browser & Vercel Edge CDN honor `Cache-Control`; keep `cache: "no-store"` on non-GET (`POST`) requests.
  - `UniverseFilterPanel.tsx`: 200 ms debounce on `fetchV2Universe` effect so multi-chip clicks coalesce into 1 request.

- [ ] **Step 1: Write failing tests in `apps/api/tests/test_v2_analytics_endpoint.py`**

```python
def test_v2_read_endpoints_emit_edge_cache_control_headers(client: TestClient) -> None:
    """Precomputed read-only V2 endpoints emit public s-maxage headers for Vercel Edge caching."""
    for path in (
        "/api/v1/v2/sectors",
        "/api/v1/v2/universe",
        "/api/v1/v2/analytics?benchmark=VNINDEX&timeframe=1Y",
        "/api/v1/v2/coverage",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc and "s-maxage=" in cc

def test_freshness_emits_short_cache_control_header(client: TestClient) -> None:
    resp = client.get("/api/v1/data/freshness")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "public" in cc and "s-maxage=300" in cc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest apps/api/tests/test_v2_analytics_endpoint.py -k "cache_control" -v`
Expected: FAIL (no `cache-control` header currently set).

- [ ] **Step 3: Add `Cache-Control` headers, update `api.ts` fetch caching, and debounce `UniverseFilterPanel.tsx`**

1. Inject `response: Response` (from `fastapi`) on the read-only GET handlers in `v2.py`, `data.py` (`/symbols`, `/data/freshness`), and `/*/options` routes, setting `response.headers["Cache-Control"] = ...`. Never set public caching on `/data/refresh`, `/data/probe`, `/data/backfill`, or any `POST` route.
2. In `apps/web/lib/api.ts`:
   - In `request<T>(path, init)`: determine `const method = (init?.method ?? "GET").toUpperCase();` and only apply `cache: "no-store"` when `method !== "GET"` (let `GET` use browser default caching).
   - Remove hardcoded `cache: "no-store"` from `fetchSectorAnalytics` (line 254) and `fetchFundamentals` (line 314).
3. In `apps/web/components/UniverseFilterPanel.tsx`:
   - Debounce the `fetchV2Universe` `useEffect` by `200ms` via `setTimeout` + `clearTimeout` in cleanup (cancelling both timer and stale response via `active = false`).

- [ ] **Step 4: Run API & web tests to verify they pass**

Run: `python -m pytest apps/api/tests/test_v2_analytics_endpoint.py -v && npm --prefix apps/web run test && npm --prefix apps/web run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/v1/v2.py apps/api/app/api/v1/data.py apps/api/app/api/v1/optimize.py apps/api/app/api/v1/risk.py apps/api/app/api/v1/rebalance.py apps/api/app/api/v1/universe.py apps/web/lib/api.ts apps/web/components/UniverseFilterPanel.tsx apps/api/tests/test_v2_analytics_endpoint.py
git commit -m "perf(web,api): add Vercel CDN Cache-Control headers and debounce universe filter"
```

---

### Task 6: Workflow Schedule, Tuning Knobs & Documentation Update

**Files:**
- Modify: `.github/workflows/precompute_v2.yml:36-42,121-132`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/DATA.md`

**Interfaces:**
- Consumes: new env vars `VNOPT_V2_PRECOMPUTE_CONCURRENCY`, `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_COOLDOWN_DAYS`, `VNOPT_V2_PRECOMPUTE_REBASE_OVERLAP_SESSIONS`, `VNOPT_V2_PRECOMPUTE_RATIOS_REFRESH_DAYS` (Tasks 1–3).

- [ ] **Step 1: Update `.github/workflows/precompute_v2.yml`**

1. Change the nightly repair cron from `13 19 * * *` (7 days/week) to `13 19 * * 1-5` (Mon–Fri 19:13 UTC = Tue–Sat 02:13 ICT), eliminating pointless Saturday/Sunday night runs when the Vietnam stock market is closed.
2. Update workflow env defaults:
   - `VNOPT_V2_CLIENT_REQUESTS_PER_SECOND: ${{ vars.VNOPT_V2_CLIENT_REQUESTS_PER_SECOND || '3.0' }}`
   - `VNOPT_V2_PRECOMPUTE_CONCURRENCY: ${{ vars.VNOPT_V2_PRECOMPUTE_CONCURRENCY || '3' }}`
   - `VNOPT_V2_PRECOMPUTE_PRE_SCREEN_COOLDOWN_DAYS: ${{ vars.VNOPT_V2_PRECOMPUTE_PRE_SCREEN_COOLDOWN_DAYS || '30' }}`
   - `VNOPT_V2_PRECOMPUTE_REBASE_OVERLAP_SESSIONS: ${{ vars.VNOPT_V2_PRECOMPUTE_REBASE_OVERLAP_SESSIONS || '10' }}`
   - `VNOPT_V2_PRECOMPUTE_RATIOS_REFRESH_DAYS: ${{ vars.VNOPT_V2_PRECOMPUTE_RATIOS_REFRESH_DAYS || '7' }}`
3. Update comments in `precompute_v2.yml` to reflect the new schedule, expected runtime (~5 min incremental), and cooldown/concurrency knobs.

- [ ] **Step 2: Update `docs/CHANGELOG.md`, `docs/DEPLOYMENT.md`, and `docs/DATA.md`**

- Add a `## [2.0.2]` (or under `## [Unreleased] -> ### Performance & Supabase egress (v2.0.2)`) section in `docs/CHANGELOG.md` summarizing all egress and runtime fixes and the new `0006_v2_query_indexes` migration.
- Document the new `VNOPT_V2_PRECOMPUTE_*` workflow variables and the `alembic upgrade head` step for `0006_v2_query_indexes` in `docs/DEPLOYMENT.md` and `docs/DATA.md`.
- Note in `docs/DEPLOYMENT.md` that since all pages (including Rebalance as of v2.0.2) now read V2 prices, the legacy V1 Vercel cron in `vercel.json` (`/api/v1/data/refresh`) can optionally be removed once confirmed no V1-only tickers are used.

- [ ] **Step 3: Run the full project verification gate (`make check`)**

Run:
```bash
python -m ruff check asgi.py packages apps/api scripts
python -m mypy
python scripts/client.py check
python -m pytest
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
```
Expected: ALL commands exit 0 with zero errors.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/precompute_v2.yml docs/CHANGELOG.md docs/DEPLOYMENT.md docs/DATA.md
git commit -m "chore(v2.0.2): tune precompute workflow schedule/concurrency and update docs"
```

---

## Post-Deploy Operator Checklist (Run After Merging v2.0.2)

1. **Apply migration `0006_v2_query_indexes` against Supabase** (using the **session pooler**, port `5432`):
   ```sh
   cd packages/data && DATABASE_URL="postgresql+psycopg://...:5432/postgres?sslmode=require" python -m alembic upgrade head
   ```
2. **Redeploy API & Web on Vercel** (`vercel --prod` from repo root and `apps/web`).
3. **Trigger one manual `Precompute V2 datasets` run (`mode=incremental`)** and verify in `precompute_report.txt`:
   - Total duration drops from ~2 hours to **~3–8 minutes** (and ~15–30 seconds on an immediate second no-op run).
   - `pre_screen_rejected=1023` appears in `verify_report.txt` under `price progress states`, with `unfinished progress rows: 0`.
   - Step timings printed for every step.
4. **Verify Supabase Dashboard → Reports → Database Egress** over the next 48 hours: daily egress should drop from **~600 MB/day** to **< 15–25 MB/day**.
