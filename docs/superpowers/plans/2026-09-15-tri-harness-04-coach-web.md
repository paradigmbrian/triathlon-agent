# tri-harness Plan 4 of 4: tri-coach and tri-web on the harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete tri-coach's own copies of the harness and point tri-coach and tri-web at `tri_core.harness`. The copies are `graph/checkpointer.py`, `text.py`, `make_subagent` and `one_tool_call_at_a_time` in `graph/llm.py`, the handoff plumbing, the agent-as-tool skeletons, `text_of` and the body of `run_turn`. Nothing the athlete sees in the terminal or the browser changes.

**Architecture:** This plan only removes code and redirects imports; nothing new is built. Six tasks each move one concern:
- a description guard test
- persistence
- agent builders and `last_ai_text`
- handoffs
- the two agent tools
- the turn driver

Each task keeps the full suite green. The coach keeps its own `TurnClassifier`, `TurnPrinter` and a thin `run_turn` with today's signature, because `tri_web.events` depends on them. A final task proves no harness definition is left outside `tri_core/harness/`.

**Tech Stack:** Python 3.12, langchain 1.4.0, langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2, anthropic 1.4.0, pytest with `pytest-asyncio` in auto mode, `tri_core.testing.ScriptedChatModel`, and the React app in `web/` (Vite, TypeScript, ESLint, Vitest).

**Spec:** `docs/superpowers/specs/2026-09-15-tri-harness-design.md`. This plan implements §4 (the tri-coach and tri-web entries), §5.2–§5.7 as they apply to tri-coach and tri-web, §6, the plans 02–04 rules and the after-plan-04 checks in §7, and §9 item 4. The interfaces it consumes are the ones plan 01 (`docs/superpowers/plans/2026-09-15-tri-harness-01-core.md`) builds.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...` unless a step says `cd web`.
- **Prerequisites: plans 01, 02 and 03 are merged into `main`.** Check from the main checkout before creating the worktree. Every command must succeed:

  ```bash
  git log --oneline main | grep -E "tri-harness-0[123]|tri_core\.harness|harness" | head
  test -f packages/tri-core/src/tri_core/harness/turns.py
  test ! -e packages/tri-planning/src/tri_planning/graph/checkpointer.py
  test ! -e packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py
  test ! -e packages/tri-wellness/src/tri_wellness/graph/checkpointer.py
  test ! -e packages/tri-wellness/src/tri_wellness/agent.py
  ! grep -nE "def (open_store|store_ready)" packages/tri-nutrition/src/tri_nutrition/store.py
  grep -n "tri_core.harness" packages/tri-coach/src/tri_coach/graph/graph.py
  ```

  If any of them fails, stop and report which one.
- **Execute in a sibling worktree:** run `git worktree add ../triathlon_agent-harness-04 -b feat/tri-harness-04 main`, copy `.env`, then run `uv sync` and `cd web && npm ci`. Other Claude sessions share the main checkout.
- **Baseline:** in the worktree, before Task 1, record `uv run pytest -q` (call the passed count **B** and note the skipped count). Plan 02 ends at 947 passed and plan 03 at 946 passed, both with 6 skipped, so B is 946 unless something else has merged since. Use the recorded number either way. Also record `uv run pytest packages/tri-coach packages/tri-web -q` (on `main` 3a5a82c, before plans 01–03, this slice was `203 passed, 1 skipped`). Every task's expected count below is relative to **B**. The skipped count never changes.
- **Files this plan may touch:**
  - `packages/tri-coach/src/tri_coach/`: `graph/llm.py`, `graph/state.py`, `graph/checkpointer.py` (deleted), `graph/nodes/coach.py`, `graph/nodes/planning.py`, `graph/nodes/nutrition.py`, `text.py` (deleted), `tools/handoff.py`, `tools/analyst.py`, `tools/wellness.py`, `repl.py`, `cli.py`, `evals/target.py`
  - `packages/tri-coach/tests/`: `test_cli.py`, `test_graph.py`, `test_graph_apply.py`, `test_live.py`, `test_models.py`, `test_repl.py`, `test_resume.py`, `test_tools.py`
  - `packages/tri-web/src/tri_web/`: `thread.py`, `routes/system.py`, `runtime.py`
  - `packages/tri-web/tests/`: `conftest.py`, `test_runtime.py`
  - any markdown file the Task 7 grep finds

  Nothing under `tri-core`, `tri-analyze`, `tri-planning`, `tri-nutrition`, `tri-wellness` or `web/src`.
- **Behaviour does not change (spec §6).** That covers:
  - terminal output of `tri-coach chat` and `tri-coach check-in`, including every error sentence
  - tri-web's SSE event names and payloads, and its thread views
  - tool names, argument schemas and descriptions (`ask_analyst` and `ask_wellness` descriptions must match exactly)
  - coach middleware order `[one_tool_call_at_a_time, caching]`
  - the checkpoint serde allow-list
  - the Postgres objects the readiness checks probe
  - `SETUP_HINT` and `STORE_SETUP_HINT` text
  - thread ids, recursion limits (60 for a coach turn, 40 for each agent tool, 30 for the eval target) and tags
- **Rules for existing tests (spec §7), applied literally:**
  - Assertions and expected values are not edited.
  - Allowed edits: import lines; construction arguments of a moved function (`make_serde()` → `make_serde(STATE_TYPES)`, `open_checkpointer(url)` → `open_checkpointer(url, STATE_TYPES)`, `make_subagent(model, tools, "sys")` → `make_subagent(model, tools, "sys", middleware=[one_tool_call_at_a_time])`); string patch paths; a test spy that wraps a moved function forwarding keyword arguments it did not know about.
  - A test that only duplicates a tri-core harness test is deleted, and the task names the covering test.
  - Anything else is a stop condition (see the end of this plan).
- **The CLIs keep importing readiness helpers inside their function bodies,** so `monkeypatch.setattr("tri_core.harness.persistence.<name>", ...)` takes effect.
- **mypy runs with `strict = true`, which includes `no_implicit_reexport`.** When `tri_coach.repl` imports a name from the harness that other modules import from `tri_coach.repl`, it re-exports that name explicitly. Today that is only `Out`, which `tri_coach/checkin.py` uses: `from tri_core.harness.turns import Out as Out`. `tri_web/thread.py` imports `text_of` from the harness directly instead.
- **Commits:** Git commits are permitted (Brian's standing permission). Commit once per task on `feat/tri-harness-04`, and end every commit message with the `Co-Authored-By:` trailer of the session executing the plan.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages/tri-coach packages/tri-web`
  2. `uv run ruff check --fix packages/tri-coach packages/tri-web`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  Task 7 also runs, from `web/`: `npm run lint`, `npm run test` and `npm run build` (the scripts in `web/package.json` are `lint: eslint .`, `test: vitest run` and `build: tsc -b && vite build`). The only acceptable pytest warning is the existing one. Never add `# type: ignore`.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file created or edited in this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Facts verified while writing this plan (against `main` 3a5a82c, 2026-09-15)

