"""Smoke test ensuring the data package is importable and versioned."""

from __future__ import annotations

import data


def test_package_exposes_version() -> None:
    assert data.__version__ == "0.1.0"
