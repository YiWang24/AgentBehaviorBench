# nl2sql-agent (AgentBench adaptation)

AgentBench adaptation of
[eosho/langchain_data_agent](https://github.com/eosho/langchain_data_agent),
pinned at `9081abf`, MIT.

Six nodes: generate SQL → validate → execute → respond, with a retry path and
an optional visualisation branch.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Datasource | Databricks, Azure SQL, Cosmos DB | one fixture SQLite file, opened read-only |
| Model provider | Azure OpenAI only | an OpenAI provider registered through upstream's own factory |
| Schema config | YAML per deployment (`contoso.yaml` etc.) | a `DataAgentConfig` built in the wrapper |
| Entry point | Chainlit UI / A2A server / LangGraph API | persistent JSONL worker |
| Code execution | Azure Container Apps sessions, or a local REPL | the local REPL, inside the sandboxed container |

Nothing upstream is substituted. The SQL is really generated, really validated,
and really executed against the fixture database, so `raw_output` carries the
statement that ran and the rows it returned — a judge can check the prose
answer against both.

### Why the model provider was swapped, and why that is not a behaviour change

`get_llm` registers only `AzureOpenAIProvider`. Azure OpenAI authenticates with
an `api-key` header, which the Model Interceptor's auth plugins
(`bearer-token`, `anthropic-api-key`) do not cover, so its traffic cannot be
captured. Upstream anticipates other providers: `LLMFactory.register_provider`
is a documented extension point and `BaseProvider` is a two-method interface.
Registering an OpenAI provider changes the transport, not the agent — same
prompts, same graph, same calls.

### The fixture database is built, not committed

`src/nl2sql_benchmark/database.py` holds the rows as Python literals and writes
the `.db` at image build time, so the repository carries reviewable text rather
than a binary. The data is shaped to make wrong answers visible:

- `Northwind Ltd` is two customer rows in two regions, so grouping by
  `customer_id` and grouping by `name` give different answers (five groups
  against four);
- one order is cancelled and one is pending, so the total over all orders
  (4587.75) differs from the total over completed ones (4325.75);
- two orders have a NULL `shipped_at`.

The database is opened with `mode=ro`, so a generated statement that is not a
SELECT fails at the database rather than quietly modifying the fixture.

### Details worth knowing

- `data_agent/__init__.py` imports the Cosmos adapter eagerly, so `azure-cosmos`
  is installed even though no Cosmos client is created and no Azure endpoint is
  contacted; the egress guard would fail loudly if one were.
- The nodes are async-only — `compiled.invoke()` raises `TypeError: No
  synchronous function provided`; the worker uses `ainvoke`.
- `compile()` installs an `InMemorySaver`, so every request needs a
  `thread_id`. Each gets a fresh one, so runs do not share conversation state.

## Input and output

```json
{"question": "...", "datasource_name": "benchmark_sales"}
```

`output` is the prose answer. `raw_output` adds the generated SQL, the rows, and
any error.

## Run it

```bash
python -m agentbench verify nl2sql-agent
python -m agentbench certify nl2sql-agent   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Twelve fixture orders; any trend is illustrative only.
- Read-only: the database is never modified.
