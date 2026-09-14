# tri-web Plan 3 of 3: The React App (shell, Today strip, coach chat, gate, jobs, settings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The athlete's browser UI in `web/`: a shell with a rail and header, the Today page with its four-card strip over a chat that streams the coach's turn, a review gate with approve, reject and a schema-generated edit form (YAML fallback), Sync now and Weekly check-in job buttons, and a Settings page with memory, reset and readiness. `npm --prefix web run build` produces `web/dist`, which `tri-web serve` already serves.

**Architecture:** Vite + React 19 + TypeScript. Server state lives in TanStack Query (`today`, `thread`, `memory`, `status`, `schema`); the in-flight turn lives in a `useTurnStream` hook that reads the SSE body with `fetch` and a stream reader and invalidates `thread` and `today` on `done`. Types come from the server's OpenAPI document (`openapi-typescript`, committed). One component set renders history (`UiMessage`) and live events (bubbles by `where`). The gate's `SchemaForm` walks the change model's JSON schema (`GET /api/coach/review/schema`) and validates through `POST /api/coach/review/validate` with a debounce. Tailwind v4 with a small token set in `src/index.css`, light and dark; the rail becomes a bottom bar under 768 px.

**Tech Stack:** Node 22.16, npm 11.4; React 19, Vite 7, TypeScript 5, Tailwind 4 (`@tailwindcss/vite`), `@tanstack/react-query` 5, `react-router` 7, `openapi-typescript` 7; Vitest 3 with `jsdom` and `@testing-library/react`; Playwright 1.5x (one smoke test, API stubbed with `page.route`). Versions are whatever `npm install <pkg>@latest` resolves on the day; majors above are the floor.

**Spec:** `docs/superpowers/specs/2026-09-14-tri-web-design.md` (§1 frontend and home screen decisions, §4 `web/` layout, §5.2 to §5.4 the contract the client consumes, §6.2 card null sentences, §6.3 to §6.8 behaviour as seen from the page, §7 frontend, §8 frontend tests and the definition of done). Plans 1 and 2 (`feat/tri-web-01`, `feat/tri-web-02`) must be merged first.

## Global Constraints

