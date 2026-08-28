"""DefuzeX SDK interfaces consumed by AgentBench."""

from __future__ import annotations

from typing import Protocol

# The one report status that means the Judge raised nothing. Every other value
# the SDK can report is a finding, so callers compare against this rather than
# enumerating the alternatives.
STATUS_PASS = "pass"


class SDKReport(Protocol):
    """Public report fields consumed by AgentBench."""

    status: str
    confidence: object
    issues: tuple[object, ...]
    evidence_gaps: tuple[object, ...]


class SDKTestInput(Protocol):
    """Public SDK input fields consumed by AgentBench."""

    input_id: str
    payload: object


class SDKRun(Protocol):
    """Strict-handshake subset of a DefuzeX SDK Run."""

    run_id: str
    state: str
    report: SDKReport | None
    history: tuple[object, ...]

    def get_input(self, *, full: bool = False) -> SDKTestInput | None:
        ...

    def submit(
        self,
        output: object = None,
        *,
        status: str = "completed",
        error: str | None = None,
    ) -> SDKReport | None:
        ...


class SDKRunFactory(Protocol):
    """Callable shape of ``defuzex.create_run``."""

    def __call__(self, **kwargs: object) -> SDKRun:
        ...
