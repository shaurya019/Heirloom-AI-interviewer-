// Mirrors backend Pydantic models (app/models/*, app/retrieval/hybrid.py, app/services/context_assembler.py).
export type MemoryType = "person" | "place" | "event" | "anecdote" | "emotion" | "fact";
export const MEMORY_TYPES: MemoryType[] = ["person", "place", "event", "anecdote", "emotion", "fact"];

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> | null; request_id?: string | null };
}

export interface User { user_id: string; name: string; birth_year: number | null; description: string; created_at: string }

export interface Session {
  session_id: string; user_id: string; title: string; status: "active" | "ended";
  created_at: string; ended_at: string | null; msg_count: number; buffer_start_seq: number;
  rolling_summary: string; rolling_summary_tokens: number; rolling_version: number;
}
export interface SessionDetail extends Session {
  message_count: number; node_counts: Record<string, number>; open_question_count: number;
}

export interface Message {
  message_id: string; session_id: string; user_id: string; seq: number;
  role: "user" | "assistant"; content: string; token_count: number; created_at: string;
  revised?: boolean; pending?: boolean;
}
export interface Page<T> { items: T[]; next_cursor: string | null }

export interface MemoryRecord {
  memory_id: string; user_id: string; session_id: string | null; type: MemoryType; text: string;
  entities: string[]; event_year_start: number | null; event_year_end: number | null;
  importance: number; importance_rationale: string; source_message_ids: string[];
  created_at: string; embedding_model: string; version: number; vector_status: "pending" | "synced";
}

export interface Weights { w_sim: number; w_rec: number; w_imp: number; decay: number }
export interface SearchFilters {
  user_id: string; types?: MemoryType[] | null; created_from?: string | null; created_to?: string | null;
  event_year_from?: number | null; event_year_to?: number | null;
}
export interface SearchRequest {
  query: string; filters: SearchFilters; weights?: Partial<Weights>; top_k?: number; min_score?: number;
}
export interface ScoreBreakdown {
  similarity: number; raw_similarity: number; recency: number; importance: number;
  weighted_components: { similarity: number; recency: number; importance: number };
  final_score: number; age_days: number;
}
export interface SearchResult { rank: number; memory: MemoryRecord; breakdown: ScoreBreakdown }
export interface SearchResponse {
  query: string; weights: Weights; top_k: number; min_score: number; results: SearchResult[];
  stats: { candidates_requested: number; candidates_returned: number; hydrated: number; after_filters: number; above_min_score: number };
}

export interface SummaryNode {
  node_id: string; user_id: string; session_id: string; level: number; parent_id: string | null;
  child_ids: string[]; title: string; summary: string; first_message_id: string; last_message_id: string;
  first_seq: number; last_seq: number; token_count: number; source_token_count: number; model: string;
  created_at: string; children: SummaryNode[];
}
export interface SummaryTree {
  session_id: string; roots: SummaryNode[]; rolling_summary: string; rolling_summary_tokens: number;
  buffer_start_seq: number; msg_count: number;
}

export type SlotName = "system" | "session_summary" | "section_summaries" | "rolling_summary" | "memories" | "open_questions" | "recent_messages";
export interface ContextSlot {
  name: SlotName; priority: number; budget: number; tokens: number; included_ids: string[]; dropped_ids: string[];
  truncated: boolean; trimmed_by_global_budget: boolean; items: { id: string | null; tokens: number; text: string }[];
}
export interface ContextPreview {
  session_id: string; user_id: string; query: string; budget: number; total_tokens: number;
  tokens_before_global_trim: number; slots: ContextSlot[];
}

export interface OpenQuestion {
  qid: string; user_id: string; session_id: string | null; memory_ids: string[]; field: "date" | "name" | "place";
  existing_value: string; new_value: string; explanation: string; question: string;
  status: "open" | "asked" | "resolved"; resolution: string | null; created_at: string;
}
export interface GapReport {
  user_id: string; span_start: number | null; span_end: number | null; year_coverage: Record<string, number>;
  gaps: { start: number; end: number; years: number }[]; theme_counts: Record<string, number>;
  type_counts: Record<string, number>; thin_themes: string[]; top_entities: [string, number][];
  suggestions: { topic: string; question: string; reason: string }[]; memory_count: number;
}
export interface ChapterRequest { theme?: string | null; era_start?: number | null; era_end?: number | null; title?: string | null; top_k?: number }
export interface Chapter {
  chapter_id: string; user_id: string; title: string; request: ChapterRequest; markdown: string;
  citations: string[]; cited_memories: MemoryRecord[]; section_ids: string[]; invalid_citations_removed: number;
  model: string; created_at: string;
}
export interface AgentRun {
  run_id: string; agent: string; session_id: string; input_ids: string[]; prompt_tokens: number;
  completion_tokens: number; output: string; latency_ms: number; model: string; status: "ok" | "error";
  error: string | null; created_at: string;
}

export type StreamEvent =
  | { event: "user_message"; data: Message }
  | { event: "context"; data: { total_tokens: number; budget: number; slots: { name: SlotName; tokens: number; included_ids: string[] }[] } }
  | { event: "token"; data: { delta: string } }
  | { event: "assistant_message"; data: Message }
  | { event: "done"; data: { repeat_of: string | null; revised_from_repeat: string | null; open_questions_asked: string[] } }
  | { event: "error"; data: { code: string; message: string } };
