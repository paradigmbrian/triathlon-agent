import type { TodayView } from "../../api/queries";
import { n, secsAsHours } from "../../lib/format";
import { Card, Empty } from "./Card";

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
