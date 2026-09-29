/** A hairline track: your band shaded, a tick at today's value. Decorative; the status word carries the meaning. */
export default function LimitMarker({ low, high, value }: { low: number | null; high: number | null; value: number | null }) {
  if (value == null || (low == null && high == null)) return null;
  const lo = low ?? Math.min(0, value);
  const hi = high ?? lo;
  const span = hi - lo || Math.abs(hi) || 1;
  const min = Math.min(value, lo) - span * 0.25;
  const max = Math.max(value, hi) + span * 0.25;
  const pos = (x: number) => `${(((x - min) / (max - min)) * 100).toFixed(1)}%`;
  return (
    <div aria-hidden="true" className="relative h-1.5 w-24 rounded-full bg-line">
      <div className="absolute inset-y-0 rounded-full bg-ink-2/50" style={{ left: pos(lo), right: `calc(100% - ${pos(hi)})` }} />
      <div className="absolute -top-1 h-3.5 w-0.5 rounded-full bg-ink" style={{ left: pos(value) }} />
    </div>
  );
}
