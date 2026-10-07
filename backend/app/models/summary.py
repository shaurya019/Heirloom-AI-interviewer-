from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryNode(BaseModel):
    node_id: str
    user_id: str
    session_id: str
    level: int = Field(ge=0, le=3)
    parent_id: str | None = None
    parent_level: int | None = None
    child_ids: list[str] = Field(default_factory=list)
    title: str = ""
    summary: str
    first_message_id: str
    last_message_id: str
    first_seq: int
    last_seq: int
    token_count: int
    source_token_count: int = 0      # tokens of the material this node summarizes
    model: str
    created_at: datetime
    version: int = 1


class SummaryTreeNode(SummaryNode):
    children: list["SummaryTreeNode"] = Field(default_factory=list)


class SummaryTree(BaseModel):
    session_id: str
    roots: list[SummaryTreeNode]
    rolling_summary: str
    rolling_summary_tokens: int
    buffer_start_seq: int
    msg_count: int
