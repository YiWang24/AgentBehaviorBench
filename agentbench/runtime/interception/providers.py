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


@dataclass(frozen=True, slots=True)
class OpenRouterProvider:
    """Resolve one model-controlled OpenRouter target for a benchmark run."""

    model: str | None = None

    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        model = (self.model or environ.get(OPENROUTER_MODEL_ENV, "")).strip()
        if not model:
            raise InterceptionConfigurationError(
                "OpenRouter model is required; pass --model or set OPENROUTER_MODEL"
            )
        if any(character.isspace() for character in model):
            raise InterceptionConfigurationError(
                f"OpenRouter model must not contain whitespace: {model!r}"
            )

        base_url = environ.get(
            OPENROUTER_BASE_URL_ENV, DEFAULT_OPENROUTER_BASE_URL
        ).strip()
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise InterceptionConfigurationError(
                "OPENROUTER_BASE_URL must be an absolute HTTPS URL"
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
            base_url=base_url.rstrip("/"),
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
        model = (
            self.model or environ.get(DEEPSEEK_MODEL_ENV, "") or DEFAULT_DEEPSEEK_MODEL
        ).strip()
        if any(character.isspace() for character in model):
            raise InterceptionConfigurationError(
                f"DeepSeek model must not contain whitespace: {model!r}"
            )

        base_url = (
            environ.get(DEEPSEEK_BASE_URL_ENV, "").strip() or DEFAULT_DEEPSEEK_BASE_URL
        )
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise InterceptionConfigurationError(
                f"{DEEPSEEK_BASE_URL_ENV} must be an absolute HTTPS URL"
            )

        return ModelTargetConfig(
            provider_id="deepseek",
            target_plugin="deepseek",
            base_url=base_url.rstrip("/"),
            model=model,
            credential_env=DEEPSEEK_API_KEY_ENV,
        )


@dataclass(frozen=True, slots=True)
class StaticModelTargetProvider:
    """Supply an already validated target, primarily for deployments and tests."""

    target: ModelTargetConfig

    def resolve(self, environ: Mapping[str, str]) -> ModelTargetConfig:
        del environ
        return self.target