- Worktree `../triathlon_agent-web-03` on `feat/tri-web-03` from `main` after plan 2 merges; copy `.env`; `uv sync`; `npm --prefix web install` after Task 1. Commit per task with the session trailers. Vault export for every markdown file.
- `web/` is an npm project with its own `package-lock.json`, not a uv member. `web/node_modules` and `web/dist` are never committed (`dist/` is already in `.gitignore`; add `web/node_modules/`).
- The dev server proxies `/api` to `http://127.0.0.1:8321`; production is `tri-web serve` alone.
- Definition of done per task: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`, then `uv run pytest -q` when the server changed (it should not in this plan, except `README.md`). Whole sub-project DoD (spec §8): those, plus `uv run ruff check . && uv run ruff format --check . && uv run mypy`, plus the manual session in Task 9.
- The page works at 400 px wide (strip stacks, rail becomes a bottom bar). Colours come from tokens only (`surface`, `surface-2`, `ink`, `ink-2`, `accent`, `planning`, `nutrition`, `warn`, `danger`), each defined for light and dark.
- Every card's null state is a sentence, never an empty box: "No session planned", "No Garmin data yet, sync first", "No targets yet, ask the coach", "No plan; ask the coach to build one", "No panels stored", "Labs not configured".
- Copy for the fixed states (verbatim): composer placeholder `Ask your coach`; stuck banner `the last run stopped early, send any message to continue`; busy `a {running} is running`; lost stream `connection lost, reloading the conversation`; held card line `held from an earlier apply; ask the coach to re-propose it`; empty-edit refusal `reject instead`.
- The `frontend-design` skill is invoked for the visual pass in Task 9, not before; Tasks 1 to 8 use the tokens and plain Tailwind utilities.
- No global store, no Redux, no Zustand. No `any` in `src/` (`eslint` with `@typescript-eslint/no-explicit-any` as error, from the Vite template).

### Facts verified while writing this plan

1. Server contract (plans 1, 2): routes and bodies exactly as spec §5.2; SSE frames are `event: <name>\ndata: <json>\n\n`; a `done` event ends a turn or review stream; `409 {running}` and `409 {reason: "no_review"}`; `422 {detail: "edit rejected", errors: [{loc, msg}]}`; job events `line {text}`, `done {result}`, `error {message}`.
2. `uv run tri-web openapi` prints the document; component schemas include `ThreadView`, `UiMessage`, `ReviewPayload`, `TodayView` and its sub-models, `Validated`, `ValidationItem`, `SchemaOut`, `StatusOut`, `MemoryOut`, `MemoryEntry`, `JobOut`, `TurnIn`, `ReviewIn`, `ValidateIn`, `ResetIn`, `SyncIn`, `CheckinIn`.
3. `Proposal` JSON: `{id, domain, summary, changes: [...], violations: [...], question: string | null, overrides: object | null}`. Planning change: `{op, workout_date, tp_workout_id, workout: PlannedSession | null, new_date, payload, reason, athlete_requested}`; `PlannedSession`: `{date, sport, title, description, duration_minutes, tss_planned, intensity, structure}`. Nutrition change: `{op, target_key, day, payload, reason}`. Enums come through as `enum` arrays on the property; optionals as `anyOf: [{...}, {type: "null"}]`; `PlannedSession` sits in `$defs` and is referenced with `$ref: "#/$defs/PlannedSession"`; `payload` is `{type: "object", additionalProperties: true}` (planning: inside `anyOf` with null).
4. Tailwind v4 needs no `tailwind.config.ts`: `@import "tailwindcss";` in the entry CSS and the Vite plugin. Theme tokens are declared with `@theme inline { --color-surface: var(--surface); ... }` over CSS variables that a `prefers-color-scheme: dark` block overrides. The spec's `tailwind.config.ts` entry in §4 is therefore not created.
5. `fetch` `Response.body` is a `ReadableStream<Uint8Array>`; reading with `getReader()` and `TextDecoder({stream: true})` and splitting on blank lines is the whole SSE reader. Playwright's `page.route(..., route.fulfill({body}))` delivers the body at once, which the reader handles as one chunk.
6. Vite's `server.proxy` forwards streaming responses unbuffered; no special config is needed for SSE through the dev proxy.

### Decisions this plan makes where the spec is silent or its literal reading fails

- **Types file:** `web/src/api/types.ts` is generated by `npm run types` (which runs `uv run tri-web openapi > openapi.json` then `openapi-typescript`), committed, and regenerated whenever a route model changes. `web/openapi.json` is committed too so the frontend can be built without Python present.
- **Live state resets after `done`:** the hook keeps bubbles only while a stream is open; on `done` it awaits `invalidateQueries(["thread"])` and `["today"]`, then clears its bubbles, so history is always the checkpoint's view and nothing renders twice. The gate shows `thread.paused` (after the refetch) or the live `interrupt` event while the refetch is in flight.
- **Bubble grouping:** consecutive `token` events with the same `where` append to one assistant bubble; a `tool_call`, `tool_result`, `consult` or `report` closes it. A `where` other than `coach` gets a small tag (`planning`, `nutrition`, `analyst`) in that domain's colour.
- **Activity rows** show `→ name` / `← name: N chars`, collapsed; expanding shows `args` as pretty JSON.
- **The gate is one component with a `mode`:** `paused` (buttons) or `held` (no buttons, the held line). Edit mode holds a local JSON copy of the proposals; `SchemaForm` is controlled.
- **`SchemaForm` field rules** (spec §6.5) resolve `$ref` and `anyOf`-with-null; unknown shapes fall back to a JSON text input for that field so a new model field never breaks the form.
- **Validation errors index by `loc.join(".")`**, e.g. `0.changes.1.new_date`; unmatched errors show under the proposal.
- **Job buttons** post the job, then open `GET /api/jobs/{id}/events`; the button label shows the last `line` while running, the result for five seconds after; the transcript panel is a `<details>` under the header, remembered per job id in component state only. The job id is kept in `sessionStorage` so a reload re-attaches (replay makes that free).
- **Busy polling:** on a 409 from a turn, review or check-in, the page sets `busy = running` and refetches `thread` every 2 s until `running` is null, then clears.
- **Placeholder pages** say: "Progress arrives in sub-project 2 (tri-web progress)." and likewise for Nutrition (3) and Labs (4).
- **Playwright** runs against `vite preview` on port 4173 with every `/api/*` request stubbed by `page.route`; no Python process is needed for the smoke test.
- **Out of scope:** charts, calendar, nutrition and labs pages (sub-projects 2 to 4); auth; hosting.

---

## File Structure

```
.gitignore                              modify: + web/node_modules/
web/package.json                        scripts: dev, build, preview, lint, test, test:e2e, types
web/vite.config.ts                      react + tailwind plugins, /api proxy, vitest config
web/tsconfig.json  web/tsconfig.app.json  web/tsconfig.node.json   from the template
web/eslint.config.js                    from the template
web/playwright.config.ts
web/index.html
web/openapi.json                        generated, committed
web/src/main.tsx                        QueryClientProvider + RouterProvider
web/src/index.css                       tokens, @theme inline, dark block, base styles
web/src/router.tsx                      routes: / (Today), /progress, /nutrition, /labs, /settings
web/src/App.tsx                         Shell around <Outlet/>
web/src/api/types.ts                    generated
web/src/api/client.ts                   api(), ApiError, readSse()
web/src/api/queries.ts                  keys, useToday, useThread, useMemory, useStatus, useSchema
web/src/components/Shell.tsx  Rail.tsx  Header.tsx
web/src/components/today/Strip.tsx  SessionCard.tsx  ReadinessCard.tsx  FuelCard.tsx  WeekCard.tsx  Card.tsx
web/src/components/chat/Chat.tsx  Message.tsx  Activity.tsx  Composer.tsx  useTurnStream.ts
web/src/components/gate/Gate.tsx  ProposalCard.tsx  ChangeRow.tsx  SchemaForm.tsx  YamlEditor.tsx  schemaUtils.ts
web/src/components/jobs/JobButton.tsx  useJobStream.ts
web/src/components/settings/MemoryTable.tsx  ResetButton.tsx  Readiness.tsx
web/src/pages/Today.tsx  Settings.tsx  Placeholder.tsx
web/src/lib/format.ts                   dates, hours, kcal
web/tests/setup.ts                      jest-dom matchers
web/tests/fixtures.ts                   TodayView, ThreadView, schema fixtures
web/tests/sse.test.ts  shell.test.tsx  strip.test.tsx  turnStream.test.tsx  schemaForm.test.tsx  jobs.test.tsx
web/tests/e2e/smoke.spec.ts
README.md                               modify: Run lines, Layout, Status
docs/superpowers/specs/2026-09-14-tri-web-design.md   modify: Status line
```

---

### Task 1: Scaffold `web/` with Vite, React 19, Tailwind 4, Vitest

**Files:**
- Create: everything under `web/` listed above except `src/api/*`, components, pages (Tasks 2+); `web/tests/setup.ts`; `web/tests/app.test.tsx`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `npm --prefix web run dev|build|preview|lint|test`; tokens in `src/index.css`; `src/main.tsx` mounting `<App/>` inside `QueryClientProvider`.

- [ ] **Step 1: Scaffold and install**

From the worktree root:

```bash
npm create vite@latest web -- --template react-ts
cd web
npm install
npm install @tanstack/react-query react-router
npm install -D tailwindcss @tailwindcss/vite vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test openapi-typescript
cd ..
printf 'web/node_modules/\n' >> .gitignore
```

- [ ] **Step 2: Configure Vite, Vitest and the scripts**

`web/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8321", changeOrigin: false } },
  },
  build: { outDir: "dist" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/e2e/**"],
  },
});
```

`web/package.json` scripts (replace the template's):

```json
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview --port 4173",
  "lint": "eslint .",
  "test": "vitest run",
  "test:e2e": "playwright test",
  "types": "cd .. && uv run tri-web openapi > web/openapi.json && cd web && openapi-typescript openapi.json -o src/api/types.ts"
}
```

`web/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Add `"types": ["vitest/globals", "@testing-library/jest-dom"]` to `compilerOptions` in `web/tsconfig.app.json` and `"tests"` to its `include` array. Add `playwright.config.ts` and `tests/e2e` to the ESLint `ignores` if the template's config complains about them (Task 9 adds the Playwright config).

- [ ] **Step 3: Tokens and base styles**

`web/src/index.css` (replaces the template's):

```css
@import "tailwindcss";

:root {
  --surface: #f7f6f2;
  --surface-2: #ffffff;
  --ink: #1b1b1f;
  --ink-2: #5d5f66;
  --line: #e2e0d8;
  --accent: #1f6f5f;
  --planning: #3552a8;
  --nutrition: #b3551d;
  --warn: #9a6b00;
  --danger: #b3261e;
}

@media (prefers-color-scheme: dark) {
  :root {
    --surface: #131417;
    --surface-2: #1d1f24;
    --ink: #ececec;
    --ink-2: #a3a6ad;
    --line: #2c2f36;
    --accent: #4fb39c;
    --planning: #8ea3ea;
    --nutrition: #e9915a;
    --warn: #e0b449;
    --danger: #ef6a63;
  }
}

@theme inline {
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-ink: var(--ink);
  --color-ink-2: var(--ink-2);
  --color-line: var(--line);
  --color-accent: var(--accent);
  --color-planning: var(--planning);
  --color-nutrition: var(--nutrition);
  --color-warn: var(--warn);
  --color-danger: var(--danger);
}

html, body, #root { height: 100%; }
body { @apply bg-surface text-ink antialiased; }
```

- [ ] **Step 4: `main.tsx`, `App.tsx`, and a first test**

`web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { router } from "./router";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1, staleTime: 5_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
```

`web/src/router.tsx` (Task 3 fills the pages; for now a single route):

```tsx
import { createBrowserRouter } from "react-router";
import App from "./App";

export const router = createBrowserRouter([{ path: "/", element: <App /> }]);
```

`web/src/App.tsx`:

```tsx
export default function App() {
  return <main className="p-4">tri-web</main>;
}
```

`web/tests/app.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import App from "../src/App";

test("the app mounts", () => {
  render(<App />);
  expect(screen.getByText("tri-web")).toBeInTheDocument();
});
```

Delete the template's `src/App.css`, `src/assets/react.svg`, `public/vite.svg` references; set `<title>tri-web</title>` in `index.html`.

- [ ] **Step 5: Run lint, test, build**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: lint clean, `1 passed`, `dist/index.html` and `dist/assets/*` written.

- [ ] **Step 6: Commit**

```bash
git add .gitignore web
git commit -m "feat(web): scaffold the React app (Vite, Tailwind 4, TanStack Query, Vitest) with the design tokens"
```

---

### Task 2: API client, generated types, SSE reader, query hooks

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/queries.ts`, `web/src/api/types.ts` (generated), `web/openapi.json` (generated), `web/src/lib/format.ts`
- Test: `web/tests/sse.test.ts`

**Interfaces:**
- Produces:

```ts
// client.ts
export class ApiError extends Error { status: number; body: unknown }
export async function api<T>(path: string, init?: RequestInit): Promise<T>        // JSON in, JSON out; throws ApiError
export async function apiNoContent(path: string, init?: RequestInit): Promise<void>
export type SseEvent = { name: string; data: unknown }
export async function readSse(res: Response, onEvent: (ev: SseEvent) => void): Promise<void>  // resolves at end of body
export async function postStream(path: string, body: unknown): Promise<Response>   // throws ApiError on non-2xx
// types.ts (generated)
export type ThreadView = components["schemas"]["ThreadView"]  // etc., re-exported from queries.ts as aliases
// queries.ts
export const keys = { today: ["today"], thread: ["thread"], memory: ["memory"], status: ["status"], schema: ["schema"] } as const
export function useToday(), useThread(), useMemory(), useStatus(), useSchema()
export type { TodayView, ThreadView, UiMessage, ReviewPayload, MemoryOut, StatusOut, SchemaOut, Validated, ValidationItem, JobOut }
```

- [ ] **Step 1: Write the failing test**

`web/tests/sse.test.ts`:

```ts
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
      controller.error(new Error("network"));
    },
  });
  const out: SseEvent[] = [];
  await expect(readSse(new Response(stream), (ev) => out.push(ev))).rejects.toThrow("network");
  expect(out).toEqual([{ name: "token", data: { t: 1 } }]);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: `Failed to resolve import "../src/api/client"`.

- [ ] **Step 3: Write `client.ts`**

```ts
export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function bodyOf(res: Response): Promise<unknown> {
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
```

- [ ] **Step 4: Generate the types**

Run: `npm --prefix web run types` (needs the server package installed in the worktree: `uv sync`). Commit `web/openapi.json` and `web/src/api/types.ts`. Check the generated file has `components["schemas"]["ThreadView"]`.

- [ ] **Step 5: Write `queries.ts` and `format.ts`**

`web/src/api/queries.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { components } from "./types";

type S = components["schemas"];
export type TodayView = S["TodayView"];
export type ThreadView = S["ThreadView"];
export type UiMessage = S["UiMessage"];
export type ReviewPayload = S["ReviewPayload"];
export type MemoryOut = S["MemoryOut"];
export type MemoryEntry = S["MemoryEntry"];
export type StatusOut = S["StatusOut"];
export type SchemaOut = S["SchemaOut"];
export type Validated = S["Validated"];
export type ValidationItem = S["ValidationItem"];
export type JobOut = S["JobOut"];

export const keys = {
  today: ["today"] as const,
  thread: ["thread"] as const,
  memory: ["memory"] as const,
  status: ["status"] as const,
  schema: ["schema"] as const,
};

export const useToday = () => useQuery({ queryKey: keys.today, queryFn: () => api<TodayView>("/api/today") });
export const useThread = (refetchInterval?: number | false) =>
  useQuery({ queryKey: keys.thread, queryFn: () => api<ThreadView>("/api/coach/thread"), refetchInterval });
export const useMemory = () => useQuery({ queryKey: keys.memory, queryFn: () => api<MemoryOut>("/api/coach/memory") });
export const useStatus = () => useQuery({ queryKey: keys.status, queryFn: () => api<StatusOut>("/api/system/status") });
export const useSchema = () =>
  useQuery({ queryKey: keys.schema, queryFn: () => api<SchemaOut>("/api/coach/review/schema"), staleTime: Infinity });
```

`web/src/lib/format.ts`:

```ts
export const hours = (h: number | null | undefined) => (h == null ? "–" : `${h.toFixed(1)} h`);
export const secsAsHours = (s: number | null | undefined) => (s == null ? "–" : `${(s / 3600).toFixed(1)} h`);
export const n = (v: number | null | undefined, digits = 0) => (v == null ? "–" : v.toFixed(digits));
export const kcal = (v: number | null | undefined) => (v == null ? "–" : `${v.toLocaleString()} kcal`);
export const day = (iso: string | null | undefined) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "–";
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never";
```

- [ ] **Step 6: Run the tests, lint, build**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: `5 passed` (4 SSE + the app test), lint clean, build ok. If `tsc -b` objects to the generated file's style, add `src/api/types.ts` to ESLint `ignores` (never to tsconfig excludes).

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat(web): fetch client, SSE reader, generated OpenAPI types, query hooks"
```

---

### Task 3: The shell: rail, header, routes, placeholder pages

**Files:**
- Create: `web/src/components/Shell.tsx`, `Rail.tsx`, `Header.tsx`, `web/src/pages/Today.tsx` (placeholder body for now), `Settings.tsx` (placeholder body), `Placeholder.tsx`
- Modify: `web/src/router.tsx`, `web/src/App.tsx`
- Test: `web/tests/shell.test.tsx`, `web/tests/fixtures.ts`

**Interfaces:**
- Produces: `<Shell/>` renders `<Rail/>`, `<Header/>` and `<Outlet/>`; `Header` props `{ today?: TodayView; slots?: ReactNode }` (the job buttons arrive in Task 7 through `slots`); routes `/`, `/progress`, `/nutrition`, `/labs`, `/settings`. `tests/fixtures.ts` exports `todayFull(): TodayView`, `todayEmpty(): TodayView`, `threadEmpty(): ThreadView`, `paused(): ReviewPayload`, `schema(): SchemaOut`, and `renderWith(ui, {route?})` that wraps in a `QueryClientProvider` and a `MemoryRouter`.

- [ ] **Step 1: Write the fixtures and the failing test**

`web/tests/fixtures.ts`:

```ts
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { render } from "@testing-library/react";
import type { ReviewPayload, SchemaOut, ThreadView, TodayView } from "../src/api/queries";

export function todayEmpty(): TodayView {
  return {
    header: { today: "2026-09-16", phase: "intake", goal: null, week: { start: "2026-09-14", number: null, of: null }, last_sync: [] },
    session: null,
    readiness: null,
    fuel: { target: null, targets_through: null },
    week: null,
    labs: null,
    labs_enabled: false,
    labs_missing: false,
    pending: null,
  };
}

export function todayFull(): TodayView {
  return {
    ...todayEmpty(),
    header: {
      today: "2026-09-16",
      phase: "active",
      goal: { goal_type: "olympic", event_name: "City Tri", event_date: "2026-11-01", days_to_go: 46 },
      week: { start: "2026-09-14", number: 1, of: 3 },
      last_sync: [{ source: "garmin", last_synced_date: "2026-09-16", last_run_at: "2026-09-16T06:10:00Z", status: "ok", error: null }],
    },
    session: {
      workouts: [{ tp_workout_id: "w1", sport: "run", title: "Tempo", completed: false, planned_duration_sec: 3600, planned_tss: 60, actual_duration_sec: null, actual_tss: null }],
      fuel: { id: 1, kind: "session", tp_workout_id: "w1", payload: { carbs_g_per_h: 60, pre: "toast" }, violations: [], written: false },
    },
    readiness: { date: "2026-09-16", is_today: true, sleep_score: 81, sleep_hours: 7.5, hrv: 62, resting_hr: 48, body_battery: 92, training_readiness: 77, ctl: 45.2, atl: 50.1, tsb: -4.9 },
    fuel: { target: { day_type: "moderate", total_kcal: 2900, carbs_g: 380, protein_g: 150, fat_g: 80, fluid_baseline_ml: 2500, written_to_garmin: false }, targets_through: "2026-09-20" },
    week: { phase: "build", target_hours: 6, target_tss: 300, actual_hours: 2.5, actual_tss: 120, sessions: [{ sport: "run", planned: 2, completed: 1 }, { sport: "bike", planned: 2, completed: 1 }] },
  };
}

export function threadEmpty(): ThreadView {
  return { messages: [], paused: null, held: null, stuck: false, running: null };
}

export function paused(): ReviewPayload {
  return {
    narration: "Knee: move Wednesday.",
    proposals: [
      {
        id: "p1",
        domain: "planning",
        summary: "move it",
        changes: [{ op: "move", workout_date: null, tp_workout_id: "w1", workout: null, new_date: "2026-09-18", payload: null, reason: "knee", athlete_requested: false }],
        violations: [],
        question: null,
        overrides: null,
      },
    ],
  };
}

export function schema(): SchemaOut {
  return {
    proposal: { type: "object", properties: { id: { type: "string" }, domain: { enum: ["planning", "nutrition"], type: "string" }, summary: { type: "string" } } },
    planning_change: {
      $defs: {
        PlannedSession: {
          type: "object",
          properties: {
            date: { type: "string", format: "date" },
            sport: { enum: ["swim", "bike", "run", "brick", "strength", "rest"], type: "string" },
            title: { type: "string" },
            description: { type: "string" },
            duration_minutes: { type: "integer", minimum: 0 },
            tss_planned: { type: "number", minimum: 0 },
            intensity: { enum: ["recovery", "endurance", "tempo", "threshold", "vo2", "race"], type: "string" },
            structure: { anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }], default: null },
          },
          required: ["date", "sport", "title", "description", "duration_minutes", "tss_planned", "intensity"],
        },
      },
      type: "object",
      properties: {
        op: { enum: ["create", "update", "delete", "move", "apply_plan", "create_event"], type: "string" },
        workout_date: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], default: null },
        tp_workout_id: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
        workout: { anyOf: [{ $ref: "#/$defs/PlannedSession" }, { type: "null" }], default: null },
        new_date: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], default: null },
        payload: { anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }], default: null },
        reason: { type: "string" },
        athlete_requested: { type: "boolean", default: false },
      },
      required: ["op", "reason"],
    },
    nutrition_change: {
      type: "object",
      properties: {
        op: { enum: ["set_day_targets", "set_session_note", "set_race_note"], type: "string" },
        target_key: { type: "string" },
        day: { type: "string", format: "date" },
        payload: { type: "object", additionalProperties: true },
        reason: { type: "string" },
      },
      required: ["op", "target_key", "day", "payload", "reason"],
    },
  };
}

export function renderWith(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
```

(Rename the file `fixtures.tsx` since it holds JSX.)

`web/tests/shell.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { renderWith, todayFull } from "./fixtures";
import Shell from "../src/components/Shell";
import Header from "../src/components/Header";
import Placeholder from "../src/pages/Placeholder";

function tree() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<div>today body</div>} />
        <Route path="/progress" element={<Placeholder name="Progress" subProject={2} />} />
        <Route path="/settings" element={<div>settings body</div>} />
      </Route>
    </Routes>
  );
}

test("the rail links the five sections and marks the current one", () => {
  renderWith(tree(), { route: "/progress" });
  for (const name of ["Today", "Progress", "Nutrition", "Labs", "Settings"]) {
    expect(screen.getByRole("link", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "Progress" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByText(/arrives in sub-project 2/)).toBeInTheDocument();
});

test("the header shows date, phase and week, countdown, last sync and the pending badge", () => {
  const today = { ...todayFull(), pending: { narration: "n", proposals: [] } };
  renderWith(<Header today={today} />);
  expect(screen.getByText(/Wed, Sep 16/)).toBeInTheDocument();
  expect(screen.getByText(/active · week 1 of 3/)).toBeInTheDocument();
  expect(screen.getByText(/46 days to City Tri/)).toBeInTheDocument();
  expect(screen.getByText(/garmin/)).toBeInTheDocument();
  expect(screen.getByText("1 review pending")).toBeInTheDocument();
});

test("the header without a plan says so and shows no badge", () => {
  renderWith(<Header today={undefined} />);
  expect(screen.queryByText(/review pending/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: unresolved imports for `Shell`, `Header`, `Placeholder`.

- [ ] **Step 3: Write the shell**

`web/src/components/Rail.tsx`:

```tsx
import { NavLink } from "react-router";

const items = [
  { to: "/", label: "Today" },
  { to: "/progress", label: "Progress" },
  { to: "/nutrition", label: "Nutrition" },
  { to: "/labs", label: "Labs" },
  { to: "/settings", label: "Settings" },
];

export default function Rail() {
  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-10 flex justify-around border-t border-line bg-surface-2 md:static md:h-full md:w-44 md:flex-col md:justify-start md:gap-1 md:border-r md:border-t-0 md:p-3"
    >
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) =>
            `rounded-md px-3 py-2 text-sm ${isActive ? "bg-accent/15 font-medium text-accent" : "text-ink-2 hover:text-ink"}`
          }
        >
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

`web/src/components/Header.tsx`:

```tsx
import type { ReactNode } from "react";
import type { TodayView } from "../api/queries";
import { day, when } from "../lib/format";

export default function Header({ today, slots }: { today?: TodayView; slots?: ReactNode }) {
  const h = today?.header;
  const week = h?.week.number != null ? `${h.phase} · week ${h.week.number} of ${h.week.of}` : (h?.phase ?? "");
  const goal = h?.goal;
  const pendingCount = today?.pending ? 1 : 0;
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface-2 px-4 py-3">
      <div className="text-base font-semibold">{h ? day(h.today) : "tri-web"}</div>
      {week && <div className="text-sm text-ink-2">{week}</div>}
      {goal?.event_date && goal.days_to_go != null && (
        <div className="text-sm text-ink-2">
          {goal.days_to_go} days to {goal.event_name ?? "race day"}
        </div>
      )}
      {h?.last_sync.map((s) => (
        <div key={s.source} className={`text-xs ${s.status === "ok" ? "text-ink-2" : "text-warn"}`} title={s.error ?? ""}>
          {s.source} {when(s.last_run_at)}
        </div>
      ))}
      <div className="ml-auto flex items-center gap-2">
        {slots}
        {pendingCount > 0 && (
          <span className="rounded-full bg-warn/15 px-2 py-0.5 text-xs font-medium text-warn">{pendingCount} review pending</span>
        )}
      </div>
    </header>
  );
}
```

`web/src/components/Shell.tsx`:

```tsx
import { Outlet } from "react-router";
import Rail from "./Rail";

export default function Shell() {
  return (
    <div className="flex h-full flex-col md:flex-row">
      <Rail />
      <div className="flex min-h-0 flex-1 flex-col pb-14 md:pb-0">
        <Outlet />
      </div>
    </div>
  );
}
```

`web/src/pages/Placeholder.tsx`:

```tsx
export default function Placeholder({ name, subProject }: { name: string; subProject: 2 | 3 | 4 }) {
  const spec = { 2: "tri-web progress", 3: "tri-web nutrition", 4: "tri-web labs" }[subProject];
  return (
    <section className="p-6">
      <h1 className="text-lg font-semibold">{name}</h1>
      <p className="mt-2 text-ink-2">
        {name} arrives in sub-project {subProject} ({spec}).
      </p>
    </section>
  );
}
```

`web/src/pages/Today.tsx` and `Settings.tsx` for now:

```tsx
import Header from "../components/Header";
import { useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  return (
    <>
      <Header today={today.data} />
      <section className="p-4">Today (Task 4)</section>
    </>
  );
}
```

```tsx
export default function Settings() {
  return <section className="p-6">Settings (Task 8)</section>;
}
```

`web/src/router.tsx`:

```tsx
import { createBrowserRouter } from "react-router";
import Shell from "./components/Shell";
import Today from "./pages/Today";
import Settings from "./pages/Settings";
import Placeholder from "./pages/Placeholder";

export const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Today /> },
      { path: "/progress", element: <Placeholder name="Progress" subProject={2} /> },
      { path: "/nutrition", element: <Placeholder name="Nutrition" subProject={3} /> },
      { path: "/labs", element: <Placeholder name="Labs" subProject={4} /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);
```

Delete `App.tsx` and `tests/app.test.tsx` (the router mounts `Shell` directly).

- [ ] **Step 4: Run the tests, lint, build**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: shell tests pass (3), SSE tests pass (4). Then `npm --prefix web run dev` with `uv run tri-web serve --no-live` in another shell: the header shows today's date and the rail switches pages; at 400 px the rail is a bottom bar.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(web): shell with rail, header and routes; placeholder pages name their sub-project"
```

---

### Task 4: The Today strip

**Files:**
- Create: `web/src/components/today/Card.tsx`, `Strip.tsx`, `SessionCard.tsx`, `ReadinessCard.tsx`, `FuelCard.tsx`, `WeekCard.tsx`
- Modify: `web/src/pages/Today.tsx`
- Test: `web/tests/strip.test.tsx`

**Interfaces:**
- Produces: `<Strip today={TodayView | undefined} />`; each card takes its slice and renders the null sentence.

- [ ] **Step 1: Write the failing test**

`web/tests/strip.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import Strip from "../src/components/today/Strip";
import { renderWith, todayEmpty, todayFull } from "./fixtures";

test("every card has a sentence for its null state", () => {
  renderWith(<Strip today={todayEmpty()} />);
  expect(screen.getByText("No session planned")).toBeInTheDocument();
  expect(screen.getByText("No Garmin data yet, sync first")).toBeInTheDocument();
  expect(screen.getByText("No targets yet, ask the coach")).toBeInTheDocument();
  expect(screen.getByText("No plan; ask the coach to build one")).toBeInTheDocument();
});

test("the cards show today's numbers", () => {
  renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("Tempo")).toBeInTheDocument();
  expect(screen.getByText(/run · 1\.0 h · 60 TSS/)).toBeInTheDocument();
  expect(screen.getByText(/60 g\/h/)).toBeInTheDocument();
  expect(screen.getByText("81")).toBeInTheDocument(); // sleep score
  expect(screen.getByText(/7\.5 h/)).toBeInTheDocument();
  expect(screen.getByText(/45\.2 \/ 50\.1 \/ -4\.9/)).toBeInTheDocument();
  expect(screen.getByText(/2,900 kcal/)).toBeInTheDocument();
  expect(screen.getByText(/380 C · 150 P · 80 F/)).toBeInTheDocument();
  expect(screen.getByText(/2\.5 h of 6\.0 h/)).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  expect(screen.getByText(/run 1\/2 · bike 1\/2/)).toBeInTheDocument();
});

test("readiness from an earlier day says which day", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, is_today: false, date: "2026-09-14" };
  renderWith(<Strip today={t} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
});

test("the strip shows skeletons while loading", () => {
  renderWith(<Strip today={undefined} />);
  expect(screen.getAllByTestId("card-skeleton")).toHaveLength(4);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: unresolved import `Strip`.

- [ ] **Step 3: Write the cards**

`web/src/components/today/Card.tsx`:

```tsx
import type { ReactNode } from "react";

export function Card({ title, children, tone }: { title: string; children: ReactNode; tone?: "planning" | "nutrition" }) {
  const bar = tone === "planning" ? "border-l-planning" : tone === "nutrition" ? "border-l-nutrition" : "border-l-accent";
  return (
    <section className={`rounded-lg border border-line border-l-4 ${bar} bg-surface-2 p-3`}>
      <h2 className="text-xs font-medium uppercase tracking-wide text-ink-2">{title}</h2>
      <div className="mt-1 text-sm">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-ink-2">{children}</p>;
}

export function Skeleton() {
  return <div data-testid="card-skeleton" className="h-24 animate-pulse rounded-lg border border-line bg-surface-2" />;
}
```

`web/src/components/today/SessionCard.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { n, secsAsHours } from "../../lib/format";
import { Card, Empty } from "./Card";

export default function SessionCard({ session }: { session: TodayView["session"] }) {
  return (
    <Card title="Session" tone="planning">
      {!session ? (
        <Empty>No session planned</Empty>
      ) : (
        <ul className="space-y-1">
          {session.workouts.map((w) => (
            <li key={w.tp_workout_id}>
              <div className="font-medium">{w.title || w.sport}</div>
              <div className="text-ink-2">
                {w.sport} · {secsAsHours(w.completed ? w.actual_duration_sec : w.planned_duration_sec)} · {n(w.completed ? w.actual_tss : w.planned_tss)} TSS
                {w.completed ? " · done" : ""}
              </div>
            </li>
          ))}
          {session.fuel && (
            <li className="text-ink-2">
              fuel: {String(session.fuel.payload.carbs_g_per_h ?? "–")} g/h
              {session.fuel.payload.pre ? ` · pre: ${String(session.fuel.payload.pre)}` : ""}
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}
```

`web/src/components/today/ReadinessCard.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty } from "./Card";

export default function ReadinessCard({ readiness }: { readiness: TodayView["readiness"] }) {
  if (!readiness) {
    return (
      <Card title="Readiness">
        <Empty>No Garmin data yet, sync first</Empty>
      </Card>
    );
  }
  const r = readiness;
  return (
    <Card title={r.is_today ? "Readiness" : `Readiness from ${day(r.date)}`}>
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-semibold">{r.sleep_score ?? "–"}</span>
        <span className="text-ink-2">sleep · {n(r.sleep_hours, 1)} h</span>
      </div>
      <div className="text-ink-2">
        HRV {r.hrv ?? "–"} · RHR {r.resting_hr ?? "–"} · battery {r.body_battery ?? "–"} · readiness {r.training_readiness ?? "–"}
      </div>
      <div className="text-ink-2">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)}
      </div>
    </Card>
  );
}
```

`web/src/components/today/FuelCard.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { day, kcal } from "../../lib/format";
import { Card, Empty } from "./Card";

export default function FuelCard({ fuel }: { fuel: TodayView["fuel"] }) {
  const t = fuel.target;
  return (
    <Card title="Fuel" tone="nutrition">
      {!t ? (
        <Empty>No targets yet, ask the coach</Empty>
      ) : (
        <>
          <div className="text-2xl font-semibold">{kcal(t.total_kcal)}</div>
          <div className="text-ink-2">
            {t.day_type} · {t.carbs_g} C · {t.protein_g} P · {t.fat_g} F · {t.fluid_baseline_ml} ml
          </div>
          <div className="text-ink-2">targets through {day(fuel.targets_through)}{t.written_to_garmin ? " · on Garmin" : ""}</div>
        </>
      )}
    </Card>
  );
}
```

`web/src/components/today/WeekCard.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { hours, n } from "../../lib/format";
import { Card, Empty } from "./Card";

export default function WeekCard({ week }: { week: TodayView["week"] }) {
  if (!week) {
    return (
      <Card title="Week" tone="planning">
        <Empty>No plan; ask the coach to build one</Empty>
      </Card>
    );
  }
  const pct = week.target_hours ? Math.min(100, Math.round((week.actual_hours / week.target_hours) * 100)) : 0;
  return (
    <Card title={`Week · ${week.phase}`} tone="planning">
      <div>
        {hours(week.actual_hours)} of {hours(week.target_hours)} · {n(week.actual_tss)} of {n(week.target_tss)} TSS
      </div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="mt-1 h-1.5 w-full rounded bg-line">
        <div className="h-1.5 rounded bg-planning" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-ink-2">{week.sessions.map((s) => `${s.sport} ${s.completed}/${s.planned}`).join(" · ")}</div>
    </Card>
  );
}
```

`web/src/components/today/Strip.tsx`:

```tsx
import type { TodayView } from "../../api/queries";
import { Skeleton } from "./Card";
import SessionCard from "./SessionCard";
import ReadinessCard from "./ReadinessCard";
import FuelCard from "./FuelCard";
import WeekCard from "./WeekCard";

export default function Strip({ today }: { today: TodayView | undefined }) {
  return (
    <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
      {!today ? (
        <>
          <Skeleton /> <Skeleton /> <Skeleton /> <Skeleton />
        </>
      ) : (
        <>
          <SessionCard session={today.session} />
          <ReadinessCard readiness={today.readiness} />
          <FuelCard fuel={today.fuel} />
          <WeekCard week={today.week} />
        </>
      )}
    </div>
  );
}
```

Update `pages/Today.tsx` to render `<Strip today={today.data} />` under the header (the chat comes in Task 5).

- [ ] **Step 4: Run the tests, lint, build**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: strip tests pass (4). Visually check with the dev server: four cards, stacking to one column at 400 px.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(web): Today strip with session, readiness, fuel and week cards and their null sentences"
```

---

### Task 5: The chat: `useTurnStream`, messages, activity rows, composer

**Files:**
- Create: `web/src/components/chat/useTurnStream.ts`, `Chat.tsx`, `Message.tsx`, `Activity.tsx`, `Composer.tsx`
- Modify: `web/src/pages/Today.tsx`
- Test: `web/tests/turnStream.test.tsx`

**Interfaces:**
- Produces:

```ts
export type Bubble =
  | { id: string; role: "assistant" | "consult" | "report" | "error"; where: string; text: string }
  | { id: string; role: "activity"; where: string; name: string; args?: unknown; chars?: number; text: string };
export type TurnState = {
  status: "idle" | "streaming" | "busy";
  busyWith: string | null;          // the 409's running kind
  bubbles: Bubble[];
  interrupt: ReviewPayload | null;  // the latest interrupt event of the open stream
  error: string | null;             // the last error event; retry resends lastText
  lost: boolean;                    // stream ended without done
  lastText: string | null;
};
export function useTurnStream(): {
  state: TurnState;
  send: (text: string) => Promise<void>;
  resume: (decision: ReviewDecision) => Promise<void>;   // throws ApiError(422) on a rejected edit
  retry: () => Promise<void>;
};
export type ReviewDecision = { action: "approve" | "reject" | "edit"; note?: string | null; proposals?: unknown[] };
```

`Chat` props: `{ thread: ThreadView | undefined; stream: ReturnType<typeof useTurnStream>; gate: ReactNode }`. `Composer` props: `{ disabled: boolean; hint?: string; onSend(text): void }`.

- [ ] **Step 1: Write the failing test**

`web/tests/turnStream.test.tsx`:

```tsx
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
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
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
  let seen: string[] = [];
  const sending = act(() => result.current.send("how fit am I?"));
  await waitFor(() => expect(result.current.state.bubbles.length).toBeGreaterThan(0));
  seen = result.current.state.bubbles.map((b) => `${b.role}:${b.where}:${b.text}`);
  await sending;
  expect(seen).toContain("assistant:coach:Let me check.");
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
  await act(() => result.current.send("x"));
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: unresolved import `useTurnStream`.

- [ ] **Step 3: Write `useTurnStream.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, postStream, readSse } from "../../api/client";
import { keys, type ReviewPayload } from "../../api/queries";

export type Bubble =
  | { id: string; role: "assistant" | "consult" | "report" | "error"; where: string; text: string }
  | { id: string; role: "activity"; where: string; name: string; args?: unknown; chars?: number; text: string };

export type TurnState = {
  status: "idle" | "streaming" | "busy";
  busyWith: string | null;
  bubbles: Bubble[];
  interrupt: ReviewPayload | null;
  error: string | null;
  lost: boolean;
  lastText: string | null;
};

export type ReviewDecision = { action: "approve" | "reject" | "edit"; note?: string | null; proposals?: unknown[] };

const initial: TurnState = { status: "idle", busyWith: null, bubbles: [], interrupt: null, error: null, lost: false, lastText: null };

let seq = 0;
const nextId = () => `live-${++seq}`;

function applyEvent(bubbles: Bubble[], name: string, data: Record<string, unknown>): Bubble[] {
  const last = bubbles[bubbles.length - 1];
  switch (name) {
    case "token": {
      const where = String(data.where);
      const text = String(data.text);
      if (last && last.role === "assistant" && last.where === where) {
        return [...bubbles.slice(0, -1), { ...last, text: last.text + text }];
      }
      return [...bubbles, { id: nextId(), role: "assistant", where, text }];
    }
    case "tool_call":
      return [...bubbles, { id: nextId(), role: "activity", where: String(data.where), name: String(data.name), args: data.args, text: `→ ${String(data.name)}` }];
    case "tool_result":
      return [...bubbles, { id: nextId(), role: "activity", where: String(data.where), name: String(data.name), chars: Number(data.chars), text: `← ${String(data.name)}: ${String(data.chars)} chars` }];
    case "consult":
      return [...bubbles, { id: nextId(), role: "consult", where: String(data.domain), text: String(data.text) }];
    case "report":
      return [...bubbles, { id: nextId(), role: "report", where: "coach", text: String(data.text) }];
    default:
      return bubbles;
  }
}

export function useTurnStream() {
  const qc = useQueryClient();
  const [state, setState] = useState<TurnState>(initial);
  const alive = useRef(true);
  useEffect(() => () => void (alive.current = false), []);

  const run = useCallback(
    async (path: string, body: unknown, lastText: string | null) => {
      setState((s) => ({ ...s, status: "streaming", busyWith: null, bubbles: [], interrupt: null, error: null, lost: false, lastText }));
      let res: Response;
      try {
        res = await postStream(path, body);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const running = (e.body as { running?: string } | null)?.running ?? "run";
          setState((s) => ({ ...s, status: "busy", busyWith: running }));
          return;
        }
        setState((s) => ({ ...s, status: "idle", error: e instanceof Error ? e.message : String(e) }));
        throw e;
      }
      let done = false;
      try {
        await readSse(res, (ev) => {
          const data = (ev.data ?? {}) as Record<string, unknown>;
          if (ev.name === "interrupt") setState((s) => ({ ...s, interrupt: data as unknown as ReviewPayload }));
          else if (ev.name === "error") setState((s) => ({ ...s, error: String(data.message) }));
          else if (ev.name === "done") done = true;
          else setState((s) => ({ ...s, bubbles: applyEvent(s.bubbles, ev.name, data) }));
        });
      } catch {
        done = false;
      }
      await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.today })]);
      if (!alive.current) return;
      setState((s) => ({ ...s, status: "idle", bubbles: [], interrupt: null, lost: !done }));
    },
    [qc],
  );

  const send = useCallback((text: string) => run("/api/coach/turns", { text }, text), [run]);
  const resume = useCallback((decision: ReviewDecision) => run("/api/coach/review", decision, null), [run]);
  const retry = useCallback(async () => {
    if (state.lastText) await send(state.lastText);
  }, [send, state.lastText]);

  // busy: poll the thread every 2 s until running is null (the Chat reads busyWith to disable inputs)
  useEffect(() => {
    if (state.status !== "busy") return;
    const t = setInterval(async () => {
      await qc.invalidateQueries({ queryKey: keys.thread });
      const view = qc.getQueryData<{ running: string | null }>(keys.thread);
      if (view && view.running == null) {
        setState((s) => ({ ...s, status: "idle", busyWith: null }));
        await qc.invalidateQueries({ queryKey: keys.today });
      }
    }, 2000);
    return () => clearInterval(t);
  }, [state.status, qc]);

  return { state, send, resume, retry };
}
```

On a rejected edit (`422`), `postStream` throws an `ApiError` whose `body` carries `errors`; `run` rethrows it after setting `error`, and the gate (Task 6) catches it to show the errors inline; the gate also clears `error` by calling `send`/`resume` again or the user dismissing it.

- [ ] **Step 4: Write the components**

`web/src/components/chat/Activity.tsx`:

```tsx
import { useState } from "react";

export default function Activity({ text, args, where }: { text: string; args?: unknown; where: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 text-xs text-ink-2">
      <button type="button" onClick={() => setOpen((o) => !o)} className="font-mono hover:text-ink" aria-expanded={open}>
        {where !== "coach" ? `[${where}] ` : ""}{text}
      </button>
      {open && args !== undefined && (
        <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface p-2 text-[11px]">{JSON.stringify(args, null, 2)}</pre>
      )}
    </div>
  );
}
```

`web/src/components/chat/Message.tsx`:

```tsx
import type { ReactNode } from "react";

const tagColor: Record<string, string> = { planning: "text-planning", nutrition: "text-nutrition", analyst: "text-ink-2" };

export function Bubble({ role, where, children }: { role: "user" | "assistant" | "consult" | "report" | "error"; where?: string | null; children: ReactNode }) {
  if (role === "user") {
    return <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent/15 px-3 py-2 text-sm">{children}</div>;
  }
  if (role === "report") {
    return <pre className="my-1 whitespace-pre-wrap rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs text-ink-2">{children}</pre>;
  }
  if (role === "error") {
    return <div className="my-1 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{children}</div>;
  }
  const tag = where && where !== "coach" ? where : null;
  return (
    <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-surface-2 px-3 py-2 text-sm ${role === "consult" ? "border border-line font-mono text-xs" : ""}`}>
      {tag && <span className={`mr-2 text-[11px] font-medium uppercase ${tagColor[tag] ?? "text-ink-2"}`}>{tag}</span>}
      {children}
    </div>
  );
}
```

`web/src/components/chat/Composer.tsx`:

```tsx
import { useState, type FormEvent, type KeyboardEvent } from "react";

export default function Composer({ disabled, hint, onSend }: { disabled: boolean; hint?: string; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) submit();
  };
  return (
    <form onSubmit={submit} className="border-t border-line bg-surface-2 p-3">
      {hint && <p className="mb-2 text-xs text-warn">{hint}</p>}
      <div className="flex gap-2">
        <textarea
          aria-label="Message"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
          rows={2}
          placeholder="Ask your coach"
          className="flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent disabled:opacity-60"
        />
        <button type="submit" disabled={disabled || !text.trim()} className="rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">
          Send
        </button>
      </div>
    </form>
  );
}
```

`web/src/components/chat/Chat.tsx`:

```tsx
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
      <div ref={scroller} onScroll={onScroll} className="flex flex-1 flex-col gap-2 overflow-y-auto px-4 py-3">
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
      <Composer disabled={busy || state.status === "streaming"} hint={hint} onSend={(t) => void stream.send(t)} />
    </div>
  );
}
```

`web/src/pages/Today.tsx`:

```tsx
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
```

- [ ] **Step 5: Run the tests, lint, build; try it live**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: turn-stream tests pass (4). Live: `uv run tri-web serve` (with the key) and `npm --prefix web run dev`; ask a question; tokens stream into one bubble; after `done` the history refetches and the bubble is replaced by the checkpoint's message without a visible jump.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat(web): coach chat with a streaming turn hook, bubbles by where, activity rows, composer"
```

---

### Task 6: The review gate: proposal cards, `SchemaForm`, YAML editor, decisions

**Files:**
- Create: `web/src/components/gate/schemaUtils.ts`, `SchemaForm.tsx`, `YamlEditor.tsx`, `ChangeRow.tsx`, `ProposalCard.tsx`, `Gate.tsx`
- Modify: `web/src/pages/Today.tsx` (mount the gate)
- Test: `web/tests/schemaForm.test.tsx`

**Interfaces:**
- Produces:

```ts
// schemaUtils.ts
export type JsonSchema = Record<string, unknown>;
export type Field = { name: string; kind: "string" | "date" | "number" | "boolean" | "enum" | "object" | "dict" | "json"; enum?: string[]; required: boolean; nested?: Field[] };
export function fieldsOf(schema: JsonSchema, root: JsonSchema): Field[]          // properties -> Field[], $ref and anyOf-null resolved
export function changeSchema(all: SchemaOut, domain: "planning" | "nutrition"): JsonSchema
export function describeChange(domain: string, change: Record<string, unknown>): string   // one line, spec §6.5
// SchemaForm.tsx
export default function SchemaForm(props: { schema: SchemaOut; proposal: ProposalJson; errors: Record<string, string>; onChange(next: ProposalJson): void; onRemove(): void; canRemove: boolean })
// Gate.tsx
export default function Gate(props: { payload: ReviewPayload; mode: "paused" | "held"; onDecide(d: ReviewDecision): Promise<void>; disabled?: boolean })
export type ProposalJson = ReviewPayload["proposals"][number]
```

- [ ] **Step 1: Write the failing test**

`web/tests/schemaForm.test.tsx`:

```tsx
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SchemaForm from "../src/components/gate/SchemaForm";
import { describeChange, fieldsOf } from "../src/components/gate/schemaUtils";
import { paused, renderWith, schema } from "./fixtures";

test("fieldsOf resolves refs, nullable anyOf, enums, dates and dicts", () => {
  const s = schema();
  const fields = fieldsOf(s.planning_change, s.planning_change);
  const by = Object.fromEntries(fields.map((f) => [f.name, f]));
  expect(by.op.kind).toBe("enum");
  expect(by.op.enum).toContain("move");
  expect(by.new_date.kind).toBe("date");
  expect(by.new_date.required).toBe(false);
  expect(by.workout.kind).toBe("object");
  expect(by.workout.nested?.map((f) => f.name)).toContain("duration_minutes");
  expect(by.workout.nested?.find((f) => f.name === "duration_minutes")?.kind).toBe("number");
  expect(by.payload.kind).toBe("dict");
  expect(by.athlete_requested.kind).toBe("boolean");
  expect(by.reason.required).toBe(true);
});

test("describeChange gives one line per op", () => {
  expect(describeChange("planning", { op: "move", tp_workout_id: "w1", new_date: "2026-09-18" })).toBe("move w1 to Fri, Sep 18");
  expect(
    describeChange("planning", { op: "create", workout_date: "2026-09-19", workout: { sport: "run", duration_minutes: 60, description: "easy" } }),
  ).toBe("create Sat, Sep 19: run 60 min, easy");
  expect(describeChange("nutrition", { op: "set_day_targets", day: "2026-09-14", target_key: "2026-09-14", payload: { calorie_goal: 2800 } })).toBe(
    "set_day_targets Mon, Sep 14: calorie_goal=2800",
  );
});

test("the form renders each field type, edits a date, removes a change, emits JSON", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWith(<SchemaForm schema={schema()} proposal={paused().proposals[0]} errors={{}} onChange={onChange} onRemove={() => {}} canRemove />);
  expect(screen.getByLabelText("summary")).toHaveValue("move it");
  expect(screen.getByText("p1")).toBeInTheDocument(); // id is read-only text
  const op = screen.getByLabelText("op") as HTMLSelectElement;
  expect(op.tagName).toBe("SELECT");
  expect(op.value).toBe("move");
  const date = screen.getByLabelText("new_date") as HTMLInputElement;
  expect(date.type).toBe("date");
  fireEvent.change(date, { target: { value: "2026-09-19" } });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ changes: [expect.objectContaining({ new_date: "2026-09-19" })] }));
  expect(screen.getByLabelText("athlete_requested")).toHaveAttribute("type", "checkbox");
  await user.click(screen.getByRole("button", { name: "remove change 1" }));
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ changes: [] }));
});

test("errors show under their field by loc path", () => {
  renderWith(
    <SchemaForm schema={schema()} proposal={paused().proposals[0]} errors={{ "changes.0.new_date": "bad date" }} onChange={() => {}} onRemove={() => {}} canRemove={false} />,
  );
  expect(screen.getByText("bad date")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "remove proposal" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: unresolved imports.

- [ ] **Step 3: Write `schemaUtils.ts`**

```ts
import type { ReviewPayload, SchemaOut } from "../../api/queries";
import { day } from "../../lib/format";

export type JsonSchema = Record<string, unknown>;
export type FieldKind = "string" | "date" | "number" | "boolean" | "enum" | "object" | "dict" | "json";
export type Field = { name: string; kind: FieldKind; enum?: string[]; required: boolean; nested?: Field[] };
export type ProposalJson = ReviewPayload["proposals"][number];

function resolve(s: JsonSchema, root: JsonSchema): JsonSchema {
  const ref = s.$ref as string | undefined;
  if (ref?.startsWith("#/$defs/")) {
    const defs = (root.$defs ?? {}) as Record<string, JsonSchema>;
    return defs[ref.slice("#/$defs/".length)] ?? {};
  }
  const anyOf = s.anyOf as JsonSchema[] | undefined;
  if (anyOf) {
    const nonNull = anyOf.filter((x) => x.type !== "null");
    if (nonNull.length === 1) return resolve(nonNull[0], root);
  }
  return s;
}

function kindOf(s: JsonSchema): FieldKind {
  if (Array.isArray(s.enum)) return "enum";
  const t = s.type;
  if (t === "string") return s.format === "date" ? "date" : "string";
  if (t === "integer" || t === "number") return "number";
  if (t === "boolean") return "boolean";
  if (t === "object") return s.properties ? "object" : "dict";
  return "json";
}

export function fieldsOf(schema: JsonSchema, root: JsonSchema): Field[] {
  const props = (schema.properties ?? {}) as Record<string, JsonSchema>;
  const required = new Set((schema.required ?? []) as string[]);
  return Object.entries(props).map(([name, raw]) => {
    const s = resolve(raw, root);
    const kind = kindOf(s);
    const nullable = Array.isArray(raw.anyOf) && (raw.anyOf as JsonSchema[]).some((x) => x.type === "null");
    return {
      name,
      kind,
      enum: kind === "enum" ? (s.enum as string[]) : undefined,
      required: required.has(name) && !nullable,
      nested: kind === "object" ? fieldsOf(s, root) : undefined,
    };
  });
}

export function changeSchema(all: SchemaOut, domain: "planning" | "nutrition"): JsonSchema {
  return (domain === "planning" ? all.planning_change : all.nutrition_change) as JsonSchema;
}

export function describeChange(domain: string, c: Record<string, unknown>): string {
  const op = String(c.op);
  if (domain === "planning") {
    const w = (c.workout ?? null) as Record<string, unknown> | null;
    const session = w ? `${String(w.sport)} ${String(w.duration_minutes)} min${w.description ? `, ${String(w.description)}` : ""}` : "";
    if (op === "move") return `move ${String(c.tp_workout_id)} to ${day(c.new_date as string)}`;
    if (op === "delete") return `delete ${String(c.tp_workout_id)}`;
    if (op === "create") return `create ${day(c.workout_date as string)}: ${session}`;
    if (op === "update") return `update ${String(c.tp_workout_id)}${session ? `: ${session}` : ""}`;
    return op;
  }
  const payload = (c.payload ?? {}) as Record<string, unknown>;
  const pairs = Object.entries(payload).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(", ");
  return `${op} ${day(c.day as string)}${pairs ? `: ${pairs}` : ""}`;
}
```

- [ ] **Step 4: Write `SchemaForm.tsx`**

```tsx
import type { SchemaOut } from "../../api/queries";
import { changeSchema, fieldsOf, type Field, type JsonSchema, type ProposalJson } from "./schemaUtils";

type Errors = Record<string, string>;
type Obj = Record<string, unknown>;

function Err({ path, errors }: { path: string; errors: Errors }) {
  return errors[path] ? <p className="text-xs text-danger">{errors[path]}</p> : null;
}

function KeyValues({ id, value, onChange }: { id: string; value: Obj; onChange: (v: Obj) => void }) {
  const entries = Object.entries(value);
  const set = (i: number, k: string, v: string) => {
    const next = entries.map(([ek, ev], j) => (j === i ? [k, parse(v)] : [ek, ev]));
    onChange(Object.fromEntries(next));
  };
  const parse = (v: string): unknown => {
    try {
      return JSON.parse(v);
    } catch {
      return v;
    }
  };
  return (
    <div className="space-y-1" data-testid={id}>
      {entries.map(([k, v], i) => (
        <div key={i} className="flex gap-1">
          <input aria-label={`${id} key ${i + 1}`} value={k} onChange={(e) => set(i, e.target.value, JSON.stringify(v))} className="w-1/3 rounded border border-line bg-surface px-2 py-1 text-xs" />
          <input aria-label={`${id} value ${i + 1}`} defaultValue={typeof v === "string" ? v : JSON.stringify(v)} onBlur={(e) => set(i, k, e.target.value)} className="flex-1 rounded border border-line bg-surface px-2 py-1 text-xs" />
          <button type="button" aria-label={`remove ${id} ${k}`} onClick={() => onChange(Object.fromEntries(entries.filter((_, j) => j !== i)))} className="text-xs text-ink-2">×</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange({ ...value, "": "" })} className="text-xs text-accent">+ add key</button>
    </div>
  );
}

function FieldInput({ field, value, path, errors, onChange }: { field: Field; value: unknown; path: string; errors: Errors; onChange: (v: unknown) => void }) {
  const cls = "w-full rounded border border-line bg-surface px-2 py-1 text-sm";
  const label = <label htmlFor={path} className="block text-xs text-ink-2">{field.name}{field.required ? "" : " (optional)"}</label>;
  let input;
  switch (field.kind) {
    case "enum":
      input = (
        <select id={path} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className={cls}>
          {!field.required && <option value="">–</option>}
          {field.enum!.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
      break;
    case "date":
      input = <input id={path} type="date" value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)} className={cls} />;
      break;
    case "number":
      input = <input id={path} type="number" value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className={cls} />;
      break;
    case "boolean":
      input = <input id={path} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />;
      break;
    case "dict":
      input = <KeyValues id={path} value={(value ?? {}) as Obj} onChange={onChange} />;
      break;
    case "object": {
      const obj = (value ?? null) as Obj | null;
      input = obj ? (
        <div className="ml-3 border-l border-line pl-3">
          {field.nested!.map((f) => (
            <FieldInput key={f.name} field={f} value={obj[f.name]} path={`${path}.${f.name}`} errors={errors} onChange={(v) => onChange({ ...obj, [f.name]: v })} />
          ))}
        </div>
      ) : (
        <span className="text-xs text-ink-2">none</span>
      );
      break;
    }
    case "json":
      input = <input id={path} defaultValue={JSON.stringify(value ?? null)} onBlur={(e) => { try { onChange(JSON.parse(e.target.value)); } catch { /* keep */ } }} className={`${cls} font-mono text-xs`} />;
      break;
    default:
      input = <input id={path} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || (field.required ? "" : null))} className={cls} />;
  }
  return (
    <div className="mb-2">
      {label}
      {input}
      <Err path={path} errors={errors} />
    </div>
  );
}

