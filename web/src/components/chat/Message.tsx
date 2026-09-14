import type { ReactNode } from "react";

const tagColor: Record<string, string> = { planning: "text-planning", nutrition: "text-nutrition", analyst: "text-ink-2" };

export function Bubble({ role, where, children }: { role: "user" | "assistant" | "consult" | "report" | "error"; where?: string | null; children: ReactNode }) {
  if (role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm border border-accent/30 bg-accent/15 px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap">
        {children}
      </div>
    );
  }
  if (role === "report") {
    return <pre className="rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-2">{children}</pre>;
  }
  if (role === "error") {
    return <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{children}</div>;
  }
  const tag = where && where !== "coach" ? where : null;
  return (
    <div
      className={`max-w-[85%] rounded-2xl rounded-bl-sm border border-line bg-surface-2 px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap ${role === "consult" ? "font-mono text-xs text-ink-2" : ""}`}
    >
      {tag && <span className={`mr-2 text-[11px] font-semibold tracking-wide uppercase ${tagColor[tag] ?? "text-ink-2"}`}>{tag}</span>}
      {children}
    </div>
  );
}
