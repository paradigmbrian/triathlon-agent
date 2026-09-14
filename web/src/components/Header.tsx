import type { ReactNode } from "react";
import type { TodayView } from "../api/queries";
import { day, when } from "../lib/format";

export default function Header({ today, slots }: { today?: TodayView; slots?: ReactNode }) {
  const h = today?.header;
  const week = h?.week.number != null ? `${h.phase} · week ${h.week.number} of ${h.week.of}` : (h?.phase ?? "");
  const goal = h?.goal;
  const pendingCount = today?.pending ? 1 : 0;
  return (
    <header className="relative flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-surface-2 px-4 py-3">
      <div className="text-base font-semibold">{h ? day(h.today) : "tri-web"}</div>
      {week && <div className="text-sm text-ink-2">{week}</div>}
      {goal?.event_date && goal.days_to_go != null && (
        <div className="text-sm text-ink-2">
          {goal.days_to_go} days to {goal.event_name ?? "race day"}
        </div>
      )}
      {h?.last_sync.map((s) => (
        <div key={s.source} className={`text-xs ${s.status === "ok" ? "text-ink-2" : "text-warn"}`} title={s.error ?? ""}>
          {s.source} {when(s.last_run_at)}
        </div>
      ))}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {slots}
        {pendingCount > 0 && (
          <span className="rounded-full bg-warn/15 px-2 py-0.5 text-xs font-medium text-warn">{pendingCount} review pending</span>
        )}
      </div>
    </header>
  );
}
