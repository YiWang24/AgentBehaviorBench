"""Give stand-in credentials the shape of the credential they replace.

Agents routinely validate a key before using it — `key.startswith("sk-")` is a
common guard, and Anthropic clients often check `sk-ant-`. Both the offline
placeholder and the temporary interception token are otherwise shapeless, so
such an Agent fails at configuration time with an error its real deployment
would never see, and the failure looks like the Agent's fault.

Prefixing costs nothing: the token's security comes from its random body, which
is unchanged, and the prefix carries no secret.
"""

from __future__ import annotations

# Ordered: the first marker found in the variable name wins, so the more
# specific family is listed first. `sk-ant-` values also satisfy a bare `sk-`
# guard, which is why no combined entry is needed.
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC", "sk-ant-api03-"),
    ("", "sk-"),
)


def prefix_for(env_name: str) -> str:
    """The prefix a credential delivered through `env_name` is expected to carry."""

    upper = env_name.upper()
    return next(prefix for marker, prefix in _FAMILY_PREFIXES if marker in upper)


def shaped(env_name: str, body: str) -> str:
    """`body` carrying the prefix expected for `env_name`."""

    return f"{prefix_for(env_name)}{body}"
