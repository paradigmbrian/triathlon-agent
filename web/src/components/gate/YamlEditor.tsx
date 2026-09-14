export default function YamlEditor({ value, onChange, errors }: { value: string; onChange: (v: string) => void; errors: string[] }) {
  return (
    <div>
      <textarea
        aria-label="YAML"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={16}
        spellCheck={false}
        className="w-full rounded border border-line bg-surface p-2 font-mono text-xs"
      />
      {errors.map((e, i) => (
        <p key={i} className="text-xs text-danger">
          {e}
        </p>
      ))}
    </div>
  );
}
