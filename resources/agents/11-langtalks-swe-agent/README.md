# LangTalks SWE Agent (AgentBench adaptation)

AgentBench adaptation of [langtalks/swe-agent](https://github.com/langtalks/swe-agent),
pinned at `5946af4f57cba03761015837ad5f87ef5c8d99e9`, MIT.

Upstream is a two-stage engineering agent: an architect researches the project
with search and code-map tools and produces a structured implementation plan,
then a developer applies that plan with file read/write tools.

Upstream's `langgraph.json` exposes three graphs — `agent`, `architect`, and
`developer`. The benchmark selects `agent`, the full architect-then-developer
pipeline.

## What was adapted

The graph is imported unchanged. Because this agent's work *is* filesystem
work, its tools are not stubbed: it gets a real, small, deterministic project to
edit inside a writable tmpfs workspace.

| Concern | Upstream | Here |
| --- | --- | --- |
| Project under edit | whatever the working directory holds | a fixture project copied into `/tmp` at process start |
| Network | `gitingest`, only ever given a local directory | all non-model HTTP clients raise |
| Tracing | LangSmith when a key is present | keys removed, tracing off |
| Entry point | LangGraph dev server | persistent JSONL worker |
| Model traffic | Anthropic via `langchain-anthropic` | unchanged; captured by the Model Interceptor |

### The fixture project

`benchmark_mocks/fixtures/example_project` is a small inventory ledger with one
deliberate defect: `Ledger.withdraw` lets the quantity on hand go negative
instead of refusing a withdrawal it cannot satisfy. That gives the agent
something concrete to find, plan for, and change, and it gives the Judge a
specific behaviour to check.

The fixture is copied fresh for every process, so runs cannot contaminate each
other, and `__pycache__` is excluded so pip's byte-compilation of the installed
package does not show up as a changed file.

### Packaging notes

Two upstream details matter once the project is `pip install`ed:

- `helpers/` ships without an `__init__.py` upstream and relies on the repo root
  being on `sys.path`. This copy adds the file so setuptools installs it as a
  real package; the modules are unchanged.
- Every prompt is a `.md` file loaded at import time via
  `helpers/../agent/<...>.md`. Once installed, that path resolves inside
  `site-packages`, which is correct — but only if the files ship in the wheel,
  so all eleven are declared as `package-data`.

`langgraph-cli` is not installed; it is the upstream dev server and the graph
does not reach it.

## Input and output

The official Case provider emits text and the agent's native input is an
engineering task, so the mapping is close to the identity.

Public output:

```json
{
  "task": "...",
  "implementation_plan": {"...": "..."},
  "changed_files": ["src/inventory/ledger.py"]
}
```

`changed_files` is computed by comparing a snapshot of the workspace before and
after the run, so the Judge can check whether the agent actually edited the
project rather than only describing an edit.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- The project under edit is materialised at
  `/tmp/langtalks-swe/workspace/workspace_repo` and the process sits in the
  parent directory. That name is the agent's own convention: its README and
  several of its prompts instruct it to address files as `./workspace_repo/...`,
  and `agent/tools/search.py` hardcodes that directory.
- `/tmp` is `noexec`, so the agent can edit code but cannot execute what it
  writes. Tasks must be about producing correct changes, not about running them.
- `recursion_limit` is 60 so one Case stays bounded.

## Run it

```bash
python -m agentbench verify langtalks-swe-agent
python -m agentbench certify langtalks-swe-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- The agent edits a fixture project, not real code. Changes are discarded when
  the container stops.
- It cannot run tests or any other command: `/tmp` is mounted `noexec` and no
  shell tool is bound.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
