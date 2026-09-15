# Upstream ships requirements.txt with no lock file; pin the interpreter instead.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/abb-runtime:/opt/agent/agent
WORKDIR /opt/agent/agent
COPY agent/requirements.txt ./requirements.txt
# Upstream is pinned at b86aff2d (2024-02-24) but leaves every dependency
# unbounded, so a current resolve installs a LangGraph that dropped the
# `Graph` API backend/langgraph_agent.py imports. Constrain the resolve to the
# last release that still exports it, without editing upstream's requirements.
RUN printf 'langgraph==0.0.69\n' > /tmp/abb-constraints.txt \
    && python -m pip install --no-cache-dir -c /tmp/abb-constraints.txt -r requirements.txt \
    && python -m pip install --no-cache-dir 'opentelemetry-sdk==1.44.0' \
    && python -c "from langgraph.graph import Graph" \
    && useradd --create-home --uid 10001 agent
COPY agent/ ./
WORKDIR /opt/agent
COPY .abb-runtime/ /opt/abb-runtime/
COPY bindings/ ./bindings/
COPY agent.toml ./agent.toml
USER agent
