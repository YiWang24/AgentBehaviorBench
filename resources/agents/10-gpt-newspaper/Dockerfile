# Upstream ships requirements.txt with no lock file; pin the interpreter instead.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/abb-runtime:/opt/agent/agent
WORKDIR /opt/agent/agent
COPY agent/requirements.txt ./requirements.txt
# Upstream is pinned at b86aff2d (2024-02-24) and bounds no dependency, so a free
# resolve installs langgraph 1.2 -- which no longer exports the `Graph` symbol
# backend/langgraph_agent.py imports. ABB is the other half of the constraint:
# agentbench/observe/langchain.py imports GraphBubbleUp from langgraph.errors,
# which older releases do not have. Measured across releases:
#   0.0.26 0.0.69 0.2.0  Graph yes, GraphBubbleUp no   -> Agent runs, ABB cannot observe
#   0.5.4  0.6.7  1.2.11 Graph no,  GraphBubbleUp yes  -> ABB observes, Agent cannot import
#   0.3.0 .. 0.4.10      both                          -> the only workable window
# 0.3.0 itself is yanked (missing langgraph-prebuilt), so take the newest good one.
# Constraining langgraph alone is enough; pip resolves langchain 0.3.x around it.
RUN printf 'langgraph==0.4.10\n' > /tmp/abb-constraints.txt \
    && python -m pip install --no-cache-dir -c /tmp/abb-constraints.txt -r requirements.txt \
    # langchain-community was split out of langchain after this snapshot was
    # written, so upstream never lists it although the code imports it.
    && python -m pip install --no-cache-dir -c /tmp/abb-constraints.txt langchain-community \
    && python -m pip install --no-cache-dir 'opentelemetry-sdk==1.44.0' \
    && python -c "from langgraph.graph import Graph; from langgraph.errors import GraphBubbleUp; from langchain_openai import ChatOpenAI; from tavily import TavilyClient; import langchain_community.adapters.openai" \
    && useradd --create-home --uid 10001 agent
COPY agent/ ./
WORKDIR /opt/agent
COPY .abb-runtime/ /opt/abb-runtime/
COPY bindings/ ./bindings/
COPY agent.toml ./agent.toml
USER agent
