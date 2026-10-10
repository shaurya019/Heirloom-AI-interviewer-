"""Per-user records: open questions (contradictions), the asked-question ledger, and chapters."""
from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.db import keys
from app.db.codec import from_ddb, to_ddb
from app.models.agents import AskedQuestion, Chapter, OpenQuestion, QuestionStatus
from app.models.memory import utcnow


def _strip(d: dict[str, Any], model: type) -> dict[str, Any]:
    return {k: v for k, v in from_ddb(d).items() if k in model.model_fields}  # type: ignore[attr-defined]


class OpenQuestionRepository:
    def __init__(self, table: Any):
        self.table = table

    def add_if_new(self, q: OpenQuestion) -> bool:
        try:
            self.table.put_item(Item=to_ddb({**q.model_dump(mode="json"), "pk": keys.user_pk(q.user_id),
                                             "sk": keys.open_question_sk(q.qid), "entity": "open_question"}),
                                ConditionExpression="attribute_not_exists(pk)")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def list(self, user_id: str, status: QuestionStatus | None = None) -> list[OpenQuestion]:
        kw: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(keys.user_pk(user_id))
                              & Key("sk").begins_with(keys.OPENQ_PREFIX)}
        if status:
            kw["FilterExpression"] = Attr("status").eq(status)
        items = self.table.query(**kw)["Items"]
        return sorted((OpenQuestion.model_validate(_strip(i, OpenQuestion)) for i in items),
                      key=lambda q: q.created_at, reverse=True)

    def set_status(self, user_id: str, qid: str, status: QuestionStatus, resolution: str | None = None) -> OpenQuestion:
        from app.errors import NotFoundError

        now = utcnow().isoformat()
        expr = "SET #s = :s"
        vals: dict[str, Any] = {":s": status}
        if status == "asked":
            expr += ", asked_at = if_not_exists(asked_at, :t)"
            vals[":t"] = now
        if status == "resolved":
            expr += ", resolved_at = :t, resolution = :r"
            vals.update({":t": now, ":r": resolution or ""})
        try:
            r = self.table.update_item(Key={"pk": keys.user_pk(user_id), "sk": keys.open_question_sk(qid)},
                                       UpdateExpression=expr, ExpressionAttributeNames={"#s": "status"},
                                       ExpressionAttributeValues=vals, ConditionExpression="attribute_exists(pk)",
                                       ReturnValues="ALL_NEW")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFoundError(f"open question {qid} not found") from e
            raise
        return OpenQuestion.model_validate(_strip(r["Attributes"], OpenQuestion))


class AskedQuestionRepository:
    def __init__(self, table: Any):
        self.table = table

    def add(self, q: AskedQuestion) -> None:
        self.table.put_item(Item=to_ddb({**q.model_dump(mode="json"), "pk": keys.user_pk(q.user_id),
                                         "sk": keys.asked_question_sk(q.created_at.isoformat(), q.qid),
                                         "entity": "asked_question"}))

    def recent(self, user_id: str, limit: int = 10) -> list[AskedQuestion]:
        out: list[AskedQuestion] = []
        kw: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(keys.user_pk(user_id))
                              & Key("sk").begins_with(keys.ASKED_PREFIX), "ScanIndexForward": False}
        while len(out) < limit:
            r = self.table.query(**kw, Limit=min(1000, limit - len(out)))
            out += [AskedQuestion.model_validate(_strip(i, AskedQuestion)) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return out

    def get_many(self, user_id: str, qids: set[str]) -> list[AskedQuestion]:
        # ledger is small per user; a filtered query avoids a second index
        r = self.table.query(KeyConditionExpression=Key("pk").eq(keys.user_pk(user_id))
                             & Key("sk").begins_with(keys.ASKED_PREFIX))
        return [AskedQuestion.model_validate(_strip(i, AskedQuestion)) for i in r["Items"] if i["qid"] in qids]


class ChapterRepository:
    def __init__(self, table: Any):
        self.table = table

    def add(self, ch: Chapter) -> None:
        self.table.put_item(Item=to_ddb({**ch.model_dump(mode="json"), "pk": keys.user_pk(ch.user_id),
                                         "sk": keys.chapter_sk(ch.created_at.isoformat(), ch.chapter_id),
                                         "entity": "chapter"}))

    def list(self, user_id: str) -> list[Chapter]:
        r = self.table.query(KeyConditionExpression=Key("pk").eq(keys.user_pk(user_id))
                             & Key("sk").begins_with(keys.CHAPTER_PREFIX), ScanIndexForward=False)
        return [Chapter.model_validate(_strip(i, Chapter)) for i in r["Items"]]
