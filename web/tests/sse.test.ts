import { readSse, type SseEvent } from "../src/api/client";

function response(chunks: string[]): Response {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { headers: { "content-type": "text/event-stream" } });
}

async function collect(chunks: string[]): Promise<SseEvent[]> {
  const out: SseEvent[] = [];
  await readSse(response(chunks), (ev) => out.push(ev));
  return out;
}

test("frames split on blank lines, even across chunks", async () => {
  const evs = await collect([
    'event: token\ndata: {"where":"coach","te',
    'xt":"Hi"}\n\nevent: done\ndata: {"final_text":"Hi","paused":false}\n\n',
  ]);
  expect(evs).toEqual([
    { name: "token", data: { where: "coach", text: "Hi" } },
    { name: "done", data: { final_text: "Hi", paused: false } },
  ]);
});

test("multi-line data joins with newlines; comments and CRLF are tolerated", async () => {
  const evs = await collect([': ping\r\nevent: line\r\ndata: "a"\r\ndata: "b"\r\n\r\n']);
  // two data lines join to "\"a\"\n\"b\"", which is not JSON: the reader keeps it as a string
  expect(evs).toEqual([{ name: "line", data: '"a"\n"b"' }]);
});

test("an event without a name is 'message'; a trailing partial frame is dropped", async () => {
  const evs = await collect(['data: {"x":1}\n\nevent: token\ndata: {"partial":true}']);
  expect(evs).toEqual([{ name: "message", data: { x: 1 } }]);
});

test("a stream that errors mid-way rejects after delivering what arrived", async () => {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(enc.encode('event: token\ndata: {"t":1}\n\n'));
      // Deferred a microtask: per the WHATWG Streams spec, controller.error() runs
      // ResetQueue and discards any chunk enqueued in the same synchronous tick,
      // so an immediate error() here would make the buffered frame unreadable by
      // any consumer, not just this one. A real network error arrives asynchronously
      // after already-received bytes were read, which is what this reproduces.
      queueMicrotask(() => controller.error(new Error("network")));
    },
  });
  const out: SseEvent[] = [];
  await expect(readSse(new Response(stream), (ev) => out.push(ev))).rejects.toThrow("network");
  expect(out).toEqual([{ name: "token", data: { t: 1 } }]);
});
