import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useContextPreview, useContradictions, useEndSession, useMessages, useSendMessage, useSession } from "../api/hooks";
import { BudgetBar } from "../components/BudgetBar";
import { Notice, errorText } from "../components/Notice";
import { SessionSelect } from "../components/SessionSelect";
import { SLOT_META } from "../lib/tokens";
import { useUser } from "../lib/user";

export function InterviewPage() {
  const { userId } = useUser();
  const [params, setParams] = useSearchParams();
  const sessionId = params.get("session") ?? undefined;
  const setSession = (id: string) => setParams({ session: id }, { replace: true });
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Interview</h1>
      <div className="mt-4"><SessionSelect sessionId={sessionId} onChange={setSession} /></div>
      {sessionId && <Conversation key={sessionId} sessionId={sessionId} userId={userId} />}
    </div>
  );
}

function Conversation({ sessionId, userId }: { sessionId: string; userId: string }) {
  const session = useSession(sessionId);
  const messages = useMessages(sessionId);
  const send = useSendMessage(sessionId, userId);
  const end = useEndSession(sessionId);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const ended = session.data?.status === "ended";

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [messages.data?.length, send.streaming]);

  const submit = () => {
    const text = draft.trim();
    if (!text || send.isPending) return;
    setDraft("");
    send.mutate(text);
  };

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section aria-label="Conversation" className="min-w-0">
        <div className="max-h-[62vh] space-y-5 overflow-y-auto pr-2">
          {messages.isLoading && <p className="text-moss">Loading the conversation…</p>}
          {messages.error && <Notice tone="error">Messages couldn't be loaded: {errorText(messages.error)}</Notice>}
          {messages.data?.length === 0 && !send.isPending && (
            <Notice>Start by saying hello, or share the first memory that comes to mind.</Notice>
          )}
          {messages.data?.map((m) => (
            <article key={m.message_id} className={m.role === "user" ? "ml-auto max-w-[62ch]" : "max-w-[62ch]"}>
              <p className="text-moss mb-1 text-sm">{m.role === "user" ? "Narrator" : "Heirloom"}
                {m.pending && " · sending"}{m.revised && " · rephrased to avoid repeating a question"}</p>
              <p className={`story text-[17px] ${m.role === "user"
                ? "bg-white border-rule rounded-md border px-4 py-3" : ""} ${m.pending ? "opacity-60" : ""}`}>{m.content}</p>
            </article>
          ))}
          {send.streaming !== null && (
            <article className="max-w-[62ch]" aria-live="polite">
              <p className="text-moss mb-1 text-sm">Heirloom</p>
              <p className="story text-[17px]">{send.streaming || "…"}</p>
            </article>
          )}
          <div ref={bottom} />
        </div>
        {send.error && <Notice tone="error">The reply didn't arrive: {errorText(send.error)} Your message was not saved; try sending it again.</Notice>}
        {ended ? (
          <Notice>This session has ended. Start a new session to keep talking.</Notice>
        ) : (
          <form className="mt-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <label htmlFor="msg" className="sr-only">Your reply</label>
            <textarea id="msg" rows={3} value={draft} onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
                      placeholder="Type what they said…"
                      className="story border-rule w-full max-w-[72ch] rounded-md border bg-white px-4 py-3 text-[17px]" />
            <div className="mt-2 flex gap-3">
              <button disabled={send.isPending || !draft.trim()} className="bg-ink rounded px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                {send.isPending ? "Listening…" : "Send"}
              </button>
              <button type="button" onClick={() => end.mutate()} disabled={end.isPending || send.isPending}
                      className="text-carbon text-sm font-semibold disabled:opacity-50">
                {end.isPending ? "Ending session…" : "End session"}
              </button>
              <span className="text-moss self-center text-sm">Ctrl/⌘ + Enter to send</span>
            </div>
          </form>
        )}
      </section>
      <ContextPanel sessionId={sessionId} userId={userId} />
    </div>
  );
}

function ContextPanel({ sessionId, userId }: { sessionId: string; userId: string }) {
  const preview = useContextPreview(sessionId);
  const contradictions = useContradictions(userId);
  const [open, setOpen] = useState<string | null>("memories");
  const pending = contradictions.data?.filter((q) => q.status !== "resolved") ?? [];
  return (
    <aside aria-label="Context for the next reply" className="lg:sticky lg:top-6 lg:self-start">
      {preview.error && <Notice tone="error">Context preview unavailable: {errorText(preview.error)}</Notice>}
      {preview.data && (
        <>
          <BudgetBar slots={preview.data.slots} budget={preview.data.budget} total={preview.data.total_tokens} />
          <ul className="border-rule mt-4 divide-y divide-[var(--color-rule)] border-y">
            {preview.data.slots.map((s) => (
              <li key={s.name}>
                <button aria-expanded={open === s.name} onClick={() => setOpen(open === s.name ? null : s.name)}
                        className="flex w-full items-center gap-2 py-2 text-left text-sm">
                  <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SLOT_META[s.name].color }} />
                  <span className="font-medium">{SLOT_META[s.name].label}</span>
                  <span className="text-moss ml-auto">{s.included_ids.length} included{s.dropped_ids.length ? `, ${s.dropped_ids.length} left out` : ""}</span>
                </button>
                {open === s.name && (
                  <ul className="max-h-64 space-y-2 overflow-y-auto pb-3">
                    {s.items.length === 0 && <li className="text-moss text-sm">Nothing in this slot this turn.</li>}
                    {s.items.map((it, i) => (
                      <li key={`${it.id}-${i}`} className="text-sm">
                        <p className="text-moss">{it.id ? it.id.slice(-10) : "item"} · {it.tokens} tokens</p>
                        <p className="line-clamp-4">{it.text}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {pending.length > 0 && (
        <Notice tone="attention">
          <p className="font-semibold">To clarify gently</p>
          {pending.map((q) => <p key={q.qid} className="mt-1">{q.question} <span className="text-moss">({q.status})</span></p>)}
        </Notice>
      )}
    </aside>
  );
}
