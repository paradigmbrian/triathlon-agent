import type { ReactNode } from "react";

export function Card({ title, children, tone }: { title: string; children: ReactNode; tone?: "planning" | "nutrition" }) {
  const bar = tone === "planning" ? "border-l-planning" : tone === "nutrition" ? "border-l-nutrition" : "border-l-accent";
  return (
    <section data-testid="strip-card" className={`h-full rounded-lg border border-line border-l-4 ${bar} bg-surface-2 px-4 py-3`}>
      <h2 className="text-[11px] font-medium uppercase tracking-wider text-ink-2">{title}</h2>
      <div className="mt-2 space-y-1 text-sm">{children}</div>
    </section>
  );
}

/** The one number a card leads with. */
export function Headline({ children }: { children: ReactNode }) {
  return <div className="text-2xl leading-tight font-semibold tabular-nums">{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-ink-2">{children}</p>;
}

export function Skeleton() {
  return <div data-testid="card-skeleton" className="h-28 animate-pulse rounded-lg border border-line bg-surface-2" />;
}
