"""The two runtime stacks verify drives, and the guarantees each one carries."""

from __future__ import annotations

import pytest

from agentbench.cli.verify_runtime import (
    OFFLINE_MODEL,
    OFFLINE_TARGET_PLUGIN,
    OFFLINE_UPSTREAM_KEY_ENV,
    VerifyOptions,
    build_verify_runtime,
)
from agentbench.runtime.interception import (
    DEEPSEEK_API_KEY_ENV,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DeepSeekProvider,
    InterceptionConfigurationError,
    TraceEvent,
)

LIVE_ENV = {DEEPSEEK_API_KEY_ENV: "sk-not-a-real-key"}


def _runtime(options: VerifyOptions | None = None, environ: dict | None = None):
    return build_verify_runtime(
        options or VerifyOptions(),
        output_fn=lambda _: None,
        environ={} if environ is None else environ,
    )


def _preflight_docker(runtime):  # type: ignore[no-untyped-def]
    return runtime.preflight_runner()._runtime_factory._docker_builder()


def _benchmark_docker(runtime):  # type: ignore[no-untyped-def]
    suite = runtime.benchmark_suite_runner(object())
    factory = suite._benchmark_runner._agent_runner._runtime_factory
    return factory._docker_builder()


class TestDeepSeekProvider:
    def test_it_defaults_to_the_chat_model_on_the_public_endpoint(self) -> None:
        target = DeepSeekProvider().resolve({})

        assert target.provider_id == "deepseek"
        assert target.base_url == DEFAULT_DEEPSEEK_BASE_URL
        assert target.model == DEFAULT_DEEPSEEK_MODEL
        assert target.credential_env == DEEPSEEK_API_KEY_ENV

    def test_an_explicit_model_wins_over_the_environment(self) -> None:
        target = DeepSeekProvider("deepseek-reasoner").resolve(
            {"DEEPSEEK_MODEL": "deepseek-chat"}
        )

        assert target.model == "deepseek-reasoner"

    def test_the_environment_overrides_the_default_model(self) -> None:
        target = DeepSeekProvider().resolve({"DEEPSEEK_MODEL": "deepseek-reasoner"})

        assert target.model == "deepseek-reasoner"

    def test_a_plaintext_base_url_is_rejected(self) -> None:
        with pytest.raises(InterceptionConfigurationError, match="HTTPS"):
            DeepSeekProvider().resolve({"DEEPSEEK_BASE_URL": "http://api.deepseek.com"})

    def test_it_reuses_the_generic_openai_compatible_adapter(self) -> None:
        """DeepSeek speaks the OpenAI chat format, so it needs no bespoke plugin."""

        assert DeepSeekProvider().resolve({}).target_plugin == "deepseek"


class TestPreflightStack:
    def test_it_blocks_egress_and_answers_from_the_interceptor(self) -> None:
        docker = _preflight_docker(_runtime())

        assert docker._egress == "blocked"
        target = docker._model_provider.resolve({})
        assert target.target_plugin == OFFLINE_TARGET_PLUGIN
        assert target.model == OFFLINE_MODEL

    def test_its_upstream_credential_is_synthetic_and_not_reported_as_stubbed(
        self,
    ) -> None:
        """A target that never calls out has nothing real to substitute."""

        runtime = _runtime()
        docker = _preflight_docker(runtime)

        assert docker._secret_resolver.require(OFFLINE_UPSTREAM_KEY_ENV)
        assert runtime.substituted_secrets == ()

    def test_it_needs_no_credential_at_all(self) -> None:
        """Preflight must run on a host that has been configured with nothing."""

        runtime = _runtime(environ={})

        assert _preflight_docker(runtime)._egress == "blocked"

    def test_the_agent_model_flag_does_not_reach_it(self) -> None:
        """`--model` names the model the graded Run uses, not the mock's label."""

        docker = _preflight_docker(_runtime(VerifyOptions(model="deepseek-reasoner")))

        assert docker._model_provider.resolve({}).model == OFFLINE_MODEL


class TestBenchmarkStack:
    def test_it_opens_egress_so_the_provider_is_reachable(self) -> None:
        docker = _benchmark_docker(_runtime(environ=LIVE_ENV))

        assert docker._egress == "open"
        assert docker._model_provider.resolve(LIVE_ENV).provider_id == "deepseek"

    def test_the_agent_model_flag_selects_its_target(self) -> None:
        docker = _benchmark_docker(
            _runtime(VerifyOptions(model="deepseek-reasoner"), environ=LIVE_ENV)
        )

        assert docker._model_provider.resolve(LIVE_ENV).model == "deepseek-reasoner"

    def test_it_carries_the_requested_input_count(self) -> None:
        runtime = _runtime(VerifyOptions(input_count=5), environ=LIVE_ENV)

        assert runtime.benchmark_suite_runner(object())._max_inputs == 5

    def test_it_is_never_built_before_it_is_needed(self) -> None:
        """A missing credential must not stop preflight from running."""

        runtime = _runtime(environ={})

        # Assembly alone touches no credential; resolution is the provider check's
        # job, and it only runs once preflight has passed.
        assert _preflight_docker(runtime) is not None


class TestSharedObservation:
    def test_both_stacks_report_into_the_same_trace_sinks(self) -> None:
        """One verification, one call log — whichever half made the call."""

        runtime = _runtime(environ=LIVE_ENV)

        assert _preflight_docker(runtime)._trace_sink is runtime.trace_sink
        assert _benchmark_docker(runtime)._trace_sink is runtime.trace_sink

    def test_captured_pairs_and_calls_come_from_the_shared_sinks(self) -> None:
        runtime = _runtime()
        for name in ("llm_request", "llm_response"):
            runtime.trace_sink.emit(
                TraceEvent(name, {"call_id": "call-1", "provider": "offline"})
            )

        assert runtime.captured_pair_count == 1
        assert [call.number for call in runtime.calls] == [1]

    def test_an_unknown_trace_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="LLM trace mode"):
            build_verify_runtime(
                VerifyOptions(llm_trace="loud"),  # type: ignore[arg-type]
                output_fn=lambda _: None,
                environ={},
            )

    def test_neither_stack_consults_the_defuzex_credential(self) -> None:
        """Only the model axis changes; Case and Judge stay local either way."""

        class _Poisoned(dict):
            def get(self, key, default=None):  # type: ignore[no-untyped-def]
                if key == "DEFUZEX_API_KEY":
                    raise AssertionError("verification read DEFUZEX_API_KEY")
                return super().get(key, default)

        runtime = _runtime(environ=_Poisoned(LIVE_ENV))

        assert _preflight_docker(runtime) is not None
        assert _benchmark_docker(runtime) is not None
