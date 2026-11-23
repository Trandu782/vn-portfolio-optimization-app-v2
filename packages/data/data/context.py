"""Composition root wiring settings -> engine -> providers -> services.

The API imports :func:`get_context`; tests call :func:`set_context` with a context
that uses a temporary database and a recorded-fixture HTTP client. Providers are
built from the registry in ``PROVIDER_ORDER``, so an unregistered id is simply
skipped and a newly registered provider needs no change here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from data.db.base import create_engine_for, create_session_factory
from data.fallback import FallbackProvider
from data.http import HttpClient, HttpxHttpClient
from data.registry import build_provider, data_providers
from data.service import DataService
from data.settings import DataSettings, get_settings
from data.sync import SyncService


class DataContext:
    """Owns the engine, the failover chain and the two services."""

    def __init__(
        self,
        settings: DataSettings,
        *,
        http: HttpClient | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.settings = settings
        self.engine: Engine = create_engine_for(settings.database_url)
        self.session_factory: sessionmaker[Session] = create_session_factory(self.engine)
        client = http or HttpxHttpClient(
            user_agent=settings.user_agent,
            timeout_seconds=settings.provider_timeout_seconds,
            rate_limit_per_minute=settings.provider_rate_limit_per_minute,
            retry_attempts=settings.retry_attempts,
            backoff_seconds=settings.retry_backoff_seconds,
        )
        registered = set(data_providers.list())
        provider_ids = [pid for pid in settings.provider_ids if pid in registered]
        self.providers = [build_provider(pid, client, settings) for pid in provider_ids]
        self.fallback = FallbackProvider(
            self.providers, settings=settings, order=provider_ids, today_provider=today_provider
        )
        self.sync = SyncService(
            session_factory=self.session_factory,
            fallback=self.fallback,
            settings=settings,
            today_provider=today_provider,
        )
        self.service = DataService(
            session_factory=self.session_factory,
            sync_service=self.sync,
            fallback=self.fallback,
            settings=settings,
            today_provider=today_provider,
        )


_context: DataContext | None = None


def get_context() -> DataContext:
    """Return the process-wide context, building it on first use."""
    global _context
    if _context is None:
        _context = DataContext(get_settings())
    return _context


def set_context(context: DataContext | None) -> None:
    """Replace the process-wide context (tests / scripts)."""
    global _context
    _context = context
