FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

# Build the fixture database from the committed row data, so the repository
# carries reviewable text rather than an opaque .db blob.
RUN python -m nl2sql_benchmark.database /opt/agent/data/sales.db \
 && chmod -R a+r /opt/agent/data

USER 10001
