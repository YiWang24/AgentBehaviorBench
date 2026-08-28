"""DefuzeX SDK Provider ports, described structurally.

The SDK adapts any object exposing ``generate_case`` or ``judge``, so AgentBench
states the shapes it consumes here instead of importing ``defuzex``. That keeps
Agent-only usage free of the SDK, exactly as :mod:`agentbench.harness.protocols.sdk`
does for the Run handshake.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol


class CaseGenerationContext(Protocol):
    """Validated local inputs handed to a Case Provider before any Input exists."""

    repo_path: Path
    repo_meta: Mapping[str, Any]
    requirement: str | None
    input_type: str
    input_schema: Mapping[str, Any] | None
    max_inputs: int
    agent_description: str | None
    requirement_sections: Mapping[str, str]


class SubmissionLike(Protocol):
    """The committed half of one history entry."""

    status: str
    output: Any
    error: str | None


class HistoryItemLike(Protocol):
    """One Input/Submission pair from a completed Run."""

    test_input: Any
    submission: SubmissionLike


class JudgeContext(Protocol):
    """Immutable completed Run history handed to a Judge Provider."""

    history: Sequence[HistoryItemLike]
    run_status: str


__all__ = [
    "CaseGenerationContext",
    "HistoryItemLike",
    "JudgeContext",
    "SubmissionLike",
]
