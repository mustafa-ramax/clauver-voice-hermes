"""
Worker lifecycle manager for Clauver.

Ensures the agent worker is running before dispatching calls.
Respects CLAUVER_WORKER_MODE: "auto" (default) or "persistent".
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("clauver-worker-manager")

PID_FILE = Path("/tmp/clauver-worker.pid")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_FILE = _PROJECT_ROOT / "clauver-agent.log"


def _is_worker_alive() -> bool:
    """Check if a worker process is running via PID file."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check if process exists
        return True
    except (ValueError, OSError):
        # Stale PID file — process is dead
        PID_FILE.unlink(missing_ok=True)
        return False


def _spawn_worker() -> None:
    """Spawn agent.py dev as a background subprocess with logs to file."""
    env = os.environ.copy()
    log_fh = open(LOG_FILE, "a")
    subprocess.Popen(
        [sys.executable, "agent.py", "dev"],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    logger.info(f"Spawned agent worker (logs: {LOG_FILE})")


async def ensure_worker_running() -> str:
    """Ensure the agent worker is running. Returns a status message."""
    mode = os.getenv("CLAUVER_WORKER_MODE", "auto").strip().lower()

    if _is_worker_alive():
        return "already running"

    # Worker not running — spawn it
    _spawn_worker()

    # Wait for PID file to appear (worker writes it on startup)
    for _ in range(30):  # 15s max (30 × 0.5s)
        await asyncio.sleep(0.5)
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)
                break
            except (ValueError, OSError):
                continue
    else:
        raise RuntimeError(f"Worker failed to start within 15s. Check logs: {LOG_FILE}")

    if mode == "persistent":
        return (
            "Worker started (persistent mode — will stay running). "
            "To stop: kill $(cat /tmp/clauver-worker.pid)"
        )
    return "Worker started (auto mode — will shutdown after 2 min idle)"
