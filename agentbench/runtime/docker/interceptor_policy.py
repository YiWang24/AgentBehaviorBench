"""Restricted Docker policy for the trusted network interceptor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterceptorPolicy:
    memory: str = "512m"
    cpus: float = 1.0
    pids_limit: int = 128

    def run_arguments(self) -> tuple[str, ...]:
        return (
            "--read-only",
            "--cap-drop=ALL",
            "--cap-add=NET_ADMIN",
            "--cap-add=NET_RAW",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs=/run/defuzex:rw,noexec,nosuid,size=64m",
        )
