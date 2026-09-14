import { useEffect, useRef, type ReactNode } from "react";
import type { ThreadView } from "../../api/queries";
import Activity from "./Activity";
import Composer from "./Composer";
import { Bubble } from "./Message";
import type { useTurnStream } from "./useTurnStream";

type Props = { thread: ThreadView | undefined; stream: ReturnType<typeof useTurnStream>; gate: ReactNode };

export default function Chat({ thread, stream, gate }: Props) {
  const { state } = stream;
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  });
  const onScroll = () => {
    const el = scroller.current;
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };
  const busy = state.status === "busy";
  const hint = busy
    ? `a ${state.busyWith} is running`
    : state.lost
      ? "connection lost, reloading the conversation"
      : thread?.stuck
        ? "the last run stopped early, send any message to continue"
        : undefined;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          {thread?.messages.map((m) =>
            m.role === "activity" ? (
              <Activity key={m.id} text={m.text} args={m.args} where={m.where ?? "coach"} />
            ) : (
              <Bubble key={m.id} role={m.role} where={m.where}>
                {m.text}
              </Bubble>
            ),
          )}
          {state.bubbles.map((b) =>
            b.role === "activity" ? (
              <Activity key={b.id} text={b.text} args={b.args} where={b.where} />
            ) : (
              <Bubble key={b.id} role={b.role} where={b.where}>
                {b.text}
              </Bubble>
            ),
          )}
          {state.status === "streaming" && state.bubbles.length === 0 && <div className="text-xs text-ink-2">thinking…</div>}
          {state.error && (
            <Bubble role="error">
              {state.error}
              {state.lastText && (
                <button type="button" onClick={() => void stream.retry()} className="ml-3 underline">
                  retry
                </button>
              )}
            </Bubble>
          )}
          {gate}
        </div>
      </div>
      <Composer disabled={busy || state.status === "streaming"} hint={hint} onSend={(t) => void stream.send(t)} />
    </div>
  );
}
