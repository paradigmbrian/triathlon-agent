import { useState, type ReactNode } from "react";
import type { TodayView } from "../api/queries";
import { day, when } from "../lib/format";

const STALE_MS = 24 * 3_600_000;

export default function Header({ today, slots, now }: { today?: TodayView; slots?: ReactNode; now?: number }) {
  const [mountedAt] = useState(Date.now);
  const clock = now ?? mountedAt;
  const h = today?.header;
  const week = h?.week.number != null ? `${h.phase} · week ${h.week.number} of ${h.week.of}` : (h?.phase ?? "");
  const goal = h?.goal;
  const pendingCount = today?.pending ? 1 : 0;
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2 tabular-nums">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1">
        <div className="text-sm font-semibold tracking-wide uppercase">{h ? day(h.today) : "tri-web"}</div>
        {week && <div className="text-sm text-ink-2">{week}</div>}
        {goal?.event_date && goal.days_to_go != null && (
          <div className="text-sm text-ink-2">
            {goal.days_to_go} days to {goal.event_name ?? "race day"}
          </div>
        )}
        {h?.last_sync.map((s) => {
          const failed = s.status !== "ok";
          const stale = !failed && clock - Date.parse(s.last_run_at) > STALE_MS;
          const tone = failed ? "text-danger" : stale ? "text-warn" : "text-ink-2";
          return (
            <div key={s.source} className={`text-xs ${tone}`} title={s.error ?? ""}>
              {s.source} {when(s.last_run_at)}
              {failed ? " · failed" : stale ? " · stale" : ""}
            </div>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {pendingCount > 0 && (
          <span className="rounded-full border border-hold/60 px-2 py-0.5 text-xs font-medium text-hold">{pendingCount} review pending</span>
        )}
        {slots}
      </div>
    </header>
  );
}
