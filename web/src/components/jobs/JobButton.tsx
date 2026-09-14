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
    // Below md the transcript opens under the whole header (the header is the positioned
    // ancestor), so it never covers the job buttons; from md it hangs under this button.
    <div className="flex items-center gap-1 md:relative">
      <button
        type="button"
        onClick={() => void start()}
        disabled={state.status === "running"}
        className={`max-w-56 truncate rounded-md border border-line bg-surface px-3 py-1 text-xs hover:border-ink-2 ${tone} disabled:opacity-70`}
        title={text}
      >
        {text}
      </button>
      {state.lines.length > 0 && (
        <details name="job-transcript" className="text-xs">
          <summary className="cursor-pointer rounded px-1 py-1 text-ink-2 hover:text-ink">transcript</summary>
          <pre className="absolute inset-x-4 top-full z-20 mt-1 max-h-64 overflow-auto rounded-md border border-line bg-surface-2 p-2 whitespace-pre-wrap shadow-lg md:inset-x-auto md:right-0 md:w-80">
            {state.lines.join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
