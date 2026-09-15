"""Append-only, run-scoped trace storage shared by host and worker."""
from __future__ import annotations

import json
import os
import threading
import tempfile
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path


def json_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(k): json_value(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: json_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump())
    return {"type": type(value).__name__, "value": str(value)}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if any(x in k.lower() for x in
                ("api_key", "authorization", "secret", "password", "access_token"))
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


_SECRET_NAME_TOKENS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_MIN_SECRET_LENGTH = 12


def environment_secrets(environ=None) -> tuple[str, ...]:
    """Values worth removing from artifacts, selected by name *and* by shape.

    Selecting on the variable name alone sweeps in ordinary settings whose names merely
    contain KEY or TOKEN -- a keyring backend selector, a token limit -- whose values are
    short, common words. Each such value then becomes a global substring rule and rewrites
    unrelated text: GOG_KEYRING_BACKEND=file turns `is_file()` into `is_[REDACTED]()` in
    the one traceback that explained a failure, and makes tests fail whose temporary
    directories are named after it. A real credential is long and is not a bare number, so
    requiring that costs nothing and stops the collateral damage.

    This is the single definition; six call sites had grown copies of the name-only test.
    """
    values = os.environ if environ is None else environ
    return tuple(value for key, value in values.items()
                 if isinstance(value, str)
                 and any(token in key.upper() for token in _SECRET_NAME_TOKENS)
                 and len(value.strip()) >= _MIN_SECRET_LENGTH
                 and not value.strip().isdigit())


def _umask_file_mode() -> int:
    """The mode a plain open() would have produced, for restoring umask semantics."""
    current = os.umask(0o022)
    os.umask(current)
    return 0o666 & ~current


def atomic_json(path: Path, value):
    # Independent writers must never share the same intermediate pathname.
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(json_value(value), stream, ensure_ascii=False, indent=2)
        # NamedTemporaryFile always creates 0600 and replace() preserves it. That is a
        # side effect of using it for unique intermediate names, not an access decision:
        # artifacts are read back by the host after a container wrote them, and by the
        # container after the host wrote them. Restore the mode the previous
        # write_text() implementation produced.
        os.chmod(temporary, _umask_file_mode())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class TraceStore:
    def __init__(self, path: Path, run_id: str, *, source="runtime", context=None,
                 environ=None):
        self.path, self.run_id, self.source = path, run_id, source
        # Authoritative invocation identity, shared by every event in this store.
        self.context = dict(context or {})
        self._lock = threading.Lock()
        environment = os.environ if environ is None else environ
        self._secrets = environment_secrets(environment)

    def record(self, event: str, **data):
        row = {"schema": "abb.observe.event.v1", "run_id": self.run_id,
               "source": self.source, "event": event,
               "timestamp": datetime.now(timezone.utc).isoformat(),
               "data": redact(json_value({**data, **self.context}), self._secrets)}
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()

    def emit(self, event):
        self.record(event.event, **dict(event.data))


def summarize(directory: Path):
    counts = {}
    for path in sorted(directory.rglob("*.jsonl")):
        if path.is_symlink():
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                counts["incomplete_lines"] = counts.get("incomplete_lines", 0) + 1
                continue
            key = row["source"] + ":" + row["event"]
            counts[key] = counts.get(key, 0) + 1
            if row["event"] == "tool_outcome" and row["data"].get("status") != "succeeded":
                warning = row["source"] + ":tool_incomplete"
                counts[warning] = counts.get(warning, 0) + 1
    return counts
