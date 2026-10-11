from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.models.memory import MemoryCreate, MemoryRecord, utcnow
from app.services.memory_service import MemoryService

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def load_seed(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or FIXTURES / "seed_memories.json").read_text())


def seed_memories(svc: MemoryService, user_id: str | None = None, path: Path | None = None) -> list[MemoryRecord]:
    data = load_seed(path)
    uid = user_id or data["user"]["user_id"]
    now = utcnow()
    items = []
    for m in data["memories"]:
        m = dict(m)
        days = m.pop("days_ago", 0)
        items.append(MemoryCreate(**m, user_id=uid, session_id="seed",
                                  created_at=now - timedelta(days=days, hours=1)))
    return svc.create_many(items)
