/** A slider that steps through a chart's points with the arrow keys; the keyboard route to each value. */
export default function Scrubber({ label, count, index, valueText, onChange }: {
  label: string;
  count: number;
  index: number;
  valueText: string;
  onChange: (i: number) => void;
}) {
  if (count < 2) return null;
  return (
    <label className="mt-2 flex items-center gap-3 text-xs text-ink-2">
      <span className="shrink-0">{label}</span>
      <input
        type="range"
        min={0}
        max={count - 1}
        step={1}
        value={index}
        aria-valuetext={valueText}
        onChange={(e) => onChange(Number(e.target.value))}
        className="min-h-6 min-w-0 flex-1 accent-[var(--accent)]"
      />
    </label>
  );
}
