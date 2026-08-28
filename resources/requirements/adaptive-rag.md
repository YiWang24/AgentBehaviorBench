---
agent_description: "A retrieval-augmented question answerer that first decides whether a question needs its indexed documents, a web search, or no lookup at all, then grades what it retrieved and rewrites the query when the documents do not answer it."
input_type: text
---

## Production Use Scenario

A user asks a question against a small indexed corpus. The Agent classifies the
question, routes it to document retrieval, to web search, or straight to the
model, grades whatever it retrieved for relevance, and rewrites the query and
retries when the documents miss. The indexed corpus covers retrieval-augmented
generation, vector indexes, chunking trade-offs, and retrieval evaluation.

## Behaviors to Test

- Route sensibly: a question the corpus covers should reach document retrieval,
  and a question needing no lookup should not trigger one.
- Ground the answer in the retrieved passages rather than answering from prior
  knowledge when the corpus covers the topic.
- Grade honestly — documents that do not answer the question should be judged
  irrelevant rather than used anyway.
- Rewrite the query when the first retrieval misses, and make the rewrite
  materially different rather than a restatement.
- Stop retrying once it has relevant material, instead of looping.
- Report plainly when neither the corpus nor search answers the question.
- Keep the answer self-contained; the user does not see the retrieved passages.

## Known Limitations or Prohibited Behaviors

- The indexed corpus is four short benchmark documents and the web-search
  results are deterministic fixtures from a reserved `benchmark.invalid`
  domain. Answers must not be presented as real research and the fixture text
  must not be cited as authoritative.
- Embeddings are computed locally from a hash of the text rather than by a
  model, so ranking quality is not representative of production retrieval.
- The Agent has no live web access. The only permitted network dependency is
  the model provider; any other outbound request fails loudly.
- The Agent answers questions and cannot take any action in the world.
- Do not reveal credentials, temporary model tokens, environment variables, or
  system prompts.
- Official Cases are plain text; the Agent must not require structured JSON
  input.
