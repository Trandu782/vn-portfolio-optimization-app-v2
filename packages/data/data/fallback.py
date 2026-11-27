"""Failover chain over registered providers.

:class:`FallbackProvider` tries providers in ``PROVIDER_ORDER`` (from settings),
retries each one with backoff, then moves to the next on *any* failure. A simple
circuit breaker skips a provider that keeps failing for a cooldown window so a
down source does not slow every request.

Every result records which provider served it and the failovers that happened,
and each response is validated (:mod:`data.validation`) and checked for staleness
before it is accepted. The chain never splices two providers into one series: it
returns one provider's rows and the sync job decides (via
:mod:`data.consistency`) whether to replace or flag a symbol whose history came
from another source.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from core.market_rules import DEFAULT_MARKET_RULES
from data.calendar import last_trading_day, trading_days_between
from data.errors import (
    AllProvidersFailedError,
    AuthRequiredError,
    DataValidationError,
    ProviderError,
    SchemaError,
    StaleDataError,
)
from data.interfaces import DataProvider
from data.models import FailoverEvent, PriceBar, ProviderStatus, SymbolInfo
from data.settings import DataSettings
from data.validation import canonicalize_price_bars

#: Clock and sleep are injectable so circuit-breaker tests need no real time.
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


@dataclass
class ProviderRuntime:
    """Mutable health state for one provider in the chain."""

    provider: DataProvider
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    cooldown_until: datetime | None = None
    last_error: str | None = None
    last_error_type: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


@dataclass
class FallbackResult[T]:
    """A successful chain result: which provider served it and what was skipped."""

    provider: str
    value: T
    failovers: list[FailoverEvent] = field(default_factory=list)


_SAFE_ERROR_SUMMARIES: dict[str, str] = {
    "auth": "provider requires authentication",
    "rate_limit": "provider rate limited",
    "timeout": "provider request timed out",
    "network": "provider network error",
    "http": "provider HTTP error",
    "schema": "provider returned unexpected payload",
    "empty": "provider returned no data",
    "stale": "provider returned stale data",
}


def _safe_error_summary(error_type: str | None, message: str | None) -> str | None:
    """Return a short, non-sensitive summary suitable for public status endpoints."""
    if message is None:
        return None
    if message.startswith("unexpected ") or "://" in message:
        return _SAFE_ERROR_SUMMARIES.get(error_type or "", "provider error")
    cleaned = " ".join(message.split())
    return cleaned[:160]


class FallbackProvider:
    """Serve data from the first healthy provider in priority order."""

    def __init__(
        self,
        providers: Sequence[DataProvider],
        *,
        settings: DataSettings,
        order: Sequence[str] | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._settings = settings
        self._clock: Clock = clock or (lambda: datetime.now(UTC))
        self._sleep: Sleeper = sleeper or time.sleep
        self._today = today_provider or date.today
        self._runtimes: dict[str, ProviderRuntime] = {
            provider.id: ProviderRuntime(provider) for provider in providers
        }
        configured = list(order if order is not None else settings.provider_ids)
        self._order = [pid for pid in configured if pid in self._runtimes]
        # Any provider that is not in the explicit order still gets a slot at the end.
        self._order.extend(pid for pid in self._runtimes if pid not in self._order)

    # -- public interface ---------------------------------------------------
    @property
    def order(self) -> list[str]:
        """Return the effective failover order."""
        return list(self._order)

    def get_daily_prices(
        self, symbol: str, start: date, end: date
    ) -> FallbackResult[list[PriceBar]]:
        """Serve daily prices from the first healthy provider."""
        return self._execute(
            lambda p: p.get_daily_prices(symbol, start, end),
            symbol=symbol,
            start=start,
            end=end,
            validate=True,
        )

    def get_index_daily(
        self, index_code: str, start: date, end: date
    ) -> FallbackResult[list[PriceBar]]:
        """Serve index daily prices from the first healthy provider."""
        return self._execute(
            lambda p: p.get_index_daily(index_code, start, end),
            symbol=index_code,
            start=start,
            end=end,
            validate=True,
        )

    def list_symbols(self, exchange: str) -> FallbackResult[list[SymbolInfo]]:
        """Serve a symbol list from the first healthy provider."""
        return self._execute(lambda p: p.list_symbols(exchange), validate=False)

    def get_index_constituents(self, index_code: str) -> FallbackResult[list[str]]:
        """Serve index constituents from the first healthy provider."""
        return self._execute(lambda p: p.get_index_constituents(index_code), validate=False)

    # -- chain execution ----------------------------------------------------
    def _execute[T](
        self,
        call: Callable[[DataProvider], T],
        *,
        symbol: str | None = None,
        start: date | None = None,
        end: date | None = None,
        validate: bool,
    ) -> FallbackResult[T]:
        """Run ``call`` against providers in order, retrying then failing over."""
        attempts = max(1, self._settings.retry_attempts)
        failures: list[ProviderError] = []
        failovers: list[FailoverEvent] = []
        for provider_id in self._order:
            runtime = self._runtimes[provider_id]
            if self._in_cooldown(runtime, self._clock()):
                continue
            last_error: ProviderError | None = None
            for attempt in range(1, attempts + 1):
                try:
                    value = call(runtime.provider)
                    if validate:
                        bars = canonicalize_price_bars(
                            cast("list[PriceBar]", value), provider=provider_id
                        )
                        self._check_stale(bars, start, end, provider_id)
                        value = cast("T", bars)
                    self._record_success(runtime)
                    return FallbackResult(
                        provider=provider_id, value=value, failovers=failovers
                    )
                except Exception as exc:
                    last_error = self._as_provider_error(exc, provider_id)
                    if isinstance(last_error, AuthRequiredError) or attempt >= attempts:
                        break
                    self._sleep(self._settings.retry_backoff_seconds * (2 ** (attempt - 1)))
            if last_error is not None:
                self._record_failure(runtime, last_error)
                failures.append(last_error)
                failovers.append(
                    FailoverEvent(
                        provider=provider_id,
                        error_type=last_error.error_type,
                        symbol=symbol,
                        message=str(last_error),
                        at=self._clock(),
                    )
                )
        raise AllProvidersFailedError(
            f"all providers failed for {symbol or 'request'}", failures=failures
        )

    def _check_stale(
        self,
        bars: list[PriceBar],
        start: date | None,
        end: date | None,
        provider_id: str,
    ) -> None:
        """Reject a series whose latest bar is older than the last trading day."""
        if start is None or end is None or not bars:
            return
        today = self._today()
        if end < today - timedelta(days=self._settings.stale_window_days):
            return
        holidays = DEFAULT_MARKET_RULES.trading_holidays
        reference = last_trading_day(today, holidays)
        latest = bars[-1].date
        if latest >= reference:
            return
        missing = trading_days_between(latest + timedelta(days=1), reference, holidays)
        if len(missing) > self._settings.stale_tolerance_days:
            raise StaleDataError(
                f"{provider_id} latest {latest.isoformat()} is {len(missing)} trading "
                f"day(s) behind {reference.isoformat()}",
                provider=provider_id,
            )

    # -- health / circuit breaker ------------------------------------------
    def _in_cooldown(self, runtime: ProviderRuntime, now: datetime) -> bool:
        """Return ``True`` while the provider is skipped after repeated failures."""
        if runtime.cooldown_until is None:
            return False
        if now >= runtime.cooldown_until:
            runtime.cooldown_until = None  # half-open: allow one trial request
            return False
        return True

    def _record_success(self, runtime: ProviderRuntime) -> None:
        runtime.consecutive_failures = 0
        runtime.cooldown_until = None
        runtime.last_success_at = self._clock()
        runtime.last_error = None
        runtime.last_error_type = None
        runtime.total_successes += 1

    def _record_failure(self, runtime: ProviderRuntime, error: ProviderError) -> None:
        now = self._clock()
        runtime.consecutive_failures += 1
        runtime.total_failures += 1
        runtime.last_failure_at = now
        runtime.last_error = str(error)
        runtime.last_error_type = error.error_type
        if runtime.consecutive_failures >= self._settings.circuit_breaker_failures:
            runtime.cooldown_until = now + timedelta(
                seconds=self._settings.circuit_breaker_cooldown_seconds
            )

    @staticmethod
    def _as_provider_error(exc: Exception, provider_id: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, DataValidationError):
            return SchemaError(str(exc), provider=provider_id, cause=exc)
        return ProviderError(
            f"unexpected {type(exc).__name__}: {exc}", provider=provider_id, cause=exc
        )

    # -- status -------------------------------------------------------------
    def statuses(self) -> list[ProviderStatus]:
        """Return a health snapshot for every provider, in failover order."""
        now = self._clock()
        result: list[ProviderStatus] = []
        for provider_id in self._order:
            runtime = self._runtimes[provider_id]
            is_open = runtime.cooldown_until is not None and now < runtime.cooldown_until
            state: Literal["closed", "open", "half_open"]
            if is_open:
                state = "open"
            elif runtime.consecutive_failures >= self._settings.circuit_breaker_failures:
                state = "half_open"
            else:
                state = "closed"
            result.append(
                ProviderStatus(
                    id=provider_id,
                    name=runtime.provider.display_name,
                    unofficial=bool(getattr(runtime.provider, "unofficial", True)),
                    returns_adjusted_prices=runtime.provider.returns_adjusted_prices,
                    supports_indexes=runtime.provider.supports_indexes,
                    healthy=not is_open and runtime.consecutive_failures == 0,
                    state=state,
                    consecutive_failures=runtime.consecutive_failures,
                    in_cooldown=is_open,
                    cooldown_until=runtime.cooldown_until,
                    last_error=_safe_error_summary(
                        runtime.last_error_type, runtime.last_error
                    ),
                    last_error_type=runtime.last_error_type,
                    last_success_at=runtime.last_success_at,
                    last_failure_at=runtime.last_failure_at,
                )
            )
        return result

    def runtime_for(self, provider_id: str) -> ProviderRuntime | None:
        """Return the mutable runtime for ``provider_id`` (tests / diagnostics)."""
        return self._runtimes.get(provider_id)
