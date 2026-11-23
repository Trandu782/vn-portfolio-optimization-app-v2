"""Curated index-based universe presets.

A preset is a named starting universe taken from an index's constituents. Only the
VN30 is offered today. Adding VN100 is a **data-only** change: append an
:class:`IndexPreset` below and, if an offline fallback is wanted, add its members to
:data:`data.seed.SEED_INDEX_CONSTITUENTS`. The KBS provider already resolves VN100
(``INDEX_GROUP_MAP["VN100"] = "100"``), so no core or API change is required.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexPreset:
    """A named universe preset backed by an index's constituents."""

    code: str
    name: str
    description: str


#: Presets offered by the API. Append a tuple entry to add another one.
INDEX_PRESETS: tuple[IndexPreset, ...] = (
    IndexPreset(
        code="VN30",
        name="VN30",
        description="The 30 largest and most liquid stocks listed on HOSE.",
    ),
)

#: Preset lookup by canonical index code.
PRESET_BY_CODE: dict[str, IndexPreset] = {preset.code: preset for preset in INDEX_PRESETS}
