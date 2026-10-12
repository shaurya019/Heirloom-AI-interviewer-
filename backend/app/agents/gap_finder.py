"""Gap Finder: event-year coverage + theme coverage → under-covered periods and next topics."""
from __future__ import annotations

from collections import Counter

from app.agents import prompts
from app.agents.base import recorder
from app.config import Settings
from app.llm.chat import ChatMessage, LLMClient
from app.models.agents import GapReport, GapSuggestions, YearGap
from app.models.memory import MemoryRecord
from app.repos.agent_runs import AgentRunRepository
from app.repos.memories import MemoryRepository
from app.repos.sessions import UserRepository
from app.services.themes import theme_counts


MAX_COVERAGE_SPAN = 10  # a memory spanning decades ("Eddie, 1958–2003") is background, not coverage


def year_coverage(mems: list[MemoryRecord]) -> Counter[int]:
    cov: Counter[int] = Counter()
    for m in mems:
        if m.event_year_start is None:
            continue
        if (m.event_year_end or m.event_year_start) - m.event_year_start + 1 > MAX_COVERAGE_SPAN:
            continue
        for y in range(m.event_year_start, (m.event_year_end or m.event_year_start) + 1):
            cov[y] += 1
    return cov


def find_gaps(cov: Counter[int], start: int, end: int, min_years: int) -> list[YearGap]:
    gaps, run_start = [], None
    for y in range(start, end + 2):
        empty = y <= end and cov.get(y, 0) == 0
        if empty and run_start is None:
            run_start = y
        elif not empty and run_start is not None:
            if y - run_start >= min_years:
                gaps.append(YearGap(start=run_start, end=y - 1, years=y - run_start))
            run_start = None
    return sorted(gaps, key=lambda g: -g.years)


class GapFinder:
    def __init__(self, settings: Settings, llm: LLMClient, memories: MemoryRepository, users: UserRepository,
                 runs: AgentRunRepository):
        self.s, self.llm, self.memories, self.users, self.runs = settings, llm, memories, users, runs

    def analyze(self, user_id: str) -> GapReport:
        user = self.users.require(user_id)
        mems = self.memories.list_by_user(user_id)
        rec = recorder(self.runs, "gap_finder", None, user_id)
        with rec.run():
            rec.input_ids = [m.memory_id for m in mems][:200]
            cov = year_coverage(mems)
            years = sorted(cov)
            start = user.birth_year or (years[0] if years else None)
            end = years[-1] if years else None
            gaps = find_gaps(cov, start, end, self.s.gap_min_years) if start and end else []
            themes = theme_counts([m.text for m in mems])
            thin = [t for t, n in sorted(themes.items(), key=lambda kv: kv[1]) if n <= 1]
            ents = Counter(e for m in mems for e in m.entities).most_common(10)
            out, res = self.llm.structured(
                "gap_suggestions", prompts.GAP_SUGGESTIONS,
                [ChatMessage(role="user", content=f"Narrator: {user.name} (born {user.birth_year}).\n"
                             f"Gaps: {[g.model_dump() for g in gaps]}\nThin themes: {thin}\n"
                             f"Well covered: {[t for t, n in themes.most_common(4)]}")],
                GapSuggestions, hints={"gaps": [g.model_dump() for g in gaps], "thin_themes": thin})
            rec.result = res
            report = GapReport(user_id=user_id, span_start=start, span_end=end,
                               year_coverage=dict(sorted(cov.items())), gaps=gaps, theme_counts=dict(themes),
                               type_counts=dict(Counter(m.type.value for m in mems)), thin_themes=thin,
                               top_entities=ents, suggestions=out.suggestions, memory_count=len(mems))
            rec.output = {"gaps": [g.model_dump() for g in gaps], "suggestions": len(out.suggestions)}
        return report
