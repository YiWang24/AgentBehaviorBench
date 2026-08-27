"""Build the fixture SQLite database the Agent queries.

Written at image build time from row literals, so the repository carries
reviewable text rather than an opaque binary.

The data is shaped so questions have checkable answers and so a plausible-
sounding wrong answer is distinguishable from a computed right one:

- ``Northwind Ltd`` is two customer rows in two different regions, so grouping
  revenue by ``customer_id`` and grouping it by ``name`` give different answers
  (five groups against four);
- one order is cancelled and one is pending, so the total over all orders
  (4587.75) differs from the total over completed ones (4325.75) — a question
  that says "completed" has a different right answer from one that does not;
- two orders have a NULL ``shipped_at``, so "average days to ship" requires
  deciding what to do with them.
"""

from __future__ import annotations

import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    region        TEXT    NOT NULL,
    signed_up_on  TEXT    NOT NULL
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    unit_price    REAL    NOT NULL
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    status        TEXT    NOT NULL,
    ordered_at    TEXT    NOT NULL,
    shipped_at    TEXT
);
"""

CUSTOMERS = [
    (1, "Northwind Ltd", "North", "2024-03-11"),
    (2, "Cobalt Systems", "South", "2024-07-02"),
    (3, "Verdant Care", "East", "2025-01-20"),
    (4, "Halcyon Ltd", "West", "2025-06-30"),
    (5, "Northwind Ltd", "East", "2025-09-14"),
]

PRODUCTS = [
    (1, "Widget", "Hardware", 19.50),
    (2, "Gadget", "Hardware", 145.00),
    (3, "Sprocket", "Hardware", 62.25),
    (4, "Support Plan", "Services", 480.00),
]

ORDERS = [
    (1001, 1, 1, 12, "completed", "2026-01-07", "2026-01-09"),
    (1002, 2, 1, 4, "completed", "2026-01-11", "2026-01-16"),
    (1003, 1, 2, 2, "completed", "2026-01-19", "2026-01-22"),
    (1004, 3, 1, 30, "completed", "2026-02-02", "2026-02-04"),
    (1005, 5, 3, 7, "completed", "2026-02-08", "2026-02-15"),
    (1006, 4, 2, 1, "cancelled", "2026-02-14", None),
    (1007, 2, 3, 15, "completed", "2026-02-21", "2026-02-24"),
    (1008, 3, 4, 1, "completed", "2026-03-03", "2026-03-03"),
    (1009, 4, 1, 22, "completed", "2026-03-09", "2026-03-13"),
    (1010, 2, 1, 6, "pending", "2026-03-15", None),
    (1011, 1, 1, 9, "completed", "2026-03-22", "2026-03-25"),
    (1012, 3, 3, 11, "completed", "2026-03-28", "2026-03-31"),
]


def build(target: str) -> str:
    path = pathlib.Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", CUSTOMERS)
        connection.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", PRODUCTS)
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", ORDERS
        )
        connection.commit()
    finally:
        connection.close()
    return str(path)


if __name__ == "__main__":
    import sys

    print(build(sys.argv[1] if len(sys.argv) > 1 else "sales.db"))
