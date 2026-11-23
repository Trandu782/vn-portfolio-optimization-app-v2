"""Pluggable groupings for the analytics engine (``docs/V2_SPEC.md`` section 3.2).

A grouping is an interface plus a :class:`core.registry.Registry`, so the sector view is
just one grouping beside the exchange and index-bucket views. Adding a grouping is one
class plus one ``@groupings.register`` call; the service never switches on a concrete id.

``assign`` returns ``None`` for a row that has no place in the grouping (for example a
ticker with no ICB level-2 sector). The service drops such rows instead of inventing a
group, matching the "never guessed" sector rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from pydantic import BaseModel

from core.registry import Registry
from data.v2.analytics.schemas import UniverseRow


class Grouping(Protocol):
    """A single way to partition the universe into labelled groups."""

    id: str
    display_name: str

    def assign(self, row: UniverseRow) -> str | None:
        """Return the group label for ``row``, or ``None`` when it is ungrouped."""


class GroupingFactory(Protocol):
    """Callable shape of a registered grouping class."""

    def __call__(self, params: dict[str, object] | None = None) -> Grouping: ...


class IndexBucketParams(BaseModel):
    """Options for the index-bucket grouping."""

    non_index_label: str = "Non-index"


#: Every registered grouping, keyed by id.
groupings: Registry[Grouping] = Registry()


@groupings.register(
    id="sector",
    name="ICB level-2 sector",
    description="Group the universe by its stored ICB level-2 sector.",
)
class SectorGrouping:
    """Group by ICB level-2 sector; a ticker without a sector is ungrouped."""

    id = "sector"
    display_name = "ICB level-2 sector"

    def __init__(self, params: dict[str, object] | None = None) -> None:
        """Create the grouping; it takes no options."""

    def assign(self, row: UniverseRow) -> str | None:
        """Return the row's ICB level-2 sector, or ``None`` when it is a coverage gap."""
        return row.sector or None


@groupings.register(
    id="exchange",
    name="Exchange",
    description="Group the universe by its board (HOSE, HNX or UPCoM).",
)
class ExchangeGrouping:
    """Group by the listed board."""

    id = "exchange"
    display_name = "Exchange"

    def __init__(self, params: dict[str, object] | None = None) -> None:
        """Create the grouping; it takes no options."""

    def assign(self, row: UniverseRow) -> str | None:
        """Return the row's exchange, or ``None`` when it is unknown."""
        return row.exchange.strip().upper() or None


@groupings.register(
    id="index",
    name="Index bucket",
    description="Group into VN30, VN100 (excluding VN30) or non-index members.",
    parameter_schema=IndexBucketParams,
)
class IndexBucketGrouping:
    """Group into VN30 / VN100-only / non-index buckets."""

    id = "index"
    display_name = "Index bucket"

    def __init__(self, params: dict[str, object] | None = None) -> None:
        """Create the grouping, optionally overriding the non-index label."""
        raw = dict(params or {})
        default_label = IndexBucketParams().non_index_label
        self._non_index_label = str(raw.get("non_index_label", default_label))

    def assign(self, row: UniverseRow) -> str | None:
        """Return ``VN30``, ``VN100`` or the non-index label."""
        memberships = {item.strip().upper() for item in row.index_memberships}
        if "VN30" in memberships:
            return "VN30"
        if "VN100" in memberships:
            return "VN100"
        return self._non_index_label


def build_grouping(
    grouping_id: str, params: dict[str, object] | None = None
) -> Grouping:
    """Instantiate the grouping registered under ``grouping_id``.

    Raises:
        KeyError: When ``grouping_id`` is unknown.
    """
    factory = cast(GroupingFactory, groupings.get(grouping_id))
    return factory(params)


def group_rows(
    rows: Sequence[UniverseRow], grouping: Grouping
) -> dict[str, list[UniverseRow]]:
    """Return ``rows`` partitioned by ``grouping``, dropping ungrouped rows."""
    groups: dict[str, list[UniverseRow]] = {}
    for row in rows:
        label = grouping.assign(row)
        if label is None:
            continue
        groups.setdefault(label, []).append(row)
    return groups


__all__ = [
    "ExchangeGrouping",
    "Grouping",
    "GroupingFactory",
    "IndexBucketGrouping",
    "IndexBucketParams",
    "SectorGrouping",
    "build_grouping",
    "group_rows",
    "groupings",
]
