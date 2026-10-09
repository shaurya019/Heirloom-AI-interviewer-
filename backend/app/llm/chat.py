"""Chat LLM abstraction.

Agents call `generate`, `structured`, or `astream` with a `task` name and optional `hints`
(the raw structured inputs). The OpenAI client ignores hints; the offline FakeLLM uses them to
produce deterministic, task-appropriate output without parsing prompts.
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Literal, Protocol, Sequence, TypeVar

from pydantic import BaseModel
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import Settings
from app.errors import ConfigError, UpstreamError
from app.logging_setup import get_logger
from app.tokens import get_counter

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResult(BaseModel):
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    
class LLMClient(Protocol):
    model: str

    def generate(self, task: str, system: str, messages: Sequence[ChatMessage], *,
                 max_tokens: int | None = None, hints: dict[str, Any] | None = None) -> LLMResult: ...

    def structured(self, task: str, system: str, messages: Sequence[ChatMessage], schema: type[T], *,
                   hints: dict[str, Any] | None = None) -> tuple[T, LLMResult]: ...

    def astream(self, task: str, system: str, messages: Sequence[ChatMessage], *,
                max_tokens: int | None = None, hints: dict[str, Any] | None = None) -> AsyncIterator[str]: ...

def count_prompt_tokens(system,messages,model):
    c = get_counter(model)
    return c.count(system) + 4 + sum(c.count(m.content) + 4 for m in messages)


class OpenAIChat:
    """LangChain ChatOpenAI. The OpenAI SDK retries 429/5xx/connection errors with exponential
    backoff (max_retries); tenacity adds retries for malformed structured output."""
    
    def __init__(self,settings,model):
        from langchain_openai import ChatOpenAI
        
        if settings.openai_api_key is None:
            raise ConfigError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        self.model = model or settings.openai_chat_model
        self._llm = ChatOpenAI(model=self.model, api_key=settings.openai_api_key.get_secret_value(),
                               base_url=settings.openai_base_url or None, max_retries=settings.llm_max_retries,
                               timeout=settings.llm_timeout_seconds, temperature=0.4,
                               stream_usage=True)
    
    @staticmethod
    def _lc(system: str, messages: Sequence[ChatMessage]) -> list[Any]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        out: list[Any] = [SystemMessage(system)]
        for m in messages:
            out.append({"user": HumanMessage, "assistant": AIMessage, "system": SystemMessage}[m.role](m.content))
        return out
        
    def _usage(self, msg: Any, system: str, messages: Sequence[ChatMessage], text: str) -> tuple[int, int]:
        um = getattr(msg, "usage_metadata", None) or {}
        pt = um.get("input_tokens") or count_prompt_tokens(system, messages, self.model)
        ct = um.get("output_tokens") or get_counter(self.model).count(text)
        return int(pt), int(ct)
        
    def generate(self, task: str, system: str, messages: Sequence[ChatMessage], *,
                 max_tokens: int | None = None, hints: dict[str, Any] | None = None) -> LLMResult:
        t0 = time.perf_counter()
        llm = self._llm.bind(max_tokens) if max_tokens else self._llm
        try:
            msg = llm.invoke(self._lc(system, messages))
        except Exception as e:
            raise UpstreamError(f"LLM call failed for {task}: {type(e).__name__}") from e
        
        text = msg.content if isinstance(msg.content,str) else str(msg.content)
        pt, ct = self._usage(msg, system, messages, text)
        return LLMResult(text=text.strip(), model=self.model, prompt_tokens=pt, completion_tokens=ct,
                         latency_ms=(time.perf_counter() - t0) * 1000)
    
    def structured(self, task: str, system: str, messages: Sequence[ChatMessage], schema: type[T], *,
                   hints: dict[str, Any] | None = None) -> tuple[T, LLMResult]:
        from langchain_core.exceptions import OutputParserException

        t0 = time.perf_counter()
        runnable = self._llm.with_structured_output(schema, include_raw=True, method="json_schema", strict=False)

        @retry(retry=retry_if_exception_type((OutputParserException, ValueError)), stop=stop_after_attempt(3),
               wait=wait_random_exponential(multiplier=0.3, max=4), reraise=True,
               before_sleep=before_sleep_log(log, logging.WARNING))
        def _call() -> tuple[T, Any]:
            out = runnable.invoke(self._lc(system, messages))
            if out.get("parsing_error") or out.get("parsed") is None:
                raise ValueError(f"structured output parse failed: {out.get('parsing_error')}")
            return out["parsed"], out["raw"]

        try:
            parsed, raw = _call()
        except Exception as e:  # noqa: BLE001
            raise UpstreamError(f"LLM structured call failed for {task}: {type(e).__name__}") from e
        text = parsed.model_dump_json()
        pt, ct = self._usage(raw, system, messages, text)
        return parsed, LLMResult(text=text, model=self.model, prompt_tokens=pt, completion_tokens=ct,
                                 latency_ms=(time.perf_counter() - t0) * 1000)
        
    async def astream(self, task: str, system: str, messages: Sequence[ChatMessage], *,
                      max_tokens: int | None = None, hints: dict[str, Any] | None = None) -> AsyncIterator[str]:
        llm = self._llm.bind(max_tokens) if max_tokens else self._llm
        async for chunk in llm.astream(self._lc(system,messages)):
            if isinstance(chunk.content,str) and chunk.content:
                yield chunk.content
    
def build_llm(settings: Settings, purpose: Literal["chat", "summary"] = "chat") -> LLMClient:
    return OpenAIChat(settings, model=settings.summary_model if purpose == "summary" else settings.openai_chat_model)
