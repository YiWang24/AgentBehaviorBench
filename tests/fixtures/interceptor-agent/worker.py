from __future__ import annotations

import json
import os
import sys
import urllib.request


for line in sys.stdin:
    request = json.loads(line)
    payload = json.dumps(
        {
            "model": "smoke-model",
            "messages": [{"role": "user", "content": request["input"]}],
        }
    ).encode("utf-8")
    upstream = urllib.request.Request(
        os.environ["MODEL_URL"],
        data=payload,
        headers={
            "Authorization": f"Bearer {os.environ['MODEL_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(upstream, timeout=20) as response:
        body = json.loads(response.read())
    print(
        json.dumps(
            {
                "ok": True,
                "output": {
                    "status": 200,
                    "model": body["json"]["model"],
                },
            }
        ),
        flush=True,
    )
