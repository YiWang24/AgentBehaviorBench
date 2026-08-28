"""Colored terminal rendering for benchmark progress events."""

from __future__ import annotations

import sys
from builtins import print as builtin_print
from collections.abc import Callable
from threading import Event, Lock, Thread
from typing import Protocol

from agentbench.harness.progress import BenchmarkProgress

from .TerminalUI import LLMActivity
from .constants import ANSI_GREEN, ANSI_RED, ANSI_RESET, ANSI_YELLOW

DOT_FRAMES = (".  ", ".. ", "...")
ANIMATION_INTERVAL_SECONDS = 0.35


class StageReporter(Protocol):
    """A renderer for stages a command opens and closes itself.

    Stated separately from the Harness progress callback because a command can
    have stages the Harness knows nothing about, and both have to appear in one
    uninterrupted column.
    """

    def start_stage(self, label: str) -> None:
        ...

    def finish_stage(self, ok: bool, detail: str | None = None) -> None:
        ...


class ProgressPrinter:
    """Render structured Harness events without coupling it to terminal I/O."""

    def __init__(
        self,
        output_fn: Callable[[str], None] = print,
        *,
        llm_activity: LLMActivity | None = None,
        live_updates: bool | None = None,
        animation_interval: float = ANIMATION_INTERVAL_SECONDS,
    ) -> None:
        self._output_fn = output_fn
        self._llm_activity = llm_activity
        self._provider_mode: str | None = None
        self._active_label: str | None = None
        self._animation_interval = animation_interval
        self._stop_animation = Event()
        self._render_lock = Lock()
        self._animation_thread: Thread | None = None
        self._live_updates = (
            output_fn is builtin_print and sys.stdout.isatty()
            if live_updates is None
            else live_updates
        )

    def __call__(self, event: BenchmarkProgress) -> None:
        if event.stage == "case_generation" and event.detail:
            self._provider_mode = event.detail
        if event.status == "started":
            self.start_stage(_stage_label(event, self._provider_mode))
            return
        self.finish_stage(event.status == "succeeded", event.detail)

    def finish_stage(self, ok: bool, detail: str | None = None) -> None:
        """Close the open stage line, so a caller can drive its own stages.

        Commands whose stages are not all Harness events still have to look like
        one run, so the OK/FAILED wording lives here rather than being rebuilt by
        every caller that opens a stage of its own.
        """

        status = "OK" if ok else "FAILED"
        color = ANSI_GREEN if ok else ANSI_RED
        suffix = f" | {detail}" if detail else ""
        self._finish_stage(f"{color}{status}{ANSI_RESET}{suffix}")

    def start_stage(self, label: str) -> None:
        if self._panel_owns_terminal():
            self._llm_activity.start_stage(label)  # type: ignore[union-attr]
            return
        if not self._live_updates:
            self._output_fn(label)
            return

        self._stop_active_animation()
        self._active_label = label
        self._stop_animation.clear()
        self._animation_thread = Thread(
            target=self._animate_stage,
            args=(label,),
            daemon=True,
        )
        self._animation_thread.start()

    def _finish_stage(self, status: str) -> None:
        if self._panel_owns_terminal():
            self._llm_activity.finish_stage(status)  # type: ignore[union-attr]
            return
        if not self._live_updates:
            self._output_fn(f"  {status}")
            return

        label = self._active_label or "Stage"
        self._stop_active_animation()
        final_label = f"{_base_stage_label(label)}..."
        with self._render_lock:
            sys.stdout.write(f"\r\033[2K  {final_label} {status}\n")
            sys.stdout.flush()
        self._active_label = None

    def _panel_owns_terminal(self) -> bool:
        """Whether the live panel will render the stage line itself.

        A panel that has been silenced — because the command prints its own
        sectioned report and would otherwise duplicate every call — still exists
        as a trace sink, but it cannot be the one to draw the stage line.
        """

        return self._llm_activity is not None and self._llm_activity.live

    def _animate_stage(self, label: str) -> None:
        base_label = _base_stage_label(label)
        frame_index = 0
        while not self._stop_animation.is_set():
            dots = DOT_FRAMES[frame_index % len(DOT_FRAMES)]
            with self._render_lock:
                sys.stdout.write(
                    f"\r\033[2K  {base_label}{dots} {ANSI_YELLOW}RUNNING{ANSI_RESET}"
                )
                sys.stdout.flush()
            frame_index += 1
            self._stop_animation.wait(self._animation_interval)

    def _stop_active_animation(self) -> None:
        if self._animation_thread is None:
            return

        self._stop_animation.set()
        self._animation_thread.join(timeout=self._animation_interval + 0.1)
        self._animation_thread = None

    def close(self) -> None:
        """Stop any live renderer left active by an interrupted run."""

        if self._llm_activity is not None:
            self._llm_activity.close()
        self._stop_active_animation()


def configuration_error(message: object) -> str:
    """Format a fatal suite configuration error."""

    return f"{ANSI_RED}【Configuration error】 {message}{ANSI_RESET}"


def _stage_label(event: BenchmarkProgress, provider_mode: str | None = None) -> str:
    if event.stage == "sdk_check":
        # The provider mode is only known once this stage reports back, so the
        # label has to stay true for both official and local runs.
        return "Checking benchmark configuration..."
    if event.stage == "agent_start":
        return "Starting Agent..."
    if event.stage == "case_generation":
        if event.detail == "official":
            return "Generating Case from DefuzeX Server..."
        return "Generating Case with local Provider..."
    if provider_mode == "local":
        return "Running Agent inputs..."
    return "Running Agent inputs and DefuzeX Judge..."


def _base_stage_label(label: str) -> str:
    return label.rstrip(".")
