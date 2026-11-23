"""Failover runner for the V2 adapters.

Responsibilities (all in one small class so callers never see provider order):

- try providers in priority order and fail over on any error;
- retry with exponential backoff plus jitter (never retry auth or 403 blocks);
- treat ``RateLimitError`` (HTTP 429) as retryable and ``BlockedError`` (HTTP
  403) as "no retry, cool down";
- enforce a per-data-type rate limit;
- keep an in-memory TTL response cache;
- track provider health (last success/failure, consecutive failures, cooldown);
- log which provider served every request;
- raise a clear ``AllProvidersFailedError`` (or ``NoProvidersConfiguredError``)
  when nothing can serve the request.

Per-call timeouts come from the injected ``HttpClient``; the runner owns retries
and throttling so the two never double up.
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

from data.errors import AllProvidersFailedError, AuthRequiredError, ProviderError
from data.v2.config import V2DataSettings
from data.v2.errors import BlockedError, NoProvidersConfiguredError
from data.v2.interfaces import ProviderChains, SectorMapProvider
from data.v2.schemas import (
    AdjustedOHLCV,
    CompanyProfile,
    CorporateAction,
    FinancialRatios,
    IndexConstituents,
    SectorMap,
    SymbolMaster,
)

#: Injectable clock/sleep/monotonic hooks so tests need no real time.
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
Monotonic = Callable[[], float]

#: Rolling window (seconds) for the per-data-type rate limiter.
_RATE_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class Served[T]:
    """A served value plus which provider produced it (and whether it was cached)."""

    provider: str
    value: T
    from_cache: bool = False


@dataclass
class ProviderHealth:
    """Mutable health state for one (data type, provider) pair."""

    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
    last_error_type: str | None = None
    cooldown_until: datetime | None = None


class _HasId(Protocol):
    """Structural guarantee that every adapter exposes an ``id``."""

    id: str


class FailoverRunner:
    """Serve one data type at a time from the first healthy adapter."""

    def __init__(
        self,
        *,
        settings: V2DataSettings,
        chains: ProviderChains,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        monotonic: Monotonic | None = None,
        rng: random.Random | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._chains = chains
        self._clock: Clock = clock or (lambda: datetime.now(UTC))
        self._sleep: Sleeper = sleeper or time.sleep
        self._monotonic: Monotonic = monotonic or time.monotonic
        self._rng: random.Random = rng or random.Random()
        self._log = logger or logging.getLogger("data.v2.runner")
        self._health: dict[str, ProviderHealth] = {}
        self._rate: dict[str, deque[float]] = {}
        self._cache: dict[str, tuple[float, str, Any]] = {}

    # -- typed public surface ----------------------------------------------
    def constituents(self, index_code: str) -> Served[IndexConstituents]:
        """Return an index's members from the first healthy provider."""
        code = index_code.upper()
        return self._execute(
            "constituents",
            self._chains.constituents,
            cache_key=f"constituents:{code}",
            call=lambda provider: provider.get_index_constituents(code),
        )

    def ohlcv(self, symbol: str, start: date, end: date) -> Served[list[AdjustedOHLCV]]:
        """Return daily bars for ``symbol`` from the first healthy provider."""
        code = symbol.upper()
        return self._execute(
            "ohlcv",
            self._chains.ohlcv,
            cache_key=f"ohlcv:{code}:{start.isoformat()}:{end.isoformat()}",
            call=lambda provider: provider.get_ohlcv(code, start, end),
        )

    def index_ohlcv(
        self, index_code: str, start: date, end: date
    ) -> Served[list[AdjustedOHLCV]]:
        """Return daily bars for an index (VNINDEX, VN30, VN100)."""
        code = index_code.upper()
        return self._execute(
            "ohlcv",
            self._chains.ohlcv,
            cache_key=f"index_ohlcv:{code}:{start.isoformat()}:{end.isoformat()}",
            call=lambda provider: provider.get_index_ohlcv(code, start, end),
        )

    def sector_map(self, ticker: str) -> Served[SectorMap]:
        """Return one ticker's sector mapping from the first healthy provider."""
        code = ticker.upper()
        return self._execute(
            "sector_map",
            self._chains.sector_map,
            cache_key=f"sector_map:{code}",
            call=lambda provider: provider.get_sector_map(code),
        )

    def sector_map_all(self, tickers: Sequence[str]) -> Served[list[SectorMap]]:
        """Return the sector mapping for every ticker, with per-ticker fallback."""
        universe = [ticker.upper() for ticker in tickers]
        return self._execute(
            "sector_map",
            self._chains.sector_map,
            cache_key="sector_map_all:" + ",".join(sorted(universe)),
            call=lambda provider: self._sector_map_all_for(provider, universe),
        )

    def ratios(self, ticker: str) -> Served[list[FinancialRatios]]:
        """Return normalized financial ratios from the first healthy provider."""
        code = ticker.upper()
        return self._execute(
            "ratios",
            self._chains.ratios,
            cache_key=f"ratios:{code}",
            call=lambda provider: provider.get_ratios(code),
        )

    def company_profile(self, ticker: str) -> Served[CompanyProfile]:
        """Return company reference data from the first healthy provider."""
        code = ticker.upper()
        return self._execute(
            "company_profile",
            self._chains.company_profile,
            cache_key=f"company_profile:{code}",
            call=lambda provider: provider.get_company_profile(code),
        )

    def corporate_actions(
        self, ticker: str, start: date, end: date
    ) -> Served[list[CorporateAction]]:
        """Return a ticker's DIV/ISS corporate actions from the first healthy provider."""
        code = ticker.upper()
        return self._execute(
            "corporate_actions",
            self._chains.corporate_actions,
            cache_key=f"corporate_actions:{code}:{start.isoformat()}:{end.isoformat()}",
            call=lambda provider: provider.get_corporate_actions(code, start, end),
        )

    def symbol_master(self) -> Served[list[SymbolMaster]]:
        """Return the bulk ticker -> exchange security master from the first provider."""
        return self._execute(
            "symbol_master",
            self._chains.symbol_master,
            cache_key="symbol_master",
            call=lambda provider: provider.get_symbol_master(),
        )

    @staticmethod
    def _sector_map_all_for(
        provider: SectorMapProvider, tickers: Sequence[str]
    ) -> list[SectorMap]:
        """Use a provider's bulk map when available, else call it per ticker."""
        if provider.supports_bulk_sector_map:
            return provider.get_sector_map_all()
        return [provider.get_sector_map(ticker) for ticker in tickers]

    # -- execution core ----------------------------------------------------
    def _execute[T, P](
        self,
        data_type: str,
        providers: Sequence[P],
        *,
        cache_key: str,
        call: Callable[[P], T],
    ) -> Served[T]:
        """Run ``call`` against providers in order, with retry, cache and failover."""
        cached = self._cache_get(cache_key)
        if cached is not None:
            origin, value = cached
            self._log.info("%s cache hit (origin=%s) key=%s", data_type, origin, cache_key)
            return Served(provider=origin, value=value, from_cache=True)
        if not providers:
            raise NoProvidersConfiguredError(
                f"no V2 providers configured for {data_type!r}; set "
                f"VNOPT_V2_{data_type.upper()}_ORDER to a verified provider list"
            )
        attempts = max(1, self._settings.retry_attempts)
        failures: list[ProviderError] = []
        for provider in providers:
            provider_id = cast(_HasId, provider).id
            health = self._health.setdefault(
                self._health_key(data_type, provider_id), ProviderHealth()
            )
            if self._in_cooldown(health, self._clock()):
                self._log.info("%s provider %s skipped (cooldown)", data_type, provider_id)
                continue
            last_error: ProviderError | None = None
            for attempt in range(1, attempts + 1):
                self._respect_rate_limit(data_type)
                try:
                    value = call(provider)
                except (BlockedError, AuthRequiredError) as exc:
                    last_error = exc
                    break
                except Exception as exc:
                    last_error = self._as_provider_error(exc, provider_id)
                    if attempt < attempts:
                        self._sleep(self._delay(attempt))
                else:
                    self._record_success(health)
                    self._cache_put(cache_key, provider_id, value)
                    self._log.info("%s served by %s key=%s", data_type, provider_id, cache_key)
                    return Served(provider=provider_id, value=value)
            if last_error is None:
                continue
            self._record_failure(health, last_error)
            failures.append(last_error)
            self._log.warning(
                "%s provider %s failed (%s): %s",
                data_type,
                provider_id,
                last_error.error_type,
                last_error,
            )
        raise AllProvidersFailedError(
            f"all V2 providers failed for {data_type} (key={cache_key})", failures=failures
        )

    # -- health / cooldown -------------------------------------------------
    @staticmethod
    def _health_key(data_type: str, provider_id: str) -> str:
        return f"{data_type}:{provider_id}"

    @staticmethod
    def _as_provider_error(exc: Exception, provider_id: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        return ProviderError(
            f"unexpected {type(exc).__name__}: {exc}", provider=provider_id, cause=exc
        )

    def _delay(self, attempt: int) -> float:
        """Exponential backoff plus jitter before the next attempt."""
        base: float = self._settings.retry_backoff_seconds * (2 ** (attempt - 1))
        span = max(0.0, self._settings.retry_jitter_seconds)
        jitter: float = float(self._rng.uniform(0.0, span))
        return base + jitter

    def _record_success(self, health: ProviderHealth) -> None:
        health.consecutive_failures = 0
        health.cooldown_until = None
        health.last_success_at = self._clock()
        health.last_error = None
        health.last_error_type = None

    def _record_failure(self, health: ProviderHealth, error: ProviderError) -> None:
        now = self._clock()
        health.consecutive_failures += 1
        health.last_failure_at = now
        health.last_error = str(error)
        health.last_error_type = error.error_type
        if isinstance(error, BlockedError):
            health.cooldown_until = now + timedelta(
                seconds=self._settings.blocked_cooldown_seconds
            )
        elif health.consecutive_failures >= self._settings.circuit_breaker_failures:
            health.cooldown_until = now + timedelta(
                seconds=self._settings.circuit_breaker_cooldown_seconds
            )

    @staticmethod
    def _in_cooldown(health: ProviderHealth, now: datetime) -> bool:
        if health.cooldown_until is None:
            return False
        if now >= health.cooldown_until:
            health.cooldown_until = None  # half-open: allow one trial request
            return False
        return True

    # -- rate limiting -----------------------------------------------------
    def _respect_rate_limit(self, data_type: str) -> None:
        """Block until a slot is free in this data type's rolling minute window."""
        limit = self._settings.rate_limit_for(data_type)
        if limit <= 0:
            return
        recent: deque[float] = self._rate.setdefault(data_type, deque())
        now = self._monotonic()
        while recent and now - recent[0] >= _RATE_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= limit:
            wait = _RATE_WINDOW_SECONDS - (now - recent[0])
            if wait > 0:
                self._sleep(wait)
            now = self._monotonic()
            while recent and now - recent[0] >= _RATE_WINDOW_SECONDS:
                recent.popleft()
        recent.append(self._monotonic())

    # -- cache -------------------------------------------------------------
    def _cache_get(self, key: str) -> tuple[str, Any] | None:
        if self._settings.cache_ttl_seconds <= 0:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        expiry, provider_id, value = entry
        if self._monotonic() >= expiry:
            self._cache.pop(key, None)
            return None
        return provider_id, value

    def _cache_put(self, key: str, provider_id: str, value: Any) -> None:
        if self._settings.cache_ttl_seconds <= 0:
            return
        self._cache[key] = (
            self._monotonic() + self._settings.cache_ttl_seconds,
            provider_id,
            value,
        )

    # -- diagnostics -------------------------------------------------------
    def health(self, data_type: str | None = None) -> dict[str, ProviderHealth]:
        """Return tracked health, optionally filtered to one data type."""
        if data_type is None:
            return dict(self._health)
        prefix = f"{data_type}:"
        return {
            key[len(prefix) :]: state
            for key, state in self._health.items()
            if key.startswith(prefix)
        }

    def clear_cache(self) -> None:
        """Drop every cached response (tests / manual refresh)."""
        self._cache.clear()


__all__ = ["FailoverRunner", "ProviderHealth", "Served"]

