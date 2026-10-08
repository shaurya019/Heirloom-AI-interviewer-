"""Python <-> DynamoDB value conversion (floats must be Decimal; Decimals come back)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_ddb(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return Decimal(repr(v))
    if isinstance(v, dict):
        return {k: to_ddb(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [to_ddb(x) for x in v]
    return v


def from_ddb(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: from_ddb(x) for k, x in v.items()}
    if isinstance(v, list):
        return [from_ddb(x) for x in v]
    if isinstance(v, set):
        return [from_ddb(x) for x in v]
    return v


def batch_get(table: Any, key_list: list[dict[str, str]], max_attempts: int = 6) -> list[dict[str, Any]]:
    """BatchGetItem in chunks of 100 with UnprocessedKeys retry + backoff."""
    import time

    client = table.meta.client
    name = table.name
    items: list[dict[str, Any]] = []
    for i in range(0, len(key_list), 100):
        req: dict[str, Any] = {name: {"Keys": key_list[i:i + 100]}}
        for attempt in range(max_attempts):
            resp = client.batch_get_item(RequestItems=req)
            items.extend(resp["Responses"].get(name, []))
            req = resp.get("UnprocessedKeys") or {}
            if not req:
                break
            time.sleep(min(2.0, 0.05 * 2 ** attempt))
        else:
            raise RuntimeError(f"BatchGetItem left unprocessed keys after {max_attempts} attempts")
    return items

