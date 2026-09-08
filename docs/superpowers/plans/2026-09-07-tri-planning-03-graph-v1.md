# tri-planning Plan 3 of 4: Graph v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `tri-planning chat` REPL in which a hand-built LangGraph `StateGraph` takes the athlete from intake (a `create_agent` sub-agent that establishes a `TrainingGoal`) through the pure targets, per-week session design by the model, a human-in-the-loop review pause, and an `apply` step that writes approved sessions to the TrainingPeaks calendar, with state persisted in Postgres so a review decision survives process exit. First plan on the calendar. This is spec milestone 3.

**Architecture:** `build_graph(deps, checkpointer)` compiles a `StateGraph[PlanningState]` with nodes `intake`, `targets`, `design`, `review`, `apply` and a placeholder `adjust` (Plan 4 replaces it). Nodes are closures over a `GraphDeps` dataclass (model, a connection factory, an optional TrainingPeaks `ToolCaller`, horizon, a `today` callable) so tests inject `ScriptedChatModel`, a rolled-back connection and a `FakeTp`. Only `apply` calls TrainingPeaks write tools; `review` calls `langgraph.types.interrupt` and the REPL resumes with `Command(resume=decision)`. `AsyncPostgresSaver` checkpoints every node transition in the shared database under thread `planning`.

**Tech Stack:** langgraph 1.2 (`StateGraph`, `interrupt`, `Command`, `add_messages`), langchain 1.4 (`create_agent`, `with_structured_output`), langchain-anthropic 1.7, `langgraph-checkpoint-postgres` 3.1 (`AsyncPostgresSaver`), `tri_core.mcp.client.McpToolClient` for TrainingPeaks, pyyaml for the edit round trip, rich.

**Spec:** `docs/superpowers/specs/2026-09-07-tri-planning-design.md` (§2 Feasibility, §6 The graph, §8 Commands `chat` and `reset`, §9 Error handling, §11 Testing, §12 Observability, §15 open items). Depends on Plans 1 and 2.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- Model: `claude-opus-5` via `ChatAnthropic`, `max_tokens=16000`, no `thinking` parameter. `TRI_MODEL` in `.env` overrides.
- **Write tools are never bound to a sub-agent.** The intake sub-agent binds `query_training_db`, `list_tp_training_plans`, `set_training_goal` only. The five TrainingPeaks write tools (`tp_create_workout`, `tp_update_workout`, `tp_delete_workout`, `tp_create_event`, `tp_apply_training_plan`) are called only from `apply`, through `ToolCaller.call_json`, never as LangChain tools.
- **The graph pauses with `interrupt()` before any TrainingPeaks write.** There is no path from `design` or `targets` to `apply` that skips `review`.
- Thread id for the athlete's plan is the string `planning`. `reset` clears that thread's checkpoints and marks the goal abandoned and the plan superseded; it never touches TrainingPeaks.
- `chat` refuses to start when the checkpoint tables are missing; there is no in-memory fallback.
- TrainingPeaks facts verified from the pinned server source (`a412a84e`): `tp_create_workout` returns `{"success": true, "workout_id": ..., "title", "date", "sport"}`; `tp_update_workout` accepts `date` (a move) and returns `{"success": true, "workout_id"}`; `tp_delete_workout` returns `{"success": true, "message"}`; `tp_create_event` returns `{"success": true, "event_id", "name", "date"}`; `tp_apply_training_plan(plan_id, start_date)` returns only counts (`created`, `failed`, `skipped_periods`, `total`) and no ids, so ownership of applied workouts needs a follow-up `tp_get_workouts(start_date, end_date, workout_filter="planned")` whose rows carry `id`, `date`, `tss_planned`, `duration_planned`. TP sport names are `Swim`, `Bike`, `Run`, `Brick`, `Strength`, `DayOff`. Simplified structure: `{"primaryIntensityMetric": "percentOfFtp" | "percentOfThresholdHr" | "percentOfThresholdPace", "steps": [{"name", "duration_seconds", "intensity_min", "intensity_max", "intensityClass": "warmUp"|"active"|"rest"|"coolDown"|"other"} | {"type": "repetition", "reps", "steps": [...]}]}`.
- **Brian runs every git command, applies DDL (`scripts/setup_checkpointer.py`), and has the first real conversation.** Tests write only through the rolled-back `db` fixture, except the Postgres checkpointer test, which uses a random thread id and deletes it afterwards.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`PlanningState` gains `changes_from` and `tp_plan_applied`.** Reject must route back to the node that produced the change set, and the post-`apply_plan` re-entry into `targets` must be distinguishable from the first entry. Neither can be derived from the eight spec fields.
- **`START` routes to `review` when `pending_changes` is non-empty**, regardless of `phase`. This is how "re-running review re-proposes only the unapplied remainder" (spec §9) works after a mid-batch failure or a process exit.
- **`reset` keeps thread id `planning` and deletes its checkpoints** (`AsyncPostgresSaver.adelete_thread`) instead of rotating ids. Every command can then hard-code the thread id; nothing has to remember the current one.
- **The `create_event` change is emitted by `design` (generated plans) or `targets` (bought plans)**, first in the change set, when `goal.create_tp_event` is true and no `tp_event_id` is stored yet.
- **Rejecting the `apply_plan` proposal ends the turn** with the note in messages; the next turn re-proposes. Routing back into `targets` would loop without new information.
- **Rest days are not written to TrainingPeaks.** `PlannedSession` with `sport == "rest"` stays in `plan_weeks.designed` for the record but produces no `CalendarChange`.
- **The design node redesigns every window week that is not yet `written_to_tp`**, so a reject redesigns the same weeks with the note, and an already-designed but unwritten week (process exit before approval) is designed again rather than re-proposed from stale JSON.

---

## File Structure

```
packages/tri-planning/src/tri_planning/
  allowlist.py                TP_WRITE_TOOLS, TP_READ_TOOLS (intake), GARMIN_LIVE_TOOLS (Plan 4)
  planning/tp_calls.py        TP_SPORT, to_tp_call(change), result_workout_id(change, result), event_change(goal)
  graph/__init__.py
  graph/state.py              PlanningState
  graph/deps.py               GraphDeps, ConnectFactory
  graph/llm.py                make_model(settings), make_subagent(model, tools, prompt)
  graph/checkpointer.py       open_checkpointer(url), checkpointer_ready(url)
  graph/graph.py              build_graph(deps, checkpointer), route functions
  graph/nodes/__init__.py
  graph/nodes/intake.py       make_intake_node(deps), goal_id_from_messages(messages)
  graph/nodes/targets.py     make_targets_node(deps)
  graph/nodes/design.py       make_design_node(deps), window_weeks(weeks, today, horizon)
  graph/nodes/review.py       review_node(state)
  graph/nodes/apply.py        make_apply_node(deps)
  graph/nodes/adjust.py       placeholder until Plan 4
  tools/__init__.py
  tools/goal.py               make_goal_tools(connect, tp, today) -> [set_training_goal, list_tp_training_plans]
  prompts/__init__.py
  prompts/intake.py           render_intake_prompt(today)
  prompts/design.py           DESIGN_SYSTEM, render_design_prompt(...)
  repl.py                     TurnPrinter, run_turn, render_changes, parse_decision, changes_to_yaml, changes_from_yaml, chat_loop
  testing.py                  FakeTp, NoCommit, MONDAY, GOAL_ARGS, week_json (test doubles)
  cli.py                      chat, reset
packages/tri-planning/tests/
  conftest.py                 FakeTp, NoCommit, deps factory fixtures
  test_tp_calls.py
  test_goal_tools.py
  test_intake_node.py
  test_targets_node.py       db
  test_design_node.py         db
  test_apply_node.py          db
  test_graph.py               db (end to end with ScriptedChatModel + FakeTp + InMemorySaver)
  test_checkpointer.py        db (AsyncPostgresSaver resume)
  test_repl.py
scripts/setup_checkpointer.py
```

Responsibilities: `tp_calls.py` is the only place that knows TrainingPeaks tool names and argument shapes. `graph/nodes/*` each own one node and nothing else; they share `GraphDeps`. `graph/graph.py` owns wiring and routing. `repl.py` owns terminal I/O, event rendering and the review dialogue. `cli.py` opens resources (MCP session, checkpointer) and hands them to the graph.

---

### Task 1: TrainingPeaks call translation and allow-lists

**What this teaches:** keeping the external API's vocabulary in one pure module so the graph speaks in `CalendarChange` and the tests never need a server.

**Files:**
- Create: `packages/tri-planning/src/tri_planning/allowlist.py`, `packages/tri-planning/src/tri_planning/planning/tp_calls.py`
- Test: `packages/tri-planning/tests/test_tp_calls.py`

**Interfaces:**
- Consumes: `CalendarChange`, `PlannedSession`, `TrainingGoal` (Plan 2).
- Produces:
  - `allowlist.TP_WRITE_TOOLS = ["tp_create_workout", "tp_update_workout", "tp_delete_workout", "tp_create_event", "tp_apply_training_plan"]`, `allowlist.TP_READ_TOOLS = ["tp_get_workouts", "tp_list_training_plans"]`, `allowlist.GARMIN_LIVE_TOOLS = ["get_training_readiness", "get_hrv_data"]`.
  - `tp_calls.TP_SPORT: dict[Sport, str]`.
  - `tp_calls.to_tp_call(change: CalendarChange) -> tuple[str, dict[str, Any]]`; raises `ValueError` when the change lacks what its op needs.
  - `tp_calls.result_workout_id(change: CalendarChange, result: Any) -> str | None`.
  - `tp_calls.event_change(goal: TrainingGoal) -> CalendarChange`.

- [x] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_tp_calls.py`:
```python
from datetime import date

import pytest

from tri_planning.allowlist import TP_READ_TOOLS, TP_WRITE_TOOLS
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal
from tri_planning.planning.tp_calls import event_change, result_workout_id, to_tp_call

STRUCTURE = {
    "primaryIntensityMetric": "percentOfFtp",
    "steps": [{"name": "steady", "duration_seconds": 3600, "intensity_min": 60, "intensity_max": 70}],
}


def session(**over) -> PlannedSession:
    base = dict(date=date(2026, 9, 14), sport="bike", title="Endurance ride", description="Zone 2",
                duration_minutes=60, tss_planned=55.0, intensity="endurance", structure=None)
    base.update(over)
    return PlannedSession(**base)


def test_create_maps_sport_and_fields():
    name, args = to_tp_call(CalendarChange(op="create", workout_date=date(2026, 9, 14),
                                           workout=session(structure=STRUCTURE), reason="r"))
    assert name == "tp_create_workout"
    assert args == {
        "date_str": "2026-09-14", "sport": "Bike", "title": "Endurance ride",
        "duration_minutes": 60, "description": "Zone 2", "tss_planned": 55.0,
        "structure": STRUCTURE,
    }


def test_create_without_structure_omits_key():
    _, args = to_tp_call(CalendarChange(op="create", workout=session(), reason="r"))
    assert "structure" not in args


def test_update_move_delete():
    _, args = to_tp_call(CalendarChange(op="update", tp_workout_id="9", workout=session(title="T"), reason="r"))
    assert args["workout_id"] == "9" and args["title"] == "T" and args["sport"] == "Bike"
    name, args = to_tp_call(CalendarChange(op="move", tp_workout_id="9", new_date=date(2026, 9, 16), reason="r"))
    assert (name, args) == ("tp_update_workout", {"workout_id": "9", "date": "2026-09-16"})
    name, args = to_tp_call(CalendarChange(op="delete", tp_workout_id="9", reason="r"))
    assert (name, args) == ("tp_delete_workout", {"workout_id": "9"})


def test_apply_plan_and_event_pass_payload():
    name, args = to_tp_call(CalendarChange(op="apply_plan", payload={"plan_id": "p1", "start_date": "2026-09-14"}, reason="r"))
    assert (name, args) == ("tp_apply_training_plan", {"plan_id": "p1", "start_date": "2026-09-14"})
    name, args = to_tp_call(CalendarChange(op="create_event", payload={"name": "X", "date": "2026-12-13"}, reason="r"))
    assert name == "tp_create_event" and args["name"] == "X"


@pytest.mark.parametrize("change", [
    CalendarChange(op="create", reason="no workout"),
    CalendarChange(op="delete", reason="no id"),
    CalendarChange(op="move", tp_workout_id="1", reason="no new_date"),
    CalendarChange(op="apply_plan", reason="no payload"),
])
def test_missing_fields_raise(change):
    with pytest.raises(ValueError):
        to_tp_call(change)


def test_result_workout_id():
    create = CalendarChange(op="create", workout=session(), reason="r")
    assert result_workout_id(create, {"success": True, "workout_id": 123}) == "123"
    assert result_workout_id(create, {"success": True}) is None
    delete = CalendarChange(op="delete", tp_workout_id="9", reason="r")
    assert result_workout_id(delete, {"success": True}) == "9"
    assert result_workout_id(CalendarChange(op="apply_plan", payload={}, reason="r"), {}) is None


