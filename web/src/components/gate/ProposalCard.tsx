import type { ProposalJson } from "./schemaUtils";
import ChangeRow from "./ChangeRow";

export default function ProposalCard({ p }: { p: ProposalJson }) {
  const tone = p.domain === "planning" ? "text-planning" : "text-nutrition";
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-xs">{p.id}</span>
        <span className={`text-xs font-medium uppercase ${tone}`}>{p.domain}</span>
        <span>{p.summary}</span>
      </div>
      {p.question ? (
        <p className="mt-1 text-sm">asked instead of proposing: {p.question}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {p.changes.map((c, i) => (
            <ChangeRow key={i} domain={p.domain} change={c} />
          ))}
        </ul>
      )}
      {p.violations.length > 0 && <p className="mt-1 text-xs text-danger">{p.violations.join("; ")}</p>}
      {p.overrides && <p className="mt-1 text-xs text-ink-2">profile overrides: {JSON.stringify(p.overrides)}</p>}
    </div>
  );
}
