"""Secret resolution that keeps offline verification runnable without real keys."""

from __future__ import annotations

import os
from collections.abc import Mapping


PLACEHOLDER_PREFIX = "defuzex-offline-verify"

# Agents routinely validate the *shape* of a credential before using it —
# `key.startswith("sk-")` is a common guard, and Anthropic clients often check
# `sk-ant-`. A placeholder that fails those guards makes startup verification
# report a configuration error the deployment does not have. Placeholders
# therefore carry the prefix of the credential family they stand in for; the
# body still says plainly what they are.
_KEY_PREFIXES = (
    ("ANTHROPIC", "sk-ant-api03-"),
    ("", "sk-"),
)


def placeholder_for(name: str) -> str:
    """A stand-in for `name`, shaped like the credential it replaces."""

    upper = name.upper()
    prefix = next(value for marker, value in _KEY_PREFIXES if marker in upper)
    return f"{prefix}{PLACEHOLDER_PREFIX}-{name.lower()}"


class OfflineSecretResolver:
    """Return real values when present, deterministic placeholders otherwise.

    Startup verification must not require production credentials, but silently
    faking every secret would hide genuine configuration gaps. Substituted names are
    therefore recorded so the CLI can report exactly what was stubbed.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ
        self._substituted: list[str] = []

    @property
    def substituted(self) -> tuple[str, ...]:
        """Names that fell back to a placeholder, in first-seen order."""

        return tuple(self._substituted)

    def require(self, name: str) -> str:
        values = os.environ if self._environ is None else self._environ
        value = values.get(name, "")
        if value.strip():
            return value
        if name not in self._substituted:
            self._substituted.append(name)
        return placeholder_for(name)
