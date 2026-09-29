import { useState } from "react";
import type { ConditionOut, ReasonOut, TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import LimitMarker from "./LimitMarker";
import Sparkline from "./Sparkline";
import { baselineValue, conditionParts } from "./format";

type Props = {
  readiness: TodayView["readiness"];
  rows: ConditionOut[];
  reasons: ReasonOut[];
  active: string | null;
  onActive: (key: string | null) => void;
};

// A row wears one state, on its rail, its figure and its status word: a flagged row its reason's
// colour, a row inside your band go, one outside your band but not flagged hold, and a row with
// no band word to judge (neutral form, no data, no baseline, a guarded ACWR) nothing. Colour is
// only ever an addition to the status word beside it.
const STATE = {
  stop: { text: "text-rest", rail: "border-rest" },
  caution: { text: "text-easy", rail: "border-easy" },
  info: { text: "text-ink-2", rail: "border-ink-2" },
  go: { text: "text-go", rail: "border-go" },
  hold: { text: "text-hold", rail: "border-hold" },
  plain: { text: "text-ink-2", rail: "border-line" },
} as const;

function stateOf(c: ConditionOut, severity: ReasonOut["severity"] | undefined) {
  if (c.flagged) return STATE[severity ?? "caution"];
  if (c.status === "within") return STATE.go;
  if (["neutral", "no data", "no baseline"].includes(c.status) || c.status.startsWith("ignored")) return STATE.plain;
  return STATE.hold;
}

export default function Conditions({ readiness, rows, reasons, active, onActive }: Props) {
  // Remember the last rows (React's adjust-state-during-render pattern) so only a value that
  // changes after a refetch flashes; the first render flashes nothing.
  const [prevRows, setPrevRows] = useState(rows);
  const [changed, setChanged] = useState<ReadonlySet<string>>(new Set());
  if (rows !== prevRows) {
    const before = new Map(prevRows.map((c) => [c.key, c.value]));
    setChanged(new Set(rows.filter((c) => before.has(c.key) && before.get(c.key) !== c.value).map((c) => c.key)));
    setPrevRows(rows);
  }
  const [view, setView] = useState<"figures" | "trends">("figures");
  const severity = new Map(reasons.map((r) => [r.key, r.severity]));
  const title = readiness && !readiness.is_today ? `Conditions from ${day(readiness.date)}` : "Conditions";
  return (
    <section aria-labelledby="conditions-h" className="border-b border-line px-6 py-5">
      <div className="flex items-center justify-between gap-3">
        <h2 id="conditions-h" className="text-xs font-medium tracking-wider text-ink-2 uppercase">
          {title}
        </h2>
        {rows.length > 0 && (
          <div role="group" aria-label="Conditions view" className="inline-flex overflow-hidden rounded-md border border-line text-xs">
            {([["figures", "Figures"], ["trends", "Trends"]] as const).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={`min-h-7 px-3 ${view === v ? "bg-hold/10 font-medium text-ink" : "text-ink-2 hover:text-ink"}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-ink-2">No Garmin data yet, sync first</p>
      ) : (
        <table className="mt-2 w-full text-sm tabular-nums">
          <thead className="text-left text-xs text-ink-2 max-sm:sr-only">
            <tr>
              <th scope="col" className="py-1.5 font-medium">Condition</th>
              <th scope="col" className="font-medium">Now</th>
              {view === "figures" ? (
                <>
                  <th scope="col" className="font-medium">28-day</th>
                  <th scope="col" className="font-medium"><span className="sr-only">Limit</span></th>
                </>
              ) : (
                <th scope="col" className="font-medium">14 days</th>
              )}
              <th scope="col" className="font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const state = stateOf(c, severity.get(c.key));
              const parts = conditionParts(c);
              return (
                <tr
                  key={c.key}
                  id={`cond-${c.key}`}
                  tabIndex={0}
                  data-active={active === c.key}
                  aria-describedby={severity.has(c.key) ? `reason-${c.key}` : undefined}
                  onMouseEnter={() => onActive(c.key)}
                  onMouseLeave={() => onActive(null)}
                  onFocus={() => onActive(c.key)}
                  onBlur={() => onActive(null)}
                  className={`grid grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] items-center gap-x-3 border-t border-line sm:table-row focus:outline-none focus-visible:ring-2 focus-visible:ring-hold ${active === c.key ? "bg-hold/10" : ""}`}
                >
                  <th scope="row" className={`col-start-1 row-start-1 border-l-4 py-3 pr-3 pl-3 text-left text-xs font-normal tracking-wider text-ink-2 uppercase ${state.rail}`}>{c.label}</th>
                  <td key={`${c.key}:${c.value}`} className={`col-start-2 row-start-1 pr-3 ${changed.has(c.key) ? "board-flash" : ""}`}>
                    {parts ? (
                      <>
                        <span data-figure className={`text-4xl leading-none font-semibold tracking-tight ${c.flagged || c.status === "within" || state === STATE.hold ? state.text : ""}`}>{parts.num}</span>
                        {parts.unit && <span data-unit className="text-sm font-normal whitespace-pre text-ink-2">{parts.unit}</span>}
                      </>
                    ) : (
                      <span className="text-base text-ink-2">no data</span>
                    )}
                  </td>
                  {view === "figures" ? (
                    <>
                      <td className="col-start-2 row-start-2 pr-3 pb-2 text-ink-2">{baselineValue(c) && <span className="text-xs sm:hidden">28-day </span>}{baselineValue(c)}</td>
                      <td className="col-start-3 row-start-2 pr-3 pb-2"><LimitMarker low={c.band_low} high={c.band_high} value={c.value} /></td>
                    </>
                  ) : (
                    <td className={`col-span-2 col-start-2 row-start-2 pr-3 pb-2 ${state === STATE.plain ? "text-ink" : state.text}`}>
                      {c.spark.some((v) => v != null) ? <Sparkline values={c.spark} low={c.band_low} high={c.band_high} /> : <span className="text-ink-2">no history</span>}
                    </td>
                  )}
                  <td data-status className={`col-start-3 row-start-1 text-xs font-semibold tracking-wide uppercase ${state.text}`}>{c.status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {readiness && (
        <p className="mt-3 text-xs text-ink-2">
          CTL / ATL / TSB {n(readiness.ctl, 1)} / {n(readiness.atl, 1)} / {n(readiness.tsb, 1)} · battery {readiness.body_battery ?? "no data"}
        </p>
      )}
    </section>
  );
}