def test_event_change_from_goal():
    g = TrainingGoal(goal_type="olympic", event_name="City Tri", event_date=date(2026, 12, 13),
                     priority="A", weekly_hours_min=5, weekly_hours_max=10, available_days={},
                     create_tp_event=True)
    c = event_change(g)
    assert c.op == "create_event"
    assert c.payload == {"name": "City Tri", "date": "2026-12-13", "event_type": "MultisportTriathlon", "priority": "A"}


def test_allowlists_are_disjoint_and_named_as_expected():
    assert set(TP_WRITE_TOOLS).isdisjoint(TP_READ_TOOLS)
    assert all(t.startswith("tp_") for t in TP_WRITE_TOOLS + TP_READ_TOOLS)
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_tp_calls.py -q`
Expected: `ImportError`.

- [x] **Step 3: Write `allowlist.py` and `tp_calls.py`**

`packages/tri-planning/src/tri_planning/allowlist.py`:
```python
"""Which MCP tools each part of the planning agent may call.

Write tools are never bound to a sub-agent; only the apply node calls them, by name, through
ToolCaller.call_json.
"""

TP_WRITE_TOOLS = [
    "tp_create_workout",
    "tp_update_workout",
    "tp_delete_workout",
    "tp_create_event",
    "tp_apply_training_plan",
]
TP_READ_TOOLS = ["tp_get_workouts", "tp_list_training_plans"]
GARMIN_LIVE_TOOLS = ["get_training_readiness", "get_hrv_data"]
```

`packages/tri-planning/src/tri_planning/planning/tp_calls.py`:
```python
"""CalendarChange -> (TrainingPeaks MCP tool name, arguments). Pure."""

from __future__ import annotations

from typing import Any

from tri_planning.planning.models import CalendarChange, PlannedSession, Sport, TrainingGoal

TP_SPORT: dict[Sport, str] = {
    "swim": "Swim",
    "bike": "Bike",
    "run": "Run",
    "brick": "Brick",
    "strength": "Strength",
    "rest": "DayOff",
}


def _workout_args(w: PlannedSession) -> dict[str, Any]:
    args: dict[str, Any] = {
        "sport": TP_SPORT[w.sport],
        "title": w.title,
        "duration_minutes": w.duration_minutes,
        "description": w.description,
        "tss_planned": w.tss_planned,
    }
    if w.structure is not None:
        args["structure"] = w.structure
    return args


def to_tp_call(change: CalendarChange) -> tuple[str, dict[str, Any]]:
    op = change.op
    if op == "create":
        if change.workout is None:
            raise ValueError("create needs a workout")
        return "tp_create_workout", {"date_str": change.workout.date.isoformat(), **_workout_args(change.workout)}
    if op == "update":
        if change.tp_workout_id is None or change.workout is None:
            raise ValueError("update needs tp_workout_id and a workout")
        return "tp_update_workout", {"workout_id": change.tp_workout_id, **_workout_args(change.workout)}
    if op == "move":
        if change.tp_workout_id is None or change.new_date is None:
            raise ValueError("move needs tp_workout_id and new_date")
        return "tp_update_workout", {"workout_id": change.tp_workout_id, "date": change.new_date.isoformat()}
    if op == "delete":
        if change.tp_workout_id is None:
            raise ValueError("delete needs tp_workout_id")
        return "tp_delete_workout", {"workout_id": change.tp_workout_id}
    if op == "apply_plan":
        if not change.payload or "plan_id" not in change.payload or "start_date" not in change.payload:
            raise ValueError("apply_plan needs payload with plan_id and start_date")
        return "tp_apply_training_plan", {"plan_id": change.payload["plan_id"], "start_date": change.payload["start_date"]}
    if op == "create_event":
        if not change.payload or "name" not in change.payload or "date" not in change.payload:
            raise ValueError("create_event needs payload with name and date")
        return "tp_create_event", dict(change.payload)
    raise ValueError(f"unknown op {op}")


def result_workout_id(change: CalendarChange, result: Any) -> str | None:
    if change.op == "create":
        wid = result.get("workout_id") if isinstance(result, dict) else None
        return str(wid) if wid is not None else None
    if change.op in ("update", "move", "delete"):
        return change.tp_workout_id
    return None


def event_change(goal: TrainingGoal) -> CalendarChange:
    if goal.event_date is None:
        raise ValueError("goal has no event_date")
    return CalendarChange(
        op="create_event",
        workout_date=goal.event_date,
        payload={
            "name": goal.event_name or goal.goal_type,
            "date": goal.event_date.isoformat(),
            "event_type": "MultisportTriathlon",
            "priority": goal.priority or "A",
        },
        reason=f"race day: {goal.event_name or goal.goal_type} on {goal.event_date}",
    )
```

- [x] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_tp_calls.py -q`
Expected: 9 passed (the parametrized test counts as 4).

- [x] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): TrainingPeaks call translation and allow-lists"
```

---

### Task 2: State, deps, sub-agent factory, test conftest

**What this teaches:** the shape of a hand-built LangGraph: a `TypedDict` state with one reducer (`add_messages`), and dependency injection through closures so nodes stay testable.

**Files:**
- Create: `packages/tri-planning/src/tri_planning/graph/__init__.py`, `graph/state.py`, `graph/deps.py`, `graph/llm.py`, `graph/nodes/__init__.py`, `tools/__init__.py`, `prompts/__init__.py`
- Create: `packages/tri-planning/src/tri_planning/testing.py`, `packages/tri-planning/tests/conftest.py`

**Interfaces:**
- Produces:
  - `state.PlanningState(TypedDict, total=False)` with `messages: Annotated[list[AnyMessage], add_messages]`, `phase: Literal["intake","planning","active"]`, `goal_id: int | None`, `plan_id: int | None`, `pending_changes: list[CalendarChange]`, `pending_summary: str | None`, `review_decision: ReviewDecision | None`, `last_error: str | None`, `changes_from: Literal["targets","design","adjust"] | None`, `tp_plan_applied: bool`.
  - `deps.ConnectFactory = Callable[[], AbstractContextManager[Conn]]`; `deps.GraphDeps(model: BaseChatModel, connect: ConnectFactory, db_url: str, tp: ToolCaller | None = None, garmin_tools: list[BaseTool] = [], horizon_weeks: int = 3, today: Callable[[], date] = date.today)`; `deps.make_deps(settings, model, tp) -> GraphDeps`.
  - `llm.make_model(settings) -> ChatAnthropic`; `llm.make_subagent(model, tools, system_prompt) -> CompiledStateGraph` (`create_agent` with `AnthropicPromptCachingMiddleware`, `checkpointer=False`).
  - `tri_planning.testing`: `MONDAY = date(2026, 9, 14)`, `ALL_DAYS`, `GOAL_ARGS` (a valid olympic goal 14 weeks out, JSON-safe), `week_json(week_start, target_tss, *, hard_on_consecutive_days=False)` (a `PlannedWeek` dict with three sessions summing to the target), `FakeTp`, `NoCommit`.
  - conftest fixtures: `fake_tp` (`FakeTp`), `nocommit` (`db` wrapped so `commit()` and `close()` are no-ops), `make_deps` (factory `(model, *, tp=None, horizon=1, today=MONDAY, garmin_tools=None) -> GraphDeps`).

- [x] **Step 1: Write the modules**

`graph/state.py`:
```python
"""Graph state. One reducer: messages accumulate; every other key is last-write-wins."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_planning.planning.models import CalendarChange, ReviewDecision


class PlanningState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    phase: Literal["intake", "planning", "active"]
    goal_id: int | None
    plan_id: int | None
    pending_changes: list[CalendarChange]
    pending_summary: str | None
    review_decision: ReviewDecision | None
    last_error: str | None
    changes_from: Literal["targets", "design", "adjust"] | None
    tp_plan_applied: bool
```

`graph/deps.py`:
```python
"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_core.sync import ToolCaller
from tri_planning.config import PlanningSettings

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    db_url: str  # for the read-only SQL tool, which opens its own connections
    tp: ToolCaller | None = None  # live TrainingPeaks session; None when the server is down
    garmin_tools: list[BaseTool] = field(default_factory=list)  # Plan 4
    horizon_weeks: int = 3
    today: Callable[[], date] = date.today


def make_deps(settings: PlanningSettings, model: BaseChatModel, tp: ToolCaller | None) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        tp=tp,
        horizon_weeks=settings.tri_planning_horizon_weeks,
    )
```

`graph/llm.py`:
```python
"""Model construction and the create_agent sub-agent used inside conversational nodes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key)


def make_subagent(model: BaseChatModel, tools: Sequence[BaseTool], system_prompt: str) -> Any:
    """A tool-calling loop with no checkpointer of its own: the parent graph owns the messages.

    LangGraph lesson: a compiled graph invoked inside a node is a subgraph. `checkpointer=False`
    stops it from writing its own checkpoints under the parent's namespace; the parent state
    already carries the conversation.
    """
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        checkpointer=False,  # if this version rejects False, pass None
    )
```

Empty `__init__.py` files for `graph/`, `graph/nodes/`, `tools/`, `prompts/`.

- [x] **Step 2: Write the test doubles module and the test conftest**

The doubles live in the package (`tri_planning.testing`) rather than under `tests/` because
`--import-mode=importlib` gives test directories no importable package name.

`packages/tri-planning/src/tri_planning/testing.py`:
```python
"""Test doubles for the planning graph: a fake TrainingPeaks caller, a no-commit connection
wrapper, and canned goal/week payloads. Imported by tests only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.mcp.client import McpToolError

MONDAY = date(2026, 9, 14)
ALL_DAYS = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

GOAL_ARGS: dict[str, Any] = {
    "goal_type": "olympic",
    "event_name": "City Tri",
    "event_date": (MONDAY + timedelta(weeks=13, days=6)).isoformat(),
    "priority": "A",
    "weekly_hours_min": 4,
    "weekly_hours_max": 12,
    "available_days": ALL_DAYS,
    "constraints": ["pool closed Fridays"],
    "create_tp_event": False,
}


def week_json(week_start: date, target_tss: float, *, hard_on_consecutive_days: bool = False) -> dict[str, Any]:
    """A PlannedWeek as the model would return it (JSON-safe). Three sessions summing to target."""
    a = round(target_tss * 0.4)
    b = round(target_tss * 0.3)
    c = target_tss - a - b
    d2 = 1 if hard_on_consecutive_days else 2
    return {
        "week_start": week_start.isoformat(),
        "coach_note": "steady aerobic week",
        "sessions": [
            {"date": week_start.isoformat(), "sport": "bike", "title": "Endurance ride",
             "description": "z2", "duration_minutes": 90, "tss_planned": a, "intensity": "endurance"},
            {"date": (week_start + timedelta(days=d2)).isoformat(), "sport": "run", "title": "Threshold run",
             "description": "4x6", "duration_minutes": 60, "tss_planned": b, "intensity": "threshold"},
            {"date": (week_start + timedelta(days=4)).isoformat(), "sport": "swim", "title": "CSS swim",
             "description": "10x100", "duration_minutes": 45, "tss_planned": c, "intensity": "threshold" if hard_on_consecutive_days else "endurance"},
        ],
    }


class FakeTp:
    """Records every call; answers like the real server. `fail_on_call` raises on the nth call."""

    def __init__(self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append((tool, dict(args or {})))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "API_ERROR: boom")
        if tool in self.responses:
            return self.responses[tool]
        if tool == "tp_create_workout":
            return {"success": True, "workout_id": 1000 + len(self.calls), "title": args["title"] if args else ""}
        if tool == "tp_update_workout":
            return {"success": True, "workout_id": (args or {})["workout_id"]}
        if tool == "tp_delete_workout":
            return {"success": True, "message": "deleted"}
        if tool == "tp_create_event":
            return {"success": True, "event_id": 77, "name": (args or {}).get("name")}
        if tool == "tp_apply_training_plan":
            return {"success": True, "created": 3, "failed": 0, "skipped_periods": 0, "total": 3}
        if tool == "tp_get_workouts":
            return {"workouts": [], "count": 0}
        if tool == "tp_list_training_plans":
            return {"plans": [{"id": "p1", "name": "12 week olympic"}]}
        return {}


class NoCommit:
    """The rolled-back test connection, with commit/close turned into no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
```

`packages/tri-planning/tests/conftest.py` (fixtures only; the root conftest is the `pytest_plugins` host):
```python
from __future__ import annotations

import contextlib

import pytest

from tri_planning.graph.deps import GraphDeps
from tri_planning.testing import MONDAY, FakeTp, NoCommit


@pytest.fixture
def fake_tp() -> FakeTp:
    return FakeTp()


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def make_deps(nocommit):
    from tri_core.config import Settings

    def _make(model, *, tp=None, horizon=1, today=MONDAY, garmin_tools=None) -> GraphDeps:
        return GraphDeps(
            model=model,
            connect=lambda: contextlib.nullcontext(nocommit),
            db_url=Settings().test_database_url,
            tp=tp,
            garmin_tools=list(garmin_tools or []),
            horizon_weeks=horizon,
            today=lambda: today,
        )

    return _make
