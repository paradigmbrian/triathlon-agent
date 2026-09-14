import { useStatus } from "../../api/queries";

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className={ok ? "text-accent" : "text-danger"}>{ok ? "✓" : "✗"} {label}</li>
  );
}

export default function Readiness() {
  const status = useStatus();
  const s = status.data;
  if (!s) return <p className="text-ink-2">checking…</p>;
  return (
    <div className="text-sm">
      <ul className="space-y-1">
        <Check ok={s.ready.api_key} label="API key" />
        <Check ok={s.ready.checkpointer} label="checkpoint tables" />
        <Check ok={s.ready.store} label="store tables" />
      </ul>
      <p className="mt-2 text-ink-2">
        thread {s.thread} · live {s.live ? "yes" : "no"} · live tools: {s.tools.length ? s.tools.join(", ") : "none"}
        {s.running ? ` · running: ${s.running}` : ""}
      </p>
    </div>
  );
}
