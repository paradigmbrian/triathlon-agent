import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty } from "./Card";

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
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-semibold">{r.sleep_score ?? "–"}</span>
        <span className="text-ink-2">sleep · {n(r.sleep_hours, 1)} h</span>
      </div>
      <div className="text-ink-2">
        HRV {r.hrv ?? "–"} · RHR {r.resting_hr ?? "–"} · battery {r.body_battery ?? "–"} · readiness {r.training_readiness ?? "–"}
      </div>
      <div className="text-ink-2">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)}
      </div>
    </Card>
  );
}
