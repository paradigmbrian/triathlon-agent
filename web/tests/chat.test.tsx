import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import Chat from "../src/components/chat/Chat";
import { useTurnStream } from "../src/components/chat/useTurnStream";
import { useThread, type ThreadView } from "../src/api/queries";
import { renderWith, threadEmpty } from "./fixtures";

function Harness({ paused = false }: { paused?: boolean }) {
  const stream = useTurnStream();
  const thread = useThread();
  return (
    <>
      <output data-testid="probe" data-status={stream.state.status} data-running={thread.data?.running ?? "none"} />
      <Chat thread={thread.data} stream={stream} gate={null} paused={paused} />
    </>
  );
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const sse = (frames: [string, unknown][]) =>
  new Response(frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join(""), { status: 200, headers: { "content-type": "text/event-stream" } });
const openStream = () => new Response(new ReadableStream<Uint8Array>({ start() {} }), { status: 200, headers: { "content-type": "text/event-stream" } });

/** The thread route serves whatever `thread()` returns now; turns go to `turn`. */
function stubServer(thread: () => ThreadView, turn: (text: string) => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/coach/thread") return json(thread());
    if (url === "/api/coach/turns") return turn((JSON.parse(String(init?.body)) as { text: string }).text);
    return json({ detail: `unexpected ${url}` }, 500);
  });
}

const LOST = "connection lost, reloading the conversation";

function sendText(text: string) {
  const box = screen.getByLabelText("Message");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.submit(box.closest("form")!);
}

/** Fire the busy poll (setInterval is faked; setTimeout stays real so fetches and notifications settle). */
const poll = () =>
  act(async () => {
    vi.advanceTimersByTime(2000);
    for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0));
  });

beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("a stream lost mid-turn stays busy with the lost sentence until the thread catches up", async () => {
  let thread = threadEmpty();
  stubServer(
    () => thread,
    () => {
      thread = { ...threadEmpty(), running: "turn" }; // the run goes on server-side
      return sse([["token", { where: "coach", text: "Let me" }]]); // ends without done
    },
  );
  renderWith(<Harness />);
  const probe = screen.getByTestId("probe");
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  sendText("how fit am I?");
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "turn"));
  expect(probe).toHaveAttribute("data-status", "busy");
  expect(screen.getByText(LOST)).toBeInTheDocument();
  expect(screen.getByLabelText("Message")).toBeDisabled();

  thread = {
    ...threadEmpty(),
    messages: [
      { id: "h1", role: "user", text: "how fit am I?" },
      { id: "a1", role: "assistant", where: "coach", text: "Let me check. CTL 45." },
    ],
  };
  await poll();
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  expect(probe).toHaveAttribute("data-status", "idle");
  expect(screen.queryByText(LOST)).not.toBeInTheDocument();
  expect(screen.getByText("Let me check. CTL 45.")).toBeInTheDocument();
  expect(screen.getByLabelText("Message")).toBeEnabled();
});

test("a busy 409 hands the text back to the composer; it sends once the run ends and shows while streaming", async () => {
  let thread = threadEmpty();
  const turn = vi.fn<(text: string) => Response>(() => {
    if (turn.mock.calls.length === 1) {
      thread = { ...threadEmpty(), running: "checkin" };
      return json({ running: "checkin" }, 409);
    }
    return openStream();
  });
  stubServer(() => thread, turn);
  renderWith(<Harness />);
  const probe = screen.getByTestId("probe");
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  sendText("move my run");
  await waitFor(() => expect(screen.getByLabelText("Message")).toHaveValue("move my run"));
  expect(screen.getByText("a checkin is running")).toBeInTheDocument();
  expect(screen.getByLabelText("Message")).toBeDisabled();
  expect(within(screen.getByTestId("chat-messages")).queryByText("move my run")).not.toBeInTheDocument();
  await poll(); // still running: stays busy
  expect(screen.getByText("a checkin is running")).toBeInTheDocument();

  thread = threadEmpty();
  await poll();
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  const box = screen.getByLabelText("Message");
  expect(box).toBeEnabled();
  expect(box).toHaveValue("move my run");
  fireEvent.submit(box.closest("form")!);
  await waitFor(() => expect(turn).toHaveBeenCalledTimes(2));
  expect(turn).toHaveBeenLastCalledWith("move my run");
  const messages = within(screen.getByTestId("chat-messages"));
  expect(await messages.findByText("move my run")).toBeInTheDocument();
  expect(messages.getByText("thinking…")).toBeInTheDocument();
  expect(screen.getByLabelText("Message")).toHaveValue("");
});

test("a paused review disables the composer with the hint to answer it first", async () => {
  stubServer(() => threadEmpty(), () => openStream());
  renderWith(<Harness paused />);
  const probe = screen.getByTestId("probe");
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  expect(probe).toHaveAttribute("data-status", "idle");
  expect(screen.getByLabelText("Message")).toBeDisabled();
  expect(screen.getByText("answer the review first")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
});