type Props = { schema: SchemaOut; proposal: ProposalJson; errors: Errors; onChange: (p: ProposalJson) => void; onRemove: () => void; canRemove: boolean };

export default function SchemaForm({ schema, proposal, errors, onChange, onRemove, canRemove }: Props) {
  const domain = proposal.domain as "planning" | "nutrition";
  const cs = changeSchema(schema, domain);
  const fields = fieldsOf(cs, cs);
  const changes = (proposal.changes ?? []) as Obj[];
  const setChange = (i: number, next: Obj) => onChange({ ...proposal, changes: changes.map((c, j) => (j === i ? next : c)) });
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono">{proposal.id}</span>
        <span className={domain === "planning" ? "text-planning" : "text-nutrition"}>{domain}</span>
        {canRemove && (
          <button type="button" onClick={onRemove} aria-label="remove proposal" className="ml-auto text-xs text-danger">remove proposal</button>
        )}
      </div>
      <div className="mt-2">
        <label htmlFor={`${proposal.id}-summary`} className="block text-xs text-ink-2">summary</label>
        <input id={`${proposal.id}-summary`} aria-label="summary" value={proposal.summary} onChange={(e) => onChange({ ...proposal, summary: e.target.value })} className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm" />
        <Err path="summary" errors={errors} />
      </div>
      {proposal.question && <p className="mt-2 text-sm">{proposal.question}</p>}
      {changes.map((c, i) => (
        <fieldset key={i} className="mt-3 rounded border border-line p-2">
          <legend className="px-1 text-xs text-ink-2">change {i + 1}</legend>
          {fields.map((f) => (
            <FieldInput key={f.name} field={f} value={c[f.name]} path={`changes.${i}.${f.name}`} errors={errors} onChange={(v) => setChange(i, { ...c, [f.name]: v })} />
          ))}
          <button type="button" aria-label={`remove change ${i + 1}`} onClick={() => onChange({ ...proposal, changes: changes.filter((_, j) => j !== i) })} className="text-xs text-danger">
            remove change
          </button>
        </fieldset>
      ))}
      {domain === "nutrition" && (
        <div className="mt-3">
          <label className="block text-xs text-ink-2">overrides</label>
          <KeyValues id="overrides" value={(proposal.overrides ?? {}) as Obj} onChange={(v) => onChange({ ...proposal, overrides: Object.keys(v).length ? v : null })} />
          <Err path="overrides" errors={errors} />
        </div>
      )}
    </div>
  );
}
```

`aria-label="summary"` makes `getByLabelText("summary")` unambiguous; the field inputs are labelled through `htmlFor`/`id` with the loc path, so `getByLabelText("op")` finds the first change's select by its label text.

- [ ] **Step 5: Write `YamlEditor.tsx`, `ChangeRow.tsx`, `ProposalCard.tsx`, `Gate.tsx`**

`YamlEditor.tsx`:

```tsx
export default function YamlEditor({ value, onChange, errors }: { value: string; onChange: (v: string) => void; errors: string[] }) {
  return (
    <div>
      <textarea aria-label="YAML" value={value} onChange={(e) => onChange(e.target.value)} rows={16} spellCheck={false} className="w-full rounded border border-line bg-surface p-2 font-mono text-xs" />
      {errors.map((e, i) => <p key={i} className="text-xs text-danger">{e}</p>)}
    </div>
  );
}
```

`ChangeRow.tsx`:

```tsx
import { describeChange } from "./schemaUtils";

