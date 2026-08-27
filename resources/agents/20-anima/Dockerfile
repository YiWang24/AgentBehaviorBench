FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

# The skills are markdown read from a directory at runtime, not package data.
# They are copied to a fixed read-only path that ANIMA_SKILLS_DIR points at.
COPY src/skills /opt/agent/skills

USER 10001
