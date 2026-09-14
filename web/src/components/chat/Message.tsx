import type { ReactNode } from "react";

const tagColor: Record<string, string> = { planning: "text-planning", nutrition: "text-nutrition", analyst: "text-ink-2" };

export function Bubble({ role, where, children }: { role: "user" | "assistant" | "consult" | "report" | "error"; where?: string | null; children: ReactNode }) {
  if (role === "user") {
    return <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent/15 px-3 py-2 text-sm">{children}</div>;
  }
  if (role === "report") {
    return <pre className="my-1 whitespace-pre-wrap rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs text-ink-2">{children}</pre>;
  }
  if (role === "error") {
    return <div className="my-1 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{children}</div>;
  }
  const tag = where && where !== "coach" ? where : null;
  return (
    <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-surface-2 px-3 py-2 text-sm ${role === "consult" ? "border border-line font-mono text-xs" : ""}`}>
      {tag && <span className={`mr-2 text-[11px] font-medium uppercase ${tagColor[tag] ?? "text-ink-2"}`}>{tag}</span>}
      {children}
    </div>
  );
}
