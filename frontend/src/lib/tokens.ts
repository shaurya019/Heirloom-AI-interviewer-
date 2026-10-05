import type { MemoryType, SlotName } from "../api/types";

export const SLOT_META: Record<SlotName, { label: string; color: string }> = {
  system: { label: "Interviewer rules", color: "#1c2541" },
  session_summary: { label: "Earlier sessions", color: "#3a506b" },
  section_summaries: { label: "Related sections", color: "#3a6ea5" },
  rolling_summary: { label: "This session so far", color: "#6fa3c7" },
  memories: { label: "Memories", color: "#8fb3a0" },
  open_questions: { label: "Things to clarify", color: "#d9a441" },
  recent_messages: { label: "Recent conversation", color: "#b9c3cc" },
};

export const TYPE_COLOR: Record<MemoryType, string> = {
  event: "#1c2541", person: "#3a6ea5", place: "#6f7f72", anecdote: "#7a6a9a", emotion: "#9c4a6e", fact: "#8a96a3",
};

export const SCORE_COLOR = { similarity: "#3a6ea5", recency: "#6fa3c7", importance: "#d9a441" } as const;

export const LEVEL_META: Record<number, { label: string; color: string }> = {
  0: { label: "Chunk", color: "#b9c3cc" },
  1: { label: "Section", color: "#3a6ea5" },
  2: { label: "Session", color: "#1c2541" },
  3: { label: "Life archive", color: "#d9a441" },
};

export const years = (s: number | null, e: number | null) =>
  s === null ? "Undated" : s === e || e === null ? `${s}` : `${s}–${e}`;
