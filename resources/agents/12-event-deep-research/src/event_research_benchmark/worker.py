"""Persistent JSONL worker for the event deep-research adapter.

stdin   {"input": <payload>, "run_config": <object|null>}
stdout  {"ok": true, "output": <public result>, "raw_output": <diagnostic>}
stdout  {"ok": false, "error": "ErrorType: safe message"}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

MAX_SUBJECT_CHARACTERS = 500


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        if getattr(handler, "stream", None) is sys.stdout:
            handler.stream = sys.stderr


def _to_subject(payload: object) -> str:
    if isinstance(payload, Mapping):
        for key in ("subject", "person_to_research", "text", "prompt", "question", "input", "content"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                payload = candidate
                break
    if isinstance(payload, (list, tuple)):
        payload = " ".join(str(item) for item in payload)
    subject = " ".join(str(payload or "").split())
    if not subject:
        raise ValueError("Input must contain non-empty text or a 'subject' field")
    return subject[:MAX_SUBJECT_CHARACTERS]


def _handle(line: str) -> dict[str, Any]:
    from . import graph as graph_module

    import benchmark_mocks
    from benchmark_mocks import corpus

    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSONDecodeError: {exc}"}

    try:
        if not isinstance(request, dict) or "input" not in request:
            raise ValueError("JSONL request must contain 'input'")

        subject = _to_subject(request["input"])
        corpus.reset_trace()
        run_config = request.get("run_config")
        result = asyncio.run(
            graph_module.run_research(
                subject, run_config if isinstance(run_config, dict) else None
            )
        )

        return {
            "ok": True,
            "output": {
                "subject": result["subject"],
                "events": result["events"],
                "events_summary": result["events_summary"],
            },
            "raw_output": {
                "event_count": len(result["events"]),
                "categories": result["categories"],
                "iterations": result["iterations"],
                "mocks_installed": benchmark_mocks.installed(),
                "mock_trace": corpus.trace_summary(),
            },
        }
    except Exception as exc:  # noqa: BLE001 - one safe error line per input
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    _configure_logging()
    stdout = sys.stdout
    for line in sys.stdin:
        if not line.strip():
            continue
        with contextlib.redirect_stdout(sys.stderr):
            response = _handle(line)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
