"""Uniform API response envelope."""

from typing import Any
from datetime import datetime, timezone


def ok(tool: str, data: Any, meta: dict | None = None) -> dict:
    payload = {
        "success": True,
        "tool": tool,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    if meta:
        payload["meta"] = meta
    return payload
