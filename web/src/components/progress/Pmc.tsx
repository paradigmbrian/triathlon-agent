import { useState } from "react";
import type { ProgressView } from "../../api/queries";
import ChartFrame from "./ChartFrame";
import Scrubber from "./Scrubber";
import { axisDate, axisLabels, niceMax, scaleLinear, segments, ticks } from "./scale";
import { signed } from "./units";
import { useWidth } from "./useWidth";

const LEFT = 40;
const RIGHT = 8;
const TOP_H = 170;
const GAP = 22;
const BOT_H = 70;
const H = TOP_H + GAP + BOT_H + 22;
const FORM_BAND: [number, number] = [-10, 5]; // the "neutral" TSB zone in metrics.py

type Point = ProgressView["pmc"][number];
const f1 = (v: number | null) => (v == null ? "–" : v.toFixed(1));

export default function Pmc({ pmc, ramp28 }: { pmc: Point[]; ramp28: number | null }) {
  const [picked, setPicked] = useState<number | null>(null);
  const known = pmc.filter((p) => p.ctl != null);
  const last = known.at(-1);
  const lastKnown = pmc.map((p) => p.ctl != null).lastIndexOf(true);
  const index = picked != null && picked < pmc.length ? picked : Math.max(lastKnown, 0);
  const at = pmc[index];
  const readout = at
    ? at.ctl == null
      ? `${axisDate(at.date)}: no reading`
      : `${axisDate(at.date)}: CTL ${f1(at.ctl)} · ATL ${f1(at.atl)} · TSB ${signed(at.tsb)}`
    : "";
  const summary = last
    ? `CTL ${f1(last.ctl)}${ramp28 != null ? `, ${signed(ramp28)} over 28 days` : ""}; form ${signed(last.tsb)}.`
    : "No data in this range.";
  const table = {
    head: ["Date", "CTL", "ATL", "TSB", "TSS"],
    rows: pmc.map((p) => [p.date, f1(p.ctl), f1(p.atl), p.tsb == null ? "–" : signed(p.tsb), f1(p.tss)]),
  };
  return (
    <ChartFrame title="Performance management" summary={summary} table={table}>
      {known.length === 0 ? (
        <p className="text-sm text-ink-2">No data in this range.</p>
      ) : (
        <>
          <Chart pmc={pmc} index={index} onPick={setPicked} />
          <p data-testid="pmc-readout" className="mt-1 text-xs text-ink-2 tabular-nums">{readout}</p>
          <Scrubber label="Inspect day" count={pmc.length} index={index} valueText={readout} onChange={setPicked} />
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
            <li><span aria-hidden="true" className="mr-1.5 inline-block h-2 w-4 rounded-sm bg-accent/40 align-middle" />CTL (fitness)</li>
            <li><span aria-hidden="true" className="mr-1.5 inline-block w-4 border-t-2 border-dashed border-nutrition align-middle" />ATL (fatigue)</li>
            <li><span aria-hidden="true" className="mr-1.5 inline-block w-4 border-t-2 border-ink align-middle" />TSB (form)</li>
          </ul>
        </>
      )}
    </ChartFrame>
  );
}

function Chart({ pmc, index, onPick }: { pmc: Point[]; index: number; onPick: (i: number) => void }) {
  const [ref, W] = useWidth();
  const n = pmc.length;
  const x = (i: number) => (n > 1 ? LEFT + (i / (n - 1)) * (W - LEFT - RIGHT) : (LEFT + W - RIGHT) / 2);
  const ctl = pmc.map((p) => p.ctl);
  const atl = pmc.map((p) => p.atl);
  const tsb = pmc.map((p) => p.tsb);
  const top = niceMax(Math.max(...ctl.concat(atl).filter((v): v is number => v != null)));
  const yTop = scaleLinear(0, top, TOP_H, 0);
  const tsbVals = tsb.filter((v): v is number => v != null);
  const lo = Math.min(-15, ...tsbVals);
  const hi = Math.max(10, ...tsbVals);
  const yBot = (v: number) => TOP_H + GAP + scaleLinear(lo, hi, BOT_H, 0)(v);
  const ctlRuns = segments(ctl, x, yTop);
  const areas = ctlRuns.map((d) => {
    const pts = d.replace(/^M/, "").split(" L");
    const first = pts[0].split(",")[0];
    const lastX = pts[pts.length - 1].split(",")[0];
    return `${d} L${lastX},${TOP_H} L${first},${TOP_H} Z`;
  });
  const labels = axisLabels(pmc.map((p) => p.date), 5);
  return (
    <div ref={ref}>
    <svg
      role="img"
      aria-label="Performance management chart: CTL, ATL and TSB by day. Use the day slider or the table for values."
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      onPointerMove={(e) => {
        const box = e.currentTarget.getBoundingClientRect();
        if (box.width === 0) return;
        const px = ((e.clientX - box.left) / box.width) * W;
        onPick(Math.max(0, Math.min(n - 1, Math.round(((px - LEFT) / (W - LEFT - RIGHT)) * (n - 1)))));
      }}
    >
      {ticks(top).map((t) => (
        <g key={t}>
          <line x1={LEFT} x2={W - RIGHT} y1={yTop(t)} y2={yTop(t)} stroke="var(--line)" strokeWidth={1} />
          <text x={LEFT - 6} y={yTop(t) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">{Math.round(t)}</text>
        </g>
      ))}
      {areas.map((d, i) => <path key={i} d={d} fill="var(--accent)" opacity={0.22} />)}
      {ctlRuns.map((d, i) => <path key={i} data-series="ctl" d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
      {segments(atl, x, yTop).map((d, i) => <path key={i} data-series="atl" d={d} fill="none" stroke="var(--nutrition)" strokeWidth={1.5} strokeDasharray="5 3" strokeLinecap="round" />)}
      <rect x={LEFT} width={W - LEFT - RIGHT} y={yBot(FORM_BAND[1])} height={yBot(FORM_BAND[0]) - yBot(FORM_BAND[1])} fill="var(--ink-2)" opacity={0.15} />
      <line x1={LEFT} x2={W - RIGHT} y1={yBot(0)} y2={yBot(0)} stroke="var(--ink-2)" strokeWidth={1} />
      <text x={LEFT - 6} y={yBot(0) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">0</text>
      {segments(tsb, x, yBot).map((d, i) => <path key={i} data-series="tsb" d={d} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />)}
      {labels.map((l) => (
        <text key={l.i} x={x(l.i)} y={H - 4} textAnchor="middle" fontSize={12} fill="var(--ink-2)">{l.text}</text>
      ))}
      <line x1={x(index)} x2={x(index)} y1={0} y2={TOP_H + GAP + BOT_H} stroke="var(--ink-2)" strokeWidth={1} />
    </svg>
    </div>
  );
}
