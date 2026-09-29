/** A 14-day line for a card row. Decorative: the row's text carries the meaning. Gaps break the line. */
export default function Spark({ values, className = "" }: { values: (number | null)[]; className?: string }) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const lo = Math.min(...nums);
  const span = Math.max(...nums) - lo || 1;
  const step = 100 / Math.max(values.length - 1, 1);
  const runs: string[][] = [[]];
  values.forEach((v, i) => {
    const run = runs[runs.length - 1];
    if (v == null) {
      if (run.length) runs.push([]);
      return;
    }
    run.push(`${(i * step).toFixed(1)},${(26 - ((v - lo) / span) * 22).toFixed(1)}`);
  });
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true" className={className}>
      {runs
        .filter((r) => r.length > 1)
        .map((r, i) => (
          <polyline key={i} points={r.join(" ")} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        ))}
    </svg>
  );
}
