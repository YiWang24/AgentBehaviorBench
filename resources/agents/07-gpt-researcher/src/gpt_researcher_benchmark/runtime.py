"""Runtime boundary: writable paths and benchmark configuration defaults.

The container root is read-only and ``/opt/agent`` is not writable, but
upstream's ChiefEditorAgent creates ``./outputs/<run>`` relative to the current
working directory as soon as it is constructed. The process therefore moves to
a writable ``/tmp`` root before any upstream module is imported.

``prepare()` also pins the retriever and embedding configuration, which
gpt-researcher reads from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("GPT_RESEARCHER_STATE_ROOT", "/tmp/gpt-researcher"))

DEFAULT_QUERY = "the current state of retrieval-augmented generation"
MAX_SECTIONS = int(os.environ.get("GPT_RESEARCHER_MAX_SECTIONS", "1"))

_SETTING_DEFAULTS = {
    # Route every search through the offline corpus; see benchmark_mocks.
    "RETRIEVER": "benchmark",
    # Bound one Case: fewer sub-queries and sources means fewer model calls.
    "MAX_ITERATIONS": "1",
    "MAX_SEARCH_RESULTS_PER_QUERY": "3",
    "MAX_SUBTOPICS": "1",
    # The agent's own model client keeps its provider URL; the Interceptor
    # rewrites the effective model.
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
    (STATE_ROOT / "outputs").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DOC_PATH", str(STATE_ROOT / "documents"))
    Path(os.environ["DOC_PATH"]).mkdir(parents=True, exist_ok=True)

    # ChiefEditorAgent writes ./outputs/<run> at construction time.
    os.chdir(workspace)

    _prepared = True
