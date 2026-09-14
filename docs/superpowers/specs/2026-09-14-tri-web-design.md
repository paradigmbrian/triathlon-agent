# tri-web — The Athlete's Web UI, sub-project 1: foundation, Today, coach chat (package `tri_web`, app `web/`)

**Date:** 2026-09-14
**Status:** Implemented (plans 01 to 03, 2026-09-14)
**Purpose:** A local web UI over the existing agents. This sub-project builds the server that hosts the coach graph behind HTTP, the React shell, the Today page with its strip of today's numbers, the coach chat with streaming and the review gate (approve, reject, edit), and the operational buttons (sync now, weekly check-in, coach memory, reset). Progress charts, nutrition management and lab management are sub-projects 2 to 4 (§14) and get their own specs.

Companion specs: `tri-coach` (2026-09-11) owns the graph, the review gate and the memory this UI drives; `tri-planning` (2026-09-07) and `tri-nutrition` (2026-09-10) own the change models the gate editor renders; `tri-wellness` (2026-09-10) owns the labs summary the Today strip shows.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Audience | One athlete, one machine. The server binds to localhost, no auth, no accounts. | Chosen 2026-09-14. Identity plumbing is a separate project; nothing here should make it harder. |
| Bridge | A Python API package `tri-web` (FastAPI, uvicorn, SSE) that opens the coach graph the same way the CLI does, plus a React app in `web/`. Not LangGraph Server, not Streamlit. | The server shares the CLI's `coach` thread, Postgres checkpointer and store, so the terminal and the browser see one conversation and one memory. LangGraph Server would own its own persistence and split the athlete's state in two. |
| Home screen | Chat-centered with a Today strip on top (layout B, chosen 2026-09-14). The conversation fills the page; four compact cards above it: session, readiness, fuel, week. | The daily loop is "open it, read today, talk to the coach". |
| Edit in the gate | Per-change fields generated from the change models' JSON schema, with a YAML editor as the fallback (option B, chosen 2026-09-14). | Nicer than raw YAML for the common edit (remove a change, move a date, change a number), and schema-driven so it does not drift when the models grow. |
| Concurrency | One graph, one thread, one lock. A second turn, check-in or reset while one runs is refused with 409. A turn runs to completion after the browser disconnects. | Checkpoints must never be left half-written by a closed tab; the CLI and the browser may both be open. |
| Streaming | Server-sent events over a `POST` response, read with `fetch` and a stream reader. Event names and payloads mirror the REPL's `TurnPrinter`. | The REPL already decides what an athlete should see; the UI renders the same events instead of reinterpreting the graph. |
| Frontend | React 19, Vite, TypeScript, Tailwind, TanStack Query, React Router. Vitest for units, one Playwright smoke test. | Brian's stack. Charts arrive in sub-project 2. |
| Serving | `uv run tri-web serve [--no-live] [--port 8321]`. When `web/dist` exists it is served from the same port; in development `npm run dev` proxies `/api` to it. | One process to start in the morning; two during frontend work. |
| Learning goals | Streaming a LangGraph run over HTTP; recovering a paused interrupt from a state snapshot after a page reload; resuming with `Command(resume=...)` from a stateless request. | Chosen 2026-09-14. |

## 2. Feasibility, verified 2026-09-14

