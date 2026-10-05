import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { Notice, errorText } from "./Notice";

export function CreateUser({ userId }: { userId: string }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [birth, setBirth] = useState("");
  const m = useMutation({
    mutationFn: () => api.createUser({ user_id: userId, name, birth_year: birth ? Number(birth) : null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.sessions(userId) }),
  });
  return (
    <section className="border-rule bg-sheet max-w-xl rounded-md border p-5">
      <h2 className="font-serif text-xl">Add a narrator</h2>
      <p className="text-ink-soft mt-1 text-sm">There's no narrator with ID “{userId}” yet. Add them to begin interviewing.</p>
      <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (name.trim()) m.mutate(); }}>
        <label className="text-sm"><span className="text-moss block">Full name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)} className="border-rule mt-1 rounded border bg-white px-2 py-1.5" /></label>
        <label className="text-sm"><span className="text-moss block">Birth year</span>
          <input inputMode="numeric" value={birth} onChange={(e) => setBirth(e.target.value.replace(/\D/g, "").slice(0, 4))}
                 className="border-rule mt-1 w-24 rounded border bg-white px-2 py-1.5" /></label>
        <button disabled={m.isPending} className="bg-ink rounded px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Add narrator</button>
      </form>
      {m.error && <Notice tone="error">{errorText(m.error)}</Notice>}
    </section>
  );
}
