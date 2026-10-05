import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "./client";
import { queryKeys } from "./queryKeys";
import type { ChapterRequest, Message, SearchRequest } from "./types";

export const useSessions = (userId: string) =>
  useQuery({ queryKey: queryKeys.sessions(userId), queryFn: () => api.listSessions(userId), enabled: !!userId });
export const useSession = (sessionId?: string) =>
  useQuery({ queryKey: queryKeys.session(sessionId!), queryFn: () => api.getSession(sessionId!), enabled: !!sessionId });
export const useMessages = (sessionId?: string) =>
  useQuery({ queryKey: queryKeys.messages(sessionId!), queryFn: () => api.listAllMessages(sessionId!), enabled: !!sessionId });
export const useSummaryTree = (sessionId?: string) =>
  useQuery({ queryKey: queryKeys.summaryTree(sessionId!), queryFn: () => api.summaryTree(sessionId!), enabled: !!sessionId });
export const useContextPreview = (sessionId?: string, q?: string) =>
  useQuery({
    queryKey: queryKeys.contextPreview(sessionId!, q), queryFn: () => api.contextPreview(sessionId!, q),
    enabled: !!sessionId, placeholderData: keepPreviousData,
  });
export const useMemories = (userId: string) =>
  useQuery({ queryKey: queryKeys.memories.list(userId), queryFn: () => api.listMemories(userId), enabled: !!userId });
export const useMemory = (memoryId?: string | null) =>
  useQuery({ queryKey: queryKeys.memory(memoryId!), queryFn: () => api.getMemory(memoryId!), enabled: !!memoryId });
export const useSearch = (req: SearchRequest, enabled = true) =>
  useQuery({
    queryKey: queryKeys.memories.search(req), queryFn: () => api.search(req),
    enabled: enabled && !!req.query.trim(), placeholderData: keepPreviousData,  // no flash while refetching
  });
export const useGaps = (userId: string) =>
  useQuery({ queryKey: queryKeys.gaps(userId), queryFn: () => api.gaps(userId), enabled: !!userId });
export const useContradictions = (userId: string) =>
  useQuery({ queryKey: queryKeys.contradictions(userId), queryFn: () => api.contradictions(userId), enabled: !!userId });
export const useChapters = (userId: string) =>
  useQuery({ queryKey: queryKeys.chapters(userId), queryFn: () => api.listChapters(userId), enabled: !!userId });

export function useCreateSession(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => api.createSession({ user_id: userId, title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.sessions(userId) }),
  });
}

export function useEndSession(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.endSession(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
      qc.invalidateQueries({ queryKey: queryKeys.summaryTree(sessionId) });
    },
  });
}

export function useWriteChapter(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: ChapterRequest) => api.writeChapter(userId, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.chapters(userId) }),
  });
}

export function useResolveContradiction(userId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ qid, resolution }: { qid: string; resolution: string }) =>
      api.resolveContradiction(userId, qid, resolution),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.contradictions(userId) }),
  });
}

/**
 * Send a message: optimistic user bubble, streamed assistant text, then targeted invalidation of
 * everything a turn can change. The Archivist/Summarizer/Continuity Checker run as background tasks
 * AFTER the stream closes, so invalidation runs again shortly after to pick up their writes.
 */
export function useSendMessage(sessionId: string, userId: string) {
  const qc = useQueryClient();
  const [streaming, setStreaming] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const invalidateTurn = () => {
    qc.invalidateQueries({ queryKey: queryKeys.messages(sessionId) });
    qc.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
    qc.invalidateQueries({ queryKey: queryKeys.summaryTree(sessionId) });
    qc.invalidateQueries({ queryKey: queryKeys.contextPreviewAll(sessionId) });
    qc.invalidateQueries({ queryKey: queryKeys.memories.all(userId) });
    qc.invalidateQueries({ queryKey: queryKeys.contradictions(userId) });
    qc.invalidateQueries({ queryKey: queryKeys.gaps(userId) });
    qc.invalidateQueries({ queryKey: queryKeys.agentRuns(sessionId) });
  };

  const mutation = useMutation({
    mutationFn: async (content: string) => {
      abort.current = new AbortController();
      setStreaming("");
      await api.streamMessage(sessionId, content, (ev) => {
        if (ev.event === "token") setStreaming((s) => (s ?? "") + ev.data.delta);
        if (ev.event === "user_message" || ev.event === "assistant_message") {
          qc.setQueryData<Message[]>(queryKeys.messages(sessionId), (old = []) => [
            ...old.filter((m) => !m.pending || ev.event !== "user_message"), ev.data,
          ]);
        }
        if (ev.event === "assistant_message") setStreaming(null);
        if (ev.event === "error") throw new Error(ev.data.message);
      }, abort.current.signal);
    },
    onMutate: async (content) => {
      await qc.cancelQueries({ queryKey: queryKeys.messages(sessionId) });
      const previous = qc.getQueryData<Message[]>(queryKeys.messages(sessionId));
      const optimistic: Message = {
        message_id: `optimistic-${Date.now()}`, session_id: sessionId, user_id: userId,
        seq: (previous?.at(-1)?.seq ?? -1) + 1, role: "user", content, token_count: 0,
        created_at: new Date().toISOString(), pending: true,
      };
      qc.setQueryData<Message[]>(queryKeys.messages(sessionId), (old = []) => [...old, optimistic]);
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.messages(sessionId), ctx.previous);
      setStreaming(null);
    },
    onSettled: () => {
      invalidateTurn();
      setTimeout(invalidateTurn, 2500); // background agents finish after the stream closes
    },
  });
  return { ...mutation, streaming, cancel: () => abort.current?.abort() };
}
