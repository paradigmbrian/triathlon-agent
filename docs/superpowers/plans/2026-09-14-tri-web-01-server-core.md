# tri-web Plan 1 of 3: Server Core (runtime, event stream, thread, review, coach routes, `serve`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `tri-web` package whose FastAPI server opens the coach graph the way the CLI does, streams a coach turn as server-sent events over `POST /api/coach/turns`, recovers a paused review from the checkpoint on `GET /api/coach/thread`, resumes it through `POST /api/coach/review` (approve, reject, edit with server-side validation), reports `GET /api/system/status`, and starts with `uv run tri-web serve [--no-live] [--port 8321]`.

**Architecture:** `tri_coach.repl.TurnPrinter` is split into a `TurnClassifier` that turns raw LangGraph stream events into `(kind, payload)` tuples and a printer that formats them, so the REPL and the server share one classification. `tri_web.runtime.open_runtime` is `tri_coach.cli._open_graph` without Typer; a `Runtime` dataclass holds the graph, store, servers, one `asyncio.Lock` and the `running` label. `tri_web.events.start_turn` acquires the lock, runs `run_turn` in a background task with a `TurnEmitter` (a `TurnPrinter` subclass whose `print_event` pushes typed events onto an `asyncio.Queue`) and releases the lock when the run ends, so a client disconnect never cuts a checkpoint short. Routes are thin: they read the queue into a `text/event-stream` response. `tri_web.thread` maps the checkpoint's root messages to `UiMessage`s with the same rules. `tri_web.review` wraps `Proposal.model_validate` and `proposals_from_yaml` into `{ok, proposals, errors}`.

**Tech Stack:** Python 3.12, FastAPI 0.141.1 (the one new dependency; starlette 1.6.0, uvicorn 0.52.4 and httpx 0.28.1 are already installed), langgraph 1.2.11, pydantic 2.13.5, typer 0.27.2, pytest with `pytest-asyncio` in auto mode, `httpx.ASGITransport` for route tests, `tri_core.testing.ScriptedChatModel` and the rolled-back `db` fixture.

**Spec:** `docs/superpowers/specs/2026-09-14-tri-web-design.md` (§1 decisions, §2 feasibility, §4 layout, §5.1 runtime, §5.2 routes `thread`, `turns`, `review`, `review/schema`, `review/validate`, `review/yaml`, `system/status`, §5.3 events, §5.4 `UiMessage`, §6.1 startup, §6.3 a turn, §6.4 reload, §6.5 the gate's server side, §6.8 errors, §8 server tests). The spec lives on branch `docs/tri-web-spec` (3a8a0a0) with this plan; merge or cherry-pick that branch's `docs/` into the feature branch first so the spec travels with the code. Plans 2 (Today, jobs, memory, reset, static serving) and 3 (the React app) follow.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-web-01 -b feat/tri-web-01 main`, copy `.env`, `uv sync`. Other Claude sessions share the main checkout. Baseline before Task 1 on `main` 373c558: `824 passed, 6 skipped` (the six are `--live`).
- One new dependency: `fastapi` (resolves to 0.141.1 against the installed starlette 1.6.0; verified with `uv pip install --dry-run fastapi`). No `sse-starlette` (see decisions). No other new Python dependency.
- Edits outside `packages/tri-web` are limited to: `pyproject.toml` (workspace membership, ruff `known-first-party`, mypy `files`), `packages/tri-coach/src/tri_coach/cli.py` (lift `ready`), `packages/tri-coach/src/tri_coach/repl.py` (the classifier split, `text_of`, `run_turn(..., printer=)`), `packages/tri-coach/src/tri_coach/graph/nodes/apply.py` (one `name="apply"` argument), `packages/tri-coach/tests/test_cli.py` and `test_repl.py` (additive tests only), `README.md`. No edits under `tri-core`, `tri-analyze`, `tri-planning`, `tri-nutrition`, `tri-wellness`.
- `packages/tri-coach/tests/test_repl.py`'s existing assertions must keep passing unchanged: the printer's output is byte-identical before and after the split.
- The server binds `127.0.0.1` by default, no auth. Thread id is exactly `coach` (shared with the CLI). One lock guards turns, review, check-in and reset; a busy server answers `409 {"running": "<kind>"}`.
- Event names and payloads are exactly spec §5.3: `token {where, text}`, `tool_call {where, name, args}`, `tool_result {where, name, chars}`, `consult {domain, text}`, `report {text}`, `interrupt {narration, proposals}`, `error {message}`, `done {final_text, paused}`. `where` is one of `coach`, `planning`, `nutrition`, `analyst`.
- Route errors return `{"detail": <message>}` only, never a traceback.
- No migration. Tests write only through the rolled-back fixtures (`nocommit`, `db`). Route tests need no Anthropic key and no MCP server.
- Git commits are permitted (Brian's standing permission). Commit per task on the feature branch. End every commit message with the `Co-Authored-By:` and `Claude-Session:` trailer lines of the session executing the plan.
- Definition of done per task, in order: `uv run ruff format packages/tri-web packages/tri-coach`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. The only acceptable pytest warning is the pre-existing langsmith `ast.Str` DeprecationWarning.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, with kebab-case names (`readme.md` for READMEs).

### Facts verified while writing this plan (against `main` 373c558)

1. `tri_coach.cli._ready(settings) -> int | None` prints one of three messages (`ANTHROPIC_API_KEY is not set in .env`, `SETUP_HINT`, `STORE_SETUP_HINT`) and returns 2. `_open_graph(*, no_live)` yields `(graph, store, servers)` from `open_servers(stack, settings, no_live=, log=)`, `open_checkpointer(url)`, `S.open_store(url)`, `make_deps(settings, make_model(settings), servers)`, `build_graph(deps, saver, store)`. `make_deps` returns `CoachDeps` whose `.connect` is `lambda: core_connect(url)`.
2. `tri_coach.repl.TurnPrinter.on_event(namespace, mode, data)` handles `messages` (an `(AIMessageChunk | AIMessage, meta)` tuple at `langgraph_node == "model"`) and `updates` (`__interrupt__`, then per-node `messages`). `_tag(where, node)` is `where` for `planning`/`nutrition`, `analyst` for root `model`/`tools`, else `""`. For node `model` the guard `(where or tag)` is always true (root gives tag `analyst`), so every tool-call-free `AIMessage` at `model` closes the streamed line with `"\n"` and resets `_line_label`. `run_turn(graph, payload, thread_id, out, *, tags=None) -> TurnPrinter` catches `anthropic.RateLimitError`, `APIStatusError`, `APIConnectionError` and `Exception`, sets `printer.error` to a bracketed line and prints it.
3. A scripted coach turn (`ScriptedChatModel(script=[AIMessage(content="Hello athlete.")])`) over `build_graph(..., InMemorySaver(serde=make_serde()), mem_store)` streams, in order: `((), "updates", {"start": ...})`, two `(("coach:<id>",), "messages", (chunk, {"langgraph_node": "model"}))`, `(("coach:<id>",), "updates", {"model": ...})`, `((), "updates", {"coach": ...})`. The checkpoint's messages carry ids (`HumanMessage` a uuid, `AIMessage` `lc_run--...`). Probed 2026-09-14.
4. `paused_review(snap)` returns `dict(snap.tasks[0].interrupts[0].value)` when `snap.next == ("review",)`. The interrupt value is `{"narration": str, "proposals": [Proposal JSON]}` (`review.py:50`). `snap.values["pending"]` is a `ChangeSet` (Pydantic) after a partial apply. `run_checkin` treats `paused is None and held is None and snap.next` as "stopped mid-run".
5. Root messages on the thread: `HumanMessage` (the athlete; also `[review] ...`, `Review rejected: ...` from `review.py`, `[follow-on] ...` from `nutrition.py`), `AIMessage` from the coach sub-agent (text and/or `tool_calls`), `AIMessage("\n".join(lines))` from `apply.py:223` (the apply report, no name today), `ToolMessage`s named `ask_analyst`, `ask_wellness`, `remember`, `consult_planning`, `consult_nutrition`, `propose_changes`. Brief-carrying `HumanMessage`s exist only inside the sub-graphs, never at the root.
6. `Proposal.model_validate` re-types `changes` by `domain` (`models.py:33`). `proposals_to_yaml(list[Proposal]) -> str` keys by id; `proposals_from_yaml(text, originals)` merges each body over the original's dump and validates. `ReviewDecision(action, note, proposals)`; resume is `Command(resume=decision.model_dump(mode="json", exclude_none=True))` (`repl.py:292`).
7. `tri_coach.testing.make_test_deps(nocommit, *, coach, planning, nutrition, analyst, tp=None, today=MONDAY)` plus `build_graph(deps, InMemorySaver(serde=make_serde()), InMemoryStore())` is the no-network graph every `test_graph.py` case uses. `seed_active_plan(nocommit)`, `consult("planning", ...)`, `move_call()`, `propose("Move it.", ["p1"])` with `planning=[move_call(), AIMessage("ok")]` and `tp=FakeTp()` produce the interrupt; `Command(resume={"action": "approve"})` then applies and appends `planning: applied 1`.
8. `Servers` (`tri_coach.servers`) has `garmin_tools`, `tp_tools` (lists of `BaseTool`), `garmin`, `tp`. `Servers()` is the `--no-live` value.
9. `httpx.ASGITransport` runs the ASGI app to completion and returns the whole body; `receive()` blocks until the response completes once the request body is consumed, so a streaming route finishes normally under it. A disconnect cannot be simulated through it; the disconnect test drives `start_turn` directly.
10. `CoachSettings` extends `tri_core.config.Settings` (`.env`, `extra="ignore"`); `Settings().test_database_url` is the rolled-back test database. `checkpointer_ready(url)` and `store_ready(url)` are synchronous psycopg probes.
11. `packages/tri-coach/tests/conftest.py` provides `nocommit`, `mem_store`, `make_deps`; they are directory-local, so `packages/tri-web/tests/conftest.py` defines its own (Task 8).

### Decisions this plan makes where the spec is silent or its literal reading fails

- **No `sse-starlette`.** Events are framed by a twelve-line `format_sse` over Starlette's `StreamingResponse` (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`). The frontend reader (plan 3) is custom anyway, the framing is testable byte-for-byte, and `sse-starlette`'s process-wide shutdown event is a known nuisance across pytest event loops. `pyproject.toml` therefore lists `fastapi` and `uvicorn` only.
- **`create_app(runtime)` takes an open `Runtime`;** `tri-web serve` opens the runtime around `uvicorn.Server.serve()` instead of inside FastAPI's lifespan. Same lifetime, and tests build a `Runtime` over fakes without a lifespan. `create_app(None)` builds the app for `tri-web openapi` (the OpenAPI document needs no runtime).
- **The classifier keeps an internal `assistant` event** (`{where, text}`, a tool-call-free `AIMessage` at node `model`) so the printer can close its streamed line exactly as today. `TurnEmitter` drops it; it is not in §5.3.
- **`run_turn` gains `printer: TurnPrinter | None = None`.** `TurnEmitter` subclasses `TurnPrinter` and overrides `print_event`; `run_turn`'s error handling is untouched and its `out` is a no-op for the emitter. `printer.error` becomes the `error` event, stripped of its newlines and brackets.
- **The apply report `AIMessage` gets `name="apply"`** so the thread mapper can tell it from the coach's own text without parsing. `langchain-anthropic` does not send `name` on assistant messages; the REPL ignores it.
- **`_text_of` becomes public `text_of`** in `tri_coach.repl`; `tri_web.thread` imports it.
- **`ThreadView.running` reports the lock's label,** `stuck` is computed exactly as `run_checkin` does (`snap.next` non-empty with nothing paused or held).
- **`POST /coach/review` with `action: "edit"` requires at least one proposal;** an empty list is `422 {"detail": "edit needs at least one proposal; reject instead"}`. Validation failures are `422 {"detail": "edit rejected", "errors": [{loc, msg}]}` with the same `errors` list `POST /coach/review/validate` returns.
- **`Runtime.today` is an injectable callable** (default `date.today`), like `CoachDeps.today`, so plan 2's Today view and tests pin a date.
- **`tri-web openapi`** prints the OpenAPI document; plan 3 generates `web/src/api/types.ts` from it.
- **Out of scope here:** Today (§6.2), jobs (§6.6), memory and reset (§6.7), static serving of `web/dist` (plan 2); everything under `web/` (plan 3).