```

- [x] **Step 3: Verify import, lint, type-check, commit (Brian)**

```bash
uv run python -c "import tri_planning.graph.state, tri_planning.graph.deps, tri_planning.graph.llm; print('ok')"
uv run pytest packages/tri-planning -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): graph state, deps, sub-agent factory, test doubles"
```

---

### Task 3: Goal tools and the intake node

**What this teaches:** a tool that does real work (validates a Pydantic model, writes a row) and a `create_agent` sub-agent embedded inside a hand-built graph node, with the node reading the sub-agent's tool result to decide the next edge.

**Files:**
- Create: `tools/goal.py`, `prompts/intake.py`, `graph/nodes/intake.py`
- Test: `tests/test_goal_tools.py`, `tests/test_intake_node.py`

**Interfaces:**
- Consumes: `repo.insert_goal`, `targets.next_monday`, `targets.count_weeks`, `targets.allocate_phases`, `periodization.PHASE_TABLE`, `make_subagent`, `tri_analyze`-free SQL tool (see note), `GraphDeps`.
- Produces:
  - `tools.goal.make_goal_tools(connect: ConnectFactory, tp: ToolCaller | None, today: Callable[[], date]) -> list[BaseTool]` returning `[set_training_goal, list_tp_training_plans]`. `set_training_goal` takes the `TrainingGoal` fields as arguments, returns JSON text `{"goal_id": int, "weeks": int, "compressed": bool, "warning": str | null}` or `{"error": str}` (goal not saved). `list_tp_training_plans` returns the server's JSON or `{"error": "TrainingPeaks server unavailable"}`.
  - `prompts.intake.render_intake_prompt(today: date) -> str`.
  - `nodes.intake.goal_id_from_messages(messages) -> int | None`.
  - `nodes.intake.make_intake_node(deps) -> async node`; returns `{"messages": new_messages}` plus `{"goal_id", "phase": "planning"}` when the goal was saved.

Note on the SQL tool: `tri_analyze.agent.sql_tool.make_query_tool` cannot be imported (dependency direction). Move it to tri-core in this task: `mv packages/tri-analyze/src/tri_analyze/agent/sql_tool.py packages/tri-core/src/tri_core/db/sql_tool.py`, move its test `packages/tri-analyze/tests/test_sql_tool.py` to `packages/tri-core/tests/test_sql_tool.py`, and rewrite the two imports (`tri_analyze/cli.py`, the test) to `from tri_core.db.sql_tool import make_query_tool`. `sql_tool.py` imports only psycopg and `langchain_core.tools`, both tri-core dependencies already. Its `SCHEMA_DOC` gains a paragraph for the four planning tables (`training_goals`, `training_plans`, `plan_weeks`, `plan_changes`) with one example (`select week_start, phase, target_tss from plan_weeks order by 1`).

- [x] **Step 1: Move the SQL tool into tri-core**

```bash
mv packages/tri-analyze/src/tri_analyze/agent/sql_tool.py packages/tri-core/src/tri_core/db/sql_tool.py
mv packages/tri-analyze/tests/test_sql_tool.py packages/tri-core/tests/test_sql_tool.py
grep -rl "tri_analyze.agent.sql_tool" packages | xargs sed -i '' 's/tri_analyze\.agent\.sql_tool/tri_core.db.sql_tool/g'
uv run pytest packages/tri-core/tests/test_sql_tool.py packages/tri-analyze -q
```
Expected: all pass. Append to `SCHEMA_DOC` in `packages/tri-core/src/tri_core/db/sql_tool.py`, before the `Examples:` line:

```
training_goals (planning agent): id, goal_type, event_name, event_date, duration_weeks, priority,
  weekly_hours_min, weekly_hours_max, available_days jsonb, constraints jsonb, status.
training_plans: id, goal_id, source ('generated'|'tp_plan'), start_date, end_date, targets jsonb, status.
plan_weeks: plan_id, week_start (Monday), phase, target_tss, target_hours, designed jsonb, written_to_tp.
plan_changes: plan_id, thread_id, operation, tp_workout_id, workout_date, payload jsonb, result jsonb,
  reason, applied_at  (audit of every calendar write; a workout is agent-authored iff its id is here).
```

- [x] **Step 2: Write the failing tests**

`packages/tri-planning/tests/test_goal_tools.py`:
```python
import contextlib
import json
from datetime import timedelta

import pytest

from tri_planning import repo
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp
from tri_planning.tools.goal import make_goal_tools

pytestmark = pytest.mark.db


def tools(nocommit, tp=None):
    named = {t.name: t for t in make_goal_tools(lambda: contextlib.nullcontext(nocommit), tp, lambda: MONDAY)}
    return named["set_training_goal"], named["list_tp_training_plans"]


def test_set_goal_inserts_and_reports_weeks(nocommit):
    set_goal, _ = tools(nocommit)
    out = json.loads(set_goal.invoke(GOAL_ARGS))
    assert out["weeks"] == 14 and out["compressed"] is False and out["warning"] is None
    stored = repo.get_goal(nocommit, out["goal_id"])
    assert stored is not None and stored.goal.event_name == "City Tri"


def test_set_goal_warns_when_compressed(nocommit):
    set_goal, _ = tools(nocommit)
    args = {**GOAL_ARGS, "event_date": (MONDAY + timedelta(weeks=9, days=6)).isoformat()}  # 10 < 12
    out = json.loads(set_goal.invoke(args))
    assert out["compressed"] is True and "12" in out["warning"]


def test_set_goal_refuses_impossible_goal(nocommit):
    set_goal, _ = tools(nocommit)
    args = {**GOAL_ARGS, "event_date": (MONDAY + timedelta(weeks=2)).isoformat()}
    out = json.loads(set_goal.invoke(args))
    assert "error" in out and repo.get_active_goal(nocommit) is None


def test_set_goal_reports_validation_errors_as_text(nocommit):
    set_goal, _ = tools(nocommit)
    out = json.loads(set_goal.invoke({**GOAL_ARGS, "weekly_hours_min": 20}))
    assert "error" in out and "weekly_hours_min" in out["error"]


async def test_list_plans_uses_server_or_reports_unavailable(nocommit):
    _, list_plans = tools(nocommit, FakeTp())
    assert "12 week olympic" in await list_plans.ainvoke({})
    _, list_plans = tools(nocommit, None)
    assert "unavailable" in await list_plans.ainvoke({})
```

`packages/tri-planning/tests/test_intake_node.py`:
```python
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.nodes.intake import goal_id_from_messages, make_intake_node
from tri_planning.testing import GOAL_ARGS

pytestmark = pytest.mark.db

CFG = {"configurable": {"thread_id": "t"}}


def test_goal_id_from_messages():
    msgs = [ToolMessage(content=json.dumps({"goal_id": 7, "weeks": 14}), name="set_training_goal", tool_call_id="c1")]
    assert goal_id_from_messages(msgs) == 7
    assert goal_id_from_messages([ToolMessage(content=json.dumps({"error": "x"}), name="set_training_goal", tool_call_id="c2")]) is None
    assert goal_id_from_messages([AIMessage(content="hi")]) is None


async def test_intake_turn_without_goal_returns_only_messages(make_deps):
    model = ScriptedChatModel(script=[AIMessage(content="What race are you targeting?")])
    node = make_intake_node(make_deps(model))
    out = await node({"messages": [HumanMessage("I want to plan my season")]}, CFG)
    assert [type(m).__name__ for m in out["messages"]] == ["AIMessage"]
    assert "goal_id" not in out


async def test_intake_sets_goal_and_phase(make_deps):
    model = ScriptedChatModel(script=[tool_call("set_training_goal", GOAL_ARGS), AIMessage(content="Goal saved.")])
    node = make_intake_node(make_deps(model))
    out = await node({"messages": [HumanMessage("Olympic on Dec 13, 4-12 h, any day")]}, CFG)
    assert out["phase"] == "planning" and isinstance(out["goal_id"], int)
    assert [type(m).__name__ for m in out["messages"]] == ["AIMessage", "ToolMessage", "AIMessage"]
```

- [x] **Step 3: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_goal_tools.py packages/tri-planning/tests/test_intake_node.py -q`
Expected: `ImportError`.

- [x] **Step 4: Write `tools/goal.py`**

`packages/tri-planning/src/tri_planning/tools/goal.py`:
```python
"""Intake tools: commit a TrainingGoal; list the athlete's bought TrainingPeaks plans."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import ValidationError

from tri_core.sync import ToolCaller
from tri_planning import repo
from tri_planning.graph.deps import ConnectFactory
from tri_planning.planning import periodization as P
from tri_planning.planning.models import TrainingGoal
from tri_planning.planning.targets import allocate_phases, count_weeks, next_monday

SET_GOAL_DESCRIPTION = """\
Commit the athlete's training goal once every field is established and confirmed. Fields:
goal_type (sprint | olympic | half_ironman | ironman | maintenance | build | recovery);
event_name and event_date (YYYY-MM-DD) for race goals; duration_weeks for non-race goals;
priority (A | B | C); weekly_hours_min and weekly_hours_max; available_days, a mapping of
mon..sun to a list of sports (swim, bike, run, brick, strength) or the string "any" (a missing
day or an empty list means unavailable); constraints, a list of short strings; tp_plan_id if the
athlete wants a bought TrainingPeaks plan activated instead of a generated one; create_tp_event
true to add the race to the TrainingPeaks calendar. Returns JSON with goal_id and the number of
weeks, or an error explaining what to fix. Do not call it more than once per goal."""


def make_goal_tools(connect: ConnectFactory, tp: ToolCaller | None, today: Callable[[], date]) -> list[BaseTool]:
    def set_training_goal(**kwargs: Any) -> str:
        try:
            goal = TrainingGoal(**kwargs)
        except ValidationError as exc:
            return json.dumps({"error": str(exc)})
        start = next_monday(today())
        try:
            weeks = count_weeks(goal, start)
            _, compressed = allocate_phases(goal.goal_type, weeks)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        minimum = P.PHASE_TABLE[goal.goal_type].minimum_weeks
        warning = (
            f"only {weeks} weeks until the event; {goal.goal_type} normally needs {minimum}. "
            "Base is dropped and build shortened; the plan is flagged compressed."
            if compressed
            else None
        )
        with connect() as conn:
            goal_id = repo.insert_goal(conn, goal)
            conn.commit()
        return json.dumps({"goal_id": goal_id, "weeks": weeks, "compressed": compressed, "warning": warning})

    async def list_tp_training_plans() -> str:
        """List the bought TrainingPeaks training plans in the athlete's library (id and name)."""
        if tp is None:
            return json.dumps({"error": "TrainingPeaks server unavailable this session"})
        return json.dumps(await tp.call_json("tp_list_training_plans"), default=str)

    set_goal_tool = StructuredTool.from_function(
        func=set_training_goal,
        name="set_training_goal",
        description=SET_GOAL_DESCRIPTION,
        args_schema=TrainingGoal,
    )
    list_tool = StructuredTool.from_function(
        coroutine=list_tp_training_plans, name="list_tp_training_plans",
        description=list_tp_training_plans.__doc__ or "",
    )
    return [set_goal_tool, list_tool]
```

- [x] **Step 5: Write `prompts/intake.py` and `graph/nodes/intake.py`**

`prompts/intake.py`:
```python
"""System prompt for the intake sub-agent."""

from datetime import date

from tri_planning.planning import periodization as P


def render_intake_prompt(today: date) -> str:
    table = "\n".join(
        f"- {g}: minimum {s.minimum_weeks} weeks" for g, s in P.PHASE_TABLE.items()
    )
    return f"""\
You are a triathlon coach establishing one athlete's next training goal. Today is {today.isoformat()}.
Plans start on the next Monday.

Establish, in conversation, every one of these before committing:
1. Goal type: one of sprint, olympic, half_ironman, ironman (a race) or maintenance, build,
   recovery (no race; ask how many weeks).
2. For a race: event name, date, and priority (A, B or C). Ask whether to add the race to the
   TrainingPeaks calendar (create_tp_event).
3. Weekly hours the athlete can train, as a min and max.
4. Which days are available and for which sports (swim, bike, run, brick, strength), or "any".
5. Constraints in the athlete's words (pool hours, travel, injuries, a long ride only on Saturdays).
6. Whether to activate a bought TrainingPeaks plan instead of generating one. Use
   list_tp_training_plans to show what is in the library when asked.

Use query_training_db to look at recent training load (daily_metrics.tss_day, ctl) and volume
(workouts) so your questions and suggestions are grounded; mention the athlete's current CTL.

Minimum weeks per goal type (weeks from next Monday to race week inclusive):
{table}
If the weeks available are below the minimum, say so before committing and explain that base is
dropped and build shortened. If the race is too close for even peak, taper and race week, say
the goal is not feasible and suggest a maintenance or build goal.

When everything is established, summarize it in one short block, ask for confirmation, and only
after the athlete confirms call set_training_goal exactly once. If it returns an error, fix the
inputs and call again. After it succeeds reply with exactly: Goal saved. Building the week targets.
Be brief. One or two questions per turn."""
```

