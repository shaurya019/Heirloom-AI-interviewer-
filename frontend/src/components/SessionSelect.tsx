import { useEffect, useState } from "react";
import { useCreateSession, useSessions } from "../api/hooks";
import { ApiError } from "../api/client";
import { useUser } from "../lib/user";
import { Notice, errorText } from "./Notice";
import { CreateUser } from "./CreateUser";

/** Picks the active session (kept in the URL by the caller). Offers to create the narrator if missing. */
export function SessionSelect({ sessionId, onChange }: { sessionId?: string; onChange: (id: string) => void }) {
  const { userId } = useUser();
  const sessions = useSessions(userId);
  const create = useCreateSession(userId);
  const [title, setTitle] = useState("");

  useEffect(() => {
    if (!sessionId && sessions.data?.length) onChange(sessions.data[0].session_id);
  }, [sessionId, sessions.data, onChange]);

  if (sessions.error instanceof ApiError && sessions.error.status === 404) return <CreateUser userId={userId} />;
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-sm">
        <span className="text-moss block">Session</span>
        <select value={sessionId ?? ""} onChange={(e) => onChange(e.target.value)}
                className="border-rule mt-1 min-w-64 rounded border bg-white px-2 py-1.5">
          {!sessions.data?.length && <option value="">No sessions yet</option>}
          {sessions.data?.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.title} ({new Date(s.created_at).toLocaleDateString()}{s.status === "ended" ? ", ended" : ""})
            </option>
          ))}
        </select>
      </label>
      <form className="flex items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        create.mutate(title.trim() || `Session ${(sessions.data?.length ?? 0) + 1}`,
          { onSuccess: (s) => { setTitle(""); onChange(s.session_id); } });
      }}>
        <label className="text-sm">
          <span className="text-moss block">New session title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. The army years"
                 className="border-rule mt-1 rounded border bg-white px-2 py-1.5" />
        </label>
        <button disabled={create.isPending} className="bg-ink rounded px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          Start session
        </button>
      </form>
      {sessions.error && !(sessions.error instanceof ApiError && sessions.error.status === 404) &&
        <Notice tone="error">Sessions couldn't be loaded: {errorText(sessions.error)}</Notice>}
      {create.error && <Notice tone="error">{errorText(create.error)}</Notice>}
    </div>
  );
}
