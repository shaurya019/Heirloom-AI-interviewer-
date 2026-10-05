import type {
  AgentRun, ApiErrorBody, Chapter, ChapterRequest, ContextPreview, GapReport, MemoryRecord, Message,
  OpenQuestion, Page, SearchRequest, SearchResponse, Session, SessionDetail, StreamEvent, SummaryTree, User,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string | null;
  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

async function toApiError(res: Response, fallback: string): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try { body = await res.json(); } catch { /* non-JSON error */ }
  return new ApiError(res.status, body?.error.code ?? "http_error", body?.error.message ?? fallback,
    body?.error.details, body?.error.request_id);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!res.ok) throw await toApiError(res, `Request failed (${res.status})`);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const qs = (o: Record<string, string | number | null | undefined>) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  createUser: (b: { name: string; user_id?: string; birth_year?: number | null; description?: string }) =>
    request<User>("/users", { method: "POST", body: JSON.stringify(b) }),
  getUser: (id: string) => request<User>(`/users/${id}`),
  listSessions: (userId: string) => request<Session[]>(`/users/${userId}/sessions`),
  createSession: (b: { user_id: string; title: string }) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify(b) }),
  getSession: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  endSession: (id: string) => request<unknown>(`/sessions/${id}/end`, { method: "POST" }),
  listMessagesPage: (id: string, cursor?: string | null) =>
    request<Page<Message>>(`/sessions/${id}/messages${qs({ cursor, limit: 200 })}`),
  async listAllMessages(id: string): Promise<Message[]> {
    const out: Message[] = [];
    let cursor: string | null | undefined;
    do {
      const page = await api.listMessagesPage(id, cursor);
      out.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor);
    return out;
  },
  summaryTree: (id: string) => request<SummaryTree>(`/sessions/${id}/summary-tree`),
  contextPreview: (id: string, q?: string) => request<ContextPreview>(`/sessions/${id}/context/preview${qs({ q })}`),
  getMemory: (id: string) => request<MemoryRecord>(`/memories/${id}`),
  deleteMemory: (id: string) => request<void>(`/memories/${id}`, { method: "DELETE" }),
  listMemories: (userId: string) => request<MemoryRecord[]>(`/users/${userId}/memories${qs({ limit: 2000 })}`),
  search: (b: SearchRequest) => request<SearchResponse>("/memories/search", { method: "POST", body: JSON.stringify(b) }),
  gaps: (userId: string) => request<GapReport>(`/users/${userId}/gaps`),
  contradictions: (userId: string) => request<OpenQuestion[]>(`/users/${userId}/contradictions`),
  resolveContradiction: (userId: string, qid: string, resolution: string) =>
    request<OpenQuestion>(`/users/${userId}/contradictions/${qid}/resolve`, {
      method: "POST", body: JSON.stringify({ resolution }),
    }),
  listChapters: (userId: string) => request<Chapter[]>(`/users/${userId}/chapters`),
  writeChapter: (userId: string, b: ChapterRequest) =>
    request<Chapter>(`/users/${userId}/chapters`, { method: "POST", body: JSON.stringify(b) }),
  agentRuns: (sessionId: string) => request<AgentRun[]>(`/agent-runs${qs({ session_id: sessionId })}`),

  /** POST a message and consume the SSE stream (EventSource can't POST, so the stream is parsed by hand). */
  async streamMessage(sessionId: string, content: string, onEvent: (e: StreamEvent) => void,
                      signal?: AbortSignal): Promise<void> {
    const res = await fetch(`${BASE}/sessions/${sessionId}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ content }), signal,
    });
    if (!res.ok || !res.body) throw await toApiError(res, "Couldn't send the message.");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) onEvent({ event, data: JSON.parse(data) } as StreamEvent);
      }
    }
  },
};
