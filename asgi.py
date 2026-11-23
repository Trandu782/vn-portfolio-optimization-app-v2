"""Vercel FastAPI entrypoint.

Vercel's zero-configuration FastAPI preset only looks for a module-level ``app``
instance at a handful of supported entrypoints in the project root: ``app.py``,
``index.py``, ``server.py``, ``main.py``, ``wsgi.py`` or ``asgi.py`` (or the
same filenames inside ``src/`` or ``app/``). See ``docs/DEPLOYMENT.md``.

The API project deploys from the repository root so that ``packages/core`` and
``packages/data`` are part of the build context, but the application source
lives in ``apps/api``. Vercel installs the third-party dependencies listed in
the root ``pyproject.toml`` but does not install the workspace packages, so the
three source directories are put on ``sys.path`` before the application is
imported. That keeps the preset pointing at the real
``apps/api/app/main.py`` without duplicating code or publishing the workspace
packages.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SOURCE_DIRS = (
    _ROOT / "apps" / "api",  # `app` (FastAPI application)
    _ROOT / "packages" / "core",  # `core` (domain logic)
    _ROOT / "packages" / "data",  # `data` (providers, repositories, sync)
)

for _source_dir in _SOURCE_DIRS:
    if str(_source_dir) not in sys.path:
        sys.path.insert(0, str(_source_dir))

from app.main import app  # noqa: E402  (path bootstrap must run first)

__all__ = ["app"]