1. **"Before" code** in each step is today's file with the changes plans 02 and 03 make to it, taken from those plans:
   - Plan 02: `tri_coach/tools/wellness.py` builds its agent with `build_chat_agent(model, tools, system_prompt=prompt, checkpointer=InMemorySaver())`, and `tri_wellness/agent.py` is deleted.
   - Plan 03 (`docs/superpowers/plans/2026-09-15-tri-harness-03-planning-nutrition.md`, Task 3 Steps 5–6):
     - In `tri_coach/cli.py`, `ready`, `_open_graph`, `_memory` and `reset_thread` take `open_store`, `store_ready` and `STORE_SETUP_HINT` from `tri_core.harness.persistence`, and the coach checkpointer imports are left for this plan. `_check_in` keeps `from tri_nutrition import store as S` for `S.get_profile`.
     - `tri_web/runtime.py` imports `open_store`, and `tri_web/routes/system.py` imports `store_ready`, from the harness.
     - `tri-coach/tests/test_cli.py` patches `"tri_core.harness.persistence.store_ready"`, and `tri-web/tests/test_runtime.py` imports `store_ready` from the harness.
     - `tri_coach/graph/graph.py` builds both subgraph serdes with harness `make_serde` and the planning and nutrition `STATE_TYPES`, so it needs no change in this plan.
2. **Importers of what this plan moves** (source and tests, every package, plus `scripts/` and the root `conftest.py`):
   - `tri_coach.graph.checkpointer`:
     - source: `tri_coach/cli.py:48,72,322`, `tri_web/routes/system.py:9`, `tri_web/runtime.py:55`
     - tests: `tri-coach/tests/test_cli.py:18,21` (string patch), `test_graph.py:11`, `test_graph_apply.py:8`, `test_live.py:12`, `test_models.py:7`, `test_resume.py:9`, `tri-web/tests/conftest.py:17`, `tri-web/tests/test_runtime.py:6`
   - `tri_coach.graph.llm.make_subagent`: `tri_coach/graph/nodes/coach.py:15`, `tri_coach/evals/target.py:20`, `tri-coach/tests/test_tools.py:11`. `tri-coach/tests/test_graph.py:186-193` and `test_graph_apply.py:173-179` monkeypatch `nodes.coach.make_subagent` with a three-argument spy.
   - `tri_coach.text.last_ai_text`: `graph/nodes/planning.py:15`, `graph/nodes/nutrition.py:20`, `tools/analyst.py:21`, `tools/wellness.py:19`, `evals/target.py:22`, `tri-coach/tests/test_tools.py:13`
   - `tri_coach.tools.handoff.turn_messages`: `tri-coach/tests/test_tools.py:15` only.
   - `tri_coach.repl.text_of`: `tri_web/thread.py:13`, `tri-coach/tests/test_repl.py:20`.
   - `tri_coach.repl.Out`: only `tri_coach/checkin.py:18`; no tri-web module imports it. `repl.py` re-exports it explicitly, so `checkin.py` is not edited.
   - `tri_coach.repl.run_turn` and `TurnPrinter`: `tri_web/events.py:16`, `tri_coach/checkin.py:18`, `tri-coach/tests/test_repl.py`. Both names stay defined in `repl.py`.
   - `tri-coach/tests/test_evals.py:16-17` imports `make_analyst_tool` and `make_wellness_tool`, and `test_stub_descriptions_match_the_real_tools` compares their descriptions with the literal docstrings in `evals/target.py`. It needs no edit and keeps guarding descriptions.
   - `tri-web/tests/test_routes_system.py` patches `"tri_web.routes.system.checkpointer_ready"` and `"tri_web.routes.system.store_ready"`. These stay valid because `system.py` keeps both names at module level.
   - `tri-coach/tests/test_servers.py` patches `"tri_coach.servers.open_live_servers"`, which this plan does not touch.
3. **Places the spec's lists were incomplete:**
   - `tri_coach/evals/target.py` builds the eval's agent with the coach's `make_subagent`, which today always includes `one_tool_call_at_a_time`. It must pass `middleware=[one_tool_call_at_a_time]` to keep eval behaviour.
   - `tri-coach/tests/test_tools.py::outer_graph` relies on the same default and must pass the middleware.
   - The spies in `test_graph.py::_recording` and in `test_graph_apply.py::test_partial_apply_keeps_the_remainder_pending_and_shows_it_next_turn` take `(model, tools, system_prompt)` and must forward `**kwargs`.
   - `tri_coach/checkin.py` imports `Out` from `repl`. Under mypy strict that needs the explicit `Out as Out` re-export in `repl.py`.
   - `tri_web/thread.py` imports `text_of` from `repl`, which would be the same implicit re-export, so it imports from the harness instead.
4. **Today's descriptions,** probed with `make_analyst_tool(...)` and `make_wellness_tool(...)` on `main`:
   - `ask_analyst`: `"Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,\nlogged intake against nutrition targets, or how training compares to plan. It reads the\ndatabase and the devices; it changes nothing. Ask one specific question at a time."`
   - `ask_wellness`: `"Ask the lab interpreter about the athlete's lab panels: a marker's value against its\nfunctional range, what is outside optimal and why, the retest plan, supplements, or\nwhether a symptom could be lab-related. It reads stored panels and reports; it changes\nnothing. Ask one specific question at a time."`
   - Both schemas are `{"title": <name>, "required": ["question"], "properties": {"question": {"title": "Question", "type": "string"}}}`, plus the description.
5. **Failure and empty sentences today:**
   - analyst: `f"The analyst failed ({type(exc).__name__}: {exc}); do not guess at the data it could not read."` and `"The analyst returned no answer; ask a narrower question."`
   - wellness: `f"The lab interpreter failed ({type(exc).__name__}: {exc}); answer without lab data."` and `"The lab interpreter returned no answer; ask a narrower question."`
   - Both recursion limits are 40. Both run the context load inside the `try`.
6. **`tri_coach.repl.run_turn` today:** config `{"configurable": {"thread_id": ...}, "recursion_limit": 60}` plus `"tags"` when given. It catches `RateLimitError`, `APIStatusError`, `APIConnectionError` and then `Exception` with the sentence `the turn failed: <Type>: <exc>`. Each failure sets `printer.error` to `\n[<sentence>]\n` and prints it. `tri_web.events._produce` strips the newlines and brackets with `error_message`. `stream_turn(..., subgraphs=True, catch_all="the turn failed")` plus `format_failure` produce the same strings (plan 01 Task 6).
7. **No README or other markdown outside `docs/superpowers/`** names `tri_coach/text.py`, `tri_coach/graph/checkpointer.py`, `tri_coach.text` or `tri_coach/graph/llm.py`. The only markdown hit for a moved name is `packages/tri-analyze/README.md:115` (`repl.py text_of, ...`), which is plan 02's. `packages/tri-coach/README.md:44-52` describes the handoff and parallel-call rules without file names, and they stay true.
8. **Duplicate-only tests this plan deletes,** confirmed on `main` as collected test ids:
   - `tri-coach/tests/test_repl.py::test_text_of_joins_text_blocks`
   - `tri-coach/tests/test_tools.py::test_turn_messages_is_everything_after_the_last_human_message`
   - `tri-coach/tests/test_tools.py::test_last_ai_text_takes_the_last_answer_without_tool_calls`

---

## File Structure

