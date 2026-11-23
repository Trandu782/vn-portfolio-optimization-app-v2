"""Pytest configuration for the data package tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``support`` importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).parent))
