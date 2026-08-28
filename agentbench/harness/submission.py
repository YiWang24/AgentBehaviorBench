"""Whether one committed Submission actually answered its Input.

Both Judge Providers have to decide this, and they have to decide it the same
way. When they disagree, the same Run passes startup verification and is then
graded as having produced nothing — a contradiction the Agent's author has no
way to act on, because neither verdict is about the Agent.

The question here is only whether an answer arrived. Whether the answer is any
good belongs to a rubric.
"""

from __future__ import annotations

from typing import Any

COMPLETED = "completed"


def is_blank(output: Any) -> bool:
    """Treat only genuinely absent output as missing.

    Agents return strings, mappings, and framework state objects alike. An empty
    container is absence — an Agent that returned ``[]`` answered nothing — while
    a falsy scalar such as ``0`` is a real answer and must not be confused with
    one.
    """

    if output is None:
        return True
    if isinstance(output, str):
        return not output.strip()
    if isinstance(output, (list, tuple, dict, set)):
        return len(output) == 0
    return False


def answered(item: Any) -> bool:
    """True when the step ran to completion and carried usable output."""

    submission = item.submission
    return submission.status == COMPLETED and not is_blank(submission.output)


def failure_reason(item: Any) -> str:
    """Why a step did not answer, as a clause a caller prefixes with a subject.

    Only meaningful when :func:`answered` is False.
    """

    submission = item.submission
    if submission.status != COMPLETED:
        return (
            f"finished as {submission.status!r}: "
            f"{submission.error or 'no error reported'}"
        )
    return "completed but returned no usable output"


__all__ = ["COMPLETED", "answered", "failure_reason", "is_blank"]
