import { useState } from "react";
import { useChapters, useWriteChapter } from "../api/hooks";
import { Markdown } from "../components/Markdown";
import { MemoryPeek } from "../components/MemoryPeek";
import { Notice, errorText } from "../components/Notice";
import { useUser } from "../lib/user";

export function ChaptersPage() {
  const { userId } = useUser();
  const chapters = useChapters(userId);
  const write = useWriteChapter(userId);
  const [mode, setMode] = useState<"theme" | "era">("era");
  const [theme, setTheme] = useState("");
  const [eraStart, setEraStart] = useState("1978");
  const [eraEnd, setEraEnd] = useState("1985");
  const [title, setTitle] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [peek, setPeek] = useState<string | null>(null);
  const current = chapters.data?.find((c) => c.chapter_id === openId) ?? chapters.data?.[0];

  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Chapters</h1>
      <p className="text-ink-soft mt-1 max-w-[70ch]">Draft a memoir chapter from the archive. Every sourced sentence links back to the memory it came from.</p>
      <form className="mt-5 flex flex-wrap items-end gap-3" onSubmit={(e) => {
        e.preventDefault();
        write.mutate(mode === "theme" ? { theme, title: title || null }
          : { era_start: eraStart ? Number(eraStart) : null, era_end: eraEnd ? Number(eraEnd) : null, title: title || null },
          { onSuccess: (c) => setOpenId(c.chapter_id) });
      }}>
        <fieldset className="flex gap-3 text-sm"><legend className="sr-only">Write about</legend>
          <label><input type="radio" checked={mode === "era"} onChange={() => setMode("era")} /> A period</label>
          <label><input type="radio" checked={mode === "theme"} onChange={() => setMode("theme")} /> A theme</label>
        </fieldset>
        {mode === "theme" ? (
          <label className="text-sm"><span className="text-moss block">Theme</span>
            <input required value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="e.g. courage, the store" className="border-rule mt-1 rounded border bg-white px-2 py-1.5" /></label>
        ) : (
          <>
            <label className="text-sm"><span className="text-moss block">From year</span>
              <input value={eraStart} onChange={(e) => setEraStart(e.target.value.replace(/\D/g, "").slice(0, 4))} className="border-rule mt-1 w-24 rounded border bg-white px-2 py-1.5" /></label>
            <label className="text-sm"><span className="text-moss block">To year</span>
              <input value={eraEnd} onChange={(e) => setEraEnd(e.target.value.replace(/\D/g, "").slice(0, 4))} className="border-rule mt-1 w-24 rounded border bg-white px-2 py-1.5" /></label>
          </>
        )}
        <label className="text-sm"><span className="text-moss block">Title (optional)</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="border-rule mt-1 rounded border bg-white px-2 py-1.5" /></label>
        <button disabled={write.isPending} className="bg-ink rounded px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {write.isPending ? "Drafting chapter…" : "Draft chapter"}
        </button>
      </form>
      {write.error && <Notice tone="error">The chapter wasn't drafted: {errorText(write.error)}</Notice>}
      {chapters.error && <Notice tone="error">Chapters couldn't be loaded: {errorText(chapters.error)}</Notice>}
      {chapters.data?.length === 0 && <Notice>No chapters yet. Choose a period or theme above and draft the first one.</Notice>}
      {current && (
        <div className="mt-8 grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)_340px]">
          <nav aria-label="Chapters"><ul className="space-y-1">
            {chapters.data?.map((c) => (
              <li key={c.chapter_id}><button onClick={() => { setOpenId(c.chapter_id); setPeek(null); }}
                className={`w-full rounded px-2 py-1.5 text-left text-sm ${c.chapter_id === current.chapter_id ? "bg-white font-semibold" : "text-ink-soft"}`}>
                {c.title}<span className="text-moss block text-xs">{new Date(c.created_at).toLocaleString()}</span></button></li>
            ))}
          </ul></nav>
          <article>
            <Markdown text={current.markdown} cited={current.citations} onCite={setPeek} />
            <p className="text-moss mt-4 text-sm">{current.citations.length} memories cited{current.invalid_citations_removed ? `, ${current.invalid_citations_removed} unsupported citations removed` : ""} · {current.model}</p>
          </article>
          <aside className="lg:sticky lg:top-6 lg:self-start">
            {peek ? <MemoryPeek memoryId={peek} onClose={() => setPeek(null)} /> : <Notice>Select a citation number to see the memory behind it.</Notice>}
          </aside>
        </div>
      )}
    </div>
  );
}
