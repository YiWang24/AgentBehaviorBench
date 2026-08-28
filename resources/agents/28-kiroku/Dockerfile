FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    NLTK_DATA=/opt/agent/nltk_data

WORKDIR /opt/agent
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

# gen_citations uses nltk.sent_tokenize, which downloads the punkt tokenizer on
# first use. The container has no egress at run time, so it is cached now.
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt punkt_tab \
 && chmod -R a+rX "$NLTK_DATA"

USER 10001