```
packages/tri-coach/src/tri_coach/
  graph/state.py          Task 2: STATE_TYPES moves here from graph/checkpointer.py
  graph/checkpointer.py   Task 2: deleted
  cli.py                  Task 2: checkpointer imports from the harness, with STATE_TYPES
  graph/llm.py            Task 3: make_subagent and one_tool_call_at_a_time removed; make_model stays
  graph/nodes/coach.py    Task 3: harness make_subagent with middleware=[one_tool_call_at_a_time]
  graph/nodes/planning.py Task 3: last_ai_text from the harness
  graph/nodes/nutrition.py Task 3: last_ai_text from the harness
  evals/target.py         Task 3: harness make_subagent (with the middleware) and last_ai_text
  text.py                 Task 3: deleted
  tools/handoff.py        Task 4: _consult and propose_changes call harness handoff()
  tools/analyst.py        Task 3 (import), Task 5: prepare + agent_tool
  tools/wellness.py       Task 3 (import), Task 5: prepare + agent_tool
  repl.py                 Task 6: text_of and Out (re-exported) from the harness; run_turn on stream_turn
packages/tri-web/src/tri_web/
  routes/system.py        Task 2: checkpointer_ready from the harness
  runtime.py              Task 2: open_checkpointer from the harness, with STATE_TYPES
  thread.py               Task 6: text_of from the harness
packages/tri-coach/tests/
  test_tools.py           Task 1 (description guard), Task 3, Task 4
  test_cli.py, test_graph.py, test_graph_apply.py, test_live.py, test_models.py, test_resume.py   Task 2
  test_graph.py, test_graph_apply.py   Task 3 (spies)
  test_repl.py            Task 6
packages/tri-web/tests/
  conftest.py, test_runtime.py   Task 2
```

---

### Task 1: Guard the agent-tool descriptions before anything moves

**Files:**
- Test: `packages/tri-coach/tests/test_tools.py` (append)

**Interfaces:**
- Consumes: `tri_coach.tools.analyst.make_analyst_tool(model, tools, connect, today) -> BaseTool`; `tri_coach.tools.wellness.make_wellness_tool(model, connect, db_url, registry, today) -> BaseTool`; the `registry` fixture from `packages/tri-coach/tests/conftest.py`.
- Produces: `test_ask_tool_names_descriptions_and_schemas_are_unchanged`, which Task 5 must keep green.

- [ ] **Step 1: Record the baseline**

Run: `uv run pytest -q` and `uv run pytest packages/tri-coach packages/tri-web -q`
Expected: both pass. Write down **B**, the passed count of the full run, and the skipped count.

- [ ] **Step 2: Write the guard test**

Append to `packages/tri-coach/tests/test_tools.py`. Every name it uses (`date`, `ScriptedChatModel`, `make_analyst_tool`, `make_wellness_tool`) is already imported there.

```python
EXPECTED_ANALYST_DESCRIPTION = (
    "Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,\n"
    "logged intake against nutrition targets, or how training compares to plan. It reads the\n"
    "database and the devices; it changes nothing. Ask one specific question at a time."
)
EXPECTED_WELLNESS_DESCRIPTION = (
    "Ask the lab interpreter about the athlete's lab panels: a marker's value against its\n"
    "functional range, what is outside optimal and why, the retest plan, supplements, or\n"
    "whether a symptom could be lab-related. It reads stored panels and reports; it changes\n"
    "nothing. Ask one specific question at a time."
)


def test_ask_tool_names_descriptions_and_schemas_are_unchanged(registry):
    def unreachable():
        raise AssertionError("building a tool must not connect")

    analyst = make_analyst_tool(
        ScriptedChatModel(script=[]), [], unreachable, lambda: date(2026, 9, 14)
    )
    wellness = make_wellness_tool(
        ScriptedChatModel(script=[]),
        unreachable,
        "postgresql://unused/db",
        registry,
        lambda: date(2026, 9, 14),
    )
    assert (analyst.name, analyst.description) == ("ask_analyst", EXPECTED_ANALYST_DESCRIPTION)
    assert (wellness.name, wellness.description) == ("ask_wellness", EXPECTED_WELLNESS_DESCRIPTION)
    for t in (analyst, wellness):
        schema = t.tool_call_schema.model_json_schema()
        assert schema["title"] == t.name and schema["required"] == ["question"]
        assert schema["properties"] == {"question": {"title": "Question", "type": "string"}}
```

- [ ] **Step 3: Run it against today's code**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py::test_ask_tool_names_descriptions_and_schemas_are_unchanged -v`
Expected: PASS. This test pins the current behaviour; it must pass before the refactor. If it fails, the literals do not match the code on this branch: stop and report the actual description.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+1 passed`, same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-coach/tests/test_tools.py
git commit -m "test(coach): pin ask_analyst and ask_wellness names, descriptions and schemas"
```

---

### Task 2: Coach persistence from the harness; `STATE_TYPES` into `graph/state.py`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/state.py`
- Delete: `packages/tri-coach/src/tri_coach/graph/checkpointer.py`
- Modify: `packages/tri-coach/src/tri_coach/cli.py` (`ready`, `_open_graph`, `reset_thread`)
- Modify: `packages/tri-web/src/tri_web/routes/system.py`
- Modify: `packages/tri-web/src/tri_web/runtime.py`
- Test: `packages/tri-coach/tests/{test_cli,test_graph,test_graph_apply,test_live,test_models,test_resume}.py`, `packages/tri-web/tests/{conftest,test_runtime}.py`

**Interfaces:**
- Consumes (plan 01): `tri_core.harness.persistence.SETUP_HINT`, `STORE_SETUP_HINT`, `make_serde(state_types)`, `open_checkpointer(url, state_types)`, `checkpointer_ready(url)`, `open_store(url)`, `store_ready(url)`.
- Produces: `tri_coach.graph.state.STATE_TYPES: tuple[type, ...]`, the same nine types in the same order as today's `tri_coach.graph.checkpointer.STATE_TYPES`.

- [ ] **Step 1: Move `STATE_TYPES` into `graph/state.py`**

Replace the whole of `packages/tri-coach/src/tri_coach/graph/state.py` with:

```python
"""Graph state. `messages` accumulates; every other key is last-write-wins and the `start` node
clears the per-turn ones."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_coach.models import (
    ApplyReport,
    Brief,
    ChangeSet,
    Proposal,
    ProposalRequest,
    ReviewDecision,
)
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange, PlannedSession


class CoachState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    brief: Brief | None  # set by a handoff tool, consumed by planning/nutrition
    proposals: list[Proposal]  # accumulated this turn
    proposal_request: ProposalRequest | None  # set by propose_changes, consumed by review
    pending: ChangeSet | None  # what review shows; remainder after a partial apply
    carried: list[Proposal]  # held proposals the change set did not name; review -> apply
    regenerate_after_apply: bool  # set by apply when planning moved sessions; routes to nutrition
    review_decision: ReviewDecision | None
    reports: list[ApplyReport]
    last_error: str | None


# Pydantic models that live in CoachState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (
    Brief,
    Proposal,
    ProposalRequest,
    ChangeSet,
    ReviewDecision,
    ApplyReport,
    CalendarChange,
    PlannedSession,
    NutritionChange,
)
```

- [ ] **Step 2: Point `cli.py` at the harness**

In `packages/tri-coach/src/tri_coach/cli.py`, replace `ready`:

Before (after plan 03):