export default function ChangeRow({ domain, change }: { domain: string; change: Record<string, unknown> }) {
  return (
    <li className="text-sm">
      <span className="font-mono text-xs text-ink-2">{String(change.op)}</span> {describeChange(domain, change)}
      {change.reason ? <span className="text-ink-2"> — {String(change.reason)}</span> : null}
      {change.athlete_requested ? <span className="ml-1 rounded bg-accent/15 px-1 text-[10px] text-accent">athlete requested</span> : null}
    </li>
  );
}
```

`ProposalCard.tsx`:

```tsx
import type { ProposalJson } from "./schemaUtils";
import ChangeRow from "./ChangeRow";

export default function ProposalCard({ p }: { p: ProposalJson }) {
  const tone = p.domain === "planning" ? "text-planning" : "text-nutrition";
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-xs">{p.id}</span>
        <span className={`text-xs font-medium uppercase ${tone}`}>{p.domain}</span>
        <span>{p.summary}</span>
      </div>
      {p.question ? (
        <p className="mt-1 text-sm">asked instead of proposing: {p.question}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {(p.changes as Record<string, unknown>[]).map((c, i) => <ChangeRow key={i} domain={p.domain} change={c} />)}
        </ul>
      )}
      {p.violations.length > 0 && <p className="mt-1 text-xs text-danger">{p.violations.join("; ")}</p>}
      {p.overrides && <p className="mt-1 text-xs text-ink-2">profile overrides: {JSON.stringify(p.overrides)}</p>}
    </div>
  );
}
```

`Gate.tsx`:

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useSchema, type ReviewPayload, type Validated } from "../../api/queries";
import type { ReviewDecision } from "../chat/useTurnStream";
import ProposalCard from "./ProposalCard";
import SchemaForm from "./SchemaForm";
import YamlEditor from "./YamlEditor";
import type { ProposalJson } from "./schemaUtils";

type Props = { payload: ReviewPayload; mode: "paused" | "held"; onDecide: (d: ReviewDecision) => Promise<void>; disabled?: boolean };

function errorMap(v: Validated | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of v?.errors ?? []) out[e.loc.slice(1).join(".")] = e.msg;
  return out;
}

export default function Gate({ payload, mode, onDecide, disabled }: Props) {
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<"none" | "form" | "yaml">("none");
  const [drafts, setDrafts] = useState<ProposalJson[]>(payload.proposals);
  const [yaml, setYaml] = useState("");
  const [validated, setValidated] = useState<Validated | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const schema = useSchema();
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setDrafts(payload.proposals), [payload]);

  const validate = (body: { proposals: unknown[] } | { yaml: string }) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      try {
        setValidated(await api<Validated>("/api/coach/review/validate", { method: "POST", body: JSON.stringify(body) }));
      } catch (e) {
        setRefused(e instanceof Error ? e.message : String(e));
      }
    }, 300);
  };

  const startYaml = async () => {
    const { yaml: text } = await api<{ yaml: string }>("/api/coach/review/yaml");
    setYaml(text);
    setEditing("yaml");
    setValidated(null);
  };

  const sendEdited = async () => {
    const proposals = editing === "yaml" ? validated?.proposals : drafts;
    if (!proposals || proposals.length === 0) {
      setRefused("removing every proposal is not an edit; reject instead");
      return;
    }
    if (editing === "yaml" && !validated?.ok) return;
    try {
      await onDecide({ action: "edit", proposals });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        const body = e.body as { errors?: Validated["errors"]; detail?: string };
        setValidated({ ok: false, proposals: [], errors: body.errors ?? [] });
        setRefused(body.detail ?? "edit rejected");
      } else throw e;
    }
  };

  const errors = useMemo(() => errorMap(validated), [validated]);
  const perProposal = (i: number) =>
    Object.fromEntries(Object.entries(errors).filter(([k]) => k.startsWith(`${i}.`)).map(([k, v]) => [k.slice(`${i}.`.length), v]));
  const unmatched = (validated?.errors ?? []).filter((e) => typeof e.loc[0] !== "number").map((e) => `${e.loc.join(".")}: ${e.msg}`);

  return (
    <section aria-label="Review" className="my-2 rounded-lg border border-warn/50 bg-surface-2 p-3">
      <p className="text-sm">{payload.narration}</p>
      {mode === "held" && <p className="mt-1 text-xs text-warn">held from an earlier apply; ask the coach to re-propose it</p>}
      <div className="mt-2 space-y-2">
        {editing === "none" && payload.proposals.map((p) => <ProposalCard key={p.id} p={p} />)}
        {editing === "form" && schema.data &&
          drafts.map((p, i) => (
            <SchemaForm
              key={p.id}
              schema={schema.data}
              proposal={p}
              errors={perProposal(i)}
              canRemove={drafts.length > 1}
              onRemove={() => { const next = drafts.filter((_, j) => j !== i); setDrafts(next); validate({ proposals: next }); }}
              onChange={(next) => { const all = drafts.map((d, j) => (j === i ? next : d)); setDrafts(all); validate({ proposals: all }); }}
            />
          ))}
        {editing === "yaml" && <YamlEditor value={yaml} onChange={(v) => { setYaml(v); validate({ yaml: v }); }} errors={unmatched} />}
      </div>
      {refused && <p className="mt-2 text-xs text-danger">{refused}</p>}
      {mode === "paused" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {editing === "none" ? (
            <>
              <input aria-label="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="note (optional)" className="min-w-40 flex-1 rounded border border-line bg-surface px-2 py-1 text-sm" />
              <button type="button" disabled={disabled} onClick={() => void onDecide({ action: "approve" })} className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-white disabled:opacity-50">Approve</button>
              <button type="button" disabled={disabled} onClick={() => void onDecide({ action: "reject", note: note || null })} className="rounded-md border border-line px-3 py-1 text-sm disabled:opacity-50">Reject</button>
              <button type="button" disabled={disabled} onClick={() => { setEditing("form"); setValidated(null); setRefused(null); }} className="rounded-md border border-line px-3 py-1 text-sm disabled:opacity-50">Edit</button>
            </>
          ) : (
            <>
              <button type="button" disabled={disabled || (editing === "yaml" && !validated?.ok)} onClick={() => void sendEdited()} className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-white disabled:opacity-50">Send edited</button>
              {editing === "form" ? (
                <button type="button" onClick={() => void startYaml()} className="rounded-md border border-line px-3 py-1 text-sm">Edit as YAML</button>
              ) : (
                <button type="button" onClick={() => { setEditing("form"); setValidated(null); }} className="rounded-md border border-line px-3 py-1 text-sm">Edit as form</button>
              )}
              <button type="button" onClick={() => { setEditing("none"); setDrafts(payload.proposals); setValidated(null); setRefused(null); }} className="rounded-md border border-line px-3 py-1 text-sm">Cancel</button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
```

