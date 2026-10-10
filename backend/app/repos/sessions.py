from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from ulid import ULID

from app.db import keys
from app.db.codec import from_ddb, to_ddb
from app.errors import ConflictError, NotFoundError
from app.models.memory import utcnow
from app.models.session import Message, Role, Session, SessionCreate, User, UserCreate

_SESSION_FIELDS = set(Session.model_fields)

class UserRepository:
    def __init__(self,table):
        self.table = table
        
    def create(self, body: UserCreate):
        user = User(user_id=body.user_id or str(ULID()).lower(), name=body.name, birth_year=body.birth_year,
                    description=body.description, created_at=utcnow())
        try:
            self.table.put_item(
                Item=to_ddb({
                 **user.model_dump(mode="json"),
                 "pk": keys.user_pk(user.user_id),   
                 "sk": keys.USER_SK, "entity": "user"}),
            )
        
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(f"user {user.user_id} already exists") from e
            raise
        return user
    
    def get(self, user_id: str):
        it = self.table.get_item(Key={"pk": keys.user_pk(user_id), "sk": keys.USER_SK}).get("Item")
        return User.model_validate(from_ddb(it)) if it else None
    
    def require(self, user_id: str) -> User:
        u = self.get(user_id)
        if not u:
            raise NotFoundError(f"user {user_id} not found", {"user_id": user_id})
        return u
    
class SessionRepository:
    def __init__(self, table: Any):
        self.table = table

    def create(self, body: SessionCreate) -> Session:
        s = Session(session_id=str(ULID()), user_id=body.user_id, title=body.title, created_at=utcnow())
        self.table.put_item(Item=to_ddb({**s.model_dump(mode="json"), "pk": keys.session_pk(s.session_id),
                                         "sk": keys.SESSION_SK, "entity": "session",
                                         "gsi1pk": keys.user_sessions_gsi1pk(s.user_id),
                                         "gsi1sk": s.created_at.isoformat()}),
                            ConditionExpression="attribute_not_exists(pk)")
        return s

    def get(self, session_id: str) -> Session | None:
        it = self.table.get_item(Key={"pk": keys.session_pk(session_id), "sk": keys.SESSION_SK},
                                 ConsistentRead=True).get("Item")
        return Session.model_validate({k: v for k, v in from_ddb(it).items() if k in _SESSION_FIELDS}) if it else None

    def require(self, session_id: str) -> Session:
        s = self.get(session_id)
        if not s:
            raise NotFoundError(f"session {session_id} not found", {"session_id": session_id})
        return s

    def list_for_user(self, user_id: str) -> list[Session]:
        resp = self.table.query(IndexName="GSI1",
                                KeyConditionExpression=Key("gsi1pk").eq(keys.user_sessions_gsi1pk(user_id)))
        return [Session.model_validate({k: v for k, v in from_ddb(i).items() if k in _SESSION_FIELDS})
                for i in resp["Items"]]

    def mark_ended(self, session_id: str) -> None:
        self.table.update_item(Key={"pk": keys.session_pk(session_id), "sk": keys.SESSION_SK},
                               UpdateExpression="SET #s = :e, ended_at = :t",
                               ExpressionAttributeNames={"#s": "status"},
                               ExpressionAttributeValues={":e": "ended", ":t": utcnow().isoformat()})
        
    def append_message(self, session_id: str, user_id: str, role: Role, content: str, token_count: int) -> Message:
        """Allocate a monotonically increasing seq atomically, then write the message."""
        try:
            resp = self.table.update_item(
                Key={"pk": keys.session_pk(session_id), "sk": keys.SESSION_SK},
                UpdateExpression="ADD msg_count :one", ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":one": 1}, ReturnValues="UPDATED_NEW")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFoundError(f"session {session_id} not found") from e
            raise
        seq = int(resp["Attributes"]["msg_count"]) - 1
        msg = Message(message_id=str(ULID()), session_id=session_id, user_id=user_id, seq=seq, role=role,
                      content=content, token_count=token_count, created_at=utcnow())
        self.table.put_item(Item=to_ddb({**msg.model_dump(mode="json"), "pk": keys.session_pk(session_id),
                                         "sk": keys.message_sk(seq), "entity": "message"}))
        return msg
    
    def list_messages(self, session_id: str, after_seq: int | None = None, limit: int = 50,
                      descending: bool = False) -> tuple[list[Message], int | None]:
        cond = Key("pk").eq(keys.session_pk(session_id))
        if after_seq is None:
            cond = cond & Key("sk").begins_with(keys.MSG_PREFIX)
        elif descending:
            cond = cond & Key("sk").between(keys.message_sk(0), keys.message_sk(max(0, after_seq - 1)))
        else:
            cond = cond & Key("sk").between(keys.message_sk(after_seq + 1), keys.message_sk(10 ** 8 - 1))
        resp = self.table.query(KeyConditionExpression=cond, Limit=limit, ScanIndexForward=not descending,
                                ConsistentRead=True)
        msgs = [Message.model_validate({k: v for k, v in from_ddb(i).items() if k in Message.model_fields})
                for i in resp["Items"]]
        nxt = msgs[-1].seq if msgs and "LastEvaluatedKey" in resp else None
        return msgs, nxt
    
    def messages_from(self, session_id: str, start_seq: int, end_seq: int | None = None) -> list[Message]:
        out: list[Message] = []
        kw: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(keys.session_pk(session_id))
                              & Key("sk").between(keys.message_sk(start_seq),
                                                  keys.message_sk(end_seq if end_seq is not None else 10 ** 8 - 1)),
                              "ConsistentRead": True}
        while True:
            resp = self.table.query(**kw)
            out += [Message.model_validate({k: v for k, v in from_ddb(i).items() if k in Message.model_fields})
                    for i in resp["Items"]]
            if "LastEvaluatedKey" not in resp:
                return out
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    
    def rolling_update_txn(self, s: Session, new_start: int, summary: str, tokens: int) -> dict[str, Any]:
        """TransactWriteItems 'Update' (high-level values: table.meta.client serializes) that advances the
        buffer only if nobody else did (optimistic concurrency on buffer_start_seq)."""
        return {"Update": {
            "TableName": self.table.name,
            "Key": {"pk": keys.session_pk(s.session_id), "sk": keys.SESSION_SK},
            "UpdateExpression": "SET buffer_start_seq = :n, rolling_summary = :r, rolling_summary_tokens = :t, "
                                "rolling_version = :v1",
            "ConditionExpression": "buffer_start_seq = :expected OR attribute_not_exists(buffer_start_seq)",
            "ExpressionAttributeValues": {":n": new_start, ":r": summary, ":t": tokens,
                                          ":v1": s.rolling_version + 1, ":expected": s.buffer_start_seq}}}