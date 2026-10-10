from __future__ import annotations

from app.config import Settings
from app.vector.base import VectorStore


def build_vector_store(settings: Settings, kind: str = "memories") -> VectorStore:
    """kind: 'memories' | 'sections' | 'questions' — separate collections/namespaces, same dim."""
    if settings.vector_backend == "pinecone":
        from app.vector.pinecone_store import PineconeVectorStore

        assert settings.pinecone_api_key is not None
        return PineconeVectorStore(settings.pinecone_api_key.get_secret_value(), settings.pinecone_index,
                                   settings.embedding_dim, namespace=f"{settings.pinecone_namespace}-{kind}",
                                   cloud=settings.pinecone_cloud, region=settings.pinecone_region,
                                   max_retries=settings.llm_max_retries)
    from app.vector.qdrant_store import QdrantVectorStore

    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    collection = settings.qdrant_collection if kind == "memories" else f"{settings.qdrant_collection}_{kind}"
    return QdrantVectorStore(settings.qdrant_url, collection, settings.embedding_dim, api_key=key)
