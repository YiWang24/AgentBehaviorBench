"""A local SDK Run that verifies Agent startup without any DefuzeX service.

``BenchmarkRunner`` already supports a ``local`` provider mode that never reads
``DEFUZEX_API_KEY``; it only requires a Case Provider, a Judge Provider and an input
budget. This module supplies all three locally, so startup verification needs no
official credentials and no installed SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


DEFAULT_PROBE_TEXT = "Reply with a short confirmation that you received this message."
PROBE_INPUT_PREFIX = "offline-probe"

_PASS = "pass"
_FAIL = "fail"


@dataclass(frozen=True, slots=True)
class OfflineTestInput:
    """One locally generated SDK Input."""

    input_id: str
    payload: object


@dataclass(frozen=True, slots=True)
class OfflineReport:
    """Startup verdict shaped like an SDK report.

    ``pass`` means the adapter and runtime are healthy, not that Agent output has
    any benchmark quality. Nothing here judges the content of a reply.
    """

    status: str
    confidence: object = None
    issues: tuple[object, ...] = ()
    evidence_gaps: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class OfflineHistoryEntry:
    """One submitted step, kept locally instead of uploaded to a service."""

    input_id: str
    status: str
    output: object = None
    error: str | None = None


class OfflineCaseProvider:
    """Marker selecting local Case generation in ``BenchmarkRunner``."""

    name = "offline-verify-case"


class OfflineJudgeProvider:
    """Marker selecting local judging in ``BenchmarkRunner``."""

    name = "offline-verify-judge"


class OfflineSdkRun:
    """Hand out probe Inputs and record their outcomes entirely in memory."""

    def __init__(
        self,
        *,
        probes: tuple[object, ...] = (DEFAULT_PROBE_TEXT,),
        run_id: str | None = None,
    ) -> None:
        if not probes:
            raise ValueError("An offline run requires at least one probe input")
        self.run_id = run_id or f"offline_{uuid4().hex}"
        self._probes = probes
        self._issued = 0
        self._history: list[OfflineHistoryEntry] = []
        self._failures: list[str] = []

    @property
    def state(self) -> str:
        if self._failures:
            return "failed"
        if len(self._history) < len(self._probes):
            return "running"
        return "completed"

    @property
    def history(self) -> tuple[OfflineHistoryEntry, ...]:
        return tuple(self._history)

    @property
    def report(self) -> OfflineReport:
        if self._failures:
            return OfflineReport(status=_FAIL, issues=tuple(self._failures))
        if len(self._history) < len(self._probes):
            return OfflineReport(
                status=_FAIL,
                issues=(
                    f"Only {len(self._history)} of {len(self._probes)} probe inputs "
                    "completed",
                ),
            )
        return OfflineReport(status=_PASS, confidence=1.0)

    def get_input(self, *, full: bool = False) -> OfflineTestInput | None:
        del full  # The local payload is already complete.
        if self._issued >= len(self._probes):
            return None
        payload = self._probes[self._issued]
        self._issued += 1
        return OfflineTestInput(
            input_id=f"{PROBE_INPUT_PREFIX}-{self._issued}",
            payload=payload,
        )

    def submit(
        self,
        output: object = None,
        *,
        status: str = "completed",
        error: str | None = None,
    ) -> OfflineReport:
        input_id = f"{PROBE_INPUT_PREFIX}-{max(self._issued, 1)}"
        self._history.append(
            OfflineHistoryEntry(
                input_id=input_id,
                status=status,
                output=output,
                error=error,
            )
        )
        if status != "completed" or error is not None:
            self._failures.append(error or f"Input {input_id} reported {status!r}")
        return self.report


@dataclass(slots=True)
class OfflineRunFactory:
    """Create one ``OfflineSdkRun`` per Case, ignoring official SDK arguments."""

    probes: tuple[object, ...] = (DEFAULT_PROBE_TEXT,)
    created: list[OfflineSdkRun] = field(default_factory=list)

    def __call__(self, **kwargs: Any) -> OfflineSdkRun:
        del kwargs  # repo_path, allow_local and provider markers are host concerns.
        run = OfflineSdkRun(probes=self.probes)
        self.created.append(run)
        return run


def probe_inputs(text: str = DEFAULT_PROBE_TEXT, *, count: int = 1) -> tuple[object, ...]:
    """Build ``count`` probe payloads from one prompt."""

    if count < 1:
        raise ValueError("Offline verification requires at least one probe input")
    return tuple(text for _ in range(count))
