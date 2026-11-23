"""Concrete anonymous market-data providers (all unofficial).

Importing this package registers every provider in ``data.registry``.
"""

from __future__ import annotations

from data.providers import dnse, kbs, ssi_iboard, tcbs, vci

__all__ = ["dnse", "kbs", "ssi_iboard", "tcbs", "vci"]
