"""Chapter Writer: section summaries + top hybrid memories → memoir chapter with inline [m:<id>] citations."""
from __future__ import annotations

import re

from ulid import ULID

from app.agents import prompts
from app.agents.base import recorder
from app.config import Settings
from app.llm.chat import ChatMessage, LLMClient
from app.models.agents import Chapter, ChapterRequest
from app.models.memory import utcnow
from app.repos.agent_runs import AgentRunRepository
from app.repos.user_records import ChapterRepository
from app.retrieval.hybrid import HybridRetriever, SearchFilters, SearchRequest, WeightOverrides
from app.services.section_index import SectionIndex

CITE_RE = re.compile(r"\[m:([A-Za-z0-9]+)\]")
# chapters are about the story, not about when it was told: no recency weight
CHAPTER_WEIGHTS = WeightOverrides(w_sim=0.7, w_rec=0.0, w_imp=0.3)


def validate_citations(markdown: str, allowed: set[str]) -> tuple[str, list[str], int]:
    """Strip citations to ids that weren't provided; return (markdown, ordered valid ids, removed count)."""
    removed = 0
    seen: list[str] = []

    def sub(m: re.Match[str]) -> str:
        nonlocal removed
        if m.group(1) in allowed:
            if m.group(1) not in seen:
                seen.append(m.group(1))
            return m.group(0)
        removed += 1
        return ""

    cleaned = CITE_RE.sub(sub, markdown)
    return re.sub(r"[ \t]+([.,;])", r"\1", cleaned), seen, removed


class ChapterWriter:
    def __init__(self, settings: Settings, llm: LLMClient, retriever: HybridRetriever, sections: SectionIndex,
                 chapters: ChapterRepository, runs: AgentRunRepository):
        self.s, self.llm, self.retriever, self.sections, self.chapters, self.runs = (
            settings, llm, retriever, sections, chapters, runs)

    def write(self, user_id: str, req: ChapterRequest) -> Chapter:
        era = (f"{req.era_start or '…'}–{req.era_end or '…'}" if (req.era_start or req.era_end) else "")
        title = req.title or (f"{req.theme}" + (f", {era}" if era else "") if req.theme else f"The years {era}")
        query = req.theme or f"life events between {req.era_start} and {req.era_end}"
        rec = recorder(self.runs, "chapter_writer", None, user_id)
        with rec.run():
            resp = self.retriever.search(SearchRequest(
                query=query, top_k=req.top_k, weights=CHAPTER_WEIGHTS,
                filters=SearchFilters(user_id=user_id, event_year_from=req.era_start, event_year_to=req.era_end)))
            mems = [r.memory for r in resp.results]
            secs = [n for n, _ in self.sections.search(user_id, query, top_k=3)]
            rec.input_ids = [m.memory_id for m in mems] + [n.node_id for n in secs]
            ctx = "SECTION SUMMARIES:\n" + "\n".join(f"- {n.title}: {n.summary}" for n in secs) + \
                  "\n\nMEMORIES:\n" + "\n".join(f"[m:{m.memory_id}] ({m.event_year_start}) {m.text}" for m in mems)
            res = self.llm.generate(
                "chapter", prompts.CHAPTER.format(title=title), [ChatMessage(role="user", content=ctx)],
                max_tokens=1800, hints={"title": title, "memories": [m.model_dump(mode="json") for m in mems],
                                        "section_summaries": [n.summary for n in secs]})
            rec.result = res
            md, cited, removed = validate_citations(res.text, {m.memory_id for m in mems})
            by_id = {m.memory_id: m for m in mems}
            ch = Chapter(chapter_id=str(ULID()), user_id=user_id, title=title, request=req, markdown=md,
                         citations=cited, cited_memories=[by_id[i] for i in cited],
                         section_ids=[n.node_id for n in secs], invalid_citations_removed=removed, model=res.model,
                         created_at=utcnow())
            self.chapters.add(ch)
            rec.output = {"chapter_id": ch.chapter_id, "title": title, "citations": len(cited),
                          "invalid_removed": removed}
        return ch