`graph/nodes/intake.py`:
```python
"""Intake node: a create_agent sub-agent that ends the phase by calling set_training_goal."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.llm import make_subagent
from tri_planning.graph.state import PlanningState
from tri_planning.prompts.intake import render_intake_prompt
from tri_planning.tools.goal import make_goal_tools


def goal_id_from_messages(messages: Sequence[AnyMessage]) -> int | None:
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "set_training_goal":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return None
            gid = data.get("goal_id") if isinstance(data, dict) else None
            return int(gid) if gid is not None else None
    return None


def make_intake_node(deps: GraphDeps) -> Any:
    tools = [make_query_tool(deps.db_url), *make_goal_tools(deps.connect, deps.tp, deps.today)]
    agent = make_subagent(deps.model, tools, render_intake_prompt(deps.today()))

    async def intake(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before):]
        update: dict[str, Any] = {"messages": new}
        goal_id = goal_id_from_messages(new)
        if goal_id is not None:
            update["goal_id"] = goal_id
            update["phase"] = "planning"
        return update

    return intake
```

- [x] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_goal_tools.py packages/tri-planning/tests/test_intake_node.py -q`
Expected: 8 passed. If `StructuredTool.from_function` rejects `**kwargs` with `args_schema`, replace `set_training_goal(**kwargs)` with an explicit signature listing the eleven `TrainingGoal` fields with the same defaults, and keep `args_schema=TrainingGoal`.

- [x] **Step 7: Full suite, lint, type-check, commit (Brian)**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): goal tools and intake node; sql tool moves to tri-core"
```

---

### Task 4: Targets node

**Files:**
- Create: `graph/nodes/targets.py`
- Test: `tests/test_targets_node.py`

**Interfaces:**
- Consumes: `repo.get_goal/insert_plan/fitness_snapshot/insert_change/mark_weeks_written`, `targets.build/next_monday/week_monday/infer_phases`, `tp_calls.event_change`, `GraphDeps`.
- Produces: `nodes.targets.make_targets_node(deps) -> async node`. Return values:
  - generated goal, no plan yet: `{"plan_id": int, "messages": [AIMessage(summary)]}`.
  - generated goal, `plan_id` already set: `{}` (fall through to design).
  - bought plan, not yet applied: `{"pending_changes": [event?, apply_plan], "pending_summary": str, "changes_from": "targets"}`.
  - bought plan, `tp_plan_applied` true: `{"plan_id": int, "phase": "active", "tp_plan_applied": False, "messages": [AIMessage(summary)]}` after reading the calendar with `tp_get_workouts` and recording ownership rows (`operation = "apply_plan"`).
  - Also `nodes.targets.weekly_targets_from_workouts(workouts: list[dict], start: date) -> list[WeekTarget]` (pure; `tss_planned` summed per Monday; `duration_planned` is hours; phases from `infer_phases`).

- [x] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_targets_node.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.nodes.targets import make_targets_node, weekly_targets_from_workouts
from tri_planning.planning.models import TrainingGoal
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def stored_goal(conn, **over):
    return repo.insert_goal(conn, TrainingGoal(**{**GOAL_ARGS, **over}))


async def test_generated_goal_builds_plan_and_summarizes(nocommit, make_deps):
    gid = stored_goal(nocommit)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[])))
    out = await node({"goal_id": gid, "phase": "planning"}, CFG)
    plan = repo.get_plan(nocommit, out["plan_id"])
    assert plan.source == "generated" and len(plan.targets) == 14 and plan.start_date == MONDAY
    assert isinstance(out["messages"][0], AIMessage) and "14 weeks" in out["messages"][0].content
    assert len(repo.list_weeks(nocommit, plan.id)) == 14


async def test_existing_plan_is_not_rebuilt(nocommit, make_deps):
    gid = stored_goal(nocommit)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[])))
    first = await node({"goal_id": gid, "phase": "planning"}, CFG)
    again = await node({"goal_id": gid, "phase": "planning", "plan_id": first["plan_id"]}, CFG)
    assert again == {}


async def test_bought_plan_proposes_apply_plan(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1", create_tp_event=True)
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    out = await node({"goal_id": gid, "phase": "planning"}, CFG)
    ops = [c.op for c in out["pending_changes"]]
    assert ops == ["create_event", "apply_plan"] and out["changes_from"] == "targets"
    assert out["pending_changes"][1].payload == {"plan_id": "p1", "start_date": MONDAY.isoformat()}


async def test_bought_plan_after_apply_derives_targets_and_ownership(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    workouts = [
        {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0},
        {"id": "w2", "date": (MONDAY + timedelta(days=3)).isoformat(), "tss_planned": 80, "duration_planned": 1.5},
        {"id": "w3", "date": (MONDAY + timedelta(weeks=1)).isoformat(), "tss_planned": 100, "duration_planned": 2.0},
        {"id": "w4", "date": (MONDAY + timedelta(weeks=2)).isoformat(), "tss_planned": 40, "duration_planned": 1.0},
    ]
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 4}})
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node({"goal_id": gid, "phase": "planning", "tp_plan_applied": True}, CFG)
    assert out["phase"] == "active" and out["tp_plan_applied"] is False
    plan = repo.get_plan(nocommit, out["plan_id"])
    assert plan.source == "tp_plan" and [t.target_tss for t in plan.targets] == [140, 100, 40]
    assert [t.phase for t in plan.targets] == ["peak", "taper", "race"]
    assert all(w.written_to_tp for w in repo.list_weeks(nocommit, plan.id))
    assert repo.owned_workout_ids(nocommit, plan.id) == {"w1", "w2", "w3", "w4"}
    assert tp.calls[0][0] == "tp_get_workouts"


def test_weekly_targets_from_workouts_groups_by_monday():
    ws = [
        {"id": "a", "date": (MONDAY + timedelta(days=2)).isoformat(), "tss_planned": 50, "duration_planned": 1.0},
        {"id": "b", "date": (MONDAY + timedelta(days=6)).isoformat(), "tss_planned": 50, "duration_planned": None},
        {"id": "c", "date": (MONDAY + timedelta(days=8)).isoformat(), "tss_planned": None, "duration_planned": 2.0},
    ]
    targets = weekly_targets_from_workouts(ws, MONDAY)
    assert [(t.week_start, t.target_tss, t.target_hours) for t in targets] == [
        (MONDAY, 100, 1.0), (MONDAY + timedelta(weeks=1), 0, 2.0),
    ]
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_targets_node.py -q`
Expected: `ImportError`.

- [x] **Step 3: Write `graph/nodes/targets.py`**

```python
"""Targets node: goal + fitness -> week targets in the database. No model call."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning import periodization as P
from tri_planning.planning.models import CalendarChange, StoredGoal, WeekTarget
from tri_planning.planning.targets import build, infer_phases, next_monday, week_monday
from tri_planning.planning.tp_calls import event_change


def weekly_targets_from_workouts(workouts: list[dict[str, Any]], start: date) -> list[WeekTarget]:
    tss: dict[date, float] = defaultdict(float)
    hours: dict[date, float] = defaultdict(float)
    for w in workouts:
        day = date.fromisoformat(str(w["date"])[:10])
        if day < start:
            continue
        monday = week_monday(day)
        tss[monday] += float(w.get("tss_planned") or 0)
        hours[monday] += float(w.get("duration_planned") or 0)  # TP totalTimePlanned is hours
    mondays = sorted(tss)
    phases = infer_phases([tss[m] for m in mondays])
    return [
        WeekTarget(
            week_start=m, phase=ph, target_tss=round(tss[m]), target_hours=round(hours[m], 1),
            sport_hint=P.SPORT_HINTS[ph],
        )
        for m, ph in zip(mondays, phases, strict=True)
    ]


def _summary(targets: list[WeekTarget], source: str) -> str:
    counts: dict[str, int] = defaultdict(int)
    for t in targets:
        counts[t.phase] += 1
    phases = ", ".join(f"{n} {p}" for p, n in counts.items())
    first, last = targets[0], targets[-1]
    flags = sorted({f for t in targets for f in t.flags})
    lines = [
        f"Targets ({source}): {len(targets)} weeks from {first.week_start} to "
        f"{last.week_start + timedelta(days=6)}; phases: {phases}.",
        f"Week 1 target {first.target_tss:.0f} TSS / {first.target_hours:.1f} h; peak "
        f"{max(t.target_tss for t in targets):.0f} TSS.",
    ]
    if flags:
        lines.append(f"Flags: {', '.join(flags)}.")
    return "\n".join(lines)


def make_targets_node(deps: GraphDeps) -> Any:
    async def _adopt_tp_plan(stored: StoredGoal, thread_id: str) -> dict[str, Any]:
        assert deps.tp is not None and stored.goal.event_date is not None
        start = next_monday(deps.today())
        end = stored.goal.event_date + timedelta(days=7)
        result = await deps.tp.call_json(
            "tp_get_workouts",
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "workout_filter": "planned"},
        )
        workouts = list((result or {}).get("workouts", []))
        targets = weekly_targets_from_workouts(workouts, start)
        if not targets:
            return {"last_error": "no planned workouts found after applying the TrainingPeaks plan",
                    "tp_plan_applied": False}
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "tp_plan", stored.goal.tp_plan_id, targets)
            for w in workouts:
                wid = str(w["id"])
                change = CalendarChange(op="apply_plan", tp_workout_id=wid,
                                        workout_date=date.fromisoformat(str(w["date"])[:10]),
                                        reason=f"applied TrainingPeaks plan {stored.goal.tp_plan_id}")
                repo.insert_change(conn, plan_id, thread_id, change, tp_workout_id=wid, result=None)
            repo.mark_weeks_written(conn, plan_id, [t.week_start for t in targets])
            conn.commit()
        return {"plan_id": plan_id, "phase": "active", "tp_plan_applied": False,
                "pending_changes": [], "pending_summary": None,
                "messages": [AIMessage(_summary(targets, "TrainingPeaks plan"))]}

    async def targets_node(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        goal_id = state.get("goal_id")
        assert goal_id is not None, "targets node needs goal_id"
        thread_id = str(config["configurable"]["thread_id"])
        with deps.connect() as conn:
            stored = repo.get_goal(conn, goal_id)
            assert stored is not None
            fitness = repo.fitness_snapshot(conn, deps.today())
        goal = stored.goal

        if goal.tp_plan_id:
            if state.get("tp_plan_applied"):
                return await _adopt_tp_plan(stored, thread_id)
            start = next_monday(deps.today())
            changes: list[CalendarChange] = []
            if goal.create_tp_event and stored.tp_event_id is None:
                changes.append(event_change(goal))
            changes.append(CalendarChange(
                op="apply_plan",
                payload={"plan_id": goal.tp_plan_id, "start_date": start.isoformat()},
                reason=f"activate TrainingPeaks plan {goal.tp_plan_id} from {start}",
            ))
            return {"pending_changes": changes, "changes_from": "targets",
                    "pending_summary": f"Apply bought plan {goal.tp_plan_id} starting {start}."}

        if state.get("plan_id") is not None:
            return {}
        targets = build(goal, fitness, next_monday(deps.today()))
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "generated", None, targets)
            conn.commit()
        return {"plan_id": plan_id, "messages": [AIMessage(_summary(targets, "generated"))]}

    return targets_node
```

- [x] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_targets_node.py -q`
Expected: 5 passed. The summary test checks the literal `14 weeks`, which `_summary` prints as `{len(targets)} weeks`.

- [x] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): targets node (generated and bought plans)"
```

---

### Task 5: Design prompt and design node

**What this teaches:** `with_structured_output` (the model returns a validated `PlannedWeek`, not prose), a deterministic validator in the loop with one retry, and LangSmith tags on individual calls.

**Files:**
- Create: `prompts/design.py`, `graph/nodes/design.py`
- Test: `tests/test_design_node.py`

**Interfaces:**
- Consumes: `repo.get_goal/get_plan/list_weeks/athlete_thresholds/set_week_designed`, `validate.week`, `tp_calls.event_change`, `PlannedWeek`, `GraphDeps`.
- Produces:
  - `prompts.design.DESIGN_SYSTEM: str`.
  - `prompts.design.render_design_prompt(goal, target, thresholds, previous: PlannedWeek | None, athlete_note: str | None, violations: list[str] | None, previous_attempt: PlannedWeek | None) -> str`.
  - `nodes.design.window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]` (weeks with `week_monday(today) <= week_start <= week_monday(today) + (horizon - 1) weeks` and `not written_to_tp`).
  - `nodes.design.make_design_node(deps) -> async node` returning `{"pending_changes", "pending_summary", "changes_from": "design", "review_decision": None}`.

- [x] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_design_node.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.nodes.design import make_design_node, window_weeks
from tri_planning.planning.models import FitnessSnapshot, PlannedWeek, ReviewDecision, TrainingGoal
from tri_planning.planning.targets import build
from tri_planning.prompts.design import render_design_prompt
from tri_planning.testing import GOAL_ARGS, MONDAY, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid, targets


def structured(week: dict) -> AIMessage:
    return tool_call("PlannedWeek", week)


async def test_designs_window_weeks_and_proposes_creates(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(script=[
        structured(week_json(MONDAY, targets[0].target_tss)),
        structured(week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)),
    ])
    node = make_design_node(make_deps(model, horizon=2))
    out = await node({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)
    assert model.calls == 2
    assert len(out["pending_changes"]) == 6 and {c.op for c in out["pending_changes"]} == {"create"}
    assert out["changes_from"] == "design" and str(MONDAY) in out["pending_summary"]
    weeks = repo.list_weeks(nocommit, pid)
    assert weeks[0].designed is not None and weeks[1].designed is not None and weeks[2].designed is None


async def test_retries_once_on_violation_and_reports_if_still_bad(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    bad = week_json(MONDAY, targets[0].target_tss, hard_on_consecutive_days=True)
    good = week_json(MONDAY, targets[0].target_tss)
    model = ScriptedChatModel(script=[structured(bad), structured(good)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" not in out["pending_summary"]

    model = ScriptedChatModel(script=[structured(bad), structured(bad)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" in out["pending_summary"] and "consecutive" in out["pending_summary"]


async def node_out(deps, gid, pid):
    return await make_design_node(deps)({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)


async def test_reject_note_reaches_prompt_and_unwritten_weeks_are_redesigned(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    captured = []

    class Spy(ScriptedChatModel):
        def _generate(self, messages, *a, **k):
            captured.append(messages[-1].content)
            return super()._generate(messages, *a, **k)

    model = Spy(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    node = make_design_node(make_deps(model))
    state = {
        "goal_id": gid, "plan_id": pid,
        "messages": [HumanMessage("Plan review rejected: no running on Wednesdays")],
        "review_decision": ReviewDecision(action="reject", note="no running on Wednesdays"),
    }
    await node(state, CFG)
    assert "no running on Wednesdays" in captured[-1]


async def test_event_change_first_when_requested(nocommit, make_deps):
    gid, pid, targets = seed(nocommit, create_tp_event=True)
    model = ScriptedChatModel(script=[structured(week_json(MONDAY, targets[0].target_tss))])
    out = await make_design_node(make_deps(model))({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)
    assert out["pending_changes"][0].op == "create_event"


def test_window_weeks_respects_horizon_and_written_flag():
    from tri_planning.planning.models import PlanWeekRow

    rows = [
        PlanWeekRow(plan_id=1, week_start=MONDAY + timedelta(weeks=i), phase="base", target_tss=1,
                    target_hours=1, designed=None, written_to_tp=(i == 0))
        for i in range(5)
    ]
    picked = window_weeks(rows, MONDAY + timedelta(days=2), 3)
    assert [w.week_start for w in picked] == [MONDAY + timedelta(weeks=1), MONDAY + timedelta(weeks=2)]


def test_prompt_mentions_target_availability_and_rules():
    goal = TrainingGoal(**GOAL_ARGS)
    targets = build(goal, FitnessSnapshot(ctl=45), MONDAY)
    text = render_design_prompt(goal, targets[0], {"ftp_watts": 250}, None, None, None, None)
    assert f"{targets[0].target_tss:.0f}" in text and "pool closed Fridays" in text
    assert "250" in text and "consecutive" in text and "percentOfFtp" in text
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py -q`
Expected: `ImportError`.

- [x] **Step 3: Write `prompts/design.py`**

```python
"""Design prompt: the model plans one week's sessions inside Python-set bounds."""

