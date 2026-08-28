"""JSONL worker for the e-commerce recommendation pipeline.

The pipeline takes a user id and a scene, not free text. The Case's text is
treated as the scene when it names one, and recorded in `raw_output.request`
either way; a numeric or keyworded payload can also set the user id and item
count.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys


def _request(payload: dict) -> dict:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return {"scene": value or "homepage"}
    if isinstance(value, dict):
        text = None
        for key in ("scene", "query", "question", "prompt", "input", "text", "content"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                text = found
                break
        request = {
            "user_id": str(value.get("user_id") or os.environ.get("ECOM_USER_ID", "benchmark-user")),
            "scene": text or "homepage",
            "num_items": int(value.get("num_items", os.environ.get("ECOM_NUM_ITEMS", "5"))),
            "context": value.get("context") if isinstance(value.get("context"), dict) else {},
        }
        return request
    return {"scene": "homepage"}


def _field(product, name):
    if isinstance(product, dict):
        return product.get(name)
    return getattr(product, name, None)


def _product_summary(products) -> list[dict]:
    return [
        {
            "product_id": _field(product, "product_id"),
            "name": _field(product, "name"),
            "category": _field(product, "category"),
            "price": _field(product, "price"),
            "score": _field(product, "score"),
        }
        for product in products or []
    ]


async def _run() -> int:
    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"JSONDecodeError: {exc}"}), flush=True)
            continue

        try:
            request = _request(payload)
            state = {
                "user_id": request.get("user_id", "benchmark-user"),
                "scene": request.get("scene", "homepage"),
                "num_items": request.get("num_items", 5),
                "context": request.get("context", {}),
            }
            with contextlib.redirect_stdout(sys.stderr):
                result = await compiled.ainvoke(state)

            final = result.get("final_products") or []
            copies = result.get("marketing_copies") or result.get("copies") or []
            reply = {
                "ok": True,
                "output": json.dumps(
                    {"products": _product_summary(final), "copies": copies},
                    ensure_ascii=False,
                    default=str,
                ),
                "raw_output": {
                    "request": request,
                    "final_products": _product_summary(final),
                    "ranked_products": _product_summary(result.get("ranked_products")),
                    "marketing_copies": copies,
                    "experiment_group": result.get("experiment_group"),
                    "total_latency_ms": result.get("total_latency_ms"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
