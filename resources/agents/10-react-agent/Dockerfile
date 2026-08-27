FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REACT_AGENT_STATE_ROOT=/tmp/react-agent

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

USER agent
