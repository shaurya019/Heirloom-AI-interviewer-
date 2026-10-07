"""HTTP API. Every handler is a thin adapter over the container; sync handlers run in the threadpool."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.api.deps import get_container
from app.api.schemas import MessageIn, Page, SessionDetail
from app.container import Container
from app.errors import NotFoundError
# from app.models.agents import Chapter, ChapterRequest, GapReport, OpenQuestion, QuestionStatus, ResolveQuestion
# from app.models.memory import MemoryCreate, MemoryRecord
from app.models.session import Message, Session, SessionCreate, User, UserCreate
from app.models.summary import SummaryNode, SummaryTree
from app.repos.agent_runs import AgentRun
from app.repos.summary_nodes import build_tree_response
from app.retrieval.hybrid import SearchRequest, SearchResponse
from app.services.context_assembler import ContextPreview

router = APIRouter()
C = Depends(get_container)

@router.post("/users", response_model=User, status_code=201, tags=["users"])
def create_user(body: UserCreate, c: Container = C) -> User:
    return c.users.create(body)


@router.get("/users/{user_id}", response_model=User, tags=["users"])
def get_user(user_id: str, c: Container = C) -> User:
    return c.users.require(user_id)


@router.get("/users/{user_id}/sessions", response_model=list[Session], tags=["users"])
def list_user_sessions(user_id: str, c: Container = C) -> list[Session]:
    c.users.require(user_id)
    return sorted(c.sessions.list_for_user(user_id), key=lambda s: s.created_at, reverse=True)


@router.post("/sessions", response_model=Session, status_code=201, tags=["sessions"])
def create_session(body: SessionCreate, c: Container = C) -> Session:
    c.users.require(body.user_id)
    return c.sessions.create(body)

@router.post("/sessions/{session_id}/messages", tags=["sessions"],
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "SSE: context, token*, assistant_message, done | error"}})
def post_message(session_id: str, body: MessageIn, c: Container = C) -> StreamingResponse:
    user_msg = c.orchestrator.accept_user_message(session_id, body.content)

    async def events() -> AsyncIterator[str]:
        yield _sse("user_message", user_msg.model_dump(mode="json"))
        async for ev in c.orchestrator.stream_reply(user_msg):
            yield _sse(ev["event"], ev["data"])

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(c.orchestrator.post_turn, user_msg))

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

@router.get("/sessions/{session_id}", response_model=SessionDetail, tags=["sessions"])
def get_session(session_id: str, c: Container = C) -> SessionDetail:
    s = c.sessions.require(session_id)
    nodes = c.nodes.list_session(session_id)
    return SessionDetail(
        **s.model_dump(),
        message_count=s.msg_count,
        node_counts={f"L{k}": v for k,v in sorted(Counter(n.level for n in nodes).items())},
        open_question_count=len(c.open_questions.list(s.user_id, "open"))
    )

@router.get("/sessions/{session_id}/messages", response_model=Page[Message], tags=["sessions"])
def list_messages(session_id: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=200),
                  c: Container = C) -> Page[Message]:
    c.sessions.require(session_id)
    after = int(cursor) if cursor not in (None, "") else None
    items, nxt = c.sessions.list_messages(session_id, after_seq=after, limit=limit)
    return Page[Message](items=items, next_cursor=str(nxt) if nxt is not None else None)

@router.post("/sessions/{session_id}/end", response_model=SummaryNode | None, tags=["sessions"])
def end_session(session_id: str, c: Container = C) -> SummaryNode | None:
    c.sessions.require(session_id)
    return c.summarizer.end_session(session_id)


@router.get("/sessions/{session_id}/summary-tree", response_model=SummaryTree, tags=["sessions"])
def summary_tree(session_id: str, c: Container = C) -> SummaryTree:
    return build_tree_response(c.nodes, c.sessions.require(session_id))


@router.get("/sessions/{session_id}/context/preview", response_model=ContextPreview, tags=["sessions"])
def context_preview(session_id: str, q: str | None = None, c: Container = C) -> ContextPreview:
    return c.assembler.assemble(session_id, query=q).preview