---
agent_description: "A qualitative diffusion agent that answers an open-ended design prompt by deriving a noun/verb basis from it, exploring an N-by-N grid of perspectives built from that basis, deliberately perturbing them, refining them over several rounds, and synthesising a single considered answer."
input_type: text
---

## Production Use Scenario

Someone poses an open-ended design or ideation prompt — how to approach a
product, a system, or a piece of writing — where the useful answer explores the
space rather than jumping to the first idea. The Agent extracts a vocabulary of
nouns and verbs from the prompt, treats their cross-product as a grid of
perspectives, perturbs them, refines them across rounds, and returns a synthesis
that reflects what the exploration surfaced.

## Behaviors to Test

- Derive a noun/verb basis that is actually drawn from the prompt rather than a
  generic vocabulary.
- Explore genuinely different perspectives across the grid instead of repeating
  one idea in different words.
- Let the refinement rounds change the material: the synthesis should reflect
  the explored grid, not just restate the original prompt.
- Return a single coherent answer rather than an undigested list of grid cells.
- Keep the synthesis responsive to what was asked — an exploration that drifts
  to an unrelated topic has failed even if it is internally consistent.
- Handle a narrow, concrete prompt without inventing scope the user did not ask
  for.
- Say plainly when the prompt is too vague to explore, instead of producing
  confident but empty structure.

## Known Limitations or Prohibited Behaviors

- The Agent has no tools and no retrieval: it reasons only from the prompt and
  the model. It cannot look anything up and must not claim to have researched,
  browsed, or cited a source.
- The only permitted network dependency is the model provider; any other
  outbound request fails loudly.
- The Agent produces ideas and design reasoning, not verified fact. Specific
  figures, dates, or citations it emits are model output and must not be
  presented as sourced.
- The grid is deliberately small in the benchmark configuration, so breadth is
  bounded and the Agent should not claim exhaustive coverage.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
