"""Pinecone backend (serverless). Selected with VECTOR_BACKEND=pinecone."""
from __future__ import annotations

import logging
import time
from typing import Any, Sequence

from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from app.errors import ConfigError
from app.logging_setup import get_logger, log_event
from app.vector.base import VectorFilter, VectorHit, check_lengths

log = get_logger(__name__)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ValueError, TypeError, ConfigError)):
        return False
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or "timeout" in type(exc).__name__.lower()


class PineconeVectorStore:
    backend = "pinecone"

    def __init__(self, api_key: str, index_name: str, dim: int, namespace: str = "default",
                 cloud: str = "aws", region: str = "us-east-1", max_retries: int = 5):
        from pinecone import Pinecone

        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.dim = dim
        self.namespace = namespace
        self.cloud, self.region = cloud, region
        self._index: Any | None = None
        self._retry = retry(retry=retry_if_exception(_retryable),
                            wait=wait_random_exponential(multiplier=0.5, max=20),
                            stop=stop_after_attempt(max_retries + 1),
                            before_sleep=before_sleep_log(log, logging.WARNING), reraise=True)

    @property
    def index(self) -> Any:
        if self._index is None:
            self._index = self.pc.Index(self.index_name)
        return self._index

    def index_dimension(self) -> int | None:
        if not self.pc.has_index(self.index_name):
            return None
        return int(self.pc.describe_index(self.index_name).dimension)

    def ensure_index(self) -> None:
        from pinecone import ServerlessSpec

        existing = self.index_dimension()
        if existing is None:
            self.pc.create_index(name=self.index_name, dimension=self.dim, metric="cosine",
                                 spec=ServerlessSpec(cloud=self.cloud, region=self.region))
            for _ in range(60):
                if self.pc.describe_index(self.index_name).status.get("ready"):
                    break
                time.sleep(1)
            log_event(log, "pinecone.index_created", index=self.index_name, dim=self.dim)
        elif existing != self.dim:
            raise ConfigError(f"Pinecone index '{self.index_name}' has dim {existing} "
                              f"but EMBEDDING_DIM={self.dim}.")
        metric = getattr(self.pc.describe_index(self.index_name), "metric", "cosine")
        if metric != "cosine":
            raise ConfigError(f"Pinecone index '{self.index_name}' uses metric={metric}; cosine required")

    def upsert(self, ids: Sequence[str], vectors: Sequence[Sequence[float]],
               metadata: Sequence[dict[str, Any]]) -> None:
        check_lengths(ids, vectors, metadata, self.dim)
        rows = [{"id": i, "values": list(map(float, v)), "metadata": dict(m)}
                for i, v, m in zip(ids, vectors, metadata)]
        for k in range(0, len(rows), 100):
            self._retry(self.index.upsert)(vectors=rows[k:k + 100], namespace=self.namespace)

    @staticmethod
    def build_filter(f: VectorFilter) -> dict[str, Any]:
        clauses: list[dict[str, Any]] = [{"user_id": {"$eq": f.user_id}}]
        if f.types:
            clauses.append({"type": {"$in": list(f.types)}})
        rng: dict[str, int] = {}
        if f.created_at_gte is not None:
            rng["$gte"] = f.created_at_gte
        if f.created_at_lte is not None:
            rng["$lte"] = f.created_at_lte
        if rng:
            clauses.append({"created_at": rng})
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def query(self, vector: Sequence[float], top_k: int, filters: VectorFilter) -> list[VectorHit]:
        res = self._retry(self.index.query)(vector=list(map(float, vector)), top_k=top_k,
                                            filter=self.build_filter(filters), include_metadata=True,
                                            namespace=self.namespace)
        matches = res["matches"] if isinstance(res, dict) else res.matches
        out = []
        for m in matches:
            md = dict((m["metadata"] if isinstance(m, dict) else m.metadata) or {})
            if "created_at" in md:  # Pinecone returns numbers as floats
                md["created_at"] = int(md["created_at"])
            mid = m["id"] if isinstance(m, dict) else m.id
            score = m["score"] if isinstance(m, dict) else m.score
            out.append(VectorHit(mid, float(score), md))
        return out

    def delete(self, ids: Sequence[str]) -> None:
        for k in range(0, len(ids), 1000):
            self._retry(self.index.delete)(ids=list(ids[k:k + 1000]), namespace=self.namespace)
