"""Typed per-turn orchestrator (explicit service layer).

  POST message ─► persist user msg ─► assemble context ─► stream Interviewer (SSE)
                                                           └► persist reply, ledger, repeat check, mark asked
               background (after the stream closes, serialized per session):
                  Archivist ─► Continuity Checker (new memories) ─► Summarizer (rolling + sections)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.agents.archivist import Archivist
from app.agents.continuity import ContinuityChecker
from app.agents.interviewer import Interviewer
from app.agents.summarizer import Summarizer
from app.errors import ConflictError
from app.llm.chat import LLMResult, count_prompt_tokens
from app.logging_setup import get_logger, log_event
from app.models.session import Message
from app.repos.agent_runs import AgentRunRepository
from app.repos.sessions import SessionRepository
from app.repos.user_records import OpenQuestionRepository
from app.services.context_assembler import ContextAssembler
from app.services.question_ledger import QuestionLedger
from app.tokens import get_counter

log = get_logger(__name__)


@dataclass
class PostTurnReport:
    memories: list[str]
    open_questions: list[str]
    leaves: list[str]
    sections: list[str]
    errors: list[str]


class TurnOrchestrator:
    def __init__(self, sessions: SessionRepository, assembler: ContextAssembler, interviewer: Interviewer,
                 archivist: Archivist, continuity: ContinuityChecker, summarizer: Summarizer,
                 ledger: QuestionLedger, questions: OpenQuestionRepository, runs: AgentRunRepository,
                 chat_model: str):
        self.sessions, self.assembler, self.interviewer = sessions, assembler, interviewer
        self.archivist, self.continuity, self.summarizer = archivist, continuity, summarizer
        self.ledger, self.questions, self.runs = ledger, questions, runs
        self.tok = get_counter(chat_model)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, session_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def accept_user_message(self, session_id: str, content: str) -> Message:
        s = self.sessions.require(session_id)
        if s.status == "ended":
            raise ConflictError("session has ended", {"session_id": session_id})
        return self.sessions.append_message(session_id, s.user_id, "user", content, self.tok.count(content))

    async def stream_reply(self, user_msg: Message) -> AsyncIterator[dict[str, Any]]:
        """Yields SSE-ready events. Persists the assistant message when the stream completes."""
        t0 = time.perf_counter()
        ctx = self.assembler.assemble(user_msg.session_id, query=user_msg.content)
        yield {"event": "context", "data": {"total_tokens": ctx.preview.total_tokens, "budget": ctx.preview.budget,
                                            "slots": [{"name": sl.name, "tokens": sl.tokens,
                                                       "included_ids": sl.included_ids} for sl in ctx.preview.slots]}}
        parts: list[str] = []
        try:
            async for delta in self.interviewer.stream(ctx):
                parts.append(delta)
                yield {"event": "token", "data": {"delta": delta}}
        except Exception as e:  # noqa: BLE001
            self.runs.log("interviewer", session_id=user_msg.session_id, user_id=user_msg.user_id,
                          input_ids=[user_msg.message_id], result=None, output="".join(parts), status="error",
                          error=f"{type(e).__name__}: {e}"[:300], latency_ms=(time.perf_counter() - t0) * 1000)
            yield {"event": "error", "data": {"code": "upstream_error", "message": "The interviewer is unavailable."}}
            return
        text = "".join(parts).strip()
        repeat = self.ledger.find_repeat(user_msg.user_id, text)
        revised = False
        if repeat:  # guard: one regeneration with the repeated question explicitly banned
            banned = self.ledger.text_for(user_msg.user_id, repeat[0])
            log_event(log, "interviewer.repeat_detected", logging.WARNING, asked_qid=repeat[0],
                      sim=round(repeat[1], 3))
            regen = self.interviewer.regenerate(ctx, banned)
            if not self.ledger.find_repeat(user_msg.user_id, regen):
                text, revised, repeat = regen, True, (repeat[0], repeat[1])
            else:
                revised = False
        msg = self.sessions.append_message(user_msg.session_id, user_msg.user_id, "assistant", text, self.tok.count(text))
        self.ledger.record(msg)
        asked = []
        for qid, q in zip(ctx.hints.get("open_question_ids", []), ctx.hints.get("open_questions", [])):
            oq = next((o for o in self.questions.list(user_msg.user_id, "open") if o.qid == qid), None)
            if oq and (q in text or (oq.existing_value in text and oq.new_value in text)):
                self.questions.set_status(user_msg.user_id, qid, "asked")
                asked.append(qid)
        included = [i for sl in ctx.preview.slots for i in sl.included_ids]
        res = LLMResult(text=text, model=self.interviewer.llm.model,
                        prompt_tokens=count_prompt_tokens(ctx.system_prompt, ctx.messages, self.interviewer.llm.model),
                        completion_tokens=self.tok.count(text), latency_ms=(time.perf_counter() - t0) * 1000)
        self.runs.log("interviewer", session_id=user_msg.session_id, user_id=user_msg.user_id,
                      input_ids=[user_msg.message_id] + included, result=res,
                      output={"reply": text, "revised": revised, "repeat_of": repeat[0] if repeat else None,
                              "open_questions_asked": asked})
        yield {"event": "assistant_message", "data": {**msg.model_dump(mode="json"), "revised": revised}}
        yield {"event": "done", "data": {"repeat_of": None if (revised or not repeat) else repeat[0],
                                         "revised_from_repeat": repeat[0] if revised else None,
                                         "open_questions_asked": asked}}

    def post_turn(self, user_msg: Message) -> PostTurnReport:
        """Background pipeline. Each agent is isolated: one failing never blocks the others."""
        rep = PostTurnReport([], [], [], [], [])
        with self._lock(user_msg.session_id):
            prev = self._previous_question(user_msg)
            try:
                new = self.archivist.run(user_msg, prev)
                rep.memories = [m.memory_id for m in new]
                if new:
                    rep.open_questions = [q.qid for q in self.continuity.run(new, user_msg.session_id)]
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"archivist/continuity: {type(e).__name__}")
                log.exception("post_turn.archivist_failed")
            try:
                sr = self.summarizer.process(user_msg.session_id)
                rep.leaves, rep.sections = sr.leaves_created, sr.sections_created
            except Exception as e:  # noqa: BLE001
                rep.errors.append(f"summarizer: {type(e).__name__}")
                log.exception("post_turn.summarizer_failed")
        log_event(log, "post_turn.done", session_id=user_msg.session_id, memories=len(rep.memories),
                  open_questions=len(rep.open_questions), leaves=len(rep.leaves), errors=rep.errors)
        return rep

    def _previous_question(self, user_msg: Message) -> str | None:
        if user_msg.seq == 0:
            return None
        msgs = self.sessions.messages_from(user_msg.session_id, max(0, user_msg.seq - 1), user_msg.seq - 1)
        return msgs[0].content if msgs and msgs[0].role == "assistant" else None
