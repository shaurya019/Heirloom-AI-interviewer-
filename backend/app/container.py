"""Builds and wires every component from Settings. One instance per process (API) or per script."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.db.client import dynamodb_table
from app.agents.archivist import Archivist
from app.agents.chapter_writer import ChapterWriter
from app.agents.continuity import ContinuityChecker
from app.agents.gap_finder import GapFinder
from app.agents.interviewer import Interviewer
from app.agents.summarizer import Summarizer
from app.repos.user_records import AskedQuestionRepository, ChapterRepository, OpenQuestionRepository
from app.services.context_assembler import ContextAssembler
from app.services.orchestrator import TurnOrchestrator
from app.services.question_ledger import QuestionLedger
from app.llm.chat import LLMClient, build_llm
from app.llm.embeddings import CachingEmbedder, build_embedder
from app.repos.agent_runs import AgentRunRepository
from app.repos.sessions import SessionRepository, UserRepository
from app.repos.summary_nodes import SummaryNodeRepository
from app.services.section_index import SectionIndex
from app.logging_setup import get_logger, log_event
from app.repos.memories import MemoryRepository
from app.retrieval.hybrid import HybridRetriever
from app.services.memory_service import MemoryService
from app.vector.base import VectorStore
from app.vector.factory import build_vector_store

log = get_logger(__name__)


@dataclass
class Container:
    settings: Settings
    table: Any
    embedder: CachingEmbedder
    memory_store: VectorStore
    section_store: VectorStore
    question_store: VectorStore
    memory_repo: MemoryRepository
    memory_service: MemoryService
    retriever: HybridRetriever
    users: UserRepository
    sessions: SessionRepository
    nodes: SummaryNodeRepository
    runs: AgentRunRepository
    llm: LLMClient
    summary_llm: LLMClient
    section_index: SectionIndex
    summarizer: Summarizer
    open_questions: OpenQuestionRepository
    chapters: ChapterRepository
    ledger: QuestionLedger
    assembler: ContextAssembler
    archivist: Archivist
    continuity: ContinuityChecker
    gap_finder: GapFinder
    chapter_writer: ChapterWriter
    interviewer: Interviewer
    orchestrator: TurnOrchestrator
    extras: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Fail loudly at startup if EMBEDDING_DIM disagrees with any index."""
        for store in (self.memory_store, self.section_store, self.question_store):
            store.ensure_index()
        log_event(log, "container.validated", backend=self.memory_store.backend, dim=self.embedder.dim,
                  embedding_model=self.embedder.model)


def build_container(settings: Settings, *, validate: bool = True,
                    stores: dict[str, VectorStore] | None = None, llm: LLMClient | None = None) -> Container:
    table = dynamodb_table(settings)
    embedder = build_embedder(settings, ddb_table=table)
    stores = stores or {}
    # explicit None checks: an empty in-memory store defines __len__ and is falsy
    mem, sec, qst = (stores[k] if stores.get(k) is not None else build_vector_store(settings, k)
                     for k in ("memories", "sections", "questions"))
    repo = MemoryRepository(table)
    msvc = MemoryService(repo, embedder, mem)
    users, sessions = UserRepository(table), SessionRepository(table)
    nodes, runs = SummaryNodeRepository(table), AgentRunRepository(table)
    chat_llm = llm or build_llm(settings, "chat")
    summary_llm = llm or build_llm(settings, "summary")
    section_index = SectionIndex(embedder, sec, nodes)
    summarizer = Summarizer(settings, sessions, users, nodes, summary_llm, runs, on_section=section_index.index)
    retriever = HybridRetriever(msvc, settings)
    oq, chapters = OpenQuestionRepository(table), ChapterRepository(table)
    ledger = QuestionLedger(AskedQuestionRepository(table), embedder, qst)
    assembler = ContextAssembler(settings, sessions, users, nodes, section_index, retriever, repo, oq, ledger)
    archivist = Archivist(settings, summary_llm, msvc, retriever, users, runs)
    continuity = ContinuityChecker(settings, summary_llm, retriever, oq, runs)
    interviewer = Interviewer(chat_llm)
    orchestrator = TurnOrchestrator(sessions, assembler, interviewer, archivist, continuity, summarizer, ledger,
                                    oq, runs, settings.openai_chat_model)
    c = Container(settings=settings, table=table, embedder=embedder, memory_store=mem, section_store=sec,
                  question_store=qst, memory_repo=repo, memory_service=msvc, retriever=retriever, users=users,
                  sessions=sessions, nodes=nodes, runs=runs, llm=chat_llm, summary_llm=summary_llm,
                  section_index=section_index, summarizer=summarizer, open_questions=oq, chapters=chapters,
                  ledger=ledger, assembler=assembler, archivist=archivist, continuity=continuity,
                  gap_finder=GapFinder(settings, summary_llm, repo, users, runs),
                  chapter_writer=ChapterWriter(settings, chat_llm, retriever, section_index, chapters, runs),
                  interviewer=interviewer, orchestrator=orchestrator)
    if validate:
        c.validate()
    return c
