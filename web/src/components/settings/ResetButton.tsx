import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiNoContent, ApiError } from "../../api/client";
import { keys } from "../../api/queries";

export default function ResetButton() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [forget, setForget] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reset = async () => {
    setLoading(true);
    try {
      await apiNoContent("/api/coach/reset", { method: "POST", body: JSON.stringify({ confirm: true, forget_memory: forget }) });
      setMsg(forget ? "conversation and memory cleared" : "conversation cleared");
      setOpen(false);
      await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.memory }), qc.invalidateQueries({ queryKey: keys.today })]);
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 409 ? `a ${(e.body as { running?: string }).running} is running` : e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };
  return (
    <div>
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="rounded-md border border-danger/50 px-3 py-1 text-sm text-danger">Reset conversation</button>
      ) : (
        <div role="dialog" aria-label="Reset" className="rounded-md border border-line bg-surface-2 p-3 text-sm">
          <p>Forget the coach conversation? Garmin, TrainingPeaks, the tables and the other agents are untouched.</p>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={forget} onChange={(e) => setForget(e.target.checked)} aria-label="forget memory too" />forget memory too</label>
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={loading} onClick={() => void reset()} className="rounded-md bg-danger px-3 py-1 text-white disabled:opacity-50">Confirm reset</button>
            <button type="button" onClick={() => setOpen(false)} className="rounded-md border border-line px-3 py-1">Cancel</button>
          </div>
        </div>
      )}
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </div>
  );
}
