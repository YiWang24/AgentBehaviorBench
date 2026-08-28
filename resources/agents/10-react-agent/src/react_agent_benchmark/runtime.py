"""Runtime boundary: writable paths and configuration defaults.

``react_agent.context.Context`` reads its defaults from upper-cased environment
variables, so the model and search width are pinned here rather than left to
whatever the host exports.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("REACT_AGENT_STATE_ROOT", "/tmp/react-agent"))

_SETTING_DEFAULTS = {
    "MODEL": "anthropic/claude-sonnet-4-5-20250929",
    "MAX_SEARCH_RESULTS": "3",
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
