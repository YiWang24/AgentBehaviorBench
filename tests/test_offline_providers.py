"""The local Case and Judge Providers, and their contract with the real SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agentbench.harness.offline import (
    DEFAULT_PROBE_TEXT,
    STATUS_ISSUE,
    STATUS_PASS,
    StartupCaseProvider,
    StartupJudgeProvider,
)


# --- test doubles ------------------------------------------------------------


@dataclass(frozen=True)
class _CaseContext:
    max_inputs: int = 1
    input_type: str = "text"
    requirement: str | None = None
    agent_description: str | None = None
    requirement_sections: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Input:
    input_id: str


@dataclass(frozen=True)
class _Submission:
    status: str = "completed"
    output: Any = "a reply"
    error: str | None = None


@dataclass(frozen=True)
class _Item:
    test_input: _Input
    submission: _Submission


@dataclass(frozen=True)
class _JudgeContext:
    history: tuple[_Item, ...]
    run_status: str = "completed"


def _history(*submissions: _Submission) -> _JudgeContext:
    return _JudgeContext(
        history=tuple(
            _Item(_Input(f"input_startup_probe_{index}"), submission)
            for index, submission in enumerate(submissions, start=1)
        )
    )


# --- Case Provider -----------------------------------------------------------


class TestStartupCaseProvider:
    def test_it_emits_one_text_input_per_requested_input(self) -> None:
        case = StartupCaseProvider().generate_case(_CaseContext(max_inputs=3))

        assert case["input_type"] == "text"
        assert len(case["inputs"]) == 3
        assert [item["payload"] for item in case["inputs"]] == [DEFAULT_PROBE_TEXT] * 3
        assert len({item["input_id"] for item in case["inputs"]}) == 3

    def test_the_probe_text_is_caller_supplied(self) -> None:
        case = StartupCaseProvider(probe_text="ping").generate_case(_CaseContext())

        assert case["inputs"][0]["payload"] == "ping"

    def test_a_requirement_is_optional(self) -> None:
        """Agents are verifiable while still being adapted, before a requirement."""

        assert StartupCaseProvider().requirement_required is False


# --- Judge Provider ----------------------------------------------------------


class TestStartupJudgeProvider:
    def test_answered_inputs_pass(self) -> None:
        report = StartupJudgeProvider().judge(
            _history(_Submission(), _Submission(output={"messages": ["hi"]}))
        )

        assert report["status"] == STATUS_PASS
        assert report["issues"] == []
        assert report["extensions"] == {"answered_inputs": 2, "total_inputs": 2}

    def test_it_does_not_grade_content(self) -> None:
        """Startup verification serves mock model replies; wording carries no signal."""

        report = StartupJudgeProvider().judge(
            _history(_Submission(output="total nonsense, factually wrong"))
        )

        assert report["status"] == STATUS_PASS

    @pytest.mark.parametrize(
        "output",
        ["", "   ", None, [], {}],
        ids=["empty", "blank", "none", "empty-list", "empty-mapping"],
    )
    def test_an_unanswered_input_is_an_issue(self, output: Any) -> None:
        report = StartupJudgeProvider().judge(_history(_Submission(output=output)))

        assert report["status"] == STATUS_ISSUE
        assert report["issues"][0]["code"] == "empty_output"

    def test_a_falsy_but_present_output_still_counts_as_an_answer(self) -> None:
        report = StartupJudgeProvider().judge(_history(_Submission(output=0)))

        assert report["status"] == STATUS_PASS

    def test_a_failed_submission_is_an_issue(self) -> None:
        report = StartupJudgeProvider().judge(
            _history(_Submission(status="failed", output=None, error="container died"))
        )

        assert report["status"] == STATUS_ISSUE
        assert report["issues"][0]["code"] == "input_not_completed"
        assert "container died" in report["issues"][0]["message"]

    def test_one_bad_input_among_several_fails_the_run(self) -> None:
        report = StartupJudgeProvider().judge(
            _history(_Submission(), _Submission(output=""), _Submission())
        )

        assert report["status"] == STATUS_ISSUE
        assert report["extensions"] == {"answered_inputs": 2, "total_inputs": 3}


# --- contract with the installed SDK -----------------------------------------


defuzex = pytest.importorskip("defuzex", reason="the DefuzeX SDK drives the real Run")


class TestRealSdkAcceptsTheLocalProviders:
    """These Providers must satisfy the SDK, not just our own expectations."""

    @pytest.fixture(autouse=True)
    def _isolated_run_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Give each test its own single-active-Run lock.

        The SDK enforces one active Run per host with an OS file lock resolved from
        ``XDG_RUNTIME_DIR``. Without redirecting it, these tests fail whenever any
        other Run — a real `agentbench verify`, or a parallel test — holds it.
        """

        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))

    @staticmethod
    def _run(tmp_path: Path, *, requirement: Path | None, max_inputs: int = 1):
        return defuzex.create_run(
            repo_path=tmp_path,
            requirement_path=requirement,
            case_provider=StartupCaseProvider(probe_text="ping"),
            judge_provider=StartupJudgeProvider(),
            max_inputs=max_inputs,
            allow_local=True,
            track_files=False,
            save_local=False,
        )

    def test_a_full_handshake_passes_without_any_credential(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("DEFUZEX_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        run = self._run(tmp_path, requirement=None, max_inputs=2)
        report = None
        while (test_input := run.get_input(full=True)) is not None:
            assert test_input.payload == "ping"
            report = run.submit("a reply")

        assert report is not None
        assert report.status == STATUS_PASS
        assert run.state == "report_ready"
        assert len(run.history) == 2

    def test_an_empty_reply_is_judged_an_issue_end_to_end(
        self, tmp_path: Path
    ) -> None:
        run = self._run(tmp_path, requirement=None)
        run.get_input(full=True)
        report = run.submit("   ")

        assert report is not None
        assert report.status == STATUS_ISSUE

    def test_the_agents_own_requirement_is_accepted(
        self, repo_root: Path, tmp_path: Path
    ) -> None:
        """Local mode still parses the requirement and enforces its input_type."""

        requirement = repo_root / "resources" / "requirements" / "langgraph-chat-agent.md"
        run = self._run(tmp_path, requirement=requirement)
        run.get_input(full=True)

        assert run.submit("a reply").status == STATUS_PASS

    def test_no_backend_base_url_is_ever_consulted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A custom Provider pair must keep the SDK from building a Backend client."""

        monkeypatch.setenv("DEFUZEX_BASE_URL", "http://127.0.0.1:1/should-never-be-used")
        run = self._run(tmp_path, requirement=None)
        run.get_input(full=True)

        assert run.submit("a reply").status == STATUS_PASS


def test_the_sdk_is_the_declared_dependency() -> None:
    """Guards against silently falling back to a hand-rolled Run again."""

    assert os.path.basename(os.path.dirname(defuzex.__file__)) == "defuzex"
    assert hasattr(defuzex, "create_run")
