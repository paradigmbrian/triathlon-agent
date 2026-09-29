import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import { Marker } from "./SportMarks";
import { MetricSwitch } from "./WeeklyBars";
import { SPORTS, SPORT_LABEL, fold, sportColor, type Sport } from "./sports";

type Measure = "duration_sec" | "distance_m";
const LABEL: Record<Measure, string> = { duration_sec: "duration", distance_m: "distance" };

type Shares = { total: number; by: Partial<Record<Sport, number>> };

function shares(rec: Record<string, number> | undefined): Shares {
  const by = fold(rec ?? {}, (a, b) => a + b);
  return { total: Object.values(by).reduce((s, v) => s + (v ?? 0), 0), by };
}

export default function ShareBars({ share }: { share: ProgressView["share"] }) {
  const [measure, setMeasure] = useState<Measure>("duration_sec");
  const done = shares(share.completed[measure]);
  const plan = shares(share.planned[measure]);
  const pct = (s: Shares, sport: Sport) => (s.total > 0 ? ((s.by[sport] ?? 0) / s.total) * 100 : 0);
  const rows = SPORTS.filter((s) => (done.by[s] ?? 0) > 0 || (plan.by[s] ?? 0) > 0);
  const lead = rows.length ? [...rows].sort((a, b) => pct(done, b) - pct(done, a))[0] : null;
  const summary = lead && done.total > 0 ? `${SPORT_LABEL[lead]} is ${pct(done, lead).toFixed(1)}% of completed ${LABEL[measure]}.` : "No data in this range.";
  return (
    <ChartFrame
      title="Sport share"
      summary={summary}
      controls={<MetricSwitch<Measure> name="Share of" value={measure} options={[{ value: "duration_sec", label: "Duration" }, { value: "distance_m", label: "Distance" }]} onChange={setMeasure} />}
      table={{ head: ["Sport", "Completed %", "Planned %"], rows: rows.map((s) => [SPORT_LABEL[s], pct(done, s).toFixed(1), pct(plan, s).toFixed(1)]) }}
    >
      {rows.length === 0 ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((s) => (
            <li key={s} role="group" aria-label={SPORT_LABEL[s]}>
              <p className="inline-flex items-center gap-1.5 text-sm"><Marker sport={s} />{SPORT_LABEL[s]}</p>
              {(["Completed", "Planned"] as const).map((kind) => {
                const p = pct(kind === "Completed" ? done : plan, s);
                return (
                  <div key={kind} className="mt-1 flex items-center gap-3 text-xs">
                    <span className="w-40 shrink-0 text-ink-2 tabular-nums sm:w-44">{kind} {p.toFixed(1)}%</span>
                    <div className="h-2 min-w-0 flex-1 rounded-sm bg-line/50">
                      {p > 0 && <div data-testid="share-bar" className={`h-full rounded-sm ${kind === "Planned" ? "opacity-50" : ""}`} style={{ width: `${p}%`, background: sportColor(s) }} />}
                    </div>
                  </div>
                );
              })}
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  );
}
