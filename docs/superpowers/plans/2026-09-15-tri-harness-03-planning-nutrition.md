# tri-harness Plan 3 of 4: tri-planning and tri-nutrition on the harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tri-planning and tri-nutrition drop their copies of the harness: both `graph/checkpointer.py` files, both `make_subagent` copies, both REPL printers and `_text_of`, and the Store helpers in `tri_nutrition/store.py`. Every caller, including the ones in tri-coach and tri-web, uses `tri_core.harness` instead, with no observable change.

**Architecture:** Five migration tasks and a closing check.
- Each package's `STATE_TYPES` tuple moves unchanged into its `graph/state.py`. Callers pass it to `tri_core.harness.persistence.open_checkpointer(url, STATE_TYPES)` and `make_serde(STATE_TYPES)`.
- `open_store`, `store_ready` and `STORE_SETUP_HINT` leave `tri_nutrition.store`, which keeps its namespace, keys and typed access.
- The four conversational nodes import `make_subagent` from `tri_core.harness.agents`.
- Each `repl.run_turn` keeps its signature and becomes a one-line call to `run_graph_turn(..., streamed_nodes=STREAMED_NODES)`.

**Tech Stack:** Python 3.12, uv workspace, langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2, pytest with `pytest-asyncio` in auto mode. `tri_core.harness` comes from plan 1.

**Spec:** `docs/superpowers/specs/2026-09-15-tri-harness-design.md`: §4 (layout for tri-planning, tri-nutrition, tri-web), §5.2 and §5.5–§5.7 (the interfaces consumed and what the packages keep), §6 (behaviour kept), §7 (rules for existing tests) and §9 item 3. The spec and the four plans live on `docs/tri-harness-spec`, merged to `main` before plan 1 ran.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Prerequisites:** plans 1 and 2 are merged on `main`. Check from the main checkout:

  ```bash
  test -f packages/tri-core/src/tri_core/harness/turns.py \
    && test ! -e packages/tri-wellness/src/tri_wellness/graph/checkpointer.py \
    && test ! -e packages/tri-wellness/src/tri_wellness/agent.py \
    && echo "plans 1 and 2 are on main"
  ```

  Expected: `plans 1 and 2 are on main`. If not, stop: this plan imports `tri_core.harness` and must not run before plan 2's merge.
- **Execute in a sibling worktree:** run `git worktree add ../triathlon_agent-harness-03 -b feat/tri-harness-03 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout.
- **Baseline:** before Task 1, run `uv run pytest -q` in the worktree and write the result down as **B** (`B passed, 6 skipped, 1 warning`; the six skips are `--live`). Plan 2 is expected to end at `947 passed, 6 skipped`, so B should be 947. If it isn't, use the recorded number and say so in the first commit message. Each task states its expected count relative to B. This plan deletes exactly one test (Task 5), so the end state is `B-1 passed, 6 skipped` (946 when B is 947).
- **Files this plan may touch:**
  - `packages/tri-planning/src/tri_planning/{graph/state.py, graph/llm.py, graph/nodes/intake.py, graph/nodes/adjust.py, repl.py, cli.py}`
  - `packages/tri-planning/src/tri_planning/graph/checkpointer.py` (deleted)
  - `packages/tri-planning/tests/{test_checkpointer.py, test_repl.py}`
  - `packages/tri-planning/README.md`
  - `packages/tri-nutrition/src/tri_nutrition/{graph/state.py, graph/llm.py, graph/nodes/intake.py, graph/nodes/checkin.py, repl.py, cli.py, store.py}`
  - `packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py` (deleted)
  - `packages/tri-nutrition/tests/{test_checkpointer.py, test_repl.py, test_store.py}`
  - `packages/tri-coach/src/tri_coach/{graph/graph.py, cli.py}`
  - `packages/tri-coach/tests/test_cli.py`
  - `packages/tri-web/src/tri_web/{runtime.py, routes/system.py}`
  - `packages/tri-web/tests/test_runtime.py`

  Nothing under `tri-core`, `tri-analyze` or `tri-wellness`, and nothing in tri-coach or tri-web beyond these files.
- **Coach checkpointer stays for plan 4.** `tri_coach.graph.checkpointer` and `tri_coach.graph.llm` still exist after this plan. Do not change the coach's own checkpointer imports (`SETUP_HINT`, `checkpointer_ready`, `open_checkpointer` from `tri_coach.graph.checkpointer`); plan 4 moves them. This plan moves only the Store pieces `tri_coach.cli` takes from `tri_nutrition.store`, and the planning/nutrition serdes in `tri_coach/graph/graph.py`.
- **Rules for existing tests (spec §7):**
  - Assertions and expected values are not edited.
  - Only these change: imports, string patch targets, arguments that construct a moved object (`open_checkpointer(url, STATE_TYPES)`, `make_serde(STATE_TYPES)`, `GraphTurnPrinter(out, STREAMED_NODES)`), and the deletion of tests that only duplicate a tri-core harness test.
  - If any step below would need an assertion edited, stop (see "Stop conditions").
- **No behaviour change (spec §6).** Terminal output, error sentences, serde allow-lists, readiness SQL and hint texts stay byte-identical. The one internal difference is that nutrition's printer now records `error`, as planning's already does; nothing in tri-nutrition reads it.
- **Readiness helpers stay imported inside function bodies** in every CLI, as today. Monkeypatching `"tri_core.harness.persistence.<name>"` then takes effect.
- **Commits:** git commits are permitted (Brian's standing permission). Commit once per task on `feat/tri-harness-03`, and end every commit message with the `Co-Authored-By:` trailer of the session executing the plan.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages`
  2. `uv run ruff check --fix packages`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing one. `ruff check --fix` may reorder the import lines shown below; accept its order.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file created or edited in this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Facts verified while writing this plan (against `main` 3a5a82c, 2026-09-15)

1. **The two `graph/checkpointer.py` files match the harness** except for their `STATE_TYPES` tuples and docstrings:
   - planning: `(CalendarChange, PlannedSession, ReviewDecision)`, with a two-line comment
   - nutrition: `(NutritionChange, ReviewDecision)`

   Their `SETUP_HINT`, `open_checkpointer` and `checkpointer_ready` are the same as `tri_core.harness.persistence`. `tri_nutrition/store.py` lines 24–43 (`STORE_SETUP_HINT`, `open_store`, `store_ready`) likewise match the harness; the rest of `store.py` uses only `BaseStore`, `NAMESPACE`, the keys and the models.
