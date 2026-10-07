from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class MemoryType(str, Enum):
    person = "person"
    place = "place"
    event = "event"
    anecdote = "anecdote"
    emotion = "emotion"
    fact = "fact"


VectorStatus = Literal["pending", "synced"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExtractedMemory(BaseModel):
    """Archivist structured output for one atomic memory."""

    type: MemoryType
    text: str = Field(min_length=3, max_length=2000)
    entities: list[str] = Field(default_factory=list)
    event_year_start: int | None = Field(None, ge=1800, le=2100)
    event_year_end: int | None = Field(None, ge=1800, le=2100)
    importance: float = Field(ge=0, le=1)
    importance_rationale: str = ""

    @model_validator(mode="after")
    def _years(self) -> "ExtractedMemory":
        if self.event_year_start is not None and self.event_year_end is None:
            self.event_year_end = self.event_year_start
        if self.event_year_end is not None and self.event_year_start is None:
            self.event_year_start = self.event_year_end
        if (self.event_year_start is not None and self.event_year_end is not None
                and self.event_year_end < self.event_year_start):
            self.event_year_start, self.event_year_end = self.event_year_end, self.event_year_start
        return self

    @field_validator("entities")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        seen: dict[str, str] = {}
        for e in v:
            e = e.strip()
            if e and e.lower() not in seen:
                seen[e.lower()] = e
        return list(seen.values())


class MemoryCreate(ExtractedMemory):
    user_id: str
    session_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None  # allow backdating (seeding, imports)


class MemoryRecord(MemoryCreate):
    memory_id: str
    created_at: datetime
    embedding_model: str
    version: int = 1
    vector_status: VectorStatus = "pending"

    @property
    def created_epoch(self) -> int:
        return int(self.created_at.timestamp())
