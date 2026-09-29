import { useEffect, useState } from "react";
import Board from "../components/board/Board";
import Chat from "../components/chat/Chat";
import Gate from "../components/gate/Gate";
import { useTurnStream } from "../components/chat/useTurnStream";
import { useThread, useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  const stream = useTurnStream();
  // The turn-stream hook is the single poller while busy (it invalidates ["thread"] every
  // 2 s); this query just reads whatever that invalidation last put in the cache.
  const thread = useThread();
  const [coachOpen, setCoachOpen] = useState(false);
  const paused = stream.state.interrupt ?? thread.data?.paused ?? null;
  const held = !paused ? (thread.data?.held ?? null) : null;
  const review = paused ?? held ?? today.data?.pending ?? null;
  const gateBody = paused ? (
    <Gate payload={paused} mode="paused" onDecide={stream.resume} disabled={stream.state.status !== "idle"} />
  ) : held ? (
    <Gate payload={held} mode="held" onDecide={stream.resume} />
  ) : null;
  const gate = gateBody && (
    <div id="review-gate" tabIndex={-1} className="focus:outline-none">
      {gateBody}
    </div>
  );

  useEffect(() => {
    if (!coachOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCoachOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [coachOpen]);

  const toHold = () => {
    setCoachOpen(true);
    window.setTimeout(() => document.getElementById("review-gate")?.focus(), 0);
  };

  return (
    // From xl the board and the coach sit side by side and each scrolls on its own; below xl
    // the coach opens over the board from the Coach toggle (kept mounted so a stream survives).
    <div className="flex min-h-0 flex-1">
      <div className={`min-w-0 flex-1 overflow-y-auto ${coachOpen ? "hidden xl:block" : ""}`}>
        <div className="flex justify-end px-6 pt-4 xl:hidden">
          <button
            type="button"
            aria-expanded={coachOpen}
            aria-controls="coach-panel"
            onClick={() => setCoachOpen(true)}
            className="inline-flex min-h-8 items-center rounded-md border border-line px-3 text-sm"
          >
            Coach{review ? " · hold" : ""}
          </button>
        </div>
        <Board today={today.data} review={review} onHold={toHold} />
      </div>
      <aside
        id="coach-panel"
        aria-label="Coach"
        className={`${coachOpen ? "flex" : "hidden"} min-h-0 w-full flex-col bg-surface-2 xl:flex xl:w-[32rem] xl:shrink-0 xl:border-l xl:border-line`}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2 xl:hidden">
          <span className="text-xs font-medium tracking-wider text-ink-2 uppercase">Coach</span>
          <button type="button" onClick={() => setCoachOpen(false)} className="inline-flex min-h-8 items-center rounded-md border border-line px-3 text-sm">
            Back to board
          </button>
        </div>
        <Chat thread={thread.data} stream={stream} gate={gate} paused={paused != null} />
      </aside>
    </div>
  );
}