2. **Importers of what this plan moves** (full grep of `packages/` and `scripts/`, source and tests):
   - `tri_planning.graph.checkpointer`: `tri_planning/cli.py` (`_open_graph`, `_reset`), `tri-planning/tests/test_checkpointer.py`, `tri_coach/graph/graph.py`.
   - `tri_nutrition.graph.checkpointer`: `tri_nutrition/cli.py` (`_ready`, `_chat`, `_check_in`, `_reset`), `tri-nutrition/tests/test_checkpointer.py`, `tri_coach/graph/graph.py`.
   - `S.open_store`, `S.store_ready` and `S.STORE_SETUP_HINT` (as `from tri_nutrition import store as S`):
     - `tri_nutrition/cli.py`: `_ready`, `_chat`, `_today`, `_check_in`, `_reset`
     - `tri_coach/cli.py`: `ready`, `_open_graph`, `_memory`, `reset_thread`
     - `tri_web/runtime.py`
     - `tri-nutrition/tests/test_checkpointer.py` and `test_store.py`
   - `from tri_nutrition.store import store_ready`: `tri_web/routes/system.py`, `tri-web/tests/test_runtime.py`.
   - String patch: `tri-coach/tests/test_cli.py:22,24` (`"tri_nutrition.store.store_ready"`).
   - `make_subagent` from `tri_{planning,nutrition}.graph.llm`: `tri_planning/graph/nodes/{intake,adjust}.py`, `tri_nutrition/graph/nodes/{intake,checkin}.py`.
   - `TurnPrinter` and `_text_of`: only each package's `repl.py`, plus `TurnPrinter` in `tests/test_repl.py` of both packages.

   No `testing.py`, `checkin.py`, `evals/` or `scripts/` module imports any of these. `scripts/design_eval.py` imports only `tri_planning.graph.llm.make_model`, which stays.
3. **The spec's §9 item 3 lists are incomplete.** These files also change or matter, and the tasks below include them:
   - `tri_web/routes/system.py`'s `store_ready` import. The spec names the file under plan 3 importers, but its test lists omit the effect on `tri-web/tests/test_routes_system.py`. That test patches `"tri_web.routes.system.store_ready"`, which stays valid because `system.py` keeps a module-level name, so it needs no edit.
   - `tri-planning/README.md` lines 110–117, which describe `llm.py` as the "sub-agent factory", `checkpointer.py`, and `repl.py` "event rendering".
   - `tri_coach/cli.py`'s `_memory` and `reset_thread`. The spec's parenthetical mentions only `S.open_store`, `S.store_ready` and `S.STORE_SETUP_HINT`, which these functions also use.
4. **`tri-planning/tests/test_adjust_node.py` needs no edit.** It monkeypatches `adjust_node.make_subagent` and calls the saved `real(model, tools, system_prompt)`. After Task 4 the name is still a module attribute of `tri_planning.graph.nodes.adjust` (imported from the harness), and the harness function accepts that positional call.
5. **Every `astream` fake that reaches a package `run_turn`** has the signature `astream(self, payload, config=None, stream_mode=None, subgraphs=False)`: `tri-planning/tests/test_repl.py:90,110`, `test_checkin.py:34,102` and `tri-nutrition/tests/test_repl.py:100`. `run_graph_turn` → `stream_turn` passes `config=`, `stream_mode=["messages", "updates"]` and `subgraphs=True`, and no `context=`, so every fake still matches.
6. **Callers of the package `run_turn`:**
   - `tri_planning/repl.py` (`chat_loop`, the review dialogue) and `tri_planning/checkin.py` (`printer.error`, `printer.interrupt`)
   - `tri_nutrition/repl.py` (`chat_loop`, `_review_dialogue`, `checkin_run`: `printer.interrupt` only)

   `GraphTurnPrinter` has `final_text`, `interrupt` and `error`.
7. **After the printer code leaves `tri_planning/repl.py`**, the rest of the module uses `defaultdict`, `Awaitable`, `Callable`, `Any`, `yaml`, `HumanMessage` and `Command`. It no longer uses `anthropic`, `AIMessage`, `AIMessageChunk`, `BaseMessage` or `ToolMessage`. The same holds for `tri_nutrition/repl.py`, which does not import `defaultdict`.
8. **Importers of `Out` from a package REPL**, found by grepping `packages/` and `scripts/` for single-line and parenthesised imports: only `tri_planning/checkin.py:15` (`from tri_planning.repl import Out, render_changes, run_turn`). Nothing imports `Out` from `tri_nutrition.repl`. Under `mypy --strict` (`no_implicit_reexport`), a name a module only imports cannot be imported from it unless it is re-exported explicitly, so both REPLs write `from tri_core.harness.turns import Out as Out`. Nutrition does the same, so the two modules match and a later importer keeps working.
9. **Test counts** before this plan:
   - tri-planning: `test_repl.py` 7, `test_checkpointer.py` 2, `test_adjust_node.py` 8, `test_intake_node.py` 3
   - tri-nutrition: `test_repl.py` 7, `test_checkpointer.py` 2, `test_store.py` 5
   - tri-web: `test_runtime.py` 2, `test_routes_system.py` 2
   - tri-coach: `test_cli.py` 2, `test_graph.py` 13
