"""Interviewer: streams one warm, open follow-up using the assembled context."""
from __future__ import annotations

from typing import AsyncIterator

from app.llm.chat import LLMClient
from app.services.context_assembler import AssembledContext

MAX_REPLY_TOKENS = 220


class Interviewer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def stream(self, ctx: AssembledContext) -> AsyncIterator[str]:
        return self.llm.astream("interviewer", ctx.system_prompt, ctx.messages, max_tokens=MAX_REPLY_TOKENS,
                                hints=ctx.hints)

    def regenerate(self, ctx: AssembledContext, banned_question: str) -> str:
        hints = {**ctx.hints, "banned_questions": [banned_question]}
        system = (ctx.system_prompt + f"\n\nYour draft repeated an earlier question: \"{banned_question}\". "
                  "Ask a DIFFERENT open question that has not been asked before.")
        return self.llm.generate("interviewer", system, ctx.messages, max_tokens=MAX_REPLY_TOKENS, hints=hints).text.strip()
