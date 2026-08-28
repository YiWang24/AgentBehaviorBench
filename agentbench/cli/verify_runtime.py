"""Assemble the two runtime stacks that `verify` drives.

Verification runs in one direction, and the two halves need different machinery.
Preflight needs nothing but Docker: model replies are synthesized inside the
interceptor with egress blocked, so an Agent stays checkable before any
credential exists on the host. The graded benchmark that follows needs one, and
reaches a real provider with egress open.

Both halves observe the same Agent through one shared set of trace sinks, so the
final report accounts for every model call either half made.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from agentbench.cli.TerminalUI.call_log import CallRecord, CallRecorder
from agentbench.harness import AgentRunner, BenchmarkRunner, SuiteRunner
from agentbench.harness.local import ChatModel, LocalBenchmarkSuiteRunner
from agentbench.runtime.contracts import OfflineSecretResolver
from agentbench.runtime import RuntimeFactory
from agentbench.runtime.docker import DockerRuntime
from agentbench.runtime.docker.runtime import EgressMode
from agentbench.runtime.interception import (
    DEEPSEEK_API_KEY_ENV,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_TRACE_MAX_BYTES,
    CompositeTraceSink,
    DeepSeekProvider,
    InterceptionTraceState,
    ModelTargetConfig,
    ModelTargetProvider,
    StaticModelTargetProvider,
    TerminalTraceSink,
    TraceSink,
)

OFFLINE_PROVIDER_ID = "offline"
OFFLINE_TARGET_PLUGIN = "offline-mock"
OFFLINE_BASE_URL = "offline://local"
OFFLINE_MODEL = "offline-verify-model"
OFFLINE_UPSTREAM_KEY_ENV = "DEFUZEX_OFFLINE_UPSTREAM_KEY"
OFFLINE_UPSTREAM_KEY_VALUE = "offline-verify-no-upstream"

TraceMode = Literal["off", "terminal"]
TRACE_MODES: tuple[TraceMode, ...] = get_args(TraceMode)

# One probe answers the preflight question. One generated Case does not answer
# the behavior question, because a single Input cannot cover a requirement.
DEFAULT_PROBE_COUNT = 1
DEFAULT_INPUT_COUNT = 3

# The probe only has to invite a reply. It deliberately says nothing an Agent
# could be graded against: preflight serves synthesized model replies, so the
# wording carries no signal worth judging.
DEFAULT_PROBE_TEXT = "Reply with a short confirmation that you received this message."


@dataclass(frozen=True, slots=True)
class VerifyOptions:
    """What to verify and how, apart from where the report goes.

    These travel together because ``verify`` reads almost none of them: it hands
    them to :func:`build_verify_runtime`. Spelling them out on both meant every
    new option had to be added in three places — two signatures and the call
    between them — and a missed one silently kept its default.
    """

    probe_count: int = DEFAULT_PROBE_COUNT
    input_count: int = DEFAULT_INPUT_COUNT
    probe_text: str = DEFAULT_PROBE_TEXT
    # The model the Agent itself talks to during the graded benchmark. Preflight
    # never uses it: its replies come from the interceptor.
    model: str | None = None
    # The model that writes the Case and grades the Run, which is a different
    # question from the model the Agent talked to.
    provider_model: str | None = None
    llm_trace: TraceMode = "off"
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES


@dataclass(frozen=True)
class VerifyRuntime:
    """Shared observation handles, plus the stack each half of verify needs.

    The stacks are built on demand rather than up front: the benchmark one
    resolves a live provider, and that must not be attempted until preflight has
    passed and the provider check has confirmed a credential exists.
    """

    options: VerifyOptions
    trace_state: InterceptionTraceState
    call_recorder: CallRecorder
    secret_resolver: OfflineSecretResolver
    trace_sink: TraceSink
    environ: Mapping[str, str]

    @property
    def captured_pair_count(self) -> int:
        """Matched ``llm_request``/``llm_response`` pairs seen across the run."""

        return self.trace_state.checkpoint()

    @property
    def calls(self) -> tuple[CallRecord, ...]:
        """Completed calls, retained for the post-run report."""

        return tuple(self.call_recorder.records)

    @property
    def substituted_secrets(self) -> tuple[str, ...]:
        return self.secret_resolver.substituted

    def preflight_runner(self) -> AgentRunner:
        """The stack preflight drives: synthesized replies, egress blocked.

        No Providers and no SDK Run appear here. Preflight invokes the adapter
        directly, which is what lets it answer for the Agent before any
        credential has been configured.
        """

        return AgentRunner(
            runtime_factory=self._runtime_factory(
                StaticModelTargetProvider(_offline_target()), "blocked"
            )
        )

    def benchmark_suite_runner(self, chat: ChatModel) -> SuiteRunner:
        """The graded stack: a live provider, egress open, local Case and Judge.

        Passing both Providers is what selects the SDK's local mode, which never
        reads ``DEFUZEX_API_KEY`` and never opens a Backend connection.
        """

        return LocalBenchmarkSuiteRunner(
            benchmark_runner=BenchmarkRunner(
                agent_runner=AgentRunner(
                    runtime_factory=self._runtime_factory(
                        DeepSeekProvider(self.options.model), "open"
                    )
                )
            ),
            model=chat,
            max_inputs=self.options.input_count,
        )

    def _runtime_factory(
        self, model_provider: ModelTargetProvider, egress: EgressMode
    ) -> RuntimeFactory:
        return RuntimeFactory(
            docker_builder=_VerifyDockerBuilder(
                secret_resolver=self.secret_resolver,
                model_provider=model_provider,
                egress=egress,
                trace_sink=self.trace_sink,
                trace_max_bytes=self.options.llm_trace_max_bytes,
            )
        )


def build_verify_runtime(
    options: VerifyOptions | None = None,
    *,
    output_fn: Callable[[str], None],
    activity_sink: TraceSink | None = None,
    environ: Mapping[str, str] | None = None,
) -> VerifyRuntime:
    """Wire the observation handles both halves of a verification share.

    Options are validated here rather than in ``VerifyOptions`` so that a bad
    combination still surfaces through ``verify``'s error path as a report, not
    as a traceback from wherever the options happened to be constructed.
    """

    options = options or VerifyOptions()
    if options.llm_trace not in TRACE_MODES:
        raise ValueError(f"Unsupported LLM trace mode: {options.llm_trace!r}")

    values = os.environ if environ is None else environ
    # The offline target never contacts a provider, so its credential is
    # synthetic. Seeding it here keeps it out of the resolver's
    # substituted-secret report, which is reserved for genuinely missing Agent
    # configuration.
    overlay = {OFFLINE_UPSTREAM_KEY_ENV: OFFLINE_UPSTREAM_KEY_VALUE}

    # Counting pairs here is independent of the runtime's own required-trace gate,
    # so the CLI can report how much model traffic verification actually observed.
    trace_state = InterceptionTraceState()
    call_recorder = CallRecorder()
    return VerifyRuntime(
        options=options,
        trace_state=trace_state,
        call_recorder=call_recorder,
        secret_resolver=OfflineSecretResolver({**values, **overlay}),
        trace_sink=CompositeTraceSink(
            _trace_sinks(
                trace_state,
                call_recorder,
                activity_sink=activity_sink,
                output_fn=output_fn,
                llm_trace=options.llm_trace,
            )
        ),
        environ=values,
    )


def _offline_target() -> ModelTargetConfig:
    return ModelTargetConfig(
        provider_id=OFFLINE_PROVIDER_ID,
        target_plugin=OFFLINE_TARGET_PLUGIN,
        base_url=OFFLINE_BASE_URL,
        model=OFFLINE_MODEL,
        credential_env=OFFLINE_UPSTREAM_KEY_ENV,
    )


def _trace_sinks(
    *required: TraceSink,
    activity_sink: TraceSink | None,
    output_fn: Callable[[str], None],
    llm_trace: str,
) -> tuple[TraceSink, ...]:
    sinks = list(required)
    if activity_sink is not None:
        sinks.append(activity_sink)
    if llm_trace == "terminal":
        # Only route through the live panel when it actually owns the terminal.
        # Otherwise its static path may be silenced, which would drop the trace
        # the caller explicitly asked for.
        sinks.append(TerminalTraceSink(_trace_output(activity_sink, output_fn)))
    return tuple(sinks)


def _trace_output(
    activity_sink: TraceSink | None, output_fn: Callable[[str], None]
) -> Callable[[str], None]:
    write_static = getattr(activity_sink, "write_static", None)
    if callable(write_static) and getattr(activity_sink, "live", False):
        return write_static
    return output_fn


@dataclass(frozen=True, slots=True)
class _VerifyDockerBuilder:
    """Build the runtime while holding only what it needs.

    A closure here would keep the whole of ``build_verify_runtime``'s scope alive
    for as long as the factory does.
    """

    secret_resolver: OfflineSecretResolver
    model_provider: ModelTargetProvider
    egress: EgressMode
    trace_sink: TraceSink
    trace_max_bytes: int

    def __call__(self) -> DockerRuntime:
        return DockerRuntime(
            secret_resolver=self.secret_resolver,
            model_provider=self.model_provider,
            trace_sink=self.trace_sink,
            trace_max_bytes=self.trace_max_bytes,
            egress=self.egress,
        )



__all__ = [
    "DEEPSEEK_API_KEY_ENV",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_INPUT_COUNT",
    "DEFAULT_PROBE_COUNT",
    "DEFAULT_PROBE_TEXT",
    "OFFLINE_MODEL",
    "OFFLINE_TARGET_PLUGIN",
    "OFFLINE_UPSTREAM_KEY_ENV",
    "TRACE_MODES",
    "VerifyOptions",
    "VerifyRuntime",
    "build_verify_runtime",
]