from __future__ import annotations

import json
from typing import Any

from tri_planning.planning.models import WEEKDAYS, PlannedWeek, TrainingGoal, WeekTarget

DESIGN_SYSTEM = """\
You are a triathlon coach writing one week of sessions for one self-coached athlete. You return a
PlannedWeek: week_start, coach_note (two sentences on the week's intent), and sessions. Each
session has date (YYYY-MM-DD inside the week), sport (swim | bike | run | brick | strength | rest),
title (short, specific), description (what to do, in the athlete's language, with targets in the
athlete's zones), duration_minutes, tss_planned, intensity (recovery | endurance | tempo |
threshold | vo2 | race) and optionally structure.

structure is TrainingPeaks' simplified format: {"primaryIntensityMetric": "percentOfFtp" for
bike, "percentOfThresholdPace" for run and swim, "percentOfThresholdHr" if no pace or power
threshold exists, "steps": [ {"name", "duration_seconds", "intensity_min", "intensity_max",
"intensityClass": "warmUp" | "active" | "rest" | "coolDown"} or {"type": "repetition", "reps",
"steps": [...]} ]}. Step durations must sum to duration_minutes within 5 minutes. Only add
structure to interval sessions; leave it out for steady endurance and swims described in text.

Hard rules (a validator rejects the week otherwise):
- The sessions' tss_planned must sum to within 10 % of the target.
- No session on an unavailable day; only the day's allowed sports. Brick needs bike and run.
- Sessions with intensity threshold, vo2 or race are never on consecutive days.
- Total duration must not exceed the weekly hours max.
Do not include rest days as sessions. Estimate TSS from duration and intensity factor:
TSS = hours * IF^2 * 100 with IF about 0.65 recovery, 0.70 endurance, 0.80 tempo, 0.90 threshold,
1.0 vo2/race."""


def _availability_block(goal: TrainingGoal) -> str:
    rows = []
    for d in WEEKDAYS:
        allowed = goal.available_days.get(d, [])
        rows.append(f"  {d}: {'any sport' if allowed == 'any' else (', '.join(allowed) or 'unavailable')}")
    return "\n".join(rows)


def _previous_block(prev: PlannedWeek | None) -> str:
    if prev is None:
        return "Previous week: none (first designed week)."
    lines = [f"Previous week ({prev.week_start}, {prev.total_tss:.0f} TSS):"]
    for s in prev.sessions:
        lines.append(f"  {s.date} {s.sport} {s.intensity} {s.duration_minutes} min: {s.title}")
    return "\n".join(lines)


def render_design_prompt(
    goal: TrainingGoal,
    target: WeekTarget,
    thresholds: dict[str, Any] | None,
    previous: PlannedWeek | None,
    athlete_note: str | None,
    violations: list[str] | None,
    previous_attempt: PlannedWeek | None,
) -> str:
    parts = [
        f"Design the week starting {target.week_start} (Monday). Phase: {target.phase}"
        f"{' (recovery week)' if target.is_recovery else ''}. Target {target.target_tss:.0f} TSS in "
        f"about {target.target_hours:.1f} hours; the athlete's range is {goal.weekly_hours_min:g} to "
        f"{goal.weekly_hours_max:g} hours.",
        f"Phase guidance: {target.sport_hint}",
        f"Goal: {goal.goal_type}" + (f", {goal.event_name} on {goal.event_date}" if goal.event_date else ""),
        "Availability:\n" + _availability_block(goal),
        "Constraints: " + ("; ".join(goal.constraints) if goal.constraints else "none"),
        "Athlete thresholds and zones: " + json.dumps(thresholds or {}, default=str),
        _previous_block(previous),
    ]
    if athlete_note:
        parts.append(f"The athlete rejected the last proposal with this note; honor it: {athlete_note}")
    if violations and previous_attempt is not None:
        parts.append(
            "Your previous attempt was rejected by the validator:\n- " + "\n- ".join(violations)
            + "\nPrevious attempt: " + previous_attempt.model_dump_json()
            + "\nFix every violation and return the whole week again."
        )
    return "\n\n".join(parts)
```

- [x] **Step 4: Write `graph/nodes/design.py`**

```python
"""Design node: one structured-output call per window week, validated, retried once."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning import validate
from tri_planning.planning.models import CalendarChange, PlannedWeek, PlanWeekRow
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import event_change
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt


def window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]:
    first = week_monday(today)
    last = first + timedelta(weeks=horizon - 1)
    return [w for w in weeks if first <= w.week_start <= last and not w.written_to_tp]


def make_design_node(deps: GraphDeps) -> Any:
    structured = deps.model.with_structured_output(PlannedWeek)

    async def design_one(prompt: str, config: RunnableConfig) -> PlannedWeek:
        out = await structured.ainvoke([SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=config)
        assert isinstance(out, PlannedWeek)
        return out

    async def design(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        goal_id, plan_id = state.get("goal_id"), state.get("plan_id")
        assert goal_id is not None and plan_id is not None
        with deps.connect() as conn:
            stored = repo.get_goal(conn, goal_id)
            plan = repo.get_plan(conn, plan_id)
            weeks = repo.list_weeks(conn, plan_id)
            thresholds = repo.athlete_thresholds(conn)
        assert stored is not None and plan is not None
        goal = stored.goal
        decision = state.get("review_decision")
        note = decision.note if decision is not None and decision.action == "reject" else None

        todo = window_weeks(weeks, deps.today(), deps.horizon_weeks)
        previous = next(
            (w.designed for w in reversed(weeks) if w.designed and todo and w.week_start < todo[0].week_start),
            None,
        )
        changes: list[CalendarChange] = []
        notes: list[str] = []
        for row in todo:
            target = next(t for t in plan.targets if t.week_start == row.week_start)
            cfg = merge_configs(config, {"tags": [f"week_start:{row.week_start}", f"phase:{target.phase}"]})
            week = await design_one(
                render_design_prompt(goal, target, thresholds, previous, note, None, None), cfg
            )
            violations = validate.week(week, target, goal)
            if violations:
                week = await design_one(
                    render_design_prompt(goal, target, thresholds, previous, note, violations, week), cfg
                )
                violations = validate.week(week, target, goal)
            with deps.connect() as conn:
                repo.set_week_designed(conn, plan_id, row.week_start, week)
                conn.commit()
            for s in week.sessions:
                if s.sport == "rest":
                    continue
                changes.append(CalendarChange(
                    op="create", workout_date=s.date, workout=s,
                    reason=f"{target.phase} week of {row.week_start}: {week.coach_note}",
                ))
            line = (f"{row.week_start} ({target.phase}, target {target.target_tss:.0f} TSS): "
                    f"{len(week.sessions)} sessions, {week.total_tss:.0f} TSS, {week.total_hours:.1f} h")
            if violations:
                line += "\n  VIOLATIONS: " + "; ".join(violations)
            notes.append(line)
            previous = week

        if goal.create_tp_event and stored.tp_event_id is None and goal.event_date is not None:
            changes.insert(0, event_change(goal))
        summary = "\n".join(notes) if notes else "No weeks to design inside the horizon."
        return {"pending_changes": changes, "pending_summary": summary,
                "changes_from": "design", "review_decision": None}

    return design
```

- [x] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py -q`
Expected: 6 passed. `ScriptedChatModel.with_structured_output` is `BaseChatModel`'s default: it binds the `PlannedWeek` schema as a tool and parses the scripted tool call named `PlannedWeek`. If the parser complains about the name, name the scripted tool call exactly `PlannedWeek`.

- [x] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): design prompt and node with validator retry"
```

---

### Task 6: Review and apply nodes

**What this teaches:** `interrupt()` as the pause point (the node re-runs from the top on resume, so everything before the interrupt must be side-effect free), and an apply step whose every external call is recorded before the next one starts.

**Files:**
- Create: `graph/nodes/review.py`, `graph/nodes/apply.py`
- Test: `tests/test_apply_node.py` (review is exercised end to end in Task 7)

**Interfaces:**
- Consumes: `repo.owned_workout_ids/insert_change/set_goal_event/mark_weeks_written`, `tp_calls.to_tp_call/result_workout_id`, `McpToolError`, `GraphDeps`.
- Produces:
  - `nodes.review.review_node(state) -> dict`: with empty `pending_changes` returns `{"review_decision": None, "messages": [AIMessage("No calendar changes to review.")]}`; otherwise calls `interrupt({"summary": str, "changes": [json dicts]})` and returns `{"review_decision": ReviewDecision}`, plus `{"messages": [HumanMessage("Plan review rejected: <note>")]}` on reject, plus `{"pending_changes": decision.changes}` on edit.
  - `nodes.apply.make_apply_node(deps) -> async node` returning `{"pending_changes": remaining, "pending_summary", "last_error", "review_decision": None, "messages": [AIMessage(report)], "tp_plan_applied": bool}` and `"phase": "active"` when everything applied and no `apply_plan` was among them.

- [x] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_apply_node.py`:
```python
from datetime import timedelta

import pytest

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.nodes.apply import make_apply_node
from tri_planning.planning.models import (
    CalendarChange, FitnessSnapshot, PlannedSession, TrainingGoal, WeekTarget,
)
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = [WeekTarget(week_start=MONDAY + timedelta(weeks=i), phase="base", target_tss=300, target_hours=6) for i in range(2)]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid


def create(day=0, title="Ride"):
    s = PlannedSession(date=MONDAY + timedelta(days=day), sport="bike", title=title, description="",
                       duration_minutes=60, tss_planned=50, intensity="endurance")
    return CalendarChange(op="create", workout_date=s.date, workout=s, reason="plan")


def state(gid, pid, changes):
    return {"goal_id": gid, "plan_id": pid, "pending_changes": changes, "pending_summary": "s", "phase": "planning"}


async def test_applies_all_records_rows_marks_weeks_and_activates(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(7, "Ride 2")]), CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None and out["phase"] == "active"
    assert [c[0] for c in tp.calls] == ["tp_create_workout", "tp_create_workout"]
    assert len(repo.owned_workout_ids(nocommit, pid)) == 2
    assert [w.written_to_tp for w in repo.list_weeks(nocommit, pid)] == [True, True]
    assert "applied 2" in out["messages"][0].content


async def test_mid_batch_failure_keeps_remainder_pending(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp(fail_on_call=2)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(1, "B"), create(2, "C")]), CFG)
    assert [c.workout.title for c in out["pending_changes"]] == ["B", "C"]
    assert "boom" in out["last_error"] and "phase" not in out
    assert len(repo.owned_workout_ids(nocommit, pid)) == 1
    rows = nocommit.execute("select count(*) as n from plan_changes where plan_id = %s", (pid,)).fetchone()
    assert rows["n"] == 1


async def test_ownership_refusal_unless_athlete_requested(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    foreign = CalendarChange(op="delete", tp_workout_id="coach-1", reason="drop")
    asked = CalendarChange(op="delete", tp_workout_id="coach-2", reason="athlete said delete it", athlete_requested=True)
    out = await node(state(gid, pid, [foreign, asked]), CFG)
    assert [c[1]["workout_id"] for c in tp.calls] == ["coach-2"]
    assert "coach-1" in out["messages"][0].content and "not agent-authored" in out["messages"][0].content
    assert out["pending_changes"] == []


async def test_event_id_is_stored_on_goal(nocommit, make_deps):
    gid, pid = seed(nocommit, create_tp_event=True)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    from tri_planning.planning.tp_calls import event_change
    goal = repo.get_goal(nocommit, gid).goal
    await node(state(gid, pid, [event_change(goal)]), CFG)
    assert repo.get_goal(nocommit, gid).tp_event_id == "77"


async def test_apply_plan_sets_flag_and_does_not_activate(nocommit, make_deps):
    gid, pid = seed(nocommit)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=FakeTp()))
    ch = CalendarChange(op="apply_plan", payload={"plan_id": "p1", "start_date": MONDAY.isoformat()}, reason="r")
    out = await node(state(gid, None, [ch]), CFG)
    assert out["tp_plan_applied"] is True and "phase" not in out


async def test_refuses_without_tp_server(nocommit, make_deps):
    gid, pid = seed(nocommit)
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=None))
    out = await node(state(gid, pid, [create()]), CFG)
    assert len(out["pending_changes"]) == 1 and "unavailable" in out["last_error"]
```

- [x] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py -q`
Expected: `ImportError`.

- [x] **Step 3: Write `graph/nodes/review.py`**

```python
"""Review node: pause the graph until the athlete decides.

