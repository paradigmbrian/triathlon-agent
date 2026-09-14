import type { TodayView } from "../../api/queries";
import { hours, n } from "../../lib/format";
import { Card, Empty } from "./Card";

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
      <div>
        {hours(week.actual_hours)} of {hours(week.target_hours)} · {n(week.actual_tss)} of {n(week.target_tss)} TSS
      </div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="mt-1 h-1.5 w-full rounded bg-line">
        <div className="h-1.5 rounded bg-planning" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-ink-2">{week.sessions.map((s) => `${s.sport} ${s.completed}/${s.planned}`).join(" · ")}</div>
    </Card>
  );
}
