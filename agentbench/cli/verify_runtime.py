"""Assemble the benchmark runner that `verify` drives.

Two axes vary here and nothing else does. The Case and Judge Providers are always
local, which is what keeps ``DEFUZEX_API_KEY`` out of every verification. The model
replies are either synthesized inside the interceptor with egress blocked, or
fetched from a real provider with egress open. Everything downstream — the SDK Run,
the handshake, the trace sinks, the call recorder — is identical either way.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from agentbench.harness import AgentRunner, BenchmarkRunner, SuiteRunner
from agentbench.harness.offline import (
    DEFAULT_PROBE_TEXT,
    OfflineSecretResolver,
    OfflineSuiteRunner,
)
from agentbench.cli.TerminalUI.call_log import CallRecord, CallRecorder
from agentbench.runtime import RuntimeFactory
from agentbench.runtime.docker import DockerRuntime
from agentbench.runtime.docker.runtime import EgressMode
from agentbench.runtime.interception import (
    DEEPSEEK_API_KEY_ENV,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_TRACE_MAX_BYTES,
    DeepSeekProvider,
    InterceptionConfigurationError,
    InterceptionTraceState,
    ModelTargetConfig,
    ModelTargetProvider,
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

ModelSource = Literal["offline", "deepseek"]
MODEL_SOURCES: tuple[ModelSource, ...] = ("offline", "deepseek")

OFFLINE_SOURCE: ModelSource = "offline"
LIVE_SOURCE: ModelSource = "deepseek"

VerifyMode = Literal["startup", "benchmark"]
VERIFY_MODES: tuple[VerifyMode, ...] = ("startup", "benchmark")

STARTUP_MODE: VerifyMode = "startup"
BENCHMARK_MODE: VerifyMode = "benchmark"


@dataclass(frozen=True)
class VerifyRuntime:
    """The runner plus the handles the CLI needs to report on a verification."""

    runner: SuiteRunner
    trace_state: InterceptionTraceState
    secret_resolver: OfflineSecretResolver
    call_recorder: CallRecorder
    model_source: ModelSource = OFFLINE_SOURCE
    model: str = OFFLINE_MODEL
    mode: VerifyMode = STARTUP_MODE
    # The model that wrote the Case and graded the Run, which is a different
    # question from the model the Agent itself talked to.
    provider_model: str | None = None

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

    @property
    def offline(self) -> bool:
        return self.model_source == OFFLINE_SOURCE


def build_verify_runtime(
    *,
    max_inputs: int,
    probe_text: str = DEFAULT_PROBE_TEXT,
    output_fn: Callable[[str], None],
    mode: VerifyMode = STARTUP_MODE,
    model_source: ModelSource = OFFLINE_SOURCE,
    llm_trace: str = "off",
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES,
    activity_sink: TraceSink | None = None,
    model: str | None = None,
    provider_model: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> VerifyRuntime:
    """Wire a runner that needs no DefuzeX credentials, online or offline."""

    if llm_trace not in {"off", "terminal"}:
        raise ValueError(f"Unsupported LLM trace mode: {llm_trace!r}")
    if model_source not in MODEL_SOURCES:
        raise ValueError(f"Unsupported model source: {model_source!r}")
    if mode not in VERIFY_MODES:
        raise ValueError(f"Unsupported verify mode: {mode!r}")
    if mode == BENCHMARK_MODE and model_source == OFFLINE_SOURCE:
        raise ValueError(
            "Benchmark mode grades what the Agent actually said, and the offline "
            "source answers every request with the same synthetic text. Pass "
            f"--model-source {LIVE_SOURCE}, or use --mode {STARTUP_MODE}."
        )

    values = os.environ if environ is None else environ
    provider, egress, overlay, label = _model_plan(model_source, model, values)

    # Counting pairs here is independent of the runtime's own required-trace gate,
    # so the CLI can report how much model traffic verification actually observed.
    trace_state = InterceptionTraceState()
    call_recorder = CallRecorder()
    secret_resolver = OfflineSecretResolver({**values, **overlay})
    benchmark_runner = BenchmarkRunner(
        agent_runner=AgentRunner(
            runtime_factory=RuntimeFactory(
                docker_builder=_VerifyDockerBuilder(
                    secret_resolver=secret_resolver,
                    model_provider=provider,
                    egress=egress,
                    trace_sink=_CompositeTraceSink(
                        _trace_sinks(
                            trace_state,
                            call_recorder,
                            activity_sink=activity_sink,
                            output_fn=output_fn,
                            llm_trace=llm_trace,
                        )
                    ),
                    trace_max_bytes=llm_trace_max_bytes,
                )
            )
        ),
        # The SDK itself owns the Run: only the Provider pair is local, which is
        # what keeps the whole path free of DefuzeX credentials and networking.
    )
    runner, provider_label = _suite_runner(
        mode,
        benchmark_runner=benchmark_runner,
        max_inputs=max_inputs,
        probe_text=probe_text,
        provider_model=provider_model,
        environ=values,
    )
    return VerifyRuntime(
        runner=runner,
        trace_state=trace_state,
        secret_resolver=secret_resolver,
        call_recorder=call_recorder,
        model_source=model_source,
        model=label,
        mode=mode,
        provider_model=provider_label,
    )


def _suite_runner(
    mode: VerifyMode,
    *,
    benchmark_runner: BenchmarkRunner,
    max_inputs: int,
    probe_text: str,
    provider_model: str | None,
    environ: Mapping[str, str],
) -> tuple[SuiteRunner, str | None]:
    """Pick which pair of Providers drives the Run.

    Both branches leave the shared execution path untouched; only the two
    Provider ports differ, which is what makes a local Run comparable to an
    official one.
    """

    if mode == STARTUP_MODE:
        return (
            OfflineSuiteRunner(
                benchmark_runner=benchmark_runner,
                max_inputs=max_inputs,
                probe_text=probe_text,
            ),
            None,
        )

    # Imported here because it pulls in the DefuzeX SDK, which the startup path
    # and every Agent-only caller must keep out of their import graph.
    from agentbench.harness.local import ChatModel, LocalBenchmarkSuiteRunner

    chat = ChatModel.from_environment(environ, model=provider_model)
    return (
        LocalBenchmarkSuiteRunner(
            benchmark_runner=benchmark_runner,
            model=chat,
            max_inputs=max_inputs,
        ),
        chat.model,
    )


def _model_plan(
    model_source: ModelSource,
    model: str | None,
    environ: Mapping[str, str],
) -> tuple[ModelTargetProvider, EgressMode, Mapping[str, str], str]:
    """Choose the target, the egress policy, and any synthetic credential."""

    if model_source == OFFLINE_SOURCE:
        target = _offline_target(model)
        # The offline target never contacts a provider, so its credential is
        # synthetic. Seeding it here keeps it out of the resolver's
        # substituted-secret report, which is reserved for genuinely missing
        # Agent configuration.
        overlay = {OFFLINE_UPSTREAM_KEY_ENV: OFFLINE_UPSTREAM_KEY_VALUE}
        return StaticModelTargetProvider(target), "blocked", overlay, target.model

    provider = DeepSeekProvider(model)
    # Resolving now turns a missing key or a bad model into an error before an
    # image is built, instead of a 401 inside the container minutes later.
    resolved = provider.resolve(environ)
    _require_credential(resolved.credential_env, environ)
    return provider, "open", {}, resolved.model


def _require_credential(name: str, environ: Mapping[str, str]) -> None:
    if environ.get(name, "").strip():
        return
    raise InterceptionConfigurationError(
        f"A live model run needs {name}. Set it in the environment or .env, or "
        "drop --model-source to verify against the offline mock."
    )


def _offline_target(model: str | None) -> ModelTargetConfig:
    return ModelTargetConfig(
        provider_id=OFFLINE_PROVIDER_ID,
        target_plugin=OFFLINE_TARGET_PLUGIN,
        base_url=OFFLINE_BASE_URL,
        model=(model or OFFLINE_MODEL).strip() or OFFLINE_MODEL,
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


@dataclass(frozen=True, slots=True)
class _CompositeTraceSink:
    sinks: tuple[TraceSink, ...]

    def emit(self, event: TraceEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)


__all__ = [
    "BENCHMARK_MODE",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEEPSEEK_API_KEY_ENV",
    "LIVE_SOURCE",
    "MODEL_SOURCES",
    "OFFLINE_SOURCE",
    "OFFLINE_TARGET_PLUGIN",
    "OFFLINE_UPSTREAM_KEY_ENV",
    "STARTUP_MODE",
    "VERIFY_MODES",
    "ModelSource",
    "VerifyMode",
    "VerifyRuntime",
    "build_verify_runtime",
]
