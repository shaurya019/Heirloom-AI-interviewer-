from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    birth_year: int | None = Field(None, ge=1880, le=2030)
    description: str = Field("", max_length=2000)
    user_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class User(BaseModel):
    user_id: str
    name: str
    birth_year: int | None = None
    description: str = ""
    created_at: datetime


class SessionCreate(BaseModel):
    user_id: str
    title: str = Field("Interview session", max_length=200)


class Session(BaseModel):
    session_id: str
    user_id: str
    title: str
    status: Literal["active", "ended"] = "active"
    created_at: datetime
    ended_at: datetime | None = None
    msg_count: int = 0                 # next seq to allocate
    buffer_start_seq: int = 0          # first message not yet folded into the rolling summary
    rolling_summary: str = ""
    rolling_summary_tokens: int = 0
    rolling_version: int = 0


Role = Literal["user", "assistant"]


class Message(BaseModel):
    message_id: str
    session_id: str
    user_id: str
    seq: int
    role: Role
    content: str
    token_count: int
    created_at: datetime
