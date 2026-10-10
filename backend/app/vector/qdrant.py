"""Qdrant backend (default). QDRANT_URL=":memory:" runs embedded, otherwise HTTP."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.errors import ConfigError
from app.logging_setup import get_logger, log_event
from app.vector.base import VectorFilter, VectorHit, check_lengths

log = get_logger(__name__)
_NS = uuid.UUID("6f1b8f0e-8e43-4b4e-9b1c-6c1f6d0a7e11")


def point_id(id_: str) -> str:
    """Qdrant needs UUID/int ids; map arbitrary string ids deterministically."""
    return str(uuid.uuid5(_NS, id_))


class QdrantVectorStore:
    backend = "qdrant"

    def __init__(self, url: str, collection: str, dim: int, api_key: str | None = None,
                 client: Any | None = None):
        from qdrant_client import QdrantClient

        self.collection = collection
        self.dim = dim
        self.embedded = url == ":memory:"
        if client is not None:
            self.client = client
        elif url == ":memory:":
            self.client = QdrantClient(":memory:")
        else:
            self.client = QdrantClient(url=url, api_key=api_key, timeout=15)
        self._retry = retry(retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
                            wait=wait_random_exponential(multiplier=0.3, max=10), stop=stop_after_attempt(5),
                            before_sleep=before_sleep_log(log, logging.WARNING), reraise=True)

    def index_dimension(self) -> int | None:
        if not self.client.collection_exists(self.collection):
            return None
        vecs = self.client.get_collection(self.collection).config.params.vectors
        return int(vecs.size)  # type: ignore[union-attr]

    def ensure_index(self) -> None:
        from qdrant_client import models

        existing = self.index_dimension()
        if existing is None:
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE))
            indexes = [("user_id", models.PayloadSchemaType.KEYWORD),
                       ("type", models.PayloadSchemaType.KEYWORD),
                       ("created_at", models.PayloadSchemaType.INTEGER)]
            for field, schema in ([] if self.embedded else indexes):  # embedded mode ignores them
                self.client.create_payload_index(self.collection, field, field_schema=schema)
            log_event(log, "qdrant.collection_created", collection=self.collection, dim=self.dim)
        elif existing != self.dim:
            raise ConfigError(f"Qdrant collection '{self.collection}' has dim {existing} "
                              f"but EMBEDDING_DIM={self.dim}. Recreate the collection or fix config.")

    def upsert(self, ids: Sequence[str], vectors: Sequence[Sequence[float]],
               metadata: Sequence[dict[str, Any]]) -> None:
        from qdrant_client import models

        check_lengths(ids, vectors, metadata, self.dim)
        points = [models.PointStruct(id=point_id(i), vector=list(map(float, v)), payload={**m, "id": i})
                  for i, v, m in zip(ids, vectors, metadata)]
        for k in range(0, len(points), 256):
            self._retry(self.client.upsert)(self.collection, points=points[k:k + 256], wait=True)

    def _filter(self, f: VectorFilter) -> Any:
        from qdrant_client import models

        must: list[Any] = [models.FieldCondition(key="user_id", match=models.MatchValue(value=f.user_id))]
        if f.types:
            must.append(models.FieldCondition(key="type", match=models.MatchAny(any=list(f.types))))
        if f.created_at_gte is not None or f.created_at_lte is not None:
            must.append(models.FieldCondition(key="created_at", range=models.Range(
                gte=f.created_at_gte, lte=f.created_at_lte)))
        return models.Filter(must=must)

    def query(self, vector: Sequence[float], top_k: int, filters: VectorFilter) -> list[VectorHit]:
        res = self._retry(self.client.query_points)(
            self.collection, query=list(map(float, vector)), limit=top_k,
            query_filter=self._filter(filters), with_payload=True)
        out = []
        for p in res.points:
            payload = dict(p.payload or {})
            orig = payload.pop("id", None)
            if orig is None:
                continue
            out.append(VectorHit(orig, float(p.score), payload))
        return out

    def delete(self, ids: Sequence[str]) -> None:
        from qdrant_client import models

        if ids:
            self._retry(self.client.delete)(
                self.collection, points_selector=models.PointIdsList(points=[point_id(i) for i in ids]), wait=True)