10. **`tri-planning/tests/test_repl.py::test_turn_printer_handles_subgraph_events_and_interrupt`** feeds the same events and makes the same assertions as plan 1's `tri-core/tests/test_harness_turns.py::test_graph_printer_handles_subgraph_events_interrupt_and_streamed_nodes`, which uses planning's `{"intake", "adjust"}` and asserts a superset. It is deleted in Task 5.
    - `tri-nutrition/tests/test_repl.py::test_turn_printer_handles_subgraph_events_and_interrupt` uses nutrition-specific input (`checkin` namespaces, an `apply` root node, nutrition's `STREAMED_NODES`), so it stays and constructs `GraphTurnPrinter(buf.append, STREAMED_NODES)`.
    - `tri-planning/tests/test_repl.py::test_run_turn_sets_error_on_api_connection_failure` tests the package's `run_turn` wrapper, so it stays unchanged.

### Stop conditions

Stop and report to Brian, without editing the assertion, if any of these happen:
- Any existing assertion fails after a task's edits (for example, a printer output difference, or `ready()` returning a different hint).
- `mypy` rejects `from tri_planning.repl import Out` in `tri_planning/checkin.py` even with the `Out as Out` re-export.
- A grep in Task 6 finds an importer of a deleted module that fact 2 does not list.

---

## File Structure

```
packages/tri-planning/src/tri_planning/
  graph/state.py          Task 1: STATE_TYPES
  graph/checkpointer.py   Task 1: deleted
  cli.py                  Task 1: harness persistence imports
  graph/llm.py            Task 4: make_subagent removed
  graph/nodes/intake.py   Task 4: make_subagent from the harness
  graph/nodes/adjust.py   Task 4: make_subagent from the harness
  repl.py                 Task 5: run_turn on run_graph_turn
packages/tri-planning/tests/
  test_checkpointer.py    Task 1
  test_repl.py            Task 5: printer test deleted
packages/tri-planning/README.md                 Task 6
packages/tri-nutrition/src/tri_nutrition/
  graph/state.py          Task 2: STATE_TYPES
  graph/checkpointer.py   Task 2: deleted
  cli.py                  Tasks 2, 3
  store.py                Task 3: open_store, store_ready, STORE_SETUP_HINT removed
  graph/llm.py            Task 4
  graph/nodes/intake.py   Task 4
  graph/nodes/checkin.py  Task 4
  repl.py                 Task 5
packages/tri-nutrition/tests/
  test_checkpointer.py    Tasks 2, 3
  test_store.py           Task 3
  test_repl.py            Task 5
packages/tri-coach/src/tri_coach/graph/graph.py Tasks 1, 2
packages/tri-coach/src/tri_coach/cli.py         Task 3
packages/tri-coach/tests/test_cli.py            Task 3
packages/tri-web/src/tri_web/runtime.py         Task 3
packages/tri-web/src/tri_web/routes/system.py   Task 3
packages/tri-web/tests/test_runtime.py          Task 3
```

---

### Task 1: tri-planning's checkpointer moves to the harness

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/state.py`
- Delete: `packages/tri-planning/src/tri_planning/graph/checkpointer.py`
- Modify: `packages/tri-planning/src/tri_planning/cli.py` (`_open_graph`, `_reset`)
- Modify: `packages/tri-coach/src/tri_coach/graph/graph.py` (planning serde)
- Test: `packages/tri-planning/tests/test_checkpointer.py`

**Interfaces:**
- Consumes (plan 1): `tri_core.harness.persistence.SETUP_HINT`, `checkpointer_ready(url: str) -> bool`, `open_checkpointer(url: str, state_types: Sequence[type])`, `make_serde(state_types: Sequence[type]) -> JsonPlusSerializer`.
- Produces: `tri_planning.graph.state.STATE_TYPES: tuple[type, ...] = (CalendarChange, PlannedSession, ReviewDecision)`.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-planning/tests/test_checkpointer.py packages/tri-planning/tests/test_graph.py packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py -q`
Expected: all pass (`test_checkpointer.py` contributes 2).

- [ ] **Step 2: Move `STATE_TYPES` into `graph/state.py`**

In `packages/tri-planning/src/tri_planning/graph/state.py`, replace:

```python
from tri_planning.planning.models import CalendarChange, GraphPhase, ReviewDecision
```

with:

```python
from tri_planning.planning.models import CalendarChange, GraphPhase, PlannedSession, ReviewDecision

# Pydantic models that live in PlanningState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (CalendarChange, PlannedSession, ReviewDecision)
```

- [ ] **Step 3: Delete the package checkpointer**

Run: `git rm packages/tri-planning/src/tri_planning/graph/checkpointer.py`

- [ ] **Step 4: Point the test at the harness**

In `packages/tri-planning/tests/test_checkpointer.py`, replace the import block:

```python
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.checkpointer import checkpointer_ready, make_serde, open_checkpointer
from tri_planning.graph.graph import build_graph
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json
```

with:

```python
from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, make_serde, open_checkpointer
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.graph import build_graph
from tri_planning.graph.state import STATE_TYPES
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json
```

Then make these four argument changes, and nothing else:

| Before | After |
|---|---|
| `    serde = make_serde()` | `    serde = make_serde(STATE_TYPES)` |
| `        async with open_checkpointer(url) as saver:` | `        async with open_checkpointer(url, STATE_TYPES) as saver:` |
| `        async with open_checkpointer(url) as saver2:` | `        async with open_checkpointer(url, STATE_TYPES) as saver2:` |
| `        async with open_checkpointer(url) as saver3:` | `        async with open_checkpointer(url, STATE_TYPES) as saver3:` |

- [ ] **Step 5: Point the CLI at the harness**

In `packages/tri-planning/src/tri_planning/cli.py`, `_open_graph`, replace:

```python
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.live_tools import open_live_tools
    from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec
    from tri_planning.allowlist import GARMIN_LIVE_TOOLS
    from tri_planning.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_planning.graph.deps import make_deps
    from tri_planning.graph.graph import build_graph
    from tri_planning.graph.llm import make_model
```

with:

```python
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.live_tools import open_live_tools
    from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec
    from tri_planning.allowlist import GARMIN_LIVE_TOOLS
    from tri_planning.graph.deps import make_deps
    from tri_planning.graph.graph import build_graph
    from tri_planning.graph.llm import make_model
    from tri_planning.graph.state import STATE_TYPES
```

and in the same function replace:

```python
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
```

with:

```python
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
```

In `_reset`, replace:

```python
    from tri_core.db.connection import connect
    from tri_planning import repo
    from tri_planning.graph.checkpointer import checkpointer_ready, open_checkpointer
```

with:

```python
    from tri_core.db.connection import connect
    from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
    from tri_planning import repo
    from tri_planning.graph.state import STATE_TYPES
```

and replace:

```python
        async with open_checkpointer(settings.database_url) as saver:
```

with:

```python
        async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
```

- [ ] **Step 6: Point the coach graph's planning subgraph at the harness serde**

In `packages/tri-coach/src/tri_coach/graph/graph.py`, replace:

```python
from tri_nutrition.graph.checkpointer import make_serde as nutrition_serde
from tri_nutrition.graph.graph import build_graph as build_nutrition_graph
from tri_planning.graph.checkpointer import make_serde as planning_serde
from tri_planning.graph.graph import build_graph as build_planning_graph
```

with:

```python
from tri_core.harness.persistence import make_serde
from tri_nutrition.graph.checkpointer import make_serde as nutrition_serde
from tri_nutrition.graph.graph import build_graph as build_nutrition_graph
from tri_planning.graph.graph import build_graph as build_planning_graph
from tri_planning.graph.state import STATE_TYPES as PLANNING_STATE_TYPES
```

and in `build_graph` replace:

```python
    planning_graph = build_planning_graph(
        deps.planning_deps, InMemorySaver(serde=planning_serde()), embedded=True
    )
```

with:

```python
    planning_graph = build_planning_graph(
        deps.planning_deps, InMemorySaver(serde=make_serde(PLANNING_STATE_TYPES)), embedded=True
    )
```

- [ ] **Step 7: Run the affected tests**

Run: `uv run pytest packages/tri-planning/tests/test_checkpointer.py packages/tri-planning/tests/test_graph.py packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py -q`
Expected: the same counts as Step 1, all pass.

Run: `rg -n "tri_planning\.graph\.checkpointer" packages scripts`
Expected: no output.

- [ ] **Step 8: Definition of done**

Run the six commands from Global Constraints.
Expected: `B passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 9: Commit**

```bash
git add -A packages/tri-planning packages/tri-coach/src/tri_coach/graph/graph.py
git commit -m "refactor(planning): checkpointer from tri_core.harness; STATE_TYPES in graph/state.py"
```

---

### Task 2: tri-nutrition's checkpointer moves to the harness

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/state.py`
- Delete: `packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/cli.py` (`_ready`, `_chat`, `_check_in`, `_reset`: checkpointer imports only)
- Modify: `packages/tri-coach/src/tri_coach/graph/graph.py` (nutrition serde)
- Test: `packages/tri-nutrition/tests/test_checkpointer.py`

**Interfaces:**
- Consumes (plan 1): `SETUP_HINT`, `checkpointer_ready`, `open_checkpointer(url, state_types)`, `make_serde(state_types)` from `tri_core.harness.persistence`.
- Produces: `tri_nutrition.graph.state.STATE_TYPES: tuple[type, ...] = (NutritionChange, ReviewDecision)`.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-nutrition packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py -q`
Expected: all pass.

- [ ] **Step 2: Move `STATE_TYPES` into `graph/state.py`**

In `packages/tri-nutrition/src/tri_nutrition/graph/state.py`, replace:

```python
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision
```

with:

```python
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision

# Pydantic models that live in NutritionState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (NutritionChange, ReviewDecision)
```

- [ ] **Step 3: Delete the package checkpointer**

Run: `git rm packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py`

- [ ] **Step 4: Point the test at the harness**

In `packages/tri-nutrition/tests/test_checkpointer.py`, replace the import block:

```python
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.checkpointer import checkpointer_ready, make_serde, open_checkpointer
from tri_nutrition.graph.graph import build_graph
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision
from tri_nutrition.testing import PROFILE_ARGS, FakeGarmin
```

with:

```python
from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, make_serde, open_checkpointer
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.graph import build_graph
from tri_nutrition.graph.state import STATE_TYPES
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision
from tri_nutrition.testing import PROFILE_ARGS, FakeGarmin
```

Then make these four argument changes, and nothing else:

| Before | After |
|---|---|
| `    serde = make_serde()` | `    serde = make_serde(STATE_TYPES)` |
| `        async with open_checkpointer(url) as saver, S.open_store(url) as store:` | `        async with open_checkpointer(url, STATE_TYPES) as saver, S.open_store(url) as store:` |
| `        async with open_checkpointer(url) as saver2, S.open_store(url) as store2:` | `        async with open_checkpointer(url, STATE_TYPES) as saver2, S.open_store(url) as store2:` |
| `        async with open_checkpointer(url) as saver3, S.open_store(url) as store3:` | `        async with open_checkpointer(url, STATE_TYPES) as saver3, S.open_store(url) as store3:` |

- [ ] **Step 5: Point the CLI's checkpointer imports at the harness**

In `packages/tri-nutrition/src/tri_nutrition/cli.py`:

`_ready`: replace

```python
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import SETUP_HINT, checkpointer_ready
```

with

```python
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready
    from tri_nutrition import store as S
```

`_chat`: replace

```python
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import open_checkpointer
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
```

with

```python
    from tri_core.db.connection import connect
    from tri_core.harness.persistence import open_checkpointer
    from tri_core.sync.runner import run_sync
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.graph.state import STATE_TYPES
```

and in `_chat` replace

```python
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
```

with

```python
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
```

`_check_in`: replace

```python
    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import open_checkpointer
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.repl import checkin_run
```

with

```python
    from tri_core.harness.persistence import open_checkpointer
    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.graph.state import STATE_TYPES
    from tri_nutrition.repl import checkin_run
```

and in `_check_in` replace

```python
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
```

with

```python
        saver = await stack.enter_async_context(
            open_checkpointer(settings.database_url, STATE_TYPES)
        )
```

`_reset`: replace

```python
    from tri_core.db.connection import connect
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import checkpointer_ready, open_checkpointer
```

with

```python
    from tri_core.db.connection import connect
    from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.state import STATE_TYPES
```

and in `_reset` replace

```python
        async with open_checkpointer(settings.database_url) as saver:
```

with

```python
        async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
```

- [ ] **Step 6: Point the coach graph's nutrition subgraph at the harness serde**

In `packages/tri-coach/src/tri_coach/graph/graph.py`, replace:

```python
from tri_core.harness.persistence import make_serde
from tri_nutrition.graph.checkpointer import make_serde as nutrition_serde
from tri_nutrition.graph.graph import build_graph as build_nutrition_graph
```

with:

```python
from tri_core.harness.persistence import make_serde
from tri_nutrition.graph.graph import build_graph as build_nutrition_graph
from tri_nutrition.graph.state import STATE_TYPES as NUTRITION_STATE_TYPES
```

and in `build_graph` replace:

```python
    nutrition_graph = build_nutrition_graph(
        deps.nutrition_deps, InMemorySaver(serde=nutrition_serde()), store, embedded=True
    )
```

with:

```python
    nutrition_graph = build_nutrition_graph(
        deps.nutrition_deps,
        InMemorySaver(serde=make_serde(NUTRITION_STATE_TYPES)),
        store,
        embedded=True,
    )
```

- [ ] **Step 7: Run the affected tests**

Run: `uv run pytest packages/tri-nutrition packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py -q`
Expected: the same counts as Step 1, all pass.

Run: `rg -n "tri_nutrition\.graph\.checkpointer" packages scripts`
Expected: no output.

- [ ] **Step 8: Definition of done**

Run the six commands from Global Constraints.
Expected: `B passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 9: Commit**

```bash
git add -A packages/tri-nutrition packages/tri-coach/src/tri_coach/graph/graph.py
git commit -m "refactor(nutrition): checkpointer from tri_core.harness; STATE_TYPES in graph/state.py"
```

---

### Task 3: The Store helpers leave `tri_nutrition.store`

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/store.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/cli.py` (`_ready`, `_chat`, `_today`, `_check_in`, `_reset`)
- Modify: `packages/tri-coach/src/tri_coach/cli.py` (`ready`, `_open_graph`, `_memory`, `reset_thread`)
- Modify: `packages/tri-web/src/tri_web/runtime.py`
- Modify: `packages/tri-web/src/tri_web/routes/system.py`
- Test: `packages/tri-nutrition/tests/test_checkpointer.py`, `packages/tri-nutrition/tests/test_store.py`, `packages/tri-coach/tests/test_cli.py`, `packages/tri-web/tests/test_runtime.py`

**Interfaces:**
- Consumes (plan 1): `STORE_SETUP_HINT`, `open_store(url)`, `store_ready(url) -> bool` from `tri_core.harness.persistence`.
- Produces: `tri_nutrition.store` without `open_store`, `store_ready` or `STORE_SETUP_HINT`. `NAMESPACE`, `KEY_*`, `KEYS` and every typed accessor are unchanged.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-nutrition packages/tri-coach/tests/test_cli.py packages/tri-web -q`
Expected: all pass (`test_cli.py` 2, `test_runtime.py` 2, `test_routes_system.py` 2, `test_store.py` 5).

- [ ] **Step 2: Remove the helpers from `store.py`**

In `packages/tri-nutrition/src/tri_nutrition/store.py`, replace everything from the top of the file through the end of `store_ready` (the module docstring down to `    return bool(row and row[0])`) with:

```python
"""The athlete's long-term nutrition memory: LangGraph Store namespace, keys and typed access.

Everything here is async because AsyncPostgresStore refuses synchronous calls from the event
loop thread. The same helpers work on InMemoryStore in tests. Opening the Postgres store and
checking for its tables live in tri_core.harness.persistence.
"""

from __future__ import annotations

from langgraph.store.base import BaseStore

from tri_nutrition.nutrition.models import FuelLogEntry, NutritionProfile, Product

NAMESPACE: tuple[str, str] = ("athlete", "nutrition")
KEY_PROFILE = "profile"
KEY_FUEL_LOG = "fuel_log"
KEY_PRODUCTS = "product_library"
KEYS = (KEY_PROFILE, KEY_FUEL_LOG, KEY_PRODUCTS)
```

Everything from `async def get_profile` down stays as it is.

- [ ] **Step 3: Update the nutrition tests**

In `packages/tri-nutrition/tests/test_checkpointer.py`, replace:

```python
from tri_core.harness.persistence import checkpointer_ready, make_serde, open_checkpointer
```

with:

```python
from tri_core.harness.persistence import (
    checkpointer_ready,
    make_serde,
    open_checkpointer,
    open_store,
    store_ready,
)
```

and make these four changes, and nothing else:

| Before | After |
|---|---|
| `    if not checkpointer_ready(url) or not S.store_ready(url):` | `    if not checkpointer_ready(url) or not store_ready(url):` |
| `        async with open_checkpointer(url, STATE_TYPES) as saver, S.open_store(url) as store:` | `        async with open_checkpointer(url, STATE_TYPES) as saver, open_store(url) as store:` |
| `        async with open_checkpointer(url, STATE_TYPES) as saver2, S.open_store(url) as store2:` | `        async with open_checkpointer(url, STATE_TYPES) as saver2, open_store(url) as store2:` |
| `        async with open_checkpointer(url, STATE_TYPES) as saver3, S.open_store(url) as store3:` | `        async with open_checkpointer(url, STATE_TYPES) as saver3, open_store(url) as store3:` |

`S.get_profile` and `S.forget_all` stay.

In `packages/tri-nutrition/tests/test_store.py`, replace:

```python
from tri_core.config import Settings
from tri_nutrition import store as S
```

with:

```python
from tri_core.config import Settings
from tri_core.harness.persistence import open_store, store_ready
from tri_nutrition import store as S
```

and in `test_postgres_store_round_trip` replace `    if not S.store_ready(url):` with `    if not store_ready(url):` and `    async with S.open_store(url) as pg:` with `    async with open_store(url) as pg:`.

- [ ] **Step 4: Update the nutrition CLI**

In `packages/tri-nutrition/src/tri_nutrition/cli.py`:

`_ready`: replace

```python
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready
    from tri_nutrition import store as S
```

with

```python
    from tri_core.harness.persistence import (
        SETUP_HINT,
        STORE_SETUP_HINT,
        checkpointer_ready,
        store_ready,
    )
```

and replace

```python
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
    return None
```

with

```python
    if not store_ready(settings.database_url):
        console.print(STORE_SETUP_HINT, style="red")
        return 2
    return None
```

`_chat`: replace `    from tri_core.harness.persistence import open_checkpointer` with `    from tri_core.harness.persistence import open_checkpointer, open_store`, and replace

```python
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)
        cfg = {"configurable": {"thread_id": THREAD_ID}}
```

with

```python
        store = await stack.enter_async_context(open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)
        cfg = {"configurable": {"thread_id": THREAD_ID}}
```

(`S.get_profile`, `S.get_fuel_log` and `S.get_product_library` later in `_chat` stay, so `import store as S` stays.)

`_today`: replace

```python
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec
    from tri_nutrition import store as S
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS
```

with

```python
    from tri_core.harness.persistence import STORE_SETUP_HINT, open_store, store_ready
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS
```

replace

```python
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
```

with

```python
    if not store_ready(settings.database_url):
        console.print(STORE_SETUP_HINT, style="red")
        return 2
```

and replace

```python
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), garmin)
```

with

```python
        store = await stack.enter_async_context(open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), garmin)
```

`_check_in`: replace

```python
    from tri_core.harness.persistence import open_checkpointer
    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
```

with

```python
    from tri_core.harness.persistence import open_checkpointer, open_store
    from tri_core.sync.runner import run_sync
```

and replace

```python
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)
        return await checkin_run(graph, thread_id=THREAD_ID, out=_out, approve=yes)
```

with

```python
        store = await stack.enter_async_context(open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)
        return await checkin_run(graph, thread_id=THREAD_ID, out=_out, approve=yes)
```

`_reset`: replace

```python
    from tri_core.harness.persistence import checkpointer_ready, open_checkpointer
```

with

```python
    from tri_core.harness.persistence import (
        checkpointer_ready,
        open_checkpointer,
        open_store,
        store_ready,
    )
```

and replace

```python
    if forget_profile and S.store_ready(settings.database_url):
        async with S.open_store(settings.database_url) as store:
            forgotten = await S.forget_all(store)
```

with

```python
    if forget_profile and store_ready(settings.database_url):
        async with open_store(settings.database_url) as store:
            forgotten = await S.forget_all(store)
```

Run: `rg -n "S\.(open_store|store_ready|STORE_SETUP_HINT)" packages/tri-nutrition`
Expected: no output.

- [ ] **Step 5: Update the coach CLI and its test**

In `packages/tri-coach/src/tri_coach/cli.py`:

`ready`: replace

```python
    from tri_coach.graph.checkpointer import SETUP_HINT, checkpointer_ready
    from tri_nutrition import store as S

    if not settings.anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set in .env"
    if not checkpointer_ready(settings.database_url):
        return SETUP_HINT
    if not S.store_ready(settings.database_url):
        return S.STORE_SETUP_HINT
    return None
```

with

```python
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

`_open_graph`: replace

```python
    from tri_coach.servers import open_servers
    from tri_nutrition import store as S
```

with

```python
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_store
```

and replace

```python
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), servers)
```

with

```python
        store = await stack.enter_async_context(open_store(settings.database_url))
        deps = make_deps(settings, make_model(settings), servers)
