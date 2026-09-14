import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, postStream, readSse } from "../../api/client";
import { keys, type ReviewPayload } from "../../api/queries";

export type Bubble =
  | { id: string; role: "assistant" | "consult" | "report" | "error"; where: string; text: string }
  | { id: string; role: "activity"; where: string; name: string; args?: unknown; chars?: number; text: string };

export type TurnState = {
  status: "idle" | "streaming" | "busy";
  busyWith: string | null;
  bubbles: Bubble[];
  interrupt: ReviewPayload | null;
  error: string | null;
  lost: boolean;
  lastText: string | null;
};

export type ReviewDecision = { action: "approve" | "reject" | "edit"; note?: string | null; proposals?: unknown[] };

const initial: TurnState = { status: "idle", busyWith: null, bubbles: [], interrupt: null, error: null, lost: false, lastText: null };

let seq = 0;
const nextId = () => `live-${++seq}`;

function applyEvent(bubbles: Bubble[], name: string, data: Record<string, unknown>): Bubble[] {
  const last = bubbles[bubbles.length - 1];
  switch (name) {
    case "token": {
      const where = String(data.where);
      const text = String(data.text);
      if (last && last.role === "assistant" && last.where === where) {
        return [...bubbles.slice(0, -1), { ...last, text: last.text + text }];
      }
      return [...bubbles, { id: nextId(), role: "assistant", where, text }];
    }
    case "tool_call":
      return [...bubbles, { id: nextId(), role: "activity", where: String(data.where), name: String(data.name), args: data.args, text: `→ ${String(data.name)}` }];
    case "tool_result":
      return [...bubbles, { id: nextId(), role: "activity", where: String(data.where), name: String(data.name), chars: Number(data.chars), text: `← ${String(data.name)}: ${String(data.chars)} chars` }];
    case "consult":
      return [...bubbles, { id: nextId(), role: "consult", where: String(data.domain), text: String(data.text) }];
    case "report":
      return [...bubbles, { id: nextId(), role: "report", where: "coach", text: String(data.text) }];
    default:
      return bubbles;
  }
}

export function useTurnStream() {
  const qc = useQueryClient();
  const [state, setState] = useState<TurnState>(initial);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Reentrancy guard: a call while a run is already in flight is ignored (no fetch, no state change).
  const inFlight = useRef(false);

  const run = useCallback(
    async (path: string, body: unknown, lastText: string | null, opts: { rethrow?: boolean } = {}) => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        setState((s) => ({ ...s, status: "streaming", busyWith: null, bubbles: [], interrupt: null, error: null, lost: false, lastText }));
        let res: Response;
        try {
          res = await postStream(path, body);
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            const running = (e.body as { running?: string | null } | null)?.running ?? null;
            if (running != null) {
              setState((s) => ({ ...s, status: "busy", busyWith: running }));
              return;
            }
            // A 409 without `running` (e.g. { reason: "no_review" }) means nothing is waiting
            // for review, not that something else is running: stay idle, surface the message.
            setState((s) => ({ ...s, status: "idle", error: "nothing is waiting for review" }));
            await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.today })]);
            return;
          }
          setState((s) => ({ ...s, status: "idle", error: e instanceof Error ? e.message : String(e) }));
          if (opts.rethrow) throw e;
          return;
        }
        let done = false;
        try {
          await readSse(res, (ev) => {
            const data = (ev.data ?? {}) as Record<string, unknown>;
            if (ev.name === "interrupt") setState((s) => ({ ...s, interrupt: data as unknown as ReviewPayload }));
            else if (ev.name === "error") setState((s) => ({ ...s, error: String(data.message) }));
            else if (ev.name === "done") done = true;
            else setState((s) => ({ ...s, bubbles: applyEvent(s.bubbles, ev.name, data) }));
          });
        } catch {
          done = false;
        }
        await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.today })]);
        if (!alive.current) return;
        setState((s) => ({ ...s, status: "idle", bubbles: [], interrupt: null, lost: !done }));
      } finally {
        inFlight.current = false;
      }
    },
    [qc],
  );

  // Only `resume` rethrows: the review gate (Task 6) catches a rejected edit (422) to show its
  // errors inline. `send`/`retry` resolve after recording the failure in `state.error` instead.
  const send = useCallback((text: string) => run("/api/coach/turns", { text }, text), [run]);
  const resume = useCallback((decision: ReviewDecision) => run("/api/coach/review", decision, null, { rethrow: true }), [run]);
  const retry = useCallback(async () => {
    if (state.lastText) await send(state.lastText);
  }, [send, state.lastText]);

  // busy: poll the thread every 2 s until running is null (the Chat reads busyWith to disable inputs)
  useEffect(() => {
    if (state.status !== "busy") return;
    const t = setInterval(() => {
      void (async () => {
        await qc.invalidateQueries({ queryKey: keys.thread });
        if (!alive.current) return;
        const view = qc.getQueryData<{ running: string | null }>(keys.thread);
        if (view && view.running == null) {
          setState((s) => ({ ...s, status: "idle", busyWith: null }));
          await qc.invalidateQueries({ queryKey: keys.today });
        }
      })();
    }, 2000);
    return () => clearInterval(t);
  }, [state.status, qc]);

  return { state, send, resume, retry };
}
