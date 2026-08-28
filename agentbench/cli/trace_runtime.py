"""Build benchmark runners with model interception trace output."""

from __future__ import annotations

from collections.abc import Callable

from agentbench.harness import AgentRunner, BenchmarkRunner, SuiteRunner
from agentbench.runtime import RuntimeFactory
from agentbench.runtime.docker import DockerRuntime
from agentbench.runtime.interception import (
    CompositeTraceSink,
    NullTraceSink,
    OpenRouterProvider,
    TerminalTraceSink,
    TraceSink,
)


def build_trace_suite_runner(
    *,
    mode: str,
    max_bytes: int,
    output_fn: Callable[[str], None],
    model: str | None = None,
    activity_sink: TraceSink | None = None,
) -> SuiteRunner:
    if mode not in {"off", "terminal"}:
        raise ValueError(f"Unsupported LLM trace mode: {mode!r}")
    sinks: list[TraceSink] = []
    if activity_sink is not None:
        sinks.append(activity_sink)
    if mode == "terminal":
        trace_output = getattr(activity_sink, "write_static", output_fn)
        sinks.append(TerminalTraceSink(trace_output))
    sink: TraceSink = CompositeTraceSink(tuple(sinks)) if sinks else NullTraceSink()
    runtime_factory = RuntimeFactory(
        docker_builder=lambda: DockerRuntime(
            model_provider=OpenRouterProvider(model=model),
            trace_sink=sink,
            trace_max_bytes=max_bytes,
        )
    )
    agent_runner = AgentRunner(runtime_factory=runtime_factory)
    benchmark_runner = BenchmarkRunner(agent_runner=agent_runner)
    return SuiteRunner(benchmark_runner=benchmark_runner)

