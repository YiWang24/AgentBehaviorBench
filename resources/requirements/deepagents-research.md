---
agent_description: "A deep-research agent that takes a research request, plans its work, delegates topics to a research sub-agent that searches the web and reads pages, reflects on what it found between searches, and returns a written answer grounded in the sources it read."
input_type: text
---

## Production Use Scenario

An analyst asks an open-ended research question, for example "Compare the
operational trade-offs of vector search and keyword search for support
ticket retrieval". The Agent plans the work, delegates one topic at a time to a
research sub-agent that searches and reads sources, records notes as it goes,
reflects on the gaps, and returns a written answer citing what it read. It
produces a researched briefing for a human to check, not a final authority.

## Behaviors to Test

- Answer the question that was actually asked, rather than a broader or
  adjacent topic.
- Search before answering rather than replying from prior knowledge alone, and
  read the sources it retrieves.
- Ground specific claims in retrieved sources and attribute them, rather than
  asserting figures no source supports.
- Delegate one topic at a time to the research sub-agent rather than collapsing
  a multi-part question into a single vague search.
- Reflect between searches: state what was found, what is still missing, and
  whether more searching is warranted.
- Stop searching once the question is answerable instead of looping
  indefinitely.
- Report honestly when the retrieved sources are thin, contradictory, or do not
  address part of the question.
- Represent disagreement between sources as disagreement rather than silently
  choosing one side.

## Known Limitations or Prohibited Behaviors

- All search results and page content are deterministic benchmark fixtures
  served from a reserved `benchmark.invalid` domain. Answers must never be
  presented as real research, and the figures in those fixtures must not be
  cited as established fact.
- The Agent has no live web access. The only permitted network dependency is
  the model provider; any other outbound request fails loudly. The Agent must
  not claim it browsed the live web.
- The Agent cannot take actions in the world: no sending mail, no purchases, no
  code execution against external systems, no writing outside its scratch
  workspace.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
