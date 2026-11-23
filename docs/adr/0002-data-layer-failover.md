# 0002. Anonymous data providers behind a failover chain

- Status: Accepted
- Date: 2026-11-21

## Context

The optimizer needs Vietnamese daily prices without making the user create an
account with any data vendor. DNSE, TCBS and SSI iBoard expose public, anonymous
endpoints, but they are unofficial and undocumented: they drift, rate-limit, and
sometimes start requiring a token (for example DNSE now answers `INVALID_TOKEN`
to anonymous callers on some routes). No single source can be trusted to be up.

SSI FastConnect is intentionally excluded: it requires a consumer id and secret
and therefore violates the "works with no credentials" rule.

## Decision

- `DataProvider` is a `Protocol` (`data/interfaces.py`). Providers live in one file
  each and register with `@data_providers.register(...)`; VCI and KBS were added
  later the same way - one file plus one registration each.
- A `FallbackProvider` tries providers in `PROVIDER_ORDER`, retries with backoff,
  validates every response, and fails over on any error (network, timeout, HTTP,
  auth, rate limit, empty, schema, stale). A circuit breaker skips a provider that
  keeps failing.
- The provider order is set from `scripts/probe_providers.py` / the protected
  `GET /api/v1/data/probe`, run on the hosted environment.
- Every row stores its `source`. A source change for a symbol triggers an overlap
  comparison; a close difference beyond tolerance replaces the series rather than
  splicing two providers.
- Persistence is SQLAlchemy 2 + Alembic, accessed only through repositories behind
  `Protocol` interfaces.

## Consequences

- The app keeps working when one (or two) providers are blocked, and degrades to a
  clearly-flagged stale cache when all are down.
- Providers are isolated and small; a schema change is a one-file fix that raises a
  clear error instead of corrupting data.
- The anonymous endpoints can disappear entirely; the probe endpoint exists so the
  order can be re-evaluated on the deployed network, and the architecture makes
  adding an alternative source cheap.
- Prices are raw (unadjusted) today; `scripts/check_adjustment.py` documents how to
  detect a provider that starts returning adjusted data.
