# ReAct Agent (AgentBench adaptation)

AgentBench adaptation of [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent),
pinned at `91092e0e124ac989f2f4ddb9854090a4b9d89723`, MIT.

Upstream is LangChain's ReAct template: a two-node loop — `call_model` and
`tools` — with one example web-search tool. It is the smallest complete agent in
the benchmark, which makes it a useful control: a failure here points at the
harness rather than at agent complexity.

## What was adapted

The graph is imported unchanged — same prompt, same context dataclass, same
loop.

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Tavily (`langchain-tavily`) | `benchmark_mocks`, deterministic corpus |
| Writable state | CWD | `/tmp/react-agent/workspace` |
| Entry point | LangGraph dev server | persistent JSONL worker |
| Model traffic | Anthropic via `langchain-anthropic` | unchanged; captured by the Model Interceptor |

`react_agent.tools.search` constructs `TavilySearch` per call, so replacing the
module-level name is enough and the `search` tool itself still runs.
`langchain-tavily` is still installed, because `tools.py` imports the class at
module level and the vendored source is unchanged.

`Context` reads its defaults from upper-cased environment variables, so `MODEL`
and `MAX_SEARCH_RESULTS` are pinned by the manifest rather than left to the
host.

## Input and output

The official Case provider emits text and the agent's native input is a chat
message, so the mapping is close to the identity.

```json
{"query": "...", "answer": "final assistant message"}
```

`raw_output` adds the tool-call sequence, message count, answer length, and the
mock trace.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- Writes go to `/tmp/react-agent/workspace`, created at process start.
- `recursion_limit` is 30 so one Case stays bounded.

## Run it

```bash
python -m agentbench verify react-agent
python -m agentbench certify react-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Every search result is a deterministic fixture served from
  `benchmark.invalid`. Answers must not be presented as real research.
- Search is the only tool; the agent cannot act on the world.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
