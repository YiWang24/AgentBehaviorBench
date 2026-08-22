# Runtime Contract

This page covers the details that most often break Agent onboarding: Docker
filesystem layout, Python packaging, JSONL workers, and model interception.

## Docker Filesystem

AgentBench runs Agent containers with a read-only root filesystem, dropped
Linux capabilities, and fresh tmpfs mounts. Docker Agents with
`[llm_interception]` share the trusted Interceptor's network namespace; their
public traffic is controlled by that Interceptor.

| Path | Runtime behavior | Use |
| --- | --- | --- |
| `/opt/agent` | image content, read-only at runtime | installed Agent project, config, static files, vendored tools |
| `/tmp` | writable tmpfs with `noexec` | workspaces, state, logs, non-executable temporary data |
| `/run/agentbench-tools` | writable executable tmpfs | uploaded tool bundles with executable `bin/*` |

Never fix a tool execution problem by making all of `/tmp` executable. Put
executable uploaded tools under `/run/agentbench-tools`.

## Dockerfile Rules

Use a non-root image and let `agent.toml` own the launch command:

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/agent
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

USER agent
```

Do not set `ENTRYPOINT` unless the runtime contract is changed.

For Agents with project-relative config paths:

```dockerfile
ENV MY_AGENT_CONFIG_DIR=/opt/agent/config
ENV SWE_AGENT_CONFIG_ROOT=/opt/agent
```

For Agents that upload executable tools:

```dockerfile
ENV SWE_AGENT_TOOLS_ROOT=/run/agentbench-tools
```

## Installed Package Versus Source Tree

After `pip install .`, imported code lives under `site-packages`. This is a
common bug:

```python
repo_root = Path(__file__).resolve().parents[2]
config_path = repo_root / "config" / "agentbench.yaml"
```

Use explicit runtime paths instead:

```python
CONFIG_DIR = Path(os.getenv("MY_AGENT_CONFIG_DIR", "/opt/agent/config"))
config_path = CONFIG_DIR / "agentbench.yaml"
```

If runtime code needs fixtures, prompts, schemas, or templates, include them in
the wheel or image. For setuptools:

```toml
[tool.setuptools]
package-dir = {"" = "src"}
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]
include = ["my_agent*", "benchmark_mocks*"]

[tool.setuptools.package-data]
benchmark_mocks = [
    "fixtures/example_repo/README.md",
    "fixtures/example_repo/pyproject.toml",
    "fixtures/example_repo/src/example/__init__.py",
    "fixtures/example_repo/tests/test_example.py",
]
```

Add a test that every declared package-data file exists.

## JSONL Worker

The container must run a persistent stdin/stdout worker:

```text
stdin:  {"input": <SDK payload>, "run_config": <optional object>}\n
stdout: {"ok": true, "output": <public result>, "raw_output": <diagnostic>}\n
stdout: {"ok": false, "error": "ErrorType: safe message"}\n
```

Rules:

- Keep stdout as JSONL only; send logs to stderr.
- Handle multiple input lines in one process.
- Accept text and structured JSON-compatible inputs.
- Pass `run_config` to LangGraph when thread state is used.
- Normalize output to stable public behavior, not raw LangChain objects.
- Keep `raw_output` safe and serializable.

## Model Interceptor

The Agent container receives a temporary per-run token through the declared
Agent-facing variable. It continues to call the original public model URL;
transparent network interception validates that token, rewrites the request to
OpenRouter, and applies the run-selected model. `OPENROUTER_API_KEY` belongs to
the run environment, not the Agent manifest or `runtime.secret_env_keys`.

For OpenAI-compatible Agents:

```toml
[llm_interception]
required = true
trust_plugin = "pem-env"

[[llm_interception.credentials]]
id = "primary"
agent_env = "OPENAI_API_KEY"
auth_plugin = "bearer-token"

[[llm_interception.routes]]
id = "openai-chat"
host_patterns = ["api.openai.com"]
ports = [443]
methods = ["POST"]
path_patterns = ["/v1/chat/completions"]
protocol_plugin = "openai-chat"
credential = "primary"
```

This minimal declaration is enough when the Agent already calls
`https://api.openai.com/v1/chat/completions` and reads `OPENAI_API_KEY`. The
Agent keeps its original SDK, URL, payload, and source model. `agent_env` must
match the variable the existing client reads, while the route must describe the
request the client actually sends.

`[llm_interception.environment]` is optional. Use it only for ordinary settings
the Agent genuinely needs, not to redirect a supported client to OpenRouter:

```toml
[llm_interception.environment]
AGENT_LOG_LEVEL = "warning"
```

Run with one model-controlled OpenRouter target:

```powershell
$env:OPENROUTER_API_KEY = "..."
python -m agentbench run --model "openai/gpt-4.1-mini"
```

`OPENROUTER_MODEL` may be used instead of `--model`. The real OpenRouter key
stays in the trusted Interceptor. The Agent image must
declare a non-root `USER`, trust the run-specific CA through the selected Trust
plugin, and use a supported TCP-based HTTP protocol. Unmatched traffic is
forwarded without model Trace output.

Source changes are a compatibility fallback, not an onboarding step. They are
needed only for clients that cannot accept a temporary credential, cannot trust
the runtime CA, pin certificates, use an unsupported protocol, or bypass normal
TCP HTTP model requests.