```python
def ready(settings: CoachSettings) -> str | None:
    """Why chat cannot start, or None when the key, checkpointer and store are all there."""
    from tri_coach.graph.checkpointer import SETUP_HINT, checkpointer_ready
    from tri_core.harness.persistence import STORE_SETUP_HINT, store_ready

    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set in .env"
    if not checkpointer_ready(settings.database_url):
        return SETUP_HINT
    if not store_ready(settings.database_url):
        return STORE_SETUP_HINT
    return None
```

After:

```python
def ready(settings: CoachSettings) -> str | None:
    """Why chat cannot start, or None when the key, checkpointer and store are all there."""
    from tri_core.harness.persistence import (
        SETUP_HINT,
        STORE_SETUP_HINT,
        checkpointer_ready,
        store_ready,
    )

    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set in .env"
    if not checkpointer_ready(settings.database_url):
        return SETUP_HINT
    if not store_ready(settings.database_url):
        return STORE_SETUP_HINT
    return None
```

Replace `_open_graph`'s imports and its saver line.

Before (after plan 03):

```python
    from tri_coach.graph.checkpointer import open_checkpointer
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_store
```

```python
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
```

After:

```python
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.graph.state import STATE_TYPES
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_checkpointer, open_store
```

```python
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
```

Replace `reset_thread`'s imports and its saver line.

Before (after plan 03):

```python
    from tri_coach import memory as M
    from tri_coach.graph.checkpointer import checkpointer_ready, open_checkpointer
    from tri_core.harness.persistence import open_store, store_ready
```

```python
        async with open_checkpointer(settings.database_url) as saver:
```

After:

```python
    from tri_coach import memory as M
    from tri_coach.graph.state import STATE_TYPES
    from tri_core.harness.persistence import (
        checkpointer_ready,
        open_checkpointer,
        open_store,
        store_ready,
    )
```

```python
        async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
```

Every other line of `cli.py` stays as plan 03 left it.

- [ ] **Step 3: Point tri-web at the harness**

In `packages/tri-web/src/tri_web/routes/system.py`, replace the imports.

Before (after plan 03):

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.harness.persistence import store_ready
from tri_web.schemas import Readiness, StatusOut
```

After:

```python
from tri_core.harness.persistence import checkpointer_ready, store_ready
from tri_web.schemas import Readiness, StatusOut
```

In `packages/tri-web/src/tri_web/runtime.py`, inside `open_runtime`, replace the imports and the saver line.

Before (after plan 03):

```python
    from tri_coach.cli import ready
    from tri_coach.graph.checkpointer import open_checkpointer
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_store
```

```python
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
```

After:

```python
    from tri_coach.cli import ready
    from tri_coach.graph.deps import make_deps
    from tri_coach.graph.graph import build_graph
    from tri_coach.graph.llm import make_model
    from tri_coach.graph.state import STATE_TYPES
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_checkpointer, open_store
```

```python
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
```

- [ ] **Step 4: Update the tests (imports, construction and patch paths only)**

`packages/tri-coach/tests/test_cli.py`: two string patch paths.

```python
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: False)
```
→
```python
    monkeypatch.setattr("tri_core.harness.persistence.checkpointer_ready", lambda url: False)
```
and
```python
    monkeypatch.setattr("tri_coach.graph.checkpointer.checkpointer_ready", lambda url: True)
```
→
```python
    monkeypatch.setattr("tri_core.harness.persistence.checkpointer_ready", lambda url: True)
```

`packages/tri-coach/tests/test_graph.py` and `packages/tri-coach/tests/test_graph_apply.py`: in each, replace

```python
from tri_coach.graph.checkpointer import make_serde
```
with
```python
from tri_coach.graph.state import STATE_TYPES
from tri_core.harness.persistence import make_serde
```

and every `InMemorySaver(serde=make_serde())` with `InMemorySaver(serde=make_serde(STATE_TYPES))`. That is `test_graph.py` lines 31 and 308, and `test_graph_apply.py` line 32.

`packages/tri-coach/tests/test_live.py`: replace

```python
from tri_coach.graph.checkpointer import make_serde
```
with
```python
from tri_coach.graph.state import STATE_TYPES
from tri_core.harness.persistence import make_serde
```

and `InMemorySaver(serde=make_serde()),` with `InMemorySaver(serde=make_serde(STATE_TYPES)),`.

`packages/tri-coach/tests/test_models.py`: replace

```python
from tri_coach.graph.checkpointer import make_serde
```
with
```python
from tri_coach.graph.state import STATE_TYPES
from tri_core.harness.persistence import make_serde
```

and in `test_serde_round_trips_state_types`, `serde = make_serde()` with `serde = make_serde(STATE_TYPES)`.

`packages/tri-coach/tests/test_resume.py`: replace

```python
from tri_coach.graph.checkpointer import checkpointer_ready, open_checkpointer
```
with
```python
from tri_coach.graph.state import STATE_TYPES
from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
```

and each of the three `open_checkpointer(url)` calls with `open_checkpointer(url, STATE_TYPES)`.

`packages/tri-web/tests/conftest.py`: replace

```python
from tri_coach.graph.checkpointer import make_serde
```
with
```python
from tri_coach.graph.state import STATE_TYPES
from tri_core.harness.persistence import make_serde
```

and `graph = build_graph(deps, InMemorySaver(serde=make_serde()), mem_store)` with `graph = build_graph(deps, InMemorySaver(serde=make_serde(STATE_TYPES)), mem_store)`.

`packages/tri-web/tests/test_runtime.py`: replace plan 03's version

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.config import Settings
from tri_core.harness.persistence import store_ready
from tri_core.testing import ScriptedChatModel
```
with
```python
from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, store_ready
from tri_core.testing import ScriptedChatModel
```

`packages/tri-web/tests/test_routes_system.py` needs no change (fact 2).

- [ ] **Step 5: Delete the old module and check nothing still names it**

Run: `git rm packages/tri-coach/src/tri_coach/graph/checkpointer.py`

Run: `rg -n "tri_coach\.graph\.checkpointer|graph/checkpointer" packages scripts conftest.py`
Expected: no output.

- [ ] **Step 6: Run the affected suites**

Run: `uv run pytest packages/tri-coach packages/tri-web -q`
Expected: the Task 1 slice count plus one (the guard test), same skips, no failures.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+1 passed`, same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add -A packages/tri-coach packages/tri-web
git commit -m "refactor(coach): checkpointer and readiness from tri_core.harness; STATE_TYPES in graph/state.py"
```

---

### Task 3: Agent builders and `last_ai_text` from the harness; delete `text.py`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/llm.py`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/coach.py`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/planning.py`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py`
- Modify: `packages/tri-coach/src/tri_coach/evals/target.py`
- Modify: `packages/tri-coach/src/tri_coach/tools/analyst.py` (one import)
- Modify: `packages/tri-coach/src/tri_coach/tools/wellness.py` (one import)
- Delete: `packages/tri-coach/src/tri_coach/text.py`
- Test: `packages/tri-coach/tests/test_tools.py`, `test_graph.py`, `test_graph_apply.py`

**Interfaces:**
- Consumes (plan 01): `tri_core.harness.agents.make_subagent(model, tools, system_prompt, *, middleware=())`, `tri_core.harness.agents.one_tool_call_at_a_time`, `tri_core.harness.messages.last_ai_text(messages)`.
- Produces: `tri_coach.graph.llm` holds only `MAX_TOKENS` and `make_model(settings) -> ChatAnthropic`. `tri_coach.graph.nodes.coach.make_subagent` stays a module attribute (the tests patch it).