---

## File Structure

```
pyproject.toml                                   modify: dependencies, [tool.uv.sources], ruff known-first-party, mypy files
packages/tri-coach/src/tri_coach/cli.py          modify: ready(settings) -> str | None; _ready wraps it
packages/tri-coach/src/tri_coach/repl.py         modify: TurnClassifier, text_of, TurnPrinter.print_event, run_turn(printer=)
packages/tri-coach/src/tri_coach/graph/nodes/apply.py   modify: AIMessage(..., name="apply")
packages/tri-coach/tests/test_cli.py             modify: + test_ready_names_the_missing_piece
packages/tri-coach/tests/test_repl.py            modify: + classifier tests (additive)
packages/tri-web/pyproject.toml                  create
packages/tri-web/src/tri_web/__init__.py         create (empty)
packages/tri-web/src/tri_web/config.py           create: WebSettings
packages/tri-web/src/tri_web/runtime.py          create: Runtime, open_runtime, cfg
packages/tri-web/src/tri_web/events.py           create: TurnEvent, TurnEmitter, TurnRun, Busy, start_turn, format_sse, sse_response
packages/tri-web/src/tri_web/thread.py           create: UiMessage, ReviewPayload, ThreadView, ui_messages, thread_snapshot
packages/tri-web/src/tri_web/review.py           create: Validated, schema, validate_json, validate_yaml, to_yaml
packages/tri-web/src/tri_web/schemas.py          create: TurnIn, ReviewIn, ValidateIn, SchemaOut, YamlOut, StatusOut, NoReview, EditRejected
packages/tri-web/src/tri_web/app.py              create: create_app, runtime_of
packages/tri-web/src/tri_web/routes/__init__.py  create (empty)
packages/tri-web/src/tri_web/routes/coach.py     create: thread, turns, review, review/schema, review/validate, review/yaml
packages/tri-web/src/tri_web/routes/system.py    create: status
packages/tri-web/src/tri_web/cli.py              create: serve, openapi
packages/tri-web/tests/conftest.py               create: nocommit, mem_store, runtime factory, client, parse_sse
packages/tri-web/tests/test_config.py            create
packages/tri-web/tests/test_runtime.py           create
packages/tri-web/tests/test_events.py            create
packages/tri-web/tests/test_thread.py            create
packages/tri-web/tests/test_review.py            create
packages/tri-web/tests/test_routes_coach.py      create
packages/tri-web/tests/test_routes_system.py     create
packages/tri-web/tests/test_cli.py               create
packages/tri-web/README.md                       create
README.md                                        modify: tri-web row, Run line, Layout line
```

---

### Task 1: The `tri-web` package joins the workspace, with `WebSettings`

**Files:**
- Create: `packages/tri-web/pyproject.toml`, `packages/tri-web/src/tri_web/__init__.py`, `packages/tri-web/src/tri_web/config.py`, `packages/tri-web/tests/__init__.py` (not needed: `--import-mode=importlib`; do not create), `packages/tri-web/tests/test_config.py`
- Modify: `pyproject.toml` (root)

**Interfaces:**
- Produces: `tri_web.config.WebSettings(CoachSettings)` with `tri_web_host: str = "127.0.0.1"`, `tri_web_port: int = 8321`, `tri_web_dist: str = "web/dist"`; `get_web_settings() -> WebSettings` (cached).

- [ ] **Step 1: Write the failing test**

`packages/tri-web/tests/test_config.py`:

```python
from tri_web.config import WebSettings


def test_defaults_bind_localhost_on_8321():
    s = WebSettings(_env_file=None)
    assert s.tri_web_host == "127.0.0.1" and s.tri_web_port == 8321
    assert s.tri_web_dist == "web/dist"
    assert s.tri_coach_langsmith_project == "tri_coach"  # inherits CoachSettings


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TRI_WEB_PORT", "9000")
    monkeypatch.setenv("TRI_WEB_HOST", "0.0.0.0")
    s = WebSettings(_env_file=None)
    assert s.tri_web_port == 9000 and s.tri_web_host == "0.0.0.0"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-web/tests/test_config.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_web'`.

- [ ] **Step 3: Create the package**

`packages/tri-web/pyproject.toml`:

```toml
[project]
name = "tri-web"
version = "0.1.0"
description = "Local web UI over the head coach: FastAPI server streaming the coach graph, React app in web/"
authors = [{ name = "Brian Flannery", email = "brian@paradigmshiftdev.io" }]
requires-python = ">=3.12,<3.13"
dependencies = [
    "tri-core",
    "tri-coach",
    "fastapi>=0.141,<1",
    "uvicorn>=0.52,<1",
    "typer>=0.15",
]

[project.scripts]
tri-web = "tri_web.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tri_web"]

[tool.uv.sources]
tri-core = { workspace = true }
tri-coach = { workspace = true }
```

`packages/tri-web/src/tri_web/__init__.py`: empty file.

`packages/tri-web/src/tri_web/config.py`:

```python
"""Web settings: the coach's settings plus where the server binds and where the built app is."""

from functools import lru_cache

from tri_coach.config import CoachSettings


class WebSettings(CoachSettings):
    tri_web_host: str = "127.0.0.1"
    tri_web_port: int = 8321
    tri_web_dist: str = "web/dist"  # relative to the working directory; served when present


@lru_cache(maxsize=1)
def get_web_settings() -> WebSettings:
    return WebSettings()
```

- [ ] **Step 4: Register the member in the root `pyproject.toml`**

Three edits:

```toml
dependencies = ["tri-core", "tri-analyze", "tri-planning", "tri-nutrition", "tri-wellness", "tri-coach", "tri-web"]
```

under `[tool.uv.sources]` add `tri-web = { workspace = true }`; under `[tool.ruff.lint.isort]`:

```toml
known-first-party = ["tri_core", "tri_analyze", "tri_planning", "tri_nutrition", "tri_wellness", "tri_coach", "tri_web"]
```

under `[tool.mypy]` append `"packages/tri-web/src"` to `files`.

Then: `uv sync` (installs fastapi 0.141.1 and the new member; `uv.lock` changes and is committed).

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest packages/tri-web/tests/test_config.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Definition of done, then commit**

Run the DoD sequence from Global Constraints. mypy needs `tri_web` to type-check: it does (two files).

```bash
git add pyproject.toml uv.lock packages/tri-web
git commit -m "feat(web): tri-web package with WebSettings joins the workspace"
```

---

### Task 2: Lift readiness into `tri_coach.cli.ready`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/cli.py:47-62`
- Test: `packages/tri-coach/tests/test_cli.py`

**Interfaces:**
- Produces: `tri_coach.cli.ready(settings: CoachSettings) -> str | None` (the message or None). `_ready` keeps its signature and behaviour (prints in red, returns 2).

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-coach/tests/test_cli.py`:

```python
from tri_coach.cli import ready
from tri_coach.config import CoachSettings


def test_ready_names_the_missing_piece(monkeypatch):
    assert ready(CoachSettings(_env_file=None, anthropic_api_key=None)) == (
        "ANTHROPIC_API_KEY is not set in .env"
    )
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: False)
    s = CoachSettings(_env_file=None, anthropic_api_key="k", database_url="postgresql://x/y")
    assert ready(s) is not None and "setup_checkpointer" in ready(s)
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: True)
    monkeypatch.setattr("tri_nutrition.store.store_ready", lambda url: False)
    assert ready(s) is not None and "LangGraph store tables are missing" in ready(s)
    monkeypatch.setattr("tri_nutrition.store.store_ready", lambda url: True)
    assert ready(s) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-coach/tests/test_cli.py -q`
Expected: `ImportError: cannot import name 'ready'`.

- [ ] **Step 3: Split `_ready`**

Replace `_ready` in `packages/tri-coach/src/tri_coach/cli.py` with:

```python
def ready(settings: CoachSettings) -> str | None:
    """Why chat cannot start, or None when the key, checkpointer and store are all there."""
    from tri_coach.graph.checkpointer import SETUP_HINT, checkpointer_ready
    from tri_nutrition import store as S

    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set in .env"
    if not checkpointer_ready(settings.database_url):
        return SETUP_HINT
    if not S.store_ready(settings.database_url):
        return S.STORE_SETUP_HINT
    return None


def _ready(settings: CoachSettings) -> int | None:
    """Exit code when chat cannot start, else None."""
    problem = ready(settings)
    if problem is None:
        return None
    console.print(problem, style="red")
    return 2
```

The lazy imports stay inside `ready` (the module imports `tri_coach.graph.*` lazily everywhere, since `tri_coach.cli` is imported before `.env` is fully loaded).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_cli.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-coach/src/tri_coach/cli.py packages/tri-coach/tests/test_cli.py
git commit -m "refactor(coach): ready(settings) returns the readiness message; _ready prints it"
```

---

### Task 3: Split `TurnPrinter` into `TurnClassifier` + printer; `run_turn(printer=)`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/repl.py:39-137,140-167`
- Test: `packages/tri-coach/tests/test_repl.py` (additive)

**Interfaces:**
- Produces: `tri_coach.repl.text_of(msg: BaseMessage) -> str` (was `_text_of`); `where_of(namespace_label: str, node: str) -> str` (`coach`, `planning`, `nutrition` or `analyst`); `Event = tuple[str, dict[str, Any]]`; `TurnClassifier` with `final_text: str`, `interrupt: dict | None`, `classify(namespace, mode, data) -> list[Event]` emitting kinds `token {where, text}`, `tool_call {where, name, args}`, `assistant {where, text}`, `tool_result {where, name, chars}`, `consult {domain, name, text}`, `report {text, node, role}`, `interrupt {narration, proposals}`; `TurnPrinter(out)` with `classifier`, `error`, read-only `final_text`/`interrupt` properties, `on_event(...)` and `print_event(kind, payload)`; `run_turn(graph, payload, thread_id, out, *, tags=None, printer=None) -> TurnPrinter`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_repl.py`:

```python
from tri_coach.repl import TurnClassifier, text_of, where_of


def test_where_of_maps_namespaces_and_root_nodes():
    assert where_of("coach", "model") == "coach"
    assert where_of("coach", "tools") == "coach"
    assert where_of("planning", "model") == "planning"
    assert where_of("nutrition", "tools") == "nutrition"
    assert where_of("", "model") == "analyst"
    assert where_of("", "tools") == "analyst"
    assert where_of("", "apply") == "coach"


