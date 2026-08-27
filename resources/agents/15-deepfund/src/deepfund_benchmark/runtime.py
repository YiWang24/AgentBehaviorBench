"""Runtime boundary: writable paths and configuration defaults.

`database.sqlite_setup` reads `DB_PATH` at import time and creates the parent
directory immediately, so the path is set before anything imports it. The
database is SQLite and stays inside the container's tmpfs, so a run leaves
nothing behind and cannot reach a shared instance.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("DEEPFUND_STATE_ROOT", "/tmp/deepfund"))

DEFAULT_TICKER = "NVDA"
DEFAULT_TRADING_DATE = "2024-05-10"

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(STATE_ROOT / "db" / "deepfund.sqlite"))
    os.environ.setdefault("DEEPFUND_LOG_DIR", str(STATE_ROOT / "logs"))
    Path(os.environ["DEEPFUND_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
    Path(os.environ["DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)

    _prepared = True
