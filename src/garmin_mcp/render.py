"""Turn Garmin API results into compact JSON text that fits a size budget."""

import json
from datetime import date, datetime
from enum import Enum
from typing import Any

_LIST_CAPS = (2000, 1000, 500, 250, 100, 50, 25, 10)


def _default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    return str(value)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=_default, separators=(",", ":"), ensure_ascii=False)


def _downsample(obj: Any, cap: int) -> Any:
    """Recursively shrink every list longer than `cap` to `cap` evenly spaced items."""
    if isinstance(obj, dict):
        return {k: _downsample(v, cap) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        items = list(obj)
        if len(items) > cap:
            step = (len(items) - 1) / (cap - 1)
            items = [items[round(i * step)] for i in range(cap)]
            return {
                "_downsampled": f"kept {cap} of {len(obj)} items, evenly spaced",
                "items": [_downsample(i, cap) for i in items],
            }
        return [_downsample(i, cap) for i in items]
    return obj


def render(obj: Any, max_chars: int) -> str:
    """Serialise `obj` as compact JSON, downsampling long lists if it exceeds `max_chars`."""
    text = _dumps(obj)
    if len(text) <= max_chars:
        return text
    for cap in _LIST_CAPS:
        shrunk = _dumps(_downsample(obj, cap))
        if len(shrunk) <= max_chars:
            return shrunk
    return _dumps(
        {
            "_truncated": f"response was {len(text)} characters; showing the first {max_chars}",
            "text": text[:max_chars],
        }
    )
