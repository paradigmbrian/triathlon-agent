import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";
import Spark from "./Spark";

type Readiness = NonNullable<TodayView["readiness"]>;
type Trend = Readiness["trends"][string];

const ROWS: { key: string; label: string; digits: number; unit: string }[] = [
  { key: "hrv", label: "HRV", digits: 0, unit: " ms" },
  { key: "resting_hr", label: "RHR", digits: 0, unit: " bpm" },
  { key: "sleep_score", label: "Sleep", digits: 0, unit: "" },
  { key: "sleep_hours", label: "Slept", digits: 1, unit: " h" },
];

function TrendRow({ label, t, digits, unit }: { label: string; t: Trend; digits: number; unit: string }) {
  const delta = t.avg_28d == null ? null : t.now - t.avg_28d;
  const word = t.band === "below" ? " · low" : t.band === "above" ? " · high" : "";
  const tone = t.better == null ? "text-ink-2" : t.better ? "text-good" : "text-warn";
  return (
    <div className="flex items-center gap-2 tabular-nums">
      <span className="w-12 text-ink-2">{label}</span>
      <span className="w-14 font-medium">
        {n(t.now, digits)}
        {unit}
      </span>
      <Spark values={t.spark} className="h-4 w-14 shrink-0 text-ink-2" />
      {delta != null && (
        <span className={`text-xs ${tone}`}>
          {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(digits)} vs 28-day avg{word}
        </span>
      )}
    </div>
  );
}

export default function ReadinessCard({ readiness }: { readiness: TodayView["readiness"] }) {
  if (!readiness) {
    return (
      <Card title="Readiness">
        <Empty>No Garmin data yet, sync first</Empty>
      </Card>
    );
  }
  const r = readiness;
  const lead = r.training_readiness ?? r.sleep_score;
  const leadLabel = r.training_readiness != null ? "training readiness" : "sleep score";
  return (
    <Card title={r.is_today ? "Readiness" : `Readiness from ${day(r.date)}`}>
      <div className="flex items-baseline gap-2">
        <Headline>{lead ?? "no data"}</Headline>
        <span className="text-ink-2">{leadLabel}</span>
      </div>
      {ROWS.map((row) => {
        const t = r.trends[row.key];
        return t ? <TrendRow key={row.key} label={row.label} t={t} digits={row.digits} unit={row.unit} /> : null;
      })}
      {r.tsb != null && (
        <div className="text-ink-2 tabular-nums">
          TSB {n(r.tsb, 1)}
          {r.tsb_zone ? ` · ${r.tsb_zone}` : ""}
          {r.ramp_7d != null && (
            <>
              {" · "}
              <span className={r.ramp_caution ? "text-warn" : ""}>
                ramp {r.ramp_7d >= 0 ? "+" : ""}
                {r.ramp_7d.toFixed(1)}/wk{r.ramp_caution ? " fast" : ""}
              </span>
            </>
          )}
          {r.acwr != null && (
            <>
              {" · "}
              <span className={r.acwr_flag ? "text-warn" : ""}>
                ACWR {r.acwr.toFixed(2)}
                {r.acwr_flag ? ` ${r.acwr_flag}` : ""}
              </span>
            </>
          )}
        </div>
      )}
      <div className="text-xs text-ink-2 tabular-nums">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)} · battery {r.body_battery ?? "no data"}
      </div>
    </Card>
  );
}
