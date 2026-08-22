from __future__ import annotations

import os
from pathlib import Path

from agentbench.cli.environment import load_project_environment


def test_environment_file_does_not_override_the_process_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "OPENROUTER_API_KEY=file-key\nOPENROUTER_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_MODEL", "process-model")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert load_project_environment(path) == path.resolve()

    assert os.environ["OPENROUTER_API_KEY"] == "file-key"
    assert os.environ["OPENROUTER_MODEL"] == "process-model"
