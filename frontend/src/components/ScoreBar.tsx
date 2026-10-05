import type { ScoreBreakdown } from "../api/types";
import { SCORE_COLOR } from "../lib/tokens";

export function ScoreBar({ b, max = 1 }: { b: ScoreBreakdown; max?: number }) {
  const parts = [
    ["similarity", b.weighted_components.similarity],
    ["recency", b.weighted_components.recency],
    ["importance", b.weighted_components.importance],
  ] as const;
  return (
    <div className="flex items-center gap-3">
      <div className="bg-sheet border-rule flex h-3 w-40 overflow-hidden rounded-sm border"
           role="img" aria-label={`score ${b.final_score.toFixed(3)}`}>
        {parts.map(([k, v]) => (
          <div key={k} title={`${k}: ${v.toFixed(3)}`} style={{ width: `${(v / max) * 100}%`, background: SCORE_COLOR[k] }} />
        ))}
      </div>
      <span className="w-12 text-right text-sm font-semibold">{b.final_score.toFixed(3)}</span>
    </div>
  );
}
