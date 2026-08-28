# Research Assistant (AgentBench adaptation)

AgentBench adaptation of the `research-assistant` agent from
[JoshuaC215/agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit),
pinned at `0c58abfce18ba97d10507f0ffd0b151d5a843e74`, MIT.

Upstream is a service toolkit hosting a dozen agents behind FastAPI and
Streamlit. Its `langgraph.json` names one graph, `research_assistant`, and that
is the agent under test: a safeguard node, a model node with web search and a
calculator, and a tool node, wired so unsafe input is blocked before the model
ever runs.

## What was adapted

The selected graph is imported unchanged — same prompts, same tools, same
routing, same safeguard.

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | DuckDuckGo | `benchmark_mocks`, deterministic corpus |
| Weather tool | OpenWeatherMap, added when a key is present | key left unset, so the tool is never bound |
| Safeguard | LlamaGuard on Groq, when a key is present | key left unset, so the node short-circuits to SAFE |
| Writable state | CWD | `/tmp/research-assistant/workspace` |
| Entry point | FastAPI service / Streamlit UI | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

Only the search tool's `api_wrapper` is replaced, and only after the module has
constructed its tools. The `DuckDuckGoSearchResults` tool object the graph bound
still runs, so its own result formatting is exercised rather than stubbed.

### Why the extra keys stay unset

Upstream adds a tool or a node whenever the matching key is present:
`OPENWEATHERMAP_API_KEY` binds a weather tool, and `GROQ_API_KEY` turns the
safeguard into a real LlamaGuard call on a second provider. The benchmark
declares exactly one model route, so the runtime boundary deletes those
variables rather than leaving the behaviour to whatever the host happens to
export. The safeguard node still runs; it returns SAFE without a model call,
which is upstream's own documented behaviour when the key is absent.

### Selected-agent subset

Upstream's `agents/__init__.py` re-exports `agents.agents`, which eagerly
imports every agent in the repository — the MCP agent, two supervisor
hierarchies, the background-task agent, and the RAG assistants. Importing the
research assistant would therefore drag in the entire fleet and its
dependencies. Since AgentBench selects exactly one graph, this vendored copy
replaces `agents/__init__.py` with a docstring-only module and does not vendor
the sibling agent modules. **Every module the selected graph imports is vendored
unchanged**, including `agents/tools.py` and the whole of `core/` and `schema/`.

### Dependencies

Upstream declares 42 dependencies covering a FastAPI service, a Streamlit UI,
four checkpointer backends, and a dozen model providers. Two eager imports
force more than the graph strictly needs and are honoured rather than edited
around:

- `core/llm.py` imports all six provider SDKs at module level, so
  `langchain-anthropic`, `-aws`, `-google-genai`, `-google-vertexai`, `-groq`,
  and `-ollama` are installed even though only OpenAI is ever called.
- `agents/tools.py` imports `langchain_chroma` at module level for a retrieval
  tool the research assistant does not bind.

## Input and output

The official Case provider emits text and the assistant's native input is a
chat message, so the mapping is close to the identity: whitespace is collapsed
and the query is capped at 2000 characters.

Public output:

```json
{
  "query": "...",
  "answer": "final assistant message",
  "safety_assessment": "safe"
}
```

`raw_output` adds the tool-call sequence, message count, answer length, and the
mock trace. Neither contains credentials.

## Runtime

- Non-root (`uid 10001`), read-only root filesystem.
- Writes go to `/tmp/research-assistant/workspace`, created at process start.
- `recursion_limit` is 30 so one Case stays bounded; upstream's own
  `remaining_steps` guard still applies.

## Run it

```bash
python -m agentbench verify agent-service-research
python -m agentbench certify agent-service-research   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Every search result is a deterministic fixture served from
  `benchmark.invalid`. Answers must not be presented as real research.
- The safeguard reports SAFE without evaluating content, because no Groq key is
  configured. Safety-classification behaviour is therefore not under test.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
