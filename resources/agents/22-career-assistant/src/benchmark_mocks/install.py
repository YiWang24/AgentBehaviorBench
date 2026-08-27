"""Replace the three modules `tools.py` reaches outside the model.

`tools.py` builds every tool at import time on top of `search` (LinkedIn),
`utils` (Serper and FireCrawl), and `data_loader` (resume PDF in, cover-letter
DOCX out). None of those can run here: three of them need API keys and egress,
and the fourth writes into a read-only image. Replacements are registered in
``sys.modules`` before `agents` imports `tools`, so the tool names, signatures
and return shapes the model sees are unchanged.

The resume is a fixture. It is deliberately specific — named skills, dated
roles, a visible gap — so a Case can tell an answer grounded in the document
from a generic one.
"""

from __future__ import annotations

import os
import pathlib
import sys
import types

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


def _search_module() -> types.ModuleType:
    """Stands in for the LinkedIn job search."""

    def get_job_ids(*args, **kwargs):
        return [job["job_id"] for job in fixtures.JOBS]

    async def fetch_all_jobs(job_ids, *args, **kwargs):
        wanted = set(job_ids or [])
        return [job for job in fixtures.JOBS if job["job_id"] in wanted]

    module = types.ModuleType("search")
    module.get_job_ids = get_job_ids
    module.fetch_all_jobs = fetch_all_jobs
    return module


def _utils_module() -> types.ModuleType:
    """Stands in for Serper web search and FireCrawl page scraping."""

    class SerperClient:
        def __init__(self, serper_api_key: str | None = None) -> None:
            self.serper_api_key = serper_api_key

        def search(self, query: str, num_results: int = 5) -> dict:
            # Upstream reads response["items"]; keep that key.
            return {"items": fixtures.search_items(query)[:num_results]}

    class FireCrawlClient:
        def __init__(self, firecrawl_api_key: str | None = None) -> None:
            self.firecrawl_api_key = firecrawl_api_key

        def scrape(self, url: str) -> str:
            return fixtures.page_markdown(url)

    module = types.ModuleType("utils")
    module.SerperClient = SerperClient
    module.FireCrawlClient = FireCrawlClient
    return module


def _data_loader_module() -> types.ModuleType:
    """Stands in for the PDF resume reader and the DOCX writer."""

    def load_resume(file_path: str) -> str:
        return fixtures.RESUME

    def write_cover_letter_to_doc(text: str, filename: str = "temp/cover_letter.docx") -> str:
        # The image root is read-only; the only writable path is the tmpfs.
        # The file really is written, so a claimed download link corresponds to
        # something that exists.
        root = pathlib.Path(os.environ.get("CAREER_WORKSPACE", "/tmp/career"))
        target = root / pathlib.Path(filename).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(text), encoding="utf-8")
        return str(target)

    module = types.ModuleType("data_loader")
    module.load_resume = load_resume
    module.write_cover_letter_to_doc = write_cover_letter_to_doc
    return module


def install() -> None:
    global _installed
    if _installed:
        return
    if "tools" in sys.modules or "agents" in sys.modules:
        raise RuntimeError(
            "benchmark_mocks.install() ran after tools was imported; the real "
            "LinkedIn, Serper and FireCrawl clients are already bound."
        )
    for name, module in (
        ("search", _search_module()),
        ("utils", _utils_module()),
        ("data_loader", _data_loader_module()),
    ):
        sys.modules[name] = module
    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
