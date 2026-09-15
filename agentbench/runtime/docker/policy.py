"""Security and resource policy applied to every agent container."""

from __future__ import annotations

from dataclasses import dataclass
import os



def _host_user_arguments() -> tuple[str, ...]:
    """Run the container as the host user so bind-mounted state stays shared.

    Everything the container produces leaves through bind mounts that the host reads
    back: the evaluation artifacts, and the SDK's request ledger under .kuma. When the
    container runs as the image's own uid, the host is a different user and cannot read
    what it is given -- the SDK stores its ledger 0600 by design, so a lost Judge verdict
    becomes unrecoverable, and artifacts written 0600 look to the host like a Case that
    was never produced.

    Matching uids removes that whole class rather than widening file modes. The image is
    still required to declare a non-root USER; this only overrides which unprivileged uid
    it runs as. If the host itself is root there is nothing to match and no benefit, so
    the image's own user is left in place.
    """
    if not hasattr(os, "getuid") or os.getuid() == 0:
        return ()
    return (f"--user={os.getuid()}:{os.getgid()}",)

@dataclass(frozen=True, slots=True)
class DockerPolicy:
    cpus: float = 1.0
    memory: str = "1g"
    pids_limit: int = 128
    tmpfs_size: str = "64m"

    def run_arguments(self) -> tuple[str, ...]:
        return (
            *_host_user_arguments(),
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--tmpfs=/tmp:rw,noexec,nosuid,size={self.tmpfs_size}",
            f"--tmpfs=/run/agentbench-tools:rw,exec,nosuid,nodev,size={self.tmpfs_size},mode=1777",
        )
