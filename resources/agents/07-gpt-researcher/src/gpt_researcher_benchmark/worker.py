"""Persistent JSONL worker for the gpt-researcher benchmark adapter.

stdin   {"input": <payload>, "run_config": <object|null>}
stdout  {"ok": true, "output": <public result>, "raw_output": <diagnostic>}
stdout  {"ok": false, "error": "ErrorType: safe message"}

The research agents print progress banners to stdout, so every request runs
with stdout redirected to stderr and the JSONL response is written to the
original stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from typing import Any


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        if getattr(handler, "stream", None) is sys.stdout:
            handler.stream = sys.stderr


def _thread_id(run_config: object) -> str | None:
    if isinstance(run_config, dict):
        configurable = run_config.get("configurable")
        if isinstance(configurable, dict):
            thread_id = configurable.get("thread_id")
            if isinstance(thread_id, str):
                return thread_id
    return None


def _handle(line: str) -> dict[str, Any]:
    from . import graph as graph_module
    from .inputs import to_query

    import benchmark_mocks
    from benchmark_mocks import corpus

    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSONDecodeError: {exc}"}

    try:
        if not isinstance(request, dict) or "input" not in request:
            raise ValueError("JSONL request must contain 'input'")

        query = to_query(request["input"])
        corpus.reset_trace()
        result = asyncio.run(
            graph_module.run_research(query, task_id=_thread_id(request.get("run_config")))
        )

        return {
            "ok": True,
            "output": {
                "query": result["query"],
                "report": result["report"],
                "sources": result["sources"],
            },
            "raw_output": {
                "section_count": len(result["sections"]),
                "sections": result["sections"],
                "source_count": len(result["sources"]),
                "diagram_count": result["diagram_count"],
                "report_characters": {
                    key: len(value) for key, value in result["report"].items()
                },
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
