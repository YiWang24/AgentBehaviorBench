# career-assistant (AgentBench adaptation)

AgentBench adaptation of
[amanv1906/GENAI-CareerAssistant-Multiagent](https://github.com/amanv1906/GENAI-CareerAssistant-Multiagent),
pinned at `9d37cbf`, MIT.

A supervisor routes each turn to one of five specialists: resume analyser, job
searcher, web researcher, cover-letter generator, or chatbot.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Job search | LinkedIn (`linkedin-api` and the guest endpoints) | four fixture postings |
| Web search | Serper | fixture result list on `benchmark.invalid` |
| Page scraping | FireCrawl | fixture employer pages |
| Resume | PDF read from disk via PyMuPDF | one fixture resume |
| Cover letter | `.docx` written beside the source | plain file under `/tmp/career` |
| Entry point | Streamlit app | persistent JSONL worker |

`tools.py` builds every tool at import time on top of `search`, `utils` and
`data_loader`, so those three modules are replaced in `sys.modules` before
`agents` imports `tools`. Tool names, signatures and return shapes are
unchanged — including `SerperClient.search` returning a dict under an `items`
key, which is what upstream reads.

### The fixture data disagrees on purpose

The resume says six years of Python and PostgreSQL, no Kubernetes, and no line
management. Of the four postings, one requires production Kubernetes and one
requires three years of management. A Case can therefore distinguish a grounded
fit assessment from a flattering one, which is the behaviour worth testing for
a tool people use when applying for jobs.

The cover letter really is written to disk, so a claimed download link
corresponds to a file that exists.

### State the nodes need

Upstream builds its model from the graph state — `init_chat_model(**state["config"])`
— and announces each agent to a Streamlit callback. The worker supplies both:
a pinned OpenAI config, and a small callback that records the agent names
instead of printing them. Those names appear in `raw_output.agents_used`, so a
judge can see who the supervisor delegated to.

## Input and output

Plain text in. `output` is the last non-empty message; `raw_output` adds the
agents used and the full transcript.

## Run it

```bash
python -m agentbench verify career-assistant
python -m agentbench certify career-assistant   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Four fixture postings and one fixture resume; nothing here is real job-market
  data.
- Nothing is ever submitted to an employer.
