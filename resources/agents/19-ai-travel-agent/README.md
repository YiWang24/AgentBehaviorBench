# ai-travel-agent (AgentBench adaptation)

AgentBench adaptation of
[nirbar1985/ai-travel-agent](https://github.com/nirbar1985/ai-travel-agent),
pinned at `930d9c4`, MIT.

A tool-calling loop that searches flights and hotels, writes an itinerary, and
stops at an approval gate before emailing it.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Flight and hotel search | Google Flights / Hotels via SerpAPI | deterministic fixture inventory |
| Email | SendGrid send after approval | never resumed past the approval gate |
| Entry point | Streamlit app | persistent JSONL worker |
| Model traffic | OpenAI via `langchain-openai` | unchanged; captured by the Model Interceptor |

### The email gate is upstream's, not ours

The graph is compiled with `interrupt_before=['email_sender']` — upstream's own
human-approval step. The benchmark honours it and never resumes, so the
SendGrid client is imported but never called and no message is ever
constructed. `raw_output` records `email_sent: false` and where the run
stopped, so a judge can check the Agent does not *claim* to have sent one.

### Why the tool modules are replaced wholesale

`agents/tools/*.py` import `serpapi` and `langchain.pydantic_v1` at module
scope. The first needs a key and egress; the second was removed from the
langchain line this image installs. Rather than pin langchain back to 0.2 or
edit the vendored files, `benchmark_mocks.install()` registers replacement
modules in `sys.modules` before `agents.agent` imports them. The tool names,
docstrings, and argument schemas are reproduced exactly, so the model sees the
same tools and its tool-calling behaviour is unchanged.

### stdout belongs to the protocol

`Agent.__init__` prints a mermaid rendering of the graph and `invoke_tools`
prints every tool call. stdout carries JSONL, so the wrapper runs graph
construction and every invocation under `contextlib.redirect_stdout(sys.stderr)`
instead of deleting the prints from the vendored source.

## Input and output

```json
{"messages": [{"role": "user", "content": "..."}]}
```

`output` is the itinerary. `raw_output` adds the tool calls the Agent made with
their arguments, so a judge can check it searched the route and dates it was
actually given.

## Run it

```bash
python -m agentbench verify ai-travel-agent
python -m agentbench certify ai-travel-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- The inventory is generated from the query. Prices and availability are
  reproducible but fictional; no result corresponds to a real flight or hotel.
- Nothing is ever booked and no email is ever sent.
