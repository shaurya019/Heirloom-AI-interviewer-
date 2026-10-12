"""Continuity Checker: for each new memory, retrieve similar ones and flag date/name/place conflicts
as open questions for the Interviewer to clarify gently later."""
from __future__ import annotations

import hashlib

from app.agents import prompts
from app.agents.base import recorder
from app.config import Settings
from app.llm.chat import ChatMessage, LLMClient
from app.models.agents import ContinuityOutput, OpenQuestion
from app.models.memory import MemoryRecord, utcnow
from app.repos.agent_runs import AgentRunRepository
from app.repos.user_records import OpenQuestionRepository
from app.retrieval.hybrid import HybridRetriever, SearchFilters, SearchRequest, WeightOverrides

SIM_ONLY = WeightOverrides(w_sim=1.0, w_rec=0.0, w_imp=0.0)


def qid_for(a: str, b: str, field: str) -> str:
    x, y = sorted([a, b])
    return "q_" + hashlib.sha1(f"{x}|{y}|{field}".encode()).hexdigest()[:16]


def _fmt(m: MemoryRecord) -> str:
    yrs = f"{m.event_year_start}" if m.event_year_start == m.event_year_end else f"{m.event_year_start}–{m.event_year_end}"
    return f"[{m.memory_id}] ({yrs}) {m.text} | entities: {', '.join(m.entities)}"


class ContinuityChecker:
    def __init__(self, settings: Settings, llm: LLMClient, retriever: HybridRetriever,
                 questions: OpenQuestionRepository, runs: AgentRunRepository):
        self.s, self.llm, self.retriever, self.questions, self.runs = settings, llm, retriever, questions, runs

    def run(self, new_memories: list[MemoryRecord], session_id: str | None = None) -> list[OpenQuestion]:
        created: list[OpenQuestion] = []
        batch_ids = [m.memory_id for m in new_memories]
        for mem in new_memories:
            rec = recorder(self.runs, "continuity_checker", session_id or mem.session_id, mem.user_id)
            with rec.run():
                rec.input_ids = [mem.memory_id]
                resp = self.retriever.search(SearchRequest(
                    query=mem.text, weights=SIM_ONLY, top_k=self.s.continuity_top_k,
                    filters=SearchFilters(user_id=mem.user_id, exclude_ids=batch_ids)))
                cands = [r for r in resp.results if r.breakdown.similarity >= self.s.continuity_similarity_threshold]
                rec.input_ids += [r.memory.memory_id for r in cands]
                if not cands:
                    rec.output = {"candidates": 0, "contradictions": 0}
                    continue
                out, res = self.llm.structured(
                    "continuity", prompts.CONTINUITY,
                    [ChatMessage(role="user", content=f"NEW:\n{_fmt(mem)}\n\nEXISTING:\n"
                                 + "\n".join(_fmt(r.memory) for r in cands))],
                    ContinuityOutput,
                    hints={"new_memory": mem.model_dump(mode="json"),
                           "candidates": [r.memory.model_dump(mode="json") for r in cands]})
                rec.result = res
                allowed = {r.memory.memory_id for r in cands}
                new_qs = []
                for c in out.contradictions:
                    if c.existing_memory_id not in allowed:  # model hallucinated an id → ignore
                        continue
                    q = OpenQuestion(qid=qid_for(c.existing_memory_id, mem.memory_id, c.field), user_id=mem.user_id,
                                     session_id=session_id or mem.session_id,
                                     memory_ids=[c.existing_memory_id, mem.memory_id], field=c.field,
                                     existing_value=c.existing_value, new_value=c.new_value,
                                     explanation=c.explanation, question=c.question, created_at=utcnow())
                    if self.questions.add_if_new(q):
                        new_qs.append(q)
                created += new_qs
                rec.output = {"candidates": len(cands), "contradictions": len(out.contradictions),
                              "open_questions": [q.qid for q in new_qs]}
        return created
