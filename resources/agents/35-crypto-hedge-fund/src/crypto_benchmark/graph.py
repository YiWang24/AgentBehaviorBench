"""Expose the crypto trading graph with Binance data mocked.

Upstream puts `src/` on the path and reads `config.yaml` into a module-level
`settings` singleton at import. Both are reproduced here: the src directory is
added to `sys.path` before any `utils`/`graph` import, and `config.yaml` sits in
the working directory. The Binance data methods are replaced before the graph
is built.
"""

from __future__ import annotations

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import benchmark_mocks


def _prepare_workspace() -> str:
    """Run from a writable dir: config.yaml is read relative to cwd and the
    data provider creates ./cache there, but the image root is read-only."""
    import pathlib
    import shutil

    workspace = os.environ.get("CRYPTO_WORKSPACE", "/tmp/crypto")
    pathlib.Path(workspace).mkdir(parents=True, exist_ok=True)
    source_config = os.environ.get("CRYPTO_CONFIG", "/opt/agent/config.yaml")
    target_config = os.path.join(workspace, "config.yaml")
    if os.path.exists(source_config) and not os.path.exists(target_config):
        shutil.copy(source_config, target_config)
    os.chdir(workspace)
    return workspace

_agent = None


def agent():
    global _agent
    if _agent is None:
        _prepare_workspace()
        benchmark_mocks.install()
        from utils import settings
        from agent import Agent

        _agent = Agent(
            intervals=settings.signals.intervals,
            strategies=settings.signals.strategies,
            show_agent_graph=False,
        )
    return _agent


def graph():
    return agent().agent
