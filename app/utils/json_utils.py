"""JSON-safe encoding for API payloads and export files."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def dumps(data: Any, indent: int | None = 2) -> str:
    return json.dumps(data, default=json_default, indent=indent, ensure_ascii=False)


def loads(text: str) -> Any:
    return json.loads(text)
