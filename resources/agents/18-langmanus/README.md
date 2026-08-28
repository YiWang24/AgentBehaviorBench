# langmanus (AgentBench adaptation)

AgentBench adaptation of [darwin-lau/langmanus](https://github.com/darwin-lau/langmanus),
pinned at `a69eabf`, MIT.

LangManus is a hierarchical research team: a coordinator decides whether the
team is needed, a planner writes the plan, a supervisor delegates each step,
and researcher, coder, browser and reporter agents carry it out.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Tavily | fixture result list on `benchmark.invalid` |
| Page reading | Jina reader (`r.jina.ai`) | fixture markdown articles |
| Browser | `browser-use` driving real Chrome | fixture session transcript |
| Entry point | FastAPI service / `main.py` | persistent JSONL worker |
| Workspace | process working directory | `/tmp/langmanus`, the only writable path |
| Model traffic | OpenAI + DeepSeek | unchanged; both captured by the Model Interceptor |

### Why the substitution happens through `sys.modules`

`src/tools/__init__.py` constructs every tool at import time and
`src/agents/agents.py` builds the three ReAct agents on top of them, also at
import time. There is no injection point. `benchmark_mocks.install()`
therefore registers replacement modules in `sys.modules` under
`src.tools.search`, `src.tools.crawl`, `src.tools.browser` and `src.crawler`
*before* anything imports them, and Python's import machinery hands those out
instead of loading the originals. `install()` raises if it runs too late, so
the ordering cannot silently regress.

A consequence worth stating: `browser-use` is never imported, so neither
Chrome nor Playwright is installed. The image is a plain `python:3.12-slim`.

### Two model providers, both captured

The reasoning role — used by the planner in deep-thinking mode — is a
`langchain-deepseek` client, not an OpenAI one. Rather than quietly swapping it
for `ChatOpenAI`, it keeps its own client and gets its own interception route:
`ChatDeepSeek` speaks the OpenAI chat wire protocol, so the `openai-chat`
plugin captures `api.deepseek.com` with a separate credential.

### Prompt templates ship as package data

`src/prompts/template.py` opens `<name>.md` next to the module, which after
`pip install .` resolves inside site-packages. The `.md` files are declared in
`[tool.setuptools.package-data]` or every node raises `FileNotFoundError`.

## What the offline gate does and does not cover

`coordinator_node` hands off only when the model's reply literally contains
`handoff_to_planner`. The offline mock synthesises generic replies, so under
`verify` the graph legitimately ends after the coordinator with one captured
model call. That is upstream's real behaviour for a reply that does not
request the team, not a defect in the adaptation.

The rest of the graph was exercised separately with a local stub model that
returns a valid plan: coordinator → planner (streaming, on the DeepSeek route)
→ supervisor (structured output) → researcher (tool calls against the fixture
search and crawl tools) → supervisor, for 21 captured model calls. The full
path runs. `certify`, against a real model, exercises it end to end.

## Input and output

```json
{"TEAM_MEMBERS": [...], "messages": [{"role": "user", "content": "..."}],
 "deep_thinking_mode": true, "search_before_planning": true}
```

`output` is the reporter's message when the team ran, otherwise the last
non-empty message. `raw_output` adds the plan and the full message list with
each author's name, so a judge can check who was asked to do what.

## Run it

```bash
python -m agentbench verify langmanus
python -m agentbench certify langmanus   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Search, page reads and browsing are fixtures; answers are not real research.
- The coder agent's Python and shell run in the sandboxed container against a
  temporary workspace and no network.