- [ ] **Step 1: Reduce `graph/llm.py` to model construction**

Replace the whole of `packages/tri-coach/src/tri_coach/graph/llm.py` with:

```python
"""Model construction. The agent builders live in tri_core.harness.agents."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
```

- [ ] **Step 2: The coach node keeps its middleware explicitly**

In `packages/tri-coach/src/tri_coach/graph/nodes/coach.py`, replace

```python
from tri_coach.graph.llm import make_subagent
```

by deleting that line and adding, after the last `tri_coach` import (`from tri_coach.tools.wellness import make_wellness_tool`):

```python
from tri_core.harness.agents import make_subagent, one_tool_call_at_a_time
```

and replace

```python
        agent = make_subagent(deps.model, tools, prompt)
```
with
```python
        agent = make_subagent(deps.model, tools, prompt, middleware=[one_tool_call_at_a_time])
```

- [ ] **Step 3: The eval target keeps the same agent**

In `packages/tri-coach/src/tri_coach/evals/target.py`, replace the import block

```python
from tri_coach import memory as M
from tri_coach.evals.cases import Route
from tri_coach.graph.llm import make_subagent
from tri_coach.prompts.coach import COACH_RULES
from tri_coach.text import last_ai_text
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools
```
with
```python
from tri_coach import memory as M
from tri_coach.evals.cases import Route
from tri_coach.prompts.coach import COACH_RULES
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools
from tri_core.harness.agents import make_subagent, one_tool_call_at_a_time
from tri_core.harness.messages import last_ai_text
```

and in `run_case` replace

```python
    agent = make_subagent(model, stub_tools(inputs), prompt)
```
with
```python
    agent = make_subagent(model, stub_tools(inputs), prompt, middleware=[one_tool_call_at_a_time])
```

- [ ] **Step 4: `last_ai_text` from the harness everywhere else**

In each of these four files, replace

```python
from tri_coach.text import last_ai_text
```
with
```python
from tri_core.harness.messages import last_ai_text
```

- `packages/tri-coach/src/tri_coach/graph/nodes/planning.py`
- `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py`
- `packages/tri-coach/src/tri_coach/tools/analyst.py`
- `packages/tri-coach/src/tri_coach/tools/wellness.py`

`ruff check --fix` moves each line into import order.

Then run: `git rm packages/tri-coach/src/tri_coach/text.py`

- [ ] **Step 5: Update the tests**

`packages/tri-coach/tests/test_tools.py`:
- Replace `from tri_coach.graph.llm import make_subagent` with `from tri_core.harness.agents import make_subagent, one_tool_call_at_a_time`.
- Delete the line `from tri_coach.text import last_ai_text`.
- In `outer_graph`, replace `agent = make_subagent(model, tools, "sys")` with:

```python
    agent = make_subagent(model, tools, "sys", middleware=[one_tool_call_at_a_time])
```

- Delete the whole test `test_last_ai_text_takes_the_last_answer_without_tool_calls`. It only duplicates `packages/tri-core/tests/test_harness_messages.py::test_last_ai_text_is_the_last_message_without_tool_calls` (list-block content) and `::test_last_ai_text_skips_tool_calling_messages_and_is_empty_when_none_match` (tool calls skipped, `""` when nothing matches).

`packages/tri-coach/tests/test_graph.py`, in `_recording`, replace

```python
    def record(model, tools, system_prompt):
        bound.append([t.name for t in tools])
        prompts.append(system_prompt)
        return real(model, tools, system_prompt)
```
with
```python
    def record(model, tools, system_prompt, **kwargs):
        bound.append([t.name for t in tools])
        prompts.append(system_prompt)
        return real(model, tools, system_prompt, **kwargs)
```

`packages/tri-coach/tests/test_graph_apply.py`, in `test_partial_apply_keeps_the_remainder_pending_and_shows_it_next_turn`, replace

```python
    def record(model, tools, system_prompt):
        prompts.append(system_prompt)
        return real(model, tools, system_prompt)
```
with
```python
    def record(model, tools, system_prompt, **kwargs):
        prompts.append(system_prompt)
        return real(model, tools, system_prompt, **kwargs)
```

- [ ] **Step 6: Check nothing still names the removed code**

Run: `rg -n "tri_coach\.text\b|from tri_coach\.graph\.llm import .*(make_subagent|one_tool_call_at_a_time)" packages scripts`
Expected: no output.

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py packages/tri-coach/tests/test_evals.py -q`
Expected: no failures. `test_the_coach_sub_agent_disables_parallel_tool_calls` and both `..._gets_a_not_delivered_result` tests pass unchanged.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `B passed` (+1 from Task 1, −1 deleted), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add -A packages/tri-coach
git commit -m "refactor(coach): make_subagent and last_ai_text from tri_core.harness; text.py removed"
```

---

### Task 4: Handoff tools on `tri_core.harness.handoff`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/tools/handoff.py`
- Test: `packages/tri-coach/tests/test_tools.py`

**Interfaces:**
- Consumes (plan 01): `tri_core.harness.handoff.handoff(goto: str, *, tool_call_id: str, messages: Sequence[AnyMessage], ack: ToolMessage, update: Mapping[str, Any] | None = None) -> Command[str]`.
- Produces: `tri_coach.tools.handoff.make_handoff_tools() -> list[BaseTool]`, unchanged. It returns `consult_planning`, `consult_nutrition` and `propose_changes` with the same names, docstrings, arguments, acknowledgement text, message ids and update keys.

- [ ] **Step 1: Rewrite `handoff.py` on the harness**

Replace the whole of `packages/tri-coach/src/tri_coach/tools/handoff.py` with the code below. The three tool functions, their docstrings and both acknowledgement texts are unchanged; only the `Command` construction moved into `handoff()`.

```python
"""Handoffs: tools that move the run from the coach to a sub-graph node.

Each tool leaves the coach sub-agent through tri_core.harness.handoff, which re-emits the turn's
messages (ids intact; add_messages upserts) with a result for any sibling call the unwinding cut
off and this tool's own ToolMessage. The sub-graph node later replaces that ToolMessage's content
(same id) with its result."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import uuid4

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from tri_coach.models import Brief, Domain, ProposalRequest
from tri_core.harness.handoff import handoff


def _consult(
    domain: Domain, instruction: str, tool_call_id: str, messages: Sequence[AnyMessage]
) -> Command[str]:
    message_id = str(uuid4())
    ack = ToolMessage(
        content=f"{domain} consulted; its answer replaces this message.",
        tool_call_id=tool_call_id,
        name=f"consult_{domain}",
        id=message_id,
    )
    brief = Brief(
        domain=domain, instruction=instruction, tool_call_id=tool_call_id, message_id=message_id
    )
    return handoff(
        domain, tool_call_id=tool_call_id, messages=messages, ack=ack, update={"brief": brief}
    )


def make_handoff_tools() -> list[BaseTool]:
    @tool
    def consult_planning(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Brief the planning agent to change the calendar, the goal or the horizon. The
        instruction must name the signal, the lever and the constraint. The result (a proposal
        id with its summary, or the agent's question) comes back as this call's result."""
        return _consult("planning", instruction, tool_call_id, messages)

    @tool
    def consult_nutrition(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Brief the nutrition agent to change daily targets, fueling notes, the profile or the
        race plan. The instruction must name the signal, the lever and the constraint. The
        result comes back as this call's result."""
        return _consult("nutrition", instruction, tool_call_id, messages)

    @tool
    def propose_changes(
        narration: str,
        proposal_ids: list[str],
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str]:
        """Send the kept proposals to the athlete for review, with a two or three sentence
        narration of why. Ends your turn; the athlete approves, rejects with a note, or edits."""
        ack = ToolMessage(
            content=f"change set {proposal_ids} sent to the athlete for review",
            tool_call_id=tool_call_id,
            name="propose_changes",
            id=str(uuid4()),
        )
        return handoff(
            "review",
            tool_call_id=tool_call_id,
            messages=messages,
            ack=ack,
            update={
                "proposal_request": ProposalRequest(narration=narration, ids=list(proposal_ids))
            },
        )

    return [consult_planning, consult_nutrition, propose_changes]
```

