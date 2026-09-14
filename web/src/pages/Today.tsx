import Header from "../components/Header";
import Strip from "../components/today/Strip";
import Chat from "../components/chat/Chat";
import { useTurnStream } from "../components/chat/useTurnStream";
import { useThread, useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  const stream = useTurnStream();
  const thread = useThread(stream.state.status === "busy" ? 2000 : false);
  return (
    <>
      <Header today={today.data} />
      <Strip today={today.data} />
      <Chat thread={thread.data} stream={stream} gate={null} />
    </>
  );
}
