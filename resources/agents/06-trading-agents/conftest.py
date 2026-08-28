"""Make the raw-copied ``benchmark_mocks`` package importable under pytest.

Mirrors what the Docker runtime gets for free: WORKDIR=/opt/agent plus
``python -m trading_agents_benchmark.worker`` implicitly prepends the
working directory to ``sys.path``. pytest does not do that automatically for
an arbitrary rootdir, so this conftest (loaded for any test collected under
this directory) does it explicitly.
"""

import sys
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))
