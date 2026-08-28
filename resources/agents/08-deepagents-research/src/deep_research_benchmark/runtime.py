"""Runtime boundary: writable paths and configuration defaults.

``research_agent.tools`` constructs ``TavilyClient()`` at module import time,
which raises without a key. A placeholder is therefore set before that import;
the client object itself is replaced by ``benchmark_mocks`` immediately after,
so the placeholder is never used to authenticate anything.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("DEEP_RESEARCH_STATE_ROOT", "/tmp/deep-research"))

_SETTING_DEFAULTS = {
    # Placeholder only: the Tavily client is replaced before any call is made.
    "TAVILY_API_KEY": "benchmark-placeholder-unused",
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
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
