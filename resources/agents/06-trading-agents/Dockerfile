FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANGCHAIN_TRACING_V2=false \
    TRADINGAGENTS_LLM_PROVIDER=openai \
    TRADINGAGENTS_CHECKPOINT_ENABLED=false \
    TRADINGAGENTS_RESULTS_DIR=/tmp/tradingagents/logs \
    TRADINGAGENTS_CACHE_DIR=/tmp/tradingagents/cache \
    TRADINGAGENTS_MEMORY_LOG_PATH=/tmp/tradingagents/memory/trading_memory.md

WORKDIR /opt/agent
COPY pyproject.toml README.md LICENSE ./
COPY benchmark_mocks ./benchmark_mocks
COPY src ./src
COPY langgraph.json ./

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

USER agent
