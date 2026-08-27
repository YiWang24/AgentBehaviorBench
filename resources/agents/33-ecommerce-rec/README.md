# ecommerce-rec (AgentBench adaptation)

AgentBench adaptation of
[bcefghj/multi-agent-ecommerce-system](https://github.com/bcefghj/multi-agent-ecommerce-system),
pinned at `faf0fd8`.

Six nodes: build a user profile and recall products in parallel, rank, filter
by stock, write marketing copy, aggregate.

## What was adapted

Nothing upstream is substituted. The catalogue is already a fixture, the
feature store degrades to empty features without a Redis client, and Milvus and
the SQLite database are not imported on the graph path — so `benchmark_mocks`
installs the egress guard only.

| Concern | Upstream | Here |
| --- | --- | --- |
| Catalogue | `MOCK_PRODUCTS` (already a fixture) | unchanged |
| Feature store | Redis-backed | no client; methods return empty features |
| Vector store / DB | Milvus, SQLite | not on the graph path; not vendored |
| Model endpoint | MiniMax, OpenAI-compatible | unchanged; captured on the MiniMax route |
| Entry point | FastAPI service | persistent JSONL worker |

The agents self-instantiate at module scope with no external clients, so
`build_recommendation_graph()` is used unchanged.

### Interception without editing the source

The agents point `ChatOpenAI` at `https://api.minimax.chat/v1`, MiniMax's
OpenAI-compatible endpoint. That is the OpenAI chat wire protocol, so the route
matches that host with the `openai-chat` plugin. Two path patterns are listed
because MiniMax exposes both `/v1/chat/completions` and its own
`/v1/text/chatcompletion_v2`.

### Licence

Upstream declares MIT in its README (badge and a `[MIT License](LICENSE)` link)
but ships no LICENSE file and no licence field in package metadata. `NOTICE`
records the declaration rather than inventing a licence text.

## Input and output

The pipeline takes a user id and a scene, not free text. The Case's text is
treated as the scene (defaulting to `homepage`) and recorded in
`raw_output.request`; a JSON payload may also set `user_id` and `num_items`.
`output` is the recommended products with their marketing copy; `raw_output`
adds the ranked list, the experiment group, and the latency.

## Run it

```bash
python -m agentbench verify ecommerce-rec
python -m agentbench certify ecommerce-rec   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Small fixture catalogue; no real inventory or prices.
- User behaviour history is empty (no feature-store backing), so the profile is
  built from the request alone.