- [ ] **Step 2: Update the tests**

`packages/tri-coach/tests/test_tools.py`:
- Replace `from tri_coach.tools.handoff import make_handoff_tools, turn_messages` with `from tri_coach.tools.handoff import make_handoff_tools`.
- Delete the whole test `test_turn_messages_is_everything_after_the_last_human_message`. It only duplicates `packages/tri-core/tests/test_harness_handoff.py::test_turn_messages_is_everything_after_the_last_human_message`, which is the same test.

- [ ] **Step 3: Check the handoff behaviour tests still pass unchanged**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_evals.py -q`
Expected: no failures, including:
- `test_consult_planning_hands_off_with_a_valid_history`
- `test_consult_nutrition_and_propose_changes_route_and_carry_state`
- `test_handoff_after_an_earlier_tool_call_keeps_that_call_too`
- both `..._gets_a_not_delivered_result` tests
- `test_stub_descriptions_match_the_real_tools`

Run: `rg -n "def (turn_messages|undelivered)\b|^NOT_DELIVERED" packages/tri-coach`
Expected: no output.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints.
Expected: `B-1 passed`, same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 5: Commit**

```bash
git add -A packages/tri-coach
git commit -m "refactor(coach): handoff tools leave through tri_core.harness.handoff"
```

---

### Task 5: `ask_analyst` and `ask_wellness` as `agent_tool`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/tools/analyst.py`
- Modify: `packages/tri-coach/src/tri_coach/tools/wellness.py`

**Interfaces:**
- Consumes (plan 01): `tri_core.harness.agent_tool.Invocation(agent, context=None)`; `tri_core.harness.agent_tool.agent_tool(*, name, description, prepare, thread_prefix, recursion_limit, failure, empty) -> BaseTool`; `tri_core.harness.agents.build_chat_agent(model, tools, *, system_prompt=None, middleware=(), context_schema=None, checkpointer=None)`. Consumes (plan 02): `tri_analyze.agent.build_agent(model, tools, checkpointer=None)`, same signature as today.
- Produces:
  - `make_analyst_tool(model, tools, connect, today) -> BaseTool`, signature unchanged
  - `make_wellness_tool(model, connect, db_url, registry, today) -> BaseTool`, signature unchanged
  - `wellness_tools(connect, db_url, registry) -> list[BaseTool]`, unchanged
  - new module constants `ASK_ANALYST_DESCRIPTION` and `ASK_WELLNESS_DESCRIPTION`

- [ ] **Step 1: Rewrite `analyst.py`**

Replace the whole of `packages/tri-coach/src/tri_coach/tools/analyst.py` with:

```python
"""ask_analyst: the tri-analyze agent as a tool. Each call runs the analyst on a throwaway
in-memory thread with the coach's read-only tools and returns its final text, or the failure as
text (spec 9)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.agent import build_agent
from tri_analyze.repo import load_athlete_context
from tri_core.db.repo import Conn
from tri_core.harness.agent_tool import Invocation, agent_tool

ANALYST_RECURSION_LIMIT = 40

ASK_ANALYST_DESCRIPTION = inspect.cleandoc(
    """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
    logged intake against nutrition targets, or how training compares to plan. It reads the
    database and the devices; it changes nothing. Ask one specific question at a time."""
)


def make_analyst_tool(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    connect: Callable[[], AbstractContextManager[Conn]],
    today: Callable[[], date],
) -> BaseTool:
    def prepare() -> Invocation:
        with connect() as conn:
            ctx = load_athlete_context(conn, today())
        return Invocation(build_agent(model, tools, InMemorySaver()), context=ctx)

    return agent_tool(
        name="ask_analyst",
        description=ASK_ANALYST_DESCRIPTION,
        prepare=prepare,
        thread_prefix="analyst",
        recursion_limit=ANALYST_RECURSION_LIMIT,
        failure="The analyst failed ({error}); do not guess at the data it could not read.",
        empty="The analyst returned no answer; ask a narrower question.",
    )
```

- [ ] **Step 2: Rewrite `wellness.py`**

Replace the whole of `packages/tri-coach/src/tri_coach/tools/wellness.py` with the code below. `wellness_tools` and its docstring are unchanged.

```python
"""ask_wellness: the tri-wellness chat agent as a tool. Each call runs the lab interpreter on a
throwaway in-memory thread with wellness's own prompt and read-only tools and returns its final
text. The coach never writes a wellness row: ingest and report stay athlete-driven commands."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_core.db.repo import Conn
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agent_tool import Invocation, agent_tool
from tri_core.harness.agents import build_chat_agent
from tri_wellness import repo
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import athlete_profile
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

ConnectFactory = Callable[[], AbstractContextManager[Conn]]

WELLNESS_RECURSION_LIMIT = 40

ASK_WELLNESS_DESCRIPTION = inspect.cleandoc(
    """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
    functional range, what is outside optimal and why, the retest plan, supplements, or
    whether a symptom could be lab-related. It reads stored panels and reports; it changes
    nothing. Ask one specific question at a time."""
)


def wellness_tools(
    connect: ConnectFactory, db_url: str, registry: MarkerRegistry
) -> list[BaseTool]:
    """What tri-wellness chat binds: the SQL read tool with the lab schema doc and the three
    findings tools. None of them writes."""
    return [make_query_tool(db_url, WELLNESS_SCHEMA_DOC), *make_findings_tools(connect, registry)]


def make_wellness_tool(
    model: BaseChatModel,
    connect: ConnectFactory,
    db_url: str,
    registry: MarkerRegistry,
    today: Callable[[], date],
) -> BaseTool:
    tools = wellness_tools(connect, db_url, registry)
    names = [t.name for t in tools]

    def prepare() -> Invocation:
        with connect() as conn:
            profile = athlete_profile(conn)
            panels = repo.list_panels(conn)
            latest = repo.latest_panel_id(conn)
            latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
        prompt = render_chat_prompt(profile, registry.sex, panels, latest_report, today(), names)
        agent = build_chat_agent(model, tools, system_prompt=prompt, checkpointer=InMemorySaver())
        return Invocation(agent)

    return agent_tool(
        name="ask_wellness",
        description=ASK_WELLNESS_DESCRIPTION,
        prepare=prepare,
        thread_prefix="wellness",
        recursion_limit=WELLNESS_RECURSION_LIMIT,
        failure="The lab interpreter failed ({error}); answer without lab data.",
        empty="The lab interpreter returned no answer; ask a narrower question.",
    )
```

