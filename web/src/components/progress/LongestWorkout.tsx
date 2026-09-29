import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import StackedBars from "./StackedBars";
import { MetricSwitch } from "./WeeklyBars";
import { axisDate } from "./scale";
import { hoursOf, miles } from "./units";

type Week = ProgressView["weeks"][number];
type Kind = "distance" | "duration";
const KIND = {
  distance: { unit: "mi", digits: 1, of: (w: Week) => miles(w.longest.distance_m) },
  duration: { unit: "h", digits: 1, of: (w: Week) => hoursOf(w.longest.duration_sec) },
};

export default function LongestWorkout({ weeks }: { weeks: Week[] }) {
  const [kind, setKind] = useState<Kind>("distance");
  const [picked, setPicked] = useState<number | null>(null);
  const k = KIND[kind];
  const values = weeks.map(k.of);
  const best = Math.max(0, ...values);
  const counted = weeks.map((w, i) => (w.partial ? null : values[i])).filter((v): v is number => v != null && v > 0);
  const average = counted.length ? counted.reduce((a, b) => a + b, 0) / counted.length : null;
  const index = picked != null && picked < weeks.length ? picked : weeks.length - 1;
  const fmt = (v: number) => v.toFixed(k.digits);
  const readout = weeks[index] ? `Week of ${axisDate(weeks[index].week_start)}${weeks[index].partial ? " (partial)" : ""}: ${fmt(values[index])} ${k.unit}` : "";
  const empty = best === 0;
  return (
    <ChartFrame
      title="Longest workout by week"
      summary={empty ? "No data in this range." : `Longest: ${fmt(best)} ${k.unit}${average == null ? "" : `; average ${fmt(average)} ${k.unit}`}.`}
      controls={<MetricSwitch<Kind> name="Longest by" value={kind} options={[{ value: "distance", label: "Distance" }, { value: "duration", label: "Duration" }]} onChange={setKind} />}
      table={{ head: ["Week", `Longest (${k.unit})`], rows: weeks.map((w, i) => [`${w.week_start}${w.partial ? " (partial)" : ""}`, fmt(values[i])]) }}
    >
      {empty ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <StackedBars weeks={weeks.map((w) => w.week_start)} stacks={[{ key: "longest", label: "Longest", color: "var(--accent)", values }]} partialLast={weeks.at(-1)?.partial ?? false} average={average} digits={k.digits} label={`Longest workout per week in ${k.unit}. Use the week slider or the table for values.`} marked={picked} />
          <p data-testid="longest-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect week" count={weeks.length} index={index} valueText={readout} onChange={setPicked} />
        </>
      )}
    </ChartFrame>
  );
}
