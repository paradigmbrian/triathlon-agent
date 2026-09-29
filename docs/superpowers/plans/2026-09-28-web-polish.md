# tri-web polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the web app accessible and easier to read (tokens, motion, live regions, markdown replies) and give the Today cards baselines, load zones and per-sport numbers.

**Architecture:** Styling and accessibility are confined to `web/` (tokens in `index.css`, small component edits). New numbers are computed server-side by pure functions in a new `tri_web/metrics.py`, exposed on the existing `GET /api/today` `TodayView`, regenerated into `web/src/api/types.ts`, and rendered by the existing card components plus a new `Spark.tsx`.

**Tech Stack:** Python 3.12, FastAPI, pydantic, pytest (Postgres test DB); React 19, Vite, Tailwind v4, TanStack Query, vitest + Testing Library; new: `react-markdown`, `remark-gfm`.

**Spec:** `docs/superpowers/specs/2026-09-28-web-polish-design.md` (approved and amended 2026-09-28)

## Global Constraints

- Work on branch `feat/web-polish` off `main`; one commit per task.
- No migration, no prompt change, no `tri-* eval` run and no `pytest --live`.
- New dependencies: `react-markdown` and `remark-gfm` only. No component, icon, chart or font library.
- Colours only through tokens in `web/src/index.css`: `--warn` light `#805800`, `--good` light `#23703a` / dark `#6fcf97`, `--line` light `#d6d3c8` / dark `#3a3e47`.
- Minimum text size is `text-xs` (12px); no `text-[10px]` or `text-[11px]` anywhere in `web/src`.
- Status colour always comes with a word or an arrow (`failed`, `stale`, `low`, `high`, `fast`, `↑`, `↓`).
- Metric constants: `BASELINE_DAYS = 28`, `SHORT_DAYS = 7`, `SPARK_DAYS = 14`, `BASELINE_MIN = 14`, TSB zones by lower bound inclusive (`-30` productive, `-10` neutral, `5` fresh, `25` detraining, below `-30` overreaching), `RAMP_CAUTION = 8`, `ACWR_LOW = 0.8`, `ACWR_HIGH = 1.3`.
- Existing tests may change only where the spec §7 lists: `web/tests/fixtures.tsx` (new fields), `strip.test.tsx:25`, `shell.test.tsx:31` and `:49`. Nothing else is weakened or removed.
- Before editing code that uses a dependency, check its current docs with Context7 (Brian's rule). Already checked for this plan: Tailwind v4 (`motion-safe:`, button cursor default, `@theme`), react-markdown (safe by default, `Components` type, `node` prop).

## Review Focus

1. Sparse Garmin history (gaps, fewer than 14 days, today's value null) must render without a band word and never throw. Pinned in Task 4 (`test_trend_*`) and Task 6 (`the readiness card copes with no trends`).
2. Readiness taken from an earlier day must anchor its 28-day window on that day, not on today. Pinned in Task 5 (`test_trends_anchor_on_the_readiness_row`).
3. A `javascript:` link in a coach reply must not produce a clickable script URL. Pinned in Task 3 (`unsafe links lose their href`).
4. A reply cut mid-stream (an unclosed `**`) renders as text and does not throw. Pinned in Task 3 (`a half-streamed reply renders`).
5. Missing or zero CTL, or no row seven days back, gives no ramp and no ACWR. Pinned in Task 4 (`test_ramp_and_acwr_with_missing_inputs`) and Task 5 (`test_trends_from_28_days_of_metrics`, gap day).

---

### Task 1: Tokens, type floor and reduced motion

**Files:**
- Modify: `web/src/index.css`
- Modify: `web/src/components/today/Card.tsx:7`, `:23`
- Modify: `web/src/components/AvatarMenu.tsx:55`
- Modify: `web/src/components/chat/Message.tsx` (bubble text size, tag size)
- Modify: `web/src/components/chat/Activity.tsx:11`
- Modify: `web/src/components/gate/ProposalCard.tsx:10`, `web/src/components/gate/ChangeRow.tsx:8`, `web/src/components/gate/SchemaForm.tsx:167`
- Test: `web/tests/styles.test.ts` (new)

**Interfaces:**
- Produces: Tailwind colour utility `good` (`text-good`, `bg-good/15`), used by Task 6.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/web-polish
```

- [ ] **Step 2: Write the failing test**

`web/tests/styles.test.ts`:

```ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const src = fileURLToPath(new URL("../src", import.meta.url));
const files = (dir: string): string[] =>
  readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
const css = readFileSync(join(src, "index.css"), "utf8");

test("no text below 12px anywhere in src", () => {
  const offenders = files(src).filter((f) => /text-\[(?:\d|1[01])px\]/.test(readFileSync(f, "utf8")));
  expect(offenders).toEqual([]);
});

test("pulses only run when motion is allowed", () => {
  const bare = files(src).filter((f) => /(^|[\s"`])animate-pulse/.test(readFileSync(f, "utf8")));
  expect(bare).toEqual([]);
});

test("the tokens pass contrast and include good", () => {
  expect(css).toContain("--warn: #805800;");
  expect(css).toContain("--good: #23703a;");
  expect(css).toContain("--good: #6fcf97;");
  expect(css).toContain("--line: #d6d3c8;");
  expect(css).toContain("--line: #3a3e47;");
  expect(css).toContain("--color-good: var(--good);");
  expect(css).toContain("prefers-reduced-motion: reduce");
  expect(css).toMatch(/button:not\(:disabled\)[^{]*\{\s*cursor: pointer;/);
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npm --prefix web run test -- tests/styles.test.ts`
Expected: FAIL; the offenders list names `Card.tsx`, `Message.tsx`, `Activity.tsx`, `ProposalCard.tsx`, `ChangeRow.tsx`, `SchemaForm.tsx`; the pulse test names `AvatarMenu.tsx` and `Card.tsx`; the token test fails on `--warn: #805800;`.

- [ ] **Step 4: Update `web/src/index.css`**

In the light `:root` block, change `--line: #e2e0d8;` to `--line: #d6d3c8;` and `--warn: #9a6b00;` to `--warn: #805800;`, and add `--good: #23703a;` after `--warn`. In the dark block, change `--line: #2c2f36;` to `--line: #3a3e47;` and add `--good: #6fcf97;` after `--warn`. In `@theme inline`, add `--color-good: var(--good);` after `--color-warn`. Replace the `@layer base` block with:

```css
@layer base {
  :focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  summary { list-style-position: inside; }
  /* Tailwind v4 preflight gives buttons cursor: default. */
  button:not(:disabled), [role="button"], summary {
    cursor: pointer;
  }
  button, a {
    transition: color 150ms ease-out, background-color 150ms ease-out, border-color 150ms ease-out;
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
  }
}
```

- [ ] **Step 5: Raise the small text and guard the pulses**

- `Card.tsx:7`: `text-[11px]` → `text-xs`.
- `Card.tsx:23`: `animate-pulse` → `motion-safe:animate-pulse`.
- `AvatarMenu.tsx:55`: `animate-pulse` → `motion-safe:animate-pulse`.
- `Message.tsx`: the tag span's `text-[11px]` → `text-xs`. In the user bubble and the assistant/consult bubble, `text-sm` → `text-base`, but keep `text-xs` on the consult variant (`role === "consult" ? "font-mono text-xs text-ink-2" : ""`).
- `Activity.tsx:11`: `text-[11px]` → `text-xs`.
- `ProposalCard.tsx:10`, `ChangeRow.tsx:8`, `SchemaForm.tsx:167`: every `text-[10px]` and `text-[11px]` → `text-xs`.

- [ ] **Step 6: Run the new test and the whole web suite**

Run: `npm --prefix web run test`
Expected: all PASS, including the three new tests.

- [ ] **Step 7: Commit**

```bash
git add web/src web/tests/styles.test.ts
git commit -m "style(web): tokens that pass contrast, a good colour, 12px floor, pointer cursor, reduced motion"
```

---

### Task 2: Accessibility and interaction

**Files:**
- Modify: `web/src/components/chat/Chat.tsx`
- Modify: `web/src/components/chat/Composer.tsx`
- Modify: `web/src/components/chat/Activity.tsx`
- Modify: `web/src/components/Shell.tsx`
- Modify: `web/src/components/Header.tsx`
- Modify: `web/src/components/settings/MemoryTable.tsx`, `web/src/components/settings/ResetButton.tsx`
- Modify: `web/src/pages/Placeholder.tsx`
- Test: `web/tests/chat.test.tsx`, `web/tests/shell.test.tsx` (lines 31 and 49 change per spec §7), `web/tests/settings.test.tsx`

**Interfaces:**
- Produces: `Composer` prop `hintTone?: "warn" | "muted"` (default `"muted"`); `Header` prop `now?: number` (ms since epoch, default: time of mount).

- [ ] **Step 1: Write the failing tests**

Append to `web/tests/chat.test.tsx`:

```tsx
test("the conversation is a polite log that is busy while a turn streams", async () => {
  stubServer(() => threadEmpty(), () => openStream());
  renderWith(<Harness />);
  const log = screen.getByRole("log", { name: "Conversation" });
  expect(log).toHaveAttribute("aria-live", "polite");
  expect(log).toHaveAttribute("aria-busy", "false");
  sendText("how am I doing?");
  await waitFor(() => expect(log).toHaveAttribute("aria-busy", "true"));
});

test("the hint is a status line: muted while running, warn when the athlete must act", async () => {
  stubServer(() => threadEmpty(), () => openStream());
  renderWith(<Harness paused />);
  expect(await screen.findByRole("status")).toHaveTextContent("answer the review first");
  expect(screen.getByRole("status")).toHaveClass("text-warn");
});
```

Add a muted-tone case after the existing `"a checkin is running"` assertion at `chat.test.tsx:102` (a new line; the existing assertion stays):

```tsx
  expect(screen.getByText("a checkin is running")).toHaveClass("text-ink-2");
```

In `web/tests/shell.test.tsx`, change `/arrives in sub-project 2/` to `/Coming soon/` at lines 31 and 49 (spec §7), and append:

```tsx
test("a skip link targets main, and main takes focus after a route change", async () => {
  const user = userEvent.setup();
  renderWith(tree(), { route: "/progress" });
  expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main");
  const main = screen.getByRole("main");
  expect(main).not.toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Account menu" }));
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(main).toHaveFocus();
});

test("sync status says failed or stale in words, not only colour", () => {
  const t = todayFull();
  const at = Date.parse(t.header.last_sync[0].last_run_at);
  const failed = { ...t, header: { ...t.header, last_sync: [{ ...t.header.last_sync[0], status: "error", error: "401" }] } };
  const { unmount } = renderWith(<Header today={failed} now={at + 60_000} />);
  expect(screen.getByText(/garmin .* · failed/)).toHaveClass("text-danger");
  unmount();
  renderWith(<Header today={t} now={at + 25 * 3_600_000} />);
  expect(screen.getByText(/garmin .* · stale/)).toHaveClass("text-warn");
});

test("a fresh sync carries no status word", () => {
  const t = todayFull();
  renderWith(<Header today={t} now={Date.parse(t.header.last_sync[0].last_run_at) + 3_600_000} />);
  expect(screen.queryByText(/stale|failed/)).not.toBeInTheDocument();
});
```

Append to `web/tests/settings.test.tsx` a check inside a new test that reuses the file's existing memory/status stubs. Copy the stub block from the test at `settings.test.tsx:24` and hold `/api/coach/reset` on a promise, as the test at line 60 does:

```tsx
test("confirm reset reads Resetting… while the request runs", async () => {
  let release: () => void;
  const hold = new Promise<void>((r) => (release = r));
  const f = vi.spyOn(globalThis, "fetch");
  f.mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/coach/memory") return new Response(JSON.stringify({ entries: [], active_ids: [] }), { status: 200 });
    if (url === "/api/system/status") return new Response(JSON.stringify({ ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", live: false, tools: [], running: null }), { status: 200 });
    if (url === "/api/coach/reset") {
      await hold;
      return new Response(null, { status: 204 });
    }
    return new Response("nope", { status: 404 });
  });
  const user = userEvent.setup();
  renderWith(<Settings />);
  await user.click(screen.getByRole("button", { name: "Reset conversation" }));
  await user.click(screen.getByRole("button", { name: "Confirm reset" }));
  expect(await screen.findByRole("button", { name: "Resetting…" })).toBeDisabled();
  release!();
  expect(await screen.findByText("conversation cleared")).toBeInTheDocument();
});
```

(If `StatusOut` in `web/src/api/types.ts` has fields beyond these, copy the status object from the existing test in the same file instead.)

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/chat.test.tsx tests/shell.test.tsx tests/settings.test.tsx`
Expected: FAIL. No `log` role; the `status` role is missing; `/Coming soon/` is not found; the skip link is missing; `now` is not a prop, and no `failed`/`stale` words; no `Resetting…`.

- [ ] **Step 3: Composer status line** (`Composer.tsx`)

Change the props and the hint paragraph:

```tsx
type Props = { disabled: boolean; hint?: string; hintTone?: "warn" | "muted"; initialText?: string; onSend: (text: string) => void };

export default function Composer({ disabled, hint, hintTone = "muted", initialText = "", onSend }: Props) {
```

Replace `{hint && <p className="mb-2 text-xs text-warn">{hint}</p>}` with a region that is always mounted, so a screen reader hears each change:

```tsx
        <p role="status" className={hint ? `mb-2 text-xs ${hintTone === "warn" ? "text-warn" : "text-ink-2"}` : "sr-only"}>
          {hint}
        </p>
```

- [ ] **Step 4: Chat log and tone** (`Chat.tsx`)

After the `hint` constant add:

```tsx
  // Warn only when the athlete has to act; a running turn or job is routine.
  const hintTone = state.lost || paused || thread?.stuck ? "warn" : "muted";
  const streaming = busy || state.status === "streaming";
```

On the scroller `div` (`Chat.tsx:38`) add `role="log" aria-label="Conversation" aria-live="polite" aria-busy={streaming}`. Pass `hintTone={hintTone}` to `<Composer>`. The retry button's class becomes `ml-3 inline-flex min-h-6 items-center px-1 underline`.

- [ ] **Step 5: Activity toggle target** (`Activity.tsx`)

The toggle button's class becomes `inline-flex min-h-6 items-center rounded font-mono hover:text-ink`.

- [ ] **Step 6: Skip link and route focus** (`Shell.tsx`)

```tsx
import { useEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router";
import { useToday } from "../api/queries";
import AvatarMenu from "./AvatarMenu";
import Header from "./Header";

export default function Shell() {
  const today = useToday();
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const shown = useRef(pathname);
  // Move focus to the page after navigation (not on first load) so a screen reader starts there.
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    main.current?.focus();
  }, [pathname]);
  return (
    <div className="flex h-full flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-2 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to main content
      </a>
      <Header today={today.data} slots={<AvatarMenu />} />
      <main id="main" ref={main} tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto focus:outline-none">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 7: Sync status words** (`Header.tsx`)

```tsx
import { useState, type ReactNode } from "react";
```

Change the signature and the sync map:

```tsx
const STALE_MS = 24 * 3_600_000;

export default function Header({ today, slots, now }: { today?: TodayView; slots?: ReactNode; now?: number }) {
  const [mountedAt] = useState(Date.now);
  const clock = now ?? mountedAt;
```

```tsx
        {h?.last_sync.map((s) => {
          const failed = s.status !== "ok";
          const stale = !failed && clock - Date.parse(s.last_run_at) > STALE_MS;
          const tone = failed ? "text-danger" : stale ? "text-warn" : "text-ink-2";
          return (
            <div key={s.source} className={`text-xs ${tone}`} title={s.error ?? ""}>
              {s.source} {when(s.last_run_at)}
              {failed ? " · failed" : stale ? " · stale" : ""}
            </div>
          );
        })}
```

- [ ] **Step 8: Target sizes and loading labels** (`MemoryTable.tsx`, `ResetButton.tsx`)

`MemoryTable.tsx`: the forget button keeps its `aria-label`; its class becomes `inline-flex min-h-6 min-w-6 items-center px-1 text-xs text-danger disabled:opacity-50`, and its text becomes:

```tsx
{forget.isPending && forget.variables === e.id ? "forgetting…" : "forget"}
```

`ResetButton.tsx`: the confirm button's text becomes `{loading ? "Resetting…" : "Confirm reset"}`.

- [ ] **Step 9: Placeholder copy** (`Placeholder.tsx`)

```tsx
const blurbs = {
  2: "your fitness curve, weekly load by sport and recovery trends",
  3: "daily targets, fuel plans and the fuel log",
  4: "lab panels, reports and PDF upload",
};

export default function Placeholder({ name, subProject }: { name: string; subProject: 2 | 3 | 4 }) {
  return (
    <section className="p-6">
      <h1 className="text-lg font-semibold">{name}</h1>
      <p className="mt-2 text-ink-2">Coming soon: {blurbs[subProject]}.</p>
    </section>
  );
}
```

- [ ] **Step 10: Run the web suite and lint**

Run: `npm --prefix web run test && npm --prefix web run lint`
Expected: all PASS, lint clean.

- [ ] **Step 11: Commit**

```bash
git add web/src web/tests
git commit -m "feat(web): chat log and status live regions, skip link, route focus, sync status words, 24px targets"
```

---

### Task 3: Markdown in coach replies

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (via npm)
- Modify: `web/src/components/chat/Message.tsx`
- Create: `web/src/components/chat/prose.css`
- Test: `web/tests/message.test.tsx` (new)

**Interfaces:**
- Consumes: `Bubble({ role, where, children })` unchanged in signature.

- [ ] **Step 1: Install the two packages**

Run: `npm --prefix web install react-markdown remark-gfm`
Expected: both added to `dependencies`, lockfile updated.

- [ ] **Step 2: Write the failing tests**

`web/tests/message.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { Bubble } from "../src/components/chat/Message";

test("an assistant reply renders markdown", () => {
  render(<Bubble role="assistant">{"Take **two** easy days:\n\n- Mon swim\n- Tue rest"}</Bubble>);
  expect(screen.getByText("two").tagName).toBe("STRONG");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("a user message stays literal", () => {
  render(<Bubble role="user">{"**not bold**"}</Bubble>);
  expect(screen.getByText("**not bold**")).toBeInTheDocument();
});

test("links open in a new tab", () => {
  render(<Bubble role="assistant">{"[guide](https://example.com)"}</Bubble>);
  const a = screen.getByRole("link", { name: "guide" });
  expect(a).toHaveAttribute("target", "_blank");
  expect(a).toHaveAttribute("rel", "noreferrer");
});

test("unsafe links lose their href", () => {
  render(<Bubble role="assistant">{"[x](javascript:alert(1))"}</Bubble>);
  expect(screen.getByText("x").getAttribute("href") ?? "").not.toMatch(/javascript/i);
});

test("a half-streamed reply renders", () => {
  render(<Bubble role="assistant">{"CTL is **up"}</Bubble>);
  expect(screen.getByText(/CTL is \*\*up/)).toBeInTheDocument();
});

test("headings never out-shout the page", () => {
  render(<Bubble role="assistant">{"# Week plan"}</Bubble>);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(screen.getByText("Week plan")).toHaveClass("font-semibold");
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/message.test.tsx`
Expected: FAIL on `STRONG`, list items, the link, and the heading class (the user-literal and half-streamed tests may already pass).

- [ ] **Step 4: Write `prose.css`**

`web/src/components/chat/prose.css`:

```css
/* Spacing for markdown inside assistant bubbles; Tailwind preflight strips list and heading styles. */
.chat-prose > * + * { margin-top: 0.6em; }
.chat-prose ul { list-style: disc; padding-left: 1.25em; }
.chat-prose ol { list-style: decimal; padding-left: 1.25em; }
.chat-prose li + li { margin-top: 0.2em; }
.chat-prose strong { font-weight: 600; }
.chat-prose code { font-family: ui-monospace, monospace; font-size: 0.9em; background: var(--surface); border-radius: 0.25rem; padding: 0.05em 0.3em; }
.chat-prose pre { background: var(--surface); border-radius: 0.375rem; padding: 0.5em 0.75em; overflow-x: auto; }
.chat-prose pre code { background: none; padding: 0; }
.chat-prose table { border-collapse: collapse; font-variant-numeric: tabular-nums; }
.chat-prose th, .chat-prose td { border: 1px solid var(--line); padding: 0.2em 0.5em; text-align: left; }
.chat-prose a { color: var(--accent); text-decoration: underline; }
.chat-prose blockquote { border-left: 3px solid var(--line); padding-left: 0.75em; color: var(--ink-2); }
```

- [ ] **Step 5: Render markdown in `Message.tsx`**

Add at the top:

```tsx
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import "./prose.css";

/** react-markdown passes the hast node; it is not a DOM attribute. */
function dom<T extends { node?: unknown }>({ node, ...rest }: T) {
  void node;
  return rest;
}

const heading = (props: { node?: unknown; children?: ReactNode }) => <p className="font-semibold">{dom(props).children}</p>;

const md: Components = {
  a: (props) => <a {...dom(props)} target="_blank" rel="noreferrer" />,
  table: (props) => (
    <div className="overflow-x-auto">
      <table {...dom(props)} />
    </div>
  ),
  h1: heading,
  h2: heading,
  h3: heading,
  h4: heading,
  h5: heading,
  h6: heading,
};
```

In the final (assistant/consult) branch, drop `whitespace-pre-wrap` for assistant bubbles only and render the markdown:

```tsx
  const tag = where && where !== "coach" ? where : null;
  const prose = role === "assistant" && typeof children === "string";
  return (
    <div
      className={`max-w-[85%] rounded-2xl rounded-bl-sm border border-line bg-surface-2 px-3.5 py-2 text-base leading-relaxed ${prose ? "" : "whitespace-pre-wrap"} ${role === "consult" ? "font-mono text-xs text-ink-2" : ""}`}
    >
      {tag && <span className={`mr-2 text-xs font-semibold tracking-wide uppercase ${tagColor[tag] ?? "text-ink-2"}`}>{tag}</span>}
      {prose ? (
        <div className="chat-prose">
          <Markdown remarkPlugins={[remarkGfm]} components={md}>
            {children}
          </Markdown>
        </div>
      ) : (
        children
      )}
    </div>
  );
```

- [ ] **Step 6: Run the web suite, lint and build**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all PASS; `chat.test.tsx:83` ("Let me check. CTL 45.") still passes because the paragraph's own text matches.

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/src/components/chat web/tests/message.test.tsx
git commit -m "feat(web): coach replies render as markdown (react-markdown, remark-gfm; safe defaults)"
```

---

### Task 4: Pure metrics module

**Files:**
- Create: `packages/tri-web/src/tri_web/metrics.py`
- Test: `packages/tri-web/tests/test_metrics.py` (new)

**Interfaces:**
- Produces:
  - `MetricTrend` (pydantic): `now: float`, `avg_7d: float | None`, `avg_28d: float | None`, `sd_28d: float | None`, `band: Literal["below","normal","above"] | None`, `better: bool | None`, `spark: list[float | None]`
  - `trend(values: list[float | None], higher_is_better: bool) -> MetricTrend | None`
  - `tsb_zone(tsb: float | None) -> str | None`
  - `ramp(ctl_now: float | None, ctl_week_ago: float | None) -> float | None`
  - `acwr(atl: float | None, ctl: float | None) -> float | None`
  - `acwr_flag(value: float | None) -> Literal["low", "high"] | None`
  - constants `BASELINE_DAYS`, `SHORT_DAYS`, `SPARK_DAYS`, `BASELINE_MIN`, `TSB_ZONES`, `RAMP_CAUTION`, `ACWR_LOW`, `ACWR_HIGH`

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_metrics.py`:

```python
"""The pure numbers behind the Today cards."""

import pytest

from tri_web.metrics import (
    BASELINE_MIN,
    RAMP_CAUTION,
    acwr,
    acwr_flag,
    ramp,
    trend,
    tsb_zone,
)


def test_trend_is_none_without_todays_value():
    assert trend([60.0, 61.0, None], higher_is_better=True) is None
    assert trend([], higher_is_better=True) is None


def test_trend_below_the_minimum_has_averages_but_no_band():
    t = trend([60.0] * (BASELINE_MIN - 2) + [50.0], higher_is_better=True)
    assert t is not None
    assert t.band is None and t.better is False and t.now == 50.0
    assert t.avg_28d is not None and t.avg_7d is not None


def test_trend_band_edges_and_direction():
    base = [58.0, 62.0] * 10  # mean 60, population sd 2
    low = trend(base + [57.0], higher_is_better=True)
    assert low is not None and low.band == "below" and low.better is False
    high_rhr = trend([48.0, 52.0] * 10 + [52.5], higher_is_better=False)
    assert high_rhr is not None and high_rhr.band == "above" and high_rhr.better is False
    normal = trend(base + [60.0], higher_is_better=True)
    assert normal is not None and normal.band == "normal" and normal.better is None


def test_trend_uses_only_the_last_28_days_and_keeps_gaps_in_the_spark():
    values: list[float | None] = [100.0] * 10 + [60.0] * 27 + [None, 60.0]
    t = trend(values, higher_is_better=True)
    assert t is not None and t.avg_28d == 60.0
    assert len(t.spark) == 14 and t.spark[-2] is None and t.spark[-1] == 60.0


@pytest.mark.parametrize(
    ("tsb", "zone"),
    [
        (None, None),
        (-30.1, "overreaching"),
        (-30, "productive"),
        (-10.1, "productive"),
        (-10, "neutral"),
        (4.9, "neutral"),
        (5, "fresh"),
        (24.9, "fresh"),
        (25, "detraining"),
    ],
)
def test_tsb_zone_boundaries(tsb, zone):
    assert tsb_zone(tsb) == zone


def test_ramp_and_acwr_with_missing_inputs():
    assert ramp(50.0, 45.0) == 5.0
    assert ramp(None, 45.0) is None and ramp(50.0, None) is None
    assert acwr(60.0, 50.0) == 1.2
    assert acwr(60.0, 0) is None and acwr(60.0, None) is None and acwr(None, 50.0) is None
    assert RAMP_CAUTION == 8


def test_acwr_flag_band():
    assert acwr_flag(None) is None
    assert acwr_flag(0.79) == "low"
    assert acwr_flag(0.8) is None and acwr_flag(1.3) is None
    assert acwr_flag(1.31) == "high"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_web.metrics'`.

- [ ] **Step 3: Write `metrics.py`**

```python
"""The numbers behind the Today cards: a metric against its own 28 days, the TSB zone, the CTL
ramp over a week and the acute:chronic ratio. Pure; build_today feeds them rows."""

from __future__ import annotations

from statistics import fmean, pstdev
from typing import Literal

from pydantic import BaseModel

BASELINE_DAYS = 28
SHORT_DAYS = 7
SPARK_DAYS = 14
BASELINE_MIN = 14  # values needed before a band is drawn
# (lower bound, inclusive; zone), highest first. Below the last bound is "overreaching".
TSB_ZONES: tuple[tuple[float, str], ...] = (
    (25, "detraining"),
    (5, "fresh"),
    (-10, "neutral"),
    (-30, "productive"),
)
RAMP_CAUTION = 8.0  # CTL gained over 7 days
ACWR_LOW = 0.8
ACWR_HIGH = 1.3

Band = Literal["below", "normal", "above"]


class MetricTrend(BaseModel):
    now: float
    avg_7d: float | None
    avg_28d: float | None
    sd_28d: float | None
    band: Band | None  # None below BASELINE_MIN values
    better: bool | None  # now against avg_28d in the metric's good direction; None when equal
    spark: list[float | None]  # the last SPARK_DAYS days, oldest first, None for a gap


def _clean(values: list[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None]


def trend(values: list[float | None], higher_is_better: bool) -> MetricTrend | None:
    """values: one per day, oldest first, ending on the readiness day."""
    if not values or values[-1] is None:
        return None
    now = float(values[-1])
    window = _clean(values[-BASELINE_DAYS:])
    week = _clean(values[-SHORT_DAYS:])
    avg = fmean(window)
    sd = pstdev(window) if len(window) >= 2 else None
    band: Band | None = None
    if len(window) >= BASELINE_MIN and sd is not None:
        band = "below" if now < avg - sd else "above" if now > avg + sd else "normal"
    better = None if now == avg else (now > avg) == higher_is_better
    return MetricTrend(
        now=now,
        avg_7d=round(fmean(week), 2),
        avg_28d=round(avg, 2),
        sd_28d=None if sd is None else round(sd, 2),
        band=band,
        better=better,
        spark=[None if v is None else float(v) for v in values[-SPARK_DAYS:]],
    )


def tsb_zone(tsb: float | None) -> str | None:
    if tsb is None:
        return None
    for bound, zone in TSB_ZONES:
        if tsb >= bound:
            return zone
    return "overreaching"


def ramp(ctl_now: float | None, ctl_week_ago: float | None) -> float | None:
    if ctl_now is None or ctl_week_ago is None:
        return None
    return round(ctl_now - ctl_week_ago, 2)


def acwr(atl: float | None, ctl: float | None) -> float | None:
    if atl is None or not ctl:
        return None
    return round(atl / ctl, 2)


def acwr_flag(value: float | None) -> Literal["low", "high"] | None:
    if value is None:
        return None
    if value < ACWR_LOW:
        return "low"
    if value > ACWR_HIGH:
        return "high"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_metrics.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check packages/tri-web && uv run ruff format --check packages/tri-web && uv run mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-web/src/tri_web/metrics.py packages/tri-web/tests/test_metrics.py
git commit -m "feat(web): pure metrics for the Today cards (28-day trend, TSB zone, ramp, ACWR)"
```

---

### Task 5: `TodayView` carries trends, load, workout detail and per-sport week

**Files:**
- Modify: `packages/tri-web/src/tri_web/today.py` (`WorkoutOut` :57, `ReadinessOut` :84, `SportCount` :117, `WeekOut` :123, `_workout`, `_readiness`, `build_today` :203)
- Modify: `web/openapi.json`, `web/src/api/types.ts` (regenerated)
- Modify: `web/tests/fixtures.tsx` (new fields; spec §7)
- Test: `packages/tri-web/tests/test_today.py` (new tests only)

**Interfaces:**
- Consumes: everything Task 4 produces.
- Produces (TypeScript via `S["…"]`):
  - `ReadinessOut` adds `trends: Record<string, MetricTrend>` (keys `hrv`, `resting_hr`, `sleep_score`, `sleep_hours`, `training_readiness`; a key is absent when that value is null), `tsb_zone: string | null`, `ramp_7d: number | null`, `ramp_caution: boolean`, `acwr: number | null`, `acwr_flag: "low" | "high" | null`
  - `WorkoutOut` adds `actual_if: number | null`, `avg_hr: number | null`, `avg_power: number | null`, `normalized_power: number | null`
  - `SportCount` adds `planned_tss`, `actual_tss`, `planned_hours`, `actual_hours` (numbers)
  - `WeekOut` adds `planned_to_date`, `completed_to_date` (integers)

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-web/tests/test_today.py` (add `from tri_web.metrics import BASELINE_DAYS` to the imports):

```python
def seed_metrics(conn, end: date, *, gap: date | None = None) -> None:
    """28 days ending on `end`: HRV 60 and RHR 48 every day, then 50 and 55 on `end`; CTL rising
    0.5 a day from 40; ATL 60 and TSB -6.5 on `end`; no training readiness or sleep time."""
    for i in range(BASELINE_DAYS):
        d = end - timedelta(days=BASELINE_DAYS - 1 - i)
        if d == gap:
            continue
        last = d == end
        conn.execute(
            "insert into daily_metrics (metric_date, sleep_score, hrv_overnight_avg, resting_hr, "
            "ctl, atl, tsb) values (%s, 80, %s, %s, %s, %s, %s)",
            (d, 50 if last else 60, 55 if last else 48, 40 + 0.5 * i, 60 if last else 50, -6.5 if last else 0),
        )


async def test_trends_from_28_days_of_metrics(nocommit, runtime):
    seed_metrics(nocommit, TODAY, gap=TODAY - timedelta(days=3))
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None
    assert set(r.trends) == {"hrv", "resting_hr", "sleep_score"}
    hrv = r.trends["hrv"]
    assert hrv.now == 50 and hrv.band == "below" and hrv.better is False
    rhr = r.trends["resting_hr"]
    assert rhr.band == "above" and rhr.better is False
    assert len(hrv.spark) == 14 and hrv.spark[10] is None
    assert r.tsb_zone == "neutral"
    assert r.ramp_7d == 3.5 and r.ramp_caution is False
    assert r.acwr == 1.12 and r.acwr_flag is None


async def test_trends_anchor_on_the_readiness_row(nocommit, runtime):
    seed_metrics(nocommit, TODAY - timedelta(days=2))
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None and r.is_today is False
    assert r.trends["hrv"].now == 50 and r.trends["hrv"].band == "below"


async def test_one_row_of_metrics_gives_no_ramp_and_no_band(nocommit, runtime):
    nocommit.execute(
        "insert into daily_metrics (metric_date, hrv_overnight_avg, ctl, atl, tsb) values (%s, 60, 0, 10, 30)",
        (TODAY,),
    )
    r = (await build_today(runtime(today=TODAY))).readiness
    assert r is not None
    assert r.trends["hrv"].band is None
    assert r.ramp_7d is None and r.acwr is None and r.acwr_flag is None
    assert r.tsb_zone == "detraining"


async def test_workout_detail_and_per_sport_week(nocommit, runtime):
    seed_active_plan(nocommit)
    seed_day(nocommit, TODAY)
    nocommit.execute(
        "update workouts set completed = true, actual_duration_sec = 3780, actual_tss = 57, "
        "actual_if = 0.82, avg_hr = 148, avg_power = 212, normalized_power = 225 "
        "where tp_workout_id = 'w1'"
    )
    view = await build_today(runtime(today=TODAY))
    assert view.session is not None
    w1 = view.session.workouts[0]
    assert (w1.actual_if, w1.avg_hr, w1.avg_power, w1.normalized_power) == (0.82, 148, 212, 225)
    week = view.week
    assert week is not None
    by = {s.sport: s for s in week.sessions}
    assert (by["run"].planned_tss, by["run"].actual_tss) == (60, 57)
    assert (by["run"].planned_hours, by["run"].actual_hours) == (1.0, 1.05)
    assert (by["bike"].planned_tss, by["bike"].actual_tss, by["bike"].planned_hours) == (80, 0, 1.5)
    assert (week.planned_to_date, week.completed_to_date) == (2, 2)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_today.py -v`
Expected: the four new tests FAIL (`AttributeError`/validation on the missing fields); the existing tests PASS.

- [ ] **Step 3: Extend the models** (`today.py`)

Add imports:

```python
from tri_web.metrics import (
    BASELINE_DAYS,
    MetricTrend,
    acwr,
    acwr_flag,
    ramp,
    trend,
    tsb_zone,
)
```

and `from typing import Any, Literal`.

`WorkoutOut` gains, after `actual_tss`:

```python
    actual_if: float | None
    avg_hr: int | None
    avg_power: int | None
    normalized_power: int | None
```

`ReadinessOut` gains, after `tsb`:

```python
    trends: dict[str, MetricTrend]  # a key is absent when that metric is null on this day
    tsb_zone: str | None
    ramp_7d: float | None  # CTL now minus CTL seven days earlier
    ramp_caution: bool
    acwr: float | None  # ATL / CTL
    acwr_flag: Literal["low", "high"] | None
```

`SportCount` gains:

```python
    planned_tss: float
    actual_tss: float
    planned_hours: float
    actual_hours: float
```

`WeekOut` gains:

```python
    planned_to_date: int  # sessions dated on or before today
    completed_to_date: int
```

- [ ] **Step 4: Fill them**

`_workout` adds:

```python
        actual_if=_f(row.get("actual_if")),
        avg_hr=row.get("avg_hr"),
        avg_power=row.get("avg_power"),
        normalized_power=row.get("normalized_power"),
```

Replace `_readiness` with:

```python
# (key, daily_metrics column, higher is better)
TRENDS = (
    ("hrv", "hrv_overnight_avg", True),
    ("resting_hr", "resting_hr", False),
    ("sleep_score", "sleep_score", True),
    ("sleep_hours", "sleep_seconds", True),
    ("training_readiness", "training_readiness", True),
)


def _readiness(row: dict[str, Any], today: date, history: list[dict[str, Any]]) -> ReadinessOut:
    """history: daily_metrics rows in the BASELINE_DAYS ending on row's date, any order."""
    end: date = row["metric_date"]
    by_day = {h["metric_date"]: h for h in history}
    days = [end - timedelta(days=BASELINE_DAYS - 1 - i) for i in range(BASELINE_DAYS)]

    def series(column: str) -> list[float | None]:
        out: list[float | None] = []
        for d in days:
            v = _f(by_day[d].get(column)) if d in by_day else None
            out.append(round(v / 3600, 2) if v is not None and column == "sleep_seconds" else v)
        return out

    trends = {
        key: t for key, column, up in TRENDS if (t := trend(series(column), up)) is not None
    }
    secs = row.get("sleep_seconds")
    ctl, atl, tsb = _f(row.get("ctl")), _f(row.get("atl")), _f(row.get("tsb"))
    week_ago = by_day.get(end - timedelta(days=7))
    ramp_7d = ramp(ctl, _f(week_ago.get("ctl")) if week_ago else None)
    ratio = acwr(atl, ctl)
    return ReadinessOut(
        date=end,
        is_today=end == today,
        sleep_score=row.get("sleep_score"),
        sleep_hours=round(secs / 3600, 2) if secs is not None else None,
        hrv=row.get("hrv_overnight_avg"),
        resting_hr=row.get("resting_hr"),
        body_battery=row.get("body_battery_high"),
        training_readiness=row.get("training_readiness"),
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        trends=trends,
        tsb_zone=tsb_zone(tsb),
        ramp_7d=ramp_7d,
        ramp_caution=ramp_7d is not None and ramp_7d > RAMP_CAUTION,
        acwr=ratio,
        acwr_flag=acwr_flag(ratio),
    )
```

(Add `RAMP_CAUTION` to the `tri_web.metrics` import.)

In `build_today`, right after the `metric = conn.execute(...).fetchone()` statement inside the `with` block:

```python
        history = (
            conn.execute(
                "select * from daily_metrics where metric_date between %s and %s",
                (metric["metric_date"] - timedelta(days=BASELINE_DAYS - 1), metric["metric_date"]),
            ).fetchall()
            if metric is not None
            else []
        )
```

and change `readiness = _readiness(metric, today) if ...` to `_readiness(metric, today, history)`.

Replace the week block's counting with:

```python
        per: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for w in week_rows:
            a = per[w["sport"]]
            a["planned"] += 1
            a["completed"] += int(bool(w["completed"]))
            a["planned_tss"] += float(w["planned_tss"] or 0)
            a["actual_tss"] += float(w["actual_tss"] or 0)
            a["planned_hours"] += (w["planned_duration_sec"] or 0) / 3600
            a["actual_hours"] += (w["actual_duration_sec"] or 0) / 3600
        to_date = [w for w in week_rows if w["workout_date"] <= today]
```

and the `WeekOut(...)` call's `sessions=` and new fields with:

```python
            sessions=[
                SportCount(
                    sport=s,
                    planned=int(a["planned"]),
                    completed=int(a["completed"]),
                    planned_tss=round(a["planned_tss"], 1),
                    actual_tss=round(a["actual_tss"], 1),
                    planned_hours=round(a["planned_hours"], 2),
                    actual_hours=round(a["actual_hours"], 2),
                )
                for s, a in sorted(per.items())
            ],
            planned_to_date=len(to_date),
            completed_to_date=sum(1 for w in to_date if w["completed"]),
```

- [ ] **Step 5: Run the today tests**

Run: `uv run pytest packages/tri-web/tests/test_today.py -v`
Expected: all PASS, old and new.

- [ ] **Step 6: Regenerate the frontend types**

Run: `npm --prefix web run types`
Expected: `web/openapi.json` and `web/src/api/types.ts` now contain `MetricTrend`, `acwr_flag`, `planned_to_date`.

- [ ] **Step 7: Update `web/tests/fixtures.tsx`** (spec §7)

In `todayFull()`:
- The workout `w1` gains `actual_if: null, avg_hr: null, avg_power: null, normalized_power: null`.
- `readiness` gains:

```tsx
      trends: {
        hrv: { now: 62, avg_7d: 60, avg_28d: 58, sd_28d: 3, band: "above", better: true, spark: [55, 56, 58, 57, 59, null, 60, 61, 58, 59, 60, 61, 60, 62] },
        resting_hr: { now: 48, avg_7d: 49, avg_28d: 50, sd_28d: 2, band: "normal", better: true, spark: [51, 50, 50, 49, 49, 50, 49, 48, 49, 50, 49, 48, 49, 48] },
        sleep_score: { now: 81, avg_7d: 79, avg_28d: 78, sd_28d: 5, band: "normal", better: true, spark: [75, 80, 78, 77, 79, 82, 76, 78, 80, 79, 77, 81, 78, 81] },
        sleep_hours: { now: 7.5, avg_7d: 7.3, avg_28d: 7.2, sd_28d: 0.4, band: "normal", better: true, spark: [7, 7.4, 7.2, 7.1, 7.3, 7.6, 7, 7.2, 7.4, 7.3, 7.1, 7.5, 7.2, 7.5] },
        training_readiness: { now: 77, avg_7d: 72, avg_28d: 70, sd_28d: 8, band: "normal", better: true, spark: [65, 70, 68, 72, 74, 71, 69, 70, 73, 72, 70, 75, 74, 77] },
      },
      tsb_zone: "neutral",
      ramp_7d: 3.5,
      ramp_caution: false,
      acwr: 1.11,
      acwr_flag: null,
```

- `week.sessions` becomes:

```tsx
      sessions: [
        { sport: "run", planned: 2, completed: 1, planned_tss: 120, actual_tss: 60, planned_hours: 2, actual_hours: 1 },
        { sport: "bike", planned: 2, completed: 1, planned_tss: 180, actual_tss: 60, planned_hours: 4, actual_hours: 1.5 },
      ],
      planned_to_date: 3,
      completed_to_date: 2,
```

- [ ] **Step 8: Type-check and run both suites**

Run: `npm --prefix web run build && npm --prefix web run test && uv run pytest packages/tri-web -q && uv run mypy`
Expected: all PASS. (The cards do not read the new fields yet; `tsc` only confirms the fixtures match the types.)

- [ ] **Step 9: Commit**

```bash
git add packages/tri-web web/openapi.json web/src/api/types.ts web/tests/fixtures.tsx
git commit -m "feat(web): TodayView carries 28-day trends, TSB zone, ramp, ACWR, workout detail and per-sport week"
```

---

### Task 6: The cards show it

**Files:**
- Create: `web/src/components/today/Spark.tsx`
- Modify: `web/src/components/today/ReadinessCard.tsx`, `SessionCard.tsx`, `WeekCard.tsx`
- Test: `web/tests/strip.test.tsx` (line 25 changes per spec §7; new tests appended)

**Interfaces:**
- Consumes: the Task 5 fields via `TodayView`; the `text-good` utility from Task 1.
- Produces: `Spark({ values: (number | null)[]; className?: string })`.

- [ ] **Step 1: Write the failing tests**

In `web/tests/strip.test.tsx`, replace line 25 (`expect(screen.getByText(/run 1\/2 · bike 1\/2/))…`) with:

```tsx
  expect(screen.getByText("run 1/2 · 60 of 120 TSS · 1.0 of 2.0 h")).toBeInTheDocument();
  expect(screen.getByText("bike 1/2 · 60 of 180 TSS · 1.5 of 4.0 h")).toBeInTheDocument();
```

Append:

```tsx
test("readiness leads with training readiness and falls back to sleep score", () => {
  const { unmount } = renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("training readiness")).toBeInTheDocument();
  expect(screen.getByText("77")).toBeInTheDocument();
  unmount();
  const t = todayFull();
  t.readiness = { ...t.readiness!, training_readiness: null };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("sleep score")).toBeInTheDocument();
  expect(screen.getAllByText("81")).toHaveLength(2); // headline and the sleep row
});

test("a trend row says how today compares, in words and colour", () => {
  const t = todayFull();
  t.readiness!.trends.hrv = { ...t.readiness!.trends.hrv, now: 50, band: "below", better: false };
  renderWith(<Strip today={t} />);
  const row = screen.getByText(/↓ 8 vs 28-day avg · low/);
  expect(row).toHaveClass("text-warn");
  expect(screen.getByText(/↓ 2 vs 28-day avg/)).toHaveClass("text-good"); // RHR 48 vs 50, lower is better
});

test("the load line names the TSB zone and flags ramp and ACWR", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, ramp_7d: 9.2, ramp_caution: true, acwr: 1.45, acwr_flag: "high" };
  renderWith(<Strip today={t} />);
  expect(screen.getByText(/TSB -4\.9 · neutral/)).toBeInTheDocument();
  expect(screen.getByText("ramp +9.2/wk fast")).toHaveClass("text-warn");
  expect(screen.getByText("ACWR 1.45 high")).toHaveClass("text-warn");
});

test("the readiness card copes with no trends and no load", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, trends: {}, tsb: null, tsb_zone: null, ramp_7d: null, acwr: null, acwr_flag: null };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("77")).toBeInTheDocument();
  expect(screen.queryByText(/vs 28-day avg/)).not.toBeInTheDocument();
  expect(screen.queryByText(/ramp|ACWR/)).not.toBeInTheDocument();
});

test("a completed session shows intensity, HR, power and percent of planned", () => {
  const t = todayFull();
  t.session!.workouts[0] = {
    ...t.session!.workouts[0],
    completed: true,
    actual_duration_sec: 3780,
    actual_tss: 57,
    actual_if: 0.82,
    avg_hr: 148,
    avg_power: 212,
    normalized_power: 225,
  };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("IF 0.82 · 148 bpm · 212 W (NP 225)")).toBeInTheDocument();
  expect(screen.getByText("105% of planned time · 95% of planned TSS")).toBeInTheDocument();
});

test("the week shows sessions done so far, hidden before the first session", () => {
  const { unmount } = renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("2 of 3 so far")).toBeInTheDocument();
  unmount();
  const t = todayFull();
  t.week = { ...t.week!, planned_to_date: 0, completed_to_date: 0 };
  renderWith(<Strip today={t} />);
  expect(screen.queryByText(/so far/)).not.toBeInTheDocument();
});

test("skeletons pulse only when motion is allowed", () => {
  renderWith(<Strip today={undefined} />);
  expect(screen.getAllByTestId("card-skeleton")[0]).toHaveClass("motion-safe:animate-pulse");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- tests/strip.test.tsx`
Expected: the new tests and the changed line 25 FAIL; the skeleton test PASSES (from Task 1); lines 16–24 still PASS.

- [ ] **Step 3: Write `Spark.tsx`**

```tsx
/** A 14-day line for a card row. Decorative: the row's text carries the meaning. Gaps break the line. */
export default function Spark({ values, className = "" }: { values: (number | null)[]; className?: string }) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const lo = Math.min(...nums);
  const span = Math.max(...nums) - lo || 1;
  const step = 100 / Math.max(values.length - 1, 1);
  const runs: string[][] = [[]];
  values.forEach((v, i) => {
    const run = runs[runs.length - 1];
    if (v == null) {
      if (run.length) runs.push([]);
      return;
    }
    run.push(`${(i * step).toFixed(1)},${(26 - ((v - lo) / span) * 22).toFixed(1)}`);
  });
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true" className={className}>
      {runs
        .filter((r) => r.length > 1)
        .map((r, i) => (
          <polyline key={i} points={r.join(" ")} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        ))}
    </svg>
  );
}
```

- [ ] **Step 4: Rewrite `ReadinessCard.tsx`**

```tsx
import type { TodayView } from "../../api/queries";
import { day, n } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";
import Spark from "./Spark";

type Readiness = NonNullable<TodayView["readiness"]>;
type Trend = Readiness["trends"][string];

const ROWS: { key: string; label: string; digits: number; unit: string }[] = [
  { key: "hrv", label: "HRV", digits: 0, unit: " ms" },
  { key: "resting_hr", label: "RHR", digits: 0, unit: " bpm" },
  { key: "sleep_score", label: "Sleep", digits: 0, unit: "" },
  { key: "sleep_hours", label: "Slept", digits: 1, unit: " h" },
];

function TrendRow({ label, t, digits, unit }: { label: string; t: Trend; digits: number; unit: string }) {
  const delta = t.avg_28d == null ? null : t.now - t.avg_28d;
  const word = t.band === "below" ? " · low" : t.band === "above" ? " · high" : "";
  const tone = t.better == null ? "text-ink-2" : t.better ? "text-good" : "text-warn";
  return (
    <div className="flex items-center gap-2 tabular-nums">
      <span className="w-12 text-ink-2">{label}</span>
      <span className="w-14 font-medium">
        {n(t.now, digits)}
        {unit}
      </span>
      <Spark values={t.spark} className="h-4 w-14 shrink-0 text-ink-2" />
      {delta != null && (
        <span className={`text-xs ${tone}`}>
          {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(digits)} vs 28-day avg{word}
        </span>
      )}
    </div>
  );
}

export default function ReadinessCard({ readiness }: { readiness: TodayView["readiness"] }) {
  if (!readiness) {
    return (
      <Card title="Readiness">
        <Empty>No Garmin data yet, sync first</Empty>
      </Card>
    );
  }
  const r = readiness;
  const lead = r.training_readiness ?? r.sleep_score;
  const leadLabel = r.training_readiness != null ? "training readiness" : "sleep score";
  return (
    <Card title={r.is_today ? "Readiness" : `Readiness from ${day(r.date)}`}>
      <div className="flex items-baseline gap-2">
        <Headline>{lead ?? "no data"}</Headline>
        <span className="text-ink-2">{leadLabel}</span>
      </div>
      {ROWS.map((row) => {
        const t = r.trends[row.key];
        return t ? <TrendRow key={row.key} label={row.label} t={t} digits={row.digits} unit={row.unit} /> : null;
      })}
      {r.tsb != null && (
        <div className="text-ink-2 tabular-nums">
          TSB {n(r.tsb, 1)}
          {r.tsb_zone ? ` · ${r.tsb_zone}` : ""}
          {r.ramp_7d != null && (
            <>
              {" · "}
              <span className={r.ramp_caution ? "text-warn" : ""}>
                ramp {r.ramp_7d >= 0 ? "+" : ""}
                {r.ramp_7d.toFixed(1)}/wk{r.ramp_caution ? " fast" : ""}
              </span>
            </>
          )}
          {r.acwr != null && (
            <>
              {" · "}
              <span className={r.acwr_flag ? "text-warn" : ""}>
                ACWR {r.acwr.toFixed(2)}
                {r.acwr_flag ? ` ${r.acwr_flag}` : ""}
              </span>
            </>
          )}
        </div>
      )}
      <div className="text-xs text-ink-2 tabular-nums">
        CTL / ATL / TSB {n(r.ctl, 1)} / {n(r.atl, 1)} / {n(r.tsb, 1)} · battery {r.body_battery ?? "no data"}
      </div>
    </Card>
  );
}
```

- [ ] **Step 5: `SessionCard.tsx` detail lines**

Add above the component:

```tsx
type Workout = NonNullable<TodayView["session"]>["workouts"][number];

const pct = (actual: number | null, planned: number | null) =>
  actual != null && planned ? Math.round((actual / planned) * 100) : null;

function detail(w: Workout): string[] {
  const effort = [
    w.actual_if != null ? `IF ${w.actual_if.toFixed(2)}` : null,
    w.avg_hr != null ? `${w.avg_hr} bpm` : null,
    w.avg_power != null ? `${w.avg_power} W${w.normalized_power != null ? ` (NP ${w.normalized_power})` : ""}` : null,
  ].filter(Boolean);
  const time = pct(w.actual_duration_sec, w.planned_duration_sec);
  const tss = pct(w.actual_tss, w.planned_tss);
  const vsPlan = [time != null ? `${time}% of planned time` : null, tss != null ? `${tss}% of planned TSS` : null].filter(Boolean);
  return [effort.join(" · "), vsPlan.join(" · ")].filter(Boolean);
}
```

Inside the `<li>`, after the sport/duration/TSS line:

```tsx
              {w.completed &&
                detail(w).map((line) => (
                  <div key={line} className="text-xs text-ink-2 tabular-nums">
                    {line}
                  </div>
                ))}
```

- [ ] **Step 6: `WeekCard.tsx` per-sport rows and so-far count**

Replace the joined sessions line (`{week.sessions.map(...).join(" · ")}`) with:

```tsx
      <ul className="space-y-0.5 text-ink-2 tabular-nums">
        {week.sessions.map((s) => (
          <li key={s.sport}>
            {`${s.sport} ${s.completed}/${s.planned} · ${n(s.actual_tss)} of ${n(s.planned_tss)} TSS · ${n(s.actual_hours, 1)} of ${hours(s.planned_hours)}`}
          </li>
        ))}
      </ul>
      {week.planned_to_date > 0 && (
        <div className="text-xs text-ink-2">
          {week.completed_to_date} of {week.planned_to_date} so far
        </div>
      )}
```

(`n(x, 1)` gives `1.0` and `hours` gives `2.0 h`, so a row reads `run 1/2 · 60 of 120 TSS · 1.0 of 2.0 h`.)

- [ ] **Step 7: Run the web suite, lint and build**

Run: `npm --prefix web run test && npm --prefix web run lint && npm --prefix web run build`
Expected: all PASS. `strip.test.tsx:16–24` still pass: "81" is the sleep row's own text, `7.5 h` the slept row, and the CTL/ATL/TSB line is unchanged apart from the appended battery.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/today web/tests/strip.test.tsx
git commit -m "feat(web): readiness trends with sparklines, load line, session effort, per-sport week"
```

---

### Task 7: Definition of done and manual pass

**Files:** none changed unless a check fails.

- [ ] **Step 1: Full checks, in Brian's order**

Run:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build
```

Expected: all green. Fix any failure in the task that owns the code and amend nothing already committed; add a `fix:` commit.

- [ ] **Step 2: Manual pass (Brian, or the executor with the `run` skill)**

`uv run tri-web serve`, then check:
- Light and dark mode (System Settings → Appearance): cards separate from the page, warn and good text is readable.
- 375 px wide (browser dev tools): no horizontal scroll, the cards stack, and the trend rows wrap cleanly.
- Reduce motion on (macOS Accessibility → Display): the skeletons and the avatar dot don't pulse.
- Tab from the address bar: the first stop is "Skip to main content", and Enter moves focus to main.
- Ask the coach for a two-item list: it renders as a list, and VoiceOver reads the reply once when it finishes.

- [ ] **Step 3: Record the result**

Add one line per check (pass/fail and a note) to the PR description or hand-off message. Don't push; ask Brian first.
