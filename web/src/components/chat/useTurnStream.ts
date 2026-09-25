import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, postStream, readSse } from "../../api/client";
import { keys, useThreadRunning, type ReviewPayload, type ThreadView } from "../../api/queries";

export type Bubble =
  | { id: string; role: "user" | "assistant" | "consult" | "report" | "error"; where: string; text: string }
  | { id: string; role: "activity"; where: string; name: string; args?: unknown; chars?: number; text: string };

export type TurnState = {
  status: "idle" | "streaming" | "busy";
  busyWith: string | null;
  bubbles: Bubble[];
  interrupt: ReviewPayload | null;
  error: string | null;
  lost: boolean;
  lastText: string | null;
  /** Text a busy 409 turned away; the composer remounts prefilled with it whenever `id` changes. */
  draft: { id: string; text: string } | null;
};

export type ReviewDecision = { action: "approve" | "reject" | "edit"; note?: string | null; proposals?: unknown[] };

const initial: TurnState = { status: "idle", busyWith: null, bubbles: [], interrupt: null, error: null, lost: false, lastText: null, draft: null };

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
  const [raw, setState] = useState<TurnState>(initial);
  const threadRunning = useThreadRunning();
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // An idle page whose thread says something holds the lock (a page load during a turn, a
  // check-in or a CLI turn) is busy with it until the poller sees `running` go null.
  const state = useMemo<TurnState>(
    () => (raw.status === "idle" && threadRunning != null ? { ...raw, status: "busy", busyWith: threadRunning } : raw),
    [raw, threadRunning],
  );

  // Reentrancy guard: a call while a run is already in flight is ignored (no fetch, no state change).
  const inFlight = useRef(false);

  const run = useCallback(
    async (path: string, body: unknown, lastText: string | null, opts: { rethrow?: boolean } = {}) => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        // The athlete's own message shows while its turn streams; the refetched thread replaces it.
        const mine: Bubble[] = lastText != null ? [{ id: nextId(), role: "user", where: "coach", text: lastText }] : [];
        setState((s) => ({ ...s, status: "streaming", busyWith: null, bubbles: mine, interrupt: null, error: null, lost: false, lastText }));
        let res: Response;
        try {
          res = await postStream(path, body);
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            const running = (e.body as { running?: string | null } | null)?.running ?? null;
            if (running != null) {
              // Nothing was sent: the text goes back into the composer instead of a live bubble.
              setState((s) => ({ ...s, status: "busy", busyWith: running, bubbles: [], draft: lastText != null ? { id: nextId(), text: lastText } : s.draft }));
              return;
            }
            // A 409 without `running` is about the gate, not another run: { reason: "paused" }
            // refused a turn because a review is waiting; { reason: "no_review" } refused a
            // decision because nothing is. Stay idle, surface the message.
            const reason = (e.body as { reason?: string } | null)?.reason;
            setState((s) => ({ ...s, status: "idle", error: reason === "paused" ? "answer the review first" : "nothing is waiting for review" }));
            await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.today })]);
            return;
          }
          // A rejected edit (422 on resume) is shown by the gate, so the chat adds no error bubble.
          const shownByGate = opts.rethrow === true && e instanceof ApiError && e.status === 422;
          setState((s) => ({ ...s, status: "idle", error: shownByGate ? null : e instanceof Error ? e.message : String(e) }));
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
        // A stream lost before `done` leaves the run going server-side: stay busy until the thread catches up.
        const running = qc.getQueryData<ThreadView>(keys.thread)?.running ?? null;
        setState((s) => ({ ...s, status: running != null ? "busy" : "idle", busyWith: running, bubbles: [], interrupt: null, lost: !done }));
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
    if (raw.lastText) await send(raw.lastText);
  }, [send, raw.lastText]);

  // busy: poll the thread every 2 s until running is null (the Chat reads busyWith to disable inputs)
  const polling = state.status === "busy";
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => {
      void (async () => {
        await qc.invalidateQueries({ queryKey: keys.thread });
        if (!alive.current) return;
        const view = qc.getQueryData<ThreadView>(keys.thread);
        if (view && view.running == null) {
          // a run that started meanwhile owns the state
          setState((s) => (s.status === "streaming" ? s : { ...s, status: "idle", busyWith: null, lost: false }));
          await qc.invalidateQueries({ queryKey: keys.today });
        }
      })();
    }, 2000);
    return () => clearInterval(t);
  }, [polling, qc]);

  return { state, send, resume, retry };
}
