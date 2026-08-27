import json
import stat
import tempfile
from pathlib import Path
from types import MappingProxyType

import pytest

from agentbench.runtime.docker import DockerPolicy
from agentbench.runtime.docker.runtime import (
    CA_EXPORT_DIR_MODE,
    DockerRuntime,
    _literal_route_hosts,
)
from agentbench.runtime.docker.session import _json_compatible
from agentbench.runtime.interception import (
    CredentialConfig,
    InterceptionConfig,
    RouteConfig,
)


def _interception(*host_patterns: str) -> InterceptionConfig:
    return InterceptionConfig(
        required=True,
        trust_plugin="pem-env",
        environment=MappingProxyType({}),
        credentials=(
            CredentialConfig(
                credential_id="primary",
                agent_env="LLM_API_KEY",
                auth_plugin="bearer-token",
            ),
        ),
        routes=tuple(
            RouteConfig(
                route_id=f"route-{index}",
                host_patterns=(pattern,),
                ports=(443,),
                methods=("POST",),
                path_patterns=("/v1/chat/completions",),
                protocol_plugin="openai-chat",
                credential_id="primary",
            )
            for index, pattern in enumerate(host_patterns)
        ),
    )


def test_docker_policy_contains_required_isolation_controls() -> None:
    arguments = DockerPolicy().run_arguments()

    assert "--read-only" in arguments
    assert "--cap-drop=ALL" in arguments
    assert "--security-opt=no-new-privileges" in arguments
    assert any(value.startswith("--memory=") for value in arguments)
    assert any(value.startswith("--cpus=") for value in arguments)
    assert any(value.startswith("--pids-limit=") for value in arguments)
    assert any(value.startswith("--tmpfs=/tmp:rw,") for value in arguments)
    assert any("noexec" in value for value in arguments if value.startswith("--tmpfs=/tmp:"))
    assert any(
        value.startswith("--tmpfs=/run/agentbench-tools:rw,")
        and "exec" in value
        and "noexec" not in value
        for value in arguments
    )


def test_open_egress_keeps_the_network_reachable_and_adds_no_aliases() -> None:
    runtime = DockerRuntime()

    assert runtime._network_options() == ()
    assert runtime._host_alias_arguments(_interception("api.openai.com")) == ()


def test_blocked_egress_isolates_the_network_and_aliases_hosts_to_loopback() -> None:
    runtime = DockerRuntime(egress="blocked")

    assert runtime._network_options() == ("--internal",)
    assert runtime._host_alias_arguments(_interception("api.openai.com")) == (
        "--add-host",
        "api.openai.com:127.0.0.1",
    )


def test_blocked_egress_skips_wildcard_hosts_and_deduplicates() -> None:
    runtime = DockerRuntime(egress="blocked")
    interception = _interception("api.openai.com", "*.anthropic.com", "api.openai.com")

    assert _literal_route_hosts(interception) == ("api.openai.com",)
    assert runtime._host_alias_arguments(interception) == (
        "--add-host",
        "api.openai.com:127.0.0.1",
    )


def test_unsupported_egress_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="egress mode"):
        DockerRuntime(egress="sometimes")  # type: ignore[arg-type]


def test_ca_export_directory_is_writable_by_a_foreign_container_uid() -> None:
    """The interceptor is container root without CAP_DAC_OVERRIDE, so the exported
    CA directory must not depend on matching the host owner's uid."""

    with tempfile.TemporaryDirectory() as parent:
        ca_dir = Path(parent) / "ca"
        ca_dir.mkdir()
        ca_dir.chmod(CA_EXPORT_DIR_MODE)

        mode = stat.S_IMODE(ca_dir.stat().st_mode)
        assert mode & stat.S_IWOTH, f"others cannot write CA dir (mode {mode:o})"
        assert mode & stat.S_IXOTH, f"others cannot traverse CA dir (mode {mode:o})"


def test_docker_transport_serializes_frozen_sdk_payloads() -> None:
    payload = MappingProxyType(
        {
            "email_input": MappingProxyType({"subject": "Hello"}),
        }
    )

    encoded = json.dumps(payload, default=_json_compatible)

    assert json.loads(encoded) == {"email_input": {"subject": "Hello"}}
