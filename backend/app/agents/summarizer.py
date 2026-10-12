"""Summarizer agent — owns Technique 1 (rolling + hierarchical summary memory).

Rolling:  when buffer tokens > ROLLING_BUFFER_MAX_TOKENS, take the oldest ROLLING_CHUNK_MESSAGES
          (never splitting a user→assistant pair, never consuming the latest pair), summarize it, and
          fold it into the running summary (capped at ROLLING_SUMMARY_MAX_TOKENS).
          The leaf node + buffer advance commit in ONE transaction, conditioned on the buffer pointer,
          so concurrent or repeated runs can't double-summarize.
Tree:     L0 chunk leaves → L1 sections every SECTION_FANOUT leaves → L2 session summary → L3 life archive.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Sequence

from pydantic import BaseModel, Field

from app.agents import prompts
from app.config import Settings
from app.llm.chat import ChatMessage, LLMClient, LLMResult
from app.logging_setup import get_logger, log_event
from app.models.memory import utcnow
from app.models.session import Message, Session
from app.models.summary import SummaryNode
from app.repos.agent_runs import AgentRunRepository
from app.repos.sessions import SessionRepository, UserRepository
from app.repos.summary_nodes import (SummaryNodeRepository, TxnConflict, archive_node_id, archive_session_id,
                                     node_id_for, session_node_id)
from app.tokens import get_counter

log = get_logger(__name__)
CHUNK_SUMMARY_MAX_TOKENS = 220
SESSION_SUMMARY_MAX_TOKENS = 450
ARCHIVE_SUMMARY_MAX_TOKENS = 700


class SectionOut(BaseModel):
    title: str = Field(max_length=120)
    summary: str


class SummarizeReport(BaseModel):
    leaves_created: list[str] = Field(default_factory=list)
    sections_created: list[str] = Field(default_factory=list)
    buffer_tokens_before: int = 0
    buffer_tokens_after: int = 0
    rolling_summary_tokens: int = 0


def transcript(msgs: Sequence[Message]) -> str:
    return "\n".join(f"{'NARRATOR' if m.role == 'user' else 'INTERVIEWER'}: {m.content}" for m in msgs)


class Summarizer:
    def __init__(self, settings: Settings, sessions: SessionRepository, users: UserRepository,
                 nodes: SummaryNodeRepository, llm: LLMClient, runs: AgentRunRepository,
                 on_section: Callable[[SummaryNode], None] | None = None):
        self.s = settings
        self.sessions, self.users, self.nodes, self.llm, self.runs = sessions, users, nodes, llm, runs
        self.on_section = on_section
        self.tok = get_counter(settings.summary_model)

    # ------------------------------------------------------------------ helpers
    def _narrator(self, user_id: str) -> str:
        u = self.users.get(user_id)
        return u.name.split()[0] if u else "The narrator"

    def _log(self, session_id: str, user_id: str, input_ids: list[str], res: LLMResult | None, out: Any,
             t0: float) -> None:
        self.runs.log("summarizer", session_id=session_id, user_id=user_id, input_ids=input_ids, result=res,
                      output=out, latency_ms=(time.perf_counter() - t0) * 1000)

    def select_chunk(self, buffer: Sequence[Message], finalize: bool) -> list[Message]:
        n = self.s.rolling_chunk_messages
        limit = len(buffer) if finalize else len(buffer) - 2   # always keep the latest pair verbatim
        take = min(n, limit)
        if take <= 0:
            return []
        chunk = list(buffer[:take])
        # never split a user→assistant pair: a trailing user message whose reply follows stays in the buffer
        if chunk[-1].role == "user" and take < len(buffer) and buffer[take].role == "assistant":
            chunk = chunk[:-1]
        return chunk

    # ------------------------------------------------------------------ rolling
    def roll_once(self, session_id: str, *, finalize: bool = False) -> SummaryNode | None:
        s = self.sessions.require(session_id)
        buffer = self.sessions.messages_from(session_id, s.buffer_start_seq)
        tokens = sum(m.token_count for m in buffer)
        if not buffer or (not finalize and tokens <= self.s.rolling_buffer_max_tokens):
            return None
        chunk = self.select_chunk(buffer, finalize)
        if not chunk:
            return None
        return self.summarize_range(s, chunk)

    def summarize_range(self, s: Session, chunk: Sequence[Message]) -> SummaryNode:
        """Summarize exactly this message range into a leaf. Idempotent per (session, first, last)."""
        first, last = chunk[0], chunk[-1]
        nid = node_id_for(s.session_id, 0, first.message_id, last.message_id)
        existing = [n for n in self.nodes.list_session(s.session_id, 0) if n.node_id == nid]
        if existing:
            log_event(log, "summarizer.leaf_exists", node_id=nid)
            return existing[0]
        t0 = time.perf_counter()
        narrator = self._narrator(s.user_id)
        msgs_json = [{"role": m.role, "content": m.content} for m in chunk]
        res = self.llm.generate(
            "chunk_summary", prompts.CHUNK_SUMMARY.format(max_tokens=CHUNK_SUMMARY_MAX_TOKENS),
            [ChatMessage(role="user", content=transcript(chunk))], max_tokens=CHUNK_SUMMARY_MAX_TOKENS,
            hints={"messages": msgs_json, "narrator": narrator, "max_tokens": CHUNK_SUMMARY_MAX_TOKENS})
        chunk_summary = self.tok.truncate(res.text, CHUNK_SUMMARY_MAX_TOKENS)
        cap = self.s.rolling_summary_max_tokens
        fold = self.llm.generate(
            "fold_rolling", prompts.FOLD_ROLLING.format(max_tokens=cap),
            [ChatMessage(role="user", content=f"EXISTING:\n{s.rolling_summary or '(none)'}\n\nNEW:\n{chunk_summary}")],
            max_tokens=cap, hints={"old": s.rolling_summary, "new": chunk_summary, "max_tokens": cap})
        rolling = self.tok.truncate(fold.text, cap)  # hard cap even if the model overshoots
        leaf = SummaryNode(
            node_id=nid, user_id=s.user_id, session_id=s.session_id, level=0, title="", summary=chunk_summary,
            first_message_id=first.message_id, last_message_id=last.message_id, first_seq=first.seq,
            last_seq=last.seq, token_count=self.tok.count(chunk_summary),
            source_token_count=sum(m.token_count for m in chunk), model=res.model, created_at=utcnow())
        try:
            self.nodes.commit_leaf(leaf, self.sessions.rolling_update_txn(
                s, last.seq + 1, rolling, self.tok.count(rolling)))
        except TxnConflict as e:
            log_event(log, "summarizer.leaf_conflict", node_id=nid, reasons=e.reasons)
            again = [n for n in self.nodes.list_session(s.session_id, 0) if n.node_id == nid]
            if again:
                return again[0]
            raise
        combined = LLMResult(text=chunk_summary, model=res.model, prompt_tokens=res.prompt_tokens + fold.prompt_tokens,
                             completion_tokens=res.completion_tokens + fold.completion_tokens,
                             latency_ms=res.latency_ms + fold.latency_ms)
        self._log(s.session_id, s.user_id, [m.message_id for m in chunk], combined,
                  {"op": "chunk+fold", "node_id": nid, "chunk_tokens": leaf.token_count,
                   "rolling_tokens": self.tok.count(rolling)}, t0)
        return leaf

    # ------------------------------------------------------------------ hierarchy
    def make_sections(self, session_id: str) -> list[SummaryNode]:
        created: list[SummaryNode] = []
        fan = self.s.section_fanout
        while True:
            leaves = self.nodes.unparented(session_id, 0)
            if len(leaves) < fan:
                return created
            group = leaves[:fan]
            nid = node_id_for(session_id, 1, group[0].first_message_id, group[-1].last_message_id)
            t0 = time.perf_counter()
            out, res = self.llm.structured(
                "section_summary", prompts.SECTION_SUMMARY,
                [ChatMessage(role="user", content="\n\n".join(f"[{i + 1}] {n.summary}" for i, n in enumerate(group)))],
                SectionOut, hints={"summaries": [n.summary for n in group]})
            sec = SummaryNode(
                node_id=nid, user_id=group[0].user_id, session_id=session_id, level=1,
                child_ids=[n.node_id for n in group], title=out.title.strip(), summary=out.summary.strip(),
                first_message_id=group[0].first_message_id, last_message_id=group[-1].last_message_id,
                first_seq=group[0].first_seq, last_seq=group[-1].last_seq, token_count=self.tok.count(out.summary),
                source_token_count=sum(n.source_token_count for n in group), model=res.model, created_at=utcnow())
            catch_all_ids = {n.parent_id for n in group if n.parent_level == 2}
            detach = self.nodes.list_session(session_id, 2)[0] if catch_all_ids else None
            try:
                self.nodes.commit_parent(sec, group, replace=False, detach_from=detach)
            except TxnConflict as e:
                log_event(log, "summarizer.section_conflict", node_id=nid, reasons=e.reasons)
                return created
            self._log(session_id, sec.user_id, [n.node_id for n in group], res,
                      {"op": "section", "node_id": nid, "title": sec.title}, t0)
            if self.on_section:
                try:
                    self.on_section(sec)
                except Exception as ex:  # noqa: BLE001 - indexing is best-effort; tree is the source of truth
                    log_event(log, "summarizer.section_index_failed", node_id=nid, error=type(ex).__name__)
            created.append(sec)

    def process(self, session_id: str) -> SummarizeReport:
        """Per-turn entry point: roll while over budget, then build any complete sections."""
        s = self.sessions.require(session_id)
        rep = SummarizeReport(buffer_tokens_before=sum(m.token_count for m in
                                                       self.sessions.messages_from(session_id, s.buffer_start_seq)))
        while (leaf := self.roll_once(session_id)) is not None:
            rep.leaves_created.append(leaf.node_id)
        rep.sections_created = [n.node_id for n in self.make_sections(session_id)]
        s = self.sessions.require(session_id)
        rep.buffer_tokens_after = sum(m.token_count for m in self.sessions.messages_from(session_id, s.buffer_start_seq))
        rep.rolling_summary_tokens = s.rolling_summary_tokens
        return rep

    def summarize_session(self, session_id: str, *, flush: bool = True) -> SummaryNode | None:
        """Level 2. flush=True (session end) folds the remaining buffer into leaves first."""
        if flush:
            while self.roll_once(session_id, finalize=True) is not None:
                pass
        self.make_sections(session_id)
        s = self.sessions.require(session_id)
        sections = self.nodes.list_session(session_id, 1)
        loose = self.nodes.unparented(session_id, 0)
        children = sorted(sections + loose, key=lambda n: n.first_seq)
        if not children:
            return None
        nid = session_node_id(session_id)
        prev = self.nodes.list_session(session_id, 2)
        prev_node = prev[0] if prev else None
        if prev_node and prev_node.child_ids == [c.node_id for c in children] \
                and prev_node.last_message_id == children[-1].last_message_id:
            return prev_node  # idempotent: nothing new since last time
        t0 = time.perf_counter()
        labels = [c.title or f"Chunk {c.first_seq}-{c.last_seq}" for c in children]
        res = self.llm.generate(
            "session_summary", prompts.SESSION_SUMMARY.format(max_tokens=SESSION_SUMMARY_MAX_TOKENS),
            [ChatMessage(role="user", content="\n\n".join(f"## {t}\n{c.summary}" for t, c in zip(labels, children)))],
            max_tokens=SESSION_SUMMARY_MAX_TOKENS,
            hints={"titles": labels, "summaries": [c.summary for c in children], "max_tokens": SESSION_SUMMARY_MAX_TOKENS})
        node = SummaryNode(
            node_id=nid, user_id=s.user_id, session_id=session_id, level=2, title=s.title,
            child_ids=[c.node_id for c in children], summary=res.text, first_message_id=children[0].first_message_id,
            last_message_id=children[-1].last_message_id, first_seq=children[0].first_seq,
            last_seq=children[-1].last_seq, token_count=self.tok.count(res.text),
            source_token_count=sum(c.source_token_count for c in children), model=res.model, created_at=utcnow(),
            version=(prev_node.version + 1) if prev_node else 1,
            parent_id=prev_node.parent_id if prev_node else None,
            parent_level=prev_node.parent_level if prev_node else None)
        self.nodes.commit_parent(node, children, replace=True)
        self._log(session_id, s.user_id, node.child_ids, res, {"op": "session", "node_id": nid}, t0)
        return node

    def end_session(self, session_id: str) -> SummaryNode | None:
        node = self.summarize_session(session_id, flush=True)
        self.sessions.mark_ended(session_id)
        return node

    def build_life_archive(self, user_id: str) -> SummaryNode | None:
        """Optional level 3 across all of a user's sessions."""
        l2s: list[SummaryNode] = []
        for sess in sorted(self.sessions.list_for_user(user_id), key=lambda x: x.created_at):
            l2s += self.nodes.list_session(sess.session_id, 2)
        if not l2s:
            return None
        t0 = time.perf_counter()
        res = self.llm.generate(
            "life_archive_summary", prompts.LIFE_ARCHIVE_SUMMARY.format(max_tokens=ARCHIVE_SUMMARY_MAX_TOKENS),
            [ChatMessage(role="user", content="\n\n".join(f"## {n.title}\n{n.summary}" for n in l2s))],
            max_tokens=ARCHIVE_SUMMARY_MAX_TOKENS,
            hints={"titles": [n.title for n in l2s], "summaries": [n.summary for n in l2s],
                   "max_tokens": ARCHIVE_SUMMARY_MAX_TOKENS})
        node = SummaryNode(
            node_id=archive_node_id(user_id), user_id=user_id, session_id=archive_session_id(user_id), level=3,
            title="Life archive", child_ids=[n.node_id for n in l2s], summary=res.text,
            first_message_id=l2s[0].first_message_id, last_message_id=l2s[-1].last_message_id,
            first_seq=0, last_seq=0, token_count=self.tok.count(res.text),
            source_token_count=sum(n.source_token_count for n in l2s), model=res.model, created_at=utcnow())
        self.nodes.commit_parent(node, l2s, replace=True)
        self._log(None, user_id, node.child_ids, res, {"op": "life_archive", "node_id": node.node_id}, t0)  # type: ignore[arg-type]
        return node
