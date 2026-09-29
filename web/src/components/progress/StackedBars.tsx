import { useId } from "react";
import { axisLabels, niceMax, scaleLinear, ticks } from "./scale";

const W = 800;
const H = 200;
const LEFT = 44;
const RIGHT = 8;
const TOP = 8;
const BOTTOM = 22;

export type Stack = { key: string; label: string; color: string; values: number[] };

/** Weekly bars, stacked, with a dashed average line and the last bar hatched when the week is partial. Decorative to assistive tech: the frame's summary, the scrubber and the table carry the data. */
export default function StackedBars({ weeks, stacks, partialLast, average, digits, label, marked }: {
  weeks: string[];
  stacks: Stack[];
  partialLast: boolean;
  average: number | null;
  digits: number;
  label: string;
  marked: number | null;
}) {
  const hatch = useId();
  const n = weeks.length;
  const totals = weeks.map((_, i) => stacks.reduce((s, st) => s + st.values[i], 0));
  const top = niceMax(Math.max(0, ...totals));
  const y = scaleLinear(0, top, H - BOTTOM, TOP);
  const slot = (W - LEFT - RIGHT) / Math.max(n, 1);
  const bw = Math.max(1, slot * 0.72);
  const x = (i: number) => LEFT + i * slot + (slot - bw) / 2;
  const labels = axisLabels(weeks, 5);
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs>
        <pattern id={hatch} width={5} height={5} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1={0} y1={0} x2={0} y2={5} stroke="var(--surface-2)" strokeWidth={2} />
        </pattern>
      </defs>
      {ticks(top).map((t) => (
        <g key={t}>
          <line x1={LEFT} x2={W - RIGHT} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
          <text x={LEFT - 6} y={y(t) + 4} textAnchor="end" fontSize={12} fill="var(--ink-2)">{Number(t.toFixed(digits))}</text>
        </g>
      ))}
      {weeks.map((_, i) => {
        let base = 0;
        return (
          <g key={weeks[i]} opacity={marked == null || marked === i ? 1 : 0.55}>
            {stacks.map((st) => {
              const v = st.values[i];
              if (!(v > 0)) return null;
              const y0 = y(base);
              base += v;
              return <rect key={st.key} x={x(i)} y={y(base)} width={bw} height={Math.max(0, y0 - y(base))} fill={st.color} />;
            })}
            {partialLast && i === n - 1 && totals[i] > 0 && (
              <rect x={x(i)} y={y(totals[i])} width={bw} height={y(0) - y(totals[i])} fill={`url(#${hatch})`} />
            )}
          </g>
        );
      })}
      {average != null && average > 0 && (
        <line x1={LEFT} x2={W - RIGHT} y1={y(average)} y2={y(average)} stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="6 4" />
      )}
      {labels.map((l) => (
        <text key={l.i} x={x(l.i) + bw / 2} y={H - 4} textAnchor="middle" fontSize={12} fill="var(--ink-2)">{l.text}</text>
      ))}
    </svg>
  );
}