- [ ] **Step 3: Run the tool tests, the guard, and the eval description test**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_evals.py packages/tri-coach/tests/test_graph.py -q`
Expected: no failures. In particular:
- `test_ask_tool_names_descriptions_and_schemas_are_unchanged` (Task 1)
- `test_stub_descriptions_match_the_real_tools`
- `test_ask_analyst_runs_the_analyst_on_a_throwaway_thread`
- `test_ask_analyst_passes_the_context_and_the_analyst_sees_its_prompt`
- `test_ask_analyst_reports_a_failure_as_its_tool_result_instead_of_raising` (it asserts `"do not guess"`)
- `test_ask_wellness_runs_the_lab_interpreter_on_a_throwaway_thread`
- `test_ask_wellness_reports_a_failure_as_its_tool_result_instead_of_raising`

The `db`-marked ones skip only if Postgres is down; report a skip rather than treating it as a pass.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints.
Expected: `B-1 passed`, same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-coach/src/tri_coach/tools/analyst.py packages/tri-coach/src/tri_coach/tools/wellness.py
git commit -m "refactor(coach): ask_analyst and ask_wellness are tri_core.harness agent tools"
```

---

### Task 6: The coach turn driver on `stream_turn`; `text_of` from the harness

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/repl.py`
- Modify: `packages/tri-web/src/tri_web/thread.py`
- Test: `packages/tri-coach/tests/test_repl.py`

**Interfaces:**
- Consumes (plan 01): `tri_core.harness.messages.text_of`; `tri_core.harness.turns.Out`, `turn_config(thread_id, *, tags=None, recursion_limit=None)`, `stream_turn(runnable, payload, config, sink, *, subgraphs, stream_mode=None, context=None, catch_all=None, rate_limit_hint=...) -> TurnFailure | None`, `format_failure(failure) -> str`.
- Produces: `tri_coach.repl.run_turn(graph, payload, thread_id, out, *, tags=None, printer=None) -> TurnPrinter`, signature and output unchanged. `TurnClassifier`, `TurnPrinter`, `label`, `where_of`, `render_review`, `parse_decision`, `proposals_to_yaml`, `proposals_from_yaml`, `paused_review` and `chat_loop` are unchanged.

- [ ] **Step 1: Swap `repl.py`'s imports**

In `packages/tri-coach/src/tri_coach/repl.py`, replace the import block and the `Out` alias.

Before:

```python
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
import yaml
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from tri_coach.models import Proposal, ReviewDecision
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.repl import render_review as render_nutrition
from tri_planning.repl import render_changes as render_planning

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
```

After:

```python
from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from tri_coach.models import Proposal, ReviewDecision
from tri_core.harness.messages import text_of
from tri_core.harness.turns import Out as Out  # re-exported: tri_coach.checkin imports it
from tri_core.harness.turns import format_failure, stream_turn, turn_config
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.repl import render_review as render_nutrition
from tri_planning.repl import render_changes as render_planning

CommandFn = Callable[[], Awaitable[str]]
```

If plan 03 changed the `tri_nutrition.repl` or `tri_planning.repl` import lines, keep plan 03's lines.

- [ ] **Step 2: Delete `repl.text_of` and move `run_turn` onto `stream_turn`**

Delete this function from `repl.py`:

```python
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
```

Replace `run_turn`.

Before:

```python
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

After:

```python
async def run_turn(
    graph: Any,
    payload: dict[str, Any] | Command[Any],
    thread_id: str,
    out: Out,
    *,
    tags: list[str] | None = None,
    printer: TurnPrinter | None = None,
) -> TurnPrinter:
    """One coach turn. Any failure is printed and kept in `printer.error`; the chat keeps the
    state at the last checkpoint."""
    printer = printer or TurnPrinter(out)
    failure = await stream_turn(
        graph,
        payload,
        turn_config(thread_id, tags=tags, recursion_limit=60),
        printer,
        subgraphs=True,
        catch_all="the turn failed",
    )
    if failure is not None:
        printer.error = format_failure(failure)
        out(printer.error)
    return printer
```

- [ ] **Step 3: tri-web takes `text_of` from the harness**

`tri_coach/checkin.py` keeps `from tri_coach.repl import Out, paused_review, render_review, run_turn`. The explicit `Out as Out` re-export from Step 1 keeps that import valid under mypy strict. If `ruff check --fix` ever rewrites `Out as Out` to plain `Out`, restore the alias and report it.

In `packages/tri-web/src/tri_web/thread.py`, replace

```python
from tri_coach.repl import paused_review, text_of
```
with
```python
from tri_coach.repl import paused_review
from tri_core.harness.messages import text_of
```

- [ ] **Step 4: Update the REPL test**

`packages/tri-coach/tests/test_repl.py`:
- Delete `text_of,` from the `from tri_coach.repl import (...)` list.
- Delete the whole test `test_text_of_joins_text_blocks`. It only duplicates `packages/tri-core/tests/test_harness_messages.py::test_text_of_joins_text_blocks_and_bare_strings_and_skips_other_blocks` (text blocks and bare strings joined, a `tool_use` block skipped).

Every `run_turn` test stays as it is and proves the driver unchanged:
- `test_run_turn_reports_a_non_anthropic_failure_instead_of_raising` (catch-all sentence and `printer.error`)
- `test_run_turn_passes_tags_to_the_run` (`tags` and `recursion_limit` 60)
- `test_run_turn_uses_the_given_printer`
- the `chat_loop` tests

- [ ] **Step 5: Run the coach and web suites**

Run: `uv run pytest packages/tri-coach packages/tri-web -q`
Expected: no failures. The tri-web route and event tests (the SSE `token`, `tool_call`, `tool_result`, `consult`, `report`, `interrupt`, `error` and `done` events) pass with no edits.

Run: `rg -n "import anthropic|from tri_coach\.repl import .*\btext_of\b" packages`
Expected: no line under `packages/tri-coach` or `packages/tri-web`.

Run: `uv run mypy`
Expected: `Success`. In particular, there is no `Module "tri_coach.repl" does not explicitly export attribute "Out"` error for `checkin.py`.

- [ ] **Step 6: Definition of done**

Run the six commands from Global Constraints.
Expected: `B-2 passed`, same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 7: Commit**

```bash
git add -A packages/tri-coach packages/tri-web
git commit -m "refactor(coach): run_turn on tri_core.harness.stream_turn; text_of and Out from the harness"
```

---

### Task 7: Nothing left behind: greps, docs, web build, smoke

**Files:**
- Modify: any markdown file Step 3 finds (and its Obsidian copy)

**Interfaces:**
- Consumes: the results of Tasks 1–6 and plans 01–03.
- Produces: nothing new.

- [ ] **Step 1: The spec §7 definition check**

Run, verbatim from the spec:

```bash
rg -n "def (text_of|_text_of|last_ai_text|make_subagent|make_serde|open_checkpointer|checkpointer_ready|open_store|store_ready)\b" packages --glob '!**/tri_core/harness/**'
```

Expected: no output. Any line is a copy this plan (or plan 02 or 03) failed to delete; remove it and re-run Task 6's definition of done.

