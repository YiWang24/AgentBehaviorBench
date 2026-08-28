"""Runtime boundary: writable paths and configuration defaults.

`config.py` selects the provider from `DEFAULT_MODEL_PROVIDER` at import time
and raises on an unknown value, so the provider and model are pinned here before
anything imports it.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("AGENTK_STATE_ROOT", "/tmp/agentk"))

_SETTING_DEFAULTS = {
    "DEFAULT_MODEL_PROVIDER": "OPENAI",
    "DEFAULT_MODEL_NAME": "gpt-4o",
    "DEFAULT_MODEL_TEMPERATURE": "0",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
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
