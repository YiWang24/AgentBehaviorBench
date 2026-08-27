"""Runtime boundary: writable paths and configuration defaults.

The benchmark container runs with a read-only root filesystem, so upstream's
``~/.tradingagents`` default is unusable. Every writable location is redirected
under ``/tmp`` and created idempotently at process start — never in the
Dockerfile, because ``/tmp`` is a fresh tmpfs when the container starts.

``prepare()`` must run before ``tradingagents.default_config`` is imported:
that module reads the ``TRADINGAGENTS_*`` overrides once, at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("TRADING_AGENTS_STATE_ROOT", "/tmp/trading-agents"))

DEFAULT_TICKER = "NVDA"
DEFAULT_TRADE_DATE = "2024-05-10"

_PATH_DEFAULTS = {
    "TRADINGAGENTS_RESULTS_DIR": STATE_ROOT / "results",
    "TRADINGAGENTS_CACHE_DIR": STATE_ROOT / "cache",
    "TRADINGAGENTS_MEMORY_LOG_PATH": STATE_ROOT / "memory" / "trading_memory.md",
}

# One debate and one risk round keep a benchmark invocation bounded. Upstream
# defaults are already 1; they are pinned here so a stray host environment
# cannot turn one Case into an unbounded number of model calls.
_SETTING_DEFAULTS = {
    "TRADINGAGENTS_LLM_PROVIDER": "openai",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "1",
    "TRADINGAGENTS_MAX_RISK_ROUNDS": "1",
    "TRADINGAGENTS_CHECKPOINT_ENABLED": "false",
}

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    for variable, default in _PATH_DEFAULTS.items():
        os.environ.setdefault(variable, str(default))
    for variable, value in _SETTING_DEFAULTS.items():
        os.environ.setdefault(variable, value)

    Path(os.environ["TRADINGAGENTS_RESULTS_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["TRADINGAGENTS_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["TRADINGAGENTS_MEMORY_LOG_PATH"]).parent.mkdir(
        parents=True, exist_ok=True
    )

    _prepared = True
