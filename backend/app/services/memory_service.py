"""Vector memory (Technique 2): DynamoDB is the source of truth; the vector store is an index.

Write path : DynamoDB put (vector_status=pending, in sparse GSI3) -> embed -> vector upsert -> mark synced.
             Writing 'pending' first means a crash between the two stores is also recovered by the reconciler.
Delete path: DynamoDB delete -> vector delete. A failed vector delete leaves an orphan that hydration drops.
Read path  : vector query -> BatchGetItem -> join; orphan hits are logged and dropped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from ulid import ULID

from app.llm.embeddings import Embedder
from app.logging_setup import get_logger, log_event
from app.models.memory import MemoryCreate, MemoryRecord, utcnow
from app.repos.memories import MemoryRepository
from app.vector.base import VectorFilter, VectorHit, VectorStore

log = get_logger(__name__)


@dataclass
class HydratedHit:
    hit: VectorHit
    record: MemoryRecord


def vector_metadata(rec: MemoryRecord) -> dict[str, object]:
    return {"user_id": rec.user_id, "type": rec.type.value, "created_at": rec.created_epoch}


def embedding_text(rec: Any) -> str:
    """What we embed: the memory text plus its entities (helps name/place recall)."""
    return rec.text if not rec.entities else f"{rec.text}\nEntities: {', '.join(rec.entities)}"


class MemoryService:
    def __init__(self, repo: MemoryRepository, embedder: Embedder, store: VectorStore):
        self.repo = repo
        self.embedder = embedder
        self.store = store

    # ------------------------------------------------------------------ writes
    def create_many(self, items: Sequence[MemoryCreate]) -> list[MemoryRecord]:
        now = utcnow()
        recs = [MemoryRecord(**{**m.model_dump(), "created_at": m.created_at or now},
                             memory_id=str(ULID()), embedding_model=self.embedder.model,
                             vector_status="pending") for m in items]
        for r in recs:  # 1) source of truth first
            self.repo.put_new(r)
        try:            # 2) index
            vecs = self.embedder.embed([embedding_text(r) for r in recs])
            self.store.upsert([r.memory_id for r in recs], vecs, [vector_metadata(r) for r in recs])
        except Exception as e:  # noqa: BLE001 - records stay pending for the reconciler
            log_event(log, "memory.vector_upsert_failed", logging.WARNING, n=len(recs),
                      error=f"{type(e).__name__}: {e}"[:300])
            for r in recs:
                self.repo.mark_pending(r.memory_id, f"{type(e).__name__}: {e}")
            return recs
        for r in recs:  # 3) flip status (removes from sparse GSI3)
            self.repo.mark_synced(r.memory_id)
            r.vector_status = "synced"
        log_event(log, "memory.created", n=len(recs), ids=[r.memory_id for r in recs])
        return recs

    def create(self, item: MemoryCreate) -> MemoryRecord:
        return self.create_many([item])[0]

    def delete(self, memory_id: str) -> bool:
        old = self.repo.delete(memory_id)
        try:
            self.store.delete([memory_id])
        except Exception as e:  # noqa: BLE001
            log_event(log, "memory.vector_delete_failed", logging.WARNING, memory_id=memory_id,
                      error=type(e).__name__)
        return old is not None

    def reconcile_pending(self, limit: int = 200) -> dict[str, int]:
        pending = self.repo.list_pending(limit)
        if not pending:
            return {"pending": 0, "synced": 0, "failed": 0}
        try:
            vecs = self.embedder.embed([embedding_text(r) for r in pending])
            self.store.upsert([r.memory_id for r in pending], vecs, [vector_metadata(r) for r in pending])
        except Exception as e:  # noqa: BLE001
            log_event(log, "reconciler.failed", logging.WARNING, n=len(pending), error=type(e).__name__)
            return {"pending": len(pending), "synced": 0, "failed": len(pending)}
        for r in pending:
            self.repo.mark_synced(r.memory_id)
        log_event(log, "reconciler.synced", n=len(pending))
        return {"pending": len(pending), "synced": len(pending), "failed": 0}

    # ------------------------------------------------------------------ reads
    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.repo.get(memory_id)

    def hydrate(self, hits: Sequence[VectorHit]) -> list[HydratedHit]:
        if not hits:
            return []
        recs = self.repo.batch_get([h.id for h in hits])
        out, orphans = [], []
        for h in hits:
            r = recs.get(h.id)
            if r is None:
                orphans.append(h.id)
            else:
                out.append(HydratedHit(h, r))
        if orphans:
            log_event(log, "memory.orphan_hits_dropped", logging.WARNING, ids=orphans)
        return out

    def search_vectors(self, query: str, filters: VectorFilter, top_k: int) -> list[HydratedHit]:
        vec = self.embedder.embed([query])[0]
        return self.hydrate(self.store.query(vec, top_k, filters))
