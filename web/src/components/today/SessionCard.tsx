import type { TodayView } from "../../api/queries";
import { n, secsAsHours } from "../../lib/format";
import { Card, Empty } from "./Card";

type Workout = NonNullable<TodayView["session"]>["workouts"][number];

const pct = (actual: number | null, planned: number | null) =>
  actual != null && planned ? Math.round((actual / planned) * 100) : null;

function detail(w: Workout): string[] {
  const effort = [
    w.actual_if != null ? `IF ${w.actual_if.toFixed(2)}` : null,
    w.avg_hr != null ? `${w.avg_hr} bpm` : null,
    w.avg_power != null ? `${w.avg_power} W${w.normalized_power != null ? ` (NP ${w.normalized_power})` : ""}` : null,
  ].filter(Boolean);
  const time = pct(w.actual_duration_sec, w.planned_duration_sec);
  const tss = pct(w.actual_tss, w.planned_tss);
  const vsPlan = [time != null ? `${time}% of planned time` : null, tss != null ? `${tss}% of planned TSS` : null].filter(Boolean);
  return [effort.join(" · "), vsPlan.join(" · ")].filter(Boolean);
}

export default function SessionCard({ session }: { session: TodayView["session"] }) {
  return (
    <Card title="Session" tone="planning">
      {!session ? (
        <Empty>No session planned</Empty>
      ) : (
        <ul className="space-y-2">
          {session.workouts.map((w, i) => (
            <li key={w.tp_workout_id}>
              <div className={i === 0 ? "text-lg leading-tight font-semibold" : "font-medium"}>{w.title || w.sport}</div>
              <div className="text-ink-2 tabular-nums">
                {w.sport} · {secsAsHours(w.completed ? w.actual_duration_sec : w.planned_duration_sec)} · {n(w.completed ? w.actual_tss : w.planned_tss)} TSS
                {w.completed ? " · done" : ""}
              </div>
              {w.completed &&
                detail(w).map((line) => (
                  <div key={line} className="text-xs text-ink-2 tabular-nums">
                    {line}
                  </div>
                ))}
            </li>
          ))}
          {session.fuel && (
            <li className="text-xs text-ink-2">
              fuel: {String(session.fuel.payload.carbs_g_per_h ?? "–")} g/h
              {session.fuel.payload.pre ? ` · pre: ${String(session.fuel.payload.pre)}` : ""}
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}
