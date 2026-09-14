import { StrictMode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useJobStream } from "../src/components/jobs/useJobStream";

function sse(frames: [string, unknown][]): Response {
  const body = frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}
const wrapper = (client: QueryClient) => ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

test("start posts the job, follows its events, keeps the last line, invalidates on done", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const f = vi.spyOn(globalThis, "fetch");
  f.mockResolvedValueOnce(new Response(JSON.stringify({ id: "ab12" }), { status: 200 }));
  f.mockResolvedValueOnce(sse([["line", { text: "== garmin: ok, 3 rows" }], ["done", { result: { ok: true, results: [] } }]]));
  const { result } = renderHook(() => useJobStream("sync", { full: false }), { wrapper: wrapper(client) });
  await act(() => result.current.start());
  await waitFor(() => expect(result.current.state.status).toBe("done"));
  expect(f).toHaveBeenNthCalledWith(1, "/api/jobs/sync", expect.objectContaining({ method: "POST" }));
  expect(f).toHaveBeenNthCalledWith(2, "/api/jobs/ab12/events", expect.anything());
  expect(result.current.state.lastLine).toBe("== garmin: ok, 3 rows");
  expect(result.current.state.result).toEqual({ ok: true, results: [] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["today"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["thread"] });
  expect(sessionStorage.getItem("job:sync")).toBeNull(); // cleared once done
});

test("a 409 on check-in is busy with the running kind", async () => {
  const client = new QueryClient();
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ running: "turn" }), { status: 409 }));
  const { result } = renderHook(() => useJobStream("checkin", { sync: true }), { wrapper: wrapper(client) });
  await act(() => result.current.start());
  expect(result.current.state.status).toBe("busy");
  expect(result.current.state.busyWith).toBe("turn");
});

test("a job id in sessionStorage is re-attached on mount", async () => {
  sessionStorage.setItem("job:checkin", "zz99");
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(sse([["line", { text: "resumed" }], ["error", { message: "boom" }]]));
  const { result } = renderHook(() => useJobStream("checkin", { sync: true }), { wrapper: wrapper(client) });
  await waitFor(() => expect(result.current.state.status).toBe("failed"));
  expect(result.current.state.error).toBe("boom");
  expect(fetch).toHaveBeenCalledWith("/api/jobs/zz99/events", expect.anything());
});

// R6: StrictMode runs mount effects twice in dev. The re-attach effect must run once per hook
// instance (not once per StrictMode double-invoke), or the transcript would duplicate lines and
// the job's events endpoint would be hit twice for the same stored id.
test("a stored job id under StrictMode is followed exactly once", async () => {
  sessionStorage.setItem("job:sync", "dup1");
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(sse([["done", { result: { ok: true, results: [] } }]]));
  const strictWrapper = ({ children }: { children: ReactNode }) => (
    <StrictMode>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </StrictMode>
  );
  const { result } = renderHook(() => useJobStream("sync", {}), { wrapper: strictWrapper });
  await waitFor(() => expect(result.current.state.status).toBe("done"));
  expect(f).toHaveBeenCalledTimes(1);
  expect(f).toHaveBeenCalledWith("/api/jobs/dup1/events", expect.anything());
});

// R25 finding 1: a non-2xx from the events endpoint must be parsed the same way api() parses a
// body (JSON in, `detail` surfaced), not stringified as "HTTP 404".
test("a 404 from the events endpoint surfaces the server's detail and clears sessionStorage", async () => {
  sessionStorage.setItem("job:checkin", "zz99");
  const client = new QueryClient();
  vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "no job zz99" }), { status: 404 }),
  );
  const { result } = renderHook(() => useJobStream("checkin", { sync: true }), { wrapper: wrapper(client) });
  await waitFor(() => expect(result.current.state.status).toBe("failed"));
  expect(result.current.state.error).toBe("no job zz99");
  expect(sessionStorage.getItem("job:checkin")).toBeNull();
});

// R25 finding 3: nothing must update state, and nothing must be logged, once the hook has
// unmounted while its events stream is still open.
test("unmounting while the events stream stays open produces no console errors and no invalidation", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const openStream = () =>
    new Response(new ReadableStream<Uint8Array>({ start() {} }), { status: 200, headers: { "content-type": "text/event-stream" } });
  const f = vi.spyOn(globalThis, "fetch");
  f.mockResolvedValueOnce(new Response(JSON.stringify({ id: "hang1" }), { status: 200 }));
  f.mockResolvedValueOnce(openStream());
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  const { result, unmount } = renderHook(() => useJobStream("sync", {}), { wrapper: wrapper(client) });
  act(() => {
    void result.current.start();
  });
  await waitFor(() => expect(result.current.state.status).toBe("running"));
  unmount();
  // let any pending microtasks settle before asserting nothing fired after unmount
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(errorSpy).not.toHaveBeenCalled();
  // the stream never closed, so the job never reached done/failed: no invalidation yet
  expect(invalidate).not.toHaveBeenCalled();
});
