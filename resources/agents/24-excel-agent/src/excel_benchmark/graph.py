"""Expose the Excel agent with a workbook already loaded.

Upstream loads a spreadsheet through its HTTP upload endpoint; the benchmark
loads the fixture workbook at startup so every Case starts from the same
known data.
"""

from __future__ import annotations

import os

import benchmark_mocks

_compiled = None


def workbook_path() -> str:
    return os.environ.get("EXCEL_WORKBOOK", "/opt/agent/data/sales.xlsx")


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        from excel_agent.excel_loader import get_loader
        from excel_agent.graph import get_graph

        # get_loader() returns the multi-table loader; add_table registers
        # the workbook and makes it the active table.
        get_loader().add_table(workbook_path())
        _compiled = get_graph()
    return _compiled


def summary() -> str:
    from excel_agent.excel_loader import get_loader

    loader = get_loader()
    return loader.get_summary() if loader.is_loaded else "no workbook loaded"
