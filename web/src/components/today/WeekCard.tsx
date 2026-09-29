import type { TodayView } from "../../api/queries";
import { hours, n } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";

export default function WeekCard({ week }: { week: TodayView["week"] }) {
  if (!week) {
    return (
      <Card title="Week" tone="planning">
        <Empty>No plan; ask the coach to build one</Empty>
      </Card>
    );
  }
  const pct = week.target_hours ? Math.min(100, Math.round((week.actual_hours / week.target_hours) * 100)) : 0;
  return (
    <Card title={`Week · ${week.phase}`} tone="planning">
      <Headline>
        {hours(week.actual_hours)} of {hours(week.target_hours)}
      </Headline>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-full rounded-full bg-line">
        <div className="h-1.5 rounded-full bg-planning" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-ink-2">
        {n(week.actual_tss)} of {n(week.target_tss)} TSS
      </div>
      <ul className="space-y-0.5 text-ink-2 tabular-nums">
        {week.sessions.map((s) => (
          <li key={s.sport}>
            {`${s.sport} ${s.completed}/${s.planned} · ${n(s.actual_tss)} of ${n(s.planned_tss)} TSS · ${n(s.actual_hours, 1)} of ${hours(s.planned_hours)}`}
          </li>
        ))}
      </ul>
      {week.planned_to_date > 0 && (
        <div className="text-xs text-ink-2">
          {week.completed_to_date} of {week.planned_to_date} so far
        </div>
      )}
    </Card>
  );
}
