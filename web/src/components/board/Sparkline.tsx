const W = 160;
const H = 28;
const PAD = 4;

/** A 14-day line with your band shaded and a dot on today's value. Decorative: the figure and status word carry the meaning. A missing day breaks the line. */
export default function Sparkline({ values, low, high }: { values: (number | null)[]; low: number | null; high: number | null }) {
  const known = values.filter((v): v is number => v != null);
  if (known.length === 0) return null;
  const banded = low != null && high != null;
  const min = Math.min(...known, ...(banded ? [low] : []));
  const max = Math.max(...known, ...(banded ? [high] : []));
  const span = max - min || 1;
  const x = (i: number) => (values.length > 1 ? PAD + (i / (values.length - 1)) * (W - 2 * PAD) : W / 2);
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - 2 * PAD);
  const runs: string[] = [];
  let run: string[] = [];
  values.forEach((v, i) => {
    if (v == null) {
      if (run.length) runs.push(run.join(" "));
      run = [];
    } else {
      run.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    }
  });
  if (run.length) runs.push(run.join(" "));
  const last = values.map((v, i) => (v == null ? -1 : i)).reduce((a, b) => Math.max(a, b), -1);
  return (
    <svg data-trend aria-hidden="true" viewBox={`0 0 ${W} ${H}`} className="h-7 w-40" fill="none">
      {banded && <rect data-band x={0} y={y(high)} width={W} height={Math.max(1, y(low) - y(high))} className="fill-ink-2/20" />}
      {runs.map((points, i) => (
        <polyline key={i} points={points} stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      ))}
      <circle cx={x(last)} cy={y(values[last]!)} r={3} fill="currentColor" />
    </svg>
  );
}
