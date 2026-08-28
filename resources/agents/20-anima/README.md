# anima (AgentBench adaptation)

AgentBench adaptation of [Fullive-AI/Anima](https://github.com/Fullive-AI/Anima),
pinned at `ea1542f`, Apache-2.0.

Anima is an agent OS for smart-home hardware. The benchmark drives its chat
graph: a planner reads the devices and their sensor readings, and an executor
issues device commands.

## What was adapted

| Concern | Upstream | Here |
| --- | --- | --- |
| Devices | MQTT + Xiaomi MIoT discovery | upstream's own `VirtualAdapter`, six fixture devices |
| Entry point | FastAPI server + scheduler + discovery loop | persistent JSONL worker |
| Writable paths | `data/` beside the source | `/tmp/anima/data` (the image root is read-only) |
| Skills | `skills/` beside the source | copied to `/opt/agent/skills`, read-only |
| Model traffic | OpenAI via the `openai` SDK | unchanged; captured by the Model Interceptor |

### Almost nothing is mocked

Worth stating plainly, because it is unusual: no upstream behaviour is
substituted. `benchmark_mocks` installs the egress guard and nothing else. The
devices come from `adapters/virtual/`, which upstream ships for running without
hardware, and commands are dispatched through the real
`DiscoveryOrchestrator` to that adapter — so a command genuinely changes device
state, and "did the Agent turn the right thing on" is answerable from the run.

`raw_output` carries every device's state after the turn plus a `devices_changed`
diff, which is what makes the claim checkable against the report.

### The fixture home

Six devices across four rooms, with readings placed near the thresholds
`core/brain/engine.py` reasons about — living-room AQI 38 and 29.5 °C, bedroom
humidity 32% — and one lamp already on. A request like "it's stuffy in here"
therefore has a defensible answer and a wrong one, rather than every action
looking equally reasonable. Both the adapter's state map and the `Sensor`
objects on each `Device` are set, since the planner reads the latter.

### Dependencies

`core/runtime/__init__.py` imports the MQTT client eagerly, so `aiomqtt` is
installed even though no broker is ever contacted; the egress guard would fail
loudly if a connection were attempted. `fastapi`, `uvicorn`, `amqtt`,
`python-miio`, and `matplotlib` are not installed — the HTTP server is not the
entry point and there is no hardware.

`core/brain/prompts/planner_hints.md` is read relative to the installed module
and is declared as package data.

## Input and output

Plain text in; `output` is the Agent's reply. `raw_output` adds the full result
payload, the post-turn device states, and the diff.

## Run it

```bash
python -m agentbench verify anima
python -m agentbench certify anima   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- No physical hardware. Device state resets between runs.
- The Agent's prompts and several replies are in Chinese; it answers in the
  language it was asked in.
