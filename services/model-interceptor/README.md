# DefuzeX Model Interceptor

This standalone Linux container transparently intercepts model HTTP traffic for
one AgentBench Docker Agent. It owns netfilter and TLS termination; the Agent
container shares its network namespace but cannot access upstream credentials.

Matched OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages
requests retain their source protocol skin while the target plugin rewrites the
upstream URL, model, and authentication for OpenRouter. Streaming responses are
relayed immediately and traced without buffering the full response.

The service is configured only through the JSON file mounted at
`/run/secrets/interceptor_config`. It emits machine-readable trace events to
stdout with the `DEFUZEX_TRACE ` prefix.
