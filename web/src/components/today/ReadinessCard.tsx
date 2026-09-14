import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";

export default function ReadinessCard({ readiness }: { readiness: TodayView["readiness"] }) {
  if (!readiness) {
    return (
      <Card title="Readiness">
        <Empty>No Garmin data yet, sync first</Empty>
      </Card>
    );
  }
  const r = readiness;
  return (
    <Card title={r.is_today ? "Readiness" : `Readiness from ${day(r.date)}`}>
      <div className="flex items-baseline gap-2">
        <Headline>{r.sleep_score ?? "–"}</Headline>
        <span className="text-ink-2">sleep · {n(r.sleep_hours, 1)} h</span>
      </div>
      <div className="text-ink-2">
        HRV {r.hrv ?? "–"} · RHR {r.resting_hr ?? "–"} · battery {r.body_battery ?? "–"} · readiness {r.training_readiness ?? "–"}
      </div>
      <div className="text-xs text-ink-2 tabular-nums">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)}
      </div>
    </Card>
  );
}
