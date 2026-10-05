import { useMemory } from "../api/hooks";
import { TYPE_COLOR, years } from "../lib/tokens";
import { Notice } from "./Notice";

export function MemoryPeek({ memoryId, onClose }: { memoryId: string; onClose: () => void }) {
  const { data: m, error, isLoading } = useMemory(memoryId);
  return (
    <aside aria-label="Memory" className="border-rule bg-white rounded-md border p-4 shadow-[0_1px_0_#d5dbd3]">
      <div className="flex items-start justify-between gap-4">
        <p className="text-moss text-sm">Memory {memoryId.slice(-8)}</p>
        <button onClick={onClose} className="text-carbon text-sm font-semibold">Close</button>
      </div>
      {isLoading && <p className="text-moss mt-2 text-sm">Loading…</p>}
      {error && <Notice tone="error">This memory couldn't be loaded. It may have been deleted.</Notice>}
      {m && (
        <>
          <p className="story mt-2 text-[17px]">{m.text}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-moss">Type</dt>
            <dd><span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[m.type] }} />{m.type}</dd>
            <dt className="text-moss">When</dt><dd>{years(m.event_year_start, m.event_year_end)}</dd>
            <dt className="text-moss">Importance</dt><dd>{m.importance.toFixed(2)} — {m.importance_rationale || "no rationale"}</dd>
            {m.entities.length > 0 && (<><dt className="text-moss">Mentions</dt><dd>{m.entities.join(", ")}</dd></>)}
          </dl>
        </>
      )}
    </aside>
  );
}