def test_classifier_emits_one_event_per_visible_thing():
    c = TurnClassifier()
    assert c.classify(
        ("coach:1",), "messages", (AIMessageChunk(content="Hel"), {"langgraph_node": "model"})
    ) == [("token", {"where": "coach", "text": "Hel"})]
    assert c.classify(
        ("coach:1",), "messages", (AIMessageChunk(content=""), {"langgraph_node": "model"})
    ) == []
    assert c.classify(
        (), "messages", (AIMessageChunk(content="CTL 45"), {"langgraph_node": "model"})
    ) == [("token", {"where": "analyst", "text": "CTL 45"})]
    assert c.final_text == "Hel"  # only the coach's own tokens count
    call = AIMessage(
        content="",
        tool_calls=[{"name": "ask_analyst", "args": {"question": "CTL?"}, "id": "a1", "type": "tool_call"}],
    )
    assert c.classify(("coach:1",), "updates", {"model": {"messages": [call]}}) == [
        ("tool_call", {"where": "coach", "name": "ask_analyst", "args": {"question": "CTL?"}})
    ]
    assert c.classify(
        ("coach:1",),
        "updates",
        {"tools": {"messages": [ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="a1")]}},
    ) == [("tool_result", {"where": "coach", "name": "ask_analyst", "chars": 10})]
    assert c.classify(
        ("coach:1",), "updates", {"model": {"messages": [AIMessage(content="Your CTL is 45.")]}}
    ) == [("assistant", {"where": "coach", "text": "Your CTL is 45."})]
    assert c.final_text == "Your CTL is 45."
    assert c.classify(
        (),
        "updates",
        {"planning": {"messages": [ToolMessage(content="p1 (planning): move it", name="consult_planning", tool_call_id="c1")]}},
    ) == [("consult", {"domain": "planning", "name": "consult_planning", "text": "p1 (planning): move it"})]
    assert c.classify((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}}) == [
        ("report", {"text": "planning: applied 1", "node": "apply", "role": "ai"})
    ]
    assert c.final_text == "planning: applied 1"
    msg = HumanMessage("[follow-on] moved.")
    assert c.classify((), "updates", {"nutrition": {"messages": [msg]}}) == [
        ("report", {"text": "[follow-on] moved.", "node": "nutrition", "role": "human"})
    ]
    ev = c.classify((), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)})
    assert ev == [("interrupt", {"narration": "n", "proposals": []})]
    assert c.interrupt == {"narration": "n", "proposals": []}
    # the coach node's own replay of the sub-agent's messages is silent
    assert c.classify((), "updates", {"coach": {"messages": [AIMessage(content="Your CTL is 45.")]}}) == []


def test_text_of_joins_text_blocks():
    assert text_of(AIMessage(content=[{"type": "text", "text": "a"}, {"type": "tool_use", "id": "x"}, "b"])) == "ab"


