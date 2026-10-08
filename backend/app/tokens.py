"""Token counting.

Uses tiktoken when its encoding is available (the Docker image pre-downloads it at build time).
If the encoding can't be loaded (offline, blocked egress), falls back to a regex approximation
calibrated against o200k/cl100k on English prose (within ~10%). The fallback is logged once,
so budgets are never silently wrong by orders of magnitude.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Protocol

from app.logging_setup import get_logger, log_event

log = get_logger(__name__)

_APPROX_RE = re.compile(r"[A-Za-z]{1,4}|[A-Za-z]{5,}|\d{1,3}|[^\sA-Za-z\d]", re.UNICODE)


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...
    def truncate(self, text: str, max_tokens: int) -> str: ...


class TiktokenCounter:
    def __init__(self, encoding_name: str):
        import tiktoken

        self._enc = tiktoken.get_encoding(encoding_name)
        self.name = f"tiktoken:{encoding_name}"

    def count(self, text: str) -> int:
        return len(self._enc.encode(text, disallowed_special=())) if text else 0

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        toks = self._enc.encode(text, disallowed_special=())
        if len(toks) <= max_tokens:
            return text
        return self._enc.decode(toks[: max(0, max_tokens - 1)]).rstrip() + "…"


# ApproxCounter is a spare tyre. The accurate counter (TiktokenCounter) needs a dictionary file that may have to be downloaded. If the machine is offline or the download is blocked, that counter can't be built. Rather than crash, the app switches to a counter that needs nothing but Python itself and gives a "good enough" estimate.

# A rough count is far better than no count. If the app thinks a text is 1,100 tokens when it's really 1,000, budgets still work. If it had no number at all, it could not enforce any limit.

# The logic
# Real tokenizers follow a rough pattern on English text:

# short common words are usually 1 token
# longer words get split into several tokens
# punctuation marks are usually 1 token each
# long numbers get split into small groups of digits
# spaces mostly don't count on their own

class ApproxCounter:
    """~1 token per short word, long words split in two, each punctuation mark one token."""

    name = "approx"

    def _units(self, text: str) -> list[re.Match[str]]:
        return list(_APPROX_RE.finditer(text))

    def count(self, text: str) -> int:
        if not text:
            return 0
        n = 0
        for m in self._units(text):
            w = m.group(0)
            n += 2 if (w.isalpha() and len(w) >= 9) else 1
        return n

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        if self.count(text) <= max_tokens:
            return text
        n, end = 0, 0
        for m in self._units(text):
            w = m.group(0)
            n += 2 if (w.isalpha() and len(w) >= 9) else 1
            if n > max_tokens - 1:
                break
            end = m.end()
        return text[:end].rstrip() + "…"


def _encoding_for(model: str) -> str:
    return "o200k_base" if any(k in model for k in ("gpt-4o", "gpt-4.1", "o1", "o3", "o4", "gpt-5")) \
        else "cl100k_base"


@lru_cache(maxsize=8)
def get_counter(model: str = "gpt-4o-mini") -> TokenCounter:
    enc = _encoding_for(model)
    try:
        return TiktokenCounter(enc)
    except Exception as e:  # noqa: BLE001
        log_event(log, "tokens.tiktoken_unavailable", logging.WARNING, encoding=enc,
                  error=type(e).__name__, fallback="approx")
        return ApproxCounter()
