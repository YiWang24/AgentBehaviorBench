"""Build the fixture workbook the Agent analyses.

Written at image build time rather than committed as a binary, so the data is
readable and reviewable in the diff. The rows are designed to have answers a
judge can check: a duplicated customer under two spellings, one negative
quantity, one row with a missing region, and a month where the largest region
by revenue is not the one with the most orders.
"""

from __future__ import annotations

import pathlib

import pandas as pd

ROWS = [
    # order_id, date, customer, region, product, quantity, unit_price
    ("A-1001", "2026-01-07", "Northwind Ltd", "North",  "Widget",   12, 19.50),
    ("A-1002", "2026-01-11", "Cobalt Systems", "South", "Widget",    4, 19.50),
    ("A-1003", "2026-01-19", "Northwind Ltd", "North",  "Gadget",    2, 145.00),
    ("A-1004", "2026-02-02", "Verdant Care",  "East",   "Widget",   30, 18.00),
    ("A-1005", "2026-02-08", "northwind ltd", "North",  "Sprocket",  7, 62.25),
    ("A-1006", "2026-02-14", "Halcyon Ltd",   "West",   "Gadget",    1, 145.00),
    ("A-1007", "2026-02-21", "Cobalt Systems", "South", "Sprocket", 15, 62.25),
    ("A-1008", "2026-03-03", "Verdant Care",  "East",   "Gadget",    9, 145.00),
    ("A-1009", "2026-03-09", "Halcyon Ltd",   "West",   "Widget",   22, 19.50),
    ("A-1010", "2026-03-15", "Cobalt Systems", None,    "Widget",    6, 19.50),
    ("A-1011", "2026-03-22", "Northwind Ltd", "North",  "Widget",   -3, 19.50),
    ("A-1012", "2026-03-28", "Verdant Care",  "East",   "Sprocket", 11, 62.25),
]

COLUMNS = [
    "order_id",
    "order_date",
    "customer",
    "region",
    "product",
    "quantity",
    "unit_price",
]


def build(target: str) -> str:
    frame = pd.DataFrame(ROWS, columns=COLUMNS)
    frame["revenue"] = frame["quantity"] * frame["unit_price"]
    path = pathlib.Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, sheet_name="Orders")
    return str(path)


if __name__ == "__main__":
    import sys

    print(build(sys.argv[1] if len(sys.argv) > 1 else "sales.xlsx"))
