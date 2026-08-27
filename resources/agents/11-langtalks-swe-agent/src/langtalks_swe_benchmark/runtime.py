"""Runtime boundary: writable workspace and configuration defaults.

The agent's tools resolve paths relative to the current directory, so the
process moves into a fresh copy of the fixture project before it runs. ``/tmp``
is a new tmpfs on every container start, so the copy happens here rather than
in the Dockerfile.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("LANGTALKS_SWE_STATE_ROOT", "/tmp/langtalks-swe"))

_SETTING_DEFAULTS = {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    # The agent traces to LangSmith when a key is present; the benchmark
    # declares one model route and nothing else.
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false",
}

_UNSET = ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")

_prepared = False
_workspace: Path | None = None


def workspace() -> Path:
    """Return the writable project directory the agent works in."""
    if _workspace is None:
        raise RuntimeError("runtime.prepare() has not run")
    return _workspace


def prepare() -> Path:
    """Materialise the fixture project and move into it. Idempotent."""
    global _prepared, _workspace
    if _prepared:
        return workspace()

    for variable, value in _SETTING_DEFAULTS.items():
        os.environ.setdefault(variable, value)
    for variable in _UNSET:
        os.environ.pop(variable, None)

    from benchmark_mocks.workspace import materialise

    root = STATE_ROOT / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    _workspace = materialise(root)
    # The agent addresses the codebase as ./workspace_repo, so the process
    # sits in the parent directory rather than inside the project.
    os.chdir(root)

    _prepared = True
    return _workspace
