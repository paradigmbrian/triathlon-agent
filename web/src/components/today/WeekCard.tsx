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
      <div className="text-ink-2">{week.sessions.map((s) => `${s.sport} ${s.completed}/${s.planned}`).join(" · ")}</div>
    </Card>
  );
}
