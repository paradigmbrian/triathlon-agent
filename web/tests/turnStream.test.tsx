import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTurnStream } from "../src/components/chat/useTurnStream";

function sse(frames: [string, unknown][]): Response {
  const body = frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.restoreAllMocks());

test("a turn groups tokens by where, records activity, and clears after done", async () => {
  const client = new QueryClient();
  const releaseInvalidate: (() => void)[] = [];
  const invalidate = vi.spyOn(client, "invalidateQueries").mockImplementation(
    () =>
      new Promise((resolve) => {
        releaseInvalidate.push(() => resolve(undefined));
      }),
  );
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    sse([
      ["token", { where: "coach", text: "Let me " }],
      ["token", { where: "coach", text: "check." }],
      ["tool_call", { where: "coach", name: "ask_analyst", args: { question: "CTL?" } }],
      ["token", { where: "analyst", text: "CTL 45" }],
      ["tool_result", { where: "coach", name: "ask_analyst", chars: 6 }],
      ["token", { where: "coach", text: "Your CTL is 45." }],
      ["done", { final_text: "Your CTL is 45.", paused: false }],
    ]),
  );
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  let sending!: Promise<void>;
  act(() => {
    sending = result.current.send("how fit am I?");
  });
  await waitFor(() => expect(result.current.state.bubbles.length).toBeGreaterThan(0));
  const seen = result.current.state.bubbles.map((b) => `${b.role}:${b.where}:${b.text}`);
  expect(seen).toContain("assistant:coach:Let me check.");
  await waitFor(() => expect(releaseInvalidate.length).toBe(2));
  await act(async () => {
    releaseInvalidate.forEach((release) => release());
    await sending;
  });
  await waitFor(() => expect(result.current.state.status).toBe("idle"));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["thread"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["today"] });
  expect(result.current.state.bubbles).toEqual([]);
  expect(fetch).toHaveBeenCalledWith("/api/coach/turns", expect.objectContaining({ method: "POST", body: JSON.stringify({ text: "how fit am I?" }) }));
});

test("bubbles while streaming: one per where run, activity rows in between", async () => {
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockImplementation(() => new Promise(() => {})); // never resolves: keep the state
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    sse([
      ["token", { where: "coach", text: "A" }],
      ["tool_call", { where: "coach", name: "consult_planning", args: {} }],
      ["token", { where: "planning", text: "B" }],
      ["consult", { domain: "planning", text: "p1 (planning): move it" }],
      ["report", { text: "planning: applied 1" }],
      ["interrupt", { narration: "n", proposals: [] }],
      ["done", { final_text: "", paused: true }],
    ]),
  );
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  act(() => {
    void result.current.send("x");
  });
  await waitFor(() => expect(result.current.state.interrupt).not.toBeNull());
  const b = result.current.state.bubbles;
  expect(b.map((x) => x.role)).toEqual(["assistant", "activity", "assistant", "consult", "report"]);
  expect(b[2]).toMatchObject({ where: "planning", text: "B" });
  expect(result.current.state.interrupt).toEqual({ narration: "n", proposals: [] });
});

test("a 409 marks the page busy with the running kind", async () => {
  const client = new QueryClient();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ running: "checkin" }), { status: 409 }));
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  await act(() => result.current.send("x"));
  expect(result.current.state.status).toBe("busy");
  expect(result.current.state.busyWith).toBe("checkin");
});

test("a 409 without a running kind is not busy: idle, a specific message, both invalidations", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ reason: "no_review" }), { status: 409 }));
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  await act(() => result.current.resume({ action: "approve" }));
  expect(result.current.state.status).toBe("idle");
  expect(result.current.state.busyWith).toBeNull();
  expect(result.current.state.error).toBe("nothing is waiting for review");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["thread"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["today"] });
});

test("a second send while the first stream is open does not call fetch again", () => {
  const client = new QueryClient();
  const openStream = () => new Response(new ReadableStream<Uint8Array>({ start() {} }), { status: 200, headers: { "content-type": "text/event-stream" } });
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(openStream());
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  act(() => {
    void result.current.send("first");
    void result.current.send("second");
  });
  expect(f).toHaveBeenCalledTimes(1);
  expect(result.current.state.lastText).toBe("first");
});

test("send resolves after a non-409 failure (error is recorded, not thrown); resume rethrows a 422", async () => {
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const f = vi.spyOn(globalThis, "fetch");
  f.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  await act(() => result.current.send("x")); // must not reject
  await waitFor(() => expect(result.current.state.status).toBe("idle"));
  expect(result.current.state.error).toBe("boom");

  f.mockResolvedValueOnce(new Response(JSON.stringify({ errors: ["bad edit"] }), { status: 422 }));
  await expect(act(() => result.current.resume({ action: "edit", proposals: [] }))).rejects.toMatchObject({ status: 422 });
});

test("an error event keeps the text for retry; a lost stream is flagged", async () => {
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const f = vi.spyOn(globalThis, "fetch");
  f.mockResolvedValueOnce(sse([["error", { message: "rate limited" }], ["done", { final_text: "", paused: false }]]));
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  await act(() => result.current.send("again"));
  await waitFor(() => expect(result.current.state.status).toBe("idle"));
  expect(result.current.state.error).toBe("rate limited");
  expect(result.current.state.lastText).toBe("again");
  f.mockResolvedValueOnce(sse([["token", { where: "coach", text: "ok" }]])); // no done
  await act(() => result.current.retry());
  expect(f).toHaveBeenLastCalledWith("/api/coach/turns", expect.objectContaining({ body: JSON.stringify({ text: "again" }) }));
  await waitFor(() => expect(result.current.state.lost).toBe(true));
});