- Installed already (transitively): starlette 1.6.0, uvicorn 0.52.4, sse-starlette 3.4.11, httpx-sse 0.4.3, psycopg 3.3.5, pydantic 2.13.5. `fastapi` is not installed and is the one new server dependency. Node 22.16, npm 11.4.
- `tri_coach.cli._open_graph` (cli.py:63) is the whole assembly: `open_servers` → `open_checkpointer` → `tri_nutrition.store.open_store` → `make_deps` → `build_graph`. It is private and raises `typer.Exit`; §6.1 lifts it into a reusable context manager.
- `tri_coach.repl.run_turn(graph, payload, thread_id, out)` streams with `stream_mode=["messages","updates"], subgraphs=True` and feeds `TurnPrinter.on_event(namespace, mode, data)`, which already classifies every event an athlete sees (token, tool call, tool result, consultation result, apply report, interrupt). The server replaces the printer with an emitter (§6.3) and keeps `run_turn`'s error handling.
- `paused_review(snap)` (repl.py:261) recovers the interrupt payload from `graph.aget_state`, and `snap.values["pending"]` holds a change set carried over from a partial apply. Both are what `GET /api/coach/thread` needs after a reload.
- Resume is `Command(resume=ReviewDecision.model_dump(mode="json", exclude_none=True))` (repl.py:292). `ReviewDecision.proposals` carries the full edited list on `edit`.
- `proposals_to_yaml` / `proposals_from_yaml(text, originals)` (repl.py:204, :209) are the YAML round trip; `Proposal.model_validate` re-types `changes` by domain, so a JSON edit from the schema form validates through the same path.
- `Proposal`, `CalendarChange` (`tri_planning.planning.models`) and `NutritionChange` (`tri_nutrition.nutrition.models`) are Pydantic v2 models; `model_json_schema()` gives the form generator its field list, types, enums and nesting (`PlannedSession` under `CalendarChange.workout`; `payload: dict` on both).
- `load_context(conn, store, today, pending, labs_enabled=...)` (context.py:92) already assembles phase, goal, plan, this week's target, actual TSS and hours, nutrition profile, targets_through, recent days and the labs summary. The Today strip adds today's workouts (`tri_core.db.repo.list_workouts_between`), today's target (`tri_nutrition.repo.list_targets`), today's fuel plan (`list_fuel_plans`) and today's `daily_metrics` row.
- `run_checkin(graph, has_plan=, has_profile=, yes=False, out=, thread_id=)` (checkin.py:31) returns 0, 1, 2 or 3 and prints through `out`; with `yes=False` a pause leaves the interrupt on the thread where `GET /api/coach/thread` finds it. `run_sync(settings, log=)` (tri_core.sync.runner:97) returns a `SyncReport` with per-source results.
- `tri_coach.memory` exposes `get_entries`, `forget_entry(store, id) -> bool`, `active`, `render`; `reset_thread(settings, forget_memory=)` (cli.py:314) deletes the thread.
- `tri_coach.testing.make_test_deps(nocommit, coach=, planning=, nutrition=, analyst=, ...)` builds deps over fake chat models and the test database, so the API can be tested end to end with FastAPI's test client and no Anthropic call.

## 3. System overview

```
 browser (web/, Vite + React) ──── fetch /api/* ────► tri-web (FastAPI on :8321)
   Today strip  ◄── GET /api/today                     │ holds for the process lifetime:
   chat         ◄── SSE from POST /api/coach/turns      │   Servers (garmin, trainingpeaks MCP)
   gate         ──► POST /api/coach/review (SSE back)   │   AsyncPostgresSaver, AsyncPostgresStore
   jobs         ◄── SSE from GET /api/jobs/{id}/events  │   compiled coach graph, thread "coach"
   settings     ◄── /api/coach/memory, /api/coach/reset │   asyncio.Lock  (one run at a time)
                                                        ▼
                                              Postgres (tables, checkpoints, store)
 tri-coach chat (terminal) ─────────────────── same thread, same store ───────────────┘
```

## 4. Package layout

```
packages/tri-web/
  pyproject.toml                 tri-web; depends on tri-coach, fastapi, uvicorn, sse-starlette;
                                 script tri-web
  src/tri_web/
    __init__.py
    cli.py                       `tri-web serve [--no-live] [--host] [--port]`
    config.py                    WebSettings(CoachSettings): tri_web_host, tri_web_port, tri_web_dist
    app.py                       create_app(runtime) -> FastAPI; lifespan opens/closes the runtime;
                                 mounts web/dist when present
    runtime.py                   Runtime: settings, graph, store, servers, connect(), lock, jobs;
                                 open_runtime(settings, no_live) async context manager (§6.1)
    events.py                    TurnEmitter: TurnPrinter's classification as typed SSE events (§6.3)
    thread.py                    thread_snapshot(graph, cfg) -> ThreadView: messages + paused review (§6.4)
    today.py                     build_today(runtime) -> TodayView (§6.2)
    review.py                    schema(), to_yaml(), from_yaml(), validate(proposals) (§6.5)
    jobs.py                      Job registry: start(kind, coro) -> id; per-job event queue (§6.6)
    routes/
      today.py  coach.py  review.py  jobs.py  memory.py  system.py
    schemas.py                   Pydantic response models for every route (the frontend types are
                                 generated from the OpenAPI document)
  tests/
    conftest.py                  fake-model runtime over the test database; TestClient
    test_runtime.py  test_events.py  test_thread.py  test_today.py  test_review.py
    test_jobs.py  test_routes_coach.py  test_routes_memory.py  test_cli.py

web/
  package.json  vite.config.ts  tsconfig.json  tailwind.config.ts  index.html
  src/
    main.tsx  App.tsx  router.tsx
    api/  client.ts (fetch + SSE reader)  types.ts (generated from /openapi.json)  queries.ts
    pages/  Today.tsx  Settings.tsx  Placeholder.tsx (Progress, Nutrition, Labs)
    components/  Shell.tsx  Rail.tsx  Header.tsx
                 today/  Strip.tsx  SessionCard.tsx  ReadinessCard.tsx  FuelCard.tsx  WeekCard.tsx
                 chat/   Chat.tsx  Message.tsx  Activity.tsx  Composer.tsx  useTurnStream.ts
                 gate/   Gate.tsx  ProposalCard.tsx  ChangeRow.tsx  SchemaForm.tsx  YamlEditor.tsx
                 jobs/   JobButton.tsx  useJobStream.ts
                 settings/  MemoryTable.tsx  ResetButton.tsx  Readiness.tsx
  tests/  sse.test.ts  schemaForm.test.ts  e2e/smoke.spec.ts (Playwright, stub API)
```

