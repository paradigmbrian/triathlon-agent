import type { ProgressView } from "../../api/queries";
import Sparkline from "../board/Sparkline";
import ChartFrame from "./ChartFrame";
import { signed } from "./units";

export default function RampRates({ ramp }: { ramp: ProgressView["ramp"] }) {
  const w28 = ramp.find((r) => r.days === 28)?.delta ?? null;
  const w7 = ramp.find((r) => r.days === 7)?.delta ?? null;
  const summary =
    w7 == null && w28 == null
      ? "No CTL history to measure a ramp."
      : `Fitness ${w7 == null ? "has no 7-day reading" : `${signed(w7)} over 7 days`}${w28 == null ? "" : `, ${signed(w28)} over 28 days`}.`;
  return (
    <ChartFrame
      title="Fitness ramp rate"
      summary={summary}
      table={{ head: ["Window", "CTL change"], rows: ramp.map((r) => [`Last ${r.days} days`, signed(r.delta)]) }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {ramp.map((r) => (
          <div key={r.days} role="group" aria-label={`Last ${r.days} days`} className="rounded-sm border border-line px-3 py-2">
            <p className="text-2xl font-semibold tracking-tight tabular-nums">{signed(r.delta)}</p>
            <p className="text-xs text-ink-2">Last {r.days} days</p>
            {r.series.some((v) => v != null) && <div className="mt-1 text-ink-2"><Sparkline values={r.series} low={null} high={null} /></div>}
          </div>
        ))}
      </div>
    </ChartFrame>
  );
}
