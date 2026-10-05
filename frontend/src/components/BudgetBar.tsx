import type { ContextSlot } from "../api/types";
import { SLOT_META } from "../lib/tokens";

/** Signature visual: how this turn's prompt budget is spent, slot by slot, in priority order. */
export function BudgetBar({ slots, budget, total }: { slots: ContextSlot[]; budget: number; total: number }) {
  return (
    <figure>
      <div className="flex items-baseline justify-between">
        <figcaption className="font-serif text-lg">What Heirloom is remembering</figcaption>
        <span className="text-moss text-sm">{total.toLocaleString()} of {budget.toLocaleString()} tokens</span>
      </div>
      <div role="img" aria-label={`Prompt uses ${total} of ${budget} tokens`}
           className="bg-sheet border-rule mt-2 flex h-5 overflow-hidden rounded-sm border">
        {slots.map((s) => s.tokens > 0 && (
          <div key={s.name} title={`${SLOT_META[s.name].label}: ${s.tokens} tokens`}
               style={{ width: `${(s.tokens / budget) * 100}%`, background: SLOT_META[s.name].color }} />
        ))}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {slots.map((s) => (
          <li key={s.name} className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: SLOT_META[s.name].color }} />
            <span className="truncate">{SLOT_META[s.name].label}</span>
            <span className="text-moss ml-auto">{s.tokens}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
