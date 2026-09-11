# tri-nutrition Plan 3 of 4: Fueling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The fuel node: one structured-output call per qualifying session in the horizon and one for the goal event when it is within 21 days, each validated by `bounds.validate_fuel` / `validate_race` with one retry, stored in `fuel_plans`, and written to TrainingPeaks after approval as private workout notes (sessions) and a calendar note (race). Apply gains the TrainingPeaks operations with note ownership. This is spec milestone 3.

**Architecture:** `fuel` replaces the Plan 2 pass-through node and keeps the `targets -> fuel -> review` edges. It reads the profile, product library and fuel log from the Store, the horizon from `plan_loader` (which now attaches TrainingPeaks workout ids to plan-designed sessions by matching synced `workouts` rows), and each day's `DayTarget` from `nutrition_targets`. The model returns `SessionFuel` / `RaceFuelPlan` through `with_structured_output`; Python validates and decides what is written. `apply` translates `set_session_note` and `set_race_note` through `nutrition/tp_calls.py` and a second live `ToolCaller` for TrainingPeaks; Garmin and TrainingPeaks failures are independent.

**Tech Stack:** langchain 1.4.0 `with_structured_output`, langgraph 1.2.11, the pinned trainingpeaks-mcp `a412a84` note tools, psycopg 3. Depends on Plans 1 and 2 as merged on main (including the today-only Garmin write and the `garmin_mcp` pin bump).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md` (§2 TrainingPeaks tools, §5.1 product library and fuel log, §5.2 `fuel_plans`, §6.2 fuel and apply, §6.3 `SessionFuel` / `RaceFuelPlan`, §7.6 bounds, §9, §13 milestone 3, §15 items 3 and 4). Read Plan 2's execution notes first.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- `tri_nutrition` imports `tri_core` only. No new dependencies.
- TrainingPeaks facts from the pinned server source (`a412a84`, verified 2026-09-10): `tp_set_workout_note(workout_id, note)` PUTs `/fitness/v6/workouts/{id}/privateWorkoutNote` and returns `{"success": true, "note": ...}`; `tp_get_workout_note(workout_id)` reads it; `tp_create_note(date, title, description?)` returns `{"success": true, "note_id": <calendarNoteId>, "title", "date"}`; `tp_update_note(note_id, title?, description?, date?, is_hidden?)`; `tp_get_note(note_id)` returns `{"note": {id, title, description, date, is_hidden}}`; `tp_list_notes(start_date, end_date)` returns `{"notes": [{id, ...}], "count"}`. Failures come back as `{"isError": true, "error_code", "message"}`, which `tri_core.mcp.client.parse_tool_text` raises as `McpToolError`.
- Session note ownership: `apply` overwrites a workout's private note only when `nutrition_changes` already holds a `set_session_note` row for that workout id, or the current private note is empty. Race note ownership: `apply` updates a calendar note only when its id is in `repo.owned_note_ids`; a `set_race_note` with an empty `target_key` creates a new note.
- Fuel qualification (spec §6.2): sessions in the horizon with `duration_min > 75` or `intensity in {threshold, vo2, race}`; the race plan when `ctx.event_date` is within 21 days of today. Sessions without a TrainingPeaks workout id are still planned and stored (their `tp_workout_id` is `NULL`) but produce no note change; the summary says so.
- Bounds (Plan 1): `validate_fuel(fuel, profile, library, fuel_log, other_caffeine_mg_today)` and `validate_race(plan, profile, library, fuel_log)`; retry once with the violation list; store remaining violations in `fuel_plans.violations` and show them at review (spec §9).
- LangSmith tags on fuel calls: `day:<date>`, `kind:session|race`.
- Every model call in tests goes through `ScriptedChatModel` with `tool_call("SessionFuel", {...})` / `tool_call("RaceFuelPlan", {...})`, as planning does for `PlannedWeek`.
- **Brian runs every database command and every TrainingPeaks write.** Tests use the rolled-back `db` fixture and `FakeTp`.
- Definition of done per task: `uv run ruff format packages/tri-nutrition`, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`PlanContext` gains `event_name: str | None` and `goal_type: str | None`** (read from `training_goals`) so the race prompt can name the event and its distance. Both default to `None`.
- **Plan-designed sessions get their TrainingPeaks workout id by matching `workouts` rows** on `(workout_date, sport)`, then title when a day has two of the same sport. Planning's `plan_weeks.designed` JSON has no ids; the synced `workouts` table does. Unmatched sessions are planned but not written.
- **`fuel` regenerates every qualifying session each time it runs** (after intake or a checkin save, never from `today`) and emits a change only when the note text differs from what was last written. Cost is bounded by the horizon; a rule that skips "unchanged" sessions would need the model's previous output to be re-derivable and it is not.
- **Session notes are private workout notes** (`tp_set_workout_note`), as the spec says; whether that field is visible enough in the TrainingPeaks calendar and mobile app is spec §15 item 3 and is settled by Brian in Task 8. If it is not, the switch to `tp_update_workout(description=...)` is a one-line change in `tp_calls.py`, and is noted there.
- **The race note title is fixed:** `Race fuel: <event name or goal type> <event date>`; `apply` finds an existing agent-owned note for the event date through `repo.owned_note_ids` and the stored `fuel_plans.tp_note_id`.
- **`GraphDeps` gains `tp: ToolCaller | None`; `chat` opens both servers.** `--no-live` starts neither. A dead TrainingPeaks server holds only the note changes pending (spec §9).

---

## File Structure

```
packages/tri-nutrition/src/tri_nutrition/
  allowlist.py               + TP_WRITE_TOOLS, TP_READ_TOOLS
  testing.py                 + FakeTp, session_fuel_json(), race_plan_json()
  plan_loader.py             + attach_workout_ids(); PlanContext event_name / goal_type
  nutrition/models.py        PlanContext + event_name, goal_type
  nutrition/tp_calls.py      to_tp_call(), result_note_id(), race_note_title()
  prompts/fuel.py            FUEL_SYSTEM, render_session_prompt()
  prompts/race.py            RACE_SYSTEM, render_race_prompt()
  graph/deps.py              GraphDeps.tp
  graph/nodes/fuel.py        make_fuel_node(deps) (replaces fuel_node)
  graph/nodes/apply.py       TP ops, ownership, write_change for both servers
  graph/graph.py             make_fuel_node
  repl.py                    render_fuel(), render_race() used in summaries
  cli.py                     chat opens TrainingPeaks; --no-live
packages/tri-nutrition/tests/
  conftest.py                make_deps(tp=...), fake_tp
  test_plan_loader.py        + attach_workout_ids
  test_tp_calls.py           pure
  test_fuel_node.py          db + ScriptedChatModel
  test_apply_node.py         + TP cases
  test_graph.py              + intake -> targets -> fuel -> review with session and race changes
  test_repl.py               + render_fuel / render_race
```

Responsibilities: `tp_calls.py` is pure translation. `prompts/` own the model-facing text. `nodes/fuel.py` decides what to plan, calls the model, validates, stores, and emits changes. `nodes/apply.py` is the only writer for both servers.

---

### Task 1: Allow-lists, deps, fakes, and workout-id matching

**Files:**
- Modify: `allowlist.py`, `graph/deps.py`, `testing.py`, `nutrition/models.py` (`PlanContext`), `plan_loader.py`, `tests/conftest.py`
- Test: `tests/test_plan_loader.py` (add cases)

**Interfaces:**
- `allowlist.TP_WRITE_TOOLS = ["tp_set_workout_note", "tp_create_note", "tp_update_note"]`, `allowlist.TP_READ_TOOLS = ["tp_get_workout_note", "tp_get_note", "tp_list_notes"]`.
- `GraphDeps.tp: ToolCaller | None = None`; `make_deps(settings, model, garmin, tp)`.
- `testing.FakeTp(responses=None, fail_on_call=None)`: `tp_set_workout_note -> {"success": True, "note": note}`, `tp_get_workout_note -> {"note": ""}` (override with `responses`), `tp_create_note -> {"success": True, "note_id": "n<N>", "title", "date"}`, `tp_update_note -> {"success": True, "note_id"}`, `tp_get_note`, `tp_list_notes -> {"notes": [], "count": 0}`.
- `testing.session_fuel_json(workout_id, day, **over) -> dict` and `testing.race_plan_json(event_date, **over) -> dict`: valid model outputs for `PROFILE_ARGS`'s product library (`Gel`).
- `plan_loader.attach_workout_ids(sessions, rows) -> list[Session]` pure: rows are `workouts` dicts with `tp_workout_id, workout_date, sport, title`; a session with an id keeps it; otherwise match on `(day, sport)`; when several rows match, prefer an exact title match; when still ambiguous take the first unused.
- `plan_loader.load_horizon` fills ids for `plan` sessions from `workouts` rows in the horizon (completed or not) and sets `PlanContext.event_name` and `goal_type`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-nutrition/tests/test_plan_loader.py`:
```python
def test_attach_workout_ids_matches_day_and_sport_then_title():
    a = session_json(MONDAY, "bike", 90)
    b = session_json(MONDAY, "bike", 30)
    b["title"] = "Openers"
    designed = {"week_start": MONDAY.isoformat(), "coach_note": "", "sessions": [a, b]}
    sessions = L.sessions_from_designed(designed, MONDAY, MONDAY)
    rows = [
        {"tp_workout_id": "w2", "workout_date": MONDAY, "sport": "bike", "title": "Openers"},
        {"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "title": "bike 90"},
        {"tp_workout_id": "w9", "workout_date": MONDAY, "sport": "run", "title": "x"},
    ]
    out = L.attach_workout_ids(sessions, rows)
    assert [(s.title, s.tp_workout_id) for s in out] == [("bike 90", "w1"), ("Openers", "w2")]
    keep = L.attach_workout_ids([sessions[0].model_copy(update={"tp_workout_id": "kept"})], rows)
    assert keep[0].tp_workout_id == "kept"
    assert L.attach_workout_ids(sessions, [])[0].tp_workout_id is None


def test_load_horizon_attaches_ids_and_goal_fields(pdb):
    seed_goal_and_plan(
        pdb, MONDAY, [("build", [session_json(MONDAY, "bike", 90)])], event_date=MONDAY + timedelta(days=10)
    )
    seed_workouts(
        pdb,
        [{"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "planned_duration_sec": 5400, "title": "bike 90"}],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 7)
    assert ctx.source == "plan" and sessions[0].tp_workout_id == "w1"
    assert ctx.event_name == "City Tri" and ctx.goal_type == "olympic"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_plan_loader.py -q`