As built: `tailwind.config.ts` does not exist (Tailwind 4 reads its tokens from `web/src/index.css`), and `routes/review.py` is folded into `routes/coach.py` (the routes are `today.py`, `coach.py`, `jobs.py`, `memory.py`, `system.py`).

`tri-web` joins the workspace members in the root `pyproject.toml`. `web/` is an npm project with its own lockfile; it is not a uv member. The root README gets a `tri-web` row and a Run line.

## 5. Interfaces

### 5.1 Runtime (server side)

```python
@dataclass
class Runtime:
    settings: WebSettings
    graph: Any                 # compiled coach graph
    store: BaseStore
    servers: Servers
    connect: Callable[[], ContextManager[Conn]]
    lock: asyncio.Lock         # coach turns, review, check-in, reset
    running: str | None        # "turn" | "review" | "checkin" | "reset" | None, for 409 bodies
    jobs: Jobs
    thread_id: str = "coach"

@asynccontextmanager
async def open_runtime(settings: WebSettings, *, no_live: bool, log) -> AsyncIterator[Runtime]
```

`open_runtime` is the CLI's `_open_graph` without Typer: it calls a lifted `tri_coach.cli.ready(settings) -> str | None` (message or None; `_ready` becomes a thin wrapper that prints and exits) and raises `RuntimeError(message)` when not ready, so `tri-web serve` prints the same hints the CLI does and exits 2.

### 5.2 HTTP routes (all under `/api`, JSON unless noted)

| Route | Body | Returns |
|---|---|---|
| `GET /today` | | `TodayView` (§6.2) |
| `GET /coach/thread` | | `ThreadView`: `messages: list[UiMessage]`, `paused: ReviewPayload \| null`, `held: ReviewPayload \| null`, `stuck: bool`, `running: str \| null` |
| `POST /coach/turns` | `{text: str}` | SSE stream of `TurnEvent` (§6.3); 409 `{running}` when busy |
| `POST /coach/review` | `ReviewDecision` JSON | SSE stream of `TurnEvent`; 409 when busy; 409 `{reason: "no_review"}` when nothing is paused |
| `GET /coach/review/schema` | | `{proposal: JSONSchema, planning_change: JSONSchema, nutrition_change: JSONSchema}` from `model_json_schema()` |
| `POST /coach/review/validate` | `{proposals: list[dict]}` or `{yaml: str}` | `{ok: true, proposals: [...]}` or `{ok: false, errors: [{loc, msg}]}` |
| `GET /coach/review/yaml` | | `{yaml: str}` of the paused proposals |
| `GET /coach/memory` | | `{entries: list[MemoryEntry], active_ids: list[str]}` |
| `DELETE /coach/memory/{id}` | | 204, or 404 |
| `POST /coach/reset` | `{confirm: true, forget_memory: bool}` | 204; 409 when busy |
| `POST /jobs/sync` | `{since?: date, full?: bool}` | `{id}` |
| `POST /jobs/checkin` | `{sync: bool}` | `{id}`; 409 when busy |
| `GET /jobs/{id}` | | `{id, kind, status: queued\|running\|done\|failed, result?, error?}` |
| `GET /jobs/{id}/events` | | SSE: `line {text}` … then `done {result}` or `error {message}`; replays lines already emitted, so a reload does not lose progress |
| `GET /system/status` | | `{live: bool, tools: list[str], ready: {api_key, checkpointer, store}, thread: "coach", running}` |

The OpenAPI document at `/openapi.json` is the source for `web/src/api/types.ts` (`openapi-typescript` at build time, committed).

