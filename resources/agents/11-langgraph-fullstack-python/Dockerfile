FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/abb-runtime:/opt/agent/agent:/opt/agent/agent/src
WORKDIR /opt/agent/agent
COPY agent/ ./
RUN python -m pip install --no-cache-dir . \
    && python -m pip install --no-cache-dir 'opentelemetry-sdk==1.44.0' \
    && useradd --create-home --uid 10001 agent
COPY agent/ ./
WORKDIR /opt/agent
COPY .abb-runtime/ /opt/abb-runtime/
COPY bindings/ ./bindings/
COPY agent.toml ./agent.toml
USER agent
