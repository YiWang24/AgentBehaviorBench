"""Materialise the deterministic fixture project into a writable workspace.

The agent's tools read and write files relative to the current directory, so
the benchmark gives it a real small project to work on rather than stubbing the
filesystem. The fixture ships inside the installed package; ``/tmp`` is a fresh
tmpfs at container start, so the copy happens at process start, never in the
Dockerfile.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

FIXTURE_PACKAGE = "benchmark_mocks.fixtures"
FIXTURE_NAME = "example_project"
# The agent's own convention -- documented in its README and baked into its
# prompts -- is that the codebase under edit sits at ./workspace_repo
# relative to the working directory.
WORKSPACE_DIRNAME = "workspace_repo"

TRACE: list[dict[str, object]] = []


def record(service: str, operation: str, summary: str) -> None:
    TRACE.append({"service": service, "operation": operation, "summary": summary})


def trace_summary() -> list[dict[str, object]]:
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def materialise(destination: Path) -> Path:
    """Copy the fixture project to `destination/workspace_repo`, replacing any previous copy."""
    target = destination / WORKSPACE_DIRNAME
    if target.exists():
        shutil.rmtree(target)
    with resources.as_file(resources.files(FIXTURE_PACKAGE)) as fixtures:
        source = Path(fixtures) / FIXTURE_NAME
        if not source.is_dir():
            raise RuntimeError(
                f"Fixture project missing from the installed package: {source}. "
                "Check [tool.setuptools.package-data]."
            )
        # pip byte-compiles the installed package, so the fixture directory
        # carries __pycache__ that is not part of the project under test and
        # would show up as changed files.
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    record("workspace", "materialise", str(target))
    return target


def snapshot(root: Path) -> dict[str, int]:
    """Map every file under `root` to its size, for the diagnostic output."""
    return {
        str(path.relative_to(root)): path.stat().st_size
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
