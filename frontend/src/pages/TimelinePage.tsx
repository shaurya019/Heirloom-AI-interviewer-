import { useMemo, useState } from "react";
import { useGaps, useMemories } from "../api/hooks";
import type { MemoryRecord } from "../api/types";
import { MemoryPeek } from "../components/MemoryPeek";
import { Notice, errorText } from "../components/Notice";
import { MEMORY_TYPES } from "../api/types";
import { TYPE_COLOR } from "../lib/tokens";
import { useUser } from "../lib/user";

const DOT = 9, GAP = 3, PAD_L = 8, PAD_B = 28, MAX_SPAN = 10;

export function TimelinePage() {
  const { userId } = useUser();
  const memories = useMemories(userId);
  const gaps = useGaps(userId);
  const [peek, setPeek] = useState<string | null>(null);

  const { byYear, start, end, undated, longSpan } = useMemo(() => {
    const byYear = new Map<number, MemoryRecord[]>();
    const undated: MemoryRecord[] = [], longSpan: MemoryRecord[] = [];
    for (const m of memories.data ?? []) {
      if (m.event_year_start === null) { undated.push(m); continue; }
      const e = m.event_year_end ?? m.event_year_start;
      if (e - m.event_year_start + 1 > MAX_SPAN) { longSpan.push(m); continue; }
      byYear.set(m.event_year_start, [...(byYear.get(m.event_year_start) ?? []), m]);
    }
    const ys = [...byYear.keys()];
    const start = Math.min(gaps.data?.span_start ?? Infinity, ...ys);
    const end = Math.max(gaps.data?.span_end ?? -Infinity, ...ys);
    return { byYear, start, end, undated, longSpan };
  }, [memories.data, gaps.data]);

  if (memories.error) return <Notice tone="error">The timeline couldn't be loaded: {errorText(memories.error)}</Notice>;
  const ready = memories.data && Number.isFinite(start);
  const colW = DOT + 5;
  const maxStack = Math.max(4, ...[...byYear.values()].map((v) => v.length));
  const height = maxStack * (DOT + GAP) + PAD_B + 8;
  const width = ready ? (end - start + 1) * colW + PAD_L * 2 : 0;
  const x = (y: number) => PAD_L + (y - start) * colW;

  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Life timeline</h1>
      <p className="text-ink-soft mt-1 max-w-[70ch]">Every dated memory, placed in the year it happened. Shaded stretches are years nobody has asked about yet.</p>
      {memories.isLoading && <p className="text-moss mt-4">Loading memories…</p>}
      {memories.data?.length === 0 && <Notice>No memories yet. They appear here as the interview goes on.</Notice>}
      {ready && (
        <>
          <ul className="mt-4 flex flex-wrap gap-4 text-sm">
            {MEMORY_TYPES.map((t) => <li key={t} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLOR[t] }} />{t}</li>)}
            <li className="flex items-center gap-1.5"><span className="bg-manila-soft border-manila h-2.5 w-4 border" />not yet covered</li>
          </ul>
          <div className="border-rule mt-3 overflow-x-auto rounded-md border bg-white p-3">
            <svg width={width} height={height} role="img" aria-label={`Memories from ${start} to ${end}`}>
              <defs>
                <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect width="6" height="6" fill="#f3e3bd" /><line x1="0" y1="0" x2="0" y2="6" stroke="#d9a441" strokeWidth="1.5" />
                </pattern>
              </defs>
              {gaps.data?.gaps.map((g) => (
                <g key={g.start}>
                  <rect x={x(g.start) - 2} y={0} width={(g.end - g.start + 1) * colW} height={height - PAD_B} fill="url(#hatch)" opacity={0.8} />
                  <title>{`${g.start}–${g.end}: no stories yet`}</title>
                </g>
              ))}
              {[...byYear.entries()].map(([year, ms]) =>
                ms.map((m, i) => (
                  <circle key={m.memory_id} cx={x(year) + DOT / 2} cy={height - PAD_B - DOT / 2 - i * (DOT + GAP)} r={DOT / 2}
                          fill={TYPE_COLOR[m.type]} opacity={0.35 + 0.65 * m.importance} tabIndex={0} role="button"
                          aria-label={`${year}: ${m.text}`} className="cursor-pointer"
                          onClick={() => setPeek(m.memory_id)} onKeyDown={(e) => e.key === "Enter" && setPeek(m.memory_id)}>
                    <title>{`${year} · ${m.text}`}</title>
                  </circle>
                )))}
              <line x1={PAD_L} x2={width - PAD_L} y1={height - PAD_B + 2} y2={height - PAD_B + 2} stroke="#d5dbd3" />
              {Array.from({ length: end - start + 1 }, (_, i) => start + i).filter((y) => y % 5 === 0).map((y) => (
                <text key={y} x={x(y)} y={height - 8} fontSize="11" fill="#6f7f72" fontFamily="Public Sans">{y}</text>
              ))}
            </svg>
          </div>
          <p className="text-moss mt-2 text-sm">{longSpan.length} long-running memories (spanning more than {MAX_SPAN} years) and {undated.length} undated memories aren't plotted.</p>
          {peek && <div className="mt-4 max-w-2xl"><MemoryPeek memoryId={peek} onClose={() => setPeek(null)} /></div>}
          {gaps.data && gaps.data.suggestions.length > 0 && (
            <section className="mt-8 max-w-[72ch]">
              <h2 className="font-serif text-xl">Ask about next</h2>
              <ul className="mt-2 space-y-3">
                {gaps.data.suggestions.map((s) => (
                  <li key={s.topic} className="border-manila border-l-4 bg-white px-4 py-2">
                    <p className="story">{s.question}</p><p className="text-moss text-sm">{s.reason}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {gaps.error && <Notice tone="error">Gap analysis unavailable: {errorText(gaps.error)}</Notice>}
        </>
      )}
    </div>
  );
}
