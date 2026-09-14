import type { ReactNode } from "react";

export function Card({ title, children, tone }: { title: string; children: ReactNode; tone?: "planning" | "nutrition" }) {
  const bar = tone === "planning" ? "border-l-planning" : tone === "nutrition" ? "border-l-nutrition" : "border-l-accent";
  return (
    <section className={`rounded-lg border border-line border-l-4 ${bar} bg-surface-2 p-3`}>
      <h2 className="text-xs font-medium uppercase tracking-wide text-ink-2">{title}</h2>
      <div className="mt-1 text-sm">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-ink-2">{children}</p>;
}

export function Skeleton() {
  return <div data-testid="card-skeleton" className="h-24 animate-pulse rounded-lg border border-line bg-surface-2" />;
}
