"""Section summaries are embedded too, so the Context Assembler / Chapter Writer can retrieve them.
Vector store keeps id + vector + {user_id, type='section', created_at}; text is hydrated from the node table.
"""
from __future__ import annotations

import logging

from app.llm.embeddings import Embedder
from app.logging_setup import get_logger, log_event
from app.models.summary import SummaryNode
from app.repos.summary_nodes import SummaryNodeRepository
from app.vector.base import VectorFilter, VectorStore

log = get_logger(__name__)


class SectionIndex:
    def __init__(self, embedder: Embedder, store: VectorStore, nodes: SummaryNodeRepository):
        self.embedder, self.store, self.nodes = embedder, store, nodes

    def index(self, node: SummaryNode) -> None:
        vec = self.embedder.embed([f"{node.title}\n{node.summary}"])[0]
        self.store.upsert([node.node_id], [vec], [{"user_id": node.user_id, "type": "section",
                                                   "created_at": int(node.created_at.timestamp())}])

    def search(self, user_id: str, query: str, top_k: int = 3, min_similarity: float = 0.0
               ) -> list[tuple[SummaryNode, float]]:
        vec = self.embedder.embed([query])[0]
        out = []
        for h in self.store.query(vec, top_k, VectorFilter(user_id=user_id, types=["section"])):
            if h.similarity < min_similarity:
                continue
            n = self.nodes.get(h.id)
            if n is None:
                log_event(log, "section_index.orphan", logging.WARNING, node_id=h.id)
                continue
            out.append((n, h.similarity))
        return out
