"""Assemble a fully offline benchmark runner for startup verification."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from agentbench.harness import AgentRunner, BenchmarkRunner, SuiteRunner
from agentbench.harness.offline import (
    OfflineRunFactory,
    OfflineSecretResolver,
    OfflineSuiteRunner,
)
from agentbench.runtime import RuntimeFactory
from agentbench.runtime.docker import DockerRuntime
from agentbench.runtime.interception import (
    DEFAULT_TRACE_MAX_BYTES,
    InterceptionTraceState,
    ModelTargetConfig,
    StaticModelTargetProvider,
    TerminalTraceSink,
    TraceEvent,
    TraceSink,
)

OFFLINE_PROVIDER_ID = "offline"
OFFLINE_TARGET_PLUGIN = "offline-mock"
OFFLINE_BASE_URL = "offline://local"
OFFLINE_MODEL = "offline-verify-model"
OFFLINE_UPSTREAM_KEY_ENV = "DEFUZEX_OFFLINE_UPSTREAM_KEY"
OFFLINE_UPSTREAM_KEY_VALUE = "offline-verify-no-upstream"


@dataclass(frozen=True)
class OfflineRuntime:
    """The runner plus the handles the CLI needs to report on a verification."""

    runner: SuiteRunner
    trace_state: InterceptionTraceState
    secret_resolver: OfflineSecretResolver

    @property
    def captured_pair_count(self) -> int:
        """Matched ``llm_request``/``llm_response`` pairs seen across the run."""

        return self.trace_state.checkpoint()

    @property
    def substituted_secrets(self) -> tuple[str, ...]:
        return self.secret_resolver.substituted


def build_offline_runtime(
    *,
    max_inputs: int,
    probes: tuple[object, ...],
    output_fn: Callable[[str], None],
    llm_trace: str = "off",
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES,
    activity_sink: TraceSink | None = None,
    model: str | None = None,
) -> OfflineRuntime:
    """Wire a runner that reaches no network and needs no official credentials."""

    if llm_trace not in {"off", "terminal"}:
        raise ValueError(f"Unsupported LLM trace mode: {llm_trace!r}")

    # Counting pairs here is independent of the runtime's own required-trace gate,
    # so the CLI can report how much model traffic verification actually observed.
    trace_state = InterceptionTraceState()
    sinks: list[TraceSink] = [trace_state]
    if activity_sink is not None:
        sinks.append(activity_sink)
    if llm_trace == "terminal":
        trace_output = getattr(activity_sink, "write_static", output_fn)
        sinks.append(TerminalTraceSink(trace_output))

    # The offline target never contacts a provider, so its credential is synthetic.
    # Seeding it here keeps it out of the resolver's substituted-secret report,
    # which is reserved for genuinely missing Agent configuration.
    secret_resolver = OfflineSecretResolver(
        {**os.environ, OFFLINE_UPSTREAM_KEY_ENV: OFFLINE_UPSTREAM_KEY_VALUE}
    )
    target = ModelTargetConfig(
        provider_id=OFFLINE_PROVIDER_ID,
        target_plugin=OFFLINE_TARGET_PLUGIN,
        base_url=OFFLINE_BASE_URL,
        model=(model or OFFLINE_MODEL).strip() or OFFLINE_MODEL,
        credential_env=OFFLINE_UPSTREAM_KEY_ENV,
    )
    runtime_factory = RuntimeFactory(
        docker_builder=lambda: DockerRuntime(
            secret_resolver=secret_resolver,
            model_provider=StaticModelTargetProvider(target),
            trace_sink=_CompositeTraceSink(tuple(sinks)),
            trace_max_bytes=llm_trace_max_bytes,
            egress="blocked",
        )
    )
    benchmark_runner = BenchmarkRunner(
        agent_runner=AgentRunner(runtime_factory=runtime_factory),
        # A local factory also stops BenchmarkRunner from importing the DefuzeX SDK.
        sdk_run_factory=OfflineRunFactory(probes=probes),
    )
    return OfflineRuntime(
        runner=OfflineSuiteRunner(
            benchmark_runner=benchmark_runner,
            max_inputs=max_inputs,
        ),
        trace_state=trace_state,
        secret_resolver=secret_resolver,
    )


class _CompositeTraceSink:
    def __init__(self, sinks: tuple[TraceSink, ...]) -> None:
        self._sinks = sinks

    def emit(self, event: TraceEvent) -> None:
        for sink in self._sinks:
            sink.emit(event)
