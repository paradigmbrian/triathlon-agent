import type { ReasonOut, VerdictOut } from "../../api/queries";
import { day } from "../../lib/format";

const WORD = { go: "GO", easy: "EASY", rest: "REST", none: "NO CALL" } as const;
const TONE = { go: "text-go", easy: "text-easy", rest: "text-rest", none: "text-ink-2" } as const;
const CHIP = { stop: "border-rest/70 text-rest", caution: "border-easy/70 text-easy", info: "border-line text-ink-2" } as const;

type Props = { verdict: VerdictOut; active: string | null; onActive: (key: string | null) => void };

function Chip({ r, active, onActive }: { r: ReasonOut; active: boolean; onActive: Props["onActive"] }) {
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

export default function VerdictStrip({ verdict: v, active, onActive }: Props) {
  return (
    <section aria-label="Today's call" className="border-b border-line px-6 pt-6 pb-5">
      <div role="status" className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span className={`text-5xl leading-none font-semibold tracking-[0.14em] ${TONE[v.call]}`}>{WORD[v.call]}</span>
        {v.stale && v.based_on && <span className="text-sm text-ink-2">based on {day(v.based_on)}</span>}
        {v.session_done && <span className="text-sm text-ink-2">session done, recover</span>}
      </div>
      {v.call === "go" ? (
        <p className="mt-3 text-sm text-ink-2">All conditions within your limits</p>
      ) : (
        v.reasons.length > 0 && (
          <ul aria-label="Reasons" className="mt-3 flex flex-wrap gap-2">
            {v.reasons.map((r) => (
              <Chip key={r.key} r={r} active={active === r.key} onActive={onActive} />
            ))}
          </ul>
        )
      )}
      {v.harder_than_call && <p className="mt-3 text-sm text-easy">planned session is harder than today's call</p>}
    </section>
  );
}
