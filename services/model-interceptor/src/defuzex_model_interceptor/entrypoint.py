"""Configure transparent routing and launch mitmdump."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .config import ServiceConfig


CONFIG_ENV = "DEFUZEX_INTERCEPTOR_CONFIG"
DEFAULT_CONFIG = "/run/secrets/interceptor_config"
PROXY_PORT = 8080


def main() -> int:
    config_path = os.environ.get(CONFIG_ENV, DEFAULT_CONFIG)
    config = ServiceConfig.load(config_path)
    _configure_netfilter()
    addon_path = Path(__file__).with_name("loader.py")
    command = [
        "mitmdump",
        "--quiet",
        "--mode",
        "transparent",
        "--listen-host",
        "0.0.0.0",
        "--listen-port",
        str(PROXY_PORT),
        "--showhost",
        "--set",
        "confdir=/run/defuzex/ca",
        "--set",
        "connection_strategy=lazy",
        "--scripts",
        str(addon_path),
    ]
    for pattern in _allow_host_patterns(config):
        command.extend(("--allow-hosts", pattern))
    os.execvp(command[0], command)
    return 1


def _configure_netfilter() -> None:
    commands = [
        ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-m", "owner", "!", "--uid-owner", "0", "--dport", "80", "-j", "REDIRECT", "--to-ports", str(PROXY_PORT)],
        ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-m", "owner", "!", "--uid-owner", "0", "--dport", "443", "-j", "REDIRECT", "--to-ports", str(PROXY_PORT)],
        ["iptables", "-A", "OUTPUT", "-p", "udp", "-m", "owner", "!", "--uid-owner", "0", "--dport", "443", "-j", "REJECT"],
    ]
    for command in commands:
        subprocess.run(command, check=True)


def _allow_host_patterns(config: ServiceConfig) -> tuple[str, ...]:
    patterns: list[str] = []
    for route in config.routes:
        for host in route.host_patterns:
            if host.startswith("*."):
                domain = re.escape(host[2:])
                expression = rf"(^|\.){domain}(:\d+)?$"
            else:
                expression = rf"^{re.escape(host)}(:\d+)?$"
            if expression not in patterns:
                patterns.append(expression)
    return tuple(patterns)


if __name__ == "__main__":
    sys.exit(main())
