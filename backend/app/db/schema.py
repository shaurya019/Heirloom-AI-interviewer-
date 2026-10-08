"""Table definition + idempotent create/delete. Works against DynamoDB Local and real AWS."""
from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from app.logging_setup import get_logger, log_event

log = get_logger(__name__)

GSI_NAMES = ("GSI1", "GSI2", "GSI3")

def table_definition(table_name: str) -> dict[str, Any]:
    attrs = ["pk", "sk"] + [f"{g.lower()}{s}" for g in GSI_NAMES for s in ("pk", "sk")]
    return {
        "TableName": table_name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in attrs],
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": g,
                "KeySchema": [
                    {"AttributeName": f"{g.lower()}pk", "KeyType": "HASH"},
                    {"AttributeName": f"{g.lower()}sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for g in GSI_NAMES
        ],
    }


def create_table(client: Any, table_name: str, wait: bool = True) -> str:
    """Create the table if missing. Returns 'created' or 'exists'."""
    try:
        client.create_table(**table_definition(table_name))
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            log_event(log, "dynamodb.table_exists", table=table_name)
            return "exists"
        raise
    if wait:
        client.get_waiter("table_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 60}
        )
    log_event(log, "dynamodb.table_created", table=table_name)
    return "created"



def delete_table(client: Any, table_name: str, wait: bool = True) -> str:
    try:
        client.delete_table(TableName=table_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return "missing"
        raise
    if wait:
        client.get_waiter("table_not_exists").wait(
            TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 60}
        )
    return "deleted"
