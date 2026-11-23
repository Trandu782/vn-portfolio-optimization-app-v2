# 0003. Parallel V2 provider adapter layer

- Status: Accepted
- Date: 2026-11-22

## Context

V2 needs four new data types (index constituents, ICB sector map, adjusted OHLCV
and financial ratios) with a different failover order per data type
(`docs/V2_SPEC.md` section 7). V1 already ships a mature `DataProvider` stack: one
monolithic protocol, one global `PROVIDER_ORDER`, a `FallbackProvider` and five
anonymous providers. It has no sector map, no ratios, no `matched_volume`, no
per-data-type chains and no response cache.

V1 is live and must not change behaviour.

## Decision

Build a **parallel, additive layer** under `packages/data/data/v2/`:

- **Schemas** (`v2/schemas.py`): `IndexConstituents`, `SectorMap`,
  `AdjustedOHLCV`, `FinancialRatios`, `CompanyProfile`.
- **One adapter interface per data type** (`v2/interfaces.py`): `ConstituentsProvider`,
  `SectorMapProvider` (with `get_sector_map_all()` bulk plus a per-ticker fallback
  in the runner), `OHLCVProvider` (with `get_index_ohlcv` for VNINDEX/VN30/VN100),
  `RatiosProvider`, and a `CompanyProfileProvider` **stub** (schema + interface +
  registry; concrete adapters deferred to the V2a precompute step).
- **One config file** (`v2/config.py`) owns the four chains and every tunable
  (timeout, retry/backoff/jitter, per-data-type rate limits, cache TTL, circuit
  breaker, blocked cooldown). The runner never hardcodes order.
- **Runner** (`v2/runner.py`): try providers in order, retry with exponential
  backoff plus jitter, in-memory TTL cache, per-data-type rate limiting, health
  tracking (last success/failure, consecutive failures, cooldown) and request
  logging. HTTP 429 is retryable; HTTP 403 becomes `BlockedError` with no retry
  and an immediate cooldown.
- **Adapters**: KBS (constituents, OHLCV, ratios), VCI (OHLCV, sector map, ratios,
  constituents), DNSE (OHLCV), SSI iBoard (OHLCV fallback), TCBS (ratios, last
  resort). Each lives in its own file; every endpoint is called anonymously.

### Verified vs unverified providers

The active chains default to providers **verified against a real recorded
response** from the environment that ran the probe. From 2026-11-22: KBS OHLCV +
constituents and VCI OHLCV are verified; the ratios, sector-map, DNSE, SSI iBoard
and TCBS endpoints could not be verified (Cloudflare 403, HTML SPA shells,
`INVALID_TOKEN`, or 404) and are therefore implemented but **excluded** from the
active defaults. Enable them by setting `VNOPT_V2_<TYPE>_ORDER` once
`scripts/probe_v2.py` confirms them on the deployed / GitHub runner. Failures on
a local PC are "unreachable from this environment, unverified", never
"deprecated"; local results do not prove cloud-IP access.

### Intentional duplication with V1

The V2 adapters deliberately **duplicate some V1 provider code** (the small
`pick`/`coerce_*` helpers and the HTTP status classification). Importing V1
provider modules from V2 would couple the two layers and risk changing V1
behaviour, so the overlap is kept intentionally small and local. A future
refactor may share it once V1 is retired.

## Consequences

- V1 stays byte-for-byte unchanged; V2 is opt-in via `data.v2`.
- Adding a provider is one file plus one registration per data type it serves.
- The active chains are honest about what is verified; unverified adapters are
  code-and-tests only until a probe on the target network promotes them.
- The GitHub Actions workflow uploads the report as an artifact and performs no
  git operations (the project is not on GitHub yet).
