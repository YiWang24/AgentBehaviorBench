import re
import tomllib
from pathlib import Path

import pytest

from agentbench.harness.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "resources" / "registry.toml"

SUPPORTED_STATUSES = frozenset({"planned", "adapting", "ready", "blocked"})
AGENT_DIRECTORY_PATTERN = re.compile(r"^(?P<order>\d+)-(?P<agent_id>.+)$")


def _registered_agent_ids() -> list[str]:
    """Read agent ids straight from the registry file for parametrization."""
    with REGISTRY_PATH.open("rb") as stream:
        data = tomllib.load(stream)
    return [str(item["agent_id"]) for item in data.get("agents", [])]


@pytest.mark.parametrize("agent_id", _registered_agent_ids())
def test_registry_resolves_registered_agents(agent_id: str) -> None:
    registry = load_registry(REGISTRY_PATH)

    agent = registry.find(agent_id, enabled_only=False)

    assert agent.agent_id == agent_id
    assert agent.framework == "langgraph"
    assert agent.status in SUPPORTED_STATUSES
    assert agent.case_count >= 1
    assert agent.source
    assert agent.path.parent == REPO_ROOT / "resources" / "agents"
    assert agent.path.is_dir()
    assert agent.path.joinpath("agent.toml").is_file()
    assert agent.requirement_path == (
        REPO_ROOT / "resources" / "requirements" / f"{agent_id}.md"
    )


@pytest.mark.parametrize("agent_id", _registered_agent_ids())
def test_agent_directory_prefix_is_not_part_of_the_agent_id(agent_id: str) -> None:
    agent = load_registry(REGISTRY_PATH).find(agent_id, enabled_only=False)

    match = AGENT_DIRECTORY_PATTERN.match(agent.path.name)

    assert match is not None, f"Directory must be <order>-<agent-id>: {agent.path.name}"
    assert match.group("agent_id") == agent_id


@pytest.mark.parametrize("agent_id", _registered_agent_ids())
def test_manifest_agent_id_matches_the_registry(agent_id: str) -> None:
    agent = load_registry(REGISTRY_PATH).find(agent_id, enabled_only=False)

    with agent.path.joinpath("agent.toml").open("rb") as stream:
        manifest = tomllib.load(stream)

    assert manifest.get("agent_id") == agent_id


def test_every_enabled_agent_has_an_sdk_requirement() -> None:
    registry = load_registry(REGISTRY_PATH)

    for agent in registry.enabled():
        requirement = REPO_ROOT / "resources" / "requirements" / f"{agent.agent_id}.md"
        assert requirement.is_file(), f"Missing SDK requirement: {requirement}"
        assert agent.requirement_path == requirement


def test_ready_agents_are_the_default_runnable_subset() -> None:
    registry = load_registry(REGISTRY_PATH)

    enabled = set(registry.enabled())
    ready = set(registry.ready())
    adapting = set(registry.enabled_with_status("adapting"))

    assert ready <= enabled
    assert adapting <= enabled
    assert not ready & adapting
    assert all(agent.status == "ready" for agent in ready)
    assert all(agent.status == "adapting" for agent in adapting)


def test_registry_defaults_case_count_to_one(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path)

    agent = load_registry(registry_path).find("test-agent")

    assert agent.case_count == 1


@pytest.mark.parametrize("case_value", ["0", "-1", "true", '"2"', "1.5"])
def test_registry_rejects_invalid_case_count(
    tmp_path: Path, case_value: str
) -> None:
    registry_path = _write_registry(tmp_path, case_value=case_value)

    with pytest.raises(ValueError, match="positive integer: case"):
        load_registry(registry_path)


def _write_registry(tmp_path: Path, *, case_value: str | None = None) -> Path:
    resources = tmp_path / "resources"
    agent_path = resources / "agents" / "test-agent"
    requirement_path = resources / "requirements" / "test-agent.md"
    agent_path.mkdir(parents=True)
    requirement_path.parent.mkdir(parents=True)
    (agent_path / "agent.toml").write_text(
        'agent_id = "test-agent"\n', encoding="utf-8"
    )
    requirement_path.write_text("# Test requirement\n", encoding="utf-8")
    case_line = "" if case_value is None else f"case = {case_value}\n"
    registry_path = resources / "registry.toml"
    registry_path.write_text(
        'schema_version = "defuzex-bench.registry.v1"\n\n'
        "[[agents]]\n"
        'agent_id = "test-agent"\n'
        'path = "resources/agents/test-agent"\n'
        'framework = "langgraph"\n'
        f"{case_line}",
        encoding="utf-8",
    )
    return registry_path