Mount it in `pages/Today.tsx`:

```tsx
  const paused = stream.state.interrupt ?? thread.data?.paused ?? null;
  const held = !paused ? (thread.data?.held ?? null) : null;
  const gate = paused ? (
    <Gate payload={paused} mode="paused" onDecide={stream.resume} disabled={stream.state.status !== "idle"} />
  ) : held ? (
    <Gate payload={held} mode="held" onDecide={stream.resume} />
  ) : null;
```

and pass `gate={gate}` to `<Chat/>` (import `Gate` from `../components/gate/Gate`).

- [ ] **Step 6: Run the tests, lint, build; try it live**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: schema-form tests pass (4). Live: trigger a change ("move my Wednesday run to Friday"), see the gate; Edit; change the date; watch the validate call return `ok`; Send edited; see `planning: applied 1` stream as a report; the strip refetches.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat(web): review gate with proposal cards, schema-generated edit form, YAML fallback and server validation"
```

---

### Task 7: Job buttons: Sync now, Weekly check-in, transcript

**Files:**
- Create: `web/src/components/jobs/useJobStream.ts`, `JobButton.tsx`
- Modify: `web/src/pages/Today.tsx` (pass the buttons through `Header`'s `slots`)
- Test: `web/tests/jobs.test.tsx`

**Interfaces:**
- Produces:

```ts
export type JobState = { id: string | null; status: "idle" | "running" | "done" | "failed" | "busy"; lastLine: string | null; lines: string[]; result: unknown; error: string | null; busyWith: string | null };
export function useJobStream(kind: "sync" | "checkin", body: unknown): { state: JobState; start(): Promise<void> }
// JobButton props: { kind: "sync" | "checkin"; label: string; body: unknown; onDone?(result: unknown): void }
```

- [ ] **Step 1: Write the failing test**

`web/tests/jobs.test.tsx`:

```tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useJobStream } from "../src/components/jobs/useJobStream";

