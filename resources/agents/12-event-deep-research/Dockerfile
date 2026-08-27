FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVENT_RESEARCH_STATE_ROOT=/tmp/event-research \
    TIKTOKEN_CACHE_DIR=/opt/agent/tiktoken-cache

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

# The chunker counts tokens with tiktoken, which downloads its BPE table on
# first use. The benchmark runtime has no egress, so fetch it at build time.
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "import tiktoken; [tiktoken.get_encoding(n) for n in ('o200k_base', 'cl100k_base')]" \
    && chmod -R a+rX "$TIKTOKEN_CACHE_DIR"

USER agent
