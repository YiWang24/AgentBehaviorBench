"""Lifecycle state for one running model interceptor."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class RunningModelInterceptor:
    container_name: str
    ca_certificate: Path
    _close_callback: Callable[[], None] = field(repr=False)
    _log_process: subprocess.Popen[str] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._log_process is not None and self._log_process.poll() is None:
            self._log_process.terminate()
            try:
                self._log_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._log_process.kill()
        self._close_callback()

    def __enter__(self) -> "RunningModelInterceptor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
