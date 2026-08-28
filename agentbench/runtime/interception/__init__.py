"""Transparent model interception configuration and lifecycle contracts."""

from .config import (
    CredentialConfig,
    InterceptionConfig,
    InterceptionConfigurationError,
    RouteConfig,
)
from .image import InterceptorImageProvider, StaticInterceptorImageProvider
from .plugins import TrustPlugin, get_trust_plugin
from .providers import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL_ENV,
    DEEPSEEK_MODEL_ENV,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_OPENROUTER_BASE_URL,
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_BASE_URL_ENV,
    OPENROUTER_MODEL_ENV,
    DeepSeekProvider,
    ModelTargetConfig,
    ModelTargetProvider,
    OpenRouterProvider,
    StaticModelTargetProvider,
)
from .session import RunningModelInterceptor
from .trace import (
    DEFAULT_TRACE_MAX_BYTES,
    InterceptionTraceState,
    NullTraceSink,
    TerminalTraceSink,
    TraceEvent,
    TraceSink,
)

__all__ = [
    "CredentialConfig",
    "DEEPSEEK_API_KEY_ENV",
    "DEEPSEEK_BASE_URL_ENV",
    "DEEPSEEK_MODEL_ENV",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_TRACE_MAX_BYTES",
    "DeepSeekProvider",
    "InterceptionConfig",
    "InterceptionConfigurationError",
    "InterceptionTraceState",
    "InterceptorImageProvider",
    "ModelTargetConfig",
    "ModelTargetProvider",
    "NullTraceSink",
    "OpenRouterProvider",
    "OPENROUTER_API_KEY_ENV",
    "OPENROUTER_BASE_URL_ENV",
    "OPENROUTER_MODEL_ENV",
    "DEFAULT_OPENROUTER_BASE_URL",
    "RouteConfig",
    "RunningModelInterceptor",
    "StaticInterceptorImageProvider",
    "StaticModelTargetProvider",
    "TerminalTraceSink",
    "TraceEvent",
    "TraceSink",
    "TrustPlugin",
    "get_trust_plugin",
]