- [ ] **Step 2: The printer-class check**

Run:

```bash
rg -n "^class \w+.*(Printer|Emitter|Sink)\b" packages --glob '!**/tri_core/harness/**' --glob '!**/tests/**'
```

Expected: exactly these three classes, and nothing else:
- `packages/tri-coach/src/tri_coach/repl.py`: `class TurnPrinter:`
- `packages/tri-web/src/tri_web/events.py`: `class TurnEmitter(TurnPrinter):`
- the private ingest sink in `packages/tri-wellness/src/tri_wellness/repl.py`, under the name plan 02 gave it

Run:

```bash
rg -n "tri_coach\.(text|graph\.checkpointer)\b|from tri_coach\.graph\.llm import .*(make_subagent|one_tool_call_at_a_time)|from tri_coach\.tools\.handoff import .*(turn_messages|undelivered|NOT_DELIVERED)|from tri_coach\.repl import .*\btext_of\b" packages scripts conftest.py
```

Expected: no output.

- [ ] **Step 3: Docs that name deleted paths**

Run:

```bash
rg -n "tri_coach/text\.py|tri_coach\.text\b|tri_coach/graph/checkpointer\.py|tri_coach\.graph\.checkpointer|make_subagent|one_tool_call_at_a_time|turn_messages|undelivered\(" --glob '*.md' . --glob '!docs/superpowers/**' --glob '!**/node_modules/**'
```

Expected: no output (fact 7). For any hit:
1. Update the sentence to name `tri_core.harness.<module>`.
2. Copy the edited file to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).
3. Add it to this task's commit.

- [ ] **Step 4: Full definition of done, including the web app**

Run the six commands from Global Constraints.
Expected: `B-2 passed`, same skips, `1 warning`, ruff clean, `mypy` `Success`.

Then run:

```bash
cd web && npm run lint && npm run test && npm run build
```

Expected: ESLint reports no problems, Vitest passes, `tsc -b && vite build` writes `web/dist` without errors. `web/src` is untouched; this proves the server-side import changes did not reach the app's build. If `npm run test` or `npm run lint` fails the same way on `main`, record that as a pre-existing failure with its output rather than a pass.

- [ ] **Step 5: Commit**

If Step 3 changed any file:

```bash
git add <each changed markdown file>
git commit -m "docs: point at tri_core.harness for the coach's moved modules"
```

If nothing changed, no commit.

- [ ] **Step 6: Manual smoke (Brian runs; it costs API money)**

Hand these to Brian with the branch name. They are not part of the automated definition of done.

1. **Terminal:** `uv run tri-coach chat`, then ask: `How did my last seven days of training go? Do not change anything.`
   - The streamed turn shows `[analyst] → query_training_db(...)` or another analyst tool, `← ask_analyst: <n> chars`, and a coach answer.
   - No `consult_*` or `propose_changes` call.
   - `/quit` exits cleanly.
2. **Browser:** `uv run tri-web serve`, open the app, send the same message in the coach chat.
   - The activity rows show `→ ask_analyst` and `← ask_analyst`.
   - The answer streams and ends with no error banner.
   - Reloading the page shows the same thread.

---

## Stop conditions

Stop, do not commit the step, and report with the failing output when:

- A tri-coach or tri-web test fails and the only way to make it pass is to edit an assertion or an expected value. Changing a test's imports, construction arguments, string patch paths, or a spy's `**kwargs` forwarding is allowed; anything else is not.
- `test_ask_tool_names_descriptions_and_schemas_are_unchanged` or `test_evals.py::test_stub_descriptions_match_the_real_tools` fails after Task 5.
- Any tri-web SSE event or thread-view test fails after Task 6.
- A prerequisite check in Global Constraints fails, or a file's current code differs from a step's "before" in something other than plan 02/03's spelling of the store, serde or wellness-builder lines.
- `mypy` can only pass with a `# type: ignore`.
- `npm run build` fails on this branch but passes on `main`.

---

## Self-review against the spec

- **§4 layout, tri-coach:**
  - `graph/llm.py` keeps only `make_model`: Task 3.
  - `graph/checkpointer.py` deleted, `STATE_TYPES` in `graph/state.py`: Task 2.
  - `text.py` deleted: Task 3.
  - `tools/handoff.py` built on `handoff()`: Task 4.
  - `tools/analyst.py` and `tools/wellness.py` as `agent_tool`: Task 5.
  - `repl.py`: `text_of` removed; `TurnClassifier`, `TurnPrinter` and `run_turn` stay, `run_turn` on `stream_turn`: Task 6.
- **§4 layout, tri-web:**
  - `thread.py`: Task 6.
  - `routes/system.py` and `runtime.py`: Task 2.
  - `graph/graph.py` is listed in §9 item 4 but plan 03 already moved its serdes (fact 1), so it has no change here.
- **§5.2:** coach node `middleware=[one_tool_call_at_a_time]` (Task 3). The eval target and `outer_graph` keep the same middleware, which the spec did not list (fact 3).
- **§5.3:** `prepare` and `agent_tool` with `thread_prefix` `analyst`/`wellness`, recursion limit 40, today's failure and empty sentences, and descriptions equal to the cleandoc'd docstrings. Pinned by the Task 1 literals and `test_evals`.
- **§5.4:** `_consult` passes `update={"brief": brief}`; `propose_changes` passes `update={"proposal_request": ...}`; both keep their `ack` ids and content (Task 4).
- **§5.5:** coach `STATE_TYPES` passed to `open_checkpointer` and `make_serde` in the CLI, tri-web and tests; readiness imports stay inside the CLI function bodies (Task 2).
- **§5.6–§5.7:** `run_turn` keeps its signature, with `recursion_limit=60`, `catch_all="the turn failed"` and `printer.error = format_failure(...)` (Task 6). `repl.py` re-exports `Out` explicitly (`Out as Out`), so `checkin.py` keeps importing it from `repl` under mypy strict (fact 3).
- **§6:** item by item, by task:
  - 1: terminal output — Task 6's untouched `run_turn` and printer tests.
  - 2: SSE — Task 6 Step 5, Task 7 Step 4.
  - 3: tool descriptions — Tasks 1 and 5.
  - 4: middleware order — Task 3.
  - 5: serde allow-list — Task 2's `test_models` and `test_resume`.
  - 6: readiness and hints — Task 2's `test_cli` and `test_runtime`.
  - 7: propagation — `GraphBubbleUp` in plan 01's `agent_tool`; the non-anthropic catch-all in Task 6.
  - 8: thread ids, limits and tags — Tasks 3, 5 and 6.
- **§7:**
  - Assertions untouched: see "Stop conditions".
  - Three duplicate-only tests deleted, each naming its covering tri-core test: Tasks 3, 4 and 6.
  - String patch paths retargeted: Task 2.
  - After-plan-04 definition grep and printer-class check: Task 7 Steps 1–2.
  - Manual smoke: Task 7 Step 6.
- **§9 item 4:**
  - Every listed source and test file is covered by a task.
  - The importers the spec did not list are in fact 3: `evals/target.py`'s middleware, the two `make_subagent` spies, `checkin.py` and the `test_evals.py` guard.
  - The web build is Task 7 Step 4.
- **Test count:** +1 (Task 1) −3 (Tasks 3, 4, 6) = **B−2** after the plan.
