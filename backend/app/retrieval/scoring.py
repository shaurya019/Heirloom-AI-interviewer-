"""Hybrid score (pure, side-effect free):

    score = w_sim * clamp(cos, 0, 1) + w_rec * exp(-decay * age_days) + w_imp * importance
"""
from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, Field


class Weights(BaseModel):
    w_sim: float = Field(0.6, ge=0)
    w_rec: float = Field(0.2, ge=0)
    w_imp: float = Field(0.2, ge=0)
    decay: float = Field(0.05, ge=0)


class WeightedComponents(BaseModel):
    similarity: float
    recency: float
    importance: float


class ScoreBreakdown(BaseModel):
    similarity: float           # clamped cosine in [0, 1]
    raw_similarity: float       # as returned by the vector store
    recency: float              # exp(-decay * age_days) in (0, 1]
    importance: float           # in [0, 1]
    weighted_components: WeightedComponents
    final_score: float
    age_days: float


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def age_in_days(created_at: datetime, now: datetime) -> float:
    return max(0.0, (now - created_at).total_seconds() / 86_400.0)


def recency_score(age_days: float, decay: float) -> float:
    return math.exp(-decay * max(0.0, age_days))


def hybrid_score(similarity: float, created_at: datetime, importance: float, now: datetime,
                 weights: Weights) -> ScoreBreakdown:
    sim = clamp(similarity)
    age = age_in_days(created_at, now)
    rec = recency_score(age, weights.decay)
    imp = clamp(importance)
    wc = WeightedComponents(similarity=weights.w_sim * sim, recency=weights.w_rec * rec,
                            importance=weights.w_imp * imp)
    return ScoreBreakdown(similarity=sim, raw_similarity=similarity, recency=rec, importance=imp,
                          weighted_components=wc, final_score=wc.similarity + wc.recency + wc.importance,
                          age_days=age)