function sse(frames: [string, unknown][]): Response {
  const body = frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}
const wrapper = (client: QueryClient) => ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: unresolved import `useJobStream`.

- [ ] **Step 3: Write `useJobStream.ts`**

```ts
import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, readSse } from "../../api/client";
import { keys } from "../../api/queries";

export type JobState = {
  id: string | null;
  status: "idle" | "running" | "done" | "failed" | "busy";
  lastLine: string | null;
  lines: string[];
  result: unknown;
  error: string | null;
  busyWith: string | null;
};

const initial: JobState = { id: null, status: "idle", lastLine: null, lines: [], result: null, error: null, busyWith: null };

export function useJobStream(kind: "sync" | "checkin", body: unknown) {
  const qc = useQueryClient();
  const [state, setState] = useState<JobState>(initial);
  const storageKey = `job:${kind}`;

  const follow = useCallback(
    async (id: string) => {
      setState((s) => ({ ...s, id, status: "running", lines: [], lastLine: null, error: null, result: null }));
      try {
        const res = await fetch(`/api/jobs/${id}/events`, { headers: { accept: "text/event-stream" } });
        if (!res.ok) throw new ApiError(res.status, await res.text());
        await readSse(res, (ev) => {
          const data = (ev.data ?? {}) as Record<string, unknown>;
          if (ev.name === "line") {
            const text = String(data.text);
            setState((s) => ({ ...s, lastLine: text.split("\n").filter(Boolean).pop() ?? text, lines: [...s.lines, text] }));
          } else if (ev.name === "done") setState((s) => ({ ...s, status: "done", result: data.result }));
          else if (ev.name === "error") setState((s) => ({ ...s, status: "failed", error: String(data.message) }));
        });
      } catch (e) {
        setState((s) => ({ ...s, status: "failed", error: e instanceof Error ? e.message : String(e) }));
      } finally {
        sessionStorage.removeItem(storageKey);
        await Promise.all([qc.invalidateQueries({ queryKey: keys.today }), qc.invalidateQueries({ queryKey: keys.thread })]);
      }
    },
    [qc, storageKey],
  );

  const start = useCallback(async () => {
    try {
      const { id } = await api<{ id: string }>(`/api/jobs/${kind}`, { method: "POST", body: JSON.stringify(body) });
      sessionStorage.setItem(storageKey, id);
      await follow(id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const running = (e.body as { running?: string } | null)?.running ?? "run";
        setState((s) => ({ ...s, status: "busy", busyWith: running }));
        return;
      }
      setState((s) => ({ ...s, status: "failed", error: e instanceof Error ? e.message : String(e) }));
    }
  }, [kind, body, follow, storageKey]);

  useEffect(() => {
    const id = sessionStorage.getItem(storageKey);
    if (id) void follow(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (state.status !== "done" && state.status !== "failed" && state.status !== "busy") return;
    const t = setTimeout(() => setState((s) => ({ ...s, status: "idle", busyWith: null })), 5000);
    return () => clearTimeout(t);
  }, [state.status]);

  return { state, start };
}
```

