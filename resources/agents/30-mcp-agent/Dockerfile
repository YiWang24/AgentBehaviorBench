FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

# The MCP servers are launched as stdio subprocesses from these paths, named in
# config.json. They stay on the read-only root; nothing writes to them.
COPY mcp_servers ./mcp_servers
COPY config.json ./config.json

USER 10001
