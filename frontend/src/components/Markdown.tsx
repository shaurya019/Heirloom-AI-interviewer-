import { Fragment, type ReactNode } from "react";

/** Minimal renderer for chapter markdown: headings, paragraphs, *italic*, **bold**, and [m:<id>] citations. */
export function Markdown({ text, onCite, cited }: { text: string; onCite: (id: string) => void; cited?: string[] }) {
  const order = new Map((cited ?? []).map((id, i) => [id, i + 1]));
  const inline = (s: string, key: string): ReactNode[] =>
    s.split(/(\[m:[A-Za-z0-9]+\]|\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => {
      const k = `${key}-${i}`;
      const cite = part.match(/^\[m:([A-Za-z0-9]+)\]$/);
      if (cite) {
        const n = order.get(cite[1]) ?? "•";
        return (
          <button key={k} onClick={() => onCite(cite[1])} aria-label={`Show source memory ${n}`}
                  className="text-carbon mx-0.5 align-super font-sans text-[11px] font-semibold hover:underline">
            {n}
          </button>
        );
      }
      if (part.startsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
      if (part.startsWith("*") && part.length > 2) return <em key={k}>{part.slice(1, -1)}</em>;
      return <Fragment key={k}>{part}</Fragment>;
    });
  return (
    <div className="story max-w-[68ch] text-[18px]">
      {text.split(/\n{2,}/).map((block, i) => {
        const t = block.trim();
        if (t.startsWith("# ")) return <h2 key={i} className="mb-4 text-3xl font-semibold leading-tight">{t.slice(2)}</h2>;
        if (t.startsWith("## ")) return <h3 key={i} className="mt-6 mb-2 text-xl font-semibold">{t.slice(3)}</h3>;
        return <p key={i} className="mb-4">{inline(t, `p${i}`)}</p>;
      })}
    </div>
  );
}
