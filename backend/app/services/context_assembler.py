"""Context Assembler — builds every Interviewer prompt under CONTEXT_BUDGET_TOKENS.

Slots, highest priority first, each with its own budget (settings.slot_budgets):
  1 system            interviewer rules + under-covered periods + QUESTIONS ALREADY ASKED
  2 session_summary   life-archive (L3) or previous sessions' L2 summaries, plus this session's L2 if any
  3 section_summaries L1 sections retrieved semantically for the current turn
  4 rolling_summary   this session's running summary
  5 memories          top-k hybrid memories (excluding ones sourced from messages already in the buffer)
  6 open_questions    unresolved contradictions to clarify gently
  7 recent_messages   verbatim buffer (newest kept first)

Step 1 fills each slot up to its own budget. Step 2, if the total still exceeds the global budget,
trims from the LOWEST-priority slot upward. The newest user message is never dropped (only truncated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.agents import prompts
from app.agents.gap_finder import find_gaps, year_coverage
from app.config import Settings
from app.llm.chat import ChatMessage
from app.models.agents import OpenQuestion
from app.models.memory import MemoryRecord
from app.models.session import Message, Session
from app.repos.memories import MemoryRepository
from app.repos.sessions import SessionRepository, UserRepository
from app.repos.summary_nodes import SummaryNodeRepository, archive_session_id
from app.repos.user_records import OpenQuestionRepository
from app.retrieval.hybrid import HybridRetriever, SearchFilters, SearchRequest
from app.services.question_ledger import QuestionLedger
from app.services.section_index import SectionIndex
from app.tokens import get_counter

SLOT_ORDER = ["system", "session_summary", "section_summaries", "rolling_summary", "memories", "open_questions",
              "recent_messages"]
HEADERS = {"system": "", "session_summary": "## PREVIOUS SESSIONS / LIFE SUMMARY",
           "section_summaries": "## RELEVANT SECTIONS", "rolling_summary": "## THIS SESSION SO FAR",
           "memories": "## RELEVANT MEMORIES", "open_questions": "## OPEN QUESTIONS (clarify gently, one at a time)",
           "recent_messages": ""}


class SlotItemView(BaseModel):
    id: str | None
    tokens: int
    text: str


class ContextSlot(BaseModel):
    name: str
    priority: int
    budget: int
    tokens: int
    included_ids: list[str]
    dropped_ids: list[str] = Field(default_factory=list)
    truncated: bool = False
    trimmed_by_global_budget: bool = False
    items: list[SlotItemView]


class ContextPreview(BaseModel):
    session_id: str
    user_id: str
    query: str
    budget: int
    total_tokens: int
    tokens_before_global_trim: int
    slots: list[ContextSlot]


@dataclass
class _Item:
    id: str | None
    text: str
    mandatory: bool = False
    payload: Any = None


@dataclass
class _Slot:
    name: str
    budget: int
    items: list[_Item]
    keep_newest: bool = False          # recent messages: drop OLDEST first
    included: list[_Item] = field(default_factory=list)
    dropped: list[_Item] = field(default_factory=list)
    truncated: bool = False
    global_trim: bool = False


@dataclass
class AssembledContext:
    preview: ContextPreview
    system_prompt: str
    messages: list[ChatMessage]
    hints: dict[str, Any]


class ContextAssembler:
    def __init__(self, settings: Settings, sessions: SessionRepository, users: UserRepository,
                 nodes: SummaryNodeRepository, sections: SectionIndex, retriever: HybridRetriever,
                 memories: MemoryRepository, questions: OpenQuestionRepository, ledger: QuestionLedger):
        self.s = settings
        self.sessions, self.users, self.nodes, self.sections = sessions, users, nodes, sections
        self.retriever, self.memories, self.questions, self.ledger = retriever, memories, questions, ledger
        self.tok = get_counter(settings.openai_chat_model)

    # ------------------------------------------------------------------ rendering / counting
    def _render(self, slot: _Slot, items: list[_Item]) -> str:
        if not items:
            return ""
        body = "\n".join(i.text for i in items)
        h = HEADERS[slot.name]
        return f"{h}\n{body}" if h else body

    def _tokens(self, slot: _Slot, items: list[_Item]) -> int:
        if slot.name == "recent_messages":  # chat turns: +4/message formatting overhead
            return sum(self.tok.count(i.text) + 4 for i in items)
        return self.tok.count(self._render(slot, items))

    def _fill(self, slot: _Slot) -> None:
        order = list(reversed(slot.items)) if slot.keep_newest else list(slot.items)
        inc: list[_Item] = []
        for it in order:
            if self._tokens(slot, inc + [it]) <= slot.budget:
                inc.append(it)
            elif it.mandatory or (not inc and len(slot.items) == 1):
                room = slot.budget - self._tokens(slot, inc) - 8
                it = _Item(it.id, self.tok.truncate(it.text, max(16, room)), it.mandatory, it.payload)
                inc.append(it)
                slot.truncated = True
            else:
                slot.dropped.append(it)
        slot.included = list(reversed(inc)) if slot.keep_newest else inc

    def _trim_global(self, slots: dict[str, _Slot]) -> None:
        def total() -> int:
            return sum(self._tokens(sl, sl.included) for sl in slots.values())

        for name in reversed(SLOT_ORDER):
            sl = slots[name]
            while total() > self.s.context_budget_tokens and sl.included:
                victims = [i for i in sl.included if not i.mandatory]
                if not victims:  # only mandatory content left: truncate it, then move on
                    over = total() - self.s.context_budget_tokens
                    it = sl.included[-1]
                    new_len = max(16, self.tok.count(it.text) - over - 4)
                    if new_len >= self.tok.count(it.text):
                        break
                    sl.included[-1] = _Item(it.id, self.tok.truncate(it.text, new_len), True, it.payload)
                    sl.truncated = sl.global_trim = True
                    break
                victim = victims[0] if sl.keep_newest else victims[-1]  # oldest msg / lowest-ranked item
                sl.included.remove(victim)
                sl.dropped.append(victim)
                sl.global_trim = True
            if total() <= self.s.context_budget_tokens:
                return

    # ------------------------------------------------------------------ slot sources
    def _system_items(self, s: Session, narrator: str, query: str, mems: list[MemoryRecord]) -> tuple[list[_Item], list[str], list[str]]:
        items = [_Item("system_prompt", prompts.INTERVIEWER.format(narrator=narrator), mandatory=True)]
        user = self.users.get(s.user_id)
        cov = year_coverage(mems)
        gaps = []
        if cov:
            start = (user.birth_year if user and user.birth_year else min(cov))
            gaps = find_gaps(cov, start, max(cov), self.s.gap_min_years)[:3]
        gap_qs = [f"We haven't talked about {g.start}–{g.end} yet. What was happening in your life then?" for g in gaps]
        if gaps:
            items.append(_Item("gaps", "UNDER-COVERED PERIODS: " + ", ".join(f"{g.start}–{g.end}" for g in gaps)))
        asked = self.ledger.relevant(s.user_id, query, k=6)
        if asked:
            items.append(_Item("asked_header", "QUESTIONS ALREADY ASKED (never repeat these):"))
            items += [_Item(q.qid, f"- {q.text}", payload=q.text) for q in asked]
        return items, gap_qs, [q.text for q in asked]

    def _session_summary_items(self, s: Session) -> list[_Item]:
        items: list[_Item] = []
        archive = self.nodes.list_session(archive_session_id(s.user_id), 3)
        if archive:
            items.append(_Item(archive[0].node_id, f"Life archive: {archive[0].summary}", payload=archive[0]))
        else:
            prev = sorted([x for x in self.sessions.list_for_user(s.user_id) if x.session_id != s.session_id],
                          key=lambda x: x.created_at, reverse=True)
            for p in prev:
                for n in self.nodes.list_session(p.session_id, 2):
                    when = p.created_at.strftime("%Y-%m-%d")
                    items.append(_Item(n.node_id, f"[{when}] {n.title}: {n.summary}", payload=n))
        for n in self.nodes.list_session(s.session_id, 2):
            items.append(_Item(n.node_id, f"Earlier in this session: {n.summary}", payload=n))
        return items

    # ------------------------------------------------------------------ main
    def assemble(self, session_id: str, query: str | None = None) -> AssembledContext:
        s = self.sessions.require(session_id)
        user = self.users.get(s.user_id)
        narrator = user.name if user else "the narrator"
        buffer: list[Message] = self.sessions.messages_from(session_id, s.buffer_start_seq)
        if query is None:
            last_user = next((m for m in reversed(buffer) if m.role == "user"), None)
            query = last_user.content if last_user else (s.rolling_summary[-500:] or "life story")
        buffer_ids = {m.message_id for m in buffer}
        all_mems = self.memories.list_by_user(s.user_id)

        # Over-fetch, THEN drop memories already present verbatim in the buffer, THEN cut to top_k.
        # (Filtering after a plain top_k fetch starves the slot when the buffer is long.)
        k = self.s.default_top_k
        resp = self.retriever.search(SearchRequest(query=query, filters=SearchFilters(user_id=s.user_id),
                                                   top_k=min(200, k + 3 * len(buffer_ids))))
        mems = [r for r in resp.results if not (set(r.memory.source_message_ids) & buffer_ids)][:k]
        sys_items, gap_qs, asked_texts = self._system_items(s, narrator, query, all_mems)
        oqs: list[OpenQuestion] = self.questions.list(s.user_id, "open")
        b = self.s.slot_budgets
        slots = {
            "system": _Slot("system", b["system"], sys_items),
            "session_summary": _Slot("session_summary", b["session_summary"], self._session_summary_items(s)),
            "section_summaries": _Slot("section_summaries", b["section_summaries"], [
                _Item(n.node_id, f"- {n.title}: {n.summary}", payload=n)
                for n, _ in self.sections.search(s.user_id, query, top_k=3, min_similarity=0.05)]),
            "rolling_summary": _Slot("rolling_summary", b["rolling_summary"],
                                     [_Item("rolling", s.rolling_summary)] if s.rolling_summary else []),
            "memories": _Slot("memories", b["memories"], [
                _Item(r.memory.memory_id, f"- [m:{r.memory.memory_id}] ({r.memory.event_year_start or '?'}) "
                                          f"{r.memory.text}", payload=r.memory) for r in mems]),
            "open_questions": _Slot("open_questions", b["open_questions"], [
                _Item(q.qid, f"- {q.question} (context: {q.explanation})", payload=q) for q in oqs]),
            "recent_messages": _Slot("recent_messages", b["recent_messages"], [
                _Item(m.message_id, m.content, mandatory=(m is buffer[-1]), payload=m) for m in buffer],
                keep_newest=True),
        }
        for sl in slots.values():
            self._fill(sl)
        before = sum(self._tokens(sl, sl.included) for sl in slots.values())
        if before > self.s.context_budget_tokens:
            self._trim_global(slots)

        views = []
        for i, name in enumerate(SLOT_ORDER, 1):
            sl = slots[name]
            views.append(ContextSlot(
                name=name, priority=i, budget=sl.budget, tokens=self._tokens(sl, sl.included),
                included_ids=[x.id for x in sl.included if x.id], dropped_ids=[x.id for x in sl.dropped if x.id],
                truncated=sl.truncated, trimmed_by_global_budget=sl.global_trim,
                items=[SlotItemView(id=x.id, tokens=self.tok.count(x.text), text=x.text) for x in sl.included]))
        preview = ContextPreview(session_id=session_id, user_id=s.user_id, query=query,
                                 budget=self.s.context_budget_tokens, total_tokens=sum(v.tokens for v in views),
                                 tokens_before_global_trim=before, slots=views)

        system_prompt = "\n\n".join(t for t in (self._render(slots[n], slots[n].included) for n in SLOT_ORDER[:-1]) if t)
        chat = [ChatMessage(role=x.payload.role, content=x.text) for x in slots["recent_messages"].included]
        inc_mems = [x.payload for x in slots["memories"].included]
        earlier = next((m for m in inc_mems if m.session_id not in (session_id,)), None)
        hints = {
            "open_questions": [x.payload.question for x in slots["open_questions"].included],
            "open_question_ids": [x.id for x in slots["open_questions"].included],
            "recent_memories": [m.model_dump(mode="json") for m in inc_mems],
            "gap_questions": gap_qs, "asked_questions": asked_texts + self.ledger.recent_texts(s.user_id),
            "earlier_memory": earlier.text if earlier else None, "narrator": narrator,
        }
        return AssembledContext(preview=preview, system_prompt=system_prompt, messages=chat, hints=hints)


AssemblerFactory = Callable[[], ContextAssembler]
