import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import { Legend } from "./SportMarks";
import StackedBars from "./StackedBars";
import { axisDate } from "./scale";
import { SPORTS, SPORT_LABEL, fold, sportColor, type Sport } from "./sports";
import { METRICS, type Metric, type SportTotals } from "./units";

type Week = ProgressView["weeks"][number];
const add = (a: SportTotals, b: SportTotals): SportTotals => ({
  duration_sec: a.duration_sec + b.duration_sec, distance_m: a.distance_m + b.distance_m,
  elevation_m: a.elevation_m + b.elevation_m, calories: a.calories + b.calories, tss: a.tss + b.tss,
});

export function MetricSwitch<T extends string>({ name, value, options, onChange }: {
  name: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={name} className="inline-flex rounded-sm border border-line">
      {options.map((o) => (
        <label key={o.value} className={`inline-flex min-h-7 cursor-pointer items-center px-2.5 text-xs has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${value === o.value ? "bg-hold text-on-fill" : "text-ink-2 hover:text-ink"}`}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
          {o.label}
        </label>
      ))}
    </div>
  );
}

export default function WeeklyBars({ weeks }: { weeks: Week[] }) {
  const [metric, setMetric] = useState<Metric>("distance");
  const [picked, setPicked] = useState<number | null>(null);
  const m = METRICS[metric];
  const folded = weeks.map((w) => fold(w.by_sport, add));
  const perSport = (i: number, s: Sport) => (folded[i][s] ? m.of(folded[i][s] as SportTotals) : 0);
  const used = SPORTS.filter((s) => weeks.some((_, i) => perSport(i, s) > 0));
  const stacks = used.map((s) => ({ key: s, label: SPORT_LABEL[s], color: sportColor(s), values: weeks.map((_, i) => perSport(i, s)) }));
  const totals = weeks.map((_, i) => used.reduce((sum, s) => sum + perSport(i, s), 0));
  const complete = weeks.map((w, i) => (w.partial ? null : totals[i])).filter((v): v is number => v != null);
  const average = complete.length ? complete.reduce((a, b) => a + b, 0) / complete.length : null;
  const index = picked != null && picked < weeks.length ? picked : weeks.length - 1;
  const fmt = (v: number) => v.toFixed(m.digits);
  const week = weeks[index];
  const readout = week
    ? `Week of ${axisDate(week.week_start)}${week.partial ? " (partial)" : ""}: ${fmt(totals[index])} ${m.unit}${used.filter((s) => perSport(index, s) > 0).map((s) => ` · ${SPORT_LABEL[s]} ${fmt(perSport(index, s))} ${m.unit}`).join("")}`
    : "";
  const empty = totals.every((t) => t === 0);
  const summary = empty
    ? "No data in this range."
    : `Average ${average == null ? "–" : fmt(average)} ${m.unit} per week${average == null ? "" : ` over ${complete.length} complete week${complete.length === 1 ? "" : "s"}`}.`;
  return (
    <ChartFrame
      title="Weekly volume by sport"
      summary={summary}
      controls={<MetricSwitch<Metric> name="Metric" value={metric} options={(Object.keys(METRICS) as Metric[]).map((k) => ({ value: k, label: METRICS[k].label }))} onChange={setMetric} />}
      table={{
        head: ["Week", ...used.map((s) => SPORT_LABEL[s]), "Total"],
        rows: weeks.map((w, i) => [`${w.week_start}${w.partial ? " (partial)" : ""}`, ...used.map((s) => fmt(perSport(i, s))), fmt(totals[i])]),
      }}
    >
      {empty ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <StackedBars weeks={weeks.map((w) => w.week_start)} stacks={stacks} partialLast={weeks.at(-1)?.partial ?? false} average={average} digits={m.digits} label={`Weekly ${m.label.toLowerCase()} in ${m.unit}, stacked by sport. Use the week slider or the table for values.`} marked={picked} />
          <p data-testid="weekly-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect week" count={weeks.length} index={index} valueText={readout} onChange={setPicked} />
          <Legend sports={used} />
        </>
      )}
    </ChartFrame>
  );
}
