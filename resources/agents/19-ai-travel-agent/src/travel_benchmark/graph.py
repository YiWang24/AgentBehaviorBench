"""Expose the travel agent's graph with the benchmark stand-ins installed.

Upstream's ``Agent.__init__`` prints a mermaid rendering of the graph to
stdout, and ``invoke_tools`` prints every tool call. stdout carries the JSONL
protocol, so all of it is redirected to stderr here rather than being deleted
from the vendored source.
"""

from __future__ import annotations

import contextlib
import sys

import benchmark_mocks

_agent = None


def agent():
    global _agent
    if _agent is None:
        benchmark_mocks.install()
        from agents.agent import Agent

        with contextlib.redirect_stdout(sys.stderr):
            _agent = Agent()
    return _agent


def graph():
    return agent().graph
