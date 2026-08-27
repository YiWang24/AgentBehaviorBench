FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRADING_AGENTS_STATE_ROOT=/tmp/trading-agents \
    TRADINGAGENTS_RESULTS_DIR=/tmp/trading-agents/results \
    TRADINGAGENTS_CACHE_DIR=/tmp/trading-agents/cache \
    TRADINGAGENTS_MEMORY_LOG_PATH=/tmp/trading-agents/memory/trading_memory.md

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

USER agent