- [ ] **Step 4: Write `JobButton.tsx`**

```tsx
import { useEffect } from "react";
import { useJobStream } from "./useJobStream";

type Props = { kind: "sync" | "checkin"; label: string; body: unknown; onDone?: (result: unknown) => void };

function summary(kind: Props["kind"], result: unknown): string {
  const r = (result ?? {}) as Record<string, unknown>;
  if (kind === "sync") return r.ok ? "synced" : "sync had errors";
  if (r.paused) return "review pending, see the gate";
  if (r.no_plan) return "no plan and no profile yet";
  return r.code === 0 ? "clean week" : "check-in did not complete";
}

export default function JobButton({ kind, label, body, onDone }: Props) {
  const { state, start } = useJobStream(kind, body);
  useEffect(() => {
    if (state.status === "done") onDone?.(state.result);
  }, [state.status, state.result, onDone]);
  const text =
    state.status === "running" ? (state.lastLine ?? "starting…")
    : state.status === "done" ? summary(kind, state.result)
    : state.status === "failed" ? (state.error ?? "failed")
    : state.status === "busy" ? `a ${state.busyWith} is running`
    : label;
  const tone = state.status === "failed" ? "text-danger" : state.status === "busy" ? "text-warn" : "";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => void start()}
        disabled={state.status === "running"}
        className={`max-w-56 truncate rounded-md border border-line bg-surface px-3 py-1 text-xs ${tone} disabled:opacity-70`}
        title={text}
      >
        {text}
      </button>
      {state.lines.length > 0 && (
        <details className="absolute right-0 top-full z-10 mt-1 w-80 rounded-md border border-line bg-surface-2 p-2 text-xs shadow">
          <summary className="cursor-pointer text-ink-2">transcript</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap">{state.lines.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}
```

In `pages/Today.tsx` pass the buttons to the header:

```tsx
  const slots = (
    <>
      <JobButton kind="sync" label="Sync now" body={{}} />
      <JobButton kind="checkin" label="Weekly check-in" body={{ sync: true }} />
    </>
  );
  // ...
  <Header today={today.data} slots={slots} />
```

The `useJobStream` `finally` block already refetches `today` and `thread`, so a paused check-in shows the gate without more wiring. The `<details>` transcript is what spec §6.6 calls the expandable panel.

- [ ] **Step 5: Run the tests, lint, build; try it live**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: jobs tests pass (3). Live with `--no-live`: Sync now fails fast (no MCP servers) and the button turns red with the error; Weekly check-in over a real key runs and either says "clean week" or shows the gate.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat(web): Sync now and Weekly check-in buttons follow their job transcripts and re-attach after a reload"
```

---

### Task 8: Settings: memory table, reset, readiness

**Files:**
- Create: `web/src/components/settings/MemoryTable.tsx`, `ResetButton.tsx`, `Readiness.tsx`
- Modify: `web/src/pages/Settings.tsx`
- Test: `web/tests/settings.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/settings.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Settings from "../src/pages/Settings";
import { renderWith } from "./fixtures";

const memory = { entries: [{ id: "a1b2c3", kind: "injury", text: "left knee", created: "2026-09-01", until: "2026-09-30" }], active_ids: ["a1b2c3"] };
const status = { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: false }, thread: "coach", running: null };

function mockApi() {
  const f = vi.spyOn(globalThis, "fetch");
  f.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/coach/memory" && (!init || init.method === undefined)) return new Response(JSON.stringify(memory), { status: 200 });
    if (url.startsWith("/api/coach/memory/") && init?.method === "DELETE") return new Response(null, { status: 204 });
    if (url === "/api/system/status") return new Response(JSON.stringify(status), { status: 200 });
    if (url === "/api/coach/reset") return new Response(null, { status: 204 });
    return new Response("nope", { status: 404 });
  });
  return f;
}

afterEach(() => vi.restoreAllMocks());