Expected: `AttributeError: module 'tri_nutrition.plan_loader' has no attribute 'attach_workout_ids'`.

- [ ] **Step 3: Allow-lists, deps, models**

`allowlist.py`: append
```python
TP_WRITE_TOOLS = ["tp_set_workout_note", "tp_create_note", "tp_update_note"]
TP_READ_TOOLS = ["tp_get_workout_note", "tp_get_note", "tp_list_notes"]
```

`graph/deps.py`: add `tp: ToolCaller | None = None  # live TrainingPeaks session; None when down` after `garmin` in `GraphDeps`, and change `make_deps` to `def make_deps(settings, model, garmin, tp=None)` passing `tp=tp`.

`nutrition/models.py`, in `PlanContext` after `event_priority`:
```python
    event_name: str | None = None
    goal_type: str | None = None
```

`tests/conftest.py`: add a `fake_tp` fixture returning `FakeTp()` and extend `_make(model, *, garmin=None, tp=None, horizon=14, today=MONDAY)` passing `tp=tp`.

- [ ] **Step 4: Fakes**

Append to `testing.py`:
```python
class FakeTp:
    """Records every call; answers like the TrainingPeaks server. `fail_on_call` raises on the
    nth call. Override any tool's answer through `responses`."""

    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        a = dict(args or {})
        self.calls.append((tool, a))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "API_ERROR: boom")
        if tool in self.responses:
            return self.responses[tool]
        if tool == "tp_set_workout_note":
            return {"success": True, "note": a.get("note")}
        if tool == "tp_get_workout_note":
            return {"note": ""}
        if tool == "tp_create_note":
            return {"success": True, "note_id": f"n{len(self.calls)}", "title": a.get("title"), "date": a.get("date")}
        if tool == "tp_update_note":
            return {"success": True, "note_id": a.get("note_id")}
        if tool == "tp_get_note":
            return {"note": {"id": a.get("note_id"), "title": "", "description": "", "date": ""}}
        if tool == "tp_list_notes":
            return {"notes": [], "count": 0}
        return {}


def session_fuel_json(workout_id: str, day: date, **over: Any) -> dict[str, Any]:
    """A SessionFuel as the model would return it, valid for PROFILE_ARGS's library."""
    base: dict[str, Any] = {
        "tp_workout_id": workout_id,
        "day": day.isoformat(),
        "pre": "Oats and a banana 2 h before.",
        "carbs_g_per_h": 60,
        "fluid_ml_per_h": 600,
        "sodium_mg_per_h": 500,
        "caffeine_mg": None,
        "products": ["Gel"],
        "post": "Shake within 30 min, then a meal.",
        "gut_training": False,
        "note_text": "Fuel: 60 g/h (2 Gel per hour), 600 ml/h, 500 mg sodium/h.",
    }
    base.update(over)
    return base


def race_plan_json(event_date: date, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_date": event_date.isoformat(),
        "timeline": [
            {"offset_min": -180, "leg": "pre", "what": "Oats, banana, coffee", "carbs_g": 120,
             "fluid_ml": 500, "sodium_mg": 300, "caffeine_mg": 100, "products": []},
            {"offset_min": 20, "leg": "bike", "what": "Gel", "carbs_g": 25, "fluid_ml": 250,
             "sodium_mg": 200, "caffeine_mg": 0, "products": ["Gel"]},
            {"offset_min": 130, "leg": "run", "what": "Gel", "carbs_g": 25, "fluid_ml": 200,
             "sodium_mg": 150, "caffeine_mg": 0, "products": ["Gel"]},
        ],
        "totals_per_h": {"bike_carbs": 60, "run_carbs": 50, "bike_fluid": 700, "run_fluid": 500,
                         "bike_sodium": 600, "run_sodium": 400},
        "contingencies": ["If the gut turns: water and one gel per 30 min."],
        "note_text": "Race fuel plan: pre-race meal 3 h out; 60 g/h bike, 50 g/h run.",
    }
    base.update(over)
    return base
```

- [ ] **Step 5: Loader changes**

In `plan_loader.py` add after `sessions_from_designed`:
```python
def attach_workout_ids(sessions: list[Session], rows: list[dict[str, Any]]) -> list[Session]:
    """Give plan-designed sessions the id of the synced TrainingPeaks workout on the same day
    and sport (title breaks ties). Sessions that already carry an id keep it."""
    used: set[str] = set()
    out: list[Session] = []
    for s in sessions:
        if s.tp_workout_id is not None:
            used.add(s.tp_workout_id)
            out.append(s)
            continue
        candidates = [
            r for r in rows
            if r["workout_date"] == s.day and r["sport"] == s.sport
            and str(r["tp_workout_id"]) not in used
        ]
        exact = [r for r in candidates if (r.get("title") or "") == s.title]
        pick = (exact or candidates)[0] if (exact or candidates) else None
        if pick is None:
            out.append(s)
            continue
        wid = str(pick["tp_workout_id"])
        used.add(wid)
        out.append(s.model_copy(update={"tp_workout_id": wid}))
    return out
```
Change `_active_goal` to select `id, goal_type, event_name, event_date, priority, weekly_hours_max`, add
```python
def _workouts_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()
```
and in `load_horizon`, after the `plan` branch sets `source = "plan"`, run `sessions = attach_workout_ids(sessions, _workouts_between(conn, today, end))`; pass `event_name=goal["event_name"] if goal is not None else None` and `goal_type=goal["goal_type"] if goal is not None else None` into `PlanContext`. Add `"event_name": ctx.event_name, "goal_type": ctx.goal_type` to `describe`.

- [ ] **Step 6: Run, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition -q` — expected: all pass (existing tests untouched).
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): TrainingPeaks allow-lists and fake, deps.tp, workout-id matching for plan sessions"
```

---

### Task 2: TrainingPeaks call translation

**Files:**
- Create: `nutrition/tp_calls.py`
- Test: `tests/test_tp_calls.py`

