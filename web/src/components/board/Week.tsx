import type { TodayView } from "../../api/queries";
import { hours, n } from "../../lib/format";
import Section, { Empty } from "./Section";

export default function Week({ week }: { week: TodayView["week"] }) {
  if (!week) {
    return (
      <Section title="Week">
        <Empty>No plan; ask the coach to build one</Empty>
      </Section>
    );
  }
  const pct = week.target_hours ? Math.min(100, Math.round((week.actual_hours / week.target_hours) * 100)) : 0;
  return (
    <Section title={`Week · ${week.phase}`}>
      <div className="text-base font-medium tabular-nums">
        {hours(week.actual_hours)} of {hours(week.target_hours)}
      </div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-1.5 w-full max-w-md rounded-full bg-line">
        <div className="h-1.5 rounded-full bg-hold" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-ink-2 tabular-nums">
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
    </Section>
  );
}
