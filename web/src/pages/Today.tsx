import Header from "../components/Header";
import Strip from "../components/today/Strip";
import Chat from "../components/chat/Chat";
import Gate from "../components/gate/Gate";
import JobButton from "../components/jobs/JobButton";
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
  const slots = (
    <>
      <JobButton kind="sync" label="Sync now" body={{}} />
      <JobButton kind="checkin" label="Weekly check-in" body={{ sync: true }} />
    </>
  );
  return (
    <>
      <Header today={today.data} slots={slots} />
      <Strip today={today.data} />
      <Chat thread={thread.data} stream={stream} gate={gate} />
    </>
  );
}
