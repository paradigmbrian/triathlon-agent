import type { ReasonOut, VerdictOut } from "../../api/queries";
import { day } from "../../lib/format";

const STEPS = [
  ["poor", "Poor"],
  ["low", "Low"],
  ["moderate", "Moderate"],
  ["high", "High"],
  ["prime", "Prime"],
] as const;
const WORD = { poor: "POOR", low: "LOW", moderate: "MODERATE", high: "HIGH", prime: "PRIME", none: "NO READING" } as const;
// The word and the lit step carry the level; colour only adds to them.
const TONE = {
  poor: { text: "text-rest", bar: "bg-rest" },
  low: { text: "text-rest", bar: "bg-rest" },
  moderate: { text: "text-easy", bar: "bg-easy" },
  high: { text: "text-go", bar: "bg-go" },
  prime: { text: "text-go", bar: "bg-go" },
  none: { text: "text-ink-2", bar: "bg-line" },
} as const;
const CHIP = { stop: "border-rest/70 text-rest", caution: "border-easy/70 text-easy", info: "border-line text-ink-2" } as const;

type Props = { verdict: VerdictOut; active: string | null; onActive: (key: string | null) => void };

function Chip({ r, active, onActive }: { r: ReasonOut; active: boolean; onActive: Props["onActive"] }) {
  if (r.severity === "info") {
    // Nothing to trace: an info reason explains the level itself, so it is text, not a button.
    return (
      <li id={`reason-${r.key}`} className={`inline-flex min-h-7 items-center rounded-full border px-3 text-sm ${CHIP.info}`}>
        {r.text}
      </li>
    );
  }
  const toRow = () => {
    const row = document.getElementById(`cond-${r.key}`);
    row?.scrollIntoView?.({ block: "nearest" });
    row?.focus();
  };
  return (
    <li>
      <button
        type="button"
        id={`reason-${r.key}`}
        data-active={active}
        onClick={toRow}
        onMouseEnter={() => onActive(r.key)}
        onMouseLeave={() => onActive(null)}
        onFocus={() => onActive(r.key)}
        onBlur={() => onActive(null)}
        className={`inline-flex min-h-7 items-center rounded-full border px-3 text-sm tabular-nums ${CHIP[r.severity]} ${active ? "bg-hold/10" : ""}`}
      >
        {r.text}
      </button>
    </li>
  );
}

export default function ReadinessStatus({ verdict: v, active, onActive }: Props) {
  const tone = TONE[v.level];
  const flagged = v.reasons.some((r) => r.severity !== "info");
  return (
    <section aria-label="Readiness" className="mx-6 my-5 rounded-lg border border-line bg-surface-2 px-5 py-4">
      <div role="status" className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-xs font-medium tracking-wider text-ink-2 uppercase">Readiness</span>
        <span className={`text-2xl leading-none font-semibold tracking-[0.12em] ${tone.text}`}>{WORD[v.level]}</span>
        {v.stale && v.based_on && <span className="text-sm text-ink-2">based on {day(v.based_on)}</span>}
        {v.session_done && <span className="text-sm text-ink-2">session done, recover</span>}
      </div>
      <ol aria-label="Readiness scale" className="mt-3 grid max-w-md grid-cols-5 gap-1.5">
        {STEPS.map(([key, label]) => {
          const current = v.level === key;
          return (
            <li key={key} aria-current={current ? "true" : undefined} className="text-xs">
              <div data-bar className={`h-1.5 rounded-full ${current ? tone.bar : "bg-line"}`} />
              <span className={`mt-1 block ${current ? "font-semibold text-ink" : "text-ink-2"}`}>{label}</span>
            </li>
          );
        })}
      </ol>
      {v.level !== "none" && !flagged && <p className="mt-3 text-sm text-ink-2">All conditions within your limits</p>}
      {v.reasons.length > 0 && (
        <ul aria-label="Reasons" className="mt-3 flex flex-wrap gap-2">
          {v.reasons.map((r) => (
            <Chip key={r.key} r={r} active={active === r.key} onActive={onActive} />
          ))}
        </ul>
      )}
      {v.harder_than_call && <p className="mt-3 text-sm text-easy">planned session is harder than today's call</p>}
    </section>
  );
}
