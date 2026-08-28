"""The SDK's local-Provider mode, which is what verify's benchmark relies on.

Passing both Provider ports is the only thing that keeps the SDK from building a
Backend client, so these tests drive the real installed SDK with the smallest
Providers that satisfy it. They deliberately do not use the product's own
Providers: the contract under test belongs to the SDK, not to ours.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agentbench.harness.protocols import STATUS_PASS
from agentbench.harness.submission import answered

STATUS_ISSUE = "issue"


@dataclass(frozen=True)
class _ProbeCaseProvider:
    """One text Input per requested Input, and no requirement needed."""

    probe_text: str = "ping"
    requirement_required: bool = False

    def generate_case(self, context: Any) -> dict[str, Any]:
        return {
            "case_id": "case_sdk_local_mode",
            "input_type": "text",
            "rubric": {"rule": "answered", "expects": "a non-empty reply"},
            "inputs": [
                {
                    "input_id": f"input_local_mode_{index}",
                    "payload_type": "text",
                    "payload": self.probe_text,
                }
                for index in range(1, context.max_inputs + 1)
            ],
        }


class _AnsweredJudgeProvider:
    """Pass only when every Input came back with usable output."""

    def judge(self, context: Any) -> dict[str, Any]:
        issues = [
            {
                "code": "empty_output",
                "message": f"Input {item.test_input.input_id} answered nothing",
            }
            for item in context.history
            if not answered(item)
        ]
        return {
            "report_id": "report_sdk_local_mode",
            "status": STATUS_ISSUE if issues else STATUS_PASS,
            "confidence": 1.0,
            "stop_reason": "local_mode_complete",
            "issues": issues,
        }


defuzex = pytest.importorskip("defuzex", reason="the DefuzeX SDK drives the real Run")


class TestRealSdkAcceptsALocalProviderPair:
    """A custom Provider pair must satisfy the SDK, not just our expectations."""

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
            case_provider=_ProbeCaseProvider(),
            judge_provider=_AnsweredJudgeProvider(),
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

        requirement = (
            repo_root / "resources" / "requirements" / "langgraph-chat-agent.md"
        )
        run = self._run(tmp_path, requirement=requirement)
        run.get_input(full=True)

        assert run.submit("a reply").status == STATUS_PASS

    def test_no_backend_base_url_is_ever_consulted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A custom Provider pair must keep the SDK from building a Backend client."""

        monkeypatch.setenv(
            "DEFUZEX_BASE_URL", "http://127.0.0.1:1/should-never-be-used"
        )
        run = self._run(tmp_path, requirement=None)
        run.get_input(full=True)

        assert run.submit("a reply").status == STATUS_PASS


def test_the_sdk_is_the_declared_dependency() -> None:
    """Guards against silently falling back to a hand-rolled Run again."""

    assert os.path.basename(os.path.dirname(defuzex.__file__)) == "defuzex"
    assert hasattr(defuzex, "create_run")
