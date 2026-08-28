"""The credential-free half of verification: no DefuzeX key, no SDK, no egress.

What lives here is everything `verify`'s preflight needs. It is deliberately thin
and SDK-free: an Agent has to be checkable before the DefuzeX SDK is installed,
so preflight drives the adapter directly and the SDK only appears once the
graded benchmark begins.
"""

from .probe import DEFAULT_PROBE_TEXT
from .secrets import OfflineSecretResolver, placeholder_for

__all__ = [
    "DEFAULT_PROBE_TEXT",
    "OfflineSecretResolver",
    "placeholder_for",
]
