FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

# config.yaml is found relative to the working directory.
COPY config.yaml ./config.yaml

# Build the fixture workbook from the committed row data, so the repository
# carries reviewable text rather than an opaque .xlsx blob.
RUN python -m excel_benchmark.make_workbook /opt/agent/data/sales.xlsx \
 && chmod -R a+r /opt/agent/data

USER 10001
