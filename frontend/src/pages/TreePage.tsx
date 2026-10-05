import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useSummaryTree } from "../api/hooks";
import type { SummaryNode } from "../api/types";
import { Notice, errorText } from "../components/Notice";
import { SessionSelect } from "../components/SessionSelect";
import { LEVEL_META } from "../lib/tokens";

export function TreePage() {
  const [params, setParams] = useSearchParams();
  const sessionId = params.get("session") ?? undefined;
  const tree = useSummaryTree(sessionId);
  const [selected, setSelected] = useState<SummaryNode | null>(null);
  return (
    <div>
      <h1 className="font-serif text-3xl font-semibold">Summary tree</h1>
      <p className="text-ink-soft mt-1 max-w-[70ch]">Each conversation is folded into chunks, chunks into sections, and sections into a session summary.</p>
      <div className="mt-4"><SessionSelect sessionId={sessionId} onChange={(id) => { setSelected(null); setParams({ session: id }, { replace: true }); }} /></div>
      {tree.error && <Notice tone="error">The tree couldn't be loaded: {errorText(tree.error)}</Notice>}
      {tree.data && (
        <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
          <section aria-label="Tree">
            <ul className="text-moss mb-3 flex flex-wrap gap-4 text-sm">
              {Object.entries(LEVEL_META).map(([l, m]) => (
                <li key={l} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: m.color }} />{m.label}</li>
              ))}
            </ul>
            {tree.data.roots.length === 0
              ? <Notice>No summaries yet. They appear once the conversation grows past the recent-message budget.</Notice>
              : <ul role="tree">{tree.data.roots.map((n) => <TreeItem key={n.node_id} node={n} selected={selected} onSelect={setSelected} />)}</ul>}
            <div className="border-rule mt-6 border-t pt-4">
              <p className="font-serif text-lg">Running summary</p>
              <p className="text-moss text-sm">{tree.data.rolling_summary_tokens} tokens · verbatim buffer starts at message {tree.data.buffer_start_seq} of {tree.data.msg_count}</p>
              <p className="story mt-2 max-w-[68ch]">{tree.data.rolling_summary || "Nothing has been summarized yet."}</p>
            </div>
          </section>
          <section aria-label="Selected node" className="lg:sticky lg:top-6 lg:self-start">
            {selected ? <NodeDetail node={selected} onSelect={setSelected} /> : <Notice>Select a node to read its summary.</Notice>}
          </section>
        </div>
      )}
    </div>
  );
}

function TreeItem({ node, selected, onSelect }: { node: SummaryNode; selected: SummaryNode | null; onSelect: (n: SummaryNode) => void }) {
  const [open, setOpen] = useState(node.level >= 1);
  const meta = LEVEL_META[node.level];
  const has = node.children.length > 0;
  return (
    <li role="treeitem" aria-expanded={has ? open : undefined} aria-selected={selected?.node_id === node.node_id}>
      <div className={`flex items-center gap-2 rounded px-2 py-1.5 ${selected?.node_id === node.node_id ? "bg-white" : ""}`}>
        <button onClick={() => setOpen(!open)} disabled={!has} aria-label={open ? "Collapse" : "Expand"}
                className="text-moss w-5 text-center disabled:opacity-0">{open ? "−" : "+"}</button>
        <span className="h-3 w-1.5 shrink-0 rounded-sm" style={{ background: meta.color }} />
        <button onClick={() => onSelect(node)} className="min-w-0 flex-1 truncate text-left">
          <span className="font-medium">{node.title || `${meta.label} ${node.first_seq}–${node.last_seq}`}</span>
          <span className="text-moss ml-2 text-sm">{meta.label} · msgs {node.first_seq}–{node.last_seq} · {node.token_count} tokens</span>
        </button>
      </div>
      {has && open && <ul role="group" className="border-rule ml-4 border-l pl-2">
        {node.children.map((c) => <TreeItem key={c.node_id} node={c} selected={selected} onSelect={onSelect} />)}
      </ul>}
    </li>
  );
}

function NodeDetail({ node, onSelect }: { node: SummaryNode; onSelect: (n: SummaryNode) => void }) {
  const meta = LEVEL_META[node.level];
  const ratio = node.source_token_count && node.token_count ? (node.source_token_count / node.token_count).toFixed(1) : null;
  return (
    <article className="border-rule rounded-md border bg-white p-5">
      <p className="text-sm" style={{ color: meta.color === "#b9c3cc" ? "#6f7f72" : meta.color }}>{meta.label}</p>
      <h2 className="font-serif mt-1 text-2xl">{node.title || `Messages ${node.first_seq}–${node.last_seq}`}</h2>
      <p className="text-moss mt-1 text-sm">Messages {node.first_seq}–{node.last_seq} · {node.token_count} tokens{ratio ? ` (compressed ${ratio}×)` : ""}</p>
      <p className="story mt-3">{node.summary}</p>
      {node.children.length > 0 && (
        <>
          <p className="mt-4 text-sm font-semibold">Built from</p>
          <ul className="mt-1 space-y-1 text-sm">
            {node.children.map((c) => (
              <li key={c.node_id}><button className="text-carbon hover:underline" onClick={() => onSelect(c)}>
                {c.title || `${LEVEL_META[c.level].label} ${c.first_seq}–${c.last_seq}`}</button></li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
