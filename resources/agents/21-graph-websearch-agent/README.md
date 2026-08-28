# graph-websearch-agent (AgentBench adaptation)

AgentBench adaptation of
[john-adeojo/graph_websearch_agent](https://github.com/john-adeojo/graph_websearch_agent),
pinned at `fbeaf58`, MIT.

Nine nodes: planner → serper → selector → scraper → reporter → reviewer →
router, with the router able to send work back to any earlier stage before
`final_report` and `end`.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Web search | Google via Serper | fixture result list on `benchmark.invalid` |
| Page reading | `requests` + BeautifulSoup | fixture article bodies |
| Model provider | choice of OpenAI/Claude/Groq/Gemini/Ollama/vLLM | pinned to the OpenAI path |
| Entry point | Chainlit chat app | persistent JSONL worker |

The replacement tool functions reproduce upstream's return shapes exactly,
including the details that look like bugs: the search tool assigns a *string*
to `serper_response` even though the channel is annotated with `add_messages`,
and the scraper serialises with `str(dict)` rather than `json.dumps` and
truncates at 4000 characters. The agents parse what they are handed, so
fidelity matters more than tidiness here.

### The config file is deliberately empty

`utils/helper_functions.load_config()` copies every key of `config/config.yaml`
into the environment, substituting a placeholder string for blank values.
Upstream ships that file with a blank `OPENAI_API_KEY`, which would overwrite
the credential the Model Interceptor injects and make every model call fail
with a bogus key. The shipped file is an empty mapping, so the loop has nothing
to overwrite.

### Dependency pins

Upstream pins `langgraph==0.0.64` and `langchain-core==0.2.4`. Those no longer
resolve cleanly on Python 3.12, and `create_graph` needs only `StateGraph`,
`END`, and a checkpointer, so the 0.2/0.3 line is used instead.

`create_graph()` returns an *uncompiled* `StateGraph`; upstream compiles it in
a separate `compile_workflow()` call, which the wrapper mirrors.

## Input and output

```json
{"research_question": "..."}
```

`output` is the final report. `raw_output` carries the plan, the selected page,
the search results, the scraped text, and the review — enough for a judge to
check that the report follows from what was actually retrieved and that the
review was not a rubber stamp.

## Run it

```bash
python -m agentbench verify graph-websearch-agent
python -m agentbench certify graph-websearch-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Four fixture articles; answers are not real research.
- One page is opened per pass, so evidence breadth is bounded.
