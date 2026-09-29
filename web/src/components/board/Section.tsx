import type { ReactNode } from "react";

export default function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-line px-6 py-5 text-sm">
      <h2 className="text-xs font-medium tracking-wider text-ink-2 uppercase">{title}</h2>
      <div className="mt-2 space-y-1">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-ink-2">{children}</p>;
}
