# DeepAgents Deep Research (AgentBench adaptation)

AgentBench adaptation of the `examples/deep_research` agent from
[langchain-ai/deepagents](https://github.com/langchain-ai/deepagents), pinned at
`92e15dc0cb6d39fce1024483c30408f1b33e7549`, MIT.

The `deepagents` library is a framework, not an agent. This adapter selects the
repository's deep-research example as the agent under test: an orchestrator with
a planning/filesystem middleware stack that delegates topics to a research
sub-agent, which searches, reads pages, and reflects with a think tool.

## What was adapted

The agent is imported unchanged — same prompts, same tools, same sub-agent
delegation, same Anthropic model client.

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Tavily API | `benchmark_mocks`, deterministic corpus |
| Page fetch | `httpx.get` + `markdownify` | deterministic markdown per corpus URL |
| Writable state | CWD | `/tmp/deep-research/workspace` |
| Entry point | LangGraph dev server | persistent JSONL worker |
| Model traffic | Anthropic via `langchain-anthropic` | unchanged; captured by the Model Interceptor |

Only two module globals in `research_agent.tools` are replaced —
`tavily_client` and `fetch_webpage_content`. The `tavily_search` tool itself
still runs, so its own result formatting is exercised by the benchmark rather
than stubbed out.

`research_agent.tools` constructs `TavilyClient()` at import time, which raises
without a key, so the runtime boundary sets a placeholder `TAVILY_API_KEY`
before that import. The client object is replaced immediately afterwards and
the placeholder never authenticates anything.

### Layout

The `deepagents` library is vendored from `libs/deepagents` at the pinned
revision rather than installed from PyPI, so the benchmark pins the exact code
under test. The example's top-level `agent.py` moved to
`src/research_agent/agent.py` to fit the `src` layout; its imports are
unchanged because `research_agent` remains a top-level package.

`examples/` (other than deep_research), `libs/` (other than `deepagents`),
`openwiki/`, and the notebook are not vendored.

## Input and output

The official Case provider emits text and the agent's native input is a
research request, so the mapping is close to the identity: whitespace is
collapsed and the query is capped at 2000 characters.

Public output:

```json
{
  "query": "...",
  "answer": "final assistant message",
  "files": ["research_notes.md"]
}
```

`raw_output` adds the tool-call sequence, message count, answer length, and the
mock trace. Neither contains credentials.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- Writes go to `/tmp/deep-research/workspace`, created at process start; the
  process moves there before any upstream import.
- `recursion_limit` is 60 so one Case stays bounded.

## Run it

```bash
python -m agentbench verify deepagents-research
python -m agentbench certify deepagents-research   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Every source document is a deterministic fixture served from
  `benchmark.invalid`. Answers must not be presented as real research.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
- The agent has a virtual filesystem for notes; nothing is written outside
  `/tmp`.
