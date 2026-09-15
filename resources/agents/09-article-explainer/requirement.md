# Article Explainer requirements

- Supply model-interception credentials for the declared OpenAI Chat Completions
  route. Importing `explainer.graph` constructs the native specialists with the
  upstream `openai:gpt-4.1-mini` model, so the temporary `OPENAI_API_KEY` must be
  present before the first invocation. Ollama fallback is deliberately not used.
- Put the complete relevant article excerpt and the current question in every
  Input. The headless graph has no PDF loader, URL fetcher, retrieval tool, or
  persistent document state. It is compiled with a checkpointer, so earlier
  Inputs of the same Case remain in the conversation, but no source passage is
  carried for you: do not encode a path/attachment or assume an excerpt that was
  never supplied.
- Preserve the returned native `SwarmState` and framework callbacks. Handoff
  tool calls are internal coordination, not external actions. The deployment has
  no web, filesystem, code-execution, publication, or account-changing tool.
- Before promotion from `adapting`, build the frozen Python 3.13 image, run a
  real `observe`, inspect the final assistant content plus native handoff/model
  traces, and complete official certification. Include a Case where specialists
  hand off while staying grounded in the supplied excerpt.

Onboarding did not use a provider key, call a model, load a PDF, generate Cases,
request a Judge report, or run a benchmark.
