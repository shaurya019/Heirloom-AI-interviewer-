"""VectorStore protocol. Stores hold ONLY id, vector, and filter metadata — never text.

Metadata schema (all backends): {"user_id": str, "type": str, "created_at": int (epoch seconds)}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, Sequence, runtime_checkable

ALLOWED_METADATA = frozenset({"user_id", "type", "created_at"})


class VectorHit(NamedTuple):
    id: str
    similarity: float           # cosine similarity in [-1, 1] as reported by the backend
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorFilter:
    user_id: str
    types: Sequence[str] | None = None
    created_at_gte: int | None = None
    created_at_lte: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # reserved; unused by built-in backends


def validate_metadata(md: dict[str, Any]) -> dict[str, Any]:
    unknown = set(md) - ALLOWED_METADATA
    if unknown:
        raise ValueError(f"vector metadata may only contain {sorted(ALLOWED_METADATA)}; got {sorted(unknown)}")
    if not isinstance(md.get("user_id"), str) or not md["user_id"]:
        raise ValueError("vector metadata requires user_id")
    if "created_at" in md and not isinstance(md["created_at"], int):
        raise ValueError("created_at must be an epoch int")
    return md


@runtime_checkable
class VectorStore(Protocol):
    backend: str
    dim: int

    def ensure_index(self) -> None:
        """Create the index/collection if missing; raise ConfigError on dimension mismatch."""

    def index_dimension(self) -> int | None: ...

    def upsert(self, ids: Sequence[str], vectors: Sequence[Sequence[float]],
               metadata: Sequence[dict[str, Any]]) -> None: ...

    def query(self, vector: Sequence[float], top_k: int, filters: VectorFilter) -> list[VectorHit]: ...

    def delete(self, ids: Sequence[str]) -> None: ...


def check_lengths(ids: Sequence[str], vectors: Sequence[Sequence[float]],
                  metadata: Sequence[dict[str, Any]], dim: int) -> None:
    if not (len(ids) == len(vectors) == len(metadata)):
        raise ValueError("ids, vectors, metadata must have equal length")
    for v in vectors:
        if len(v) != dim:
            raise ValueError(f"vector dim {len(v)} != index dim {dim}")
    for md in metadata:
        validate_metadata(md)
