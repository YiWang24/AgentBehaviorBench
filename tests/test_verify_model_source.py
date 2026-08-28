"""Selecting a live model source, and the guarantees it changes."""

from __future__ import annotations

import pytest

from agentbench.cli.verify_runtime import (
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
)

LIVE_ENV = {DEEPSEEK_API_KEY_ENV: "sk-not-a-real-key"}


def _docker_runtime(runtime):  # type: ignore[no-untyped-def]
    factory = runtime.runner._benchmark_runner._agent_runner._runtime_factory
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


class TestModelSourceSelection:
    def test_offline_blocks_egress_and_uses_a_synthetic_credential(self) -> None:
        runtime = build_verify_runtime(
            VerifyOptions(input_count=1), output_fn=lambda _: None, environ={}
        )
        docker = _docker_runtime(runtime)

        assert runtime.offline is True
        assert docker._egress == "blocked"
        assert docker._model_provider.resolve({}).target_plugin == OFFLINE_TARGET_PLUGIN
        assert docker._secret_resolver.require(OFFLINE_UPSTREAM_KEY_ENV)
        assert runtime.substituted_secrets == ()

    def test_a_live_source_opens_egress_so_the_provider_is_reachable(self) -> None:
        runtime = build_verify_runtime(
            VerifyOptions(input_count=1, model_source="deepseek"),
            output_fn=lambda _: None,
            environ=LIVE_ENV,
        )
        docker = _docker_runtime(runtime)

        assert runtime.offline is False
        assert runtime.model == DEFAULT_DEEPSEEK_MODEL
        assert docker._egress == "open"
        assert docker._model_provider.resolve(LIVE_ENV).provider_id == "deepseek"

    def test_a_live_source_without_its_credential_fails_before_any_build(self) -> None:
        """A missing key must not surface as a 401 inside the container."""

        with pytest.raises(InterceptionConfigurationError, match=DEEPSEEK_API_KEY_ENV):
            build_verify_runtime(
                VerifyOptions(input_count=1, model_source="deepseek"),
                output_fn=lambda _: None,
                environ={},
            )

    def test_a_blank_credential_counts_as_missing(self) -> None:
        with pytest.raises(InterceptionConfigurationError):
            build_verify_runtime(
                VerifyOptions(input_count=1, model_source="deepseek"),
                output_fn=lambda _: None,
                environ={DEEPSEEK_API_KEY_ENV: "   "},
            )

    def test_benchmark_mode_refuses_the_offline_source(self) -> None:
        """Grading synthetic replies would say nothing about the Agent."""

        with pytest.raises(ValueError, match="offline source"):
            build_verify_runtime(
                VerifyOptions(input_count=3, mode="benchmark", model_source="offline"),
                output_fn=lambda _: None,
                environ=LIVE_ENV,
            )

    def test_benchmark_mode_needs_a_provider_credential(self) -> None:
        with pytest.raises(Exception, match=DEEPSEEK_API_KEY_ENV):
            build_verify_runtime(
                VerifyOptions(input_count=3, mode="benchmark", model_source="deepseek"),
                output_fn=lambda _: None,
                environ={},
            )

    def test_benchmark_mode_records_which_model_graded_the_run(self) -> None:
        runtime = build_verify_runtime(
            VerifyOptions(
                input_count=3,
                mode="benchmark",
                model_source="deepseek",
                provider_model="deepseek-reasoner",
            ),
            output_fn=lambda _: None,
            environ=LIVE_ENV,
        )

        assert runtime.mode == "benchmark"
        assert runtime.provider_model == "deepseek-reasoner"
        # The Agent's model and the grading model are separate choices.
        assert runtime.model == DEFAULT_DEEPSEEK_MODEL

    def test_startup_mode_names_no_grading_model(self) -> None:
        runtime = build_verify_runtime(
            VerifyOptions(input_count=1), output_fn=lambda _: None, environ={}
        )

        assert runtime.mode == "startup"
        assert runtime.provider_model is None

    def test_an_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="verify mode"):
            build_verify_runtime(
                VerifyOptions(input_count=1, mode="vibes"),
                output_fn=lambda _: None,  # type: ignore[arg-type]
                environ={},
            )

    def test_an_unknown_source_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="model source"):
            build_verify_runtime(
                VerifyOptions(input_count=1, model_source="gpt5"),
                output_fn=lambda _: None,  # type: ignore[arg-type]
                environ={},
            )

    def test_a_live_source_never_consults_the_defuzex_credential(self) -> None:
        """Only the model axis changes; Case and Judge stay local either way."""

        class _Poisoned(dict):
            def get(self, key, default=None):  # type: ignore[no-untyped-def]
                if key == "DEFUZEX_API_KEY":
                    raise AssertionError("live verification read DEFUZEX_API_KEY")
                return super().get(key, default)

        runtime = build_verify_runtime(
            VerifyOptions(input_count=1, model_source="deepseek"),
            output_fn=lambda _: None,
            environ=_Poisoned(LIVE_ENV),
        )

        assert runtime.offline is False
