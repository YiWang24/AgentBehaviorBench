"""The shared animated stage column, driven by the Harness and by a command.

`certify` reports only Harness stages; `verify` opens stages of its own around
them. Both have to render one uninterrupted column, so the wording and the
OK/FAILED shape live in one renderer rather than in each command.
"""

from __future__ import annotations

from agentbench.cli.presentation import ANSI_PATTERN
from agentbench.cli.progress import ProgressPrinter, configuration_error
from agentbench.harness import BenchmarkProgress


def _plain(lines: list[str]) -> list[str]:
    return [ANSI_PATTERN.sub("", line).strip() for line in lines]


def _printer(output: list[str]) -> ProgressPrinter:
    # A list sink cannot redraw, so the renderer writes each line once, which is
    # what makes the output assertable.
    return ProgressPrinter(output.append, live_updates=False)


# --- Harness events ----------------------------------------------------------


def test_each_harness_stage_renders_a_label_and_a_result() -> None:
    output: list[str] = []
    progress = _printer(output)

    progress(BenchmarkProgress("agent_start", "started"))
    progress(BenchmarkProgress("agent_start", "succeeded", detail="ContainerAgentAdapter"))

    assert _plain(output) == ["Starting Agent...", "OK | ContainerAgentAdapter"]


def test_a_failed_stage_says_so_and_keeps_its_detail() -> None:
    output: list[str] = []
    progress = _printer(output)

    progress(BenchmarkProgress("agent_start", "started"))
    progress(
        BenchmarkProgress("agent_start", "failed", detail="DockerRuntimeError: no daemon")
    )

    assert _plain(output)[1] == "FAILED | DockerRuntimeError: no daemon"


def test_the_case_label_names_who_wrote_the_case() -> None:
    """A local Run and an official one differ here, and only here."""

    local: list[str] = []
    official: list[str] = []
    _printer(local)(BenchmarkProgress("case_generation", "started", detail="local"))
    _printer(official)(
        BenchmarkProgress("case_generation", "started", detail="official")
    )

    assert _plain(local) == ["Generating Case with local Provider..."]
    assert _plain(official) == ["Generating Case from DefuzeX Server..."]


def test_the_run_label_follows_the_provider_mode_reported_earlier() -> None:
    """Only an official Run has a DefuzeX Judge to name."""

    output: list[str] = []
    progress = _printer(output)

    progress(BenchmarkProgress("case_generation", "succeeded", detail="local"))
    progress(BenchmarkProgress("benchmark_execution", "started"))

    assert _plain(output)[-1] == "Running Agent inputs..."


# --- stages a command opens itself -------------------------------------------


def test_a_command_can_open_and_close_its_own_stage() -> None:
    output: list[str] = []
    progress = _printer(output)

    progress.start_stage("Probing Agent...")
    progress.finish_stage(True, "1/1 answered")

    assert _plain(output) == ["Probing Agent...", "OK | 1/1 answered"]


def test_a_command_stage_without_a_detail_still_reports_its_result() -> None:
    output: list[str] = []
    progress = _printer(output)

    progress.start_stage("Checking DefuzeX SDK...")
    progress.finish_stage(False)

    assert _plain(output)[1] == "FAILED"


def test_command_stages_and_harness_stages_share_one_column() -> None:
    """The two sources must be indistinguishable in the finished output."""

    output: list[str] = []
    progress = _printer(output)

    progress.start_stage("Starting Agent...")
    progress.finish_stage(True, "ContainerAgentAdapter")
    progress(BenchmarkProgress("benchmark_execution", "started"))
    progress(BenchmarkProgress("benchmark_execution", "succeeded", detail="Judge: pass"))
    progress.close()

    assert _plain(output) == [
        "Starting Agent...",
        "OK | ContainerAgentAdapter",
        "Running Agent inputs and DefuzeX Judge...",
        "OK | Judge: pass",
    ]


def test_closing_an_idle_renderer_is_safe() -> None:
    """An interrupted run closes the renderer without having opened a stage."""

    output: list[str] = []
    _printer(output).close()

    assert output == []


def test_a_configuration_error_is_labelled_as_one() -> None:
    assert "Configuration error" in ANSI_PATTERN.sub(
        "", configuration_error("docker unavailable")
    )
