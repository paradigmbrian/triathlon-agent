import { useState } from "react";
import type { ConditionOut, ReasonOut, TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import LimitMarker from "./LimitMarker";
import Sparkline from "./Sparkline";
import { baselineValue, conditionValue } from "./format";

type Props = {
  readiness: TodayView["readiness"];
  rows: ConditionOut[];
  reasons: ReasonOut[];
  active: string | null;
  onActive: (key: string | null) => void;
};

const SEVERITY_TONE = { stop: "text-rest", caution: "text-easy", info: "text-ink-2" } as const;

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
          <thead className="text-left text-xs text-ink-2">
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
              const tone = c.flagged ? SEVERITY_TONE[severity.get(c.key) ?? "caution"] : "text-ink-2";
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
                  className={`border-t border-line focus:outline-none focus-visible:ring-2 focus-visible:ring-hold ${active === c.key ? "bg-hold/10" : ""}`}
                >
                  <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-2">{c.label}</th>
                  <td key={`${c.key}:${c.value}`} className={`pr-3 text-2xl font-semibold ${c.flagged ? tone : ""} ${changed.has(c.key) ? "board-flash" : ""}`}>
                    {conditionValue(c)}
                  </td>
                  {view === "figures" ? (
                    <>
                      <td className="pr-3 text-ink-2">{baselineValue(c)}</td>
                      <td className="pr-3"><LimitMarker low={c.band_low} high={c.band_high} value={c.value} /></td>
                    </>
                  ) : (
                    <td className={`pr-3 ${c.flagged ? tone : "text-ink"}`}>
                      {c.spark.some((v) => v != null) ? <Sparkline values={c.spark} low={c.band_low} high={c.band_high} /> : <span className="text-ink-2">no history</span>}
                    </td>
                  )}
                  <td data-status className={tone}>{c.status}</td>
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
