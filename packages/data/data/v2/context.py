"""Composition root for the V2 adapter layer.

Builds the ordered adapter lists from :class:`V2DataSettings` and wires them into
a :class:`FailoverRunner`. The runner never reads provider order itself, so the
only place a chain lives is the config.
"""

from __future__ import annotations

from data.http import HttpClient, HttpxHttpClient
from data.settings import DEFAULT_USER_AGENT
from data.v2.config import V2DataSettings, get_v2_settings
from data.v2.interfaces import ProviderChains
from data.v2.registry import (
    build_company_profile,
    build_constituents,
    build_corporate_actions,
    build_ohlcv,
    build_ratios,
    build_sector_map,
    build_symbol_master,
    company_profile_providers,
    constituents_providers,
    corporate_actions_providers,
    ohlcv_providers,
    ratios_providers,
    sector_map_providers,
    symbol_master_providers,
)
from data.v2.runner import FailoverRunner


def build_chains(settings: V2DataSettings, http: HttpClient) -> ProviderChains:
    """Build the ordered adapter lists for every configured data type."""
    return ProviderChains(
        constituents=[
            build_constituents(pid, http, settings)
            for pid in settings.chain("constituents")
            if pid in constituents_providers.list()
        ],
        ohlcv=[
            build_ohlcv(pid, http, settings)
            for pid in settings.chain("ohlcv")
            if pid in ohlcv_providers.list()
        ],
        sector_map=[
            build_sector_map(pid, http, settings)
            for pid in settings.chain("sector_map")
            if pid in sector_map_providers.list()
        ],
        ratios=[
            build_ratios(pid, http, settings)
            for pid in settings.chain("ratios")
            if pid in ratios_providers.list()
        ],
        company_profile=[
            build_company_profile(pid, http, settings)
            for pid in settings.chain("company_profile")
            if pid in company_profile_providers.list()
        ],
        corporate_actions=[
            build_corporate_actions(pid, http, settings)
            for pid in settings.chain("corporate_actions")
            if pid in corporate_actions_providers.list()
        ],
        symbol_master=[
            build_symbol_master(pid, http, settings)
            for pid in settings.chain("symbol_master")
            if pid in symbol_master_providers.list()
        ],
    )


def build_default_client(settings: V2DataSettings) -> HttpxHttpClient:
    """Build the shared HTTP client (per-call timeout; runner owns retries)."""
    return HttpxHttpClient(
        user_agent=DEFAULT_USER_AGENT,
        timeout_seconds=settings.timeout_seconds,
        rate_limit_per_minute=settings.client_rate_limit_per_minute,
        requests_per_second=settings.client_requests_per_second,
        retry_attempts=settings.client_retry_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
        rate_limit_retry_attempts=settings.client_rate_limit_retry_attempts,
        rate_limit_backoff_seconds=settings.client_rate_limit_backoff_seconds,
        cooldown_seconds=float(settings.blocked_cooldown_seconds),
    )


class V2DataContext:
    """Owns the HTTP client, the adapter chains and the failover runner."""

    def __init__(
        self,
        settings: V2DataSettings | None = None,
        *,
        http: HttpClient | None = None,
    ) -> None:
        self.settings = settings or get_v2_settings()
        self.http = http or build_default_client(self.settings)
        self.chains = build_chains(self.settings, self.http)
        self.runner = FailoverRunner(settings=self.settings, chains=self.chains)


__all__ = ["V2DataContext", "build_chains", "build_default_client"]
