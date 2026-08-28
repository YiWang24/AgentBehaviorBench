"""How a runtime supplies the credentials an Agent declares.

Two resolvers implement one contract, and the choice between them is the whole
difference between a graded run and a credential-free one: :class:`EnvironmentSecretResolver`
stops startup when a declared secret is missing, while :class:`OfflineSecretResolver`
substitutes a placeholder and records that it did.

Placeholders are shaped like the credential they replace. Agents routinely
validate a key before using it — ``key.startswith("sk-")`` is a common guard, and
Anthropic clients often check ``sk-ant-`` — so a shapeless stand-in fails at
configuration time with an error the Agent's real deployment would never see, and
the failure looks like the Agent's fault. Prefixing costs nothing: the value's
security comes from its body, which is unchanged, and the prefix carries no
secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

PLACEHOLDER_PREFIX = "defuzex-offline-verify"

# Ordered: the first marker found in the variable name wins, so the more
# specific family is listed first. `sk-ant-` values also satisfy a bare `sk-`
# guard, which is why no combined entry is needed.
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC", "sk-ant-api03-"),
    ("", "sk-"),
)


class MissingSecretError(RuntimeError):
    """Raised before startup when a declared secret is unavailable."""


@runtime_checkable
class SecretResolver(Protocol):
    def require(self, name: str) -> str:
        """Resolve a non-empty secret or stop startup."""


@dataclass(frozen=True, slots=True)
class EnvironmentSecretResolver:
    """Resolve explicitly named secrets from the process environment."""

    environ: Mapping[str, str] | None = None

    def require(self, name: str) -> str:
        values = os.environ if self.environ is None else self.environ
        value = values.get(name, "")
        if not value.strip():
            raise MissingSecretError(
                f"Required secret is not configured in the environment: {name}"
            )
        return value


class OfflineSecretResolver:
    """Return real values when present, deterministic placeholders otherwise.

    Verification must not require production credentials, but silently faking
    every secret would hide genuine configuration gaps. Substituted names are
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


def prefix_for(env_name: str) -> str:
    """The prefix a credential delivered through `env_name` is expected to carry."""

    upper = env_name.upper()
    return next(prefix for marker, prefix in _FAMILY_PREFIXES if marker in upper)


def shaped(env_name: str, body: str) -> str:
    """`body` carrying the prefix expected for `env_name`."""

    return f"{prefix_for(env_name)}{body}"


def placeholder_for(name: str) -> str:
    """A stand-in for `name`, shaped like the credential it replaces."""

    return shaped(name, f"{PLACEHOLDER_PREFIX}-{name.lower()}")