**Interfaces:**
- `race_note_title(ctx_or_name: str | None, goal_type: str | None, event_date: date) -> str` = `f"Race fuel: {name or goal_type or 'race'} {event_date}"`.
- `session_note_change(fuel: SessionFuel) -> NutritionChange`: `op="set_session_note"`, `target_key=fuel.tp_workout_id`, payload `{"workout_id", "note"}`, reason from carbs/fluid/sodium.
- `race_note_change(plan: RaceFuelPlan, title: str, note_id: str | None) -> NutritionChange`: `op="set_race_note"`, `target_key = note_id or ""`, payload `{"date", "title", "description"}`.
- `to_tp_call(change) -> tuple[str, dict]`: `set_session_note -> ("tp_set_workout_note", {"workout_id", "note"})`; `set_race_note` with empty key `-> ("tp_create_note", {"date", "title", "description"})`, with a key `-> ("tp_update_note", {"note_id", "title", "description"})`; anything else raises `ValueError`.
- `result_note_id(change, result) -> str | None`: the created note's id (`result["note_id"]`) for a create, `change.target_key` for an update, `None` otherwise.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_tp_calls.py`:
```python
from datetime import date

import pytest

from tri_nutrition.nutrition.models import NutritionChange, RaceFuelPlan, SessionFuel
from tri_nutrition.nutrition.tp_calls import (
    race_note_change,
    race_note_title,
    result_note_id,
    session_note_change,
    to_tp_call,
)
from tri_nutrition.testing import MONDAY, race_plan_json, session_fuel_json


def test_session_note_change_and_call():
    fuel = SessionFuel.model_validate(session_fuel_json("w1", MONDAY))
    c = session_note_change(fuel)
    assert c.op == "set_session_note" and c.target_key == "w1" and c.day == MONDAY
    assert c.payload == {"workout_id": "w1", "note": fuel.note_text}
    assert "60 g/h" in c.reason
    assert to_tp_call(c) == ("tp_set_workout_note", {"workout_id": "w1", "note": fuel.note_text})
    assert result_note_id(c, {"success": True}) is None


def test_race_note_create_then_update():
    plan = RaceFuelPlan.model_validate(race_plan_json(date(2026, 10, 4)))
    title = race_note_title("City Tri", "olympic", plan.event_date)
    assert title == "Race fuel: City Tri 2026-10-04"
    assert race_note_title(None, None, plan.event_date) == "Race fuel: race 2026-10-04"
    create = race_note_change(plan, title, None)
    assert create.op == "set_race_note" and create.target_key == "" and create.day == plan.event_date
    name, args = to_tp_call(create)
    assert name == "tp_create_note"
    assert args == {"date": "2026-10-04", "title": title, "description": plan.note_text}
    assert result_note_id(create, {"success": True, "note_id": 123}) == "123"
    update = race_note_change(plan, title, "123")
    name, args = to_tp_call(update)
    assert name == "tp_update_note"
    assert args == {"note_id": "123", "title": title, "description": plan.note_text}
    assert result_note_id(update, {"success": True}) == "123"


def test_to_tp_call_rejects_garmin_ops():
    c = NutritionChange(op="set_day_targets", target_key="2026-09-14", day=MONDAY, payload={}, reason="")
    with pytest.raises(ValueError):
        to_tp_call(c)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_tp_calls.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.nutrition.tp_calls'`.

- [ ] **Step 3: Write the module**

`packages/tri-nutrition/src/tri_nutrition/nutrition/tp_calls.py`:
```python
"""SessionFuel / RaceFuelPlan -> NutritionChange -> (TrainingPeaks MCP tool name, arguments). Pure.

Session notes go to the workout's private note (tp_set_workout_note). If Brian finds that field
too hidden in the TrainingPeaks apps (spec §15 item 3), switch `to_tp_call` to
("tp_update_workout", {"workout_id", "description"}); nothing else changes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_nutrition.nutrition.models import NutritionChange, RaceFuelPlan, SessionFuel


def race_note_title(event_name: str | None, goal_type: str | None, event_date: date) -> str:
    return f"Race fuel: {event_name or goal_type or 'race'} {event_date.isoformat()}"


def session_note_change(fuel: SessionFuel) -> NutritionChange:
    caffeine = f", {fuel.caffeine_mg} mg caffeine" if fuel.caffeine_mg else ""
    return NutritionChange(
        op="set_session_note",
        target_key=fuel.tp_workout_id,
        day=fuel.day,
        payload={"workout_id": fuel.tp_workout_id, "note": fuel.note_text},
        reason=(
            f"{fuel.carbs_g_per_h} g/h carbs, {fuel.fluid_ml_per_h} ml/h, "
            f"{fuel.sodium_mg_per_h} mg/h sodium{caffeine}; {', '.join(fuel.products)}"
        ),
    )


def race_note_change(plan: RaceFuelPlan, title: str, note_id: str | None) -> NutritionChange:
    return NutritionChange(
        op="set_race_note",
        target_key=note_id or "",
        day=plan.event_date,
        payload={"date": plan.event_date.isoformat(), "title": title, "description": plan.note_text},
        reason=("update" if note_id else "create") + f" race fuel note for {plan.event_date}",
    )


def to_tp_call(change: NutritionChange) -> tuple[str, dict[str, Any]]:
    p = change.payload
    if change.op == "set_session_note":
        return "tp_set_workout_note", {"workout_id": str(p["workout_id"]), "note": str(p["note"])}
    if change.op == "set_race_note":
        if change.target_key:
            return "tp_update_note", {
                "note_id": change.target_key,
                "title": str(p["title"]),
                "description": str(p["description"]),
            }
        return "tp_create_note", {
            "date": str(p["date"]),
            "title": str(p["title"]),
            "description": str(p["description"]),
        }
    raise ValueError(f"{change.op} is not a TrainingPeaks operation")


def result_note_id(change: NutritionChange, result: Any) -> str | None:
    if change.op != "set_race_note":
        return None
    if change.target_key:
        return change.target_key
    nid = result.get("note_id") if isinstance(result, dict) else None
    return str(nid) if nid is not None else None
```

- [ ] **Step 4: Run, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition/tests/test_tp_calls.py -q` — expected: 3 passed.
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): TrainingPeaks note call translation"
```

---

### Task 3: Prompts and the fuel node

**Files:**
- Create: `prompts/fuel.py`, `prompts/race.py`
- Modify: `graph/nodes/fuel.py` (replace the placeholder), `graph/graph.py` (use `make_fuel_node`), `repl.py` (add `render_fuel`, `render_race`)
- Test: `tests/test_fuel_node.py`, `tests/test_repl.py` (add two cases)

**Interfaces:**
- `prompts.fuel.FUEL_SYSTEM: str`; `render_session_prompt(profile, library, fuel_log, session, target, violations, previous) -> str`.
- `prompts.race.RACE_SYSTEM: str`; `render_race_prompt(profile, library, fuel_log, ctx, target, violations, previous) -> str`.
- `nodes.fuel.qualifies(session) -> bool`; `nodes.fuel.race_due(ctx, today) -> bool` (event within `RACE_WINDOW_DAYS = 21`, today inclusive, and not past).
- `nodes.fuel.make_fuel_node(deps)`: returns an update with `pending_changes` = state's Garmin changes + new note changes, `pending_summary` = targets summary + fuel block, `last_error` unchanged.
- `repl.render_fuel(fuels: list[SessionFuel], violations: dict[str, list[str]]) -> str`; `repl.render_race(plan: RaceFuelPlan, violations: list[str]) -> str`.

Write rule for changes: a session's note change is emitted when the session has a `tp_workout_id` and the stored `fuel_plans` row is absent, unwritten, or has a different `note_text`. The race change is emitted when the stored race row is absent, unwritten, or differs; its `target_key` is the stored `tp_note_id` when present (an update), else empty (a create).

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_fuel_node.py`:
```python
from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.fuel import make_fuel_node, qualifies, race_due
from tri_nutrition.graph.nodes.targets import build_horizon
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session
from tri_nutrition.testing import (
    MONDAY,
    PROFILE_ARGS,
    race_plan_json,
    seed_goal_and_plan,
    seed_workouts,
    session_fuel_json,
    session_json,
)

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}
RACE = MONDAY + timedelta(days=13)


@pytest.fixture
def ndb(nocommit):
    for t in ("nutrition_targets", "plan_weeks"):
        if nocommit.execute(f"select to_regclass('{t}') as t").fetchone()["t"] is None:
            pytest.skip(f"{t} missing: migrations not applied")
    return nocommit


def test_qualifies_and_race_due():
    long = Session(day=MONDAY, sport="bike", duration_min=90, intensity="endurance")
    short = Session(day=MONDAY, sport="run", duration_min=40, intensity="endurance")
    hard = Session(day=MONDAY, sport="run", duration_min=40, intensity="threshold")
    assert qualifies(long) and qualifies(hard) and not qualifies(short)
    assert race_due(PlanContext(source="plan", event_date=MONDAY + timedelta(days=21)), MONDAY)
    assert not race_due(PlanContext(source="plan", event_date=MONDAY + timedelta(days=22)), MONDAY)
    assert not race_due(PlanContext(source="plan", event_date=MONDAY - timedelta(days=1)), MONDAY)
    assert not race_due(PlanContext(source="plan"), MONDAY)


