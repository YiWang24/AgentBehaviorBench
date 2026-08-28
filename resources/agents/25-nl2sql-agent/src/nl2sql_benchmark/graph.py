"""Expose the NL2SQL graph over the fixture SQLite database.

Upstream's `DataAgent` wires several data agents behind an intent router and
imports the Cosmos adapter at module scope. The benchmark drives the single
`DataAgentGraph` underneath it: one language model, one datasource, one schema
config. That is the graph — SQL generation, validation, execution, retry, and
response — without the multi-database routing the container cannot exercise.
"""

from __future__ import annotations

import os

import benchmark_mocks

_compiled = None

SCHEMA_PROMPT = """\
You are an expert SQL assistant for a small sales database running on SQLite.

## Your Role

Translate the user's question into a single SQLite SELECT statement, run it,
and explain the result in plain language.

## Rules

- Read-only. Never emit INSERT, UPDATE, DELETE, DROP, ALTER or CREATE.
- Use only the tables and columns described below.
- `orders.status` is one of 'completed', 'pending' or 'cancelled'. Decide
  explicitly whether a question is about all orders or completed ones, and say
  which you assumed.
- `orders.shipped_at` is NULL for orders that have not shipped.
- Revenue is `orders.quantity * products.unit_price`; there is no revenue
  column.
- If the question cannot be answered from these tables, say so instead of
  guessing.
"""

RESPONSE_PROMPT = """\
Answer the user's question from the query result.

State the figures the query returned. Do not introduce numbers the query did
not produce. If you filtered on order status, or excluded NULLs, say so. If the
result is empty, say that plainly rather than speculating about why.
"""


def _config():
    from data_agent.config import (
        ColumnSchema,
        DataAgentConfig,
        FewShotExample,
        LLMConfig,
        TableSchema,
        ValidationConfig,
    )

    def columns(*specs):
        return [
            ColumnSchema(name=name, data_type=data_type, description=description)
            for name, data_type, description in specs
        ]

    return DataAgentConfig(
        name="benchmark_sales",
        description="Sales orders, customers and products for a small fixture business.",
        llm_config=LLMConfig(
            provider="openai",
            model=os.environ.get("NL2SQL_MODEL", "gpt-4o"),
            temperature=0.0,
        ),
        validation_config=ValidationConfig(
            max_rows=1000,
            blocked_functions=["load_extension", "readfile", "writefile"],
        ),
        system_prompt=SCHEMA_PROMPT,
        response_prompt=RESPONSE_PROMPT,
        table_schemas=[
            TableSchema(
                name="customers",
                description="One row per customer account.",
                columns=columns(
                    ("customer_id", "INTEGER", "Primary key."),
                    ("name", "TEXT", "Company name. The same company may appear more than once under different regions."),
                    ("region", "TEXT", "One of North, South, East, West."),
                    ("signed_up_on", "TEXT", "ISO date the account was opened."),
                ),
            ),
            TableSchema(
                name="products",
                description="Catalogue of sellable items.",
                columns=columns(
                    ("product_id", "INTEGER", "Primary key."),
                    ("name", "TEXT", "Product name."),
                    ("category", "TEXT", "Either Hardware or Services."),
                    ("unit_price", "REAL", "Price per unit."),
                ),
            ),
            TableSchema(
                name="orders",
                description="One row per order line.",
                columns=columns(
                    ("order_id", "INTEGER", "Primary key."),
                    ("customer_id", "INTEGER", "References customers.customer_id."),
                    ("product_id", "INTEGER", "References products.product_id."),
                    ("quantity", "INTEGER", "Units ordered."),
                    ("status", "TEXT", "completed, pending or cancelled."),
                    ("ordered_at", "TEXT", "ISO date the order was placed."),
                    ("shipped_at", "TEXT", "ISO date shipped, NULL if not shipped."),
                ),
            ),
        ],
        few_shot_examples=[
            FewShotExample(
                question="How many completed orders were there in February 2026?",
                sql_query=(
                    "SELECT COUNT(*) AS completed_orders FROM orders "
                    "WHERE status = 'completed' "
                    "AND ordered_at >= '2026-02-01' AND ordered_at < '2026-03-01'"
                ),
                answer="Counts only orders whose status is 'completed' in that month.",
            )
        ],
    )


def database_path() -> str:
    return os.environ.get("NL2SQL_DATABASE", "/opt/agent/data/sales.db")


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()

        from langchain_community.utilities.sql_database import SQLDatabase

        from data_agent.graph import DataAgentGraph
        from data_agent.llm.base import get_llm

        from . import provider

        provider.register()

        config = _config()
        llm = get_llm(
            provider="openai",
            deployment_name=config.llm_config.model,
            temperature=config.llm_config.temperature,
        )
        # SQLite opened read-only: the Agent's tools generate SELECTs, and a
        # generated statement that is not a SELECT should fail at the database
        # rather than silently modifying the fixture.
        datasource = SQLDatabase.from_uri(f"sqlite:///file:{database_path()}?mode=ro&uri=true")
        _compiled = DataAgentGraph(llm=llm, datasource=datasource, config=config).compile()
    return _compiled
