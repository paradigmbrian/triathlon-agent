import type { ReactNode } from "react";
import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";

type Readiness = NonNullable<TodayView["readiness"]>;
type Trend = Readiness["trends"][string];

const TILES: { key: string; label: string; digits: number; unit: string }[] = [
  { key: "hrv", label: "HRV", digits: 0, unit: " ms" },
  { key: "resting_hr", label: "RHR", digits: 0, unit: " bpm" },
  { key: "sleep_score", label: "Sleep", digits: 0, unit: "" },
  { key: "sleep_hours", label: "Slept", digits: 1, unit: " h" },
];

/** Compact "now vs 28-day avg": ↓7, ↑0.3 or = (rounded first, so a tiny move reads as level), plus low/high
 * outside the band. The comparison is spelled out for screen readers; sighted readers get one caption. */
function Delta({ t, digits }: { t: Trend; digits: number }) {
  if (t.avg_28d == null) return null;
  const factor = 10 ** digits;
  const rounded = Math.round((t.now - t.avg_28d) * factor) / factor;
  const word = t.band === "below" ? " low" : t.band === "above" ? " high" : "";
  const level = rounded === 0;
  const tone = level || t.better == null ? "text-ink-2" : t.better ? "text-good" : "text-warn";
  return (
    <span className={`text-xs ${tone}`}>
      {level ? "=" : `${rounded > 0 ? "↑" : "↓"}${Math.abs(rounded).toFixed(digits)}`}
      {word}
      <span className="sr-only"> vs 28-day avg</span>
    </span>
  );
}

function Tile({ label, t, digits, unit }: { label: string; t: Trend; digits: number; unit: string }) {
  return (
    <div className="rounded-md bg-surface px-2.5 py-1.5">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="flex items-baseline justify-between gap-1 tabular-nums">
        <span className="font-medium">
          {n(t.now, digits)}
          {unit}
        </span>
        <Delta t={t} digits={digits} />
      </div>
    </div>
  );
}

function Chip({ warn = false, children }: { warn?: boolean; children: ReactNode }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs whitespace-nowrap ${warn ? "border-warn/50 text-warn" : "border-line text-ink-2"}`}>
      {children}
    </span>
  );
}

function ramp(v: number) {
  const x = Math.round(v * 10) / 10;
  return `${x > 0 ? "+" : ""}${x.toFixed(1)}`.replace("-0.0", "0.0");
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
  const leadTrend = r.trends[r.training_readiness != null ? "training_readiness" : "sleep_score"];
  const tiles = TILES.flatMap((tile) => (r.trends[tile.key] ? [{ ...tile, t: r.trends[tile.key] }] : []));
  const compared = [leadTrend, ...tiles.map((tile) => tile.t)].some((t) => t?.avg_28d != null);
  return (
    <Card title={r.is_today ? "Readiness" : `Readiness from ${day(r.date)}`}>
      <div className="flex items-baseline gap-2">
        <Headline>{lead ?? "no data"}</Headline>
        <span className="text-ink-2">{leadLabel}</span>
        {leadTrend && <Delta t={leadTrend} digits={0} />}
      </div>
      {compared && <div className="text-xs text-ink-2">arrows: vs 28-day avg</div>}
      {tiles.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          {tiles.map((tile) => (
            <Tile key={tile.key} label={tile.label} t={tile.t} digits={tile.digits} unit={tile.unit} />
          ))}
        </div>
      )}
      {r.tsb != null && (
        <div className="flex flex-wrap gap-1.5 pt-1 tabular-nums">
          <Chip>
            TSB {n(r.tsb, 1)}
            {r.tsb_zone ? ` ${r.tsb_zone}` : ""}
          </Chip>
          {r.ramp_7d != null && (
            <Chip warn={r.ramp_caution}>
              ramp {ramp(r.ramp_7d)}/wk{r.ramp_caution ? " fast" : ""}
            </Chip>
          )}
          {r.acwr != null && (
            <Chip warn={r.acwr_flag != null}>
              ACWR {r.acwr.toFixed(2)}
              {r.acwr_flag ? ` ${r.acwr_flag}` : ""}
            </Chip>
          )}
        </div>
      )}
      <div className="text-xs text-ink-2 tabular-nums">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)} · battery {r.body_battery ?? "no data"}
      </div>
    </Card>
  );
}
