# AgentK Web Researcher (AgentBench adaptation)

AgentBench adaptation of the `web_researcher` agent from
[mikekelly/AgentK](https://github.com/mikekelly/AgentK), pinned at
`e9ec892bddeb0b9afd77fbb130f0a89c5b715cb7`, MIT.

Upstream is a self-building agent system: `hermes` talks to a human,
`agent_smith` writes new agents, `tool_maker` writes new tools, and
`web_researcher` and `software_engineer` do the work. AgentBench selects one
graph, `web_researcher` — a two-node ReAct loop with a web-search tool and a
page-fetch tool.

## What was adapted

The graph is imported unchanged.

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | DuckDuckGo | `benchmark_mocks`, deterministic corpus |
| Page fetch | `SeleniumURLLoader` driving headless Chrome | deterministic markdown per corpus URL |
| Writable state | CWD | `/tmp/agentk/workspace` |
| Entry point | `agent_kernel.py` REPL | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

Both tools construct their client inside the call, so replacing the names they
look up is enough and the tool functions run unchanged. Replacing the Selenium
loader also means the image needs no browser or chromedriver at all.

`config.py` selects the provider from `DEFAULT_MODEL_PROVIDER` at import time
and raises on an unknown value, so the provider and model are pinned by the
manifest before anything imports it.

### Selected-agent subset

Only `agents/web_researcher.py` and the two tools it imports are vendored. The
sibling agents — which spawn other agents, run shell commands, and write files —
are not, so this adapter cannot do any of that. That is deliberate: the selected
graph's behaviour is what the benchmark measures.

## Input and output

The official Case provider emits text and the agent's native input is a research
task, so the mapping is close to the identity.

```json
{"task": "...", "answer": "final assistant message"}
```

`raw_output` adds the tool-call sequence, message count, answer length, and the
mock trace.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem, writes under `/tmp`.
- The agent prints its reasoning to stdout, so each request runs with stdout
  redirected to stderr and the JSONL reply goes to the original stream.
- `recursion_limit` is 30 so one Case stays bounded.

## Run it

```bash
python -m agentbench verify agentk-web-researcher
python -m agentbench certify agentk-web-researcher   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Every search result and page is a deterministic fixture from
  `benchmark.invalid`. Answers must not be presented as real research.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
