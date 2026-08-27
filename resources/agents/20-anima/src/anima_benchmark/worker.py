"""JSONL worker for Anima.

One request per line on stdin, one reply per line on stdout. The reply carries
the state of every virtual device after the turn, so a judge can check what the
Agent actually did to the home rather than only what it said.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import sys


def _message(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("message", "question", "query", "prompt", "input", "text", "content"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from . import runtime as runtime_module

    with contextlib.redirect_stdout(sys.stderr):
        anima = runtime_module.runtime()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"JSONDecodeError: {exc}"}), flush=True)
            continue

        try:
            message = _message(payload)
            before = copy.deepcopy(anima.device_states())
            with contextlib.redirect_stdout(sys.stderr):
                result = asyncio.run(anima.chat(message))
            after = anima.device_states()
            changed = {
                device_id: {"before": before.get(device_id, {}).get("state"),
                            "after": entry["state"]}
                for device_id, entry in after.items()
                if before.get(device_id, {}).get("state") != entry["state"]
            }
            reply = {
                "ok": True,
                "output": str(result.get("reply", "")),
                "raw_output": {
                    "reply": result.get("reply", ""),
                    "request": message,
                    "result": result,
                    "devices_after": after,
                    "devices_changed": changed,
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
