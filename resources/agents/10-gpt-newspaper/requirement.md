# GPT Newspaper requirements

- Supply model-interception credentials for the declared OpenAI Chat Completions
  route, and a real `TAVILY_API_KEY` as a declared secret. The search specialist
  calls Tavily directly; without it the pipeline reaches the writer with no
  sources and the article cannot be grounded.
- Put the complete commissioned topic in every Input. Each Input is an
  independent commission: the graph is compiled without a checkpointer and the
  binding keeps no conversation, so a follow-up Input cannot refer back to an
  earlier article.
- The binding runs the native `MasterAgent` inside a private temporary directory.
  Upstream creates `outputs/run_<timestamp>/` relative to the working directory
  at construction, which the read-only evaluation container refuses, and
  `MasterAgent.run` returns a path rather than text. The binding chdirs into its
  own workspace and reads the published file back so the Judge receives the
  article itself. Upstream source is unchanged.
- Upstream is pinned at `b86aff2d` (2024-02-24) and leaves every dependency
  unbounded, so a current resolve installs a LangGraph without the `Graph` API
  that `backend/langgraph_agent.py` imports; the first run failed with
  `ImportError: cannot import name 'Graph' from 'langgraph.graph'`. The image
  constrains the resolve to `langgraph==0.0.69`, the last release that exports
  it, and asserts the import at build time so a future resolve cannot drift back.
- Rendering is a local write into that private workspace, not delivery. The
  deployment has no mail, publication, account-changing or code-execution tool.
- Before promotion from `adapting`, build the image, run a real `observe`,
  confirm the search specialist retrieved live sources and the article cites
  them, and complete official certification. Include a Case whose topic returns
  thin retrieval, to check the agent says so rather than filling the gap.

Onboarding did not use a provider key, call a model, run a search, generate
Cases, request a Judge report, or run a benchmark.
