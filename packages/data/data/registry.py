"""Registry of anonymous data providers.

Concrete providers register themselves with ``@data_providers.register(...)`` from
``data.providers``. Adding a new source (for example VCI or KBS) is therefore one
new provider file plus one registration - the failover chain reads the registry
and never needs an ``if/else`` change.

``build_provider`` turns a registered id into a live provider for a given HTTP
client, which keeps the production client and the recorded-fixture client
interchangeable.
"""

from __future__ import annotations

from typing import Protocol, cast

from pydantic import BaseModel

from core.registry import Registry
from data.http import HttpClient
from data.interfaces import DataProvider
from data.settings import DataSettings


class ProviderParams(BaseModel):
    """Built-in anonymous providers take no user options."""


class ProviderFactory(Protocol):
    """Callable shape of a provider class in the registry."""

    def __call__(
        self, http: HttpClient, settings: DataSettings | None = None
    ) -> DataProvider: ...


#: Every registered provider, keyed by its stable id (kbs, vci, dnse, tcbs, ssi_iboard).
data_providers: Registry[DataProvider] = Registry()


def build_provider(
    provider_id: str,
    http: HttpClient,
    settings: DataSettings | None = None,
) -> DataProvider:
    """Instantiate the provider registered under ``provider_id``.

    Raises:
        KeyError: When no provider is registered under that id.
    """
    cls = data_providers.get(provider_id)
    factory = cast(ProviderFactory, cls)
    return factory(http, settings)
