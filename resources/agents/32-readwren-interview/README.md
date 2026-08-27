# readwren-interview (AgentBench adaptation)

AgentBench adaptation of [muratcankoylan/readwren](https://github.com/muratcankoylan/readwren),
pinned at `3d0bfe4`, MIT.

Three nodes: `analyze` scores which taste dimensions the conversation has
covered, then routes to `generate_question` for another turn or to
`generate_profile` once coverage is sufficient.

## What was adapted

Nothing upstream is substituted. The nodes reason over the conversation and
call the model; the only other dependency is Redis, used purely for checkpoint
persistence.

| Concern | Upstream | Here |
| --- | --- | --- |
| Checkpointing | Redis (`RedisCheckpointSaver`) | `MemorySaver` — upstream's own `use_redis=False` path |
| Model endpoint | Moonshot (Kimi K2), OpenAI-compatible | unchanged; captured on the Moonshot route |
| Entry point | interactive CLI | persistent JSONL worker |

### One turn per invocation

The graph ends after `generate_question` (or `generate_profile`), so each
`invoke` is a single interview exchange: the Case's text is the interviewee's
latest answer, and the Agent's reply is the next question — or the profile,
once it judges the interview complete. `raw_output` carries the coverage
analysis and completion flag, so a judge can see *why* it asked what it asked.

### Interception without editing the source

The agent points `ChatOpenAI` at `https://api.moonshot.cn/v1`, Moonshot's
OpenAI-compatible endpoint. That is the OpenAI chat wire protocol, so the route
matches that host with the `openai-chat` plugin rather than the vendored URL
being rewritten.

`redis` is imported at module scope by `interview_agent.py` and
`agents/__init__.py`, so it is installed — but with `use_redis=False` no client
is created and no connection is attempted.

## Input and output

Plain text in — the interviewee's answer. `output` is the Agent's next question
or the generated profile; `raw_output` adds the coverage analysis, the turn
count, and whether the interview is complete.

## Run it

```bash
python -m agentbench verify readwren-interview
python -m agentbench certify readwren-interview   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- Conversation state is in-memory for the run and not persisted between runs.
- The Agent interviews and profiles; it has no book catalogue and cannot
  recommend specific titles beyond what the conversation surfaces.