### 5.3 SSE event schema (`TurnEvent`)

Each event is `event: <name>` with a JSON `data` line.

| name | data | from |
|---|---|---|
| `token` | `{where: "coach" \| "planning" \| "nutrition" \| "analyst", text}` | `messages` mode, node `model` |
| `tool_call` | `{where, name, args}` | `AIMessage.tool_calls` on node `model` |
| `tool_result` | `{where, name, chars}` | `ToolMessage` on node `tools` |
| `consult` | `{domain: "planning" \| "nutrition", text}` | consultation result on the root `planning`/`nutrition` node |
| `report` | `{text}` | `AIMessage`/`HumanMessage` on root `apply`/`review`/`nutrition` |
| `interrupt` | `ReviewPayload = {narration, proposals: list[Proposal JSON]}` | `__interrupt__` |
| `error` | `{message}` | `run_turn`'s caught exceptions |
| `done` | `{final_text, paused: bool}` | end of the stream |

`where` is `TurnPrinter`'s `_tag` plus `"coach"` for the coach's own voice, so the UI can style consultations and the analyst without knowing namespaces.

### 5.4 UI message model (`UiMessage`, from a snapshot)

`{id, role: "user" \| "assistant" \| "activity" \| "consult" \| "report", text, where?, name?, args?, chars?}`. Built by `thread.py` from the checkpoint's root `messages` with the same classification as §5.3, so history and live stream render through one component set. The coach's own AI messages become `assistant`; tool calls and tool results become collapsed `activity` rows; consultation `ToolMessage`s become `consult`; apply lines become `report`. System and brief-carrying messages are skipped.

## 6. Behaviour

### 6.1 Startup and lifetime

`tri-web serve` builds `WebSettings`, opens the runtime inside FastAPI's lifespan, and serves. Startup takes the same 10 to 20 s as the CLI while the MCP servers launch; `--no-live` skips them and `GET /system/status` reports `live: false`. Shutdown closes the exit stack so the MCP processes end with the server. `today()` is computed per request in the settings' local date, never cached across midnight.

### 6.2 Today

`build_today` opens one connection, calls `load_context` with the current pending change set, and adds today's rows. `TodayView`:

- `header`: `today`, `phase`, `goal` (event name, date, days to go), `week` (start, number, of), `last_sync` per source from `sync_state`.
- `session`: today's workouts from `workouts` (planned and completed columns, sport, title, planned TSS), or `null`, and the fuel plan for the first planned session if `fuel_plans` has one.
- `readiness`: today's `daily_metrics` row (sleep score, sleep hours, HRV, resting HR, body battery, training readiness, CTL, ATL, TSB) or the latest row with its date when today's is absent.
- `fuel`: today's `nutrition_targets` row (day type, total kcal, carbs, protein, fat, fluid) or `null`; `targets_through`.
- `week`: this week's `PlanWeekRow` target hours and TSS, `actual_hours`, `actual_tss`, sessions planned and completed by sport.
- `labs`: the context's `LabSummary` or `null`; `labs_enabled`.
- `pending`: `ReviewPayload | null` (paused or held), so the strip can show the "1 review pending" badge without a second call.

Every card renders its `null` state as a short sentence ("No session planned", "No targets yet, ask the coach"), never an empty box. The strip refetches after each `done` event, each job completion, and on window focus.

### 6.3 A turn

`POST /coach/turns` acquires the lock (409 with `{running}` if held), sets `running = "turn"`, and returns a streaming response. The producer task runs `run_turn(graph, {"messages": [HumanMessage(text)]}, thread_id, emitter.out)` with a `TurnEmitter` whose `on_event` is `TurnPrinter.on_event` re-expressed as events pushed to an `asyncio.Queue`; `run_turn`'s exception handling stays, and `emitter.error` becomes an `error` event. The response reads the queue until `done`. If the client disconnects, the response ends but the producer task continues; the lock releases only when the run finishes. `done.paused` is true when the run ended at the review interrupt.

The `TurnEmitter` is built by refactoring `TurnPrinter` into a classifier that yields `(kind, payload)` tuples and a printer that formats them, so the REPL and the server share one classification and `test_repl.py` keeps passing. Every event kind in §5.3 has a unit test that feeds a recorded `(namespace, mode, data)` and asserts the event.

### 6.4 Thread state and reload