test("memory rows, forget, readiness checks and the reset dialog", async () => {
  const f = mockApi();
  const user = userEvent.setup();
  renderWith(<Settings />);
  await screen.findByText("left knee");
  expect(screen.getByText("injury")).toBeInTheDocument();
  expect(screen.getByText("active")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "forget a1b2c3" }));
  await waitFor(() => expect(f).toHaveBeenCalledWith("/api/coach/memory/a1b2c3", expect.objectContaining({ method: "DELETE" })));
  expect(await screen.findByText(/store tables/)).toHaveClass("text-danger");
  expect(screen.getByText(/API key/)).toHaveClass("text-accent");
  expect(screen.getByText(/live tools: none/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reset conversation" }));
  await user.click(screen.getByLabelText("forget memory too"));
  await user.click(screen.getByRole("button", { name: "Confirm reset" }));
  await waitFor(() =>
    expect(f).toHaveBeenCalledWith("/api/coach/reset", expect.objectContaining({ method: "POST", body: JSON.stringify({ confirm: true, forget_memory: true }) })),
  );
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test`
Expected: the settings page renders the Task 3 placeholder; assertions fail.

- [ ] **Step 3: Write the components**

`MemoryTable.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiNoContent } from "../../api/client";
import { keys, useMemory } from "../../api/queries";
import { day } from "../../lib/format";

export default function MemoryTable() {
  const qc = useQueryClient();
  const memory = useMemory();
  const forget = useMutation({
    mutationFn: (id: string) => apiNoContent(`/api/coach/memory/${id}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.memory }),
  });
  const entries = memory.data?.entries ?? [];
  const active = new Set(memory.data?.active_ids ?? []);
  if (memory.isPending) return <p className="text-ink-2">loading…</p>;
  if (entries.length === 0) return <p className="text-ink-2">nothing remembered yet</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-ink-2">
        <tr><th className="py-1">kind</th><th>text</th><th>created</th><th>until</th><th></th><th></th></tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.id} className="border-t border-line">
            <td className="py-1 pr-2">{e.kind}</td>
            <td className="pr-2">{e.text}</td>
            <td className="pr-2 text-ink-2">{day(e.created)}</td>
            <td className="pr-2 text-ink-2">{e.until ? day(e.until) : "–"}</td>
            <td className="pr-2 text-xs">{active.has(e.id) ? <span className="text-accent">active</span> : <span className="text-ink-2">expired</span>}</td>
            <td><button type="button" aria-label={`forget ${e.id}`} onClick={() => forget.mutate(e.id)} className="text-xs text-danger">forget</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`ResetButton.tsx`:

```tsx
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiNoContent, ApiError } from "../../api/client";
import { keys } from "../../api/queries";

export default function ResetButton() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [forget, setForget] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const reset = async () => {
    try {
      await apiNoContent("/api/coach/reset", { method: "POST", body: JSON.stringify({ confirm: true, forget_memory: forget }) });
      setMsg(forget ? "conversation and memory cleared" : "conversation cleared");
      setOpen(false);
      await Promise.all([qc.invalidateQueries({ queryKey: keys.thread }), qc.invalidateQueries({ queryKey: keys.memory }), qc.invalidateQueries({ queryKey: keys.today })]);
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 409 ? `a ${(e.body as { running?: string }).running} is running` : String(e));
    }
  };
  return (
    <div>
      {!open ? (
        <button type="button" onClick={() => setOpen(true)} className="rounded-md border border-danger/50 px-3 py-1 text-sm text-danger">Reset conversation</button>
      ) : (
        <div role="dialog" aria-label="Reset" className="rounded-md border border-line bg-surface-2 p-3 text-sm">
          <p>Forget the coach conversation? Garmin, TrainingPeaks, the tables and the other agents are untouched.</p>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={forget} onChange={(e) => setForget(e.target.checked)} aria-label="forget memory too" />forget memory too</label>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => void reset()} className="rounded-md bg-danger px-3 py-1 text-white">Confirm reset</button>
            <button type="button" onClick={() => setOpen(false)} className="rounded-md border border-line px-3 py-1">Cancel</button>
          </div>
        </div>
      )}
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </div>
  );
}
```

`Readiness.tsx`:

```tsx
import { useStatus } from "../../api/queries";

export default function Readiness() {
  const status = useStatus();
  const s = status.data;
  if (!s) return <p className="text-ink-2">checking…</p>;
  const Check = ({ ok, label }: { ok: boolean; label: string }) => (
    <li className={ok ? "text-accent" : "text-danger"}>{ok ? "✓" : "✗"} {label}</li>
  );
  return (
    <div className="text-sm">
      <ul className="space-y-1">
        <Check ok={s.ready.api_key} label="API key" />
        <Check ok={s.ready.checkpointer} label="checkpoint tables" />
        <Check ok={s.ready.store} label="store tables" />
      </ul>
      <p className="mt-2 text-ink-2">
        thread {s.thread} · live {s.live ? "yes" : "no"} · live tools: {s.tools.length ? s.tools.join(", ") : "none"}
        {s.running ? ` · running: ${s.running}` : ""}
      </p>
    </div>
  );
}
```

`pages/Settings.tsx`:

```tsx
import MemoryTable from "../components/settings/MemoryTable";
import ResetButton from "../components/settings/ResetButton";
import Readiness from "../components/settings/Readiness";

export default function Settings() {
  return (
    <section className="space-y-8 p-6">
      <div>
        <h1 className="text-lg font-semibold">Coach memory</h1>
        <div className="mt-2"><MemoryTable /></div>
      </div>
      <div>
        <h2 className="text-lg font-semibold">Reset</h2>
        <div className="mt-2"><ResetButton /></div>
      </div>
      <div>
        <h2 className="text-lg font-semibold">Readiness</h2>
        <div className="mt-2"><Readiness /></div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run the tests, lint, build**

Run: `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: settings test passes.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(web): Settings page with memory table, reset dialog and readiness checks"
```

---

### Task 9: Playwright smoke, visual pass, docs, spec status, finish

**Files:**
- Create: `web/playwright.config.ts`, `web/tests/e2e/smoke.spec.ts`
- Modify: `web/package.json` (already has `test:e2e`), `web/src/index.css` and components (visual pass only), `README.md`, `packages/tri-web/README.md`, `docs/superpowers/specs/2026-09-14-tri-web-design.md` (Status)

- [ ] **Step 1: Playwright config and the smoke test**

`web/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1200, height: 800 } },
  webServer: { command: "npm run build && npm run preview", url: "http://127.0.0.1:4173", reuseExistingServer: true, timeout: 120_000 },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
```

`web/tests/e2e/smoke.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";

const today = {
  header: { today: "2026-09-16", phase: "active", goal: { goal_type: "olympic", event_name: "City Tri", event_date: "2026-11-01", days_to_go: 46 }, week: { start: "2026-09-14", number: 1, of: 3 }, last_sync: [] },
  session: { workouts: [{ tp_workout_id: "w1", sport: "run", title: "Tempo", completed: false, planned_duration_sec: 3600, planned_tss: 60, actual_duration_sec: null, actual_tss: null }], fuel: null },
  readiness: null,
  fuel: { target: null, targets_through: null },
  week: { phase: "build", target_hours: 6, target_tss: 300, actual_hours: 1, actual_tss: 60, sessions: [] },
  labs: null, labs_enabled: false, labs_missing: false, pending: null,
};
const proposal = { id: "p1", domain: "planning", summary: "move it", changes: [{ op: "move", workout_date: null, tp_workout_id: "w1", workout: null, new_date: "2026-09-18", payload: null, reason: "knee", athlete_requested: false }], violations: [], question: null, overrides: null };
const interrupt = { narration: "Knee: move Wednesday to Friday.", proposals: [proposal] };

function sse(frames: [string, unknown][]) {
  return frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

async function stub(page: Page) {
  let thread: Record<string, unknown> = { messages: [], paused: null, held: null, stuck: false, running: null };
  await page.route("**/api/today", (r) => r.fulfill({ json: today }));
  await page.route("**/api/system/status", (r) => r.fulfill({ json: { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", running: null } }));
  await page.route("**/api/coach/thread", (r) => r.fulfill({ json: thread }));
  await page.route("**/api/coach/review/schema", (r) => r.fulfill({ json: { proposal: {}, planning_change: { type: "object", properties: {} }, nutrition_change: { type: "object", properties: {} } } }));
  await page.route("**/api/coach/turns", async (r) => {
    thread = {
      messages: [
        { id: "h1", role: "user", text: "move my Wednesday run" },
        { id: "a1", role: "assistant", where: "coach", text: "Planning suggests Friday." },
      ],
      paused: interrupt, held: null, stuck: false, running: null,
    };
    await r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse([
        ["token", { where: "coach", text: "Planning " }],
        ["token", { where: "coach", text: "suggests Friday." }],
        ["interrupt", interrupt],
        ["done", { final_text: "Planning suggests Friday.", paused: true }],
      ]),
    });
  });
  await page.route("**/api/coach/review", async (r) => {
    thread = { messages: [...(thread.messages as unknown[]), { id: "r1", role: "report", text: "planning: applied 1" }], paused: null, held: null, stuck: false, running: null };
    await r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([["report", { text: "planning: applied 1" }], ["done", { final_text: "planning: applied 1", paused: false }]]) });
  });
}

test("load Today, send a message, see tokens, see a gate, approve, see a report", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await expect(page.getByText("Tempo")).toBeVisible();
  await expect(page.getByText(/46 days to City Tri/)).toBeVisible();
  await page.getByLabel("Message").fill("move my Wednesday run");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Planning suggests Friday.")).toBeVisible();
  const gate = page.getByRole("region", { name: "Review" });
  await expect(gate).toBeVisible();
  await expect(gate.getByText("Knee: move Wednesday to Friday.")).toBeVisible();
  await expect(gate.getByText(/move w1 to/)).toBeVisible();
  await expect(page.getByText("1 review pending")).toHaveCount(0); // today.pending is null in the stub
  await gate.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("planning: applied 1")).toBeVisible();
  await expect(page.getByRole("region", { name: "Review" })).toHaveCount(0);
});

test("the page works at phone width", async ({ page }) => {
  await stub(page);
  await page.setViewportSize({ width: 400, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  const box = await page.getByRole("navigation", { name: "Sections" }).boundingBox();
  expect(box && box.y > 600).toBeTruthy(); // the rail is a bottom bar
  await expect(page.getByLabel("Message")).toBeVisible();
});
```

Run: `npx --prefix web playwright install chromium` once, then `npm --prefix web run test:e2e`.
Expected: `2 passed`. Add `tests/e2e/**` and `playwright.config.ts` to the ESLint `ignores` if `npm run lint` complains about the Playwright globals, and keep `exclude: ["tests/e2e/**"]` in Vitest.

- [ ] **Step 2: Visual pass**

Invoke the `frontend-design` skill now and apply its direction within the token set: type scale, spacing rhythm, the strip's hierarchy (one number per card that reads first), the chat's bubble contrast in dark mode, the gate's warn border, focus rings. Keep every test selector (labels, roles, copy) unchanged. Check light and dark (`prefers-color-scheme`) and 400 px. Commit separately:

```bash
git add web
git commit -m "style(web): visual pass on the strip, chat and gate"
```

- [ ] **Step 3: Docs**

Root `README.md`: in the Run block, after the `tri-web serve` line, add:

```
npm --prefix web install && npm --prefix web run build   # once: build the app that tri-web serve hosts
npm --prefix web run dev                                  # frontend work: Vite on :5173 proxying /api to :8321
npm --prefix web run lint && npm --prefix web run test && npm --prefix web run test:e2e
```

In the Layout block add `web/                    Vite + React app: src/{api,components,pages,lib}, tests/ (Vitest, Playwright e2e)`. In Status replace the tri-web line with:

```markdown
- tri-web sub-project 1 (2026-09): server (`tri-web serve`), React shell, Today strip, coach chat with the review gate (schema form and YAML), sync and check-in jobs, memory and reset; tracked in `docs/superpowers/plans/2026-09-14-tri-web-0*.md`. Sub-projects 2 to 4 (progress, nutrition, labs) unspecced.
```

`packages/tri-web/README.md`: add a "Frontend" section pointing at `web/` with the three npm commands, the `types` script, and the note that `web/src/api/types.ts` and `web/openapi.json` are regenerated with `npm --prefix web run types` whenever a route model changes.

`docs/superpowers/specs/2026-09-14-tri-web-design.md`: change `**Status:** Approved design, not yet implemented` to `**Status:** Implemented (plans 01 to 03 merged <date>)` and, in §4, note that `tailwind.config.ts` does not exist (Tailwind 4 tokens live in `src/index.css`) and that `routes/review.py` is folded into `routes/coach.py`.

Copy every changed markdown file to the vault (`readme.md` for READMEs; kebab-case names).

- [ ] **Step 4: Whole sub-project definition of done (spec §8)**

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build
npm --prefix web run test:e2e
```

Then the manual session: `uv run tri-web serve` (live), open `http://127.0.0.1:8321`, ask the coach a question, trigger a change, Edit, change one field, Send edited, approve if a second gate appears, watch the strip update. Reload mid-review and confirm the gate comes back from the thread. Record what happened in the final commit's body.

- [ ] **Step 5: Commit**

```bash
git add README.md packages/tri-web/README.md docs/superpowers/specs/2026-09-14-tri-web-design.md web
git commit -m "docs(web): run lines, layout, status; spec status Implemented; Playwright smoke"
```

Then hand off per `superpowers:finishing-a-development-branch` (merge `feat/tri-web-03` into `main` from the shared tree once no other session is open).

---

## Self-review against the spec

**Spec coverage for this plan's slice:**
- §1 home screen (chat-centered, Today strip on top): Tasks 4, 5. Gate edit (schema fields, YAML fallback): Task 6. Frontend stack: Task 1. Serving (`npm run dev` proxies `/api`; `web/dist` served by the server): Tasks 1, 9.
- §4 `web/` layout: every listed file except `tailwind.config.ts` (Tailwind 4; noted in the spec in Task 9) and `Card.tsx`, `schemaUtils.ts`, `lib/format.ts`, `fixtures.tsx` which are additions.
- §5.3/5.4: the client renders every event and every `UiMessage` role through one component set (Task 5).
- §6.2 null sentences and refetch after `done`, after a job, on focus: Tasks 4, 5, 7 (`refetchOnWindowFocus: true` in Task 1).
- §6.3 tokens append by `where`; a change of `where` opens a new tagged bubble (Task 5).
- §6.4 reload renders history and the gate for `paused`; `held` renders without buttons with the CLI's line; the stuck hint (Tasks 5, 6).
- §6.5 gate: narration, per-proposal cards with id, domain tag, summary, change rows (op, one-line description, reason, athlete_requested), violations in red, questions; note field; Approve, Reject, Edit; `SchemaForm` field rules; `id`/`domain`/`question` read-only, `summary`/`overrides` editable; remove change and remove proposal (last one refused with "reject instead"); Edit as YAML from `GET /coach/review/yaml`; debounced validate with errors by `loc`; Send edited; Cancel; a second interrupt renders as a new gate (the hook sets `interrupt` again) (Task 6).
- §6.6 header buttons show the latest line while running and the result for a few seconds; transcript panel; paused check-in refetches the thread and shows the gate (Task 7).
- §6.7 memory table with forget; reset behind a confirm with "forget memory too"; readiness as three checks and the tool list (Task 8).
- §6.8 error bubble with retry (composer keeps the text through `lastText`); 409 disables inputs with `a {running} is running` and polls every 2 s; lost stream shows the sentence and refetches (Task 5).
- §7 rail with five sections, placeholders naming the sub-project, header contents, Today page composition, TanStack Query keys, no global store, tokens light and dark, 400 px (Tasks 1, 3, 9).
- §8 Vitest for the SSE reader (framing, multi-line data, error mid-stream) and `SchemaForm` (field types, emits JSON, remove buttons); one Playwright smoke test against a stub API covering load, send, tokens, gate, approve, report (Tasks 2, 6, 9). Definition of done (Task 9).

**Placeholder scan:** clean; every component and hook is written out.

**Type consistency:**
- `ReviewDecision` is defined in `useTurnStream.ts` and imported by `Gate.tsx`; `Gate.onDecide` receives `stream.resume`.
- `ProposalJson` (`schemaUtils.ts`) is `ReviewPayload["proposals"][number]`, the type both `SchemaForm` and `ProposalCard` take.
- `keys` in `queries.ts` are what the hooks invalidate (`["thread"]`, `["today"]`, `["memory"]`), matching the test spies.
- `Header({ today, slots })` (Task 3) is what `Today.tsx` renders with the job buttons (Task 7).
- `readSse(res, onEvent)` and `postStream(path, body)` (Task 2) are the only fetch paths used by both hooks.
- `Validated`/`ValidationItem` shapes (`{ok, proposals, errors: [{loc, msg}]}`) match plan 1's models; `errorMap` drops the leading proposal index and `perProposal` re-keys by it.
