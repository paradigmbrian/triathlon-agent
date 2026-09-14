import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, bodyOf, readSse } from "../../api/client";
import { keys } from "../../api/queries";

export type JobState = {
  id: string | null;
  status: "idle" | "running" | "done" | "failed" | "busy";
  lastLine: string | null;
  lines: string[];
  result: unknown;
  error: string | null;
  busyWith: string | null;
};

const initial: JobState = { id: null, status: "idle", lastLine: null, lines: [], result: null, error: null, busyWith: null };

export function useJobStream(kind: "sync" | "checkin", body: unknown) {
  const qc = useQueryClient();
  const [state, setState] = useState<JobState>(initial);
  const storageKey = `job:${kind}`;

  // Guards setState after unmount (e.g. a follow() still in flight when the page navigates
  // away) so tests and real usage never see an act() warning from a late state update.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const follow = useCallback(
    async (id: string) => {
      if (alive.current) setState((s) => ({ ...s, id, status: "running", lines: [], lastLine: null, error: null, result: null }));
      try {
        const res = await fetch(`/api/jobs/${id}/events`, { headers: { accept: "text/event-stream" } });
        if (!res.ok) throw new ApiError(res.status, await bodyOf(res));
        await readSse(res, (ev) => {
          if (!alive.current) return;
          const data = (ev.data ?? {}) as Record<string, unknown>;
          if (ev.name === "line") {
            const text = String(data.text);
            setState((s) => ({ ...s, lastLine: text.split("\n").filter(Boolean).pop() ?? text, lines: [...s.lines, text] }));
          } else if (ev.name === "done") setState((s) => ({ ...s, status: "done", result: data.result }));
          else if (ev.name === "error") setState((s) => ({ ...s, status: "failed", error: String(data.message) }));
        });
      } catch (e) {
        if (alive.current) setState((s) => ({ ...s, status: "failed", error: e instanceof Error ? e.message : String(e) }));
      } finally {
        sessionStorage.removeItem(storageKey);
        await Promise.all([qc.invalidateQueries({ queryKey: keys.today }), qc.invalidateQueries({ queryKey: keys.thread })]);
      }
    },
    [qc, storageKey],
  );

  const start = useCallback(async () => {
    try {
      const { id } = await api<{ id: string }>(`/api/jobs/${kind}`, { method: "POST", body: JSON.stringify(body) });
      sessionStorage.setItem(storageKey, id);
      await follow(id);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 409) {
        const running = (e.body as { running?: string } | null)?.running ?? "run";
        setState((s) => ({ ...s, status: "busy", busyWith: running }));
        return;
      }
      setState((s) => ({ ...s, status: "failed", error: e instanceof Error ? e.message : String(e) }));
    }
  }, [kind, body, follow, storageKey]);

  // R6: StrictMode runs mount effects twice in dev, which would otherwise follow a stored job id
  // twice (duplicating every transcript line and double-hitting the events endpoint). A ref that
  // is only ever set, never reset, makes the second invocation on the same hook instance a no-op.
  const reattached = useRef(false);
  useEffect(() => {
    if (reattached.current) return;
    reattached.current = true;
    const id = sessionStorage.getItem(storageKey);
    if (id) void follow(id);
  }, [follow, storageKey]);

  useEffect(() => {
    if (state.status !== "done" && state.status !== "failed" && state.status !== "busy") return;
    const t = setTimeout(() => {
      if (alive.current) setState((s) => ({ ...s, status: "idle", busyWith: null }));
    }, 5000);
    return () => clearTimeout(t);
  }, [state.status]);

  return { state, start };
}