```

`_memory`: replace

```python
    from tri_coach import memory as M
    from tri_nutrition import store as S

    settings = get_coach_settings()
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
    async with S.open_store(settings.database_url) as store:
```

with

```python
    from tri_coach import memory as M
    from tri_core.harness.persistence import STORE_SETUP_HINT, open_store, store_ready

    settings = get_coach_settings()
    if not store_ready(settings.database_url):
        console.print(STORE_SETUP_HINT, style="red")
        return 2
    async with open_store(settings.database_url) as store:
```

`reset_thread`: replace

```python
    from tri_coach import memory as M
    from tri_coach.graph.checkpointer import checkpointer_ready, open_checkpointer
    from tri_nutrition import store as S
```

with

```python
    from tri_coach import memory as M
    from tri_coach.graph.checkpointer import checkpointer_ready, open_checkpointer
    from tri_core.harness.persistence import open_store, store_ready
```

and replace

```python
    if forget_memory and S.store_ready(settings.database_url):
        async with S.open_store(settings.database_url) as store:
```

with

```python
    if forget_memory and store_ready(settings.database_url):
        async with open_store(settings.database_url) as store:
```

`_check_in` keeps `from tri_nutrition import store as S` for `S.get_profile`.

In `packages/tri-coach/tests/test_cli.py`, replace both occurrences of `"tri_nutrition.store.store_ready"` with `"tri_core.harness.persistence.store_ready"`. Change nothing else.

- [ ] **Step 6: Update tri-web**

In `packages/tri-web/src/tri_web/runtime.py`, `open_runtime`, replace

```python
    from tri_coach.servers import open_servers
    from tri_nutrition import store as S
