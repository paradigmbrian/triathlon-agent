export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export async function bodyOf(res: Response): Promise<unknown> {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return text;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await bodyOf(res);
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export async function apiNoContent(path: string, init?: RequestInit): Promise<void> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new ApiError(res.status, await bodyOf(res));
}

export async function postStream(path: string, body: unknown): Promise<Response> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await bodyOf(res));
  return res;
}

export type SseEvent = { name: string; data: unknown };

function parseFrame(frame: string): SseEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const raw of frame.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  const text = data.join("\n");
  try {
    return { name, data: JSON.parse(text) };
  } catch {
    return { name, data: text };
  }
}

/** Reads a text/event-stream body to its end, calling onEvent per frame. Rejects if the body errors. */
export async function readSse(res: Response, onEvent: (ev: SseEvent) => void): Promise<void> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    let at: number;
    while ((at = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, at);
      buffer = buffer.slice(at + 2);
      const ev = parseFrame(frame);
      if (ev) onEvent(ev);
    }
  }
}
