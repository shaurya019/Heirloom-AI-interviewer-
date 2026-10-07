"""API request/response models not owned by the domain layer."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.models.session import Message, Session

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SessionDetail(Session):
    message_count: int
    node_counts: dict[str, int]
    open_question_count: int


class MemoryCounts(BaseModel):
    total: int
    by_type: dict[str, int]


__all__ = ["Page", "MessageIn", "SessionDetail", "MemoryCounts", "Message"]
