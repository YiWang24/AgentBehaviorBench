"""Run GPT Newspaper's native MasterAgent graph and return the published article.

Two upstream assumptions do not hold inside ABB's evaluation container, and both are
handled here rather than by editing upstream:

* ``MasterAgent.__init__`` calls ``os.makedirs("outputs/run_<ts>")`` against the process
  working directory. That is handled by ``workdir`` in agent.toml, not here: the default
  /opt/agent is read-only, so the manifest points the working directory at a writable
  tmpfs. The private temporary directory below is kept for a different reason -- the
  tmpfs is capped at 64 MiB and shared by every Case in the container, so each invocation
  reclaims its own space on close rather than accumulating rendered newspapers.
* ``MasterAgent.run`` returns a filesystem path, not text. The Judge needs the article
  itself, so the binding reads the published file back and returns its content alongside
  the native return value.
"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock


def request_from_input(value):
    """Accept {queries: [...], layout: str} or plain text as a single query."""
    if isinstance(value, str):
        value = {'queries': [value]}
    if not isinstance(value, dict):
        raise ValueError('GPT Newspaper accepts text or a queries/layout object')
    unknown = set(value) - {'queries', 'layout', 'query'}
    if unknown:
        raise ValueError(f'Unsupported GPT Newspaper input fields: {sorted(unknown)}')
    queries = value.get('queries')
    if queries is None and isinstance(value.get('query'), str):
        queries = [value['query']]
    if not isinstance(queries, list) or not queries or not all(
            isinstance(item, str) and item.strip() for item in queries):
        raise ValueError('queries must be a non-empty list of non-empty strings')
    layout = value.get('layout', 'layout_1.html')
    if not isinstance(layout, str) or not layout.strip():
        raise ValueError('layout must be a non-empty string')
    return queries, layout


class NewspaperGraph:
    def __init__(self):
        self._directory = None
        self._closed = False
        self._lock = RLock()

    async def ainvoke(self, value, config=None, *, context=None):
        return await asyncio.to_thread(self._run, value)

    def invoke(self, value, config=None, *, context=None):
        return self._run(value)

    def _run(self, value):
        queries, layout = request_from_input(value)
        with self._lock:
            if self._closed:
                raise RuntimeError('GPT Newspaper is closed')
            if self._directory is None:
                self._directory = TemporaryDirectory(prefix='abb-newspaper-')
            workspace = Path(self._directory.name)

        from backend.langgraph_agent import MasterAgent

        previous = Path.cwd()
        os.chdir(workspace)
        try:
            # MasterAgent creates outputs/run_<ts>/ relative to the working directory.
            published = MasterAgent().run(queries, layout)
            path = Path(published)
            if not path.is_absolute():
                path = workspace / path
            article = path.read_text(encoding='utf-8') if path.is_file() else ''
        finally:
            os.chdir(previous)
        if not article.strip():
            raise RuntimeError('GPT Newspaper produced no published article')
        return {'article': article, 'published_path': str(published), 'queries': queries}

    def close(self):
        with self._lock:
            self._closed = True
            directory, self._directory = self._directory, None
            if directory is not None:
                directory.cleanup()


def create_graph():
    return NewspaperGraph()
