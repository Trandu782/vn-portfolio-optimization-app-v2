"""V2-specific provider errors.

Reuses the V1 taxonomy from :mod:`data.errors` (so V2 errors are still
``ProviderError`` subclasses and interoperate with ``AllProvidersFailedError``)
and adds ``BlockedError`` for HTTP 403 / hard anti-bot blocks, which the runner
treats as "do not retry, cool down".
"""

from __future__ import annotations

from data.errors import DataError, ProviderError


class BlockedError(ProviderError):
    """The endpoint returned HTTP 403 or a hard block (retrying will not help)."""

    error_type = "blocked"


class NoProvidersConfiguredError(DataError):
    """The configured failover chain for a data type is empty."""


class PrecomputeError(DataError):
    """The precompute pipeline hit a fatal, non-retryable inconsistency."""


__all__ = ["BlockedError", "NoProvidersConfiguredError", "PrecomputeError"]
