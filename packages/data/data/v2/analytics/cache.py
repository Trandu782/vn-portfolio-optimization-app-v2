"""In-memory cache for the Sector Analysis payload (docs/V2_SPEC.md section 8).

The analytics payload is expensive to rebuild from the stored V2 tables, but it only
changes when the underlying data changes. The cache is keyed by the request settings
and invalidated by the data's ``data_as_of``: a hit is returned only when the stored
``data_as_of`` is unchanged, so a nightly precompute that advances the date evicts
every entry automatically.

The cache is deliberately DB-free and stores only the pure payload; per-response
metadata (``served_from_cache``, ``elapsed_ms``) is attached by the API layer after the
lookup and is never cached. ``clear_analytics_cache`` exists for tests.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import date
from time import perf_counter

from data.v2.analytics.schemas import AnalyticsPayload


@dataclass(frozen=True)
class _CacheEntry:
    """One cached payload plus the data date it was built against."""

    data_as_of: date | None
    payload: AnalyticsPayload


#: Process-wide cache. Module-level so every request in one serverless instance shares it.
_cache: dict[tuple[Hashable, ...], _CacheEntry] = {}


def cached_build(
    key: tuple[Hashable, ...],
    data_as_of: date | None,
    build: Callable[[], AnalyticsPayload],
) -> tuple[AnalyticsPayload, bool, float]:
    """Return ``(payload, from_cache, elapsed_ms)``, building only on a miss.

    A cached entry is served only when its ``data_as_of`` equals the current one, so a
data refresh invalidates the entry without a TTL. ``elapsed_ms`` is ``0.0`` for a hit;
for a miss it is the wall-clock build time in milliseconds.
    """
    entry = _cache.get(key)
    if entry is not None and entry.data_as_of == data_as_of:
        return entry.payload, True, 0.0
    started = perf_counter()
    payload = build()
    _cache[key] = _CacheEntry(data_as_of=data_as_of, payload=payload)
    return payload, False, (perf_counter() - started) * 1000.0


def clear_analytics_cache() -> None:
    """Drop every cached payload (used by tests)."""
    _cache.clear()


__all__ = ["cached_build", "clear_analytics_cache"]
