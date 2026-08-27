"""Runtime boundary: writable paths and configuration defaults."""

from __future__ import annotations

import os
from pathlib import Path

STATE_ROOT = Path(os.environ.get("QDAD_STATE_ROOT", "/tmp/open-deepthink"))

MODEL = os.environ.get("QDAD_MODEL", "gpt-4o-mini")

# A 2x2 grid with one denoising step keeps a single Case bounded: the noise and
# denoise nodes fan out over every cell in parallel, so the model-call count
# grows with N squared times the step count.
GRID_SIZE = int(os.environ.get("QDAD_GRID_SIZE", "2"))
DENOISING_STEPS = int(os.environ.get("QDAD_DENOISING_STEPS", "1"))

_prepared = False


def prepare() -> None:
    """Create writable directories and apply benchmark defaults. Idempotent."""
    global _prepared
    if _prepared:
        return

    os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
    workspace = STATE_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", "/opt/agent/tiktoken-cache")
    os.chdir(workspace)

    _prepared = True
