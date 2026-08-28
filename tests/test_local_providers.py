"""The local stand-ins for the official Case and Judge services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from agentbench.harness.local import (
    LocalCaseProvider,
    LocalJudgeProvider,
    LocalProviderError,
)
from agentbench.harness.local.judge import INSUFFICIENT, ISSUE, PASS

SECTIONS = {
    "production_scenario": "A support assistant answering billing questions.",
    "behaviors_to_test": "- Answer directly.\n- Keep context across turns.",
    "prohibited_behaviors": "- Never claim an external action was performed.",
}


# --- test doubles ------------------------------------------------------------


@dataclass
class _FakeModel:
    """Return canned JSON and record what it was asked."""

    reply: dict[str, Any]
    model: str = "fake-model"
    prompts: list[str] = field(default_factory=list)

    def json_object(self, *, system: str, user: str, **_: Any) -> dict[str, Any]:
        self.prompts.append(user)
        return self.reply


@dataclass(frozen=True)
class _CaseContext:
    max_inputs: int = 2
    input_type: str = "text"
    agent_description: str | None = "A billing support assistant."
    requirement_sections: dict[str, str] = field(default_factory=lambda: dict(SECTIONS))
    requirement: str | None = None
    repo_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Case:
    rubric: dict[str, Any] | None


@dataclass(frozen=True)
class _Input:
    input_id: str
    payload: Any = "a question"


@dataclass(frozen=True)
class _Submission:
    status: str = "completed"
    output: Any = "an answer"
    error: str | None = None


@dataclass(frozen=True)
class _Item:
    test_input: _Input
    submission: _Submission


@dataclass(frozen=True)
class _JudgeContext:
    history: tuple[_Item, ...]
    case: _Case = _Case(
        rubric={
            "behaviors_to_test": SECTIONS["behaviors_to_test"],
            "prohibited_behaviors": SECTIONS["prohibited_behaviors"],
        }
    )
    run_status: str = "completed"


def _history(*submissions: _Submission) -> _JudgeContext:
    return _JudgeContext(
        history=tuple(
            _Item(_Input(f"step_{index}"), submission)
            for index, submission in enumerate(submissions, start=1)
        )
    )


def _case_reply(count: int = 2) -> dict[str, Any]:
    return {
        "steps": [
            {"step_id": f"s{index}", "prompt": f"prompt {index}", "targets": "answer"}
            for index in range(1, count + 1)
        ]
    }


# --- Case Provider -----------------------------------------------------------


class TestLocalCaseProvider:
    def test_it_feeds_the_requirement_sections_to_the_model(self) -> None:
        model = _FakeModel(_case_reply())

        LocalCaseProvider(model=model).generate_case(_CaseContext())

        prompt = model.prompts[0]
        for section in SECTIONS.values():
            assert section in prompt
        assert "A billing support assistant." in prompt

    def test_it_numbers_input_ids_rather_than_trusting_the_model(self) -> None:
        """A model that repeats or invents an id must not break Case validation."""

        model = _FakeModel(
            {"steps": [{"prompt": "one", "step_id": "dup"}, {"prompt": "two", "step_id": "dup"}]}
        )

        case = LocalCaseProvider(model=model).generate_case(_CaseContext())

        assert [item["input_id"] for item in case["inputs"]] == ["step_1", "step_2"]

    def test_it_never_returns_more_inputs_than_requested(self) -> None:
        model = _FakeModel(_case_reply(count=9))

        case = LocalCaseProvider(model=model).generate_case(_CaseContext(max_inputs=2))

        assert len(case["inputs"]) == 2

    def test_the_rubric_carries_the_behavior_spec_to_the_judge(self) -> None:
        """A custom Case is the only channel a local Judge has for the spec."""

        case = LocalCaseProvider(model=_FakeModel(_case_reply())).generate_case(
            _CaseContext()
        )

        assert case["rubric"]["behaviors_to_test"] == SECTIONS["behaviors_to_test"]
        assert case["rubric"]["prohibited_behaviors"] == SECTIONS["prohibited_behaviors"]

    @pytest.mark.parametrize("missing", sorted(SECTIONS))
    def test_a_missing_behavior_section_is_rejected(self, missing: str) -> None:
        """The official service refuses the same way; a local Case must not differ."""

        sections = {name: text for name, text in SECTIONS.items() if name != missing}
        with pytest.raises(LocalProviderError, match=missing):
            LocalCaseProvider(model=_FakeModel(_case_reply())).generate_case(
                _CaseContext(requirement_sections=sections)
            )

    def test_a_structured_requirement_is_rejected(self) -> None:
        with pytest.raises(LocalProviderError, match="text"):
            LocalCaseProvider(model=_FakeModel(_case_reply())).generate_case(
                _CaseContext(input_type="structured")
            )

    def test_an_empty_generated_prompt_is_rejected(self) -> None:
        model = _FakeModel({"steps": [{"step_id": "s1", "prompt": "   "}]})

        with pytest.raises(LocalProviderError, match="empty prompt"):
            LocalCaseProvider(model=model).generate_case(_CaseContext())

    def test_no_steps_at_all_is_rejected(self) -> None:
        with pytest.raises(LocalProviderError, match="no steps"):
            LocalCaseProvider(model=_FakeModel({"steps": []})).generate_case(
                _CaseContext()
            )


# --- Judge Provider ----------------------------------------------------------


class TestLocalJudgeProvider:
    def test_it_shows_the_judge_both_inputs_and_outputs(self) -> None:
        model = _FakeModel({"status": PASS, "confidence": 0.9, "summary": "fine"})

        LocalJudgeProvider(model=model).judge(
            _history(_Submission(output="the reply"))
        )

        prompt = model.prompts[0]
        assert "a question" in prompt
        assert "the reply" in prompt
        assert SECTIONS["behaviors_to_test"] in prompt

    def test_it_returns_the_judged_status_and_issues(self) -> None:
        model = _FakeModel(
            {
                "status": ISSUE,
                "confidence": 0.8,
                "summary": "missed a behavior",
                "issues": [{"code": "off_topic", "message": "did not answer", "step_id": "step_1"}],
                "step_results": [{"step_id": "step_1", "passed": False, "reason": "no answer"}],
            }
        )

        report = LocalJudgeProvider(model=model).judge(_history(_Submission()))

        assert report["status"] == ISSUE
        assert report["issues"][0]["code"] == "off_topic"
        assert report["extensions"]["summary"] == "missed a behavior"
        assert report["extensions"]["step_results"][0]["passed"] is False

    def test_an_unanswered_run_is_decided_without_asking_the_model(self) -> None:
        """Nothing to weigh, so spending a call on it would be waste."""

        model = _FakeModel({"status": PASS})

        report = LocalJudgeProvider(model=model).judge(
            _history(_Submission(status="failed", output=None, error="container died"))
        )

        assert report["status"] == INSUFFICIENT
        assert model.prompts == []
        assert "container died" in report["issues"][0]["message"]

    @pytest.mark.parametrize(
        "output",
        ["", "   ", None, [], {}],
        ids=["empty", "blank", "none", "empty-list", "empty-mapping"],
    )
    def test_empty_output_counts_as_unanswered_here_too(self, output: Any) -> None:
        """The two Judges must agree on what "answered" means.

        The startup Judge already treats an empty container as no answer. When
        this one disagreed, the same Run could pass startup verification and then
        be graded as having produced output worth weighing.
        """

        model = _FakeModel({"status": PASS})

        report = LocalJudgeProvider(model=model).judge(
            _history(_Submission(output=output))
        )

        assert report["status"] == INSUFFICIENT
        assert model.prompts == []

    def test_a_partially_answered_run_still_reaches_the_model(self) -> None:
        model = _FakeModel({"status": ISSUE, "confidence": 0.5, "summary": "mixed"})

        report = LocalJudgeProvider(model=model).judge(
            _history(_Submission(), _Submission(output=""))
        )

        assert model.prompts, "the judge should weigh a run that produced some output"
        assert report["status"] == ISSUE

    def test_an_unusable_status_is_rejected(self) -> None:
        model = _FakeModel({"status": "looks-good-to-me"})

        with pytest.raises(LocalProviderError, match="unusable status"):
            LocalJudgeProvider(model=model).judge(_history(_Submission()))

    @pytest.mark.parametrize(
        ("given", "expected"), [(1.5, 1.0), (-2, 0.0), ("high", 0.5), (None, 0.5)]
    )
    def test_confidence_is_clamped_into_the_contract(self, given, expected) -> None:
        """The SDK rejects a report whose confidence is outside 0..1."""

        model = _FakeModel({"status": PASS, "confidence": given})

        assert LocalJudgeProvider(model=model).judge(_history(_Submission()))[
            "confidence"
        ] == expected

    def test_a_case_without_a_rubric_is_rejected(self) -> None:
        model = _FakeModel({"status": PASS})
        context = _JudgeContext(history=(_Item(_Input("step_1"), _Submission()),), case=_Case(rubric=None))

        with pytest.raises(LocalProviderError, match="rubric"):
            LocalJudgeProvider(model=model).judge(context)

    def test_a_long_output_is_truncated_before_it_reaches_the_prompt(self) -> None:
        model = _FakeModel({"status": PASS, "confidence": 1.0})

        LocalJudgeProvider(model=model).judge(
            _history(_Submission(output="x" * 20_000))
        )

        assert "truncated" in model.prompts[0]
        assert len(model.prompts[0]) < 20_000