```

with

```python
    from tri_coach.servers import open_servers
    from tri_core.harness.persistence import open_store
```

and replace

```python
        store = await stack.enter_async_context(S.open_store(settings.database_url))
```

with

```python
        store = await stack.enter_async_context(open_store(settings.database_url))
```

In `packages/tri-web/src/tri_web/routes/system.py`, replace

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_nutrition.store import store_ready
from tri_web.schemas import Readiness, StatusOut
```

with

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.harness.persistence import store_ready
from tri_web.schemas import Readiness, StatusOut
```

In `packages/tri-web/tests/test_runtime.py`, replace

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel
from tri_nutrition.store import store_ready
from tri_web.config import WebSettings
```

with

```python
from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.config import Settings
from tri_core.harness.persistence import store_ready
from tri_core.testing import ScriptedChatModel
from tri_web.config import WebSettings
```

`tri-web/tests/test_routes_system.py` patches `"tri_web.routes.system.store_ready"`, a name `system.py` still binds, so it is not edited.

- [ ] **Step 7: Run the affected tests**

Run: `uv run pytest packages/tri-nutrition packages/tri-coach/tests/test_cli.py packages/tri-web -q`
Expected: the same counts as Step 1, all pass.

Run: `rg -n "S\.(open_store|store_ready|STORE_SETUP_HINT)|tri_nutrition\.store import store_ready|tri_nutrition\.store\.store_ready" packages scripts`
Expected: no output.

