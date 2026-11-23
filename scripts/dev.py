"""Run the FastAPI app and the Next.js dev server together.

This is the cross-platform equivalent of ``make dev``. It starts uvicorn for
the API on port 8000 and the Next.js dev server for the web app, then waits
until either process exits or the user presses Ctrl+C.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
WEB_DIR = ROOT / "apps" / "web"
API_PORT = 8000


def _start_api() -> subprocess.Popen[bytes]:
    """Start uvicorn for the API on port 8000 with auto-reload."""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
        ],
        cwd=API_DIR,
    )


def _start_web() -> subprocess.Popen[bytes]:
    """Start the Next.js dev server (shell mode is required for npm on Windows)."""
    return subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=WEB_DIR,
        shell=os.name == "nt",
    )


def _terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    """Terminate any still-running child processes, then wait for them to exit."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    """Start both servers and block until interrupted."""
    processes = [_start_api(), _start_web()]
    print(f"API:  http://127.0.0.1:{API_PORT}/api/v1/health")
    print("Web:  http://localhost:3000")
    print("Press Ctrl+C to stop both servers.")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        _terminate(processes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
