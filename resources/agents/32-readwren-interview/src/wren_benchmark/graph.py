"""Expose the interview graph with in-memory checkpointing.

Upstream persists conversation state to Redis. The benchmark configures
`use_redis=False`, which is upstream's own development path — a `MemorySaver`,
no connection attempted. The `redis` package is still imported at module scope,
so it is installed, but no client is created.
"""

from __future__ import annotations

import benchmark_mocks

_agent = None


def agent():
    global _agent
    if _agent is None:
        benchmark_mocks.install_all()
        from src.agents.interview_agent import InterviewAgent

        _agent = InterviewAgent(use_redis=False)
    return _agent


def graph():
    return agent().app
