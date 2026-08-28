"""Runtime boundary: writable paths and configuration defaults.

`Configuration.from_runnable_config` reads every field from an upper-cased
environment variable before falling back to the runnable config, so the model
is pinned here. Upstream defaults to `google_genai:gemini-2.5-flash`, which the
Model Interceptor cannot capture. Its OpenAI path is broken upstream --
`llm_service` passes `reasoning="False"` as a string and `ChatOpenAI` requires a
dict -- so Anthropic is pinned instead. The field is configurable, so this is a
configuration change rather than a source edit.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("EVENT_RESEARCH_STATE_ROOT", "/tmp/event-research"))

DEFAULT_SUBJECT = "Ada Lovelace"

_SETTING_DEFAULTS = {
    "LLM_MODEL": "anthropic:claude-sonnet-4-5-20250929",
    # Each role resolves its own model and they do not all fall back to
    # LLM_MODEL: get_chunk_model() falls back to a hardcoded "ollama:gemma3:4b",
    # which dials localhost:11434 and is refused in the benchmark runtime.
    "CHUNK_LLM_MODEL": "anthropic:claude-sonnet-4-5-20250929",
    "STRUCTURED_LLM_MODEL": "anthropic:claude-sonnet-4-5-20250929",
    "TOOLS_LLM_MODEL": "anthropic:claude-sonnet-4-5-20250929",
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    # Bound one Case: fewer supervisor turns means fewer model calls.
    "MAX_TOOL_ITERATIONS": "2",
    # Placeholder only: the search client is replaced before any call is made.
    "TAVILY_API_KEY": "benchmark-placeholder-unused",
}

# Tracing would ship spans to a hosted service; the benchmark has no egress.
_UNSET = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "GOOGLE_API_KEY",
    "FIRECRAWL_API_KEY",
)

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    for variable, value in _SETTING_DEFAULTS.items():
        os.environ.setdefault(variable, value)
    for variable in _UNSET:
        os.environ.pop(variable, None)

    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", "/opt/agent/tiktoken-cache")
    os.chdir(workspace)

    _prepared = True