- [ ] **Step 8: Definition of done**

Run the six commands from Global Constraints.
Expected: `B passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 9: Commit**

```bash
git add -A packages/tri-nutrition packages/tri-coach/src/tri_coach/cli.py packages/tri-coach/tests/test_cli.py packages/tri-web
git commit -m "refactor(nutrition): open_store, store_ready and STORE_SETUP_HINT from tri_core.harness"
```

---

### Task 4: The conversational nodes use the harness `make_subagent`

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/llm.py`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/intake.py`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/adjust.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/llm.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py`
- Test: the existing node and graph tests of both packages (no edits)

**Interfaces:**
- Consumes (plan 1): `tri_core.harness.agents.make_subagent(model, tools, system_prompt, *, middleware=()) -> Any`. With no `middleware`, it builds `create_agent(model, list(tools), system_prompt=..., middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")], checkpointer=False)`, which is what the package copies build today.
- Produces: `tri_planning.graph.llm` and `tri_nutrition.graph.llm` hold only `MAX_TOKENS` and `make_model(settings) -> ChatAnthropic`.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-planning packages/tri-nutrition packages/tri-coach -q`
Expected: all pass (`test_adjust_node.py` 8, planning `test_intake_node.py` 3).

- [ ] **Step 2: Reduce both `llm.py` files to `make_model`**

Replace the whole of `packages/tri-planning/src/tri_planning/graph/llm.py`, and also the whole of `packages/tri-nutrition/src/tri_nutrition/graph/llm.py`, with:

```python
"""Model construction. The create_agent sub-agent the conversational nodes run is
tri_core.harness.agents.make_subagent."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
```

- [ ] **Step 3: Point the four nodes at the harness**

In `packages/tri-planning/src/tri_planning/graph/nodes/intake.py` and `packages/tri-planning/src/tri_planning/graph/nodes/adjust.py`, replace:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.llm import make_subagent
```

with:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import make_subagent
from tri_planning.graph.deps import GraphDeps
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py`, replace:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.allowlist import INTAKE_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
```

with:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import make_subagent
from tri_nutrition.allowlist import INTAKE_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py`, replace:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.allowlist import CHECKIN_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
```

with:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import make_subagent
from tri_nutrition.allowlist import CHECKIN_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
```

The call sites (`make_subagent(deps.model, tools, render_..._prompt(...))`) do not change.

- [ ] **Step 4: Run the affected tests**

Run: `uv run pytest packages/tri-planning packages/tri-nutrition packages/tri-coach -q`
Expected: the same counts as Step 1, all pass. `test_adjust_node.py`'s `monkeypatch.setattr(adjust_node, "make_subagent", record)` still works (fact 4).

Run: `rg -n "graph\.llm import make_subagent|def make_subagent" packages/tri-planning packages/tri-nutrition`
Expected: no output.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-planning/src/tri_planning/graph packages/tri-nutrition/src/tri_nutrition/graph
git commit -m "refactor(planning,nutrition): conversational nodes use tri_core.harness make_subagent"
```

---

### Task 5: Both REPLs run their turns on `run_graph_turn`

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/repl.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/repl.py`
- Test: `packages/tri-planning/tests/test_repl.py` (one test deleted), `packages/tri-nutrition/tests/test_repl.py`

**Interfaces:**
- Consumes (plan 1): from `tri_core.harness.turns`: `Out`, `GraphTurnPrinter(out: Out, streamed_nodes: frozenset[str] = frozenset())`, and `run_graph_turn(graph, payload, thread_id, out, *, streamed_nodes=frozenset()) -> GraphTurnPrinter`.
- Produces: `tri_planning.repl.run_turn(graph, payload, thread_id, out) -> GraphTurnPrinter` and `tri_nutrition.repl.run_turn(...)`, with unchanged signatures. `Out` and `STREAMED_NODES` stay importable from both modules.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-planning/tests/test_repl.py packages/tri-planning/tests/test_checkin.py packages/tri-nutrition/tests/test_repl.py packages/tri-nutrition/tests/test_graph.py -q`
Expected: all pass (planning `test_repl.py` 7, nutrition `test_repl.py` 7).

- [ ] **Step 2: Replace the planning printer**

In `packages/tri-planning/src/tri_planning/repl.py`, replace the imports and constants from `from __future__ import annotations` through `STREAMED_NODES = frozenset({"intake", "adjust"})`:

```python
from __future__ import annotations

from collections import defaultdict
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

from tri_planning.planning.models import CalendarChange, ReviewDecision
from tri_planning.planning.targets import week_monday

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[CalendarChange]], Awaitable[list[CalendarChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Nodes that host a sub-agent: their text was already streamed token by token, so the
# parent update that carries the same messages is not echoed again.
STREAMED_NODES = frozenset({"intake", "adjust"})
```

with:

```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_core.harness.turns import GraphTurnPrinter, run_graph_turn
from tri_core.harness.turns import Out as Out
from tri_planning.planning.models import CalendarChange, ReviewDecision
from tri_planning.planning.targets import week_monday

CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[CalendarChange]], Awaitable[list[CalendarChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Nodes that host a sub-agent: their text was already streamed token by token, so the
# parent update that carries the same messages is not echoed again.
STREAMED_NODES = frozenset({"intake", "adjust"})
```

Then replace everything from `def _text_of(msg: BaseMessage) -> str:` through the end of `run_turn` (the line `    return printer` before `def render_changes`) with:

```python
async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> GraphTurnPrinter:
    return await run_graph_turn(graph, payload, thread_id, out, streamed_nodes=STREAMED_NODES)
```

The module docstring and everything from `def render_changes` down are unchanged.

- [ ] **Step 3: Replace the nutrition printer**

In `packages/tri-nutrition/src/tri_nutrition/repl.py`, replace:

```python
from __future__ import annotations

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

from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    RaceFuelPlan,
    ReviewDecision,
    SessionFuel,
)
from tri_nutrition.prompts.checkin import CHECKIN_REQUEST

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
```

with:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import yaml
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_core.harness.turns import GraphTurnPrinter, run_graph_turn
from tri_core.harness.turns import Out as Out
from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    RaceFuelPlan,
    ReviewDecision,
    SessionFuel,
)
from tri_nutrition.prompts.checkin import CHECKIN_REQUEST

CommandFn = Callable[[], Awaitable[str]]
```

Then replace everything from `def _text_of(msg: BaseMessage) -> str:` through the end of `run_turn` (the line `    return printer` before `def render_review`) with:

```python
async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> GraphTurnPrinter:
    return await run_graph_turn(graph, payload, thread_id, out, streamed_nodes=STREAMED_NODES)
```

`render_targets`, `render_fuel` and `render_race` above it, and everything from `def render_review` down, are unchanged.

- [ ] **Step 4: Update the planning REPL test**

In `packages/tri-planning/tests/test_repl.py`, delete `test_turn_printer_handles_subgraph_events_and_interrupt` (the whole function, from `def test_turn_printer_handles_subgraph_events_and_interrupt():` through `    assert p.interrupt == {"summary": "s", "changes": []}`, and one of the two blank lines around it). Its events and assertions are covered by `packages/tri-core/tests/test_harness_turns.py::test_graph_printer_handles_subgraph_events_interrupt_and_streamed_nodes` (fact 10).

Then replace the imports:

```python
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.repl import (
    TurnPrinter,
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    parse_decision,
    render_changes,
    run_turn,
)
```

with:

```python
from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.repl import (
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    parse_decision,
    render_changes,
    run_turn,
)
```

`test_run_turn_sets_error_on_api_connection_failure` and every other test are unchanged.

- [ ] **Step 5: Update the nutrition REPL test**

In `packages/tri-nutrition/tests/test_repl.py`, replace:

```python
from tri_nutrition.nutrition.models import DayTarget, NutritionChange
from tri_nutrition.repl import (
    TurnPrinter,
    changes_from_yaml,
```

with:

```python
from tri_core.harness.turns import GraphTurnPrinter
from tri_nutrition.nutrition.models import DayTarget, NutritionChange
from tri_nutrition.repl import (
    STREAMED_NODES,
    changes_from_yaml,
```

and in `test_turn_printer_handles_subgraph_events_and_interrupt` replace `    p = TurnPrinter(buf.append)` with `    p = GraphTurnPrinter(buf.append, STREAMED_NODES)`. Change nothing else.

- [ ] **Step 6: Run the affected tests**

Run: `uv run pytest packages/tri-planning/tests/test_repl.py packages/tri-planning/tests/test_checkin.py packages/tri-nutrition/tests/test_repl.py packages/tri-nutrition/tests/test_graph.py -q`
Expected: planning `test_repl.py` 6 (one deleted), nutrition `test_repl.py` 7, all pass.

Run: `rg -n "_text_of|class TurnPrinter|TurnPrinter\b" packages/tri-planning packages/tri-nutrition`
Expected: no output.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `B-1 passed, 6 skipped`, ruff clean, `mypy` `Success`. If `mypy` reports `Module "tri_planning.repl" does not explicitly export attribute "Out"`, stop (see Stop conditions).

- [ ] **Step 8: Commit**

```bash
git add packages/tri-planning/src/tri_planning/repl.py packages/tri-planning/tests/test_repl.py packages/tri-nutrition/src/tri_nutrition/repl.py packages/tri-nutrition/tests/test_repl.py
git commit -m "refactor(planning,nutrition): REPL turns run on tri_core.harness run_graph_turn"
```

---

### Task 6: Scope check, README, and final verification

**Files:**
- Modify: `packages/tri-planning/README.md`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: nothing new.

- [ ] **Step 1: Prove the copies are gone**

Run:

```bash
rg -n "def _text_of|class TurnPrinter|def make_subagent|def make_serde|def open_checkpointer|def checkpointer_ready|def open_store|def store_ready|^STORE_SETUP_HINT|^SETUP_HINT" packages/tri-planning packages/tri-nutrition
ls packages/tri-planning/src/tri_planning/graph/checkpointer.py packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py
rg -n "tri_(planning|nutrition)\.graph\.checkpointer|graph\.llm import make_subagent|S\.(open_store|store_ready|STORE_SETUP_HINT)|tri_nutrition\.store(\.| import )(open_store|store_ready|STORE_SETUP_HINT)" packages scripts
```

Expected:
- The first and third commands print nothing.
- `ls` reports `No such file or directory` for both paths.

If either `rg` finds a file this plan does not list, stop (see Stop conditions).

Run: `git diff --name-only main...HEAD`
Expected: only paths from "Files this plan may touch" in Global Constraints.

- [ ] **Step 2: Update the tri-planning README**

In `packages/tri-planning/README.md`, section `## Layout`, replace:

```markdown
- `graph/`: `state.py` (PlanningState), `deps.py` (GraphDeps), `llm.py` (model, sub-agent
  factory), `nodes/` (one file per node), `graph.py` (wiring and route functions),
  `checkpointer.py` (AsyncPostgresSaver).
```

with:

```markdown
- `graph/`: `state.py` (PlanningState and the `STATE_TYPES` its checkpointer registers),
  `deps.py` (GraphDeps), `llm.py` (model), `nodes/` (one file per node), `graph.py` (wiring and
  route functions). The sub-agent factory, the Postgres checkpointer and the turn printer come
  from `tri_core.harness`.
```

and replace:

```markdown
- `repl.py`: terminal I/O, event rendering, the review dialogue, YAML edit round trip.
```

with:

```markdown
- `repl.py`: terminal I/O over `tri_core.harness.turns`, the review dialogue, YAML edit round
  trip.
```

Run: `rg -n "checkpointer\.py|sub-agent factory|_text_of|TurnPrinter|open_store|store_ready|STORE_SETUP_HINT" packages/tri-planning/README.md packages/tri-nutrition/README.md packages/tri-coach/README.md packages/tri-web/README.md README.md`
Expected: no output. (`tri-nutrition/README.md` mentions only `scripts/setup_checkpointer.py` and the Store namespace, which stay correct.)

Copy `packages/tri-planning/README.md` to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-planning/readme.md`, creating the directory if it does not exist.

- [ ] **Step 3: Definition of done**

Run the six commands from Global Constraints.
Expected: `B-1 passed, 6 skipped, 1 warning`, ruff clean, `mypy` `Success`. This plan adds no build step, and `web/` is untouched.

- [ ] **Step 4: Commit**

```bash
git add packages/tri-planning/README.md
git commit -m "docs(planning): README layout points at tri_core.harness"
```

---

## Self-review against the spec

- **§4 layout:**
  - tri-planning: `graph/checkpointer.py` deleted with `STATE_TYPES` moved to `graph/state.py` (Task 1); `graph/llm.py` drops `make_subagent` (Task 4); `repl.py` drops `_text_of` and `TurnPrinter`, with `run_turn` wrapping `run_graph_turn` (Task 5).
  - tri-nutrition: the same (Tasks 2, 4, 5), and `store.py` loses `open_store`, `store_ready` and `STORE_SETUP_HINT` while keeping its namespace, keys and typed access (Task 3).
  - tri-web: `runtime.py` and `routes/system.py` (Task 3). Their `checkpointer_ready` and `open_checkpointer` imports stay for plan 4.
- **§5.5:** callers pass `STATE_TYPES` to `open_checkpointer` and `make_serde` (Tasks 1–2). The coach graph builds `InMemorySaver(serde=make_serde(<package>.graph.state.STATE_TYPES))` for both subgraphs (Tasks 1–2). `STORE_SETUP_HINT` is imported from the harness with its text unchanged (Task 3).
- **§5.7:**
  - Both `run_turn`s keep their signatures and call `run_graph_turn(..., streamed_nodes=STREAMED_NODES)` (Task 5).
  - `Out` stays importable from both REPLs through an explicit re-export (fact 8).
  - Domain dialogues are untouched.
- **§6:** no output, error-sentence, serde or readiness change. Nutrition's printer now records `error` (the spec's one listed internal difference). The fakes and patches keep working (facts 4, 5).
- **§7 rules for plans 02–04:**
  - Assertions are not edited.
  - The changes are imports, `open_checkpointer(url, STATE_TYPES)` and `make_serde(STATE_TYPES)` arguments, `GraphTurnPrinter(buf.append, STREAMED_NODES)`, and the `"tri_core.harness.persistence.store_ready"` patch target.
  - One test that only duplicates a tri-core test is deleted and named (Task 5, fact 10).
  - The CLIs keep readiness imports inside function bodies (Tasks 1–3).
- **§9 item 3:** every listed source file, importer and test is covered. Fact 3 lists what the spec's lists missed (the `test_routes_system.py` note, `tri-planning/README.md`, `_memory`/`reset_thread` in `tri_coach/cli.py`).
- **Test delta:** −1 (`tri-planning/tests/test_repl.py::test_turn_printer_handles_subgraph_events_and_interrupt`). End state: `B-1 passed, 6 skipped`.
- **Hand-off to plan 4:** `tri_coach/cli.py`, `tri_web/routes/system.py`, `tri_web/runtime.py`, `tri-web/tests/test_runtime.py` and `tri-coach/tests/test_cli.py` already import Store pieces from `tri_core.harness.persistence` when plan 4 starts. Plan 4's replacements for the coach checkpointer lines in those files must be written against this plan's result.
