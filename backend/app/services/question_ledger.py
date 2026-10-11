"""Every question the Interviewer asks is recorded (text in DynamoDB, vector in the 'questions' index).
The assembler injects semantically relevant + recent ones as QUESTIONS ALREADY ASKED, and each new reply
is checked for near-repeats (logged on the agent run, surfaced in the SSE 'done' event)."""
from __future__ import annotations

import hashlib
import re

from app.llm.embeddings import Embedder
from app.models.agents import AskedQuestion
from app.models.memory import utcnow
from app.models.session import Message
from app.repos.user_records import AskedQuestionRepository
from app.vector.base import VectorFilter, VectorStore

Q_RE = re.compile(r"[^.!?]*\?")
REPEAT_SIMILARITY = 0.92


def extract_questions(text: str) -> list[str]:
    return [q.strip() for q in Q_RE.findall(text) if len(q.split()) >= 4]


class QuestionLedger:
    def __init__(self, repo: AskedQuestionRepository, embedder: Embedder, store: VectorStore):
        self.repo, self.embedder, self.store = repo, embedder, store

    def find_repeat(self, user_id: str, text: str) -> tuple[str, float] | None:
        qs = extract_questions(text)
        if not qs:
            return None
        best: tuple[str, float] | None = None
        for v in self.embedder.embed(qs):
            for h in self.store.query(v, 1, VectorFilter(user_id=user_id, types=["question"])):
                if h.similarity >= REPEAT_SIMILARITY and (best is None or h.similarity > best[1]):
                    best = (h.id, h.similarity)
        return best

    def record(self, msg: Message) -> list[AskedQuestion]:
        qs = extract_questions(msg.content)
        if not qs:
            return []
        now = utcnow()
        items = [AskedQuestion(qid="aq_" + hashlib.sha1(f"{msg.message_id}|{i}".encode()).hexdigest()[:16],
                               user_id=msg.user_id, session_id=msg.session_id, message_id=msg.message_id, text=q,
                               created_at=now) for i, q in enumerate(qs)]
        for it in items:
            self.repo.add(it)
        self.store.upsert([i.qid for i in items], self.embedder.embed(qs),
                          [{"user_id": msg.user_id, "type": "question", "created_at": int(now.timestamp())}
                           for _ in items])
        return items

    def relevant(self, user_id: str, query: str, k: int = 6) -> list[AskedQuestion]:
        hits = self.store.query(self.embedder.embed([query])[0], k, VectorFilter(user_id=user_id, types=["question"]))
        by_id = {q.qid: q for q in self.repo.get_many(user_id, {h.id for h in hits})} if hits else {}
        semantic = [by_id[h.id] for h in hits if h.id in by_id]
        seen, out = set(), []
        for q in semantic + self.repo.recent(user_id, k):
            if q.qid not in seen:
                seen.add(q.qid)
                out.append(q)
        return out

    def recent_texts(self, user_id: str, n: int = 500) -> list[str]:
        return [q.text for q in self.repo.recent(user_id, n)]

    def text_for(self, user_id: str, qid: str) -> str:
        found = self.repo.get_many(user_id, {qid})
        return found[0].text if found else ""
