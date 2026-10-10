"""Hybrid semantic retrieval (Technique 3).

1. over-fetch CANDIDATE_MULTIPLIER × top_k from the vector store with user/type/created_at pushed down
2. hydrate from DynamoDB (orphans dropped)
3. apply event-year filter (event years live only in DynamoDB, so this filter is post-hydration;
   when it is set we over-fetch 2× more to compensate)
4. rescore with the pure hybrid formula, drop < min_score, return top_k with full breakdowns
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.config import Settings
from app.logging_setup import get_logger, log_event
from app.models.memory import MemoryRecord, MemoryType, utcnow
from app.retrieval.scoring import ScoreBreakdown, Weights, hybrid_score
from app.services.memory_service import MemoryService
from app.vector.base import VectorFilter

log = get_logger(__name__)


class SearchFilters(BaseModel):
    user_id: str = Field(min_length=1)
    types: list[MemoryType] | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    event_year_from: int | None = None
    event_year_to: int | None = None
    exclude_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ranges(self) -> "SearchFilters":
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must be <= created_to")
        if (self.event_year_from is not None and self.event_year_to is not None
                and self.event_year_from > self.event_year_to):
            raise ValueError("event_year_from must be <= event_year_to")
        return self

    def has_event_year(self) -> bool:
        return self.event_year_from is not None or self.event_year_to is not None

    def to_vector_filter(self) -> VectorFilter:
        return VectorFilter(
            user_id=self.user_id, types=[t.value for t in self.types] if self.types else None,
            created_at_gte=int(self.created_from.timestamp()) if self.created_from else None,
            created_at_lte=int(self.created_to.timestamp()) if self.created_to else None)

    def matches_event_year(self, r: MemoryRecord) -> bool:
        if not self.has_event_year():
            return True
        if r.event_year_start is None:
            return False
        lo = self.event_year_from if self.event_year_from is not None else -10_000
        hi = self.event_year_to if self.event_year_to is not None else 10_000
        return r.event_year_start <= hi and (r.event_year_end or r.event_year_start) >= lo  # overlap


class WeightOverrides(BaseModel):
    w_sim: float | None = Field(None, ge=0)
    w_rec: float | None = Field(None, ge=0)
    w_imp: float | None = Field(None, ge=0)
    decay: float | None = Field(None, ge=0)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    filters: SearchFilters
    weights: WeightOverrides | None = None
    top_k: int | None = Field(None, ge=1, le=200)
    min_score: float | None = Field(None, ge=0, le=10)


class SearchResult(BaseModel):
    rank: int
    memory: MemoryRecord
    breakdown: ScoreBreakdown


class SearchStats(BaseModel):
    candidates_requested: int
    candidates_returned: int
    hydrated: int
    after_filters: int
    above_min_score: int


class SearchResponse(BaseModel):
    query: str
    weights: Weights
    top_k: int
    min_score: float
    results: list[SearchResult]
    stats: SearchStats


class HybridRetriever:
    def __init__(self, memories: MemoryService, settings: Settings):
        self.memories = memories
        self.settings = settings

    def resolve_weights(self, o: WeightOverrides | None) -> Weights:
        s = self.settings
        base = Weights(w_sim=s.w_sim, w_rec=s.w_rec, w_imp=s.w_imp, decay=s.decay)
        if not o:
            return base
        w = base.model_copy(update={k: v for k, v in o.model_dump().items() if v is not None})
        if w.w_sim + w.w_rec + w.w_imp <= 0:
            raise ValueError("at least one weight must be > 0")
        return w

    def search(self, req: SearchRequest, now: datetime | None = None) -> SearchResponse:
        now = now or utcnow()
        weights = self.resolve_weights(req.weights)
        top_k = req.top_k or self.settings.default_top_k
        min_score = self.settings.default_min_score if req.min_score is None else req.min_score
        mult = self.settings.candidate_multiplier * (2 if req.filters.has_event_year() else 1)
        n_cand = top_k * mult + len(req.filters.exclude_ids)

        qvec = self.memories.embedder.embed([req.query])[0]
        hits = self.memories.store.query(qvec, n_cand, req.filters.to_vector_filter())
        joined = self.memories.hydrate(hits)
        excluded = set(req.filters.exclude_ids)
        kept = [j for j in joined if j.record.memory_id not in excluded and req.filters.matches_event_year(j.record)]
        scored = [(j.record, hybrid_score(j.hit.similarity, j.record.created_at, j.record.importance, now, weights))
                  for j in kept]
        above = [(r, b) for r, b in scored if b.final_score >= min_score]
        above.sort(key=lambda rb: (-rb[1].final_score, -rb[1].similarity, rb[0].memory_id))
        results = [SearchResult(rank=i + 1, memory=r, breakdown=b) for i, (r, b) in enumerate(above[:top_k])]
        stats = SearchStats(candidates_requested=n_cand, candidates_returned=len(hits), hydrated=len(joined),
                            after_filters=len(kept), above_min_score=len(above))
        log_event(log, "retrieval.hybrid", user_id=req.filters.user_id, top_k=top_k, **stats.model_dump())
        return SearchResponse(query=req.query, weights=weights, top_k=top_k, min_score=min_score,
                              results=results, stats=stats)
