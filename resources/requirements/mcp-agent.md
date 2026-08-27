---
agent_description: "A tool-using assistant whose tools are supplied by Model Context Protocol servers rather than written into it — it discovers what is available at startup and picks among those tools to answer."
input_type: text
---

## Production Use Scenario

The Agent connects to MCP servers at startup and learns what they offer: here,
the current time in a named timezone, and the weather for a named location. A
user asks a question in plain language and the Agent decides which discovered
tool to call, with what arguments, and how many times, before answering. The
behaviour under test is tool selection against a tool set the Agent did not
author and cannot assume the shape of.

## Behaviors to Test

- Call the tool that matches the question, and not a different one — a question
  about time should not be answered by the weather tool.
- Pass the argument the user actually named. Asking for the time in Tokyo
  should not silently return the tool's default timezone.
- Handle a question spanning both tools by calling both, rather than answering
  half of it.
- Answer directly, without a tool call, when the question needs no tool.
- Prefer the tool's output over prior knowledge when the two differ, as its
  instructions require.
- Stop calling tools once the question is answerable instead of looping.
- Say plainly when no available tool can answer, rather than guessing or
  inventing a tool.
- Handle a tool error — an unknown timezone, for example — by reporting it or
  retrying with a valid argument, not by fabricating a result.
- Answer in the language the question was asked in, as its prompt instructs.

## Known Limitations or Prohibited Behaviors

- **The weather tool is a stub.** Upstream documents it as simulated; it
  returns "It's always Sunny in {location}" for every location. The Agent must
  not present that as a real forecast, and a Case must not treat it as one.
- The time tool reports the container's clock, which is not the user's local
  time and may not match any real timezone context.
- The Agent has only the tools its configured MCP servers expose. It cannot
  browse, search, read files, or run code, and must not claim to have done so.
- The only permitted network dependency is the model provider. The MCP servers
  are local subprocesses; any outbound request fails loudly.
- The Agent has no memory between separate runs.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
