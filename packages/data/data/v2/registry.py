"""Registries of V2 adapters, one per data type.

Adding a provider is one new file plus one registration per data type it
supports. The typed ``build_*`` helpers turn a registered id into a live adapter
for a given HTTP client, so production and recorded-fixture clients are
interchangeable in tests, exactly like the V1 registry.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from pydantic import BaseModel

from core.registry import Registry
from data.http import HttpClient
from data.v2.config import V2DataSettings
from data.v2.interfaces import (
    CompanyProfileProvider,
    ConstituentsProvider,
    CorporateActionsProvider,
    OHLCVProvider,
    RatiosProvider,
    SectorMapProvider,
    SymbolMasterProvider,
)


class ProviderParams(BaseModel):
    """Built-in anonymous V2 adapters take no user options."""


class ProviderFactory[T](Protocol):
    """Callable shape of a registered V2 adapter class."""

    def __call__(self, http: HttpClient, settings: V2DataSettings | None = None) -> T: ...


constituents_providers: Registry[ConstituentsProvider] = Registry()
sector_map_providers: Registry[SectorMapProvider] = Registry()
ohlcv_providers: Registry[OHLCVProvider] = Registry()
ratios_providers: Registry[RatiosProvider] = Registry()
company_profile_providers: Registry[CompanyProfileProvider] = Registry()
corporate_actions_providers: Registry[CorporateActionsProvider] = Registry()
symbol_master_providers: Registry[SymbolMasterProvider] = Registry()

_REGISTRIES: tuple[Registry[Any], ...] = (
    constituents_providers,
    sector_map_providers,
    ohlcv_providers,
    ratios_providers,
    company_profile_providers,
    corporate_actions_providers,
    symbol_master_providers,
)


def _build[T](
    registry: Registry[T],
    provider_id: str,
    http: HttpClient,
    settings: V2DataSettings | None,
) -> T:
    """Instantiate the adapter registered under ``provider_id`` in ``registry``."""
    factory = cast(ProviderFactory[T], registry.get(provider_id))
    return factory(http, settings)


def build_constituents(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> ConstituentsProvider:
    """Build the constituents adapter registered under ``provider_id``."""
    return _build(constituents_providers, provider_id, http, settings)


def build_sector_map(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> SectorMapProvider:
    """Build the sector-map adapter registered under ``provider_id``."""
    return _build(sector_map_providers, provider_id, http, settings)


def build_ohlcv(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> OHLCVProvider:
    """Build the OHLCV adapter registered under ``provider_id``."""
    return _build(ohlcv_providers, provider_id, http, settings)


def build_ratios(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> RatiosProvider:
    """Build the ratios adapter registered under ``provider_id``."""
    return _build(ratios_providers, provider_id, http, settings)


def build_company_profile(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> CompanyProfileProvider:
    """Build the company-profile adapter registered under ``provider_id``."""
    return _build(company_profile_providers, provider_id, http, settings)


def build_corporate_actions(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> CorporateActionsProvider:
    """Build the corporate-actions adapter registered under ``provider_id``."""
    return _build(corporate_actions_providers, provider_id, http, settings)


def build_symbol_master(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> SymbolMasterProvider:
    """Build the symbol-master adapter registered under ``provider_id``."""
    return _build(symbol_master_providers, provider_id, http, settings)


def registered_ids() -> list[str]:
    """Return every registered V2 provider id in stable registration order."""
    seen: dict[str, None] = {}
    for registry in _REGISTRIES:
        for provider_id in registry.list():
            seen.setdefault(provider_id, None)
    return list(seen)


def build_adapter(
    provider_id: str, http: HttpClient, settings: V2DataSettings | None = None
) -> object:
    """Build any registered adapter by id, regardless of data type (probe use).

    Raises:
        KeyError: When no registry knows ``provider_id``.
    """
    for registry in _REGISTRIES:
        if provider_id in registry.list():
            factory = cast(ProviderFactory[object], registry.get(provider_id))
            return factory(http, settings)
    raise KeyError(f"Unknown V2 provider {provider_id!r}")


__all__ = [
    "ProviderParams",
    "build_adapter",
    "build_company_profile",
    "build_constituents",
    "build_corporate_actions",
    "build_ohlcv",
    "build_ratios",
    "build_sector_map",
    "build_symbol_master",
    "company_profile_providers",
    "constituents_providers",
    "corporate_actions_providers",
    "ohlcv_providers",
    "ratios_providers",
    "registered_ids",
    "sector_map_providers",
    "symbol_master_providers",
]
