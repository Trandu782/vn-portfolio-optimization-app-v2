"""Error hierarchy for the data layer.

Every provider failure is expressed as a :class:`ProviderError` subclass with a
stable ``error_type`` so the failover chain, the circuit breaker and the status
endpoint can classify it without string matching. Each error carries the
``provider`` id that raised it (or ``"unknown"`` when the origin is not a
specific provider).

The hierarchy is deliberately small: one class per failure category named in the
task (network error, timeout, HTTP error, auth/token failure, rate limit, empty
result, wrong schema, stale data).
"""

from __future__ import annotations


class DataError(Exception):
    """Base class for every error raised by the data layer."""


class ProviderError(DataError):
    """A single provider failed. ``error_type`` classifies the failure."""

    error_type: str = "provider"

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.cause = cause

    @property
    def error_type_name(self) -> str:
        """Return the stable machine-readable failure category."""
        return self.error_type


class NetworkError(ProviderError):
    """The connection could not be established (DNS, TLS, reset, ...)."""

    error_type = "network"


class ProviderTimeoutError(ProviderError):
    """The request timed out."""

    error_type = "timeout"


class HttpStatusError(ProviderError):
    """The endpoint returned an unhandled non-success HTTP status."""

    error_type = "http"

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        provider: str = "unknown",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, provider=provider, cause=cause)
        self.status_code = status_code


class AuthRequiredError(ProviderError):
    """The endpoint now demands registration, a token or a login."""

    error_type = "auth"


class RateLimitError(ProviderError):
    """The endpoint rejected the request because of rate limiting."""

    error_type = "rate_limit"


class EmptyResultError(ProviderError):
    """The provider returned no rows for a range it should have covered."""

    error_type = "empty"


class SchemaError(ProviderError):
    """The response did not match the documented schema."""

    error_type = "schema"


class StaleDataError(ProviderError):
    """The provider's latest row is older than the last trading day."""

    error_type = "stale"


class DataValidationError(DataError):
    """A price series failed structural validation (negative price, ...)."""


class InconsistentDataError(DataError):
    """Two providers disagree about the same symbol on the same days."""


class AllProvidersFailedError(DataError):
    """Every provider in the failover chain failed for one request."""

    def __init__(self, message: str, *, failures: list[ProviderError]) -> None:
        super().__init__(message)
        self.failures = failures
