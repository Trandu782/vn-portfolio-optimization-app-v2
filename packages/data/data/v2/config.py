"""Configuration for the V2 provider adapter layer.

The four failover chains live here and nowhere else. Each is a comma-separated
priority list of provider ids; an id with no registered adapter is ignored, so a
typo cannot crash a chain. Override any chain with the matching ``VNOPT_V2_``
environment variable without a code change.

Verification policy: the *active* defaults below contain only providers verified
against a real recorded response from the current environment. The full spec
order (``docs/V2_SPEC.md`` section 7, plus ``ssi_iboard`` for OHLCV) is kept in
:data:`SPEC_CHAIN` for reference. Unverified providers are implemented and
registered, but stay out of the active chains until they are confirmed on the
deployed / GitHub runner; enable them by setting the env var once verified.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Full failover order from docs/V2_SPEC.md section 7, plus ssi_iboard for OHLCV.
#: ``ssi_statistics`` is the SSI iBoard ``statistics`` service: adjusted OHLCV with
#: matched volume/value, bulk ICB level-2 sectors, ratios, company profile,
#: corporate actions and the symbol master. The KBS tradable-stock list is merged
#: into the SSI symbol master by ``data.v2.symbols.merge_symbol_master`` (not a
#: chain member), so ``symbol_master`` lists only the V2 adapter.
SPEC_CHAIN: dict[str, tuple[str, ...]] = {
    "constituents": ("kbs", "vci"),
    "ohlcv": ("ssi_statistics", "vci", "kbs", "dnse", "ssi_iboard"),
    "sector_map": ("ssi_statistics", "vci", "kbs"),
    "ratios": ("ssi_statistics", "kbs", "vci", "tcbs"),
    "company_profile": ("ssi_statistics",),
    "corporate_actions": ("ssi_statistics",),
    "symbol_master": ("ssi_statistics", "kbs"),
}

#: Providers verified against a real recorded response from this environment.
#: Everything else is "unreachable from this environment, unverified" and is
#: excluded from the active defaults. Local results do not prove cloud-IP access;
#: re-run scripts/probe_v2.py on the GitHub runner before promoting a provider.
#: The SSI ``statistics`` endpoints are verified from recorded fixtures here, but
#: their cloud-IP reachability (behind Cloudflare) is still unconfirmed.
VERIFIED_PROVIDERS: dict[str, tuple[str, ...]] = {
    "constituents": ("kbs",),
    "ohlcv": ("ssi_statistics", "vci", "kbs"),
    "sector_map": ("ssi_statistics",),
    "ratios": ("ssi_statistics",),
    "company_profile": ("ssi_statistics",),
    "corporate_actions": ("ssi_statistics",),
    "symbol_master": ("ssi_statistics", "kbs"),
}


def _order(data_type: str) -> str:
    """Join the verified providers for ``data_type`` into a config string."""
    return ",".join(VERIFIED_PROVIDERS.get(data_type, ()))


class V2DataSettings(BaseSettings):
    """Failover chains and tunables for the V2 adapter runner."""

    model_config = SettingsConfigDict(
        env_prefix="VNOPT_V2_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    constituents_order: str = _order("constituents")
    ohlcv_order: str = _order("ohlcv")
    sector_map_order: str = _order("sector_map")
    ratios_order: str = _order("ratios")
    company_profile_order: str = _order("company_profile")
    corporate_actions_order: str = _order("corporate_actions")
    symbol_master_order: str = _order("symbol_master")

    timeout_seconds: float = 15.0
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    retry_jitter_seconds: float = 0.5
    circuit_breaker_failures: int = 5
    circuit_breaker_cooldown_seconds: int = 300
    blocked_cooldown_seconds: int = 900
    cache_ttl_seconds: float = 60.0

    # The runner owns retries and per-data-type rate limiting for the API/sync path.
    # The precompute path calls the adapters directly, so the shared HTTP client
    # applies an explicit, conservative requests-per-second cap (0.5 rps ~ 30/min by
    # default) plus its own 429 backoff and 403 cooldown. All three are configurable
    # per environment; client_rate_limit_per_minute stays as a very high safety net.
    client_retry_attempts: int = 1
    client_rate_limit_per_minute: int = 10_000
    client_requests_per_second: float = 0.5
    client_rate_limit_retry_attempts: int = 5
    client_rate_limit_backoff_seconds: float = 2.0

    ohlcv_rate_limit_per_minute: int = 20
    constituents_rate_limit_per_minute: int = 20
    sector_map_rate_limit_per_minute: int = 20
    ratios_rate_limit_per_minute: int = 10
    company_profile_rate_limit_per_minute: int = 10
    corporate_actions_rate_limit_per_minute: int = 10
    symbol_master_rate_limit_per_minute: int = 10
    default_rate_limit_per_minute: int = 20

    # Precompute pipeline tunables. The start date is a string because pydantic-
    # settings reads environment variables as text; the service parses it once.
    backfill_start_date: str = "2023-01-01"
    precompute_window_sessions: int = 20
    precompute_batch_size: int = 50
    precompute_pre_screen_enabled: bool = True
    precompute_pre_screen_days: int = 30
    #: Minimum 30-session median volume (shares) a ticker must clear before the
    #: per-ticker backfill fetches run. This is a **backfill-cost floor, not a
    #: liquidity filter**: it only drops effectively untraded/suspended names so the
    #: backfill stays affordable, and it is deliberately low (10k shares) so the
    #: "All Stocks" universe is not silently filtered. Set to 0 to disable.
    precompute_pre_screen_min_median_volume: int = 10_000

    #: How many *trading sessions* the benchmark series (`VNINDEX`) and the overall
    #: price series may lag the resolved target before the quality gate fails. ``0``
    #: (default) keeps the strict check — any missing session is an error. Raise it to
    #: ``1`` (``VNOPT_V2_PRECOMPUTE_STALENESS_TOLERANCE_SESSIONS=1``) only while an
    #: upstream feed is known to publish a session late, e.g. right after an exchange
    #: holiday that the illustrative ``MarketRules.trading_holidays`` set does not know:
    #: the run then logs a warning instead of failing `quality: stale dataset`. An
    #: absent series (no bars at all) is never tolerated.
    precompute_staleness_tolerance_sessions: int = 0

    #: Incremental re-base detection. SSI's adjusted closes change retroactively
    #: when a new corporate action's ex-date lands, so an incremental fetch that
    #: only grabs new dates would leave old rows stale. When a ticker has new
    #: dates the price step re-fetches this many sessions of stored tail together
    #: with the new dates, compares the overlapping adjusted closes and, on a
    #: difference beyond ``precompute_rebase_tolerance``, re-fetches the whole
    #: history and replaces the old rows in the same run. Detection uses prices
    #: only (never the corporate-actions feed, which omits some bonus issues).
    precompute_rebase_overlap_sessions: int = 40
    #: Relative tolerance for the overlap comparison (0.0001 = 0.01%).
    precompute_rebase_tolerance: float = 0.0001

    def chain(self, data_type: str) -> list[str]:
        """Return the configured provider ids for ``data_type`` in priority order."""
        orders = {
            "constituents": self.constituents_order,
            "ohlcv": self.ohlcv_order,
            "sector_map": self.sector_map_order,
            "ratios": self.ratios_order,
            "company_profile": self.company_profile_order,
            "corporate_actions": self.corporate_actions_order,
            "symbol_master": self.symbol_master_order,
        }
        raw = orders.get(data_type, "")
        return [part.strip() for part in raw.split(",") if part.strip()]

    def rate_limit_for(self, data_type: str) -> int:
        """Return the per-minute request budget for ``data_type``."""
        limits = {
            "constituents": self.constituents_rate_limit_per_minute,
            "ohlcv": self.ohlcv_rate_limit_per_minute,
            "sector_map": self.sector_map_rate_limit_per_minute,
            "ratios": self.ratios_rate_limit_per_minute,
            "company_profile": self.company_profile_rate_limit_per_minute,
            "corporate_actions": self.corporate_actions_rate_limit_per_minute,
            "symbol_master": self.symbol_master_rate_limit_per_minute,
        }
        return limits.get(data_type, self.default_rate_limit_per_minute)


@lru_cache(maxsize=1)
def get_v2_settings() -> V2DataSettings:
    """Return the process-wide V2 settings singleton."""
    return V2DataSettings()


__all__ = [
    "SPEC_CHAIN",
    "VERIFIED_PROVIDERS",
    "V2DataSettings",
    "get_v2_settings",
]