`GET /coach/thread` calls `graph.aget_state(cfg)`, maps `values["messages"]` to `UiMessage`s, and sets `paused` from `paused_review(snap)` and `held` from `values["pending"]` when the graph is not paused (a change set carried from a partial apply; the CLI's `/pending`). When `snap.next` is non-empty and neither is set, the thread stopped mid-run; `running` is `null` and the response carries `stuck: true`, and the composer shows "the last run stopped early, send any message to continue", matching the check-in's hint.

On load the page fetches the thread, renders the history, and renders the gate for `paused` with its buttons. A `held` set renders as the same card without buttons and with the CLI's line, "held from an earlier apply; ask the coach to re-propose it", since only a paused interrupt can be resumed; `POST /coach/review` answers 409 `{reason: "no_review"}` when nothing is paused. Both branches have a test.

### 6.5 The review gate

The gate card shows the narration, then one card per proposal: id, domain tag, summary, and each change as a row with its `op`, a one-line description (planning: date, sport, duration, description, new date for `move`; nutrition: day, target key, payload keys and values), its `reason`, and `athlete_requested` when set. Violations render under the proposal in red. A proposal that carries a `question` instead of changes renders the question. Below: a note field and three buttons.

- **Approve** posts `{action: "approve"}`.
- **Reject** posts `{action: "reject", note}`; the note is optional.
- **Edit** switches every proposal card into the schema form. `SchemaForm` takes the JSON schema from `GET /coach/review/schema` and a proposal, and renders: strings and numbers as inputs, `date` formats as date inputs, enums as selects, booleans as checkboxes, nested objects (`workout: PlannedSession`) indented, `dict[str, Any]` payloads as editable key-value rows, and lists of changes as rows with a remove button. `id`, `domain` and `question` are read-only; `summary` and `overrides` are editable. Each proposal has a remove button (removing all proposals is refused client-side with "reject instead"). "Edit as YAML" opens `YamlEditor` prefilled from `GET /coach/review/yaml`; both editors call `POST /coach/review/validate` on change with a short debounce and show `errors` inline by `loc`. **Send edited** posts `{action: "edit", proposals}` with the validated list. Cancel restores the card.

Validation on the server: JSON goes through `Proposal.model_validate` per item; YAML goes through `proposals_from_yaml(text, originals)` against the paused proposals; `ValidationError`s map to `{loc, msg}`. The same function guards `POST /coach/review`, so an edit that bypasses the client's validate call still gets a 422 with the same errors.

Approval streams the rest of the run (apply reports as `report` events, possibly a second `interrupt` for the nutrition follow-on, which renders as a new gate) and ends with `done`.

### 6.6 Jobs: sync and check-in

`Jobs` holds an in-memory registry: `start(kind, coro_factory) -> id` creates a job with an event list and a queue, and runs the coroutine as a task. `GET /jobs/{id}/events` replays recorded events then follows the queue. Jobs die with the process; that is acceptable for one athlete on one machine.

- **sync** runs `run_sync(settings, log=job.line)` and finishes with `{ok, results: [{source, status, rows, error}]}`. It does not take the coach lock; the graph reads the database per turn.
- **checkin** takes the coach lock for its whole duration (409 if held), optionally runs sync first, derives `has_plan` from `derive_phase` and `has_profile` from `store.get_profile` as the CLI does, then runs `run_checkin(..., yes=False, out=job.line)`. The exit code becomes `result.code`; 3 means a review is now paused, and the page refetches the thread and shows the gate. 2 renders the "no plan and no profile" line as the result.

Header buttons show the job's latest line while running and its result for a few seconds after; the job's event stream also feeds a small transcript panel the athlete can expand.

### 6.7 Settings

Memory: a table of entries (kind, text, created, until, active) with a forget button per row that calls `DELETE /coach/memory/{id}` and refetches. Reset: a button behind a confirm dialog with a "forget memory too" checkbox, posting `POST /coach/reset`. Readiness: `GET /system/status` rendered as three checks and the bound tool list.

### 6.8 Errors

- Model, MCP and unexpected errors inside a run arrive as an `error` event; the chat shows a red bubble with the message and a retry button that resends the same text. The composer keeps the text.
- A 409 disables the composer and gate buttons with "a {running} is running"; the page polls `GET /coach/thread` every 2 s until `running` is null, then refetches.
- A lost stream (network error before `done`) shows "connection lost, reloading the conversation" and refetches the thread; since the run continues server-side, the thread catches up.
- Startup readiness failures print the CLI's hints and exit 2. A `web/dist` that is missing is not an error: the server logs "frontend not built, API only".
- Route errors return `{detail}` with the message only, never a traceback; uvicorn's log keeps the traceback.

## 7. Frontend

Shell: a left rail with Today, Progress, Nutrition, Labs, Settings; Progress, Nutrition and Labs route to a placeholder page naming the sub-project that fills it. Header: date, phase and week, race countdown, last sync, then the Sync now and Weekly check-in job buttons and the pending-review badge.

Today page: the four-card strip (`SessionCard`, `ReadinessCard`, `FuelCard`, `WeekCard`, the week card with a progress bar of hours), then `Chat`, which owns the history from `useQuery(thread)`, the live stream from `useTurnStream`, the gate from `paused`/`held` or the latest `interrupt` event, and the `Composer`. Tokens append to the open assistant bubble by `where`; a change of `where` opens a new bubble with a tag. `Activity` rows are collapsed by default and expand to show args or the result size. The page scrolls to the newest message on each event unless the athlete has scrolled up.

State: TanStack Query for `today`, `thread`, `memory`, `status`, `schema`; the stream hook holds the in-flight turn and invalidates `thread` and `today` on `done`. No global store.

Styling: Tailwind with a small token set (surface, text, accent, planning tag, nutrition tag, warning) in light and dark; the frontend-design skill is used at implementation time for the visual pass. The layout must work at 400 px wide (the strip stacks, the rail becomes a bottom bar), since "reachable from my phone" is a plausible next step even though it is out of scope here.

## 8. Testing

Server (`packages/tri-web/tests`, pytest, skips when Postgres is down like every other package):

- `test_runtime.py`: `open_runtime` with `no_live=True` and fake models yields a graph on thread `coach`; a readiness failure raises with the CLI's hint text.
- `test_events.py`: each `TurnEvent` kind from a recorded `(namespace, mode, data)`; the REPL printer still prints the same text for the same input (`test_repl.py` unchanged).
- `test_thread.py`: a checkpoint with user, coach, tool and consultation messages maps to the expected `UiMessage` list; a paused review and a held set are recovered.
- `test_today.py`: `TodayView` with and without a plan, targets, metrics, labs; the pending badge.
- `test_review.py`: schema shapes; JSON and YAML validate paths, including a wrong domain, a bad date, and an unknown op; the "send edited" path posts typed proposals and resumes.
- `test_jobs.py`: replay then follow; a failing job ends with `error`.
- `test_routes_coach.py`: a turn over fake models streams `token`, `done`; a scripted coach that proposes streams `interrupt` and pauses; approve resumes and streams `report`; a second turn while one runs is 409; a disconnect mid-stream lets the run finish and the thread shows the assistant message.
- `test_routes_memory.py`, `test_cli.py`: memory list and forget; `serve --help`, readiness exit 2.

Frontend (`web/tests`): Vitest for the SSE reader (event framing, multi-line data, error mid-stream) and `SchemaForm` (renders each field type from a fixture schema, emits a proposal JSON, remove buttons). One Playwright smoke test against a stub API: load Today, send a message, see tokens, see a gate, approve, see a report.

Definition of done for the sub-project: `uv run pytest`, `uv run ruff check . && uv run ruff format --check . && uv run mypy`, `npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`, and a manual session: `tri-web serve`, ask the coach a question, trigger a change, edit one field, approve, watch the strip update.

## 9. Out of scope for this sub-project

Progress charts and the plan calendar (sub-project 2); nutrition targets, fuel log, profile and product forms, push today (3); lab panels, reports and PDF ingest (4). Authentication, hosting, multi-athlete. Editing the training goal or plan outside the coach's gate. Per-agent chats (wellness, analyst, planning, nutrition) in the UI: the coach is the front door, and the CLIs keep those.

## 10. Roadmap of sub-projects

| # | Spec | Adds |
|---|---|---|
| 1 | this | `tri-web` server, shell, Today, coach chat, gate, jobs, memory, reset |
| 2 | tri-web progress | fitness curve (CTL/ATL/TSB with race day), planned vs actual hours and TSS per week by sport, recovery trend (sleep, HRV, RHR, readiness), week calendar of planned vs completed sessions |
| 3 | tri-web nutrition | targets and fuel plans by day, fuel log entry, profile and product library forms, push today to Garmin |
| 4 | tri-web labs | panel list, report view with findings against functional ranges, PDF upload with the ingest review interrupt |

Each later sub-project adds routes under `/api` and a page under `web/src/pages`, and reuses the runtime, the query client, the SSE reader and the shell from this one.
