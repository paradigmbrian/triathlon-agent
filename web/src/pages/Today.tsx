import Strip from "../components/today/Strip";
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
  const paused = stream.state.interrupt ?? thread.data?.paused ?? null;
  const held = !paused ? (thread.data?.held ?? null) : null;
  const gate = paused ? (
    <Gate payload={paused} mode="paused" onDecide={stream.resume} disabled={stream.state.status !== "idle"} />
  ) : held ? (
    <Gate payload={held} mode="held" onDecide={stream.resume} />
  ) : null;
  return (
    // Below md the page scrolls as one column, cards then chat; from md the cards stack in a
    // column left of the chat and each side scrolls on its own.
    <div className="flex flex-col md:min-h-0 md:flex-1 md:flex-row">
      <Strip today={today.data} />
      <Chat thread={thread.data} stream={stream} gate={gate} />
    </div>
  );
}
