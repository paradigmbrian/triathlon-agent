import { useEffect } from "react";
import { useJobStream } from "./useJobStream";

type Props = { kind: "sync" | "checkin"; label: string; body: unknown; onDone?: (result: unknown) => void };

function summary(kind: Props["kind"], result: unknown): string {
  const r = (result ?? {}) as Record<string, unknown>;
  if (kind === "sync") return r.ok ? "synced" : "sync had errors";
  if (r.paused) return "review pending, see the gate";
  if (r.no_plan) return "no plan and no profile yet";
  return r.code === 0 ? "clean week" : "check-in did not complete";
}

export default function JobButton({ kind, label, body, onDone }: Props) {
  const { state, start } = useJobStream(kind, body);
  useEffect(() => {
    if (state.status === "done") onDone?.(state.result);
  }, [state.status, state.result, onDone]);
  const text =
    state.status === "running" ? (state.lastLine ?? "starting…")
    : state.status === "done" ? summary(kind, state.result)
    : state.status === "failed" ? (state.error ?? "failed")
    : state.status === "busy" ? `a ${state.busyWith} is running`
    : label;
  const tone = state.status === "failed" ? "text-danger" : state.status === "busy" ? "text-warn" : "";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => void start()}
        disabled={state.status === "running"}
        className={`max-w-56 truncate rounded-md border border-line bg-surface px-3 py-1 text-xs ${tone} disabled:opacity-70`}
        title={text}
      >
        {text}
      </button>
      {state.lines.length > 0 && (
        <details className="absolute right-0 top-full z-10 mt-1 w-80 rounded-md border border-line bg-surface-2 p-2 text-xs shadow">
          <summary className="cursor-pointer text-ink-2">transcript</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap">{state.lines.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}
