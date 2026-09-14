import Header from "../components/Header";
import Strip from "../components/today/Strip";
import Chat from "../components/chat/Chat";
import { useTurnStream } from "../components/chat/useTurnStream";
import { useThread, useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  const stream = useTurnStream();
  // The turn-stream hook is the single poller while busy (it invalidates ["thread"] every
  // 2 s); this query just reads whatever that invalidation last put in the cache.
  const thread = useThread();
  return (
    <>
      <Header today={today.data} />
      <Strip today={today.data} />
      <Chat thread={thread.data} stream={stream} gate={null} />
    </>
  );
}
