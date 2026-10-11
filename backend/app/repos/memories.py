from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.db import keys
from app.db.codec import batch_get, from_ddb, to_ddb
from app.errors import ConflictError
from app.models.memory import MemoryRecord


def _item(rec: MemoryRecord) -> dict[str, Any]:
    ts = rec.created_at.isoformat()
    item = rec.model_dump(mode="json")
    item.update({
        "pk": keys.memory_pk(rec.memory_id), "sk": keys.MEMORY_SK, "entity": "memory",
        "created_epoch": rec.created_epoch,
        "gsi1pk": keys.user_memories_gsi1pk(rec.user_id),
        "gsi1sk": keys.memory_time_gsi1sk(ts, rec.memory_id),
    })
    if rec.vector_status == "pending":
        item["gsi3pk"] = keys.VECTOR_PENDING_GSI3PK
        item["gsi3sk"] = keys.memory_time_gsi1sk(ts, rec.memory_id)
    return to_ddb(item)

def _record(item: dict[str, Any]) -> MemoryRecord:
    d = from_ddb(item)
    for k in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi3pk", "gsi3sk", "entity", "created_epoch", "vector_error"):
        d.pop(k, None)
    return MemoryRecord.model_validate(d)


class MemoryRepository:
    def __init__(self, table: Any):
        self.table = table

    def put_new(self, rec: MemoryRecord) -> None:
        try:
            self.table.put_item(Item=_item(rec), ConditionExpression="attribute_not_exists(pk)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(f"memory {rec.memory_id} already exists") from e
            raise

    def get(self, memory_id: str) -> MemoryRecord | None:
        it = self.table.get_item(Key={"pk": keys.memory_pk(memory_id), "sk": keys.MEMORY_SK}).get("Item")
        return _record(it) if it else None

    def batch_get(self, ids: list[str]) -> dict[str, MemoryRecord]:
        uniq = list(dict.fromkeys(ids))
        items = batch_get(self.table, [{"pk": keys.memory_pk(i), "sk": keys.MEMORY_SK} for i in uniq])
        recs = [_record(it) for it in items]
        return {r.memory_id: r for r in recs}

    def mark_synced(self, memory_id: str) -> None:
        self.table.update_item(
            Key={"pk": keys.memory_pk(memory_id), "sk": keys.MEMORY_SK},
            UpdateExpression="SET vector_status = :s REMOVE gsi3pk, gsi3sk, vector_error",
            ConditionExpression="attribute_exists(pk)", ExpressionAttributeValues={":s": "synced"})

    def mark_pending(self, memory_id: str, error: str) -> None:
        rec = self.get(memory_id)
        if rec is None:
            return
        self.table.update_item(
            Key={"pk": keys.memory_pk(memory_id), "sk": keys.MEMORY_SK},
            UpdateExpression="SET vector_status = :s, gsi3pk = :p, gsi3sk = :k, vector_error = :e",
            ExpressionAttributeValues={":s": "pending", ":p": keys.VECTOR_PENDING_GSI3PK,
                                       ":k": keys.memory_time_gsi1sk(rec.created_at.isoformat(), memory_id),
                                       ":e": error[:500]})

    def delete(self, memory_id: str) -> MemoryRecord | None:
        resp = self.table.delete_item(Key={"pk": keys.memory_pk(memory_id), "sk": keys.MEMORY_SK},
                                      ReturnValues="ALL_OLD")
        old = resp.get("Attributes")
        return _record(old) if old else None

    def _paginate(self, **kw: Any) -> Iterator[dict[str, Any]]:
        while True:
            resp = self.table.query(**kw)
            yield from resp["Items"]
            if "LastEvaluatedKey" not in resp:
                return
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def list_by_user(self, user_id: str, start: datetime | None = None, end: datetime | None = None,
                     limit: int | None = None) -> list[MemoryRecord]:
        cond = Key("gsi1pk").eq(keys.user_memories_gsi1pk(user_id))
        if start or end:
            lo = start.isoformat() if start else "0"
            hi = (end.isoformat() if end else "9") + "~"
            cond = cond & Key("gsi1sk").between(lo, hi)
        out = []
        for it in self._paginate(IndexName="GSI1", KeyConditionExpression=cond):
            out.append(_record(it))
            if limit and len(out) >= limit:
                break
        return out

    def list_pending(self, limit: int = 100) -> list[MemoryRecord]:
        out = []
        for it in self._paginate(IndexName="GSI3",
                                 KeyConditionExpression=Key("gsi3pk").eq(keys.VECTOR_PENDING_GSI3PK)):
            out.append(_record(it))
            if len(out) >= limit:
                break
        return out
