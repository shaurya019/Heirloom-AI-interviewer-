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
# from app.repos.agent_runs import AgentRun
# from app.repos.summary_nodes import build_tree_response
# from app.retrieval.hybrid import SearchRequest, SearchResponse
# from app.services.context_assembler import ContextPreview

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
