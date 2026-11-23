"""Built-in universe filters.

Importing this package registers every filter in :data:`core.universe.universe_filters`.
Adding a filter is one new module in this package plus one ``@register`` call.
"""

from __future__ import annotations

from core.filters import exchange, history, liquidity, tradability

__all__ = ["exchange", "history", "liquidity", "tradability"]
