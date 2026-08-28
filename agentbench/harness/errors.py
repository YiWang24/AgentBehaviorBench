"""Errors raised by AgentBench harness orchestration, and how they are named."""


def error_detail(exc: Exception) -> str:
    """Name the exception, and its message when it carries one.

    Every stage that reports a failure to a caller formats it this way. Keeping
    one definition is what stops two phases of the same run from describing the
    same exception differently — a bare message in one, a qualified name in the
    other — which reads as two unrelated faults.
    """

    message = str(exc).strip()
    return type(exc).__name__ if not message else f"{type(exc).__name__}: {message}"


class AgentStartError(RuntimeError):
    """Raised when a registered agent cannot be loaded."""


class AgentNotRunningError(RuntimeError):
    """Raised when a stopped agent is invoked."""


class AgentInvocationError(RuntimeError):
    """Raised when an agent fails while processing an SDK input."""


class ProviderSelectionError(RuntimeError):
    """Raised before agent startup when no valid provider mode is available."""


class SuiteConfigurationError(RuntimeError):
    """Raised when shared suite configuration fails preflight validation."""
