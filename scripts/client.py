"""Generate and verify the typed web API client.

The FastAPI app is the single source of truth. ``generate`` writes
``apps/api/openapi.json`` from ``app.openapi()`` and then runs
``openapi-typescript`` (an ``apps/web`` dev dependency) to produce
``apps/web/lib/schema.d.ts``. ``check`` regenerates both and exits non-zero when
the committed artefacts are out of date, which is the ``make check`` guard that
keeps the web client in sync with the API.

Usage:
    python scripts/client.py generate
    python scripts/client.py check
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
WEB_DIR = ROOT / "apps" / "web"
OPENAPI_JSON = API_DIR / "openapi.json"
SCHEMA_TS = WEB_DIR / "lib" / "schema.d.ts"
SCHEMA_CHECK_TS = WEB_DIR / "lib" / "schema.check.d.ts"
STALE_HINT = "typed client is out of date: run `make client`"


def render_openapi() -> str:
    """Return the FastAPI OpenAPI document as stable, pretty JSON."""
    from app.main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def _run_npm(script: str) -> None:
    """Run an ``apps/web`` npm script (shell mode is required for npm on Windows)."""
    subprocess.run(["npm", "run", script], cwd=WEB_DIR, check=True, shell=(os.name == "nt"))


def _diff(expected: str, actual: str, label: str) -> bool:
    """Print a unified diff and return True when the two texts differ."""
    if expected == actual:
        return False
    sys.stderr.writelines(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"committed {label}",
            tofile=f"regenerated {label}",
        )
    )
    return True


def generate() -> int:
    """Write ``openapi.json`` and regenerate ``schema.d.ts``."""
    API_DIR.mkdir(parents=True, exist_ok=True)
    OPENAPI_JSON.write_text(render_openapi(), encoding="utf-8")
    _run_npm("client")
    print(f"wrote {OPENAPI_JSON.relative_to(ROOT)} and {SCHEMA_TS.relative_to(ROOT)}")
    return 0


def check() -> int:
    """Fail when the committed OpenAPI schema or typed client is out of date."""
    committed = OPENAPI_JSON.read_text(encoding="utf-8") if OPENAPI_JSON.exists() else ""
    stale = _diff(committed, render_openapi(), "apps/api/openapi.json")
    try:
        _run_npm("client:check")
        generated = SCHEMA_CHECK_TS.read_text(encoding="utf-8") if SCHEMA_CHECK_TS.exists() else ""
        committed_ts = SCHEMA_TS.read_text(encoding="utf-8") if SCHEMA_TS.exists() else ""
        stale |= _diff(committed_ts, generated, "apps/web/lib/schema.d.ts")
    finally:
        SCHEMA_CHECK_TS.unlink(missing_ok=True)
    if stale:
        print(STALE_HINT)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ``generate`` or ``check``."""
    parser = argparse.ArgumentParser(description="Generate or verify the typed web API client.")
    parser.add_argument("command", choices=["generate", "check"])
    args = parser.parse_args(argv)
    return generate() if args.command == "generate" else check()


if __name__ == "__main__":
    raise SystemExit(main())
