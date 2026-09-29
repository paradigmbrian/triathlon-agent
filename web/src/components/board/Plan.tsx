import type { TodayView } from "../../api/queries";
import { day, kcal, n, secsAsHours } from "../../lib/format";
import Section, { Empty } from "./Section";

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

export default function Plan({ session, fuel }: { session: TodayView["session"]; fuel: TodayView["fuel"] }) {
  const t = fuel.target;
  return (
    <Section title="Today's plan">
      {!session ? (
        <Empty>No session planned</Empty>
      ) : (
        <ul className="space-y-2">
          {session.workouts.map((w, i) => (
            <li key={w.tp_workout_id}>
              <div className={i === 0 ? "text-base font-medium" : "font-medium"}>{w.title || w.sport}</div>
              <div className="text-ink-2 tabular-nums">
                {w.sport} · {secsAsHours(w.completed ? w.actual_duration_sec : w.planned_duration_sec)} · {n(w.completed ? w.actual_tss : w.planned_tss)} TSS
                {w.completed ? " · done" : ""}
              </div>
              {w.completed &&
                detail(w).map((line, j) => (
                  <div key={j} className="text-xs text-ink-2 tabular-nums">
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
      <div className="pt-2">
        {!t ? (
          <Empty>No targets yet, ask the coach</Empty>
        ) : (
          <>
            <div className="text-base font-medium tabular-nums">{kcal(t.total_kcal)}</div>
            <div className="text-ink-2 tabular-nums">
              {t.day_type} · {t.carbs_g} C · {t.protein_g} P · {t.fat_g} F · {t.fluid_baseline_ml} ml
            </div>
            <div className="text-xs text-ink-2">targets through {day(fuel.targets_through)}{t.written_to_garmin ? " · on Garmin" : ""}</div>
          </>
        )}
      </div>
    </Section>
  );
}
