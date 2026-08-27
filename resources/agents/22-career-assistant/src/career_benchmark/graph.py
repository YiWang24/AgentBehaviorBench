"""Expose the career assistant graph with the benchmark stand-ins installed."""

from __future__ import annotations

import benchmark_mocks

_compiled = None


class BenchmarkCallback:
    """Stands in for the Streamlit callback the nodes announce themselves to.

    Upstream passes a `CustomStreamlitCallbackHandler`; the nodes only call
    `write_agent_name`. The names are recorded rather than printed, so the run
    can report which agent the supervisor delegated to.
    """

    def __init__(self) -> None:
        self.agent_names: list[str] = []

    def write_agent_name(self, name: str) -> None:
        self.agent_names.append(name)

    def __getattr__(self, item):  # pragma: no cover - defensive
        def _noop(*args, **kwargs):
            return None

        return _noop


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install()
        from agents import define_graph

        _compiled = define_graph()
    return _compiled
