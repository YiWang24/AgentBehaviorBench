# mcp-agent (AgentBench adaptation)

AgentBench adaptation of
[braincrew-lab/langgraph-mcp-agents](https://github.com/braincrew-lab/langgraph-mcp-agents),
pinned at `d4694e9`.

A `create_react_agent` loop whose tools are **discovered from Model Context
Protocol servers at startup** rather than written into the agent.

## Why this one is worth having

It is the first MCP agent in the benchmark. Every other tool-using adaptation
here binds tools the project authored; this one connects a
`MultiServerMCPClient` to servers named in a config file and hands whatever it
discovers to the model. The failure modes are different — the agent has to pick
among tools whose shape it did not choose — and `raw_output` records both the
tool calls and which servers were configured.

The servers really run: two Python processes are spawned over stdio inside the
container. Nothing is mocked.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Entry point | Streamlit app (`app.py`) | persistent JSONL worker |
| Agent construction | inside `initialize_session()` | the same three calls, in a wrapper |
| Configured servers | `config.json` (time only) | time **and** the local weather server |
| Model | user-selected Claude or GPT | the OpenAI path |

`app.py` is a Streamlit application, so importing it would pull in the whole
UI. The wrapper makes upstream's own three calls — `MultiServerMCPClient(config)`,
`client.get_tools()`, `create_react_agent(model, tools, checkpointer, prompt)`
— against upstream's own config file and server scripts. Its `SYSTEM_PROMPT` is
copied verbatim into `prompt.py` rather than the module being vendored.

`mcp_server_remote.py` and `mcp_server_rag.py` are not shipped: the first needs
a network endpoint, the second needs FAISS and a PDF corpus. Neither is among
the configured servers.

### The weather tool is a stub, and that matters for Cases

Upstream's `get_weather` is documented in its own docstring as simulated and
returns `"It's always Sunny in {location}"` for every location. That makes it a
good test of whether the agent prefers tool output over prior knowledge — and a
bad thing to treat as a forecast. The requirement file says so explicitly.

### Licence

Upstream declares MIT in its README (badge and a "License" section) but ships no
LICENSE file and no licence field in `pyproject.toml`. `NOTICE` records the
declaration rather than inventing a licence text.

## Input and output

Plain text in. `output` is the answer; `raw_output` adds every tool call with
its arguments and the configured server list.

## Run it

```bash
python -m agentbench verify mcp-agent
python -m agentbench certify mcp-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Two tools only: a real clock and a stubbed weather service.
- The MCP client and its subprocesses are started once and reused across
  requests.
