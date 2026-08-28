"""Runtime boundary: writable paths and configuration defaults."""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("ADAPTIVE_RAG_STATE_ROOT", "/tmp/adaptive-rag"))

_SETTING_DEFAULTS = {
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_API_KEY": "benchmark-placeholder-unused",
    # Settings validation requires these; the clients they configure are
    # replaced before any call is made.
    "TAVILY_API_KEY": "benchmark-placeholder-unused",
}

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    for variable, value in _SETTING_DEFAULTS.items():
        os.environ.setdefault(variable, value)

    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)

    _prepared = True