LangGraph lesson: `interrupt(value)` raises internally, the run stops with the value exposed to
the caller as `__interrupt__`, and the checkpoint records where we are. On `Command(resume=x)`
the node runs again from the top and `interrupt()` returns x. Nothing before the interrupt may
have side effects.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import ReviewDecision


def review_node(state: PlanningState) -> dict[str, Any]:
    changes = state.get("pending_changes") or []
    if not changes:
        return {"review_decision": None, "messages": [AIMessage("No calendar changes to review.")]}
    raw = interrupt({
        "summary": state.get("pending_summary") or "",
        "changes": [c.model_dump(mode="json") for c in changes],
        "last_error": state.get("last_error"),
    })
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {"review_decision": decision}
    if decision.action == "reject":
        update["messages"] = [HumanMessage(f"Plan review rejected: {decision.note or 'no note given'}")]
    elif decision.action == "edit" and decision.changes is not None:
        update["pending_changes"] = decision.changes
    return update
```

- [x] **Step 4: Write `graph/nodes/apply.py`**

```python
"""Apply node: the only place TrainingPeaks is written. One call per change, recorded as it goes."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.mcp.client import McpToolError
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call

OWNED_OPS = ("update", "move", "delete")


def _label(c: CalendarChange) -> str:
    if c.workout is not None:
        return f"{c.op} {c.workout.date} {c.workout.sport} '{c.workout.title}'"
    return f"{c.op} {c.tp_workout_id or c.workout_date or ''}".strip()


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        plan_id, goal_id = state.get("plan_id"), state.get("goal_id")
        thread_id = str(config["configurable"]["thread_id"])
        if deps.tp is None:
            msg = "TrainingPeaks server unavailable; nothing applied, change set left pending."
            return {"last_error": msg, "review_decision": None, "messages": [AIMessage(msg)]}

        owned: set[str] = set()
        if plan_id is not None:
            with deps.connect() as conn:
                owned = repo.owned_workout_ids(conn, plan_id)

        applied: list[CalendarChange] = []
        skipped: list[str] = []
        remaining = list(changes)
        error: str | None = None
        written: set[Any] = set()
        tp_plan_applied = bool(state.get("tp_plan_applied"))

        for change in changes:
            if change.op in OWNED_OPS and change.tp_workout_id not in owned and not change.athlete_requested:
                skipped.append(f"{_label(change)}: not agent-authored (id {change.tp_workout_id}); dropped")
                remaining.remove(change)
                continue
            try:
                name, args = to_tp_call(change)
                result = await deps.tp.call_json(name, args)
            except (McpToolError, ValueError) as exc:
                error = f"{_label(change)} failed: {exc}"
                break
            wid = result_workout_id(change, result)
            with deps.connect() as conn:
                repo.insert_change(conn, plan_id, thread_id, change, tp_workout_id=wid,
                                   result=result if isinstance(result, dict) else {"result": result})
                if change.op == "create_event" and goal_id is not None and isinstance(result, dict):
                    if result.get("event_id") is not None:
                        repo.set_goal_event(conn, goal_id, str(result["event_id"]))
                conn.commit()
            applied.append(change)
            remaining.remove(change)
            if change.op == "create" and change.workout_date is not None:
                written.add(week_monday(change.workout_date))
            if change.op == "apply_plan":
                tp_plan_applied = True

        if plan_id is not None and written:
            with deps.connect() as conn:
                repo.mark_weeks_written(conn, plan_id, sorted(written))
                conn.commit()

        lines = [f"TrainingPeaks: applied {len(applied)} of {len(changes)} changes."]
        lines += [f"  skipped: {s}" for s in skipped]
        if error:
            lines.append(f"  stopped: {error}")
            lines.append(f"  {len(remaining)} changes still pending; they will be re-proposed next turn.")
        update: dict[str, Any] = {
            "pending_changes": remaining,
            "pending_summary": state.get("pending_summary") if remaining else None,
            "last_error": error,
            "review_decision": None,
            "messages": [AIMessage("\n".join(lines))],
            "tp_plan_applied": tp_plan_applied,
        }
        if error is None and not remaining and not tp_plan_applied:
            update["phase"] = "active"
        return update

    return apply
```

- [x] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py -q`
Expected: 6 passed.

- [x] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): review interrupt and apply node"
```

---

### Task 7: Graph wiring and end-to-end tests

**What this teaches:** conditional edges as plain functions over state, the interrupt/resume cycle from the caller's side, and that the same graph object serves every command.

**Files:**
- Create: `graph/nodes/adjust.py` (placeholder), `graph/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: every node factory above, `PlanningState`, `GraphDeps`.
- Produces:
  - `graph.graph.build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph`.
  - Route functions (module level, testable): `route_start(state) -> "review" | "intake" | "targets" | "adjust"`, `after_intake(state) -> "targets" | END`, `after_targets(state) -> "review" | "design" | END`, `after_review(state) -> "apply" | "design" | "adjust" | END`, `after_apply(state) -> "targets" | END`.
  - `nodes.adjust.adjust_node(state) -> {"messages": [AIMessage("The plan is active. Adjustments and check-in arrive in milestone 4.")]}`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_graph.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.graph import after_review, build_graph, route_start
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "planning"}}
APPROVE = Command(resume={"action": "approve"})


def intake_script():
    return [tool_call("set_training_goal", GOAL_ARGS), AIMessage(content="Goal saved. Building the week targets.")]


def week_call(target_tss, week_start=MONDAY, **k):
    return tool_call("PlannedWeek", week_json(week_start, target_tss, **k))


async def first_target(nocommit):
    return repo.get_active_plan(nocommit, repo.get_active_goal(nocommit).id).targets[0].target_tss


async def test_intake_to_review_pauses_before_any_write(nocommit, make_deps, fake_tp):
    # the design call needs the week-1 target, which only exists after the targets node runs;
    # week_json is tolerant: the validator allows ±10 %, so script a plausible number and
    # correct it below if the test DB's fitness rows change the target.
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["changes"] and all(c["op"] == "create" for c in payload["changes"])
    assert fake_tp.calls == []
    snap = await graph.aget_state(CFG)
    assert snap.next == ("review",)
    assert snap.values["phase"] == "planning" and snap.values["changes_from"] == "design"


async def test_approve_applies_and_activates(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["phase"] == "active" and out["pending_changes"] == []
    assert [c[0] for c in fake_tp.calls] == ["tp_create_workout"] * 3
    assert isinstance(out["messages"][-1], AIMessage) and "applied 3" in out["messages"][-1].content
    # a later turn goes to the adjust placeholder
    out = await graph.ainvoke({"messages": [HumanMessage("how's it going")]}, CFG)
    assert "milestone 4" in out["messages"][-1].content


async def test_reject_routes_back_to_design_with_note(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "too much bike"}), CFG)
    assert "__interrupt__" in out and model.calls == 4
    msgs = (await graph.aget_state(CFG)).values["messages"]
    assert any(isinstance(m, HumanMessage) and "too much bike" in m.content for m in msgs)
    assert fake_tp.calls == []


async def test_edit_replaces_change_set(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    edited = out["__interrupt__"][0].value["changes"][:1]
    out = await graph.ainvoke(Command(resume={"action": "edit", "changes": edited}), CFG)
    assert len(fake_tp.calls) == 1 and out["phase"] == "active"


async def test_mid_batch_failure_then_reproposes_remainder(nocommit, make_deps):
    tp = FakeTp(fail_on_call=2)
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(out["pending_changes"]) == 2 and "boom" in out["last_error"] and out["phase"] == "planning"
    tp.fail_on_call = None
    out = await graph.ainvoke({"messages": [HumanMessage("try again")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 2
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["phase"] == "active" and len(tp.calls) == 4  # 1 ok + 1 failed + 2 retried


async def test_bought_plan_path(nocommit, make_deps):
    workouts = [
        {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0},
        {"id": "w2", "date": (MONDAY + timedelta(weeks=1)).isoformat(), "tss_planned": 40, "duration_planned": 1.0},
    ]
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 2}})
    args = {**GOAL_ARGS, "tp_plan_id": "p1"}
    model = ScriptedChatModel(script=[tool_call("set_training_goal", args), AIMessage(content="Goal saved.")])
    graph = build_graph(make_deps(model, tp=tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("use my bought plan p1")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][0]["op"] == "apply_plan"
    out = await graph.ainvoke(APPROVE, CFG)
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert out["phase"] == "active" and out["plan_id"] is not None
    assert repo.owned_workout_ids(nocommit, out["plan_id"]) == {"w1", "w2"}


def test_route_functions():
    assert route_start({"pending_changes": [1]}) == "review"
    assert route_start({}) == "intake"
    assert route_start({"phase": "planning"}) == "targets"
    assert route_start({"phase": "active"}) == "adjust"
    from tri_planning.planning.models import ReviewDecision
    assert after_review({"review_decision": ReviewDecision(action="approve")}) == "apply"
    assert after_review({"review_decision": ReviewDecision(action="reject"), "changes_from": "design"}) == "design"
    assert after_review({"review_decision": ReviewDecision(action="reject"), "changes_from": "targets"}) == "__end__"
    assert after_review({"review_decision": None}) == "__end__"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_graph.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write `graph/nodes/adjust.py` and `graph/graph.py`**

`graph/nodes/adjust.py`:
```python
"""Placeholder until Plan 4 replaces it with the adjust sub-agent."""

from typing import Any

from langchain_core.messages import AIMessage

from tri_planning.graph.state import PlanningState


def adjust_node(state: PlanningState) -> dict[str, Any]:
    return {"messages": [AIMessage("The plan is active. Adjustments and check-in arrive in milestone 4.")]}
```

`graph/graph.py`:
```python
"""The planning graph. Nodes are closures over GraphDeps; routing is pure functions over state.

  START -> route_start: pending changes -> review; intake | targets | adjust by phase
  intake   -> targets (goal saved) | END
  targets -> review (bought plan) | design (generated) | END (bought plan adopted)
  design   -> review
  review   -> apply (approve/edit) | design or adjust (reject) | END (nothing to review, or
              rejected apply_plan)
  apply    -> targets (after apply_plan) | END
  adjust   -> END (Plan 4: -> review when changes are proposed)
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.adjust import adjust_node
from tri_planning.graph.nodes.apply import make_apply_node
from tri_planning.graph.nodes.design import make_design_node
from tri_planning.graph.nodes.intake import make_intake_node
from tri_planning.graph.nodes.review import review_node
from tri_planning.graph.nodes.targets import make_targets_node
from tri_planning.graph.state import PlanningState


