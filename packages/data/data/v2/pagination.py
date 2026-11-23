"""Pagination and date-window helpers for per-ticker, paginated providers.

SSI iBoard's ``statistics`` endpoints paginate per ticker (``stock-info`` returns
40 rows/page, ``finance-indicator`` 20 periods/page), so a consumer must walk
date windows *and* pages. These two pure helpers keep that loop in one tested
place instead of in every adapter. No network access happens here: callers pass a
``fetch`` callable that performs exactly one page request.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

#: Hard cap used when a caller does not supply a page limit, so a buggy upstream
#: that never reports a total cannot make a backfill loop forever.
DEFAULT_MAX_PAGES = 1_000

#: Paging keys a provider may return, most specific first.
_PAGING_KEYS: tuple[str, ...] = ("paging", "pagination")


def date_windows(start: date, end: date, *, window_days: int = 366) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into inclusive windows of at most ``window_days`` days.

    Used to keep each paginated request inside a bounded date span (SSI honours
    ``fromDate``/``toDate``), so a multi-year backfill becomes a sequence of
    shallow windows instead of one deep page crawl.
    """
    if window_days < 1:
        raise ValueError("window_days must be positive")
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _as_int(value: Any) -> int | None:
    """Coerce a paging value to ``int`` or return ``None`` when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _extract_paging(payload: Any) -> Mapping[str, Any]:
    """Return the provider's paging block, or an empty mapping when absent."""
    if not isinstance(payload, Mapping):
        return {}
    for key in _PAGING_KEYS:
        block = payload.get(key)
        if isinstance(block, Mapping):
            return block
    # Some payloads flatten the counters onto the top level.
    if any(name in payload for name in ("totalPage", "page", "pageSize", "total")):
        return payload
    return {}


def _extract_rows(payload: Any, rows_key: str) -> list[Any]:
    """Return the row list from a ``{rows_key: [...]}`` (or plain list) payload."""
    if isinstance(payload, Mapping):
        rows = payload.get(rows_key)
        if isinstance(rows, list):
            return rows
        return []
    if isinstance(payload, list):
        return payload
    return []


def has_more(paging: Mapping[str, Any], page: int, rows_on_page: int) -> bool:
    """Return ``True`` when another page follows ``page`` per the paging block.

    Preference order: ``totalPage`` (used by ``corporate-actions``), then
    ``total``/``pageSize`` (``stock-info`` and ``finance-indicator``), then a
    short-page heuristic. A block with no recognisable counter stops after one
    page so a missing field never triggers an unbounded crawl.
    """
    total_pages = _as_int(paging.get("totalPage"))
    if total_pages is not None:
        return page < total_pages
    total = _as_int(paging.get("total"))
    page_size = _as_int(paging.get("pageSize"))
    if total is not None and page_size is not None and page_size > 0:
        return page * page_size < total
    if total is not None and page_size is None and rows_on_page > 0:
        return page < total
    return False


def paginate(
    fetch: Callable[[int], Any],
    *,
    rows_key: str = "data",
    start_page: int = 1,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    max_rows: int | None = None,
) -> list[Any]:
    """Collect rows across pages by calling ``fetch(page)`` until the provider stops.

    Args:
        fetch: Performs one page request for the given 1-based page number and
            returns the decoded JSON payload.
        rows_key: Key holding the row list in the payload (``data`` for SSI).
        start_page: First page to request (1-based).
        max_pages: Safety cap on the number of page requests. ``None`` disables it
            (use only when the caller controls the upstream).
        max_rows: Optional cap on collected rows.

    Returns:
        Every row from every page, in page order (not de-duplicated).
    """
    collected: list[Any] = []
    page = start_page
    pages_read = 0
    while True:
        payload = fetch(page)
        rows = _extract_rows(payload, rows_key)
        collected.extend(rows)
        pages_read += 1
        if max_rows is not None and len(collected) >= max_rows:
            return collected[:max_rows]
        if max_pages is not None and pages_read >= max_pages:
            return collected
        if not rows:
            return collected
        if not has_more(_extract_paging(payload), page, len(rows)):
            return collected
        page += 1


__all__ = [
    "DEFAULT_MAX_PAGES",
    "date_windows",
    "has_more",
    "paginate",
]
