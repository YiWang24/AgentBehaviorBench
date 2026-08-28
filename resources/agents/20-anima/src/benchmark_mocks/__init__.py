"""Benchmark guards for Anima.

Anima's only outbound dependency on this path is the model provider: devices
are served by upstream's own VirtualAdapter and the skills are local markdown.
Nothing is substituted, so this installs the egress guard only — a future
revision that reaches for MQTT, the Xiaomi cloud, or an HTTP service fails
loudly rather than silently.
"""

from .network_guard import install

_installed = False


def install_all() -> None:
    global _installed
    if _installed:
        return
    install()
    _installed = True


def installed() -> bool:
    return _installed


__all__ = ["install_all", "installed"]
