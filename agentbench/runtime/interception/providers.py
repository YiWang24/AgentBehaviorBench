"""Run-level model target provider contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable
from urllib.parse import urlsplit

from .config import InterceptionConfigurationError


OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_MODEL_ENV = "OPENROUTER_MODEL"
OPENROUTER_BASE_URL_ENV = "OPENROUTER_BASE_URL"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"


@dataclass(frozen=True, slots=True)
class ModelTargetConfig:
    provider_id: str
    target_plugin: str
    base_url: str
    model: str
    credential_env: str
    headers: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


@runtime_checkable
class ModelTargetProvider(Protocol):
    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        ...


def _validated_model(model: str, *, label: str) -> str:
    """A model name with no embedded whitespace, which no provider accepts."""

    model = model.strip()
    if any(character.isspace() for character in model):
        raise InterceptionConfigurationError(
            f"{label} model must not contain whitespace: {model!r}"
        )
    return model


def _validated_base_url(raw: str, *, default: str, env_name: str) -> str:
    """An absolute HTTPS base URL, with no trailing slash.

    An empty or blank override falls back to the default rather than failing:
    an exported-but-unset variable is the same as not setting one.
    """

    base_url = raw.strip() or default
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InterceptionConfigurationError(
            f"{env_name} must be an absolute HTTPS URL"
        )
    return base_url.rstrip("/")


@dataclass(frozen=True, slots=True)
class OpenRouterProvider:
    """Resolve one model-controlled OpenRouter target for a benchmark run."""

    model: str | None = None

    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        model = _validated_model(
            self.model or environ.get(OPENROUTER_MODEL_ENV, ""), label="OpenRouter"
        )
        if not model:
            raise InterceptionConfigurationError(
                "OpenRouter model is required; pass --model or set OPENROUTER_MODEL"
            )

        base_url = _validated_base_url(
            environ.get(OPENROUTER_BASE_URL_ENV, ""),
            default=DEFAULT_OPENROUTER_BASE_URL,
            env_name=OPENROUTER_BASE_URL_ENV,
        )

        headers: dict[str, str] = {}
        referer = environ.get("OPENROUTER_HTTP_REFERER", "").strip()
        title = environ.get("OPENROUTER_APP_TITLE", "").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-OpenRouter-Title"] = title

        return ModelTargetConfig(
            provider_id="openrouter",
            target_plugin="openrouter",
            base_url=base_url,
            model=model,
            credential_env=OPENROUTER_API_KEY_ENV,
            headers=MappingProxyType(headers),
        )


@dataclass(frozen=True, slots=True)
class DeepSeekProvider:
    """Resolve a DeepSeek target for a run that needs real model replies.

    DeepSeek serves the OpenAI chat wire format, so it reuses the same generic
    target adapter as OpenRouter. It exposes no ``/responses`` or ``/messages``
    endpoint, so Agents whose manifest declares those source protocols cannot be
    routed here; the interceptor rejects them rather than guessing a translation.
    """

    model: str | None = None

    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        return ModelTargetConfig(
            provider_id="deepseek",
            target_plugin="deepseek",
            base_url=_validated_base_url(
                environ.get(DEEPSEEK_BASE_URL_ENV, ""),
                default=DEFAULT_DEEPSEEK_BASE_URL,
                env_name=DEEPSEEK_BASE_URL_ENV,
            ),
            model=_validated_model(
                self.model
                or environ.get(DEEPSEEK_MODEL_ENV, "")
                or DEFAULT_DEEPSEEK_MODEL,
                label="DeepSeek",
            ),
            credential_env=DEEPSEEK_API_KEY_ENV,
        )


@dataclass(frozen=True, slots=True)
class StaticModelTargetProvider:
    """Supply an already validated target, primarily for deployments and tests."""

    target: ModelTargetConfig

    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        del environ
        return self.target
