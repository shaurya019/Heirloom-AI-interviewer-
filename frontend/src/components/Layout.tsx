import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useUser } from "../lib/user";

const TABS = [
  { to: "/interview", label: "Interview" },
  { to: "/tree", label: "Summary tree" },
  { to: "/memories", label: "Memory explorer" },
  { to: "/timeline", label: "Life timeline" },
  { to: "/chapters", label: "Chapters" },
];

export function Layout() {
  const { userId, setUserId } = useUser();
  const [draft, setDraft] = useState(userId);
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <nav aria-label="Main" className="border-rule bg-sheet md:w-56 md:shrink-0 md:border-r">
        <div className="px-5 pt-6 pb-4">
          <p className="font-serif text-2xl font-semibold tracking-tight">Heirloom</p>
          <p className="text-moss mt-1 text-sm">Stories, kept.</p>
        </div>
        <ul className="flex gap-1 overflow-x-auto px-3 md:flex-col md:gap-0 md:px-0">
          {TABS.map((t) => (
            <li key={t.to}>
              <NavLink to={t.to} className={({ isActive }) =>
                `block whitespace-nowrap px-5 py-2.5 text-[15px] md:-mr-px md:border-y md:border-l ${isActive
                  ? "bg-paper border-rule text-ink font-semibold md:rounded-l-md"
                  : "text-ink-soft hover:text-ink border-transparent"}`}>
                {t.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <form className="mt-6 hidden px-5 pb-6 md:block"
              onSubmit={(e) => { e.preventDefault(); if (draft.trim()) setUserId(draft.trim()); }}>
          <label htmlFor="uid" className="text-moss text-sm">Narrator ID</label>
          <div className="mt-1 flex gap-2">
            <input id="uid" value={draft} onChange={(e) => setDraft(e.target.value)}
                   className="border-rule w-full rounded border bg-white px-2 py-1 text-sm" />
            <button className="text-carbon text-sm font-semibold">Open</button>
          </div>
        </form>
      </nav>
      <main className="min-w-0 flex-1 px-5 py-6 md:px-10 md:py-8">
        <Outlet />
      </main>
    </div>
  );
}
