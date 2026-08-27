"""Secret resolution that keeps offline verification runnable without real keys."""

from __future__ import annotations

import os
from collections.abc import Mapping


PLACEHOLDER_PREFIX = "defuzex-offline-verify"


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
        return f"{PLACEHOLDER_PREFIX}-{name.lower()}"
