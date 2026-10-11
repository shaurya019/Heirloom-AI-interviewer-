from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from boto3.dynamodb.conditions import Key
from pydantic import BaseModel
from ulid import ULID

from app.db import keys
from app.db.codec import from_ddb, to_ddb
from app.llm.chat import LLMResult
from app.logging_setup import get_logger, log_event
from app.models.memory import utcnow

log = get_logger(__name__)
OUTPUT_MAX_CHARS = 4000


class AgentRun(BaseModel):
    run_id: str
    agent: str
    session_id: str
    user_id: str | None = None
    input_ids: list[str]
    prompt_tokens: int
    completion_tokens: int = 0
    output: str
    latency_ms: float
    model: str
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    created_at: datetime


def run_scope(session_id: str | None, user_id: str | None) -> str:
    """User-level agents (gap finder, chapter writer) log under a per-user pseudo-session."""
    return session_id or f"user-{user_id}"


class AgentRunRepository:
    def __init__(self, table: Any):
        self.table = table

    def log(self, agent: str, *, session_id: str | None, user_id: str | None, input_ids: list[str],
            result: LLMResult | None, output: Any, status: str = "ok", error: str | None = None,
            latency_ms: float | None = None) -> AgentRun:
        out = output if isinstance(output, str) else json.dumps(output, default=str)
        run = AgentRun(run_id=str(ULID()), agent=agent, session_id=run_scope(session_id, user_id), user_id=user_id,
                       input_ids=input_ids, prompt_tokens=result.prompt_tokens if result else 0,
                       completion_tokens=result.completion_tokens if result else 0,
                       output=out[:OUTPUT_MAX_CHARS], latency_ms=round(latency_ms if latency_ms is not None
                                                                       else (result.latency_ms if result else 0), 1),
                       model=result.model if result else "n/a", status=status,  # type: ignore[arg-type]
                       error=error, created_at=utcnow())
        ts = run.created_at.isoformat()
        self.table.put_item(Item=to_ddb({**run.model_dump(mode="json"), "pk": keys.session_pk(run.session_id),
                                         "sk": keys.agent_run_sk(ts, run.run_id), "entity": "agent_run"}))
        log_event(log, "agent.run", agent=agent, session_id=run.session_id, prompt_tokens=run.prompt_tokens,
                  latency_ms=run.latency_ms, model=run.model, status=status)
        return run

    def list_for_session(self, session_id: str, limit: int = 200) -> list[AgentRun]:
        r = self.table.query(KeyConditionExpression=Key("pk").eq(keys.session_pk(session_id))
                             & Key("sk").begins_with(keys.RUN_PREFIX), ScanIndexForward=False, Limit=limit)
        return [AgentRun.model_validate({k: v for k, v in from_ddb(i).items() if k in AgentRun.model_fields})
                for i in r["Items"]]
