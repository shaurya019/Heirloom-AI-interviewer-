"""Pydantic models for agent inputs/outputs and the records they persist."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.memory import ExtractedMemory, MemoryRecord


class ArchivistOutput(BaseModel):
    memories: list[ExtractedMemory] = Field(default_factory=list)


class Contradiction(BaseModel):
    existing_memory_id: str
    field: Literal["date", "name", "place"]
    existing_value: str
    new_value: str
    explanation: str
    question: str


class ContinuityOutput(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)


QuestionStatus = Literal["open", "asked", "resolved"]


class OpenQuestion(BaseModel):
    qid: str
    user_id: str
    session_id: str | None = None
    memory_ids: list[str]                 # [existing, new]
    field: Literal["date", "name", "place"]
    existing_value: str
    new_value: str
    explanation: str
    question: str
    status: QuestionStatus = "open"
    resolution: str | None = None
    created_at: datetime
    asked_at: datetime | None = None
    resolved_at: datetime | None = None


class ResolveQuestion(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)


class TopicSuggestion(BaseModel):
    topic: str
    question: str
    reason: str


class GapSuggestions(BaseModel):
    suggestions: list[TopicSuggestion] = Field(default_factory=list)


class YearGap(BaseModel):
    start: int
    end: int
    years: int


class GapReport(BaseModel):
    user_id: str
    span_start: int | None
    span_end: int | None
    year_coverage: dict[int, int]
    gaps: list[YearGap]
    theme_counts: dict[str, int]
    type_counts: dict[str, int]
    thin_themes: list[str]
    top_entities: list[tuple[str, int]]
    suggestions: list[TopicSuggestion]
    memory_count: int


class ChapterRequest(BaseModel):
    theme: str | None = Field(None, max_length=200)
    era_start: int | None = Field(None, ge=1800, le=2100)
    era_end: int | None = Field(None, ge=1800, le=2100)
    title: str | None = Field(None, max_length=200)
    top_k: int = Field(20, ge=3, le=60)

    @model_validator(mode="after")
    def _need_theme_or_era(self) -> "ChapterRequest":
        if not self.theme and self.era_start is None and self.era_end is None:
            raise ValueError("provide a theme or an era (era_start/era_end)")
        if self.era_start and self.era_end and self.era_start > self.era_end:
            raise ValueError("era_start must be <= era_end")
        return self


class Chapter(BaseModel):
    chapter_id: str
    user_id: str
    title: str
    request: ChapterRequest
    markdown: str
    citations: list[str]
    cited_memories: list[MemoryRecord]
    section_ids: list[str]
    invalid_citations_removed: int
    model: str
    created_at: datetime


class AskedQuestion(BaseModel):
    qid: str
    user_id: str
    session_id: str
    message_id: str
    text: str
    created_at: datetime