async def seeded(ndb, mem_store, make_deps, model, *, with_race=True, horizon=14):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    week = [
        session_json(MONDAY, "bike", 120, "endurance", 100),  # qualifies (long)
        session_json(MONDAY + timedelta(days=2), "run", 45, "threshold", 60),  # qualifies (hard)
        session_json(MONDAY + timedelta(days=4), "swim", 45, "endurance", 40),  # does not
    ]
    seed_goal_and_plan(ndb, MONDAY, [("build", week), ("peak", None)], event_date=RACE if with_race else None)
    seed_workouts(
        ndb,
        [
            {"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "planned_duration_sec": 7200, "title": "bike 120"},
            {"tp_workout_id": "w2", "workout_date": MONDAY + timedelta(days=2), "sport": "run", "planned_duration_sec": 2700, "title": "run 45"},
        ],
    )
    deps = make_deps(model, horizon=horizon)
    h = await build_horizon(deps, mem_store)
    assert not h.violations
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("fuel", make_fuel_node(deps))
    g.add_edge(START, "fuel")
    g.add_edge("fuel", END)
    graph = g.compile(store=mem_store)
    return deps, graph, h


def fuel_call(workout_id, day, **over):
    return tool_call("SessionFuel", session_fuel_json(workout_id, day, **over))


async def test_plans_qualifying_sessions_and_race(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", MONDAY + timedelta(days=2)),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    out = await graph.ainvoke({"pending_changes": h.changes, "pending_summary": h.summary()}, CFG)
    assert model.calls == 3
    ops = [c.op for c in out["pending_changes"]]
    assert ops == ["set_day_targets", "set_session_note", "set_session_note", "set_race_note"]
    assert out["pending_changes"][-1].target_key == ""  # create
    plans = repo.list_fuel_plans(ndb, MONDAY, RACE)
    assert [(p.kind, p.tp_workout_id) for p in plans] == [("session", "w1"), ("session", "w2"), ("race", None)]
    assert all(p.violations == [] and not p.written for p in plans)
    assert "60 g/h" in out["pending_summary"] and "Race fuel" in out["pending_summary"]
    assert "2026-09-14" in out["pending_summary"]


async def test_retries_once_and_keeps_violations(ndb, mem_store, make_deps):
    bad = fuel_call("w1", MONDAY, carbs_g_per_h=95)  # needs evidence at 90
    good = fuel_call("w1", MONDAY)
    model = ScriptedChatModel(
        script=[
            bad,
            good,
            fuel_call("w2", MONDAY + timedelta(days=2), products=["Mystery"]),
            fuel_call("w2", MONDAY + timedelta(days=2), products=["Mystery"]),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    out = await graph.ainvoke({"pending_changes": h.changes}, CFG)
    assert model.calls == 5
    w2 = next(p for p in repo.list_fuel_plans(ndb, MONDAY, RACE) if p.tp_workout_id == "w2")
    assert any("Mystery" in v for v in w2.violations)
    assert "VIOLATIONS" in out["pending_summary"] and "Mystery" in out["pending_summary"]
    # a session plan with violations is still proposed; the athlete decides at review
    assert [c.op for c in out["pending_changes"]].count("set_session_note") == 2


async def test_unchanged_written_notes_are_not_reproposed(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[fuel_call("w1", MONDAY), fuel_call("w2", MONDAY + timedelta(days=2)), fuel_call("w1", MONDAY), fuel_call("w2", MONDAY + timedelta(days=2))]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model, with_race=False)
    await graph.ainvoke({"pending_changes": []}, CFG)
    plans = repo.list_fuel_plans(ndb, MONDAY, MONDAY + timedelta(days=13))
    repo.mark_fuel_written(ndb, plans[0].id, None)
    out = await graph.ainvoke({"pending_changes": []}, CFG)
    assert [c.target_key for c in out["pending_changes"]] == ["w2"]


async def test_race_update_uses_stored_note_id(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[fuel_call("w1", MONDAY), fuel_call("w2", MONDAY + timedelta(days=2)), tool_call("RaceFuelPlan", race_plan_json(RACE))]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    rid = repo.upsert_fuel_plan(ndb, "race", RACE, None, {"note_text": "old"}, [])
    repo.mark_fuel_written(ndb, rid, "note-77")
    out = await graph.ainvoke({"pending_changes": []}, CFG)
    race = next(c for c in out["pending_changes"] if c.op == "set_race_note")
    assert race.target_key == "note-77"


async def test_session_without_workout_id_is_stored_not_written(ndb, mem_store, make_deps):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    seed_goal_and_plan(ndb, MONDAY, [("build", [session_json(MONDAY, "bike", 120, "endurance", 100)])])
    model = ScriptedChatModel(script=[fuel_call("unmatched", MONDAY)])
    deps = make_deps(model, horizon=7)
    h = await build_horizon(deps, mem_store)
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("fuel", make_fuel_node(deps))
    g.add_edge(START, "fuel")
    g.add_edge("fuel", END)
    out = await g.compile(store=mem_store).ainvoke({"pending_changes": []}, CFG)
    assert out["pending_changes"] == []
    assert "not on the TrainingPeaks calendar" in out["pending_summary"]
    plans = repo.list_fuel_plans(ndb, MONDAY, MONDAY)
    assert len(plans) == 1 and plans[0].tp_workout_id is None


async def test_no_profile_is_a_no_op(ndb, mem_store, make_deps):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("fuel", make_fuel_node(make_deps(ScriptedChatModel(script=[]))))
    g.add_edge(START, "fuel")
    g.add_edge("fuel", END)
    out = await g.compile(store=mem_store).ainvoke({"pending_changes": [], "last_error": "x"}, CFG)
    assert out["pending_changes"] == [] and out["last_error"] == "x"
```

Append to `packages/tri-nutrition/tests/test_repl.py`:
```python
def test_render_fuel_and_race():
    from tri_nutrition.nutrition.models import RaceFuelPlan, SessionFuel
    from tri_nutrition.repl import render_fuel, render_race
    from tri_nutrition.testing import race_plan_json, session_fuel_json

    fuel = SessionFuel.model_validate(session_fuel_json("w1", MONDAY))
    text = render_fuel([fuel], {"w1": ["too much"]})
    assert "2026-09-14" in text and "60 g/h" in text and "Gel" in text and "VIOLATIONS: too much" in text
    plan = RaceFuelPlan.model_validate(race_plan_json(date(2026, 10, 4)))
    text = render_race(plan, [])
    assert "-180" in text and "pre" in text and "bike" in text and "60 g/h" in text
    assert "If the gut turns" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_fuel_node.py packages/tri-nutrition/tests/test_repl.py -q`
Expected: `ImportError: cannot import name 'make_fuel_node'`.

- [ ] **Step 3: Prompts**

`packages/tri-nutrition/src/tri_nutrition/prompts/fuel.py`:
```python
"""Session fueling prompt: the model writes one session's fuel plan inside Python-set bounds."""

from __future__ import annotations

import json

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    Session,
    SessionFuel,
)

FUEL_SYSTEM = f"""\
You are an endurance sports nutritionist writing the fueling plan for one training session of
one athlete. You return a SessionFuel: tp_workout_id and day copied from the session; pre (what
to eat and when before the session, one or two sentences); carbs_g_per_h, fluid_ml_per_h,
sodium_mg_per_h during the session; caffeine_mg for the session or null; products, a list of
product names taken verbatim from the athlete's product library; post (recovery intake in one
sentence); gut_training (true when the plan deliberately pushes intake above what the athlete has
tolerated before, to train the gut); note_text, the text that goes on the TrainingPeaks workout
(4 to 8 short lines: pre, during per hour with product counts, sodium, caffeine, post). Plain
text, no markdown.

Hard rules (a validator rejects the plan otherwise):
- carbs_g_per_h above {C.FUEL_CARBS_TIER_1} needs a logged session with outcome ok at or above
  {C.FUEL_CARBS_TIER_1} g/h; above {C.FUEL_CARBS_TIER_2} needs one at or above
  {C.FUEL_CARBS_TIER_2}; never above {C.FUEL_CARBS_MAX}. The fuel log is given; when it is empty
  stay at or below {C.FUEL_CARBS_TIER_1}.
- fluid_ml_per_h at most {C.FUEL_FLUID_MAX_ML_PER_H}; sodium_mg_per_h between
  {C.FUEL_SODIUM_MIN_MG_PER_H} and {C.FUEL_SODIUM_MAX_MG_PER_H}.
- No caffeine when the athlete takes none; total caffeine for the day at most
  {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg per kg.
- Only products from the library. Name them exactly.
Respect restrictions, dislikes and GI history. Sessions under 90 minutes at endurance intensity
need little or nothing during; say so rather than inventing intake."""


def _library_block(library: list[Product]) -> str:
    if not library:
        return "Product library: empty (use real food and water only)."
    rows = [
        f"  {p.name}: {p.form}, {p.carbs_g:g} g carbs, {p.sodium_mg:g} mg sodium, "
        f"{p.caffeine_mg:g} mg caffeine per serving"
        for p in library
    ]
    return "Product library:\n" + "\n".join(rows)


def _log_block(fuel_log: list[FuelLogEntry]) -> str:
    if not fuel_log:
        return "Fuel log: empty (no evidence above 60 g/h)."
    rows = [
        f"  {e.day} {e.sport} {e.duration_min} min: {e.carbs_g_per_h} g/h, {e.outcome}"
        + (f" ({e.note})" if e.note else "")
        for e in fuel_log[-10:]
    ]
    return "Fuel log (most recent last):\n" + "\n".join(rows)


def _profile_block(profile: NutritionProfile) -> str:
    return json.dumps(
        {
            "weight_kg": profile.weight_kg,
            "pattern": profile.pattern,
            "restrictions": profile.restrictions,
            "dislikes": profile.dislikes,
            "gi_issues": profile.gi_issues,
            "caffeine_mg_per_day": profile.caffeine_mg_per_day,
            "known_sweat_rate_l_per_h": profile.known_sweat_rate_l_per_h,
            "fuel_notes": profile.fuel_notes,
            "constraints": profile.constraints,
        }
    )


def render_session_prompt(
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    session: Session,
    target: DayTarget | None,
    violations: list[str] | None,
    previous: SessionFuel | None,
) -> str:
    parts = [
        f"Session: {session.day} {session.sport} '{session.title}', {session.duration_min} min, "
        f"intensity {session.intensity}, tp_workout_id {session.tp_workout_id or 'none'}."
        + (f" Planned TSS {session.planned_tss:g}." if session.planned_tss else ""),
        (
            f"Day target: {target.day_type} day, {target.total_kcal} kcal, "
            f"{target.carbs_g}/{target.protein_g}/{target.fat_g} g C/P/F, "
            f"fluid baseline {target.fluid_baseline_ml} ml."
            if target
            else "Day target: not available."
        ),
        "Athlete: " + _profile_block(profile),
        _library_block(library),
        _log_block(fuel_log),
    ]
    if violations and previous is not None:
        parts.append(
            "Your previous attempt was rejected by the validator:\n- "
            + "\n- ".join(violations)
            + "\nPrevious attempt: "
            + previous.model_dump_json()
            + "\nFix every violation and return the whole plan again."
        )
    return "\n\n".join(parts)
```

`packages/tri-nutrition/src/tri_nutrition/prompts/race.py`:
```python
"""Race-day fueling prompt: the model writes the race timeline inside Python-set bounds."""

from __future__ import annotations

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    PlanContext,
    Product,
    RaceFuelPlan,
)
from tri_nutrition.prompts.fuel import _library_block, _log_block, _profile_block

RACE_SYSTEM = f"""\
You are an endurance sports nutritionist writing the race-day fueling plan for one athlete's
triathlon. You return a RaceFuelPlan: event_date; timeline, a list of steps with offset_min from
the race start (negative before), leg (pre | swim | t1 | bike | t2 | run | post), what (plain
words), carbs_g, fluid_ml, sodium_mg, caffeine_mg for that step, and products (library names
used in the step, empty for real food or water); totals_per_h with keys bike_carbs, run_carbs,
bike_fluid, run_fluid, bike_sodium, run_sodium (per hour of that leg); contingencies (two to four
short lines: GI trouble, heat, a dropped bottle); note_text, the calendar-note text (a compact
timeline the athlete can read on race morning, plain text, no markdown).

Hard rules (a validator rejects the plan otherwise):
- The pre-race meal step must fall between {-C.PRE_RACE_WINDOW_MIN[0] // 60} and
  {-C.PRE_RACE_WINDOW_MIN[1] // 60} hours before the start.
- Per-hour carbs on the bike and run follow the same evidence tiers as training: above
  {C.FUEL_CARBS_TIER_1} g/h needs a logged ok session at or above {C.FUEL_CARBS_TIER_1}; above
  {C.FUEL_CARBS_TIER_2} needs one at or above {C.FUEL_CARBS_TIER_2}; never above
  {C.FUEL_CARBS_MAX}.
- Fluid at most {C.FUEL_FLUID_MAX_ML_PER_H} ml/h; sodium between {C.FUEL_SODIUM_MIN_MG_PER_H}
  and {C.FUEL_SODIUM_MAX_MG_PER_H} mg/h per leg.
- Total race caffeine at most {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg per kg; none if the athlete
  takes none.
- Only products from the library, named exactly.
Nitrate (beetroot) may be mentioned as an optional pre-race item; no other supplements."""


def render_race_prompt(
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    ctx: PlanContext,
    target: DayTarget | None,
    violations: list[str] | None,
    previous: RaceFuelPlan | None,
) -> str:
    parts = [
        f"Event: {ctx.event_name or ctx.goal_type or 'race'} ({ctx.goal_type or 'unknown distance'}) "
        f"on {ctx.event_date}, priority {ctx.event_priority or 'A'}.",
        (
            f"Race-day target: {target.total_kcal} kcal, {target.carbs_g} g carbs for the day "
            "(in-race intake is on top)."
            if target
            else "Race-day target: not available."
        ),
        "Athlete: " + _profile_block(profile),
        _library_block(library),
        _log_block(fuel_log),
    ]
    if violations and previous is not None:
        parts.append(
            "Your previous attempt was rejected by the validator:\n- "
            + "\n- ".join(violations)
            + "\nPrevious attempt: "
            + previous.model_dump_json()
            + "\nFix every violation and return the whole plan again."
        )
    return "\n\n".join(parts)
```

- [ ] **Step 4: Renderers in `repl.py`**

Add to `repl.py` (imports: `RaceFuelPlan`, `SessionFuel`):
```python
def render_fuel(fuels: list[SessionFuel], violations: dict[str, list[str]]) -> str:
    if not fuels:
        return "No sessions in the horizon need a fueling plan."
    lines = [f"{'day':10}  {'workout':10}  {'carbs':>6}  {'fluid':>6}  {'sodium':>6}  products"]
    for f in fuels:
        lines.append(
            f"{f.day.isoformat():10}  {f.tp_workout_id:10.10}  {f.carbs_g_per_h:>4} g/h  "
            f"{f.fluid_ml_per_h:>4} ml  {f.sodium_mg_per_h:>4} mg  {', '.join(f.products)}"
        )
        v = violations.get(f.tp_workout_id)
        if v:
            lines.append(f"    VIOLATIONS: {'; '.join(v)}")
    return "\n".join(lines)


def render_race(plan: RaceFuelPlan, violations: list[str]) -> str:
    lines = [f"Race fuel {plan.event_date}:"]
    for s in plan.timeline:
        prod = f" [{', '.join(s.products)}]" if s.products else ""
        lines.append(
            f"  {s.offset_min:>5} min  {s.leg:5}  {s.what}{prod}: {s.carbs_g} g carbs, "
            f"{s.fluid_ml} ml, {s.sodium_mg} mg Na, {s.caffeine_mg} mg caffeine"
        )
    t = plan.totals_per_h
    lines.append(
        f"  per hour: bike {t.get('bike_carbs', '-')} g/h carbs, {t.get('bike_fluid', '-')} ml, "
        f"{t.get('bike_sodium', '-')} mg Na; run {t.get('run_carbs', '-')} g/h carbs, "
        f"{t.get('run_fluid', '-')} ml, {t.get('run_sodium', '-')} mg Na"
    )
    lines += [f"  if: {c}" for c in plan.contingencies]
    if violations:
        lines.append("  VIOLATIONS: " + "; ".join(violations))
    return "\n".join(lines)
```

- [ ] **Step 5: The fuel node**

Replace `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`:
```python
"""Fuel node: one structured-output call per qualifying session and one for the race, each
validated with one retry, stored in fuel_plans, proposed as TrainingPeaks note changes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.store.base import BaseStore

from tri_nutrition import plan_loader, repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.bounds import validate_fuel, validate_race
from tri_nutrition.nutrition.models import (
    HARD_INTENSITIES,
    DayTarget,
    NutritionChange,
    PlanContext,
    RaceFuelPlan,
    Session,
    SessionFuel,
    StoredFuelPlan,
)
from tri_nutrition.nutrition.tp_calls import race_note_change, race_note_title, session_note_change
from tri_nutrition.prompts.fuel import FUEL_SYSTEM, render_session_prompt
from tri_nutrition.prompts.race import RACE_SYSTEM, render_race_prompt
from tri_nutrition.repl import render_fuel, render_race

LONG_SESSION_MIN = 75
RACE_WINDOW_DAYS = 21


def qualifies(session: Session) -> bool:
    return session.duration_min > LONG_SESSION_MIN or session.intensity in HARD_INTENSITIES


def race_due(ctx: PlanContext, today: date) -> bool:
    return ctx.event_date is not None and 0 <= (ctx.event_date - today).days <= RACE_WINDOW_DAYS


def _needs_write(stored: StoredFuelPlan | None, note_text: str) -> bool:
    return stored is None or not stored.written or stored.payload.get("note_text") != note_text


def make_fuel_node(deps: GraphDeps) -> Any:
    session_model = deps.model.with_structured_output(SessionFuel)
    race_model = deps.model.with_structured_output(RaceFuelPlan)

    async def fuel_one(prompt: str, config: RunnableConfig) -> SessionFuel:
        out = await session_model.ainvoke([SystemMessage(FUEL_SYSTEM), HumanMessage(prompt)], config=config)
        assert isinstance(out, SessionFuel)
        return out

    async def race_one(prompt: str, config: RunnableConfig) -> RaceFuelPlan:
        out = await race_model.ainvoke([SystemMessage(RACE_SYSTEM), HumanMessage(prompt)], config=config)
        assert isinstance(out, RaceFuelPlan)
        return out

    async def fuel(state: NutritionState, config: RunnableConfig, *, store: BaseStore) -> dict[str, Any]:
        profile = await S.get_profile(store)
        if profile is None or state.get("last_error"):
            return {}
        library = list(profile.tested_products)
        for p in await S.get_product_library(store):
            if p.name not in {q.name for q in library}:
                library.append(p)
        fuel_log = await S.get_fuel_log(store)
        today = deps.today()
        end = today + timedelta(days=deps.horizon_days - 1)
        with deps.connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today, deps.horizon_days)
            targets = {s.target.day: s.target for s in repo.list_targets(conn, today, end)}
            stored = repo.list_fuel_plans(conn, today, max(end, ctx.event_date or end))
        by_workout = {p.tp_workout_id: p for p in stored if p.kind == "session" and p.tp_workout_id}
        stored_race = next((p for p in stored if p.kind == "race"), None)

        changes: list[NutritionChange] = list(state.get("pending_changes") or [])
        fuels: list[SessionFuel] = []
        violations_by_id: dict[str, list[str]] = {}
        unmatched: list[str] = []
        caffeine_today: dict[date, int] = {}

        for s in [x for x in sessions if qualifies(x)]:
            target = targets.get(s.day)
            cfg = merge_configs(config, {"tags": [f"day:{s.day}", "kind:session"]})
            other = caffeine_today.get(s.day, 0)
            plan = await fuel_one(render_session_prompt(profile, library, fuel_log, s, target, None, None), cfg)
            plan = plan.model_copy(update={"tp_workout_id": s.tp_workout_id or "", "day": s.day})
            violations = validate_fuel(plan, profile, library, fuel_log, other)
            if violations:
                retry = render_session_prompt(profile, library, fuel_log, s, target, violations, plan)
                plan = (await fuel_one(retry, cfg)).model_copy(update={"tp_workout_id": s.tp_workout_id or "", "day": s.day})
                violations = validate_fuel(plan, profile, library, fuel_log, other)
            caffeine_today[s.day] = other + (plan.caffeine_mg or 0)
            with deps.connect() as conn:
                repo.upsert_fuel_plan(conn, "session", s.day, s.tp_workout_id, plan.model_dump(mode="json"), violations)
                conn.commit()
            if s.tp_workout_id is None:
                unmatched.append(f"{s.day} {s.sport} '{s.title}'")
                continue
            fuels.append(plan)
            if violations:
                violations_by_id[s.tp_workout_id] = violations
            if _needs_write(by_workout.get(s.tp_workout_id), plan.note_text):
                changes.append(session_note_change(plan))

        race_text = ""
        if race_due(ctx, today) and ctx.event_date is not None:
            cfg = merge_configs(config, {"tags": [f"day:{ctx.event_date}", "kind:race"]})
            target = targets.get(ctx.event_date)
            plan_r = await race_one(render_race_prompt(profile, library, fuel_log, ctx, target, None, None), cfg)
            rv = validate_race(plan_r, profile, library, fuel_log)
            if rv:
                plan_r = await race_one(render_race_prompt(profile, library, fuel_log, ctx, target, rv, plan_r), cfg)
                rv = validate_race(plan_r, profile, library, fuel_log)
            with deps.connect() as conn:
                repo.upsert_fuel_plan(conn, "race", ctx.event_date, None, plan_r.model_dump(mode="json"), rv)
                conn.commit()
            race_text = render_race(plan_r, rv)
            if _needs_write(stored_race, plan_r.note_text):
                title = race_note_title(ctx.event_name, ctx.goal_type, ctx.event_date)
                note_id = stored_race.tp_note_id if stored_race is not None else None
                changes.append(race_note_change(plan_r, title, note_id))

        block = [render_fuel(fuels, violations_by_id)]
        if unmatched:
            block.append(
                "Planned but not on the TrainingPeaks calendar yet (no note will be written): "
                + "; ".join(unmatched)
            )
        if race_text:
            block.append(race_text)
        summary = (state.get("pending_summary") or "") + "\n\n" + "\n".join(block)
        return {"pending_changes": changes, "pending_summary": summary.strip()}

    return fuel
```

`graph/graph.py`: import `make_fuel_node` instead of `fuel_node` and register `g.add_node("fuel", make_fuel_node(deps))`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_fuel_node.py packages/tri-nutrition/tests/test_repl.py -q`
Expected: 13 passed (6 fuel + 7 repl). If the `race_plan_json` fixture trips `validate_race` (bike 60 g/h needs no evidence; run 50; sodium 600/400; pre at -180; caffeine 100 with `caffeine_mg_per_day` 200 in `PROFILE_ARGS`), check the fixture values against `constants.py` rather than the validator.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): fuel node with session and race prompts, validation retry, fuel_plans storage"
```

---

### Task 4: Apply the TrainingPeaks operations

**Files:**
- Modify: `graph/nodes/apply.py`, `nutrition/models.py` (nothing), `repo.py` (add `mark_fuel_written_for(conn, kind, day, tp_workout_id, tp_note_id)`)
- Test: `tests/test_apply_node.py` (add cases), `tests/test_repo.py` (add one)

**Interfaces:**
- `repo.mark_fuel_written_for(conn, kind, day, tp_workout_id, tp_note_id) -> None`: marks the matching `fuel_plans` row written and stores the note id (race).
- `repo.session_note_owned(conn, workout_id) -> bool`: true when `nutrition_changes` has a `set_session_note` row for that `target_key`.
- `apply.write_change(deps, thread_id, change)`: routes by op; Garmin ops as before; `set_session_note` requires `deps.tp`, checks ownership (owned, or the current private note read through `tp_get_workout_note` is empty), raises `PermissionError` when not owned; `set_race_note` with a key requires the id in `repo.owned_note_ids`, else `PermissionError`; records the audit row and marks the fuel plan written.
- The node: Garmin changes and TP changes are applied in order; a `PermissionError` drops the change with a printed reason (spec §9) and continues; a server failure stops the batch as before; when `deps.tp` is `None` the TP changes are held pending while Garmin changes still apply (and vice versa).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repo.py`:
```python
def test_mark_fuel_written_for_and_session_ownership(ndb):
    pid = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"note_text": "x"}, [])
    repo.mark_fuel_written_for(ndb, "session", MON, "w1", None)
    assert repo.list_fuel_plans(ndb, MON, MON)[0].written is True
    rid = repo.upsert_fuel_plan(ndb, "race", MON, None, {"note_text": "r"}, [])
    repo.mark_fuel_written_for(ndb, "race", MON, None, "n-1")
    race = next(p for p in repo.list_fuel_plans(ndb, MON, MON) if p.kind == "race")
    assert race.written and race.tp_note_id == "n-1" and race.id == rid
    assert repo.session_note_owned(ndb, "w1") is False
    change = NutritionChange(op="set_session_note", target_key="w1", day=MON, payload={}, reason="")
    repo.insert_change(ndb, "nutrition", change, {"success": True})
    assert repo.session_note_owned(ndb, "w1") is True
```

Append to `tests/test_apply_node.py` (imports: `FakeTp`, `SessionFuel`, `RaceFuelPlan`, `session_fuel_json`, `race_plan_json`, `session_note_change`, `race_note_change`):
```python
def apply_graph2(make_deps, mem_store, garmin, tp):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("apply", make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=garmin, tp=tp)))
    g.add_edge(START, "apply")
    g.add_edge("apply", END)
    return g.compile(store=mem_store)


def session_change(workout_id="w1", day=MONDAY):
    return session_note_change(SessionFuel.model_validate(session_fuel_json(workout_id, day)))


async def test_session_note_written_when_note_empty_then_owned(ndb, make_deps, mem_store):
    repo.upsert_fuel_plan(ndb, "session", MONDAY, "w1", {"note_text": "n"}, [])
    tp = FakeTp()
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note", "tp_set_workout_note"]
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert repo.list_fuel_plans(ndb, MONDAY, MONDAY)[0].written is True
    assert repo.session_note_owned(ndb, "w1")
    # second write: owned, no read needed
    tp2 = FakeTp(responses={"tp_get_workout_note": {"note": "athlete wrote this"}})
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp2).ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp2.calls] == ["tp_set_workout_note"] and out["pending_changes"] == []


async def test_session_note_refused_when_athlete_note_exists(ndb, make_deps, mem_store):
    tp = FakeTp(responses={"tp_get_workout_note": {"note": "my own reminder"}})
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(state([session_change()]), CFG)
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note"]
    assert out["pending_changes"] == [] and "not agent-authored" in out["messages"][-1].content


async def test_race_note_create_records_id_then_update_owned(ndb, make_deps, mem_store):
    plan = RaceFuelPlan.model_validate(race_plan_json(MONDAY + timedelta(days=10)))
    repo.upsert_fuel_plan(ndb, "race", plan.event_date, None, plan.model_dump(mode="json"), [])
    tp = FakeTp()
    create = race_note_change(plan, "Race fuel: City Tri", None)
    await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(state([create]), CFG)
    assert tp.calls[0][0] == "tp_create_note"
    race = next(p for p in repo.list_fuel_plans(ndb, plan.event_date, plan.event_date) if p.kind == "race")
    assert race.written and race.tp_note_id == "n1"
    assert repo.owned_note_ids(ndb) == {"n1"}
    update = race_note_change(plan, "Race fuel: City Tri", "n1")
    tp2 = FakeTp()
    await apply_graph2(make_deps, mem_store, FakeGarmin(), tp2).ainvoke(state([update]), CFG)
    assert tp2.calls[0] == ("tp_update_note", {"note_id": "n1", "title": "Race fuel: City Tri", "description": plan.note_text})
    foreign = race_note_change(plan, "Race fuel: City Tri", "coach-9")
    tp3 = FakeTp()
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp3).ainvoke(state([foreign]), CFG)
    assert tp3.calls == [] and "not agent-authored" in out["messages"][-1].content


async def test_tp_down_holds_notes_but_garmin_applies(ndb, make_deps, mem_store):
    repo.upsert_targets(ndb, [target()])
    g = FakeGarmin()
    out = await apply_graph2(make_deps, mem_store, g, None).ainvoke(
        state([day_target_change(target()), session_change()]), CFG
    )
    assert len(g.calls) == 1 and [c.op for c in out["pending_changes"]] == ["set_session_note"]
    assert "TrainingPeaks server unavailable" in out["last_error"]


async def test_tp_failure_stops_batch_and_keeps_remainder(ndb, make_deps, mem_store):
    tp = FakeTp(fail_on_call=2)  # get_workout_note ok, set fails
    out = await apply_graph2(make_deps, mem_store, FakeGarmin(), tp).ainvoke(
        state([session_change("w1"), session_change("w2", MONDAY + timedelta(days=1))]), CFG
    )
    assert [c.target_key for c in out["pending_changes"]] == ["w1", "w2"]
    assert "boom" in out["last_error"]
```
Update the existing `test_non_garmin_ops_are_skipped_with_reason` to expect that a `set_race_note` with an empty payload now fails translation (`ValueError`) and is reported as `stopped`, or delete it: the plan chooses **delete it**; TP ops are real now.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_repo.py packages/tri-nutrition/tests/test_apply_node.py -q`
Expected: failures on `mark_fuel_written_for`, `session_note_owned`, and the new apply cases.

- [ ] **Step 3: Repository additions**

Append to `repo.py`:
```python
def mark_fuel_written_for(
    conn: Conn, kind: str, day: date, tp_workout_id: str | None, tp_note_id: str | None
) -> None:
    conn.execute(
        "update fuel_plans set written = true, tp_note_id = coalesce(%s::text, tp_note_id) "
        "where kind = %s and day = %s and coalesce(tp_workout_id, '') = %s",
        (tp_note_id, kind, day, tp_workout_id or ""),
    )


def session_note_owned(conn: Conn, workout_id: str) -> bool:
    row = conn.execute(
        "select 1 as x from nutrition_changes where operation = 'set_session_note' "
        "and target_key = %s limit 1",
        (workout_id,),
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: Apply node**

Replace `graph/nodes/apply.py`:
```python
"""Apply node: the only place Garmin and TrainingPeaks are written. One call per change,
recorded as it goes. `write_change` is shared with the `today` command."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.mcp.client import McpToolError
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.nutrition.tp_calls import result_note_id, to_tp_call

GARMIN_OPS = ("set_day_targets",)
TP_OPS = ("set_session_note", "set_race_note")


def _label(c: NutritionChange) -> str:
    return f"{c.op} {c.target_key or c.day}"


async def _check_ownership(deps: GraphDeps, change: NutritionChange) -> None:
    """Raise PermissionError when the change would overwrite something we did not write."""
    assert deps.tp is not None
    if change.op == "set_session_note":
        wid = str(change.payload["workout_id"])
        with deps.connect() as conn:
            if repo.session_note_owned(conn, wid):
                return
        current = await deps.tp.call_json("tp_get_workout_note", {"workout_id": wid})
        existing = (current or {}).get("note") if isinstance(current, dict) else None
        if existing and str(existing).strip():
            raise PermissionError(f"workout {wid} has a private note that is not agent-authored")
    elif change.op == "set_race_note" and change.target_key:
        with deps.connect() as conn:
            owned = repo.owned_note_ids(conn)
        if change.target_key not in owned:
            raise PermissionError(f"calendar note {change.target_key} is not agent-authored")


async def write_change(deps: GraphDeps, thread_id: str, change: NutritionChange) -> dict[str, Any]:
    """Send one change to its server, record the audit row, mark the target written.
    Raises McpToolError/ValueError on failure and PermissionError on an ownership refusal."""
    if change.op in GARMIN_OPS:
        if deps.garmin is None:
            raise McpToolError("set_nutrition_daily_settings", "Garmin server unavailable")
        if change.day != deps.today():
            raise ValueError(f"Garmin can only hold today's target; {change.day} is not today")
        name, args = to_garmin_call(change)
        result = await deps.garmin.call_json(name, args)
        payload = result if isinstance(result, dict) else {"result": result}
        with deps.connect() as conn:
            repo.insert_change(conn, thread_id, change, payload)
            repo.mark_targets_written(conn, [change.day])
            conn.commit()
        return payload
    if change.op in TP_OPS:
        if deps.tp is None:
            raise McpToolError(change.op, "TrainingPeaks server unavailable")
        await _check_ownership(deps, change)
        name, args = to_tp_call(change)
        result = await deps.tp.call_json(name, args)
        payload = result if isinstance(result, dict) else {"result": result}
        note_id = result_note_id(change, result)
        recorded = change if change.op != "set_race_note" or note_id is None else change.model_copy(update={"target_key": note_id})
        with deps.connect() as conn:
            repo.insert_change(conn, thread_id, recorded, payload)
            if change.op == "set_session_note":
                repo.mark_fuel_written_for(conn, "session", change.day, str(change.payload["workout_id"]), None)
            else:
                repo.mark_fuel_written_for(conn, "race", change.day, None, note_id)
            conn.commit()
        return payload
    raise ValueError(f"unknown operation {change.op}")


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(state: NutritionState, config: RunnableConfig, *, store: BaseStore) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        thread_id = str(config["configurable"]["thread_id"])
        applied: list[NutritionChange] = []
        skipped: list[str] = []
        held: list[NutritionChange] = []
        remaining = list(changes)
        error: str | None = None
        for change in changes:
            if (change.op in GARMIN_OPS and deps.garmin is None) or (change.op in TP_OPS and deps.tp is None):
                held.append(change)
                continue
            try:
                await write_change(deps, thread_id, change)
            except PermissionError as exc:
                skipped.append(f"{_label(change)}: {exc}; dropped")
                remaining.remove(change)
                continue
            except (McpToolError, ValueError) as exc:
                error = f"{_label(change)} failed: {exc}"
                break
            applied.append(change)
            remaining.remove(change)
        remaining = [c for c in remaining if c in held or error is not None]
        if held:
            servers = sorted({"Garmin" if c.op in GARMIN_OPS else "TrainingPeaks" for c in held})
            held_msg = f"{' and '.join(servers)} server unavailable; {len(held)} change(s) held pending."
            error = held_msg if error is None else f"{error}; {held_msg}"

        overrides = state.get("profile_overrides")
        persisted = False
        if error is None and not remaining and overrides:
            base = await S.get_profile(store)
            if base is not None:
                await S.put_profile(store, apply_overrides(base, overrides))
                persisted = True

        n_garmin = sum(1 for c in applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in applied if c.op in TP_OPS)
        lines = [f"Applied {len(applied)} of {len(changes)} changes (Garmin {n_garmin}, TrainingPeaks {n_tp})."]
        lines += [f"  skipped: {s}" for s in skipped]
        if persisted:
            lines.append(f"  profile updated: {overrides}")
        if error:
            lines.append(f"  stopped: {error}")
            lines.append(f"  {len(remaining)} change(s) still pending; they will be re-proposed next turn.")
        return {
            "pending_changes": remaining,
            "pending_summary": state.get("pending_summary") if remaining else None,
            "last_error": error,
            "review_decision": None,
            "profile_overrides": None if (error is None and not remaining) else overrides,
            "messages": [AIMessage("\n".join(lines))],
        }

    return apply
```

Note the order rule: `remaining` keeps held changes and, after a stop, everything not yet applied; a `PermissionError` never stops the batch. The existing Plan 2 tests keep passing: `test_refuses_without_garmin` now sees `held`, and the message text "unavailable" still appears in `last_error`; adjust `test_applies_today_records_row_and_marks_written`'s assertion on the message from `"applied 1 of 1"` to `"Applied 1 of 1"`.

- [ ] **Step 5: Run everything**

Run: `uv run pytest packages/tri-nutrition -q`
Expected: all pass. `daily.py` and the `today` command are unchanged (they call `write_change` with a Garmin change only).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): apply writes TrainingPeaks session and race notes with ownership checks"
```

---

### Task 5: Graph end-to-end, CLI, README

**Files:**
- Modify: `tests/test_graph.py` (one end-to-end case), `cli.py` (open TrainingPeaks in `chat`), `packages/tri-nutrition/README.md`, root `README.md`

- [ ] **Step 1: End-to-end test**

Append to `tests/test_graph.py` (imports: `FakeTp`, `seed_goal_and_plan`, `seed_workouts`, `session_json`, `session_fuel_json`, `race_plan_json`, `tool_call`):
```python
async def test_intake_to_review_with_fuel_and_approve_writes_both_servers(ndb, make_deps, mem_store):
    if ndb.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    race = MONDAY + timedelta(days=6)
    seed_goal_and_plan(ndb, MONDAY, [("race", [session_json(MONDAY, "bike", 120, "endurance", 100)])], event_date=race)
    seed_workouts(ndb, [{"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "planned_duration_sec": 7200, "title": "bike 120"}])
    model = ScriptedChatModel(
        script=[
            *intake_script(),
            tool_call("SessionFuel", session_fuel_json("w1", MONDAY)),
            tool_call("RaceFuelPlan", race_plan_json(race)),
        ]
    )
    g, tp = FakeGarmin(), FakeTp()
    graph = build_graph(make_deps(model, garmin=g, tp=tp, horizon=7), InMemorySaver(), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    ops = [c["op"] for c in out["__interrupt__"][0].value["changes"]]
    assert ops == ["set_day_targets", "set_session_note", "set_race_note"]
    assert "Race fuel" in out["__interrupt__"][0].value["summary"]
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert [c[0] for c in g.calls] == ["set_nutrition_daily_settings"]
    assert [c[0] for c in tp.calls] == ["tp_get_workout_note", "tp_set_workout_note", "tp_create_note"]
    plans = repo.list_fuel_plans(ndb, MONDAY, race)
    assert all(p.written for p in plans) and next(p for p in plans if p.kind == "race").tp_note_id == "n3"
```

- [ ] **Step 2: CLI**

In `cli.py` `_chat`: import `trainingpeaks_spec`, `TP_READ_TOOLS`, `TP_WRITE_TOOLS` are not needed for the spec (the TP server registers all its tools; the allow-list is enforced by `apply` calling by name). Open TrainingPeaks after Garmin with the same pattern:
```python
        tp = None
        if not no_live:
            try:
                tp = await asyncio.wait_for(
                    stack.enter_async_context(McpToolClient(trainingpeaks_spec(settings))),
                    timeout=GARMIN_START_TIMEOUT_S,
                )
                _out("trainingpeaks: connected (notes are written only after you approve)\n")
            except Exception as exc:
                _out(f"warning: trainingpeaks MCP server unavailable ({type(exc).__name__}: {exc}); note changes will be held pending\n")
```
and pass `tp` into `make_deps(settings, make_model(settings), garmin, tp)`. Rename the constant to `SERVER_START_TIMEOUT_S`. `/status` gains a line: `fuel plans in horizon: N (M written)` from `repo.list_fuel_plans`.

- [ ] **Step 3: READMEs**

Package README: replace the `fuel["fuel\n(Plan 3)"]` mermaid node with `fuel["fuel\nwith_structured_output(SessionFuel | RaceFuelPlan)\none call per qualifying session, validated"]`, and add under Commands: "At review the table is followed by the session fueling lines and the race timeline; `set_session_note` writes the workout's private note, `set_race_note` creates or updates the calendar note titled `Race fuel: <event> <date>`." Root README: nothing (the package line already lists `prompts`).

- [ ] **Step 4: Run everything, lint, type-check, commit**

```bash
uv run pytest -q && uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition README.md
git commit -m "feat(nutrition): chat opens TrainingPeaks; end-to-end fueling test; README"
```

---

### Task 6: Live check of the TrainingPeaks note fields (Brian) and execution notes

**What this settles:** spec §15 items 3 and 4. Whether the private workout note written by `tp_set_workout_note` shows in the TrainingPeaks calendar and mobile app well enough to be the fueling note, and that `tp_create_note` returns the id `apply` needs.

- [ ] **Step 1: Brian runs a conversation with a real horizon**

```bash
uv run tri-nutrition chat
```
Say "I'm on my feet more now, activity factor 1.4" (or any profile edit) so checkin saves and the graph regenerates. At review, `edit` the YAML down to one `set_session_note` and the `set_race_note` if present, then `approve`. Then look at the workout in the TrainingPeaks web calendar and the mobile app.

- [ ] **Step 2: Record**

Append to this plan's execution notes: whether the private note is visible (and where), the `tp_create_note` result as recorded in `nutrition_changes.result`, and whether the race note appears on the event date. If the private note is hidden, switch `tp_calls.to_tp_call` for `set_session_note` to `("tp_update_workout", {"workout_id", "description": note})` (the workout description shows everywhere) and add `tp_get_workout` to `TP_READ_TOOLS` for the ownership read (the description must be empty or agent-written), then rerun the suite.

- [ ] **Step 3: Docs to the vault, commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp packages/tri-nutrition/README.md $V/packages/tri-nutrition/readme.md
cp docs/superpowers/plans/2026-09-10-tri-nutrition-03-fueling.md $V/docs/superpowers/plans/
git add -A packages/tri-nutrition docs/superpowers/plans/2026-09-10-tri-nutrition-03-fueling.md
git commit -m "docs(nutrition): plan 3 execution notes"
```

---

## Self-review notes

- Spec §6.2 fuel: qualification rule, one call per session and one for the race within 21 days, inputs (profile, library, fuel log, session, day target), validate, one retry with the violation list, upsert with remaining violations, `set_session_note` and `set_race_note` changes, `day` and `kind` tags (Task 3). §9 "fuel validation fails twice": stored with violations, shown at review, athlete edits or rejects (Task 3 `test_retries_once_and_keeps_violations`).
- Spec §6.2 apply: TP calls, note ownership through `nutrition_changes`, one audit row per call, `written` and `tp_note_id`, batch stop on failure, held changes when a server is down, dropped with a reason on an ownership failure (Task 4).
- Spec §5.2 `fuel_plans`: kind, day, tp_workout_id, tp_note_id, payload, violations, written (Task 4 `mark_fuel_written_for`).
- Spec §8: review prints the table then the fueling lines and race timeline (`render_fuel`, `render_race` in the summary); YAML edit already covers note changes since `NutritionChange` is generic.
- Spec §11 unit list: "`NutritionChange` to server-call translation" now covers TP (Task 2); "YAML edit round trip" was Plan 2. Apply tests: ownership refusal (both note kinds), mid-batch failure, one row per call, TP down while Garmin applies.
- Spec §15 items 3 and 4: Task 6.
- Type consistency: `make_fuel_node(deps)` replaces `fuel_node` in `graph.py`; `write_change(deps, thread_id, change)` keeps its signature so `daily.py` is unchanged; `FakeTp` mirrors `FakeGarmin`; `make_deps(model, *, garmin, tp, horizon, today)` in the conftest; `repo.mark_fuel_written` (Plan 1, by id) stays for tests, `mark_fuel_written_for` is what apply uses.

## Execution notes (2026-09-10, for Plan 4 to pick up)

- Executed inline on branch `feat/tri-nutrition-03`, Tasks 1 to 5 committed (Tasks 2 and 3 together). Every module matched the plan; the only edits were line wrapping and one message-text assertion (`Applied 1 of 1`, capitalised in the new apply summary).
- **Suite:** 386 passed, 2 skipped (the two live tests). New tests: workout-id matching (2), TP call translation (3), fuel node (6), apply TP cases (5), repo helpers (1), end-to-end intake -> targets -> fuel -> review -> apply across both fakes (1), renderers (1).
- **Task 6 is Brian's:** a real conversation that writes one session note and the race note, then a look at the TrainingPeaks web calendar and mobile app to settle spec §15 item 3 (is the private workout note visible enough?) and confirm item 4 (`tp_create_note` returns `note_id`, as the pinned source shows). Record here; if the private note is hidden, switch `tp_calls.to_tp_call` to `tp_update_workout(description=...)` as the module docstring describes.
- **For Plan 4:** `FuelLogEntry` writes (`record_fuel_feedback`) go to the Store key `fuel_log` as `{"entries": [...]}`; `store.get_fuel_log` already reads it. `GARMIN_CHECKIN_TOOLS` is declared in `allowlist.py`. The checkin node in `graph/nodes/checkin.py` keeps the Plan 2 prompt and tool set; Plan 4 replaces `prompts/checkin.py` and adds `tools/checkin.py` (`record_fuel_feedback`, `propose_target_changes`). `profile_overrides` and `regenerate_from = "checkin"` are already honored by targets, review and apply.
