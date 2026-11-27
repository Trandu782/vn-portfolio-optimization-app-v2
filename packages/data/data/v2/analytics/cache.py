"""In-memory cache for the Sector Analysis payload (docs/V2_SPEC.md section 8).

The analytics payload is expensive to rebuild from the stored V2 tables, but it only
changes when the underlying data changes. The cache is keyed by the request settings
and invalidated by the data's ``data_as_of``: a hit is returned only when the stored
``data_as_of`` is unchanged, and advancing ``data_as_of`` evicts stale entries.

The cache is bounded (LRU, default ``maxsize=64``) and thread-safe. Per-response
metadata (``served_from_cache``, ``elapsed_ms``) is attached by the API layer after
the lookup and is never cached. ``clear_analytics_cache`` exists for tests.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import date
from time import perf_counter

from data.v2.analytics.schemas import AnalyticsPayload
from data.v2.analytics.universe_reader import clear_universe_cache

#: Default maximum number of cached analytics payloads held in memory.
DEFAULT_CACHE_MAXSIZE = 64


@dataclass(frozen=True)
class _CacheEntry:
    """One cached payload plus the data date it was built against."""

    data_as_of: date | None
    payload: AnalyticsPayload


#: Process-wide bounded LRU cache, guarded by ``_cache_lock``.
_cache: OrderedDict[tuple[Hashable, ...], _CacheEntry] = OrderedDict()
_latest_data_as_of: date | None = None
_cache_lock = threading.Lock()


def _evict_stale_locked(data_as_of: date | None) -> None:
    """Evict older-snapshot entries whenever ``data_as_of`` advances."""
    global _latest_data_as_of
    if data_as_of is None:
        return
    if _latest_data_as_of is None or data_as_of > _latest_data_as_of:
        _latest_data_as_of = data_as_of
        stale_keys = [
            key
            for key, entry in _cache.items()
            if entry.data_as_of is None or entry.data_as_of < data_as_of
        ]
        for key in stale_keys:
            _cache.pop(key, None)


def cached_build(
    key: tuple[Hashable, ...],
    data_as_of: date | None,
    build: Callable[[], AnalyticsPayload],
    *,
    maxsize: int = DEFAULT_CACHE_MAXSIZE,
) -> tuple[AnalyticsPayload, bool, float]:
    """Return ``(payload, from_cache, elapsed_ms)``, building only on a miss.

    A cached entry is served only when its ``data_as_of`` equals the current one, so a
    data refresh invalidates stale entries without a TTL. ``elapsed_ms`` is ``0.0`` for
    a hit; for a miss it is the wall-clock build time in milliseconds.
    """
    limit = max(1, maxsize)
    with _cache_lock:
        _evict_stale_locked(data_as_of)
        entry = _cache.get(key)
        if entry is not None and entry.data_as_of == data_as_of:
            _cache.move_to_end(key)
            return entry.payload, True, 0.0

    started = perf_counter()
    payload = build()
    elapsed_ms = (perf_counter() - started) * 1000.0

    with _cache_lock:
        _evict_stale_locked(data_as_of)
        _cache[key] = _CacheEntry(data_as_of=data_as_of, payload=payload)
        _cache.move_to_end(key)
        while len(_cache) > limit:
            _cache.popitem(last=False)
    return payload, False, elapsed_ms


def cache_size() -> int:
    """Return the number of entries currently held in the analytics cache."""
    with _cache_lock:
        return len(_cache)


def clear_analytics_cache() -> None:
    """Drop every cached payload and universe snapshot (used by tests)."""
    global _latest_data_as_of
    with _cache_lock:
        _cache.clear()
        _latest_data_as_of = None
    clear_universe_cache()


__all__ = ["DEFAULT_CACHE_MAXSIZE", "cache_size", "cached_build", "clear_analytics_cache"]