async def test_run_turn_uses_the_given_printer():
    class Collect(TurnPrinter):
        def __init__(self) -> None:
            super().__init__(lambda s: None)
            self.kinds: list[str] = []

        def print_event(self, kind: str, payload: dict[str, Any]) -> None:
            self.kinds.append(kind)

    graph = StubGraph([[interrupt_event()]])
    collect = Collect()
    printer = await run_turn(graph, {"messages": []}, "coach", lambda s: None, printer=collect)
    assert printer is collect and collect.kinds == ["interrupt"]
    assert collect.interrupt == interrupt_payload()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_repl.py -q`
Expected: `ImportError: cannot import name 'TurnClassifier'`.

- [ ] **Step 3: Rewrite the printer section of `repl.py`**

Replace everything from `def _text_of(msg` through the end of `run_turn` with the following. `label`, `_tag`, `TAGGED`, `ROOT_NODES`, `REVIEW_PROMPT` and everything after `run_turn` stay as they are (`render_review` and friends use `Proposal`, not the printer).

```python
Event = tuple[str, dict[str, Any]]


def text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(
        str(b.get("text", ""))
        if isinstance(b, dict) and b.get("type") == "text"
        else (b if isinstance(b, str) else "")
        for b in content
    )


def label(namespace: tuple[str, ...]) -> str:
    return namespace[0].split(":", 1)[0] if namespace else ""


def _tag(where: str, node: str = "") -> str:
    """The bracket label: a consultation's, the analyst's, or "" for the coach and the root."""
    if where in TAGGED:
        return where
    if not where and node in ("model", "tools"):
        return "analyst"
    return ""


def where_of(namespace_label: str, node: str) -> str:
    """Who is speaking: the tag, or "coach" for the coach's own voice and the root nodes."""
    return _tag(namespace_label, node) or "coach"


class TurnClassifier:
    """Raw stream events in, (kind, payload) tuples out. Kinds: token, tool_call, assistant,
    tool_result, consult, report, interrupt. Tracks the coach's final text and the interrupt."""

    def __init__(self) -> None:
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None

    def classify(self, namespace: tuple[str, ...], mode: str, data: Any) -> list[Event]:
        where = label(namespace)
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    if where == "coach":
                        self.final_text += text
                    return [("token", {"where": where_of(where, "model"), "text": text})]
            return []
        if mode != "updates" or not isinstance(data, dict):
            return []
        if "__interrupt__" in data:
            self.interrupt = dict(data["__interrupt__"][0].value)
            return [("interrupt", self.interrupt)]
        events: list[Event] = []
        for node, payload in data.items():
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    who = where_of(where, node)
                    for tc in msg.tool_calls:
                        events.append(
                            ("tool_call", {"where": who, "name": tc["name"], "args": tc["args"]})
                        )
                    if not msg.tool_calls:
                        text = text_of(msg)
                        if where == "coach" and text:
                            self.final_text = text
                        events.append(("assistant", {"where": who, "text": text}))
                elif node == "tools" and isinstance(msg, ToolMessage):
                    events.append(
                        (
                            "tool_result",
                            {"where": where_of(where, node), "name": msg.name, "chars": len(text_of(msg))},
                        )
                    )
                elif (
                    not where and node in ("planning", "nutrition") and isinstance(msg, ToolMessage)
                ):  # a consultation's result, once, from the coach graph's own node
                    events.append(
                        ("consult", {"domain": node, "name": msg.name, "text": text_of(msg)})
                    )
                elif (
                    not where
                    and node in ("apply", "review", "nutrition")
                    and isinstance(msg, AIMessage | HumanMessage)
                ):
                    text = text_of(msg)
                    if isinstance(msg, AIMessage):
                        self.final_text = text
                    role = "ai" if isinstance(msg, AIMessage) else "human"
                    events.append(("report", {"text": text, "node": node, "role": role}))
        return events


class TurnPrinter:
    """Formats the classifier's events for the terminal. Subclasses override print_event."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.classifier = TurnClassifier()
        self.error: str | None = None
        self._line_label = ""  # tag printed at the start of the current streamed line

    @property
    def final_text(self) -> str:
        return self.classifier.final_text

    @property
    def interrupt(self) -> dict[str, Any] | None:
        return self.classifier.interrupt

    def _stream(self, tag: str, text: str) -> None:
        if self._line_label != tag:
            self.out(f"\n[{tag}] " if tag else "\n")
            self._line_label = tag
        self.out(text)

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        for kind, payload in self.classifier.classify(namespace, mode, data):
            self.print_event(kind, payload)

    def print_event(self, kind: str, payload: dict[str, Any]) -> None:
        where = payload.get("where", "coach")
        tag = "" if where == "coach" else where
        prefix = f"[{tag}] " if tag else ""
        if kind == "token":
            self._stream(tag, payload["text"])
        elif kind == "tool_call":
            self.out(f"\n{prefix}→ {payload['name']}({payload['args']})\n")
            self._line_label = ""
        elif kind == "assistant":
            self.out("\n")  # close the streamed line
            self._line_label = ""
        elif kind == "tool_result":
            self._line_label = ""
            self.out(f"{prefix}← {payload['name']}: {payload['chars']} chars\n")
        elif kind == "consult":
            self.out(f"← {payload['name']}: {payload['text']}\n")
        elif kind == "report":
            self.out(f"{payload['text']}\n")


async def run_turn(
    graph: Any,
    payload: dict[str, Any] | Command[Any],
    thread_id: str,
    out: Out,
    *,
    tags: list[str] | None = None,
    printer: TurnPrinter | None = None,
) -> TurnPrinter:
    printer = printer or TurnPrinter(out)
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    if tags:
        cfg["tags"] = list(tags)
    try:
        async for namespace, mode, data in graph.astream(
            payload, config=cfg, stream_mode=["messages", "updates"], subgraphs=True
        ):
            printer.on_event(tuple(namespace), mode, data)
    except anthropic.RateLimitError as exc:
        printer.error = f"\n[rate limited: {exc}. Wait a moment and try again.]\n"
        out(printer.error)
    except anthropic.APIStatusError as exc:
        printer.error = f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n"
        out(printer.error)
    except anthropic.APIConnectionError as exc:
        printer.error = f"\n[connection error talking to Anthropic: {exc}]\n"
        out(printer.error)
    except Exception as exc:  # noqa: BLE001 - the chat keeps the state at the last checkpoint
        printer.error = f"\n[the turn failed: {type(exc).__name__}: {exc}]\n"
        out(printer.error)
    return printer
```

Then `grep -rn "_text_of" packages/` and rename every remaining use to `text_of` (expected: none outside `repl.py`; `checkin.py` imports only `Out, paused_review, render_review, run_turn`).

Why the output is byte-identical: the old code printed each tool call, then `"\n"` for a tool-call-free message, then reset `_line_label` once per message; resetting after each `tool_call` event and after `assistant` is the same because the reset is idempotent and nothing prints between them. `_tag(where, "model")` for tokens equals `"" if where_of(...) == "coach" else where_of(...)`. `final_text` follows the same three rules (coach tokens append; a coach `model` message with text replaces; an apply/review/nutrition `AIMessage` replaces).

- [ ] **Step 4: Run the whole coach suite to verify nothing moved**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass, including every pre-existing `test_repl.py` and `test_checkin.py` assertion, plus the four new tests.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-coach/src/tri_coach/repl.py packages/tri-coach/tests/test_repl.py
git commit -m "refactor(coach): TurnClassifier yields typed events; TurnPrinter formats them; run_turn takes a printer"
```

---

### Task 4: `Runtime` and `open_runtime`

**Files:**
- Create: `packages/tri-web/src/tri_web/runtime.py`
- Test: `packages/tri-web/tests/test_runtime.py`

**Interfaces:**
- Consumes: `tri_coach.cli.ready` (Task 2).
- Produces:

```python
Log = Callable[[str], None]

@dataclass
class Runtime:
    settings: WebSettings
    graph: Any                                   # compiled coach graph
    store: BaseStore
    servers: Servers
    connect: Callable[[], AbstractContextManager[Conn]]
    live: bool                                   # False under --no-live
    today: Callable[[], date] = date.today
    thread_id: str = "coach"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running: str | None = None                   # "turn" | "review" | "checkin" | "reset" | None
    turn_task: asyncio.Task[None] | None = None  # the producer of the current run, kept alive

def cfg(rt: Runtime) -> dict[str, Any]          # {"configurable": {"thread_id": rt.thread_id}}

@asynccontextmanager
async def open_runtime(settings: WebSettings, *, no_live: bool, log: Log, model: BaseChatModel | None = None) -> AsyncIterator[Runtime]
```

`open_runtime` raises `RuntimeError(message)` with `ready()`'s message when the key, checkpointer or store is missing.

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_runtime.py`:

```python
"""open_runtime is the CLI's assembly without Typer: readiness first, then servers, saver, store,
deps, graph. The graph is opened over the test database with a scripted model."""

import pytest

from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel
from tri_nutrition.store import store_ready
from tri_web.config import WebSettings
from tri_web.runtime import Runtime, cfg, open_runtime

pytestmark = pytest.mark.db


async def test_readiness_failure_raises_with_the_cli_hint():
    settings = WebSettings(_env_file=None, anthropic_api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        async with open_runtime(settings, no_live=True, log=lambda m: None):
            pass


async def test_no_live_runtime_opens_the_graph_on_thread_coach(db):
    url = Settings().test_database_url
    if not (checkpointer_ready(url) and store_ready(url)):
        pytest.skip("checkpoint or store tables missing in the test database")
    settings = WebSettings(_env_file=None, anthropic_api_key="test-key", database_url=url)
    logged: list[str] = []
    async with open_runtime(
        settings, no_live=True, log=logged.append, model=ScriptedChatModel(script=[])
    ) as rt:
        assert isinstance(rt, Runtime)
        assert rt.thread_id == "coach" and rt.live is False and rt.running is None
        assert not rt.lock.locked()
        assert rt.servers.garmin_tools == [] and rt.servers.tp_tools == []
        assert cfg(rt) == {"configurable": {"thread_id": "coach"}}
        snap = await rt.graph.aget_state(cfg(rt))
        assert snap.next == () or snap.next == ("review",)  # a real thread may be paused
        with rt.connect() as conn:
            assert conn.execute("select 1 as one").fetchone()["one"] == 1
    assert logged == []  # --no-live starts no server, so nothing is logged
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_runtime.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.runtime'`.

- [ ] **Step 3: Write `runtime.py`**

```python
"""The process-wide state behind every route: one graph on thread "coach", one store, one set of
MCP sessions, one lock. open_runtime is tri_coach.cli._open_graph without Typer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.store.base import BaseStore

from tri_coach.servers import Servers
from tri_core.db.repo import Conn
from tri_web.config import WebSettings

Log = Callable[[str], None]


@dataclass
class Runtime:
    settings: WebSettings
    graph: Any
    store: BaseStore
    servers: Servers
    connect: Callable[[], AbstractContextManager[Conn]]
    live: bool
    today: Callable[[], date] = date.today
    thread_id: str = "coach"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running: str | None = None
    turn_task: asyncio.Task[None] | None = None


def cfg(rt: Runtime) -> dict[str, Any]:
    return {"configurable": {"thread_id": rt.thread_id}}


@asynccontextmanager
async def open_runtime(
    settings: WebSettings, *, no_live: bool, log: Log, model: BaseChatModel | None = None
) -> AsyncIterator[Runtime]:
    """Readiness, then servers, checkpointer, store, deps, graph; everything closes with the
    exit stack. `model` overrides make_model (tests)."""
    from tri_coach.cli import ready
    from tri_coach.graph.checkpointer import open_checkpointer
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.servers import open_servers
    from tri_nutrition import store as S

    problem = ready(settings)
    if problem is not None:
        raise RuntimeError(problem)
    async with AsyncExitStack() as stack:
        servers = await open_servers(stack, settings, no_live=no_live, log=log)
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        deps = make_deps(settings, model or make_model(settings), servers)
        yield Runtime(
            settings=settings,
            graph=build_graph(deps, saver, store),
            store=store,
            servers=servers,
            connect=deps.connect,
            live=not no_live,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_runtime.py -q`
Expected: `2 passed` (or the second skipped when the test database lacks the checkpoint tables; `scripts/setup_checkpointer.py $TEST_DATABASE_URL` creates them).

Note: `make_deps` builds the planning and nutrition deps from `get_planning_settings()` / `get_nutrition_settings()`, which read `.env`; the test opens no turn, so nothing touches those URLs.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/runtime.py packages/tri-web/tests/test_runtime.py
git commit -m "feat(web): Runtime and open_runtime open the coach graph like the CLI, without Typer"
```

---

### Task 5: Turn events: `TurnEmitter`, `start_turn`, SSE framing

**Files:**
- Create: `packages/tri-web/src/tri_web/events.py`
- Test: `packages/tri-web/tests/test_events.py`

**Interfaces:**
- Consumes: `TurnPrinter`, `run_turn(..., printer=)` (Task 3); `Runtime` (Task 4).
- Produces:

```python
@dataclass
class TurnEvent:
    name: str          # token | tool_call | tool_result | consult | report | interrupt | error | done
    data: dict[str, Any]

class TurnEmitter(TurnPrinter):        # print_event pushes TurnEvents onto a queue; drops "assistant"
    def __init__(self, queue: asyncio.Queue[TurnEvent | None]) -> None

class Busy(Exception):                 # .running: str
    def __init__(self, running: str) -> None

@dataclass
class TurnRun:
    queue: asyncio.Queue[TurnEvent | None]   # None is the end marker
    task: asyncio.Task[None]

async def start_turn(rt: Runtime, payload: dict[str, Any] | Command[Any], *, kind: str, tags: list[str] | None = None) -> TurnRun
def format_sse(name: str, data: Any) -> str                # "event: <name>\ndata: <json>\n\n"
def sse_response(run: TurnRun) -> StreamingResponse
def error_message(printer_error: str) -> str               # strips newlines and the brackets
```

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_events.py`:

```python
"""Each spec §5.3 event from a recorded (namespace, mode, data); start_turn over a stub graph."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Interrupt

from tri_web.events import Busy, TurnEmitter, TurnEvent, error_message, format_sse, start_turn


def emitted(events: list[tuple[tuple[str, ...], str, Any]]) -> list[TurnEvent]:
    q: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
    em = TurnEmitter(q)
    for ns, mode, data in events:
        em.on_event(ns, mode, data)
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_token_and_tool_activity_by_where():
    call = AIMessage(
        content="",
        tool_calls=[{"name": "query_training_db", "args": {"sql": "select 1"}, "id": "q1", "type": "tool_call"}],
    )
    evs = emitted(
        [
            (("coach:1",), "messages", (AIMessageChunk(content="Hi"), {"langgraph_node": "model"})),
            ((), "messages", (AIMessageChunk(content="CTL 45"), {"langgraph_node": "model"})),
            ((), "updates", {"model": {"messages": [call]}}),
            ((), "updates", {"tools": {"messages": [ToolMessage(content="[]", name="query_training_db", tool_call_id="q1")]}}),
            (("coach:1",), "updates", {"model": {"messages": [AIMessage(content="Your CTL is 45.")]}}),
        ]
    )
    assert [(e.name, e.data) for e in evs] == [
        ("token", {"where": "coach", "text": "Hi"}),
        ("token", {"where": "analyst", "text": "CTL 45"}),
        ("tool_call", {"where": "analyst", "name": "query_training_db", "args": {"sql": "select 1"}}),
        ("tool_result", {"where": "analyst", "name": "query_training_db", "chars": 2}),
    ]  # the tool-call-free AIMessage ("assistant") is not an SSE event


def test_consult_report_and_interrupt():
    consult = ToolMessage(content="p1 (planning): move it", name="consult_planning", tool_call_id="c1")
    evs = emitted(
        [
            ((), "updates", {"planning": {"messages": [consult]}}),
            ((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}}),
            ((), "updates", {"nutrition": {"messages": [HumanMessage("[follow-on] moved.")]}}),
            ((), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)}),
        ]
    )
    assert [(e.name, e.data) for e in evs] == [
        ("consult", {"domain": "planning", "text": "p1 (planning): move it"}),
        ("report", {"text": "planning: applied 1"}),
        ("report", {"text": "[follow-on] moved."}),
        ("interrupt", {"narration": "n", "proposals": []}),
    ]


def test_format_sse_frames_one_event_with_json_data():
    assert format_sse("token", {"where": "coach", "text": "a\nb"}) == (
        'event: token\ndata: {"where": "coach", "text": "a\\nb"}\n\n'
    )
    assert json.loads(format_sse("done", {"paused": False}).split("data: ")[1]) == {"paused": False}


def test_error_message_strips_the_terminal_dressing():
    assert error_message("\n[the turn failed: RuntimeError: boom]\n") == "the turn failed: RuntimeError: boom"


class StubGraph:
    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.inputs: list[Any] = []
        self.release = asyncio.Event()

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        turn = self.turns.pop(0)
        if turn == "boom":
            raise RuntimeError("model down")
        for ev in turn:
            yield ev
        await self.release.wait()  # hold the run open until the test lets go

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(next=(), values={}, tasks=())


def runtime_over(graph: Any) -> Any:
    return SimpleNamespace(
        graph=graph, thread_id="coach", lock=asyncio.Lock(), running=None, turn_task=None
    )


async def drain(run) -> list[TurnEvent]:
    out = []
    while (ev := await run.queue.get()) is not None:
        out.append(ev)
    return out


async def test_start_turn_holds_the_lock_until_the_run_ends_and_ends_with_done():
    graph = StubGraph([[(("coach:1",), "messages", (AIMessageChunk(content="Hi"), {"langgraph_node": "model"}))]])
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": [HumanMessage("hi")]}, kind="turn")
    assert rt.lock.locked() and rt.running == "turn"
    first = await run.queue.get()
    assert first is not None and first.name == "token"
    try:
        await start_turn(rt, {"messages": []}, kind="turn")
    except Busy as exc:
        assert exc.running == "turn"
    else:
        raise AssertionError("second start_turn should be refused")
    graph.release.set()
    rest = await drain(run)
    await run.task
    assert rest[-1].name == "done" and rest[-1].data == {"final_text": "Hi", "paused": False}
    assert not rt.lock.locked() and rt.running is None


async def test_a_failing_run_emits_error_then_done_and_releases_the_lock():
    graph = StubGraph(["boom"])
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": []}, kind="turn")
    evs = await drain(run)
    await run.task
    assert [e.name for e in evs] == ["error", "done"]
    assert "model down" in evs[0].data["message"]
    assert not rt.lock.locked()


async def test_done_paused_is_true_after_an_interrupt():
    graph = StubGraph([[((), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)})]])
    graph.release.set()
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": []}, kind="review")
    evs = await drain(run)
    assert [e.name for e in evs] == ["interrupt", "done"] and evs[-1].data["paused"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_events.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.events'`.

- [ ] **Step 3: Write `events.py`**

```python
"""A coach turn as a stream of typed events. start_turn takes the runtime lock, runs the graph in
a background task through a TurnEmitter, and releases the lock when the run ends, so a closed tab
never leaves a checkpoint half-written. sse_response reads the queue into text/event-stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command
from starlette.responses import StreamingResponse

from tri_coach.repl import TurnPrinter, run_turn
from tri_web.runtime import Runtime


@dataclass
class TurnEvent:
    name: str
    data: dict[str, Any]


class TurnEmitter(TurnPrinter):
    """TurnPrinter's classification as queued events (spec §5.3); no terminal output."""

    def __init__(self, queue: asyncio.Queue[TurnEvent | None]) -> None:
        super().__init__(lambda s: None)
        self.queue = queue

    def print_event(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "assistant":
            return
        if kind == "consult":
            payload = {"domain": payload["domain"], "text": payload["text"]}
        elif kind == "report":
            payload = {"text": payload["text"]}
        self.queue.put_nowait(TurnEvent(kind, payload))


class Busy(Exception):
    def __init__(self, running: str) -> None:
        super().__init__(f"a {running} is running")
        self.running = running


@dataclass
class TurnRun:
    queue: asyncio.Queue[TurnEvent | None]
    task: asyncio.Task[None]


def error_message(printer_error: str) -> str:
    return printer_error.strip().removeprefix("[").removesuffix("]")


async def _produce(
    rt: Runtime,
    payload: dict[str, Any] | Command[Any],
    queue: asyncio.Queue[TurnEvent | None],
    tags: list[str] | None,
) -> None:
    emitter = TurnEmitter(queue)
    try:
        printer = await run_turn(
            rt.graph, payload, rt.thread_id, emitter.out, tags=tags, printer=emitter
        )
        if printer.error is not None:
            queue.put_nowait(TurnEvent("error", {"message": error_message(printer.error)}))
        queue.put_nowait(
            TurnEvent(
                "done", {"final_text": printer.final_text, "paused": printer.interrupt is not None}
            )
        )
    finally:
        queue.put_nowait(None)
        rt.running = None
        rt.lock.release()


async def start_turn(
    rt: Runtime,
    payload: dict[str, Any] | Command[Any],
    *,
    kind: str,
    tags: list[str] | None = None,
) -> TurnRun:
    """Refuses with Busy while another run holds the lock. The lock is taken here, in the caller's
    task, and released by the producer when the run ends."""
    if rt.lock.locked():
        raise Busy(rt.running or kind)
    await rt.lock.acquire()
    rt.running = kind
    queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
    task = asyncio.create_task(_produce(rt, payload, queue, tags))
    rt.turn_task = task
    return TurnRun(queue=queue, task=task)


def format_sse(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


async def _body(run: TurnRun) -> AsyncIterator[str]:
    while (ev := await run.queue.get()) is not None:
        yield format_sse(ev.name, ev.data)


def sse_response(run: TurnRun) -> StreamingResponse:
    return StreamingResponse(
        _body(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`asyncio.Lock.acquire()` on an unlocked lock returns without suspending, so the `locked()` check and the acquire cannot interleave with another request on the single event loop.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_events.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/events.py packages/tri-web/tests/test_events.py
git commit -m "feat(web): TurnEmitter, start_turn behind the runtime lock, SSE framing"
```

---

### Task 6: Thread snapshot: `UiMessage`, `ThreadView`, `thread_snapshot`

**Files:**
- Create: `packages/tri-web/src/tri_web/thread.py`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/apply.py:223` (`AIMessage("\n".join(lines), name="apply")`)
- Test: `packages/tri-web/tests/test_thread.py`

**Interfaces:**
- Consumes: `text_of` (Task 3), `paused_review` (`tri_coach.repl`), `cfg` (Task 4).
- Produces:

```python
class UiMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "activity", "consult", "report"]
    text: str
    where: str | None = None
    name: str | None = None
    args: dict[str, Any] | None = None
    chars: int | None = None

class ReviewPayload(BaseModel):
    narration: str
    proposals: list[dict[str, Any]]

class ThreadView(BaseModel):
    messages: list[UiMessage]
    paused: ReviewPayload | None
    held: ReviewPayload | None
    stuck: bool
    running: str | None

REPORT_PREFIXES = ("[review]", "[follow-on]", "Review rejected:")
def ui_messages(messages: Sequence[BaseMessage]) -> list[UiMessage]
async def thread_snapshot(graph: Any, thread_id: str, *, running: str | None) -> ThreadView
```

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_thread.py`:

```python
"""Checkpoint messages map to UiMessages; a paused review and a held set are recovered."""

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Interrupt

from tri_coach.models import ChangeSet, Proposal
from tri_web.thread import ThreadView, thread_snapshot, ui_messages


def proposal() -> Proposal:
    return Proposal.model_validate(
        {
            "id": "p1",
            "domain": "planning",
            "summary": "move it",
            "changes": [{"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "knee"}],
        }
    )


def payload() -> dict[str, Any]:
    return {"narration": "Knee: move Wednesday.", "proposals": [proposal().model_dump(mode="json")]}


def test_ui_messages_classify_each_root_message():
    ask = AIMessage(
        content="",
        id="a1",
        tool_calls=[{"name": "ask_analyst", "args": {"question": "CTL?"}, "id": "t1", "type": "tool_call"}],
    )
    consult = AIMessage(
        content="Let me ask planning.",
        id="a2",
        tool_calls=[{"name": "consult_planning", "args": {"instruction": "move w1"}, "id": "t2", "type": "tool_call"}],
    )
    msgs = [
        SystemMessage("never shown"),
        HumanMessage("how fit am I?", id="h1"),
        ask,
        ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="t1", id="tm1"),
        AIMessage(content="Your CTL is 45.", id="a3"),
        consult,
        ToolMessage(content="p1 (planning): move it", name="consult_planning", tool_call_id="t2", id="tm2"),
        AIMessage(content="planning: applied 1", name="apply", id="a4"),
        HumanMessage("[review] nothing to review; call propose_changes with proposal ids", id="h2"),
        HumanMessage("[follow-on] The approved plan change moved sessions.", id="h3"),
        HumanMessage("Review rejected: keep Wednesday", id="h4"),
    ]
    out = ui_messages(msgs)
    assert [(m.id, m.role) for m in out] == [
        ("h1", "user"),
        ("a1.0", "activity"),
        ("tm1", "activity"),
        ("a3", "assistant"),
        ("a2.0", "activity"),
        ("a2", "assistant"),
        ("tm2", "consult"),
        ("a4", "report"),
        ("h2", "report"),
        ("h3", "report"),
        ("h4", "report"),
    ]
    assert out[1].name == "ask_analyst" and out[1].args == {"question": "CTL?"} and out[1].where == "coach"
    assert out[2].name == "ask_analyst" and out[2].chars == 10 and out[2].text == "← ask_analyst: 10 chars"
    assert out[3].where == "coach" and out[3].text == "Your CTL is 45."
    assert out[6].where == "planning" and out[6].text == "p1 (planning): move it"
    assert out[7].text == "planning: applied 1"


def test_messages_without_ids_get_positional_ids():
    out = ui_messages([HumanMessage("a"), AIMessage(content="b")])
    assert [m.id for m in out] == ["m0", "m1"]


class Graph:
    def __init__(self, snap: Any) -> None:
        self.snap = snap

    async def aget_state(self, config: Any) -> Any:
        assert config == {"configurable": {"thread_id": "coach"}}
        return self.snap


async def test_snapshot_recovers_a_paused_review():
    snap = SimpleNamespace(
        next=("review",),
        values={"messages": [HumanMessage("move it", id="h1")], "pending": None},
        tasks=(SimpleNamespace(interrupts=(Interrupt(value=payload()),)),),
    )
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert isinstance(view, ThreadView)
    assert [m.role for m in view.messages] == ["user"]
    assert view.paused is not None and view.paused.narration == "Knee: move Wednesday."
    assert view.paused.proposals[0]["id"] == "p1"
    assert view.held is None and view.stuck is False and view.running is None


async def test_snapshot_recovers_a_held_change_set():
    held = ChangeSet(narration="Held from the last apply.", proposals=[proposal()])
    snap = SimpleNamespace(next=(), values={"messages": [], "pending": held}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running="turn")
    assert view.paused is None
    assert view.held is not None and view.held.narration == "Held from the last apply."
    assert view.held.proposals[0]["changes"][0]["new_date"] == "2026-09-18"
    assert view.running == "turn"


async def test_snapshot_marks_a_thread_stopped_mid_run_as_stuck():
    snap = SimpleNamespace(next=("nutrition",), values={"messages": []}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert view.stuck is True and view.paused is None and view.held is None


async def test_snapshot_of_an_empty_thread():
    snap = SimpleNamespace(next=(), values={}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert view.messages == [] and view.stuck is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_thread.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.thread'`.

- [ ] **Step 3: Name the apply report**

In `packages/tri-coach/src/tri_coach/graph/nodes/apply.py` change the last line of the return dict:

```python
            "messages": [AIMessage("\n".join(lines), name="apply")],
```

Run `uv run pytest packages/tri-coach -q` afterwards: the printer and every graph test compare content only, so nothing changes.

- [ ] **Step 4: Write `thread.py`**

```python
"""What the page renders after a reload: the checkpoint's root messages as UiMessages, plus the
review that is paused or the change set that is held. The classification mirrors the stream's
(spec §5.3) so history and live events go through one component set."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from tri_coach.repl import paused_review, text_of

CONSULTS = {"consult_planning": "planning", "consult_nutrition": "nutrition"}
REPORT_PREFIXES = ("[review]", "[follow-on]", "Review rejected:")


class UiMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "activity", "consult", "report"]
    text: str
    where: str | None = None
    name: str | None = None
    args: dict[str, Any] | None = None
    chars: int | None = None


class ReviewPayload(BaseModel):
    narration: str
    proposals: list[dict[str, Any]]


class ThreadView(BaseModel):
    messages: list[UiMessage]
    paused: ReviewPayload | None
    held: ReviewPayload | None
    stuck: bool
    running: str | None


def ui_messages(messages: Sequence[BaseMessage]) -> list[UiMessage]:
    out: list[UiMessage] = []
    for i, m in enumerate(messages):
        mid = m.id or f"m{i}"
        text = text_of(m)
        if isinstance(m, HumanMessage):
            role: Literal["user", "report"] = "report" if text.startswith(REPORT_PREFIXES) else "user"
            out.append(UiMessage(id=mid, role=role, text=text))
        elif isinstance(m, AIMessage):
            if m.name == "apply":
                out.append(UiMessage(id=mid, role="report", text=text))
                continue
            for k, tc in enumerate(m.tool_calls):
                out.append(
                    UiMessage(
                        id=f"{mid}.{k}",
                        role="activity",
                        text=f"→ {tc['name']}",
                        where="coach",
                        name=tc["name"],
                        args=dict(tc["args"]),
                    )
                )
            if text:
                out.append(UiMessage(id=mid, role="assistant", text=text, where="coach"))
        elif isinstance(m, ToolMessage):
            domain = CONSULTS.get(m.name or "")
            if domain is not None:
                out.append(UiMessage(id=mid, role="consult", text=text, where=domain, name=m.name))
            else:
                out.append(
                    UiMessage(
                        id=mid,
                        role="activity",
                        text=f"← {m.name}: {len(text)} chars",
                        where="coach",
                        name=m.name,
                        chars=len(text),
                    )
                )
        # SystemMessage and anything else: skipped
    return out


def _review_payload(raw: Any) -> ReviewPayload | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return ReviewPayload.model_validate(raw)
    return ReviewPayload(
        narration=raw.narration, proposals=[p.model_dump(mode="json") for p in raw.proposals]
    )


async def thread_snapshot(graph: Any, thread_id: str, *, running: str | None) -> ThreadView:
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = snap.values or {}
    paused = _review_payload(paused_review(snap))
    held = _review_payload(values.get("pending")) if paused is None else None
    stuck = paused is None and held is None and bool(snap.next)
    return ThreadView(
        messages=ui_messages(values.get("messages", [])),
        paused=paused,
        held=held,
        stuck=stuck,
        running=running,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_thread.py packages/tri-coach -q`
Expected: all pass.

- [ ] **Step 6: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/thread.py packages/tri-web/tests/test_thread.py packages/tri-coach/src/tri_coach/graph/nodes/apply.py
git commit -m "feat(web): thread snapshot maps checkpoint messages to UiMessages, recovers paused and held reviews"
```

---

### Task 7: Review helpers: schema, JSON and YAML validation

**Files:**
- Create: `packages/tri-web/src/tri_web/review.py`
- Test: `packages/tri-web/tests/test_review.py`

**Interfaces:**
- Consumes: `Proposal`, `proposals_to_yaml`, `proposals_from_yaml`.
- Produces:

```python
class ValidationItem(BaseModel):  loc: list[str | int]; msg: str
class Validated(BaseModel):       ok: bool; proposals: list[dict[str, Any]] = []; errors: list[ValidationItem] = []
def schema() -> dict[str, Any]                                  # {"proposal", "planning_change", "nutrition_change"}
def validate_json(items: list[dict[str, Any]]) -> Validated
def validate_yaml(text: str, originals: list[Proposal]) -> Validated
def to_yaml(proposals: list[Proposal]) -> str
def typed(v: Validated) -> list[Proposal]                        # after ok
```

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_review.py`:

```python
"""Schema shapes; JSON and YAML validate paths with a wrong domain, a bad date and an unknown op."""

from tri_coach.models import Proposal
from tri_web.review import schema, to_yaml, typed, validate_json, validate_yaml


def proposals() -> list[Proposal]:
    return [
        Proposal.model_validate(
            {
                "id": "p1",
                "domain": "planning",
                "summary": "move it",
                "changes": [{"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "rest"}],
            }
        ),
        Proposal.model_validate(
            {
                "id": "p2",
                "domain": "nutrition",
                "summary": "targets",
                "changes": [
                    {
                        "op": "set_day_targets",
                        "target_key": "2026-09-14",
                        "day": "2026-09-14",
                        "payload": {"calorie_goal": 2800},
                        "reason": "extend",
                    }
                ],
                "overrides": {"activity_factor": 1.45},
            }
        ),
    ]


def test_schema_has_the_three_models_with_their_enums():
    s = schema()
    assert set(s) == {"proposal", "planning_change", "nutrition_change"}
    assert s["proposal"]["properties"]["domain"]["enum"] == ["planning", "nutrition"]
    assert "create" in s["planning_change"]["properties"]["op"]["enum"]
    assert "set_day_targets" in s["nutrition_change"]["properties"]["op"]["enum"]
    assert "PlannedSession" in s["planning_change"]["$defs"]
    assert s["nutrition_change"]["properties"]["day"]["format"] == "date"


def test_validate_json_accepts_typed_proposals_and_round_trips():
    v = validate_json([p.model_dump(mode="json") for p in proposals()])
    assert v.ok and v.errors == [] and [p["id"] for p in v.proposals] == ["p1", "p2"]
    back = typed(v)
    assert back[0].changes[0].new_date.isoformat() == "2026-09-18"
    assert back[1].overrides == {"activity_factor": 1.45}


def test_validate_json_reports_loc_and_msg_per_error():
    bad = [p.model_dump(mode="json") for p in proposals()]
    bad[0]["domain"] = "cooking"
    bad[1]["changes"][0]["day"] = "2026-13-40"
    v = validate_json(bad)
    assert not v.ok and v.proposals == []
    locs = [e.loc for e in v.errors]
    assert [0, "domain"] in locs
    assert any(loc[:3] == [1, "changes", 0] and "day" in loc for loc in locs)
    assert all(e.msg for e in v.errors)


def test_validate_json_rejects_an_unknown_op():
    bad = [proposals()[0].model_dump(mode="json")]
    bad[0]["changes"][0]["op"] = "teleport"
    v = validate_json(bad)
    assert not v.ok and any("op" in e.loc for e in v.errors)


def test_yaml_path_edits_one_field_and_keeps_the_rest():
    text = to_yaml(proposals()).replace("2026-09-18", "2026-09-19")
    v = validate_yaml(text, proposals())
    assert v.ok and typed(v)[0].changes[0].new_date.isoformat() == "2026-09-19"
    assert typed(v)[1].overrides == {"activity_factor": 1.45}


def test_yaml_path_reports_parse_and_validation_errors():
    v = validate_yaml("p1: [unclosed", proposals())
    assert not v.ok and v.errors[0].loc == ["yaml"]
    v = validate_yaml(to_yaml(proposals()).replace("op: move", "op: teleport"), proposals())
    assert not v.ok and any("op" in e.loc for e in v.errors)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_review.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.review'`.

- [ ] **Step 3: Write `review.py`**

```python
"""The gate's server side: the change models' JSON schema for the form, and one validation path
for both editors. The same function guards POST /coach/review, so an edit that skips the client's
validate call still gets the same errors."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from tri_coach.models import Proposal
from tri_coach.repl import proposals_from_yaml, proposals_to_yaml
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange


class ValidationItem(BaseModel):
    loc: list[str | int]
    msg: str


class Validated(BaseModel):
    ok: bool
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[ValidationItem] = Field(default_factory=list)


def schema() -> dict[str, Any]:
    return {
        "proposal": Proposal.model_json_schema(),
        "planning_change": CalendarChange.model_json_schema(),
        "nutrition_change": NutritionChange.model_json_schema(),
    }


def _items(exc: ValidationError, prefix: list[str | int]) -> list[ValidationItem]:
    return [
        ValidationItem(loc=[*prefix, *e["loc"]], msg=e["msg"]) for e in exc.errors(include_url=False)
    ]


def validate_json(items: list[dict[str, Any]]) -> Validated:
    typed_items: list[Proposal] = []
    errors: list[ValidationItem] = []
    for i, item in enumerate(items):
        try:
            typed_items.append(Proposal.model_validate(item))
        except ValidationError as exc:
            errors.extend(_items(exc, [i]))
    if errors:
        return Validated(ok=False, errors=errors)
    return Validated(ok=True, proposals=[p.model_dump(mode="json") for p in typed_items])


def validate_yaml(text: str, originals: list[Proposal]) -> Validated:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return Validated(ok=False, errors=[ValidationItem(loc=["yaml"], msg=str(exc))])
    if doc is not None and not isinstance(doc, dict):
        return Validated(ok=False, errors=[ValidationItem(loc=["yaml"], msg="expected a mapping of id to proposal")])
    try:
        typed_items = proposals_from_yaml(text, originals)
    except ValidationError as exc:
        return Validated(ok=False, errors=_items(exc, ["yaml"]))
    return Validated(ok=True, proposals=[p.model_dump(mode="json") for p in typed_items])


def to_yaml(proposals: list[Proposal]) -> str:
    return proposals_to_yaml(proposals)


def typed(v: Validated) -> list[Proposal]:
    return [Proposal.model_validate(p) for p in v.proposals]
```

`CalendarChange.model_json_schema()` nests `PlannedSession` under `$defs` because `workout: PlannedSession | None`; `Proposal`'s `changes` is `list[CalendarChange] | list[NutritionChange]`, so `s["proposal"]["$defs"]` carries both change models too. The `include_url=False` keeps pydantic's docs links out of `msg`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_review.py -q`
Expected: `6 passed`. If `test_validate_json_reports_loc_and_msg_per_error`'s `day` assertion fails because pydantic reports the bad date under `changes.0.day` with a union tag, print `v.errors` and adjust the assertion to the actual `loc` shape (the requirement is that the loc names index 1, `changes`, 0 and `day`).

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/review.py packages/tri-web/tests/test_review.py
git commit -m "feat(web): review schema and one validation path for JSON and YAML edits"
```

---

### Task 8: The app, the coach routes, the system route, and the route tests

**Files:**
- Create: `packages/tri-web/src/tri_web/schemas.py`, `packages/tri-web/src/tri_web/app.py`, `packages/tri-web/src/tri_web/routes/__init__.py` (empty), `packages/tri-web/src/tri_web/routes/coach.py`, `packages/tri-web/src/tri_web/routes/system.py`
- Test: `packages/tri-web/tests/conftest.py`, `packages/tri-web/tests/test_routes_coach.py`, `packages/tri-web/tests/test_routes_system.py`

**Interfaces:**
- Consumes: `Runtime`, `cfg` (Task 4); `Busy`, `start_turn`, `sse_response` (Task 5); `ThreadView`, `thread_snapshot` (Task 6); `schema`, `validate_json`, `validate_yaml`, `to_yaml`, `typed`, `Validated` (Task 7).
- Produces: `tri_web.app.create_app(runtime: Runtime | None) -> FastAPI`, `runtime_of(request) -> Runtime`; `tri_web.schemas`: `TurnIn(text)`, `ReviewIn(action, note, proposals)`, `ValidateIn(proposals | yaml)`, `SchemaOut`, `YamlOut(yaml)`, `StatusOut(live, tools, ready, thread, running)`, `NoReview`, `EditRejected(errors)`. Routes under `/api/coach`: `GET /thread`, `POST /turns`, `POST /review`, `GET /review/schema`, `POST /review/validate`, `GET /review/yaml`; under `/api/system`: `GET /status`. Test fixtures: `nocommit`, `mem_store`, `runtime` (factory), `client` (factory), `parse_sse`.

- [ ] **Step 1: Write the fixtures**

`packages/tri-web/tests/conftest.py`:

```python
"""A Runtime over the rolled-back test database, scripted models and an in-memory checkpointer;
an httpx client over the ASGI app; an SSE parser for the streamed bodies."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from tri_coach.graph.checkpointer import make_serde
from tri_coach.graph.graph import build_graph
from tri_coach.servers import Servers
from tri_coach.testing import make_test_deps
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel
from tri_planning.testing import MONDAY, NoCommit
from tri_web.app import create_app
from tri_web.config import WebSettings
from tri_web.runtime import Runtime


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def mem_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def runtime(nocommit, mem_store) -> Callable[..., Runtime]:
    def _make(
        *,
        coach: list[Any] | None = None,
        planning: list[Any] | None = None,
        nutrition: list[Any] | None = None,
        analyst: list[Any] | None = None,
        tp: Any = None,
        today: date = MONDAY,
    ) -> Runtime:
        deps = make_test_deps(
            nocommit,
            coach=ScriptedChatModel(script=coach or []),
            planning=ScriptedChatModel(script=planning or []),
            nutrition=ScriptedChatModel(script=nutrition or []),
            analyst=ScriptedChatModel(script=analyst or []),
            tp=tp,
            today=today,
        )
        graph = build_graph(deps, InMemorySaver(serde=make_serde()), mem_store)
        settings = WebSettings(
            _env_file=None, anthropic_api_key="test-key", database_url=Settings().test_database_url
        )
        return Runtime(
            settings=settings,
            graph=graph,
            store=mem_store,
            servers=Servers(),
            connect=lambda: contextlib.nullcontext(nocommit),
            live=False,
            today=lambda: today,
        )

    return _make


@pytest.fixture
def client() -> Callable[[Runtime], contextlib.AbstractAsyncContextManager[httpx.AsyncClient]]:
    @contextlib.asynccontextmanager
    async def _open(rt: Runtime) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=create_app(rt), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://tri-web") as c:
            yield c

    return _open


def parse_sse(text: str) -> list[tuple[str, Any]]:
    """[(event name, parsed data)] from a text/event-stream body."""
    out: list[tuple[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append((name, json.loads("\n".join(data))))
    return out
```

`make_test_deps` gives `deps.connect = nullcontext(nocommit)`, and the graph's `apply` node commits through it; `NoCommit.commit` is a no-op, so nothing persists.

- [ ] **Step 2: Write the failing route tests**

`packages/tri-web/tests/test_routes_coach.py`:

```python
"""Coach routes over the fake runtime: a turn streams token and done; a proposing coach pauses;
approve resumes and streams the apply report; busy is 409; an edit is validated server-side; a
disconnect lets the run finish."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_planning.testing import FakeTp
from tri_web.events import start_turn
from tri_web.thread import thread_snapshot

from .conftest import parse_sse

pytestmark = pytest.mark.db


def proposing(nocommit):
    """Runtime kwargs for a coach that consults planning and proposes moving w1; the FakeTp is
    returned too so tests can assert on the writes apply made."""
    seed_active_plan(nocommit)
    tp = FakeTp()
    kwargs = {
        "tp": tp,
        "coach": [consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        "planning": [move_call(), AIMessage(content="ok")],
    }
    return tp, kwargs


async def test_empty_thread(runtime, client):
    async with client(runtime()) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 200
    assert r.json() == {"messages": [], "paused": None, "held": None, "stuck": False, "running": None}


async def test_a_turn_streams_tokens_then_done_and_the_thread_shows_it(runtime, client):
    rt = runtime(coach=[AIMessage(content="Hello athlete.")])
    async with client(rt) as c:
        r = await c.post("/api/coach/turns", json={"text": "hi"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.text)
        assert events[0][0] == "token" and events[0][1]["where"] == "coach"
        assert "".join(d["text"] for n, d in events if n == "token") == "Hello athlete."
        assert events[-1] == ("done", {"final_text": "Hello athlete.", "paused": False})
        thread = (await c.get("/api/coach/thread")).json()
    roles = [m["role"] for m in thread["messages"]]
    assert roles == ["user", "assistant"] and thread["messages"][1]["text"] == "Hello athlete."
    assert not rt.lock.locked() and rt.running is None


async def test_a_proposing_coach_streams_the_interrupt_and_pauses(nocommit, runtime, client):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        events = parse_sse((await c.post("/api/coach/turns", json={"text": "my knee hurts"})).text)
        names = [n for n, _ in events]
        assert "tool_call" in names and "consult" in names and "interrupt" in names
        interrupt = next(d for n, d in events if n == "interrupt")
        assert interrupt["narration"] == "Move it." and interrupt["proposals"][0]["id"] == "p1"
        assert events[-1][1]["paused"] is True
        thread = (await c.get("/api/coach/thread")).json()
        assert thread["paused"]["proposals"][0]["domain"] == "planning" and thread["stuck"] is False
        # approve resumes the run and streams the apply report
        r = await c.post("/api/coach/review", json={"action": "approve"})
        events = parse_sse(r.text)
        assert ("report", {"text": "planning: applied 1"}) in events
        assert events[-1][1]["paused"] is False
        assert (await c.get("/api/coach/thread")).json()["paused"] is None
    assert [call[0] for call in tp.calls] == ["tp_update_workout"]


async def test_review_without_a_paused_review_is_409(runtime, client):
    async with client(runtime()) as c:
        r = await c.post("/api/coach/review", json={"action": "approve"})
    assert r.status_code == 409 and r.json() == {"reason": "no_review"}


async def test_busy_is_409_with_the_running_kind(runtime, client):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "checkin"
    try:
        async with client(rt) as c:
            r = await c.post("/api/coach/turns", json={"text": "hi"})
            assert r.status_code == 409 and r.json() == {"running": "checkin"}
            r = await c.post("/api/coach/review", json={"action": "approve"})
            assert r.status_code == 409 and r.json() == {"running": "checkin"}
            assert (await c.get("/api/coach/thread")).json()["running"] == "checkin"
    finally:
        rt.lock.release()


async def test_edit_is_validated_and_resumes_with_typed_proposals(nocommit, runtime, client):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        paused = (await c.get("/api/coach/thread")).json()["paused"]
        edited = paused["proposals"]
        edited[0]["changes"][0]["op"] = "teleport"
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": edited})
        assert r.status_code == 422 and r.json()["detail"] == "edit rejected"
        assert any("op" in e["loc"] for e in r.json()["errors"])
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": []})
        assert r.status_code == 422 and "reject instead" in r.json()["detail"]
        edited[0]["changes"][0]["op"] = "move"
        edited[0]["changes"][0]["new_date"] = "2026-09-19"
        r = await c.post("/api/coach/review", json={"action": "edit", "proposals": edited})
        assert r.status_code == 200
        assert ("report", {"text": "planning: applied 1"}) in parse_sse(r.text)
    assert tp.calls[0][0] == "tp_update_workout"
    assert "2026-09-19" in str(tp.calls[0][1])  # the moved date reached TrainingPeaks


async def test_reject_with_a_note(nocommit, runtime, client):
    _tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        r = await c.post("/api/coach/review", json={"action": "reject", "note": "keep Wednesday"})
        assert r.status_code == 200 and parse_sse(r.text)[-1][0] == "done"
        thread = (await c.get("/api/coach/thread")).json()
    assert thread["paused"] is None
    assert any(m["role"] == "report" and "keep Wednesday" in m["text"] for m in thread["messages"])


async def test_review_helpers(nocommit, runtime, client):
    _tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        assert set((await c.get("/api/coach/review/schema")).json()) == {"proposal", "planning_change", "nutrition_change"}
        assert (await c.get("/api/coach/review/yaml")).status_code == 409
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        text = (await c.get("/api/coach/review/yaml")).json()["yaml"]
        assert text.startswith("p1:")
        r = await c.post("/api/coach/review/validate", json={"yaml": text.replace("op: move", "op: teleport")})
        assert r.status_code == 200 and r.json()["ok"] is False
        r = await c.post("/api/coach/review/validate", json={"yaml": text})
        assert r.json()["ok"] is True and r.json()["proposals"][0]["id"] == "p1"
        paused = (await c.get("/api/coach/thread")).json()["paused"]
        r = await c.post("/api/coach/review/validate", json={"proposals": paused["proposals"]})
        assert r.json()["ok"] is True
        r = await c.post("/api/coach/review/validate", json={})
        assert r.status_code == 422


async def test_a_disconnect_mid_stream_lets_the_run_finish(runtime):
    rt = runtime(coach=[AIMessage(content="Still here.")])
    run = await start_turn(rt, {"messages": [HumanMessage("hi")]}, kind="turn")
    first = await run.queue.get()  # the browser read one event, then closed the tab
    assert first is not None
    del run.queue  # nobody reads the rest
    await asyncio.wait_for(rt.turn_task, timeout=10)
    view = await thread_snapshot(rt.graph, rt.thread_id, running=rt.running)
    assert [m.role for m in view.messages] == ["user", "assistant"]
    assert view.messages[1].text == "Still here." and not rt.lock.locked()


async def test_route_errors_return_detail_only(runtime, client):
    rt = runtime()

    async def boom(config):
        raise RuntimeError("psycopg went away")

    rt.graph.aget_state = boom  # type: ignore[method-assign]
    async with client(rt) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "RuntimeError: psycopg went away"}
```

`FakeTp` records `(tool, args)` per call; `test_graph_apply.py` shows a `move` reaches TrainingPeaks as one `tp_update_workout` call carrying the new date, which the edit test checks by substring.

`packages/tri-web/tests/test_routes_system.py`:

```python
import pytest

pytestmark = pytest.mark.db


async def test_status_reports_live_tools_readiness_and_thread(runtime, client, monkeypatch):
    monkeypatch.setattr("tri_web.routes.system.checkpointer_ready", lambda url: True)
    monkeypatch.setattr("tri_web.routes.system.store_ready", lambda url: False)
    async with client(runtime()) as c:
        r = await c.get("/api/system/status")
    assert r.status_code == 200
    assert r.json() == {
        "live": False,
        "tools": [],
        "ready": {"api_key": True, "checkpointer": True, "store": False},
        "thread": "coach",
        "running": None,
    }
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_routes_coach.py packages/tri-web/tests/test_routes_system.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.app'` (from conftest).

- [ ] **Step 4: Write `schemas.py`**

```python
"""Request and response models for the routes; the frontend's types are generated from the
OpenAPI document these produce."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tri_web.review import ValidationItem


class TurnIn(BaseModel):
    text: str = Field(min_length=1)


class ReviewIn(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    proposals: list[dict[str, Any]] | None = None


class ValidateIn(BaseModel):
    proposals: list[dict[str, Any]] | None = None
    yaml: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> ValidateIn:
        if (self.proposals is None) == (self.yaml is None):
            raise ValueError("send exactly one of proposals or yaml")
        return self


class SchemaOut(BaseModel):
    proposal: dict[str, Any]
    planning_change: dict[str, Any]
    nutrition_change: dict[str, Any]


class YamlOut(BaseModel):
    yaml: str


class Readiness(BaseModel):
    api_key: bool
    checkpointer: bool
    store: bool


class StatusOut(BaseModel):
    live: bool
    tools: list[str]
    ready: Readiness
    thread: str
    running: str | None


class NoReview(Exception):
    """Nothing is paused at the gate."""


class EditRejected(Exception):
    def __init__(self, errors: list[ValidationItem]) -> None:
        super().__init__("edit rejected")
        self.errors = errors
```

- [ ] **Step 5: Write `app.py`**

```python
"""create_app(runtime): the FastAPI app over one Runtime. Error bodies carry a message only."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from tri_web.events import Busy
from tri_web.routes import coach, system
from tri_web.runtime import Runtime
from tri_web.schemas import EditRejected, NoReview


def runtime_of(request: Request) -> Runtime:
    rt: Runtime | None = request.app.state.runtime
    if rt is None:
        raise HTTPException(status_code=503, detail="runtime not open")
    return rt


def create_app(runtime: Runtime | None) -> FastAPI:
    app = FastAPI(title="tri-web", version="0.1.0")
    app.state.runtime = runtime
    app.include_router(coach.router, prefix="/api/coach", tags=["coach"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])

    @app.exception_handler(Busy)
    async def busy(request: Request, exc: Busy) -> JSONResponse:
        return JSONResponse({"running": exc.running}, status_code=409)

    @app.exception_handler(NoReview)
    async def no_review(request: Request, exc: NoReview) -> JSONResponse:
        return JSONResponse({"reason": "no_review"}, status_code=409)

    @app.exception_handler(EditRejected)
    async def edit_rejected(request: Request, exc: EditRejected) -> JSONResponse:
        return JSONResponse(
            {"detail": "edit rejected", "errors": [e.model_dump() for e in exc.errors]},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # uvicorn's error log keeps the traceback; the body never does
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)

    return app
```

- [ ] **Step 6: Write `routes/coach.py`**

```python
"""The conversation: thread snapshot, a streamed turn, the review gate and its helpers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from starlette.responses import StreamingResponse

from tri_coach.models import Proposal, ReviewDecision
from tri_coach.repl import paused_review
from tri_web import review as R
from tri_web.events import Busy, sse_response, start_turn
from tri_web.runtime import Runtime, cfg
from tri_web.schemas import EditRejected, NoReview, ReviewIn, SchemaOut, TurnIn, ValidateIn, YamlOut
from tri_web.thread import ThreadView, thread_snapshot

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


async def _paused_proposals(rt: Runtime) -> list[Proposal]:
    paused = paused_review(await rt.graph.aget_state(cfg(rt)))
    if paused is None:
        raise NoReview()
    return [Proposal.model_validate(p) for p in paused.get("proposals", [])]


@router.get("/thread", response_model=ThreadView)
async def get_thread(request: Request) -> ThreadView:
    rt = _runtime(request)
    return await thread_snapshot(rt.graph, rt.thread_id, running=rt.running)


@router.post("/turns")
async def post_turn(body: TurnIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    run = await start_turn(rt, {"messages": [HumanMessage(body.text)]}, kind="turn")
    return sse_response(run)


@router.post("/review")
async def post_review(body: ReviewIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await _paused_proposals(rt)  # 409 no_review when nothing is paused
    decision = ReviewDecision(action=body.action, note=body.note)
    if body.action == "edit":
        checked = R.validate_json(body.proposals or [])
        if not checked.ok:
            raise EditRejected(checked.errors)
        if not checked.proposals:
            raise HTTPException(status_code=422, detail="edit needs at least one proposal; reject instead")
        decision = ReviewDecision(action="edit", proposals=R.typed(checked))
    resume: Command[Any] = Command(resume=decision.model_dump(mode="json", exclude_none=True))
    run = await start_turn(rt, resume, kind="review")
    return sse_response(run)


@router.get("/review/schema", response_model=SchemaOut)
async def get_schema() -> SchemaOut:
    return SchemaOut(**R.schema())


@router.post("/review/validate", response_model=R.Validated)
async def post_validate(body: ValidateIn, request: Request) -> R.Validated:
    if body.proposals is not None:
        return R.validate_json(body.proposals)
    originals = await _paused_proposals(_runtime(request))
    return R.validate_yaml(body.yaml or "", originals)


@router.get("/review/yaml", response_model=YamlOut)
async def get_yaml(request: Request) -> YamlOut:
    return YamlOut(yaml=R.to_yaml(await _paused_proposals(_runtime(request))))
```

The lazy import of `runtime_of` avoids the `app -> routes -> app` import cycle; alternatively move `runtime_of` into `runtime.py` and import it from there in both places (either is fine; pick one and keep it).

- [ ] **Step 7: Write `routes/system.py`**

```python
"""Readiness as the CLI checks it, the bound live tools, and what is running."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from tri_coach.graph.checkpointer import checkpointer_ready
from tri_nutrition.store import store_ready
from tri_web.schemas import Readiness, StatusOut

router = APIRouter()


@router.get("/status", response_model=StatusOut)
async def get_status(request: Request) -> StatusOut:
    from tri_web.app import runtime_of

    rt = runtime_of(request)
    url = rt.settings.database_url
    checkpointer, store = await asyncio.gather(
        asyncio.to_thread(checkpointer_ready, url), asyncio.to_thread(store_ready, url)
    )
    return StatusOut(
        live=rt.live,
        tools=[t.name for t in rt.servers.garmin_tools + rt.servers.tp_tools],
        ready=Readiness(
            api_key=bool(rt.settings.anthropic_api_key), checkpointer=checkpointer, store=store
        ),
        thread=rt.thread_id,
        running=rt.running,
    )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web -q`
Expected: all pass. Two things to check if not:
- The `ValidateIn` with `{}` returns 422 through FastAPI's request validation (the `model_validator` raises `ValueError`, which FastAPI reports as 422 with its own `detail` list). The test only asserts the status.
- `test_a_proposing_coach_streams_the_interrupt_and_pauses` depends on `seed_active_plan` and `FakeTp` exactly as `test_graph.py::test_no_checkpoint_deserializes_an_unregistered_type` does; if the apply report differs, copy the string that test's graph produces.

- [ ] **Step 9: Definition of done, then commit**

```bash
git add packages/tri-web
git commit -m "feat(web): FastAPI app with thread, turns, review and status routes over one runtime"
```

---

### Task 9: `tri-web serve`, `tri-web openapi`, package README, root README

**Files:**
- Create: `packages/tri-web/src/tri_web/cli.py`, `packages/tri-web/README.md`
- Modify: `README.md` (package table row, Run line, Layout line)
- Test: `packages/tri-web/tests/test_cli.py`

**Interfaces:**
- Consumes: `open_runtime`, `create_app`, `get_web_settings`.
- Produces: `tri_web.cli.app` (Typer) with `serve [--no-live] [--host] [--port]` and `openapi`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_cli.py`:

```python
import json

from typer.testing import CliRunner

from tri_web.cli import app


def test_help_lists_the_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("serve", "openapi"):
        assert name in result.output


def test_openapi_prints_the_document_with_the_routes():
    result = CliRunner().invoke(app, ["openapi"])
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert "/api/coach/turns" in doc["paths"] and "/api/system/status" in doc["paths"]
    assert "ThreadView" in doc["components"]["schemas"]


def test_serve_exits_2_when_not_ready(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from tri_web import config

    config.get_web_settings.cache_clear()
    result = CliRunner().invoke(app, ["serve", "--no-live"])
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY is not set" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.cli'`.

- [ ] **Step 3: Write `cli.py`**

```python
"""`tri-web serve`: open the coach runtime, serve the API (and web/dist when built) on localhost.
`tri-web openapi`: print the OpenAPI document the frontend's types are generated from."""

from __future__ import annotations

import asyncio
import json

import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console

from tri_web.config import WebSettings, get_web_settings

load_dotenv()

app = typer.Typer(help="Local web UI over the head coach", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """tri-web server."""


def _log(m: str) -> None:
    console.print(m, markup=False, highlight=False, soft_wrap=True)


@app.command()
def serve(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
    host: str | None = typer.Option(None, "--host", help="Bind address (default TRI_WEB_HOST)"),
    port: int | None = typer.Option(None, "--port", help="Port (default TRI_WEB_PORT, 8321)"),
) -> None:
    """Serve the coach API on localhost; the built frontend too when web/dist exists."""
    settings = get_web_settings()
    raise typer.Exit(
        code=asyncio.run(
            _serve(
                settings,
                no_live=no_live,
                host=host or settings.tri_web_host,
                port=port or settings.tri_web_port,
            )
        )
    )


async def _serve(settings: WebSettings, *, no_live: bool, host: str, port: int) -> int:
    from tri_web.app import create_app
    from tri_web.runtime import open_runtime

    try:
        async with open_runtime(settings, no_live=no_live, log=_log) as rt:
            server = uvicorn.Server(
                uvicorn.Config(create_app(rt), host=host, port=port, log_level="info")
            )
            _log(f"tri-web: http://{host}:{port}  (thread coach, live={'no' if no_live else 'yes'})")
            await server.serve()
    except RuntimeError as exc:
        console.print(str(exc), style="red")
        return 2
    return 0


@app.command()
def openapi() -> None:
    """Print the OpenAPI document (web/src/api/types.ts is generated from it)."""
    from tri_web.app import create_app

    typer.echo(json.dumps(create_app(None).openapi(), indent=2))


if __name__ == "__main__":
    app()
```

`uvicorn.Server.serve()` installs its own signal handlers; Ctrl-C ends `serve()`, the `async with` closes the exit stack, and the MCP processes end with the server (spec §6.1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_cli.py -q`
Expected: `3 passed`. If `test_serve_exits_2_when_not_ready` sees a cached settings object with the key set, the `cache_clear()` line above handles it; `WebSettings` reads `ANTHROPIC_API_KEY=""` as an empty string, which `ready()` treats as missing.

- [ ] **Step 5: Package README**

`packages/tri-web/README.md`:

````markdown
# tri-web

A local web UI over the head coach. The server (`tri_web`, FastAPI on 127.0.0.1:8321) opens the coach graph the way `tri-coach chat` does: the same thread `coach`, the same Postgres checkpointer and store, so the terminal and the browser see one conversation and one memory. The React app lives in `web/` (plan 3).

Spec: `docs/superpowers/specs/2026-09-14-tri-web-design.md`.

## Run

```
uv run tri-web serve [--no-live] [--port 8321]   # API, plus web/dist when built
uv run tri-web openapi > web/openapi.json        # the document web/src/api/types.ts is generated from
```

Startup takes 10 to 20 s while the MCP servers launch; `--no-live` skips them and `GET /api/system/status` reports `live: false`. Readiness failures print the CLI's hints and exit 2.

## Routes (all under `/api`)

| Route | Body | Returns |
|---|---|---|
| `GET /coach/thread` | | `ThreadView`: messages, `paused`, `held`, `stuck`, `running` |
| `POST /coach/turns` | `{text}` | SSE `TurnEvent`s; `409 {running}` when busy |
| `POST /coach/review` | `{action, note?, proposals?}` | SSE; `409 {reason: "no_review"}`; `422 {detail: "edit rejected", errors}` |
| `GET /coach/review/schema` | | `{proposal, planning_change, nutrition_change}` JSON schemas |
| `POST /coach/review/validate` | `{proposals}` or `{yaml}` | `{ok, proposals, errors: [{loc, msg}]}` |
| `GET /coach/review/yaml` | | `{yaml}` of the paused proposals |
| `GET /system/status` | | `{live, tools, ready: {api_key, checkpointer, store}, thread, running}` |

Events: `token {where, text}`, `tool_call {where, name, args}`, `tool_result {where, name, chars}`, `consult {domain, text}`, `report {text}`, `interrupt {narration, proposals}`, `error {message}`, `done {final_text, paused}`. `where` is `coach`, `planning`, `nutrition` or `analyst`.

One lock: a second turn, review, check-in or reset while one runs is refused with 409. A run continues after the browser disconnects; the lock releases when it finishes.

## Layout

```
src/tri_web/config.py    WebSettings (host, port, dist)
src/tri_web/runtime.py   Runtime, open_runtime
src/tri_web/events.py    TurnEmitter, start_turn, SSE framing
src/tri_web/thread.py    UiMessage, ThreadView, thread_snapshot
src/tri_web/review.py    schema, validate_json, validate_yaml, to_yaml
src/tri_web/schemas.py   request/response models, NoReview, EditRejected
src/tri_web/app.py       create_app
src/tri_web/routes/      coach.py, system.py
src/tri_web/cli.py       serve, openapi
```

## Tests

`uv run pytest packages/tri-web` (db tests skip when Postgres is down). Route tests run the graph over scripted models and an in-memory checkpointer through `httpx.ASGITransport`; no Anthropic call, no MCP server.
````

- [ ] **Step 6: Root README**

Add to the package table after the `tri-coach` row:

```markdown
| `packages/tri-web` | `tri_web` | `tri-web serve \| openapi` | Local web UI over the coach: FastAPI server streaming the coach graph on localhost; React app in `web/`. |
```

Add to the Run block after the `tri-coach reset` line:

```
uv run tri-web serve [--no-live] [--port 8321]   # the coach in the browser, same thread and memory as tri-coach chat
```

Add to the Layout block after the `tri-wellness` line:

```
packages/tri-web/       src/tri_web/{config,cli,app,runtime,events,thread,review,schemas,routes}
```

Copy both READMEs to the vault as `readme.md` under the matching paths.

- [ ] **Step 7: Definition of done, then commit**

Run the full DoD sequence, then a manual smoke (needs `.env` with a key and the checkpoint tables): `uv run tri-web serve --no-live`, then in another shell:

```bash
curl -s localhost:8321/api/system/status
curl -s localhost:8321/api/coach/thread
curl -N -s -X POST localhost:8321/api/coach/turns -H 'content-type: application/json' -d '{"text":"hello"}'
```

The third call streams `token` events from the real model and ends with `done`. Record the outcome in the commit message body (streamed or not, and why if not).

```bash
git add packages/tri-web README.md
git commit -m "feat(web): tri-web serve and openapi; package and root README"
```

---

## Self-review against the spec

**Spec coverage for this plan's slice:**
- §1 bridge (FastAPI sharing the CLI's thread, checkpointer and store): Task 4. Concurrency (one lock, 409, a run outlives the disconnect): Tasks 5, 8. Streaming (SSE over POST, events mirror the printer): Tasks 3, 5, 8. Serving (`tri-web serve [--no-live] [--port]`): Task 9.
- §2 feasibility items 2 to 6 are the facts Tasks 3 to 8 build on; `ready` lifted (Task 2).
- §4 layout: `pyproject.toml`, `cli.py`, `config.py`, `app.py`, `runtime.py`, `events.py`, `thread.py`, `review.py`, `schemas.py`, `routes/coach.py`, `routes/system.py`, the matching tests. `today.py`, `jobs.py`, `routes/today.py`, `routes/jobs.py`, `routes/memory.py`, `routes/review.py` (folded into `routes/coach.py` here; plan 2 leaves it there) are plan 2.
- §5.1 `Runtime` and `open_runtime` (Task 4; `jobs` is added by plan 2). §5.2 rows `thread`, `turns`, `review`, `review/schema`, `review/validate`, `review/yaml`, `system/status` (Task 8); `today`, `memory`, `reset`, `jobs/*` are plan 2. §5.3 every event (Tasks 3, 5). §5.4 `UiMessage` (Task 6).
- §6.1 startup, `--no-live`, shutdown, readiness exit 2 (Tasks 4, 9). §6.3 the turn (Tasks 5, 8). §6.4 thread state, `held`, `stuck`, `no_review` (Tasks 6, 8). §6.5 server side of the gate: schema, validate (JSON and YAML), yaml, the guard on `POST /coach/review` (Tasks 7, 8). §6.8 error events, 409 bodies, `{detail}` only, "frontend not built" log line is plan 2 with the static mount.
- §8 server tests: `test_runtime.py`, `test_events.py`, `test_thread.py`, `test_review.py`, `test_routes_coach.py` (turn, interrupt, approve, 409, disconnect), `test_cli.py` (Tasks 4 to 9). `test_today.py`, `test_jobs.py`, `test_routes_memory.py` are plan 2.

**Placeholder scan:** no "TBD", "similar to" or "add handling"; every code step shows the code. Two steps name a fallback if an assertion's exact `loc` or arg key differs, with the requirement stated.

**Type consistency:**
- `run_turn(..., printer=)` (Task 3) is what `events._produce` calls (Task 5); `TurnEmitter(TurnPrinter)` overrides `print_event(kind, payload)` with the same signature.
- `Runtime` fields used by Tasks 5, 6, 8, 9: `graph`, `thread_id`, `lock`, `running`, `turn_task`, `settings`, `servers`, `live`; the test `SimpleNamespace` in `test_events.py` carries exactly the five `start_turn` touches.
- `ReviewPayload`, `ThreadView` (Task 6) are the response model of `GET /thread` (Task 8).
- `Validated`, `ValidationItem`, `typed` (Task 7) are used by `EditRejected` (Task 8 schemas) and `post_review`.
- `Busy.running`, `NoReview`, `EditRejected.errors` match the three exception handlers in `create_app`.
- `cfg(rt)` (Task 4) is used by `_paused_proposals` (Task 8).
