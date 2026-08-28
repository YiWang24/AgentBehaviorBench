"""A local stand-in for the official DefuzeX Case service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..protocols.providers import CaseGenerationContext
from .chat import ChatModel, LocalProviderError
from .prompts import CASE_SYSTEM, case_prompt

# The official service parses exactly these three sections out of a requirement
# and refuses to generate without them. A local Case built from anything less
# would not be testing the same contract.
BEHAVIOR_SECTIONS = (
    "production_scenario",
    "behaviors_to_test",
    "prohibited_behaviors",
)

CASE_ID = "case_local_behavior_v1"
STEP_PREFIX = "step"
MAX_PROMPT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class LocalCaseProvider:
    """Generate behavioral Inputs from the Agent's own requirement.

    This mirrors ``OfficialCaseProvider``: the same three requirement sections and
    the same Agent description go in, and text Inputs come out. The difference is
    only where the generation happens — a local model instead of the DefuzeX
    Backend — so the SDK still owns Case normalization, the Run, and the report.

    The rubric is published in the Case rather than kept private. An official Case
    can hide it because the official Judge already knows it; a local Judge has no
    such channel, so the Case carries the behavior spec forward.
    """

    model: ChatModel
    requirement_required: bool = True

    def generate_case(self, context: CaseGenerationContext) -> dict[str, Any]:
        if context.input_type != "text":
            raise LocalProviderError(
                "Local Case generation currently supports text Inputs only"
            )
        spec = _behavior_spec(context.requirement_sections)
        description = (context.agent_description or "").strip()
        if not description:
            raise LocalProviderError(
                "The requirement must declare a non-empty agent_description"
            )

        reply = self.model.json_object(
            system=CASE_SYSTEM,
            user=case_prompt(
                count=context.max_inputs,
                agent_description=description,
                **spec,
            ),
        )
        steps = _steps(reply, max_inputs=context.max_inputs)
        return {
            "case_id": CASE_ID,
            "input_type": "text",
            "rubric": {
                "rule": "behavior_spec",
                "behaviors_to_test": spec["behaviors_to_test"],
                "prohibited_behaviors": spec["prohibited_behaviors"],
                "targets": {step["input_id"]: step.pop("_targets") for step in steps},
            },
            "inputs": steps,
        }


def _behavior_spec(sections: Mapping[str, str]) -> dict[str, str]:
    """Require the same three sections the official service requires."""

    spec: dict[str, str] = {}
    for name in BEHAVIOR_SECTIONS:
        value = sections.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LocalProviderError(
                f"The requirement is missing its '{name}' section, which local "
                "Case generation needs just as the official service does"
            )
        spec[name] = value.strip()
    return spec


def _steps(reply: Mapping[str, Any], *, max_inputs: int) -> list[dict[str, Any]]:
    """Turn the model's answer into Inputs, or say precisely why it is unusable."""

    raw = reply.get("steps")
    if not isinstance(raw, list) or not raw:
        raise LocalProviderError(
            "Local Case generation returned no steps"
        )
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:max_inputs], start=1):
        if not isinstance(item, Mapping):
            raise LocalProviderError("Local Case generation returned an invalid step")
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise LocalProviderError(
                f"Local Case generation returned an empty prompt for step {index}"
            )
        steps.append(
            {
                # Numbering here rather than trusting the model keeps input_ids
                # unique and valid even when it repeats or invents one.
                "input_id": f"{STEP_PREFIX}_{index}",
                "payload_type": "text",
                "payload": prompt.strip()[:MAX_PROMPT_CHARS],
                "_targets": str(item.get("targets") or "").strip(),
            }
        )
    return steps


__all__ = ["BEHAVIOR_SECTIONS", "CASE_ID", "LocalCaseProvider"]
