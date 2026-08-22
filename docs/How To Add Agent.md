# How to Add an Agent

This page explains how to add your own Agent to DefuzeX AgentBench for testing.
The goal is to package the Agent in a form that AgentBench can discover, start,
invoke, record, and submit to the DefuzeX Judge.

## Choose the Right Architecture Path

AgentBench is designed to support multiple Agent architectures. Before copying
files or editing the Registry, first identify how your Agent is built and choose
the closest adaptation path.

Current architecture paths:

- [AgentFactory Flow](./Agents/Factory.md): use this when you have a downloaded
  Agent project and need to convert it into a deterministic AgentBench candidate.
- [Runtime Contract](./Agents/Runtime.md): use this when Docker, package data,
  JSONL worker behavior, Model Interceptor routing, or filesystem rules are involved.
- [Certification](./Agents/Certify.md): use this when you need to understand
  `certify`, `ready`, result artifacts, or Judge failure semantics.
- [Troubleshooting](./Agents/Troubleshooting.md): use this when you already have
  a concrete error message.
- [Full Reference](./Agents/Reference.md): use this when you need the complete
  onboarding reference.

Future framework-specific paths should be added here as new Agent architectures
are supported.

## Add the Agent

After choosing the right architecture path, start from
[AgentFactory Flow](./Agents/Factory.md). AgentFactory should work on a copied
Agent project, not the original source checkout. Keep the adaptation small: an
existing model client should normally keep its SDK, public URL, request format,
and source model configuration.

Use this flow:

1. Copy the original Agent project to a separate working directory.
2. Identify its launch command, input/output contract, and actual model request
   host, path, protocol, and credential environment variable.
3. Add a non-root Docker image and a persistent JSONL worker. Wrap the existing
   Agent instead of rewriting its workflow.
4. Copy the adapted Agent into `resources/agents/<order>-<agent-id>/`.
5. Add `agent.toml`, declaring the native model traffic under
   `[llm_interception]` when the Agent calls a model.
6. Add `resources/requirements/<agent-id>.md`.
7. Add an entry in `resources/registry.toml` with `enabled = true` and
   `status = "adapting"`.
8. Run the focused tests for Registry discovery, Docker configuration,
   interception routes, and the worker.

Do not change model code merely to point it at OpenRouter. The Agent should keep
calling its original provider URL with the temporary token injected into the
environment variable it already expects. AgentBench captures the matching
request, replaces the credential and run-selected model in the trusted
Interceptor, forwards it to OpenRouter, and returns the response to the Agent.

Modify the Agent's model integration only when its existing behavior cannot meet
that contract, for example when it embeds a credential in source code, uses an
unsupported wire protocol, pins TLS certificates, cannot trust the runtime CA,
or does not provide any way to receive a temporary credential.

## Certify the Agent

After the Agent has been added, run certification to check whether it can enter
the benchmark:

```powershell
python -m agentbench certify <agent-id>
```

`certify` runs the full DefuzeX benchmark flow for that Agent. It promotes the
Agent from `adapting` to `ready` only when every requested Case completes without
invocation or runtime errors.

A Judge failure means the Agent ran but performed poorly on the benchmark. It
does not necessarily mean the adapter is broken. Startup failures, invocation
errors, invalid worker output, or Registry errors usually mean the Agent
adaptation still needs work.

After certification succeeds, the Agent can be included in normal benchmark
runs:

```powershell
python -m agentbench run
```

To save the result and inspect it in the local viewer, add an output path:

```powershell
python -m agentbench run --output results\result.json
```

## Definition of Done

An Agent is onboarded when:

- The Agent is registered in `resources/registry.toml`.
- Docker starts it under the AgentBench runtime policy when a Docker runtime is
  required.
- The worker accepts SDK Inputs and returns serializable `output` and
  `raw_output`.
- Model-backed Agents declare their native request route and the Interceptor
  captures a complete request/response pair without requiring a provider rewrite
  in Agent source.
- Static fixtures and config files exist in the installed runtime image or
  package.
- Runtime writes go to allowed paths.
- `python -m agentbench certify <agent-id>` exits `0` and writes JSONL evidence.
- The Registry status for that Agent is `ready`.
