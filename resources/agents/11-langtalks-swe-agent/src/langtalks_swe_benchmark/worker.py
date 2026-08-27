"""Persistent JSONL worker for the langtalks SWE agent adapter.

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

MAX_TASK_CHARACTERS = 4000


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        if getattr(handler, "stream", None) is sys.stdout:
            handler.stream = sys.stderr


def _to_task(payload: object) -> str:
    if isinstance(payload, Mapping):
        for key in ("task", "text", "prompt", "question", "input", "content"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                payload = candidate
                break
    if isinstance(payload, (list, tuple)):
        payload = " ".join(str(item) for item in payload)
    task = " ".join(str(payload or "").split())
    if not task:
        raise ValueError("Input must contain non-empty text or a 'task' field")
    return task[:MAX_TASK_CHARACTERS]


def _handle(line: str) -> dict[str, Any]:
    from . import graph as graph_module

    import benchmark_mocks

    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSONDecodeError: {exc}"}

    try:
        if not isinstance(request, dict) or "input" not in request:
            raise ValueError("JSONL request must contain 'input'")

        task = _to_task(request["input"])
        benchmark_mocks.reset_trace()
        run_config = request.get("run_config")
        result = asyncio.run(
            graph_module.run_task(
                task, run_config if isinstance(run_config, dict) else None
            )
        )

        return {
            "ok": True,
            "output": {
                "task": result["task"],
                "implementation_plan": result["implementation_plan"],
                "changed_files": result["changed_files"],
            },
            "raw_output": {
                "message_count": result["message_count"],
                "files": result["files"],
                "mocks_installed": benchmark_mocks.installed(),
                "mock_trace": benchmark_mocks.trace_summary(),
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
