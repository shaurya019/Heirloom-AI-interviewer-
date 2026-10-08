"""boto3 factories. DYNAMODB_ENDPOINT_URL switches to DynamoDB Local; unset means real AWS."""
from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config

from app.config import Settings

_BOTO_CONFIG = Config(retries={"max_attempts": 8, "mode": "adaptive"}, connect_timeout=5, read_timeout=15)


def _kwargs(settings: Settings) -> dict[str, Any]:
    kw: dict[str, Any] = {"region_name": settings.aws_region, "config": _BOTO_CONFIG}
    if settings.dynamodb_endpoint_url:
        kw["endpoint_url"] = settings.dynamodb_endpoint_url
    return kw


def dynamodb_client(settings: Settings) -> Any:
    return boto3.client("dynamodb", **_kwargs(settings))


def dynamodb_table(settings: Settings) -> Any:
    return boto3.resource("dynamodb", **_kwargs(settings)).Table(settings.dynamodb_table)


def ping(settings: Settings) -> tuple[bool, str | None]:
    """(reachable_and_table_exists, error_summary)."""
    try:
        dynamodb_client(settings).describe_table(TableName=settings.dynamodb_table)
        return True, None
    except Exception as e:  # noqa: BLE001 - health check must never raise
        return False, f"{type(e).__name__}: {e}"[:200]
