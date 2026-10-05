import type { ReactNode } from "react";

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "attention"; children: ReactNode }) {
  const cls = tone === "error" ? "border-danger/40 text-danger bg-white"
    : tone === "attention" ? "border-manila bg-manila-soft text-ink" : "border-rule bg-sheet text-ink-soft";
  return <div role={tone === "error" ? "alert" : "status"} className={`mt-3 rounded border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong.";
}
