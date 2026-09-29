import type { ProgressRange } from "../../api/queries";

const OPTIONS: { value: ProgressRange; label: string }[] = [
  { value: "6w", label: "6 weeks" },
  { value: "6m", label: "6 months" },
  { value: "12m", label: "12 months" },
  { value: "all", label: "All" },
];

export default function RangePicker({ value, onChange }: { value: ProgressRange; onChange: (r: ProgressRange) => void }) {
  return (
    <div role="radiogroup" aria-label="Range" className="inline-flex rounded-sm border border-line">
      {OPTIONS.map((o) => (
        <label
          key={o.value}
          className={`inline-flex min-h-8 cursor-pointer items-center px-3 text-xs has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
            value === o.value ? "bg-hold text-on-fill" : "text-ink-2 hover:text-ink"
          }`}
        >
          <input type="radio" name="range" value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
          {o.label}
        </label>
      ))}
    </div>
  );
}
