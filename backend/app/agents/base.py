from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from app.llm.chat import LLMResult
from app.repos.agent_runs import AgentRunRepository


class RunRecorder:
    """Times an agent run and logs exactly one agent_run record (ok or error)."""

    def __init__(self, runs: AgentRunRepository, agent: str, session_id: str | None, user_id: str | None):
        self.runs, self.agent, self.session_id, self.user_id = runs, agent, session_id, user_id
        self.input_ids: list[str] = []
        self.result: LLMResult | None = None
        self.output: Any = None
        self.t0 = time.perf_counter()

    @contextmanager
    def run(self) -> Iterator["RunRecorder"]:
        try:
            yield self
        except Exception as e:
            self.runs.log(self.agent, session_id=self.session_id, user_id=self.user_id, input_ids=self.input_ids,
                          result=self.result, output=self.output or "", status="error",
                          error=f"{type(e).__name__}: {e}"[:500], latency_ms=(time.perf_counter() - self.t0) * 1000)
            raise
        self.runs.log(self.agent, session_id=self.session_id, user_id=self.user_id, input_ids=self.input_ids,
                      result=self.result, output=self.output, latency_ms=(time.perf_counter() - self.t0) * 1000)


def recorder(runs: AgentRunRepository, agent: str, session_id: str | None, user_id: str | None) -> RunRecorder:
    return RunRecorder(runs, agent, session_id, user_id)
