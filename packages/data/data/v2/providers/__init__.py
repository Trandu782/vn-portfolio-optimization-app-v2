"""Concrete V2 adapters (all unofficial and anonymous).

Importing this package imports every adapter module, which registers it in the
V2 registries (``data.v2.registry``).
"""

from __future__ import annotations

from data.v2.providers import dnse, kbs, ssi_iboard, ssi_statistics, tcbs, vci

__all__ = ["dnse", "kbs", "ssi_iboard", "ssi_statistics", "tcbs", "vci"]