def route_start(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    phase = state.get("phase") or "intake"
    return {"intake": "intake", "planning": "targets", "active": "adjust"}[phase]


def after_intake(state: PlanningState) -> str:
    return "targets" if state.get("phase") == "planning" and state.get("goal_id") else END


def after_targets(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("phase") == "active":
        return END
    return "design"


def after_review(state: PlanningState) -> str:
    decision = state.get("review_decision")
    if decision is None:
        return END
    if decision.action in ("approve", "edit"):
        return "apply"
    origin = state.get("changes_from")
    return origin if origin in ("design", "adjust") else END


def after_apply(state: PlanningState) -> str:
    return "targets" if state.get("tp_plan_applied") else END


def build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    g: StateGraph[PlanningState] = StateGraph(PlanningState)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("design", make_design_node(deps))
    g.add_node("review", review_node)
    g.add_node("apply", make_apply_node(deps))
    g.add_node("adjust", adjust_node)

    g.add_conditional_edges(START, route_start, ["review", "intake", "targets", "adjust"])
    g.add_conditional_edges("intake", after_intake, ["targets", END])
    g.add_conditional_edges("targets", after_targets, ["review", "design", END])
    g.add_edge("design", "review")
    g.add_conditional_edges("review", after_review, ["apply", "design", "adjust", END])
    g.add_conditional_edges("apply", after_apply, ["targets", END])
    g.add_edge("adjust", END)
    return g.compile(checkpointer=checkpointer, name="tri-planning")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_graph.py -q`
Expected: 7 passed. Two things to check if not:
- The scripted `week_call(300)` must be within 10 % of the week-1 target for the test database's fitness rows. The test database has no `daily_metrics` rows outside a transaction, so week 1 falls to the olympic floor `300`. If a test asserts a `VIOLATIONS` summary unexpectedly, print `await first_target(nocommit)` and script that number.
- `Command(resume=...)` with a compiled graph and `ainvoke` returns the final state; `__interrupt__` is present in the returned dict only when the run paused.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): graph wiring with review interrupt, end-to-end tests"
```

---

### Task 8: Postgres checkpointer

**Files:**
- Create: `graph/checkpointer.py`, `scripts/setup_checkpointer.py`
- Test: `tests/test_checkpointer.py`

**Interfaces:**
- Produces:
  - `checkpointer.open_checkpointer(url: str) -> AsyncIterator[AsyncPostgresSaver]` (async context manager over `AsyncPostgresSaver.from_conn_string(url)`).
  - `checkpointer.checkpointer_ready(url: str) -> bool` (sync; true when the `checkpoints` table exists).
  - `checkpointer.SETUP_HINT: str` (the command to run).

- [ ] **Step 1: Write the failing test**

`packages/tri-planning/tests/test_checkpointer.py`:
```python
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.graph.checkpointer import checkpointer_ready, open_checkpointer
from tri_planning.graph.graph import build_graph
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db


async def test_second_process_resumes_from_postgres(nocommit, make_deps):
    url = Settings().test_database_url
    if not checkpointer_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
    script = [tool_call("set_training_goal", GOAL_ARGS), AIMessage(content="Goal saved."),
              tool_call("PlannedWeek", week_json(MONDAY, 300))]
    tp = FakeTp()
    try:
        async with open_checkpointer(url) as saver:
            graph = build_graph(make_deps(ScriptedChatModel(script=script), tp=tp), saver)
            out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, thread)
            assert "__interrupt__" in out
        # "second process": a new saver, a new graph, a model with nothing left to say
        async with open_checkpointer(url) as saver2:
            graph2 = build_graph(make_deps(ScriptedChatModel(script=[]), tp=tp), saver2)
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), thread)
            assert out["phase"] == "active" and len(tp.calls) == 3
    finally:
        async with open_checkpointer(url) as saver3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
```

Note: the graph's own rows (goal, plan) go through `nocommit` and roll back; only checkpoint rows persist, and the `finally` deletes them.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_checkpointer.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write `graph/checkpointer.py` and the setup script**

`graph/checkpointer.py`:
```python
"""Postgres-backed checkpointing so a paused review survives process exit.

LangGraph lesson: the checkpointer is what makes `interrupt()` durable. Every super-step writes
a checkpoint keyed by thread_id; `Command(resume=...)` in a fresh process picks up from it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


@asynccontextmanager
async def open_checkpointer(url: str) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])
```

`scripts/setup_checkpointer.py`:
```python
"""Create LangGraph's checkpoint tables. Brian runs this once per database; the app never does DDL.

    uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
"""

import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def main(url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
    print(f"checkpoint tables ready in {url.rsplit('/', 1)[-1]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 4: Brian creates the tables, then run the test**

```bash
uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test
uv run pytest packages/tri-planning/tests/test_checkpointer.py -q
```
Expected: `checkpoint tables ready in tri_analyze` and `... tri_analyze_test`; 1 passed. If `from_conn_string` complains about pipeline mode or `autocommit`, pass the connection explicitly: `AsyncPostgresSaver(await psycopg.AsyncConnection.connect(url, autocommit=True, prepare_threshold=0, row_factory=dict_row))` in `open_checkpointer` and close it on exit. Verify this against the installed package's `from_conn_string` source and note the finding in spec §15.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): Postgres checkpointer and setup script"
```

---

### Task 9: REPL

**What this teaches:** streaming a graph that contains subgraphs (`subgraphs=True` changes the event tuple), detecting `__interrupt__` in the update stream, and driving resume from a terminal.

**Files:**
- Create: `repl.py`
- Test: `tests/test_repl.py`

**Interfaces:**
- Consumes: `CalendarChange`, `ReviewDecision`, a compiled graph (`astream`, `aget_state`).
- Produces (all in `tri_planning.repl`):
  - `TurnPrinter(out)` with `on_event(namespace: tuple, mode: str, data)`, attributes `final_text: str`, `interrupt: dict | None`.
  - `run_turn(graph, payload: dict | Command, thread_id: str, out) -> TurnPrinter`.
  - `render_changes(payload: dict) -> str` (summary, then a table grouped by week: date, sport, op, title, min, TSS, reason; `last_error` line when present).
  - `parse_decision(line: str) -> ReviewDecision | None` (`approve`; `reject <note>`; `edit` -> `ReviewDecision(action="edit")` with `changes=None`, the loop fills it; anything else `None`).
  - `changes_to_yaml(changes: list[CalendarChange]) -> str`, `changes_from_yaml(text: str) -> list[CalendarChange]`.
  - `EditFn = Callable[[list[CalendarChange]], Awaitable[list[CalendarChange] | None]]`.
  - `chat_loop(graph, *, read, out, thread_id="planning", commands=None, edit=None) -> None`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_repl.py`:
```python
from datetime import date

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.repl import (
    TurnPrinter, changes_from_yaml, changes_to_yaml, chat_loop, parse_decision, render_changes,
)


def change(day=14, title="Ride", op="create"):
    s = PlannedSession(date=date(2026, 9, day), sport="bike", title=title, description="z2",
                       duration_minutes=60, tss_planned=50, intensity="endurance")
    return CalendarChange(op=op, workout_date=s.date, workout=s, reason="base week")


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject too much bike")
    assert d.action == "reject" and d.note == "too much bike"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip():
    changes = [change(), change(15, "Run"), CalendarChange(op="delete", tp_workout_id="9", reason="drop")]
    text = changes_to_yaml(changes)
    assert "Ride" in text and "tp_workout_id: '9'" in text
    assert changes_from_yaml(text) == changes


def test_render_changes_groups_by_week():
    payload = {"summary": "week one", "changes": [change().model_dump(mode="json"), change(21, "Next").model_dump(mode="json")],
               "last_error": None}
    text = render_changes(payload)
    assert "week one" in text and "2026-09-14" in text and "2026-09-21" in text and "Ride" in text
    assert text.index("2026-09-14") < text.index("2026-09-21")


def test_turn_printer_handles_subgraph_events_and_interrupt():
    buf = []
    p = TurnPrinter(buf.append)
    p.on_event(("intake:abc",), "messages", (AIMessageChunk(content="Hel"), {"langgraph_node": "model"}))
    p.on_event(("intake:abc",), "messages", (AIMessageChunk(content="lo"), {"langgraph_node": "model"}))
    p.on_event(("intake:abc",), "updates", {"tools": {"messages": [ToolMessage(content="{}", name="set_training_goal", tool_call_id="1")]}})
    p.on_event((), "updates", {"targets": {"messages": [AIMessage(content="Targets: 14 weeks")]}})
    p.on_event((), "updates", {"__interrupt__": (Interrupt(value={"summary": "s", "changes": []}),)})
    text = "".join(buf)
    assert "Hello" in text and "← set_training_goal" in text and "Targets: 14 weeks" in text
    assert p.interrupt == {"summary": "s", "changes": []}


class StubGraph:
    """Yields scripted event lists per astream call; records the inputs it was given."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.inputs = []

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"pending_changes": [], "phase": "intake"}
            next = ()
        return S()


async def test_chat_loop_review_dialogue_resumes_with_decision():
    interrupt_ev = ((), "updates", {"__interrupt__": (Interrupt(value={"summary": "s", "changes": [change().model_dump(mode="json")], "last_error": None}),)})
    done_ev = ((), "updates", {"apply": {"messages": [AIMessage(content="TrainingPeaks: applied 1 of 1 changes.")]}})
    graph = StubGraph([[interrupt_ev], [done_ev]])
    inputs = iter(["plan my season", "huh", "approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    text = "".join(buf)
    assert "Ride" in text and "approve / reject" in text and "applied 1" in text
    assert isinstance(graph.inputs[1], Command) and graph.inputs[1].resume == {"action": "approve"}


async def test_chat_loop_edit_uses_editor_callback():
    interrupt_ev = ((), "updates", {"__interrupt__": (Interrupt(value={"summary": "s", "changes": [change().model_dump(mode="json")], "last_error": None}),)})
    graph = StubGraph([[interrupt_ev], []])
    inputs = iter(["go", "edit", "/quit"])

    async def read():
        return next(inputs, None)

    async def edit(changes):
        return [changes[0].model_copy(update={"reason": "edited"})]

    await chat_loop(graph, read=read, out=lambda s: None, edit=edit)
    resume = graph.inputs[1].resume
    assert resume["action"] == "edit" and resume["changes"][0]["reason"] == "edited"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_repl.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write `repl.py`**

```python
"""Terminal REPL for the planning graph: stream a turn, show node activity, run the review dialogue.

LangGraph lesson: with `subgraphs=True` every stream event is (namespace, mode, data). The
namespace is () for the parent graph and ("intake:<id>",) inside the intake sub-agent. An
interrupt shows up as an "updates" event whose only key is "__interrupt__".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
import yaml
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from tri_planning.planning.models import CalendarChange, ReviewDecision
from tri_planning.planning.targets import week_monday

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[CalendarChange]], Awaitable[list[CalendarChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


class TurnPrinter:
    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if isinstance(chunk, AIMessageChunk | AIMessage) and meta.get("langgraph_node") == "model":
                text = _text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode != "updates" or not isinstance(data, dict):
            return
        if "__interrupt__" in data:
            first = data["__interrupt__"][0]
            self.interrupt = dict(first.value)
            return
        for node, payload in data.items():
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls:
                        self.final_text = _text_of(msg) or self.final_text
                        self.out("\n")
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self.out(f"← {msg.name}: {len(_text_of(msg))} chars\n")
                elif not namespace and isinstance(msg, AIMessage):
                    text = _text_of(msg)
                    self.out(f"[{node}] {text}\n")
                    self.final_text = text


async def run_turn(graph: Any, payload: dict[str, Any] | Command, thread_id: str, out: Out) -> TurnPrinter:
    printer = TurnPrinter(out)
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        async for namespace, mode, data in graph.astream(
            payload, config=cfg, stream_mode=["messages", "updates"], subgraphs=True
        ):
            printer.on_event(tuple(namespace), mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    return printer


def render_changes(payload: dict[str, Any]) -> str:
    changes = [CalendarChange.model_validate(c) for c in payload.get("changes", [])]
    lines: list[str] = []
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
    by_week: dict[str, list[CalendarChange]] = defaultdict(list)
    for c in changes:
        key = str(week_monday(c.workout_date)) if c.workout_date else "(no date)"
        by_week[key].append(c)
    lines.append(f"{'date':10}  {'sport':8}  {'op':11}  {'title':28}  {'min':>4}  {'tss':>4}  reason")
    for key in sorted(by_week):
        lines.append(f"-- week of {key}")
        for c in by_week[key]:
            w = c.workout
            lines.append(
                f"{str(c.workout_date or ''):10}  {(w.sport if w else ''):8}  {c.op:11}  "
                f"{(w.title if w else (c.tp_workout_id or '')):28.28}  "
                f"{(str(w.duration_minutes) if w else ''):>4}  {(f'{w.tss_planned:.0f}' if w else ''):>4}  {c.reason[:60]}"
            )
    lines.append(f"{len(changes)} changes. {REVIEW_PROMPT}")
    return "\n".join(lines)


def parse_decision(line: str) -> ReviewDecision | None:
    word, _, rest = line.strip().partition(" ")
    if word == "approve":
        return ReviewDecision(action="approve")
    if word == "reject":
        return ReviewDecision(action="reject", note=rest.strip() or None)
    if word == "edit":
        return ReviewDecision(action="edit")
    return None


def changes_to_yaml(changes: list[CalendarChange]) -> str:
    return yaml.safe_dump([c.model_dump(mode="json", exclude_none=True) for c in changes], sort_keys=False)


def changes_from_yaml(text: str) -> list[CalendarChange]:
    return [CalendarChange.model_validate(d) for d in (yaml.safe_load(text) or [])]


async def _review_dialogue(
    payload: dict[str, Any], read: Callable[[], Awaitable[str | None]], out: Out, edit: EditFn | None
) -> ReviewDecision | None:
    out(render_changes(payload) + "\n")
    while True:
        line = await read()
        if line is None:
            return None
        if line.strip() == "/pending":
            out(render_changes(payload) + "\n")
            continue
        if line.strip() == "/quit":
            return None
        decision = parse_decision(line)
        if decision is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        if decision.action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            changes = [CalendarChange.model_validate(c) for c in payload.get("changes", [])]
            edited = await edit(changes)
            if edited is None:
                out("edit cancelled\n")
                continue
            decision = ReviewDecision(action="edit", changes=edited)
        return decision


async def chat_loop(
    graph: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    thread_id: str = "planning",
    commands: dict[str, CommandFn] | None = None,
    edit: EditFn | None = None,
) -> None:
    commands = dict(commands or {})
    out("tri-planning chat. Type a message, /quit to exit, /<command> for: "
        + ", ".join(sorted(["quit", "pending", *commands])) + "\n")
    pending: dict[str, Any] | None = None
    while True:
        if pending is not None:
            decision = await _review_dialogue(pending, read, out, edit)
            if decision is None:
                out("\n")
                return
            printer = await run_turn(graph, Command(resume=decision.model_dump(mode="json")), thread_id, out)
            pending = printer.interrupt
            continue
        line = await read()
        if line is None:
            out("\n")
            return
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            name = line[1:].split()[0]
            if name == "quit":
                return
            if name == "pending":
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                changes = snap.values.get("pending_changes") or []
                if not changes:
                    out("nothing pending\n")
                else:
                    pending = {"summary": snap.values.get("pending_summary") or "",
                               "changes": [c.model_dump(mode="json") for c in changes],
                               "last_error": snap.values.get("last_error")}
                continue
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        printer = await run_turn(graph, {"messages": [HumanMessage(line)]}, thread_id, out)
        pending = printer.interrupt
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_repl.py -q`
Expected: 6 passed. `/pending` from a paused state re-enters the review dialogue by re-reading `pending_changes` from the checkpoint and resuming with the athlete's decision, which is exactly what a second process does.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): streaming REPL with review dialogue and YAML edit"
```

---

### Task 10: `chat` and `reset` commands, README, first conversation

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/cli.py`, `packages/tri-planning/README.md`, root `README.md`
- Test: manual (Brian) plus `uv run tri-planning --help`

**Interfaces:**
- Produces: `tri-planning chat [--no-live]`, `tri-planning reset [--yes]`, `/status`, `/pending`, `/sync`, `/quit`.

- [ ] **Step 1: Write the commands**

Replace `packages/tri-planning/src/tri_planning/cli.py` with:
```python
"""Command-line entry points for the planning agent: chat, reset (check-in arrives in Plan 4)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from datetime import date, timedelta
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_planning.config import get_planning_settings

load_dotenv()
# Both agents share one .env; give this agent its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_planning_settings().tri_planning_langsmith_project

app = typer.Typer(help="Triathlon training planning agent", no_args_is_help=True)
console = Console()
THREAD_ID = "planning"
TP_START_TIMEOUT_S = 120


@app.callback()
def main() -> None:
    """Triathlon training planning agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


@app.command()
def chat(no_live: bool = typer.Option(False, "--no-live", help="Do not start the TrainingPeaks server")) -> None:
    """Plan and adjust training in conversation; every calendar write is approved first."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from contextlib import AsyncExitStack

    from tri_core.db.connection import connect
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import trainingpeaks_spec
    from tri_core.sync.runner import run_sync
    from tri_planning import repo
    from tri_planning.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_planning.graph.deps import make_deps
    from tri_planning.graph.graph import build_graph
    from tri_planning.graph.llm import make_model
    from tri_planning.planning.models import CalendarChange
    from tri_planning.planning.targets import week_monday
    from tri_planning.repl import changes_from_yaml, changes_to_yaml, chat_loop

    settings = get_planning_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        raise typer.Exit(code=2)

    async with AsyncExitStack() as stack:
        tp = None
        if not no_live:
            try:
                tp = await asyncio.wait_for(
                    stack.enter_async_context(McpToolClient(trainingpeaks_spec(settings))),
                    timeout=TP_START_TIMEOUT_S,
                )
                _out("trainingpeaks: connected (writes happen only after you approve)\n")
            except Exception as exc:  # the chat still works; apply refuses until the server is back
                _out(f"warning: trainingpeaks MCP server unavailable ({type(exc).__name__}: {exc}); "
                     "apply will refuse to write\n")
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), tp), saver)
        cfg = {"configurable": {"thread_id": THREAD_ID}}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def cmd_status() -> str:
            snap = await graph.aget_state(cfg)
            values: dict[str, Any] = snap.values or {}
            with connect(settings.database_url) as conn:
                goal = repo.get_active_goal(conn)
                if goal is None:
                    return "no active goal; phase " + str(values.get("phase") or "intake")
                plan = repo.get_active_plan(conn, goal.id)
                monday = week_monday(date.today())
                actual = conn.execute(
                    "select coalesce(sum(tss_day), 0) as t from daily_metrics where metric_date between %s and %s",
                    (monday, monday + timedelta(days=6)),
                ).fetchone()
                lines = [f"goal: {goal.goal.goal_type} {goal.goal.event_name or ''} {goal.goal.event_date or ''}".rstrip(),
                         f"phase: {values.get('phase') or 'intake'}; next node: {snap.next or '-'}"]
                if plan is not None:
                    weeks = repo.list_weeks(conn, plan.id)
                    this = next((w for w in weeks if w.week_start == monday), None)
                    if this is not None:
                        lines.append(f"this week ({this.phase}): target {this.target_tss:.0f} TSS, actual so far {float(actual['t']):.0f}")
                    remaining = sum(1 for w in weeks if w.designed and w.week_start >= monday)
                    lines.append(f"designed weeks remaining: {remaining} of {len(weeks)}")
                if values.get("last_error"):
                    lines.append(f"last error: {values['last_error']}")
                return "\n".join(lines)

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            return "sync " + ("ok" if report.ok else "had errors")

        async def edit_in_editor(changes: list[CalendarChange]) -> list[CalendarChange] | None:
            editor = os.environ.get("EDITOR", "vi")
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                f.write(changes_to_yaml(changes))
                path = f.name
            await asyncio.to_thread(subprocess.call, [editor, path])
            try:
                with open(path) as f:
                    return changes_from_yaml(f.read())
            except Exception as exc:
                _out(f"could not parse edited YAML: {exc}\n")
                return None
            finally:
                os.unlink(path)

        await chat_loop(graph, read=read, out=_out, thread_id=THREAD_ID,
                        commands={"status": cmd_status, "sync": cmd_sync}, edit=edit_in_editor)


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation")) -> None:
    """Abandon the active goal and plan and clear the conversation. Never touches TrainingPeaks."""
    if not yes and not typer.confirm("Abandon the active goal and plan and forget the conversation?"):
        raise typer.Exit(code=1)
    asyncio.run(_reset())


async def _reset() -> None:
    from tri_core.db.connection import connect
    from tri_planning import repo
    from tri_planning.graph.checkpointer import checkpointer_ready, open_checkpointer

    settings = get_planning_settings()
    with connect(settings.database_url) as conn:
        goals, plans = repo.abandon_active(conn)
        conn.commit()
    if checkpointer_ready(settings.database_url):
        async with open_checkpointer(settings.database_url) as saver:
            await saver.adelete_thread(THREAD_ID)
    console.print(f"reset: {goals} goal(s) abandoned, {plans} plan(s) superseded, thread cleared")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Smoke the commands**

```bash
uv run tri-planning --help
uv run tri-planning chat --no-live
```
In chat: `/status`, then `/quit`. Expected: `--help` lists `chat` and `reset`; `/status` prints `no active goal; phase intake`.

- [ ] **Step 3: First real conversation (Brian)**

```bash
docker compose up -d && uv run tri sync
uv run tri-planning chat
```
Suggested flow: describe a race 12+ weeks out, answer the intake questions, confirm. Watch for `→ set_training_goal(...)`, the `[targets] Targets (generated): N weeks ...` line, the design summary per week, then the change table. Type `reject` with a note once to see the redesign, then `approve`. Check the TrainingPeaks calendar. If anything is wrong, `uv run tri-planning reset --yes` and delete the workouts in TrainingPeaks by hand (this milestone has no bulk undo; Plan 4's adjust can delete agent-authored workouts).

Things to judge, as in analyze's README: whether intake asks one or two questions per turn and grounds them in CTL; whether the designed weeks respect availability without validator retries (LangSmith shows a second design call per week when they don't; tune `DESIGN_SYSTEM`); whether reasons in the change table are useful.

- [ ] **Step 4: README updates**

`packages/tri-planning/README.md`: replace "Layout so far" with:
```markdown
## Commands

```bash
uv run tri-planning chat [--no-live]   # intake -> targets -> design -> review -> apply
uv run tri-planning reset [--yes]      # abandon goal and plan, clear the thread; TrainingPeaks untouched
```

In chat: `/status` (goal, phase, this week's target vs actual, designed weeks left), `/pending`
(re-show a paused change set), `/sync`, `/quit`. At review: `approve`, `reject <note>`, or
`edit` (opens the change set as YAML in `$EDITOR`).

One-time setup after the migrations: `uv run python scripts/setup_checkpointer.py <DATABASE_URL>`
for both databases (creates LangGraph's checkpoint tables).

## How a turn flows

```
you> ...            intake sub-agent (create_agent) asks, queries the DB, finally calls set_training_goal
[targets] ...      pure Python: goal + fitness -> week targets (training_plans, plan_weeks)
[design]            one with_structured_output(PlannedWeek) call per window week, validated, retried once
<change table>      review node: interrupt(); the run is checkpointed in Postgres until you answer
approve             apply: one TrainingPeaks call per change, each recorded in plan_changes
```

Layout: `graph/` (state, deps, nodes, wiring, checkpointer), `planning/` (models, periodization,
targets, validate, tp_calls), `tools/` (intake tools), `prompts/`, `repl.py`, `repo.py`.
```

Root `README.md`: in the package table change the tri-planning row's description to `Planning agent: goal intake, periodized plan, approved writes to the TrainingPeaks calendar.`; under Setup add step `6. Checkpoint tables (once per database): uv run python scripts/setup_checkpointer.py <url>`; under Run add `uv run tri-planning chat [--no-live]` and `uv run tri-planning reset`.

- [ ] **Step 5: Docs to the vault, final checks, commit (Brian)**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp README.md $V/readme.md && cp packages/tri-planning/README.md $V/packages/tri-planning/readme.md
cp docs/superpowers/plans/*.md $V/docs/superpowers/plans/
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): chat and reset commands; README"
git push
```

---

## Self-review notes

- Spec §6.1 state: eight fields plus two routing fields (deviation listed). §6.2 every edge is a route function in Task 7 with a test. Intake (Task 3), targets including the bought-plan re-entry (Task 4), design with tags and one retry (Task 5), review interrupt with approve/reject/edit and reject-note-as-HumanMessage (Tasks 6 and 7), apply with ownership, per-call audit rows, mid-batch stop and `written_to_tp` (Task 6). Adjust is a placeholder by design (milestone 4).
- Spec §8 `chat` (streaming, `→`/`←` lines, change table grouped by week with reasons, `approve / reject <note> / edit`, YAML in `$EDITOR`, `/status`, `/pending`, `/sync`, `/quit`) and `reset` in Tasks 9 and 10.
- Spec §9: MCP server down (warning, apply refuses: Task 6 test), mid-batch failure (Task 6 and Task 7 tests), design fails twice (VIOLATIONS in the summary: Task 5 test), ownership (Task 6 test), API errors caught per turn (Task 9 `run_turn`), checkpointer unavailable (`chat` exits with `SETUP_HINT`).
- Spec §11 graph tests: intake ends on `set_training_goal`, review pauses and approve reaches apply, reject routes back with the note, second process resumes from Postgres, fake TP ownership refusal and mid-batch failure, one `plan_changes` row per call, YAML round trip. The live create/update/delete test is deferred to Plan 4 where `update` and `delete` first get exercised by the agent.
- Spec §15 open items: `PostgresSaver` connection handling (Task 8, with a fallback), `tp_apply_training_plan` id behavior (Global Constraints; Task 4 follow-up `tp_get_workouts`), `tp_create_workout` result shape (Global Constraints; `result_workout_id`).
- Type consistency: `make_*_node(deps)` factories return `async (state, config)`; `review_node` and `adjust_node` are plain functions; `build_graph(deps, checkpointer)` matches the cli and both test files; `FakeTp.call_json` matches `tri_core.sync.ToolCaller`.
