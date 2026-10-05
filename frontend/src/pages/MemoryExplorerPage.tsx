import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { useSearch } from "../api/hooks";
import { MEMORY_TYPES, type MemoryType, type SearchRequest } from "../api/types";
import { MemoryPeek } from "../components/MemoryPeek";
import { Notice, errorText } from "../components/Notice";
import { ScoreBar } from "../components/ScoreBar";
import { useDebounced } from "../lib/hooks";
import { SCORE_COLOR, TYPE_COLOR, years } from "../lib/tokens";
import { useUser } from "../lib/user";

const DEFAULTS = { w_sim: 0.6, w_rec: 0.2, w_imp: 0.2, decay: 0.05 };

export function MemoryExplorerPage() {
  const { userId } = useUser();
  const reduce = useReducedMotion();
  const [query, setQuery] = useState("times he felt afraid");
  const [types, setTypes] = useState<MemoryType[]>([]);
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [w, setW] = useState(DEFAULTS);
  const [topK, setTopK] = useState(10);
  const [minScore, setMinScore] = useState(0);
  const [peek, setPeek] = useState<string | null>(null);

  const req: SearchRequest = useMemo(() => ({
    query, top_k: topK, min_score: minScore, weights: w,
    filters: {
      user_id: userId, types: types.length ? types : null,
      created_from: createdFrom ? new Date(createdFrom).toISOString() : null,
      created_to: createdTo ? new Date(`${createdTo}T23:59:59`).toISOString() : null,
      event_year_from: yearFrom ? Number(yearFrom) : null, event_year_to: yearTo ? Number(yearTo) : null,
    },
  }), [query, topK, minScore, w, userId, types, createdFrom, createdTo, yearFrom, yearTo]);
  const debounced = useDebounced(req, 250);
  const search = useSearch(debounced);

  // rank movement relative to the previous result set
  const prevRanks = useRef(new Map<string, number>());
  const lastData = useRef<typeof search.data>(undefined);
  const deltas = useMemo(() => {
    const d = new Map<string, number | "new">();
    if (!search.data) return d;
    if (lastData.current && lastData.current !== search.data) {
      prevRanks.current = new Map(lastData.current.results.map((r) => [r.memory.memory_id, r.rank]));
    }
    lastData.current = search.data;
    for (const r of search.data.results) {
      const p = prevRanks.current.get(r.memory.memory_id);
      d.set(r.memory.memory_id, p === undefined ? (prevRanks.current.size ? "new" : 0) : p - r.rank);
    }
    return d;
  }, [search.data]);
  const maxScore = Math.max(1, ...(search.data?.results.map((r) => r.breakdown.final_score) ?? [1]));
  const sumW = w.w_sim + w.w_rec + w.w_imp;

  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Memory explorer</h1>
      <p className="text-ink-soft mt-1 max-w-[70ch]">Search the archive and tune how much meaning, recency and importance count. Results re-rank as you move the sliders.</p>
      <div className="mt-6 grid gap-8 xl:grid-cols-[320px_minmax(0,1fr)]">
        <form aria-label="Search controls" onSubmit={(e) => e.preventDefault()} className="space-y-5">
          <label className="block text-sm"><span className="text-moss">Search for</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} className="border-rule mt-1 w-full rounded border bg-white px-3 py-2 text-base" /></label>
          <fieldset><legend className="text-moss text-sm">Types</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {MEMORY_TYPES.map((t) => {
                const on = types.includes(t);
                return (
                  <button key={t} type="button" aria-pressed={on}
                          onClick={() => setTypes(on ? types.filter((x) => x !== t) : [...types, t])}
                          className={`rounded-full border px-3 py-1 text-sm ${on ? "text-white" : "border-rule bg-white"}`}
                          style={on ? { background: TYPE_COLOR[t], borderColor: TYPE_COLOR[t] } : undefined}>{t}</button>
                );
              })}
            </div></fieldset>
          <fieldset className="grid grid-cols-2 gap-2"><legend className="text-moss col-span-2 text-sm">Recorded between</legend>
            <input type="date" aria-label="Recorded from" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} className="border-rule rounded border bg-white px-2 py-1 text-sm" />
            <input type="date" aria-label="Recorded to" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} className="border-rule rounded border bg-white px-2 py-1 text-sm" />
          </fieldset>
          <fieldset className="grid grid-cols-2 gap-2"><legend className="text-moss col-span-2 text-sm">Happened between (years)</legend>
            <input inputMode="numeric" aria-label="From year" placeholder="1950" value={yearFrom} onChange={(e) => setYearFrom(e.target.value.replace(/\D/g, "").slice(0, 4))} className="border-rule rounded border bg-white px-2 py-1 text-sm" />
            <input inputMode="numeric" aria-label="To year" placeholder="2025" value={yearTo} onChange={(e) => setYearTo(e.target.value.replace(/\D/g, "").slice(0, 4))} className="border-rule rounded border bg-white px-2 py-1 text-sm" />
          </fieldset>
          <fieldset className="space-y-3"><legend className="text-moss text-sm">Weights</legend>
            <Slider label="Meaning" color={SCORE_COLOR.similarity} value={w.w_sim} onChange={(v) => setW({ ...w, w_sim: v })} />
            <Slider label="Recency" color={SCORE_COLOR.recency} value={w.w_rec} onChange={(v) => setW({ ...w, w_rec: v })} />
            <Slider label="Importance" color={SCORE_COLOR.importance} value={w.w_imp} onChange={(v) => setW({ ...w, w_imp: v })} />
            <Slider label="Recency fades per day" value={w.decay} max={0.3} step={0.005} onChange={(v) => setW({ ...w, decay: v })}
                    hint={w.decay > 0 ? `half-life ${(Math.log(2) / w.decay).toFixed(0)} days` : "never fades"} />
            {sumW === 0 && <Notice tone="error">Set at least one weight above zero.</Notice>}
            <button type="button" onClick={() => setW(DEFAULTS)} className="text-carbon text-sm font-semibold">Reset weights</button>
          </fieldset>
          <div className="grid grid-cols-2 gap-3">
            <Slider label="Results" value={topK} min={1} max={30} step={1} onChange={setTopK} fmt={(v) => `${v}`} />
            <Slider label="Minimum score" value={minScore} max={1} step={0.01} onChange={setMinScore} />
          </div>
        </form>

        <section aria-label="Results" className="min-w-0">
          {search.error && <Notice tone="error">Search failed: {errorText(search.error)}</Notice>}
          {!query.trim() && <Notice>Type something to search, such as a person, a place or a feeling.</Notice>}
          {search.data && (
            <>
              <p className="text-moss text-sm">{search.isFetching ? "Re-ranking…" : `${search.data.results.length} results`} · checked {search.data.stats.candidates_returned} candidates</p>
              <ul className="mt-3 flex gap-4 text-sm">
                {Object.entries(SCORE_COLOR).map(([k, c]) => <li key={k} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{k}</li>)}
              </ul>
              {search.data.results.length === 0 && <Notice>No memories match. Try lowering the minimum score or clearing filters.</Notice>}
              <table className="mt-3 w-full border-collapse text-left">
                <thead className="text-moss text-sm"><tr className="border-rule border-b">
                  <th className="py-2 pr-2 font-normal">Rank</th><th className="py-2 pr-4 font-normal">Memory</th>
                  <th className="py-2 pr-2 font-normal">When</th><th className="py-2 font-normal">Score</th></tr></thead>
                <tbody>
                  <AnimatePresence initial={false}>
                    {search.data.results.map((r) => {
                      const d = deltas.get(r.memory.memory_id);
                      return (
                        <motion.tr key={r.memory.memory_id} layout={!reduce} initial={reduce ? false : { opacity: 0 }}
                                   animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}
                                   className="border-rule border-b align-top">
                          <td className="py-3 pr-2">
                            <span className="font-semibold">{r.rank}</span>
                            {d === "new" && <span className="text-carbon ml-1 text-xs">new</span>}
                            {typeof d === "number" && d > 0 && <span className="ml-1 text-xs text-[#2e7d5b]" aria-label={`up ${d}`}>↑{d}</span>}
                            {typeof d === "number" && d < 0 && <span className="text-danger ml-1 text-xs" aria-label={`down ${-d}`}>↓{-d}</span>}
                          </td>
                          <td className="py-3 pr-4">
                            <button onClick={() => setPeek(r.memory.memory_id)} className="story text-left hover:underline">{r.memory.text}</button>
                            <p className="text-moss mt-1 text-sm">
                              <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[r.memory.type] }} />
                              {r.memory.type} · importance {r.memory.importance.toFixed(2)} · recorded {r.breakdown.age_days.toFixed(0)} days ago · meaning {r.breakdown.similarity.toFixed(2)}
                            </p>
                          </td>
                          <td className="py-3 pr-2 text-sm whitespace-nowrap">{years(r.memory.event_year_start, r.memory.event_year_end)}</td>
                          <td className="py-3"><ScoreBar b={r.breakdown} max={maxScore} /></td>
                        </motion.tr>
                      );
                    })}
                  </AnimatePresence>
                </tbody>
              </table>
            </>
          )}
          {peek && <div className="mt-4"><MemoryPeek memoryId={peek} onClose={() => setPeek(null)} /></div>}
        </section>
      </div>
    </div>
  );
}

function Slider({ label, value, onChange, min = 0, max = 1, step = 0.05, color, hint, fmt = (v: number) => v.toFixed(2) }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number;
  color?: string; hint?: string; fmt?: (v: number) => string;
}) {
  return (
    <label className="block text-sm">
      <span className="flex items-center gap-2">
        {color && <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />}
        {label}<span className="ml-auto font-semibold">{fmt(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-1 w-full" />
      {hint && <span className="text-moss">{hint}</span>}
    </label>
  );
}
