# Clinical Decision Pipeline (AgentBench adaptation)

AgentBench adaptation of [bcefghj/medical-multi-agent-system](https://github.com/bcefghj/medical-multi-agent-system),
pinned at `09936ed696d8f5b1bd6a1cc0c1c9caf05d50f002`, MIT.

Upstream is a five-stage clinical decision pipeline: intake structures a patient
presentation, diagnosis forms a differential and can loop back to intake for
more detail, then treatment, ICD-10 coding, and an audit record.

The repository ships Python, Go, and Java implementations; the benchmark selects
the Python one, which is the LangGraph implementation.

## Gate status

> **This adapter has not passed `agentbench verify`.** The pipeline builds and
> all five nodes run, but the intake/diagnosis loop does not terminate under a
> canned model reply. See [Offline gate limitation](#offline-gate-limitation).
> The registry entry is `status = "adapting"`.

## What was adapted

Very little needed replacing. Most of this agent's reference data already ships
as Python literals.

| Concern | Upstream | Here |
| --- | --- | --- |
| Drug interactions | `DDI_DATABASE`, a module-level list | unchanged, no external service |
| ICD-10 index | `ICD10_DATABASE`, a module-level dict | unchanged |
| GraphRAG | Neo4j when `use_neo4j=True` | unchanged; the default in-memory backend is used |
| FHIR push | `httpx` POST to a FHIR server | deterministic acknowledgement |
| Patient record | fetched | one synthetic fixture record |
| Entry point | FastAPI service | persistent JSONL worker |

`httpx` is the model SDK's transport, so it cannot be blocked wholesale. The
single outbound call — `push_to_fhir_server` — is replaced directly instead, and
the other functions in that module, which are pure resource builders, are left
alone.

The Neo4j, Postgres, and Redis settings are cleared at startup so a host that
happens to export them cannot pull the agent onto a real service.

### Patient data

The record served to the pipeline is a single synthetic fixture. It is not real
and not derived from a real person, and no protected health information is
involved. Nothing is written to a real record system.

## Input and output

The official Case provider emits text and the pipeline's native input is a
patient presentation, so the mapping is close to the identity.

```json
{"presentation": "...", "diagnosis": ..., "treatment": ..., "codes": ...}
```

`raw_output` adds the audit record, whether the agent asked for more
information, and the mock trace.

## Offline gate limitation

`diagnosis_agent` asks for JSON in its prompt and parses the reply itself. On a
parse failure it takes its error path, which sets `needs_more_info: True`
(`diagnosis_agent.py:69`), and `_route_after_diagnosis` sends the run back to
intake. There is no iteration cap on that loop upstream, so a model that never
returns parseable JSON loops until the recursion limit.

The offline mock *does* answer a prompt that states its contract as a literal
JSON example, and `diagnosis_agent`, `treatment_agent`, and `coding_agent` are
all answered correctly that way. `intake_agent` is the exception: it writes its
example with type placeholders — `"age": <integer>`, `<int or null>`,
`true/false` — which is not parseable JSON, so there is nothing to echo. Intake
is also the node the loop returns to, so the run never leaves it. Fifteen model
calls happen before the recursion limit is reached.

This is not repairable from the benchmark side without editing the agent's
parsing or its routing. It is unblocked by `agentbench certify
clinical-pipeline` against a real model, which returns the JSON the prompt asks
for.

## Known limitations

- **This Agent does not provide medical advice.** Output is a draft for a
  qualified clinician and must never be shown to a patient as diagnosis or
  prescription.
- The drug-interaction table and ICD-10 index are small fixtures, not clinical
  references.
- Non-LLM egress raises `BenchmarkNetworkBlocked` rather than degrading.
