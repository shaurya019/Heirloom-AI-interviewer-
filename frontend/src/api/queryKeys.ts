import type { SearchRequest } from "./types";

/** Central query-key factory. Hierarchical so invalidation can target a whole branch. */
export const queryKeys = {
  user: (userId: string) => ["users", userId] as const,
  sessions: (userId: string) => ["users", userId, "sessions"] as const,
  gaps: (userId: string) => ["users", userId, "gaps"] as const,
  contradictions: (userId: string) => ["users", userId, "contradictions"] as const,
  chapters: (userId: string) => ["users", userId, "chapters"] as const,

  session: (sessionId: string) => ["sessions", sessionId] as const,
  messages: (sessionId: string) => ["sessions", sessionId, "messages"] as const,
  summaryTree: (sessionId: string) => ["sessions", sessionId, "summary-tree"] as const,
  contextPreviewAll: (sessionId: string) => ["sessions", sessionId, "context-preview"] as const,
  contextPreview: (sessionId: string, q?: string) => ["sessions", sessionId, "context-preview", q ?? null] as const,
  agentRuns: (sessionId: string) => ["sessions", sessionId, "agent-runs"] as const,

  memories: {
    all: (userId: string) => ["memories", userId] as const,
    list: (userId: string) => ["memories", userId, "list"] as const,
    search: (req: SearchRequest) => ["memories", req.filters.user_id, "search", req] as const,
  },
  memory: (memoryId: string) => ["memory", memoryId] as const,
};
