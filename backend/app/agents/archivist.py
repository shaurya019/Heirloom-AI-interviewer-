"""Archivist: after every user turn, extract atomic memories and persist them (DynamoDB → vector)."""
from __future__ import annotations

from app.agents import prompts
from app.agents.base import recorder
from app.config import Settings
from app.llm.chat import ChatMessage, LLMClient
from app.logging_setup import get_logger, log_event
from app.models.agents import ArchivistOutput
from app.models.memory import MemoryCreate, MemoryRecord
from app.models.session import Message
from app.repos.agent_runs import AgentRunRepository
from app.repos.sessions import UserRepository
from app.retrieval.hybrid import HybridRetriever, SearchFilters, SearchRequest
from app.services.memory_service import MemoryService, embedding_text
from app.vector.base import VectorFilter

log = get_logger(__name__)
DUPLICATE_SIMILARITY = 0.97


class Archivist:
    def __init__(self, settings: Settings, llm: LLMClient, memories: MemoryService, retriever: HybridRetriever,
                 users: UserRepository, runs: AgentRunRepository):
        self.s, self.llm, self.memories, self.retriever, self.users, self.runs = (
            settings, llm, memories, retriever, users, runs)

    def run(self, user_msg: Message, prev_question: str | None) -> list[MemoryRecord]:
        user = self.users.get(user_msg.user_id)
        narrator = user.name if user else "the narrator"
        rec = recorder(self.runs, "archivist", user_msg.session_id, user_msg.user_id)
        with rec.run():
            rec.input_ids = [user_msg.message_id]
            known = self.retriever.search(SearchRequest(query=user_msg.content, top_k=5,
                                                        filters=SearchFilters(user_id=user_msg.user_id)))
            known_txt = "\n".join(f"- {r.memory.text}" for r in known.results) or "(none)"
            out, res = self.llm.structured(
                "archivist",
                prompts.ARCHIVIST.format(narrator=narrator, birth_year=user.birth_year if user else "unknown"),
                [ChatMessage(role="user", content=f"INTERVIEWER: {prev_question or '(opening)'}\n"
                                                  f"NARRATOR: {user_msg.content}\n\nKNOWN MEMORIES:\n{known_txt}")],
                ArchivistOutput,
                hints={"user_message": user_msg.content, "narrator": narrator.split()[0]})
            rec.result = res
            candidates = [m for m in out.memories if m.importance >= self.s.archivist_min_importance]
            fresh = self._dedupe(user_msg.user_id, candidates)
            created = self.memories.create_many([MemoryCreate(**m.model_dump(), user_id=user_msg.user_id,
                                                              session_id=user_msg.session_id,
                                                              source_message_ids=[user_msg.message_id])
                                                 for m in fresh]) if fresh else []
            rec.output = {"extracted": len(out.memories), "kept": len(created),
                          "memory_ids": [m.memory_id for m in created],
                          "memories": [{"type": m.type.value, "text": m.text, "years": [m.event_year_start,
                                                                                         m.event_year_end],
                                        "importance": m.importance} for m in created]}
        log_event(log, "archivist.done", extracted=len(out.memories), kept=len(created))
        return created

    def _dedupe(self, user_id: str, cands: list) -> list:  # type: ignore[type-arg]
        if not cands:
            return []
        # embed exactly what the index stores (text + entities), or similarities aren't comparable
        vecs = self.memories.embedder.embed([embedding_text(m) for m in cands])
        kept, kept_vecs = [], []
        for m, v in zip(cands, vecs):
            hits = self.memories.store.query(v, 1, VectorFilter(user_id=user_id))
            if hits and hits[0].similarity >= DUPLICATE_SIMILARITY:
                continue
            if any(sum(a * b for a, b in zip(v, kv)) >= DUPLICATE_SIMILARITY for kv in kept_vecs):
                continue
            kept.append(m)
            kept_vecs.append(v)
        return kept
