"""Central configuration. Every tunable lives here and is read from env / .env.

Secrets are SecretStr so they never appear in repr(), logs, or error payloads.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- OpenAI / LLM ---
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_summary_model: str | None = None  # falls back to chat model
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_max_retries: int = Field(5, ge=0, le=10)
    llm_timeout_seconds: float = Field(60.0, gt=0)

    # --- embeddings ---
    embedding_provider: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = Field(1536, gt=0)
    embedding_batch_size: int = Field(64, ge=1, le=2048)

    # --- vector store ---
    vector_backend: Literal["qdrant", "pinecone"] = "qdrant"
    qdrant_url: str = "http://localhost:6333"  # ":memory:" for in-process
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "heirloom_memories"
    pinecone_api_key: SecretStr | None = None
    pinecone_index: str = "heirloom"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_namespace: str = "default"

    # --- DynamoDB ---
    aws_region: str = "us-east-1"
    dynamodb_endpoint_url: str | None = None  # http://localhost:8000 for DynamoDB Local
    dynamodb_table: str = "heirloom"

    # --- hybrid retrieval ---
    w_sim: float = Field(0.6, ge=0)
    w_rec: float = Field(0.2, ge=0)
    w_imp: float = Field(0.2, ge=0)
    decay: float = Field(0.05, ge=0)
    candidate_multiplier: int = Field(4, ge=1, le=50)
    default_top_k: int = Field(8, ge=1, le=200)
    default_min_score: float = Field(0.0, ge=0, le=1)

    # --- summaries ---
    rolling_buffer_max_tokens: int = Field(3000, gt=0)
    rolling_chunk_messages: int = Field(12, ge=2)
    rolling_summary_max_tokens: int = Field(800, gt=0)
    section_fanout: int = Field(5, ge=2)

    # --- context assembler budgets ---
    context_budget_tokens: int = Field(8000, gt=0)
    budget_system: int = Field(700, ge=0)
    budget_session_summary: int = Field(600, ge=0)
    budget_section_summaries: int = Field(1200, ge=0)
    budget_rolling_summary: int = Field(800, ge=0)
    budget_memories: int = Field(1800, ge=0)
    budget_open_questions: int = Field(400, ge=0)
    budget_recent_messages: int = Field(2500, ge=0)

    # --- agent thresholds ---
    continuity_top_k: int = Field(5, ge=1)
    continuity_similarity_threshold: float = Field(0.55, ge=0, le=1)
    gap_min_years: int = Field(2, ge=1)
    archivist_min_importance: float = Field(0.0, ge=0, le=1)
    
    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.w_sim + self.w_rec + self.w_imp <= 0:
            raise ValueError("At least one of W_SIM, W_REC, W_IMP must be > 0")
        if self.rolling_chunk_messages % 2 != 0:
            raise ValueError(
                "ROLLING_CHUNK_MESSAGES must be even so user/assistant pairs are never split"
            )
        if self.vector_backend == "pinecone" and self.pinecone_api_key is None:
            raise ValueError("VECTOR_BACKEND=pinecone requires PINECONE_API_KEY")
        if self.app_env == "prod":
            if self.llm_provider == "openai" and self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY is required in prod")
            if self.llm_provider == "fake" or self.embedding_provider == "fake":
                raise ValueError("fake LLM/embedding providers are not allowed in prod")
        return self
    
    @property
    def summary_model(self) -> str:
        return self.openai_summary_model or self.openai_chat_model
    
    @property
    def slot_budgets(self) -> dict[str, int]:
        """Per-slot budgets in priority order (highest priority first)."""
        return {
            "system": self.budget_system,
            "session_summary": self.budget_session_summary,
            "section_summaries": self.budget_section_summaries,
            "rolling_summary": self.budget_rolling_summary,
            "memories": self.budget_memories,
            "open_questions": self.budget_open_questions,
            "recent_messages": self.budget_recent_messages,
        }
    
@lru_cache
def get_settings() -> Settings:
    return Settings()