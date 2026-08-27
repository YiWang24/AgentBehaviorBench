"""Runtime boundary: writable paths and configuration defaults.

Upstream reads configuration through pydantic-settings. Two defaults matter for
the benchmark: the model provider is pinned to OpenAI so exactly one provider is
intercepted, and ``GROQ_API_KEY`` is deliberately left unset so the LlamaGuard
safeguard node short-circuits to SAFE instead of calling a second provider that
the manifest does not declare.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("RESEARCH_ASSISTANT_STATE_ROOT", "/tmp/research-assistant"))

_SETTING_DEFAULTS = {
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_API_KEY": "",
}

# Providers whose keys must stay unset: each would add an undeclared model route.
_UNSET = ("GROQ_API_KEY", "OPENWEATHERMAP_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    for variable, value in _SETTING_DEFAULTS.items():
        if value:
            os.environ.setdefault(variable, value)
    for variable in _UNSET:
        os.environ.pop(variable, None)

    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)

    _prepared = True
