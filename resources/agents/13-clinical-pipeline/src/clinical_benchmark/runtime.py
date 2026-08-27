"""Runtime boundary: writable paths and configuration defaults.

The pipeline's reference data ships as Python literals and its GraphRAG service
defaults to an in-memory backend, so nothing here needs to point at a database.
The Neo4j, Postgres, and Redis settings are cleared so a host that happens to
export them cannot pull the agent onto a real service.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("CLINICAL_STATE_ROOT", "/tmp/clinical-pipeline"))

_SETTING_DEFAULTS = {
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-4o-mini",
}

_UNSET = (
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "REDIS_HOST",
    "DATABASE_URL",
    "FHIR_BASE_URL",
)

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    for variable, value in _SETTING_DEFAULTS.items():
        os.environ.setdefault(variable, value)
    for variable in _UNSET:
        os.environ.pop(variable, None)

    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)

    _prepared = True
