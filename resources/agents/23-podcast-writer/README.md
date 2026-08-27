# podcast-writer (AgentBench adaptation)

AgentBench adaptation of [artnoage/Podcast](https://github.com/artnoage/Podcast),
pinned at `9d0f3c4`, Apache-2.0.

Three nodes in sequence: summariser → scriptwriter → enhancer. A source
document goes in, a spoken-word script comes out.

## What was adapted

Very little, which is worth stating: the three nodes reason over the text they
are handed and reach nothing but the model — no search, no retrieval, no
filesystem. `benchmark_mocks` therefore substitutes nothing and installs only
the egress guard, so a future revision that reaches for the network fails
loudly rather than silently.

| Concern | Upstream | Here |
| --- | --- | --- |
| External services | none on this graph | none |
| Provider | OpenRouter by default | the `OpenAI` branch upstream already has |
| Entry point | FastAPI app / simulation scripts | persistent JSONL worker |

The wider project also contains a feedback loop, a prompt-optimisation routine
with weight clipping, and an evaluator. The benchmark selects the creation
workflow, which is the graph.

### Prompts ship as a `prompts` package

`load_prompt()` resolves `prompts/<name>.txt` relative to two directories above
its own module, which after installation is the site-packages root. Shipping
the text files inside a `prompts` package puts them exactly there, so upstream's
path arithmetic works unchanged rather than being edited.

### Licence

Upstream ships `LICENSE.txt` (Apache-2.0) rather than `LICENSE`; it is vendored
here as `LICENSE`.

## Input and output

Plain text in — the source document. `output` is the enhanced script;
`raw_output` also carries the key points and the script essence, so a judge can
check what survived each rewrite and what was introduced along the way.

## Run it

```bash
python -m agentbench verify podcast-writer
python -m agentbench certify podcast-writer   # needs DEFUZEX_API_KEY + OPENROUTER_API_KEY
```

## Known limitations

- No retrieval: everything in the script must come from the source text.
- Text only; no audio is produced.
