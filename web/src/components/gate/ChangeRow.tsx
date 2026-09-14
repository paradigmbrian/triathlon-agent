import { describeChange } from "./schemaUtils";

export default function ChangeRow({ domain, change }: { domain: string; change: Record<string, unknown> }) {
  return (
    <li className="text-sm">
      {describeChange(domain, change)}
      {change.reason ? <span className="text-ink-2"> — {String(change.reason)}</span> : null}
      {change.athlete_requested ? <span className="ml-1 rounded bg-accent/15 px-1 text-[10px] text-accent">athlete requested</span> : null}
    </li>
  );
}
