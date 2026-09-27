# Guardrails 01: Python-owned TSS and Validate-then-Refuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The planner computes every session's TSS from duration and intensity and scales the week to its target; a week or fuel plan that still fails validation after its one retry is stored with its violations and never proposed.

**Architecture:** The designer returns a `DesignedWeek` (no TSS). `planning/tss.py` turns it into the stored `PlannedWeek`: per-session TSS at fixed intensity factors, one clamped scale factor over the non-race sessions, durations rounded to 5 minutes, interval structures scaled with their session. `design_week` validates the scaled week; the design node and `design_next_week` store a refused week as `designed = null` plus `plan_weeks.violations` (migration 008) and leave it out of the change set. The fuel node does the same for session and race notes. Refused items stay in `pending_violations`, which now means "what was not proposed and why"; every unattended check-in exits 1 when it is non-empty.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, langchain-core 1.6, psycopg 3, pytest, LangSmith evals.

**Spec:** `docs/superpowers/specs/2026-09-24-guardrails-design.md` (sections 3, 4 and the Plan 01 half of 11). Plan 02 (consult budget, one held-review rule, `checkpointer=False`) is a separate plan.

**Branch:** `feat/guardrails-tss` off `main` @ 38d2661.

## Global Constraints

- Intensity factors, exactly: recovery 0.65, endurance 0.70, tempo 0.80, threshold 0.90, vo2 1.0, race 1.0. `session_tss = hours * IF^2 * 100`, rounded to one decimal.
- Scaling runs only when the week total is outside 10% of `target.target_tss`; the factor is clamped to `[0.75, 1.25]`; durations round to 5 minutes (a non-zero session never rounds below 5).
- Unreachable-after-clamping violation text starts exactly `total TSS <n> cannot reach target <t> by scaling`.
- Hours min: `target_hours * 0.8`, skipped when the target is a recovery week (`is_recovery`) or its phase is `recovery`, `taper` or `race`.
- Per-session sanity: no session over 6 hours (360 min); no `vo2` session over 90 minutes.
- Planning summary line for a refused week, exactly: `week <start>: not designed: <violations joined by "; ">`.
- Nutrition summary line for a refused plan, exactly: `<day> <title>: not proposed: <violations joined by "; ">`; the race uses `<event_date> race` as its label.
- `design_next_week` for a refused week returns exactly `{"week_start", "violations", "changes": []}`.
- `PROMPT_VERSION = "2"` in `tri_planning/prompts/design.py`; the eval experiment prefix defaults to `design-v2`.
- Migration file: `migrations/008_guardrails.sql`; `tri_core.db.migrate.PROBES[8]` already probes `plan_weeks.violations`, so no change to `migrate.py`.
- **Brian's database rule:** the implementer never runs `tri migrate`, `psql` DDL, or any write against `tri_analyze` or `tri_analyze_test` outside the test suite. Task 1 prints the commands for Brian and waits.
- Run `uv run ruff format` on the touched packages before each commit; some code blocks here run past the line length and the formatter wraps them.
- **Brian's dependency rule:** before the first edit that touches Pydantic, LangGraph or langchain-core APIs, look up the version in use (`uv pip show pydantic langgraph langchain-core`) in Context7. Nothing here needs an API the repo does not already use; the lookup confirms that.

## Deviations from the spec (decided while planning, 2026-09-27)

1. **`scale_to_target(week, target)` takes no `goal`.** Nothing in the algorithm reads it.
2. **The factor applies to the scalable part only:** `(target − fixed) / scalable`, where `fixed` is the TSS of race-intensity and rest sessions. The spec's `target / total` would over- or under-shoot any week that holds a race session. Rest sessions count 0 TSS.
3. **Structure steps scale by each session's actual `new / old` minutes** (after rounding), not the raw factor, so structure sums keep matching the duration.
4. **Refused items stay in `pending_violations`.** The key keeps its shape (planning: week ISO; nutrition: `tp_workout_id` or `"race"`) but now names what was *not* proposed. The review payload, the coach's proposal lines and every check-in read it from there. The existing `--yes` filters (`changes_without_violations`, `split_violating`) stay as the second layer, as the spec says.
5. **Unattended check-ins exit 1 whenever something was refused,** including a turn with nothing to review. The spec is silent; the fixes spec made a skipped violation exit 1, and a refused week that exits 0 would hide it from cron. Covers `tri-planning check-in`, `tri-nutrition check-in`, and the nutrition half of `tri-coach check-in` (the planning half already counts via `changes_without_violations`).
6. **A design turn with nothing to propose ends at the design node** (`after_design` routes to END) with the summary as an `AIMessage`, instead of the review node's "No calendar changes to review."
7. **`design_next_week` gains an optional `note` argument,** which the spec's "call `design_next_week` again with a note" needs.
8. **Nutrition's route node clears `pending_violations`** at the start of a turn that has no pending changes, so a check-in reading state after the turn sees only this turn's refusals.
9. **Eval metadata gains `prompt_version`,** as tri-nutrition, tri-coach, tri-wellness and tri-analyze already do.
10. **Spec §9's "week_start mismatch" test already exists** (`test_week_start_must_match_the_target`, from the fixes spec). Not re-added.
11. **The coach's proposal lines keep their wording** (`violations: week of <w>: …`). Rewording them to "not proposed" touches three coach tests and the coach prompt. Left for Plan 02, which changes the coach anyway.

### Existing tests this plan changes, and why

All are mechanical renames or assertions that flip because the spec changes the behaviour they pin. None is weakened.

- `tool_call("PlannedWeek", …)` becomes `tool_call("DesignedWeek", …)` in `tri-planning/tests/{test_design_node,test_design_next_week,test_graph,test_graph_adjust,test_adjust_node,test_checkpointer}.py` and `tri-coach/tests/test_graph.py`. The parser rejects a tool name that isn't the schema: `OutputParserException: Unknown tool type: 'PlannedWeek'` (checked against langchain-core 1.6.2).
- `tri_planning.testing.week_json` builds durations from the target, not TSS numbers. Its keys and signature stay the same.
- `test_design_node.py`: `test_retries_once_on_violation_and_reports_if_still_bad`, `test_a_reply_without_a_week_is_retried_once_then_reported`, `test_a_design_for_the_wrong_week_is_left_out_entirely`, `test_a_violation_retry_without_a_week_keeps_the_first_design_and_its_violations`, `test_design_week_uses_the_design_model_when_one_is_set`.
- `test_adjust_node.py::test_design_violations_become_pending_violations`, `test_graph_adjust.py::test_review_payload_carries_the_designed_weeks_violations`, `test_design_next_week.py::test_config_not_exposed_in_model_facing_schema`.
- `test_eval_run.py`: `test_render_pass_rates_lists_each_key`, `test_run_eval_designs_on_the_design_role`.
- `tri-nutrition/tests/test_fuel_node.py::test_retries_once_and_keeps_violations`, `tri-nutrition/tests/test_graph.py::test_checkin_run_yes_skips_violating_changes_and_exits_1`.

## Review Focus

- **A designed week already within 10% of target:** durations and structures come back untouched (no rounding drift), and TSS is filled in. Test: `test_a_week_inside_the_tolerance_is_not_scaled` (Task 2).
- **A week with no scalable load (empty, only rest, or only race intensity):** no `ZeroDivisionError`, and the unreachable violation when the target is above zero. Tests: `test_an_empty_week_cannot_reach_the_target`, `test_race_sessions_count_but_do_not_scale` (Task 2).
- **An interval structure with a distance step (no `duration_seconds`):** scaling leaves the structure as it was, and the validator still flags it. Test: `test_a_structure_without_step_durations_is_left_as_is` (Task 2).
- **A week designed earlier, never approved, then refused on a re-design:** `designed` becomes null and the violations are stored; a later clean design clears them. Test: `test_a_refused_design_is_stored_as_null_and_a_clean_one_clears_it` (Task 1).
- **An unattended check-in where everything was refused and nothing reached review:** exit 1 with the refusals printed, not a silent 0. Tests: `test_a_week_refused_with_nothing_to_review_exits_1` (Task 6), `test_checkin_run_exits_1_on_a_refusal_with_nothing_to_review` (Task 7).

---

### Task 1: Migration 008 and the `violations` column in the repository

**Files:**
- Create: `migrations/008_guardrails.sql`
- Modify: `packages/tri-planning/src/tri_planning/planning/models.py` (`PlanWeekRow`)
- Modify: `packages/tri-planning/src/tri_planning/repo.py` (`list_weeks`, `set_week_designed`)
- Test: `packages/tri-planning/tests/test_repo.py`

**Interfaces:**
- Consumes: the `pdb` fixture, `goal()` and `targets()` helpers already in `test_repo.py`.
- Produces:
  - `PlanWeekRow.violations: list[str]` (default `[]`)
  - `repo.set_week_designed(conn, plan_id: int, week_start: date, week: PlannedWeek | None, violations: Sequence[str] = ()) -> None`. `week=None` writes SQL null to `designed`; empty `violations` writes SQL null to `violations`.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/guardrails-tss
```

- [ ] **Step 2: Write the migration**

Create `migrations/008_guardrails.sql`:

```sql
-- 008_guardrails.sql
-- Guardrails, 2026-09-24 spec: a week whose design still fails validation after its retry is
-- not proposed. It is stored with designed = null and the validator's violations here; a clean
-- design writes null back.

alter table plan_weeks add column if not exists violations jsonb;
```

- [ ] **Step 3: Ask Brian to apply it, then wait**

Print exactly this and stop until Brian confirms:

```
Migration 008 is ready. Please run:
  uv run tri migrate --dry-run
  uv run tri migrate && uv run tri migrate --test
```

- [ ] **Step 4: Write the failing test**

Append to `packages/tri-planning/tests/test_repo.py`:

```python
def test_a_refused_design_is_stored_as_null_and_a_clean_one_clears_it(pdb):
    gid = repo.insert_goal(pdb, goal())
    pid = repo.insert_plan(pdb, gid, "generated", None, targets())
    designed = PlannedWeek(week_start=MON, sessions=[], coach_note="first")
    repo.set_week_designed(pdb, pid, MON, designed)
    assert repo.list_weeks(pdb, pid)[0].violations == []

    # a re-design of the unapproved week is refused: the old design goes, the reasons stay
    repo.set_week_designed(pdb, pid, MON, None, ["hard sessions on consecutive days"])
    first = repo.list_weeks(pdb, pid)[0]
    assert first.designed is None
    assert first.violations == ["hard sessions on consecutive days"]
    raw = pdb.execute(
        "select designed from plan_weeks where plan_id = %s and week_start = %s", (pid, MON)
    ).fetchone()
    assert raw["designed"] is None  # SQL null, not JSON null

    repo.set_week_designed(pdb, pid, MON, designed)
    first = repo.list_weeks(pdb, pid)[0]
    assert first.designed == designed and first.violations == []
    raw = pdb.execute(
        "select violations from plan_weeks where plan_id = %s and week_start = %s", (pid, MON)
    ).fetchone()
    assert raw["violations"] is None
```

- [ ] **Step 5: Run it to verify it fails**

Run: `uv run pytest packages/tri-planning/tests/test_repo.py -v -k refused`
Expected: FAIL with `TypeError: set_week_designed() takes 4 positional arguments but 5 were given` (or `AttributeError: 'PlanWeekRow' object has no attribute 'violations'`).

- [ ] **Step 6: Implement**

In `planning/models.py`, `PlanWeekRow` gains a field after `written_to_tp`:

```python
class PlanWeekRow(BaseModel):
    plan_id: int
    week_start: date
    phase: Phase
    target_tss: float | None
    target_hours: float | None
    designed: PlannedWeek | None
    written_to_tp: bool
    violations: list[str] = Field(default_factory=list)  # why the last design was refused
```

In `repo.py`, add `from collections.abc import Sequence` to the imports, then in `list_weeks` add `violations=list(r["violations"] or []),` after `written_to_tp=r["written_to_tp"],`, and replace `set_week_designed`:

```python
def set_week_designed(
    conn: Conn,
    plan_id: int,
    week_start: date,
    week: PlannedWeek | None,
    violations: Sequence[str] = (),
) -> None:
    """Store a week's design, or for a design refused by the validator, null and its
    violations. A clean design clears the violations an earlier refusal left."""
    conn.execute(
        "update plan_weeks set designed = %s, violations = %s "
        "where plan_id = %s and week_start = %s",
        (
            Jsonb(week.model_dump(mode="json")) if week is not None else None,
            Jsonb(list(violations)) if violations else None,
            plan_id,
            week_start,
        ),
    )
```

- [ ] **Step 7: Run the repo tests**

Run: `uv run pytest packages/tri-planning/tests/test_repo.py -v`
Expected: all pass. If they skip, Postgres is down: `docker compose up -d db`, rerun; they must pass, not skip.

- [ ] **Step 8: Commit**

```bash
git add migrations/008_guardrails.sql packages/tri-planning/src/tri_planning/planning/models.py packages/tri-planning/src/tri_planning/repo.py packages/tri-planning/tests/test_repo.py
git commit -m "feat(planning): migration 008 stores a refused week's violations on plan_weeks"
```

---

### Task 2: `planning/tss.py`: session TSS and scaling to the target

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/models.py` (add `DesignedSession`, `DesignedWeek`)
- Create: `packages/tri-planning/src/tri_planning/planning/tss.py`
- Test: `packages/tri-planning/tests/test_tss.py`

**Interfaces:**
- Consumes: `validate.TSS_TOLERANCE` (0.10, exists), `WeekTarget`, `PlannedSession`, `PlannedWeek`, `Intensity`, `Sport`.
- Produces:
  - `class DesignedSession(BaseModel)`: `date, sport, title, description, duration_minutes (ge=0), intensity, structure: dict | None = None`
  - `class DesignedWeek(BaseModel)`: `week_start: date, sessions: list[DesignedSession], coach_note: str`
  - `tss.INTENSITY_IF: dict[Intensity, float]`, `tss.SCALE_MIN = 0.75`, `tss.SCALE_MAX = 1.25`, `tss.ROUND_MIN = 5`
  - `tss.session_tss(duration_minutes: int, intensity: Intensity) -> float`
  - `tss.scale_to_target(week: DesignedWeek, target: WeekTarget) -> tuple[PlannedWeek, list[str]]`

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-planning/tests/test_tss.py`:

```python
from datetime import date, timedelta

from tri_planning.planning.models import DesignedSession, DesignedWeek, WeekTarget
from tri_planning.planning.tss import scale_to_target, session_tss

MON = date(2026, 9, 14)
INTERVALS = {
    "primaryIntensityMetric": "percentOfThresholdPace",
    "steps": [
        {"name": "wu", "duration_seconds": 600, "intensity_min": 60, "intensity_max": 70},
        {
            "type": "repetition",
            "reps": 4,
            "steps": [
                {"name": "on", "duration_seconds": 300, "intensity_min": 95, "intensity_max": 100},
                {"name": "off", "duration_seconds": 180, "intensity_min": 60, "intensity_max": 70},
            ],
        },
        {"name": "cd", "duration_seconds": 1080, "intensity_min": 60, "intensity_max": 70},
    ],
}


def s(day=0, minutes=60, intensity="endurance", sport="bike", structure=None) -> DesignedSession:
    return DesignedSession(
        date=MON + timedelta(days=day),
        sport=sport,
        title=f"{sport} {minutes}",
        description="",
        duration_minutes=minutes,
        intensity=intensity,
        structure=structure,
    )


def wk(*sessions) -> DesignedWeek:
    return DesignedWeek(week_start=MON, sessions=list(sessions), coach_note="note")


def tgt(tss: float) -> WeekTarget:
    return WeekTarget(week_start=MON, phase="build", target_tss=tss, target_hours=6)


def test_session_tss_is_hours_times_if_squared_times_100():
    assert session_tss(60, "threshold") == 81.0
    assert session_tss(90, "endurance") == 73.5
    assert session_tss(45, "recovery") == 31.7
    assert session_tss(30, "vo2") == 50.0
    assert session_tss(0, "race") == 0.0


def test_a_week_inside_the_tolerance_is_not_scaled():
    week = wk(s(0, 180), s(2, 60, "threshold", "run", INTERVALS))  # 147 + 81 = 228
    planned, violations = scale_to_target(week, tgt(240))
    assert violations == []
    assert [x.duration_minutes for x in planned.sessions] == [180, 60]
    assert [x.tss_planned for x in planned.sessions] == [147.0, 81.0]
    assert planned.sessions[1].structure == INTERVALS
    assert planned.week_start == MON and planned.coach_note == "note"


def test_scaling_moves_every_duration_by_one_factor_rounded_to_five_minutes():
    week = wk(s(0, 180), s(2, 60, "threshold", "run", INTERVALS))  # 228 vs 280: factor 1.228
    planned, violations = scale_to_target(week, tgt(280))
    assert violations == []
    assert [x.duration_minutes for x in planned.sessions] == [220, 75]
    assert abs(planned.total_tss - 280) <= 28
    steps = planned.sessions[1].structure["steps"]
    # the steps scale by the session's own 75 / 60, so they still sum to its duration
    assert steps[0]["duration_seconds"] == 750
    assert [x["duration_seconds"] for x in steps[1]["steps"]] == [375, 225]
    assert steps[2]["duration_seconds"] == 1350
    assert INTERVALS["steps"][0]["duration_seconds"] == 600  # the input is not mutated


def test_the_factor_is_clamped_and_a_remaining_gap_is_a_violation():
    planned, violations = scale_to_target(wk(s(0, 120), s(2, 120)), tgt(300))  # 196: 1.53 -> 1.25
    assert [x.duration_minutes for x in planned.sessions] == [150, 150]
    assert len(violations) == 1
    assert violations[0].startswith("total TSS 245 cannot reach target 300 by scaling")
    assert "add a session" in violations[0]

    planned, violations = scale_to_target(wk(s(0, 180), s(2, 60, "threshold")), tgt(150))
    assert [x.duration_minutes for x in planned.sessions] == [135, 45]  # 0.66 -> 0.75
    assert violations[0].startswith("total TSS 171 cannot reach target 150 by scaling")
    assert "remove a session" in violations[0]


def test_race_sessions_count_but_do_not_scale():
    week = wk(s(0, 60, "race", "run"), s(2, 60))  # 100 fixed + 49 scalable vs 200
    planned, violations = scale_to_target(week, tgt(200))
    assert [x.duration_minutes for x in planned.sessions] == [60, 75]
    assert planned.sessions[0].tss_planned == 100.0
    assert violations and violations[0].startswith("total TSS 161 cannot reach target 200")


def test_rest_sessions_carry_no_load_and_are_not_scaled():
    week = wk(s(0, 180), s(1, 30, "recovery", "rest"), s(2, 60, "threshold"))
    planned, _ = scale_to_target(week, tgt(280))
    assert planned.sessions[1].duration_minutes == 30 and planned.sessions[1].tss_planned == 0.0


def test_an_empty_week_cannot_reach_the_target():
    planned, violations = scale_to_target(wk(), tgt(300))
    assert planned.sessions == []
    assert violations[0].startswith("total TSS 0 cannot reach target 300 by scaling")
    assert scale_to_target(wk(), tgt(0)) == (planned, [])  # no target, nothing to reach


def test_a_structure_without_step_durations_is_left_as_is():
    swim = {"steps": [{"name": "swim", "distance_meters": 400}]}
    week = wk(s(0, 180), s(2, 60, "threshold", "swim", swim))
    planned, _ = scale_to_target(week, tgt(280))
    assert planned.sessions[1].duration_minutes == 75
    assert planned.sessions[1].structure == swim
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_tss.py -v`
Expected: collection error, `ImportError: cannot import name 'DesignedSession'`.

- [ ] **Step 3: Add the designed models**

In `planning/models.py`, add after `WeekTarget` (before `PlannedSession`):

```python
class DesignedSession(BaseModel):
    """A session as the designer returns it: no load. `tss.scale_to_target` computes the load
    and makes it a PlannedSession."""

    date: date
    sport: Sport
    title: str
    description: str
    duration_minutes: int = Field(ge=0)
    intensity: Intensity
    structure: dict[str, Any] | None = None


class DesignedWeek(BaseModel):
    week_start: date
    sessions: list[DesignedSession]
    coach_note: str
```

- [ ] **Step 4: Write `tss.py`**

Create `packages/tri-planning/src/tri_planning/planning/tss.py`:

```python
"""Session load from duration and intensity, and scaling a designed week to its target. Pure."""

from __future__ import annotations

import copy
from typing import Any

from tri_planning.planning.models import (
    DesignedSession,
    DesignedWeek,
    Intensity,
    PlannedSession,
    PlannedWeek,
    WeekTarget,
)
from tri_planning.planning.validate import TSS_TOLERANCE

# Assumed intensity factor per session intensity: TSS = hours * IF^2 * 100.
INTENSITY_IF: dict[Intensity, float] = {
    "recovery": 0.65,
    "endurance": 0.70,
    "tempo": 0.80,
    "threshold": 0.90,
    "vo2": 1.0,
    "race": 1.0,
}
SCALE_MIN, SCALE_MAX = 0.75, 1.25
ROUND_MIN = 5


def session_tss(duration_minutes: int, intensity: Intensity) -> float:
    return round(duration_minutes / 60 * INTENSITY_IF[intensity] ** 2 * 100, 1)


def _load(s: DesignedSession) -> float:
    return 0.0 if s.sport == "rest" else session_tss(s.duration_minutes, s.intensity)


def _scalable(s: DesignedSession) -> bool:
    return s.sport != "rest" and s.intensity != "race" and s.duration_minutes > 0


def _round(minutes: float) -> int:
    return max(ROUND_MIN, int(minutes / ROUND_MIN + 0.5) * ROUND_MIN)


def _scale_steps(steps: list[dict[str, Any]], ratio: float) -> None:
    for step in steps:
        if step.get("type") == "repetition":
            _scale_steps(step.get("steps", []), ratio)
        elif step.get("duration_seconds") is not None:
            step["duration_seconds"] = round(int(step["duration_seconds"]) * ratio)


def _scaled(s: DesignedSession, factor: float) -> DesignedSession:
    minutes = _round(s.duration_minutes * factor)
    structure = copy.deepcopy(s.structure)
    if structure is not None:
        # by the session's own rounded ratio, so the steps still sum to its duration
        _scale_steps(structure.get("steps", []), minutes / s.duration_minutes)
    return s.model_copy(update={"duration_minutes": minutes, "structure": structure})


def _off_target(total: float, target_tss: float) -> bool:
    return bool(target_tss) and abs(total - target_tss) > TSS_TOLERANCE * target_tss


def scale_to_target(week: DesignedWeek, target: WeekTarget) -> tuple[PlannedWeek, list[str]]:
    """The week with each session's TSS computed from its duration and intensity. When the
    total is more than TSS_TOLERANCE from the target, every scalable session (not rest, not
    race intensity) is scaled by one factor, clamped to [SCALE_MIN, SCALE_MAX] and rounded to
    ROUND_MIN minutes; an interval structure scales with its session. A total still off target
    is one violation, which asks the designer for more or fewer sessions."""
    sessions = list(week.sessions)
    goal = target.target_tss
    total = sum(_load(s) for s in sessions)
    scalable = sum(_load(s) for s in sessions if _scalable(s))
    if _off_target(total, goal) and scalable > 0:
        factor = min(SCALE_MAX, max(SCALE_MIN, (goal - (total - scalable)) / scalable))
        sessions = [_scaled(s, factor) if _scalable(s) else s for s in sessions]
    planned = PlannedWeek(
        week_start=week.week_start,
        sessions=[PlannedSession(**s.model_dump(), tss_planned=_load(s)) for s in sessions],
        coach_note=week.coach_note,
    )
    total = planned.total_tss
    if not _off_target(total, goal):
        return planned, []
    ask = (
        "add a session or raise an intensity"
        if total < goal
        else "remove a session or lower an intensity"
    )
    return planned, [
        f"total TSS {total:.0f} cannot reach target {goal:.0f} by scaling durations; {ask}"
    ]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_tss.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-planning/src/tri_planning/planning/models.py packages/tri-planning/src/tri_planning/planning/tss.py packages/tri-planning/tests/test_tss.py
git commit -m "feat(planning): tss.py computes session TSS and scales a designed week to its target"
```

---

### Task 3: Validator: hours min and per-session sanity

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/validate.py`
- Test: `packages/tri-planning/tests/test_validate.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `validate.TSS_SUM_PREFIX = "total TSS "`, `HOURS_MIN_FRACTION = 0.8`, `MAX_SESSION_MIN = 360`, `MAX_VO2_MIN = 90`. `validate.week` gains three rules; its signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-planning/tests/test_validate.py`:

```python
def test_hours_under_eighty_percent_of_the_target():
    short = week(session(0, minutes=120, tss=150), session(2, minutes=120, tss=150))  # 4 h
    out = validate.week(short, target(hours=6.0), goal())
    assert any("under 4.8" in v and "hours" in v for v in out)
    enough = week(session(0, minutes=150, tss=150), session(2, minutes=150, tss=150))  # 5 h
    assert not any("under" in v for v in validate.week(enough, target(hours=6.0), goal()))


def test_light_weeks_have_no_hours_floor():
    short = week(session(0, minutes=120, tss=150), session(2, minutes=120, tss=150))
    for light in (
        WeekTarget(week_start=MON, phase="taper", target_tss=300, target_hours=6),
        WeekTarget(week_start=MON, phase="race", target_tss=300, target_hours=6),
        WeekTarget(week_start=MON, phase="recovery", target_tss=300, target_hours=6),
        WeekTarget(week_start=MON, phase="base", target_tss=300, target_hours=6, is_recovery=True),
    ):
        assert not any("under" in v for v in validate.week(short, light, goal()))


def test_no_session_over_six_hours():
    out = validate.week(week(session(0, minutes=365, tss=300)), target(), goal())
    assert any("365 min" in v and "6-hour" in v for v in out)
    out = validate.week(week(session(0, minutes=360, tss=300)), target(), goal())
    assert not any("6-hour" in v for v in out)


def test_no_vo2_session_over_ninety_minutes():
    out = validate.week(week(session(0, minutes=95, tss=300, intensity="vo2")), target(), goal())
    assert any("vo2 for 95 min" in v for v in out)
    out = validate.week(week(session(0, minutes=90, tss=300, intensity="vo2")), target(), goal())
    assert not any("vo2 for" in v for v in out)


def test_the_tss_sum_line_starts_with_the_prefix():
    out = validate.week(week(session(0, tss=100)), target(), goal())
    assert any(v.startswith(validate.TSS_SUM_PREFIX) for v in out)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_validate.py -v`
Expected: the five new tests FAIL (`AttributeError: ... has no attribute 'TSS_SUM_PREFIX'`, and no "under"/"6-hour"/"vo2 for" lines); the existing ones pass.

- [ ] **Step 3: Implement**

In `validate.py`, below `STRUCTURE_TOLERANCE_MIN = 5` add:

```python
TSS_SUM_PREFIX = "total TSS "  # the sum rule's line; design_week swaps it for the scaling one
HOURS_MIN_FRACTION = 0.8
MAX_SESSION_MIN = 360
MAX_VO2_MIN = 90
```

Change the TSS line so it builds from the prefix:

```python
        out.append(
            f"{TSS_SUM_PREFIX}{total:.0f} is more than 10% from target {target.target_tss:.0f}"
        )
```

At the top of the `for s in planned.sessions:` loop, before the "outside the week" check, add:

```python
        if s.duration_minutes > MAX_SESSION_MIN:
            out.append(
                f"{s.date} {s.title}: {s.duration_minutes} min is over the "
                f"{MAX_SESSION_MIN // 60}-hour session limit"
            )
        if s.intensity == "vo2" and s.duration_minutes > MAX_VO2_MIN:
            out.append(f"{s.date} {s.title}: vo2 for {s.duration_minutes} min is over {MAX_VO2_MIN} min")
```

Replace the hours block at the end with:

```python
    hours = planned.total_hours
    if hours > goal.weekly_hours_max:
        out.append(f"total hours {hours:.1f} exceed weekly max {goal.weekly_hours_max:g}")
    light = target.is_recovery or target.phase in ("recovery", "taper", "race")
    floor = HOURS_MIN_FRACTION * target.target_hours
    if not light and hours < floor:
        out.append(
            f"total hours {hours:.1f} are under {floor:.1f} "
            f"(80% of the target {target.target_hours:.1f})"
        )
    return out
```

(Run `uv run ruff format` if the vo2 line is over the line length.)

- [ ] **Step 4: Run the validator tests**

Run: `uv run pytest packages/tri-planning/tests/test_validate.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/planning/validate.py packages/tri-planning/tests/test_validate.py
git commit -m "feat(planning): validator checks the hours floor, 6-hour sessions and 90-minute vo2"
```

---

### Task 4: The designer returns `DesignedWeek`; prompt v2; eval `design-v2`

This task switches the model-facing schema. All the test fixture and tool-name changes land in the same commit, because the suite cannot pass halfway through.

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/design.py` (`design_week`, new `checked_week`)
- Modify: `packages/tri-planning/src/tri_planning/prompts/design.py` (`DESIGN_SYSTEM`, `PROMPT_VERSION`, target line)
- Modify: `packages/tri-planning/src/tri_planning/testing.py` (`week_json`)
- Modify: `packages/tri-planning/src/tri_planning/evals/run.py`, `packages/tri-planning/src/tri_planning/cli.py` (`--prefix` help)
- Modify (rename `"PlannedWeek"` to `"DesignedWeek"` in `tool_call`s): `packages/tri-planning/tests/{test_design_node,test_design_next_week,test_graph,test_graph_adjust,test_adjust_node,test_checkpointer}.py`, `packages/tri-coach/tests/test_graph.py`
- Test: `packages/tri-planning/tests/test_design_node.py`, `packages/tri-planning/tests/test_eval_run.py`

**Interfaces:**
- Consumes: `tss.scale_to_target`, `tss.session_tss`, `tss.INTENSITY_IF` (Task 2); `validate.TSS_SUM_PREFIX` (Task 3).
- Produces:
  - `design.checked_week(designed: DesignedWeek, target: WeekTarget, goal: TrainingGoal) -> tuple[PlannedWeek, list[str]]`
  - `design_week(...)` keeps its signature and `(PlannedWeek, violations)` return.
  - `prompts.design.PROMPT_VERSION = "2"`.
  - `week_json(week_start, target_tss, *, hard_on_consecutive_days=False)`: same keys as before. Durations now come from the target; each session carries the matching `tss_planned`.

- [ ] **Step 1: Rewrite `week_json`**

In `packages/tri-planning/src/tri_planning/testing.py`, add `from tri_planning.planning.tss import INTENSITY_IF, ROUND_MIN, session_tss` and replace `week_json`:

```python
def week_json(
    week_start: date, target_tss: float, *, hard_on_consecutive_days: bool = False
) -> dict[str, Any]:
    """A week as the designer would return it (JSON-safe): three sessions whose durations put
    the week within a few percent of `target_tss`, so scaling leaves it alone. Each session
    also carries its `tss_planned`, so the dict validates as a PlannedWeek too; DesignedWeek
    ignores the field."""
    d2 = 3 if hard_on_consecutive_days else 2  # Thu run + Fri swim are consecutive hard days
    swim = "threshold" if hard_on_consecutive_days else "endurance"
    rows = [
        (0, "bike", "Endurance ride", "z2", "endurance", 0.4),
        (d2, "run", "Threshold run", "4x6", "threshold", 0.3),
        (4, "swim", "CSS swim", "10x100", swim, 0.3),
    ]
    sessions = []
    for day, sport, title, description, intensity, share in rows:
        per_hour = INTENSITY_IF[intensity] ** 2 * 100
        steps = int(target_tss * share / per_hour * 60 / ROUND_MIN + 0.5)  # half rounds up
        minutes = max(ROUND_MIN, steps * ROUND_MIN)
        sessions.append(
            {
                "date": (week_start + timedelta(days=day)).isoformat(),
                "sport": sport,
                "title": title,
                "description": description,
                "duration_minutes": minutes,
                "tss_planned": session_tss(minutes, intensity),
                "intensity": intensity,
            }
        )
    return {"week_start": week_start.isoformat(), "coach_note": "steady aerobic week", "sessions": sessions}
```

(Checked on 2026-09-27: for every target the planning tests and the eval dataset use, this lands within 2% of target and at or above the 80% hours floor.)

- [ ] **Step 2: Rename the scripted tool calls**

Run: `git grep -l '"PlannedWeek"' -- 'packages/*/tests/*.py' | xargs sed -i '' 's/"PlannedWeek"/"DesignedWeek"/g'`
Then: `git grep -n '"PlannedWeek"' -- packages`
Expected: no output.

- [ ] **Step 3: Write the failing tests**

In `packages/tri-planning/tests/test_design_node.py`:

Add to the imports: `from tri_planning.planning.models import DesignedWeek` (into the existing models import) and `from tri_planning.planning.tss import session_tss`, and `from tri_planning.prompts.design import PROMPT_VERSION` (into the existing prompts import).

Change the last line of `test_design_week_uses_the_design_model_when_one_is_set` to:

```python
    assert seen == [(agent, DesignedWeek), (designer, DesignedWeek)]
```

Append:

```python
async def test_the_designer_gives_no_tss_and_the_week_is_scaled_to_the_target(
    nocommit, make_deps
):
    gid, pid, targets = seed(nocommit)
    light = week_json(MONDAY, targets[0].target_tss * 0.85)
    for s in light["sessions"]:
        s["tss_planned"] = 999  # whatever the model sends, the planner computes the load
    model = ScriptedChatModel(script=[structured(light)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 1
    sessions = [c.workout for c in out["pending_changes"]]
    assert all(s.tss_planned == session_tss(s.duration_minutes, s.intensity) for s in sessions)
    total = sum(s.tss_planned for s in sessions)
    assert abs(total - targets[0].target_tss) <= 0.1 * targets[0].target_tss
    assert [s.duration_minutes for s in sessions] != [
        s["duration_minutes"] for s in light["sessions"]
    ]


def test_the_design_prompt_leaves_load_to_the_planner():
    assert PROMPT_VERSION == "2"
    assert "tss_planned" not in DESIGN_SYSTEM and "10 %" not in DESIGN_SYSTEM
    assert "computes" in DESIGN_SYSTEM and "hours" in DESIGN_SYSTEM
    assert "6 hours" in DESIGN_SYSTEM and "90 minutes" in DESIGN_SYSTEM
```

In `packages/tri-planning/tests/test_eval_run.py`, change `test_render_pass_rates_lists_each_key`'s assertion and the two captured asserts in `test_run_eval_designs_on_the_design_role`:

```python
    assert out.splitlines() == [
        "pass rate over 4 examples (prompt version 2):",
        "  validator_pass             75%",
    ]
```

```python
    assert captured["experiment_prefix"] == "design-v2"
    assert captured["metadata"] == {"prompt_version": "2", "model": "claude-opus-5", "effort": None}
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py packages/tri-planning/tests/test_eval_run.py -v`
Expected: FAIL. Every scripted design raises `OutputParserException: Unknown tool type: 'DesignedWeek'. Available tools: PlannedWeek`, `PROMPT_VERSION` fails to import, and the eval asserts fail.

- [ ] **Step 5: Switch `design_week` to `DesignedWeek`**

In `graph/nodes/design.py`, add `DesignedWeek` to the models import, and add `from tri_planning.planning.tss import scale_to_target`. Add above `design_week`:

```python
def checked_week(
    designed: DesignedWeek, target: WeekTarget, goal: TrainingGoal
) -> tuple[PlannedWeek, list[str]]:
    """The designed week scaled to its target, and its violations. When scaling cannot reach
    the target, its line (which asks for more or fewer sessions) replaces the validator's sum
    line."""
    week, scaling = scale_to_target(designed, target)
    violations = validate.week(week, target, goal)
    if scaling:
        violations = scaling + [v for v in violations if not v.startswith(validate.TSS_SUM_PREFIX)]
    return week, violations
```

Replace the body of `design_week` from `designer = ...` through `return week, violations`:

```python
    designer = structured(deps.design_model or deps.model, DesignedWeek)
    cfg = merge_configs(
        config, {"tags": [f"week_start:{target.week_start}", f"phase:{target.phase}"]}
    )

    async def one(prompt: str) -> DesignedWeek | None:
        out = await designer.ainvoke(
            [SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg
        )
        return out if isinstance(out, DesignedWeek) else None

    first = render_design_prompt(goal, target, thresholds, previous, note, None, None)
    designed = await one(first)
    if designed is None:
        designed = await one(first)  # a reply without the structured week gets one more try
    if designed is None:
        empty = PlannedWeek(week_start=target.week_start, sessions=[], coach_note=NO_WEEK)
        return empty, [NO_WEEK]
    week, violations = checked_week(designed, target, goal)
    if violations:
        retry = await one(
            render_design_prompt(goal, target, thresholds, previous, note, violations, week)
        )
        if retry is not None:
            week, violations = checked_week(retry, target, goal)
    return week, violations
```

- [ ] **Step 6: Rewrite the design prompt**

In `prompts/design.py`, add below the imports:

```python
PROMPT_VERSION = "2"  # bump when DESIGN_SYSTEM changes; names the eval experiment design-v<N>
```

Replace `DESIGN_SYSTEM`:

```python
DESIGN_SYSTEM = """\
You are a triathlon coach writing one week of sessions for one self-coached athlete. You return a
DesignedWeek: week_start, coach_note (two sentences on the week's intent), and sessions. Each
session has date (YYYY-MM-DD inside the week), sport (swim | bike | run | brick | strength | rest),
title (short, specific), description (what to do, in the athlete's language, with targets in the
athlete's zones), duration_minutes, intensity (recovery | endurance | tempo | threshold | vo2 |
race) and optionally structure.

The planner computes each session's load from its duration and intensity, then scales every
duration together (by at most a quarter) to meet the week's load target. You do not estimate
load: choose the sessions, their intensities and durations that fit the hours target and the
phase. If the planner cannot reach the target, it asks you for more or fewer sessions.

structure is TrainingPeaks' simplified format: {"primaryIntensityMetric": "percentOfFtp" for
bike, "percentOfThresholdPace" for run and swim, "percentOfThresholdHr" if no pace or power
threshold exists, "steps": [ {"name", "duration_seconds", "intensity_min", "intensity_max",
"intensityClass": "warmUp" | "active" | "rest" | "coolDown"} or {"type": "repetition", "reps",
"steps": [...]} ]}. Step durations must sum to duration_minutes within 5 minutes. Only add
structure to interval sessions; leave it out for steady endurance and swims described in text.

Hard rules (a validator rejects the week otherwise):
- No session on an unavailable day; only the day's allowed sports. Brick is allowed when the
  day lists brick, or both bike and run.
- Sessions with intensity threshold, vo2 or race are never on consecutive days.
- Total duration must not exceed the weekly hours max, and must reach 80 % of the target hours
  except in recovery, taper and race weeks.
- No session longer than 6 hours; no vo2 session longer than 90 minutes.
Do not include rest days as sessions."""
```

In `render_design_prompt`, replace the first `parts` entry:

```python
        f"Design the week starting {target.week_start} (Monday). Phase: {target.phase}{recovery}. "
        f"Target about {target.target_hours:.1f} hours; the planner scales durations to "
        f"{target.target_tss:.0f} TSS. The athlete's range is {goal.weekly_hours_min:g} to "
        f"{goal.weekly_hours_max:g} hours.",
```

- [ ] **Step 7: Name the eval by prompt version**

In `evals/run.py`, add `from tri_planning.prompts.design import PROMPT_VERSION`, change the module docstring's last sentence to "The experiment is named by PROMPT_VERSION (design-v<N>), so pass rates compare across prompt versions.", and change:

```python
def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
```

```python
        experiment_prefix=prefix or f"design-v{PROMPT_VERSION}",
        metadata={
            "prompt_version": PROMPT_VERSION,
            **eval_metadata(settings, Role.PLANNING_DESIGN, judge=False),
        },
```

In `cli.py`, change the `--prefix` help to `"Experiment name prefix (default design-v<PROMPT_VERSION>)"`.

- [ ] **Step 8: Run the planning and coach suites**

Run: `uv run pytest packages/tri-planning packages/tri-coach -q`
Expected: all pass. Two tests have outcomes that depend on refusal semantics (Task 5): `test_a_design_for_the_wrong_week_is_left_out_entirely` and `test_a_violation_retry_without_a_week_keeps_the_first_design_and_its_violations`. Both still assert today's behaviour (a flagged week is proposed), and both must still pass here. If any other test fails, read it before changing anything: a failure here means the fixture or the scaling is off, not that the test is stale.

- [ ] **Step 9: Commit**

```bash
git add packages/tri-planning packages/tri-coach/tests/test_graph.py
git commit -m "feat(planning): the designer returns durations only; prompt v2; eval design-v2"
```

---

### Task 5: The design node refuses a week that still fails

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/design.py` (`not_designed_line`, `make_design_node`)
- Modify: `packages/tri-planning/src/tri_planning/graph/graph.py` (`after_design`, docstring)
- Test: `packages/tri-planning/tests/test_design_node.py`, `packages/tri-planning/tests/test_graph.py`

**Interfaces:**
- Consumes: `repo.set_week_designed(conn, plan_id, week_start, week | None, violations)` (Task 1), `design_week` (Task 4).
- Produces:
  - `design.not_designed_line(week_start: date, violations: list[str]) -> str`, which returns `f"week {week_start}: not designed: " + "; ".join(violations)`
  - `graph.after_design(state) -> str`: `"review"` when `pending_changes`, else `END`
  - Design node output: a refused week is in `pending_violations` (week ISO to violations) and in the summary via `not_designed_line`, with no changes. When the node proposes nothing it adds `messages=[AIMessage(summary)]`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_design_node.py`, add `from tri_planning.graph.nodes.design import not_designed_line` to the design import. Replace the bodies named below.

`test_retries_once_on_violation_and_reports_if_still_bad`, second half:

```python
    model = ScriptedChatModel(script=[structured(bad), structured(bad)])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and out["pending_changes"] == []
    assert f"week {MONDAY}: not designed: " in out["pending_summary"]
    assert "consecutive" in out["pending_summary"]
```

(and in its first half, change `"VIOLATIONS" not in` to `"not designed" not in`).

`test_a_reply_without_a_week_is_retried_once_then_reported`: change `"VIOLATIONS" not in` to `"not designed" not in`, and the last line to:

```python
    assert out["pending_summary"] == not_designed_line(MONDAY, [design_node.NO_WEEK])
```

`test_a_design_for_the_wrong_week_is_left_out_entirely`:

```python
async def test_a_design_for_the_wrong_week_is_left_out_entirely(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    wrong = week_json(MONDAY + timedelta(weeks=1), targets[0].target_tss)
    model = ScriptedChatModel(script=[structured(wrong), structured(wrong)])
    out = await node_out(make_deps(model), gid, pid)
    assert any("does not match" in v for v in out["pending_violations"][MONDAY.isoformat()])
    assert out["pending_changes"] == []
```

`test_a_violation_retry_without_a_week_keeps_the_first_design_and_its_violations` (renamed):

```python
async def test_a_violation_retry_without_a_week_refuses_the_first_design(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    bad = week_json(MONDAY, targets[0].target_tss, hard_on_consecutive_days=True)
    model = ScriptedChatModel(script=[structured(bad), AIMessage(content="I can't fix that.")])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and out["pending_changes"] == []
    assert any("consecutive" in v for v in out["pending_violations"][MONDAY.isoformat()])
    week = repo.list_weeks(nocommit, pid)[0]
    assert week.designed is None and any("consecutive" in v for v in week.violations)
```

Append:

```python
async def test_a_refused_week_is_stored_not_proposed_and_the_next_week_still_is(
    nocommit, make_deps
):
    gid, pid, targets = seed(nocommit)
    bad = week_json(MONDAY, targets[0].target_tss, hard_on_consecutive_days=True)
    clean = week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)
    model = ScriptedChatModel(script=[structured(bad), structured(bad), structured(clean)])
    out = await node_out(make_deps(model, horizon=2), gid, pid)
    assert {c.design_week for c in out["pending_changes"]} == {MONDAY + timedelta(weeks=1)}
    assert "messages" not in out  # there is something to review
    first, second = repo.list_weeks(nocommit, pid)[:2]
    assert first.designed is None and any("consecutive" in v for v in first.violations)
    assert second.designed is not None and second.violations == []
    lines = out["pending_summary"].splitlines()
    assert lines[0].startswith(f"week {MONDAY}: not designed: ")
    assert lines[1].startswith(f"{MONDAY + timedelta(weeks=1)} (")


async def test_a_turn_with_every_week_refused_ends_with_the_summary_as_the_note(
    nocommit, make_deps
):
    gid, pid, targets = seed(nocommit)
    bad = week_json(MONDAY, targets[0].target_tss, hard_on_consecutive_days=True)
    model = ScriptedChatModel(script=[structured(bad), structured(bad)])
    out = await node_out(make_deps(model), gid, pid)
    assert out["pending_changes"] == []
    assert [m.content for m in out["messages"]] == [out["pending_summary"]]
```

In `packages/tri-planning/tests/test_graph.py`, add `after_design` to the graph import and append:

```python
def test_after_design_reviews_only_a_proposal():
    assert after_design({"pending_changes": [object()]}) == "review"
    assert after_design({"pending_changes": []}) == END


async def test_a_refused_design_ends_the_turn_without_a_review(nocommit, make_deps, fake_tp):
    repo.insert_goal(nocommit, TrainingGoal(**GOAL_ARGS))
    model = ScriptedChatModel(
        script=[week_call(300, hard_on_consecutive_days=True)] * 2
    )
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("continue")]}, CFG)
    assert "__interrupt__" not in out and fake_tp.calls == []
    assert "not designed" in out["messages"][-1].content
    assert (await graph.aget_state(CFG)).next == ()
```

(add `from langgraph.graph import END` to `test_graph.py`'s imports).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py packages/tri-planning/tests/test_graph.py -v`
Expected: the changed and new tests FAIL (flagged weeks still proposed; `ImportError` for `not_designed_line` / `after_design`).

- [ ] **Step 3: Implement the refusal in the node**

In `graph/nodes/design.py`, add `from langchain_core.messages import AIMessage` (next to the existing messages import) and, below `NO_WEEK`:

```python
def not_designed_line(week_start: date, violations: list[str]) -> str:
    return f"week {week_start}: not designed: " + "; ".join(violations)
```

In `make_design_node`, replace the loop body after `week, violations = await design_week(...)` through `previous = week`:

```python
            with deps.connect() as conn:
                if violations:
                    repo.set_week_designed(conn, plan_id, row.week_start, None, violations)
                else:
                    repo.set_week_designed(conn, plan_id, row.week_start, week)
                conn.commit()
            if violations:
                # still failing after the retry: stored with its reasons, never proposed
                flagged[row.week_start.isoformat()] = violations
                notes.append(not_designed_line(row.week_start, violations))
                continue
            changes.extend(session_changes(week, target))
            notes.append(
                f"{row.week_start} ({target.phase}, target {target.target_tss:.0f} TSS): "
                f"{len(week.sessions)} sessions, {week.total_tss:.0f} TSS, {week.total_hours:.1f} h"
            )
            previous = week
```

Replace the return at the end:

```python
        summary = "\n".join(notes) if notes else "No weeks to design inside the horizon."
        update: dict[str, Any] = {
            "pending_changes": changes,
            "pending_summary": summary,
            "pending_violations": flagged,
            "changes_from": "design",
            "review_decision": None,
        }
        if not changes:
            update["messages"] = [AIMessage(summary)]  # nothing to review: the turn ends here
        return update
```

Update the module docstring to: `"""Design node: one structured-output call per window week, scaled to its target, validated, retried once; a week that still fails is stored with its violations and not proposed."""`

- [ ] **Step 4: Route design to END when nothing is proposed**

In `graph/graph.py`, add:

```python
def after_design(state: PlanningState) -> str:
    return "review" if state.get("pending_changes") else END
```

Replace `g.add_edge("design", review)` with:

```python
    g.add_conditional_edges("design", after_design, {"review": review, END: END})
```

In the module docstring, change `design   -> review` to `design   -> review (changes proposed) | END (every week refused, the summary is the note)`.

- [ ] **Step 5: Run the planning suite**

Run: `uv run pytest packages/tri-planning packages/tri-coach -q`
Expected: all pass. `tri-coach/tests/test_graph.py::test_checkin_yes_leaves_out_a_designed_week_with_violations` still passes: week 1 is now refused rather than filtered, and the check-in still prints `skipping p1 week of …` from `pending_violations` and exits 1.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-planning
git commit -m "feat(planning): a week that still fails validation is stored, not proposed"
```

---

### Task 6: `design_next_week`, the adjust agent and `tri-planning check-in` under refusal

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/tools/design_next_week.py`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/adjust.py` (`changes_from_messages`, no-change branch)
- Modify: `packages/tri-planning/src/tri_planning/prompts/adjust.py` (`ADJUST_RULES`)
- Modify: `packages/tri-planning/src/tri_planning/checkin.py` (no-interrupt exit)
- Test: `packages/tri-planning/tests/{test_design_next_week,test_adjust_node,test_graph_adjust,test_adjust_prompt,test_checkin}.py`

**Interfaces:**
- Consumes: `not_designed_line` (Task 5), `repo.set_week_designed(..., None, violations)` (Task 1).
- Produces:
  - Tool `design_next_week(note: str | None = None)`. A refused week returns `{"week_start": iso, "violations": [...], "changes": []}`; a clean one returns today's shape.
  - `changes_from_messages` return shape unchanged; its summary now ends with one `not_designed_line` per refused week.
  - The adjust node's no-change branch returns `pending_violations` (refused weeks) and `pending_summary` (their lines, or None).
  - `run_checkin` returns `EXIT_ERROR` after a turn with no interrupt whose state holds `pending_violations`, and prints `check-in: week of <w> not designed: <v>` per week.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_design_next_week.py`: replace `test_config_not_exposed_in_model_facing_schema`'s last line and append two tests:

```python
    assert set(tool.args_schema.model_json_schema()["properties"]) == {"note"}
```

```python
async def test_a_refused_week_returns_its_violations_and_no_changes(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    repo.mark_weeks_written(nocommit, pid, [MONDAY])
    week1 = MONDAY + timedelta(weeks=1)
    bad = week_json(week1, targets[1].target_tss, hard_on_consecutive_days=True)
    model = ScriptedChatModel(script=[structured(bad), structured(bad)])
    tool = make_design_next_week_tool(make_deps(model, horizon=3), lambda: pid)
    out = json.loads(await tool.ainvoke({}))
    assert set(out) == {"week_start", "violations", "changes"}
    assert out["week_start"] == week1.isoformat() and out["changes"] == []
    assert any("consecutive" in v for v in out["violations"])
    stored = repo.list_weeks(nocommit, pid)[1]
    assert stored.designed is None and stored.violations == out["violations"]


async def test_a_note_reaches_the_design_prompt(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    repo.mark_weeks_written(nocommit, pid, [MONDAY])
    captured = []

    class Spy(ScriptedChatModel):
        def _generate(self, messages, *a, **k):
            captured.append(messages[-1].content)
            return super()._generate(messages, *a, **k)

    week1 = MONDAY + timedelta(weeks=1)
    model = Spy(script=[structured(week_json(week1, targets[1].target_tss))])
    tool = make_design_next_week_tool(make_deps(model, horizon=3), lambda: pid)
    await tool.ainvoke({"note": "swap the Thursday run for a swim"})
    assert "swap the Thursday run for a swim" in captured[0]
```

`packages/tri-planning/tests/test_adjust_node.py`: replace the last two asserts of `test_design_violations_become_pending_violations`:

```python
    assert out["pending_changes"] == [] and out["changes_from"] is None
    assert out["pending_summary"].startswith("week 2026-09-21: not designed: ")
```

and append:

```python
def test_changes_from_messages_names_a_refused_week_in_the_summary():
    refused = ToolMessage(
        content=json.dumps(
            {"week_start": "2026-09-21", "violations": ["hard days"], "changes": []}
        ),
        name="design_next_week",
        tool_call_id="1",
    )
    changes, summary, violations = changes_from_messages(
        [refused, design_message(week_start="2026-09-28", title="clean", call_id="2")]
    )
    assert [c.workout.title for c in changes] == ["clean"]
    assert violations == {"2026-09-21": ["hard days"]}
    assert summary.splitlines() == [
        "Designed week(s) 2026-09-28 added to the calendar proposal.",
        "week 2026-09-21: not designed: hard days",
    ]
```

`packages/tri-planning/tests/test_graph_adjust.py`: replace `test_review_payload_carries_the_designed_weeks_violations`:

```python
async def test_a_refused_week_ends_the_adjust_turn_without_a_review(nocommit, make_deps):
    _, pid = seed_active(nocommit)
    bad = week_json(MONDAY + timedelta(weeks=1), 300, hard_on_consecutive_days=True)
    model = ScriptedChatModel(
        script=[
            tool_call("design_next_week", {}),
            tool_call("DesignedWeek", bad),
            tool_call("DesignedWeek", bad),
            AIMessage(content="Next week's design broke a rule; tell me what to change."),
        ]
    )
    graph = build_graph(
        make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=1), horizon=3),
        InMemorySaver(),
    )
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert "__interrupt__" not in out
    assert list(out["pending_violations"]) == ["2026-09-21"]
    assert "consecutive" in out["pending_violations"]["2026-09-21"][0]
    assert repo.list_weeks(nocommit, pid)[1].designed is None
```

`packages/tri-planning/tests/test_adjust_prompt.py`: append:

```python
def test_rules_say_how_to_handle_a_refused_week():
    from tri_planning.prompts.adjust import ADJUST_RULES

    assert "refuse" in ADJUST_RULES and "note" in ADJUST_RULES
```

`packages/tri-planning/tests/test_checkin.py`: append:

```python
class RefusedGraph(StubGraph):
    """After its turn, the state holds a week the design refused."""

    async def aget_state(self, config):
        snap = await super().aget_state(config)
        if self.inputs:
            snap.values["pending_violations"] = {"2026-09-21": ["hard sessions on consecutive days"]}
        return snap


async def test_a_week_refused_with_nothing_to_review_exits_1():
    printed: list[str] = []
    code = await run_checkin(RefusedGraph([[]]), phase="active", yes=True, out=printed.append)
    assert code == 1
    assert (
        "check-in: week of 2026-09-21 not designed: hard sessions on consecutive days"
        in "".join(printed)
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_design_next_week.py packages/tri-planning/tests/test_adjust_node.py packages/tri-planning/tests/test_graph_adjust.py packages/tri-planning/tests/test_adjust_prompt.py packages/tri-planning/tests/test_checkin.py -v`
Expected: the new and changed tests FAIL.

- [ ] **Step 3: `design_next_week` refuses and takes a note**

In `tools/design_next_week.py`, change the signature, the docstring and the tail:

```python
    async def design_next_week(
        config: Annotated[RunnableConfig, InjectedToolArg], note: str | None = None
    ) -> str:
        """Design the next plan week that is not yet on the calendar (sessions, durations,
        structure) so at least two weeks ahead stay covered. Its sessions join the proposal
        automatically. Re-designs a week that was designed but never approved. A week whose
        design still breaks a rule after one retry is refused: you get its violations and no
        changes. `note`: what the athlete wants changed, when calling again after a refusal."""
```

```python
        week, violations = await design_week(
            deps, stored.goal, target, thresholds, previous, note, config
        )
        with deps.connect() as conn:
            if violations:
                repo.set_week_designed(conn, plan_id, row.week_start, None, violations)
            else:
                repo.set_week_designed(conn, plan_id, row.week_start, week)
            conn.commit()
        if violations:
            return json.dumps(
                {"week_start": row.week_start.isoformat(), "violations": violations, "changes": []}
            )
        changes = session_changes(week, target)
        return json.dumps(
            {
                "week_start": row.week_start.isoformat(),
                "coach_note": week.coach_note,
                "violations": [],
                "changes": [c.model_dump(mode="json") for c in changes],
            }
        )
```

- [ ] **Step 4: The adjust node reports refused weeks**

In `graph/nodes/adjust.py`, add `from tri_planning.graph.nodes.design import not_designed_line`. In `changes_from_messages`, replace everything from `designed_weeks = list(designed)` to the return:

```python
    designed_weeks = [week for week in designed if designed[week]]
    all_changes = [c for week in designed_weeks for c in designed[week]] + proposed
    if summary is None and designed_weeks:
        summary = (
            "Designed week(s) " + ", ".join(designed_weeks) + " added to the calendar proposal."
        )
    refused = [not_designed_line(date.fromisoformat(w), v) for w, v in violations.items()]
    if refused:
        summary = "\n".join([summary, *refused] if summary else refused)
    return all_changes, summary, violations
```

Add one sentence to its docstring: `A refused week (violations, no changes) adds a "not designed" line to the summary.`

Replace the no-change return in `adjust`:

```python
        # adjust is entered with either no pending changes or its own rejected proposal;
        # a turn that proposes nothing must clear that proposal so it isn't re-reviewed. A
        # refused week stays in pending_violations so check-in can report it.
        return {
            "messages": new,
            "pending_changes": [],
            "pending_summary": summary,
            "pending_violations": violations,
            "changes_from": None,
            "review_decision": None,
        }
```

- [ ] **Step 5: Tell the adjust agent what a refusal means**

In `prompts/adjust.py`, replace the `design_next_week` rule in `ADJUST_RULES`:

```
- When "Window extension needed" is yes, call design_next_week once; its sessions are added to
  the proposal automatically. Do not repeat them in propose_calendar_changes.
- design_next_week may refuse a week whose design still breaks a rule after its retry: it returns
  the violations and no changes. Tell the athlete which rules it broke. If the athlete's message
  suggests a fix, call design_next_week once more with note set to that fix; otherwise do not
  call it again this turn.
```

- [ ] **Step 6: Check-in exits 1 on a refusal with nothing to review**

In `checkin.py`, replace:

```python
    if printer.interrupt is None:
        return EXIT_OK
```

with:

```python
    if printer.interrupt is None:
        # nothing to review, but a week the design refused must not pass silently
        refused = (await graph.aget_state(cfg)).values.get("pending_violations") or {}
        for week in sorted(refused):
            out(f"check-in: week of {week} not designed: {'; '.join(refused[week])}\n")
        return EXIT_ERROR if refused else EXIT_OK
```

Update the module docstring's exit-code line 1 to: `1 model/API error, apply failure, a week not designed for validator violations, or one skipped under --yes`.

- [ ] **Step 7: Run the planning and coach suites**

Run: `uv run pytest packages/tri-planning packages/tri-coach -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-planning
git commit -m "feat(planning): design_next_week refuses a failing week; check-in exits 1 on a refusal"
```

---

### Task 7: Nutrition: a fuel plan that still fails is stored, not proposed

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/repl.py` (`not_proposed`, `checkin_run`)
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/route.py`
- Modify: `packages/tri-coach/src/tri_coach/checkin.py` (`without_violations`)
- Test: `packages/tri-nutrition/tests/test_fuel_node.py`, `packages/tri-nutrition/tests/test_graph.py`, `packages/tri-nutrition/tests/test_repl.py`, `packages/tri-coach/tests/test_checkin.py`

**Interfaces:**
- Consumes: `RACE_VIOLATIONS_KEY`, `split_violating` (exist in `tri_nutrition.repl`).
- Produces:
  - `tri_nutrition.repl.not_proposed(changes: list[NutritionChange], violations: dict[str, list[str]]) -> list[tuple[str, list[str]]]`: violation keys no change covers, in key order.
  - Fuel node: a session or race plan with violations is upserted, keyed in `pending_violations`, named in the summary as `<day> <title>: not proposed: …` (race: `<event_date> race: not proposed: …`), with no change.
  - `route_node` sets `pending_violations = {}` when the turn starts with no pending changes.
  - `checkin_run` returns 1 when anything was not proposed (with or without an interrupt), printing `not proposed <key>: <v>`.
  - `tri_coach.checkin.without_violations` adds `"<pid> <key>: not proposed: <v>"` lines for a nutrition proposal's uncovered keys.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_fuel_node.py`: replace the last three lines of `test_retries_once_and_keeps_violations` (from the `# a session plan with violations is still proposed` comment on) and rename it:

```python
async def test_a_plan_that_still_fails_is_stored_but_not_proposed(ndb, mem_store, make_deps):
```

```python
    # w2 still fails after its retry: stored with its violations, named, not proposed
    notes = [c.target_key for c in out["pending_changes"] if c.op == "set_session_note"]
    assert notes == ["w1"]
    assert list(out["pending_violations"]) == ["w2"]
    line = next(x for x in out["pending_summary"].splitlines() if "not proposed" in x)
    assert line.startswith(f"{TUE} ") and "Mystery" in line
    assert "VIOLATIONS" not in out["pending_summary"]
```

(Keep the lines above it; they still hold. Delete the old `assert "VIOLATIONS" in …` line.)

Append:

```python
async def test_a_race_plan_that_still_fails_is_stored_but_not_proposed(ndb, mem_store, make_deps):
    no_pre = race_plan_json(RACE, timeline=[race_plan_json(RACE)["timeline"][1]])
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
            tool_call("RaceFuelPlan", no_pre),
            tool_call("RaceFuelPlan", no_pre),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    out = await graph.ainvoke({"pending_changes": h.changes}, CFG)
    assert "set_race_note" not in [c.op for c in out["pending_changes"]]
    assert list(out["pending_violations"]) == ["race"]
    assert f"{RACE} race: not proposed: " in out["pending_summary"]
    race = next(p for p in repo.list_fuel_plans(ndb, MONDAY, RACE) if p.kind == "race")
    assert any("pre-race" in v for v in race.violations)
```

`packages/tri-nutrition/tests/test_graph.py`: in `test_checkin_run_yes_skips_violating_changes_and_exits_1`, replace `assert "skipped set_session_note w2" in text and "Mystery" in text` with:

```python
    assert "not proposed w2: " in text and "Mystery" in text
```

That changed test now pins the interrupt path: w2 is refused, the targets and w1's note are approved, and the run exits 1. Append a unit test for the route node (add `from tri_nutrition.graph.nodes.route import route_node` to the imports):

```python
async def test_route_starts_a_turn_without_last_turns_refusals(mem_store):
    out = await route_node({"pending_violations": {"w9": ["old"]}}, store=mem_store)
    assert out["pending_violations"] == {}
    # a change set waiting at review keeps the violations its payload shows
    held = {"pending_changes": [object()], "pending_violations": {"w9": ["old"]}}
    assert "pending_violations" not in await route_node(held, store=mem_store)
```

`packages/tri-nutrition/tests/test_repl.py`: add `from types import SimpleNamespace` and `checkin_run` to the `tri_nutrition.repl` import, then append a stub-graph test for the no-interrupt path:

```python
class _RefusedTurn:
    """A graph whose turn ends without an interrupt, leaving a refused note in state."""

    def __init__(self) -> None:
        self.turned = False

    async def astream(self, payload, config=None, **kwargs):
        self.turned = True
        return
        yield

    async def aget_state(self, config):
        values = {"pending_violations": {"w2": ["product Mystery"]}} if self.turned else {}
        return SimpleNamespace(values=values, next=())


async def test_checkin_run_exits_1_on_a_refusal_with_nothing_to_review():
    printed: list[str] = []
    code = await checkin_run(_RefusedTurn(), thread_id="n", out=printed.append, approve=True)
    assert code == 1 and "not proposed w2: product Mystery" in "".join(printed)
```

`packages/tri-coach/tests/test_checkin.py`: add `from tri_coach.checkin import without_violations` if not imported, and append:

```python
def test_without_violations_names_a_fuel_plan_that_was_not_proposed():
    payload = {
        "proposals": [
            {
                "id": "p1",
                "domain": "nutrition",
                "summary": "s",
                "changes": [
                    {
                        "op": "set_session_note",
                        "target_key": "w1",
                        "day": "2026-09-14",
                        "payload": {},
                        "reason": "r",
                    }
                ],
                "pending_violations": {"w2": ["product Mystery is not in the library"]},
            }
        ]
    }
    kept, skipped = without_violations(payload)
    assert [c.target_key for c in kept[0].changes] == ["w1"]
    assert skipped == ["p1 w2: not proposed: product Mystery is not in the library"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_fuel_node.py packages/tri-nutrition/tests/test_graph.py packages/tri-nutrition/tests/test_repl.py packages/tri-coach/tests/test_checkin.py -v`
Expected: the new and changed tests FAIL.

- [ ] **Step 3: The fuel node refuses**

In `graph/nodes/fuel.py`, add below `RACE_WINDOW_DAYS`:

```python
def not_proposed_line(label: str, violations: list[str]) -> str:
    return f"{label}: not proposed: " + "; ".join(violations)
```

In `fuel`, add `refused: list[str] = []` next to `unmatched`. Replace the loop tail after the `if s.tp_workout_id is None:` block:

```python
            if violations:
                # still failing after the retry: stored above with its reasons, never proposed
                violations_by_id[s.tp_workout_id] = violations
                refused.append(not_proposed_line(f"{s.day} {s.title}", violations))
                continue
            fuels.append(plan)
            if _needs_write(by_workout.get(s.tp_workout_id), plan.note_text):
                changes.append(session_note_change(plan))
```

Replace the race block's tail after the upsert:

```python
            if rv:
                violations_by_id[RACE_VIOLATIONS_KEY] = rv
                refused.append(not_proposed_line(f"{ctx.event_date} race", rv))
            else:
                race_text = render_race(plan_r, rv)
                if _needs_write(stored_race, plan_r.note_text):
                    title = race_note_title(ctx.event_name, ctx.goal_type, ctx.event_date)
                    note_id = stored_race.tp_note_id if stored_race is not None else None
                    changes.append(race_note_change(plan_r, title, note_id))
```

(and delete the old `if rv: violations_by_id[...] = rv` above the upsert, and the old `race_text = …` / `_needs_write` lines below it).

Replace the block assembly:

```python
        block = [render_fuel(fuels, violations_by_id)] if fuels or not refused else []
        if unmatched:
            block.append(
                "Planned but not on the TrainingPeaks calendar yet (no note will be written): "
                + "; ".join(unmatched)
            )
        if race_text:
            block.append(race_text)
        block += refused
```

Update the module docstring to: `"""Fuel node: one structured-output call per qualifying session and one for the race, each validated with one retry and stored in fuel_plans. A plan that passes is proposed as a TrainingPeaks note change; one that still fails is named in the summary and not proposed."""`

- [ ] **Step 4: `not_proposed` and the nutrition check-in**

In `tri_nutrition/repl.py`, below `split_violating`:

```python
def not_proposed(
    changes: list[NutritionChange], violations: dict[str, list[str]]
) -> list[tuple[str, list[str]]]:
    """The violation keys no change covers: plans the fuel node stored but did not propose,
    as (key, violations) in key order."""
    covered = {RACE_VIOLATIONS_KEY if c.op == "set_race_note" else c.target_key for c in changes}
    return [(k, list(v)) for k, v in sorted(violations.items()) if v and k not in covered]
```

In `checkin_run`, replace:

```python
    if printer.interrupt is None:
        return 0
```

with:

```python
    if printer.interrupt is None:
        refused = not_proposed([], (await graph.aget_state(cfg)).values.get("pending_violations") or {})
        for key, reasons in refused:
            out(f"not proposed {key}: {'; '.join(reasons)}\n")
        return 1 if refused else 0
```

and replace the tail from `changes = [...]` to the end:

```python
    changes = [NutritionChange.model_validate(c) for c in printer.interrupt.get("changes", [])]
    violations = printer.interrupt.get("violations") or {}
    clean, skipped = split_violating(changes, violations)
    refused = not_proposed(changes, violations)
    for change, reasons in skipped:
        out(f"skipped {change.op} {change.target_key or change.day}: {'; '.join(reasons)}\n")
    for key, reasons in refused:
        out(f"not proposed {key}: {'; '.join(reasons)}\n")
    resume: dict[str, Any] = {"action": "approve"}
    if skipped:
        resume = {"action": "edit", "changes": [c.model_dump(mode="json") for c in clean]}
    printer = await run_turn(graph, Command(resume=resume), thread_id, out)
    if printer.interrupt is not None:
        return 3
    return 1 if skipped or refused else 0
```

Update its docstring: `0: nothing pending, or approved in full; 1: a plan was not proposed for violations, or approved with the violating changes skipped (each printed with its violations); 3: …` (keep the rest).

- [ ] **Step 5: Each turn starts without the last turn's refusals**

Replace `route_node` in `graph/nodes/route.py`:

```python
async def route_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]:
    update: dict[str, Any] = {"has_profile": await S.get_profile(store) is not None}
    if not state.get("pending_changes"):
        # this turn's refusals only: check-in reads pending_violations after the turn
        update["pending_violations"] = {}
    return update
```

- [ ] **Step 6: The coach's check-in counts nutrition refusals**

In `tri_coach/checkin.py`, add `not_proposed` to the `from tri_nutrition.repl import split_violating` import, and in `without_violations`' nutrition branch, after the `skipped += [...]` for flagged changes:

```python
            skipped += [
                f"{p.id} {key}: not proposed: " + "; ".join(v)
                for key, v in not_proposed(cast(list[NutritionChange], p.changes), keyed)
            ]
```

- [ ] **Step 7: Run the nutrition and coach suites**

Run: `uv run pytest packages/tri-nutrition packages/tri-coach -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-nutrition packages/tri-coach
git commit -m "feat(nutrition): a fuel plan that still fails is stored, named, and not proposed"
```

---

### Task 8: README, full checks, vault copies

**Files:**
- Modify: `README.md` (check-in exit code lines)
- Modify: `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/readme.md` (the same edit)

- [ ] **Step 1: Update the check-in lines**

In `README.md`, find the three check-in lines (`git grep -n "check-in \[--yes\]" README.md`) and make each exit-1 clause read `1 on a model error, a week or note not proposed for violations, or a change --yes skipped for violations`. Apply the same edit to the vault's `readme.md`. Check first that the vault copy matches the repo's README (`diff README.md <vault>/readme.md`). If it doesn't, apply only these lines and tell Brian it had drifted.

- [ ] **Step 2: Full checks, in the Definition of Done order**

```bash
uv run pytest -q -rs
uv run ruff format --check . && uv run ruff check . && uv run mypy
(cd web && npm run lint && npm test && npm run build)
```

Expected: pytest all pass, and no `SKIPPED` except `needs --live`. Ruff and mypy are clean. The web build passes (untouched, run because the Definition of Done asks for it).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: check-in exit 1 covers a week or note not proposed for violations"
```

- [ ] **Step 4: Hand off the eval run**

Tell Brian: `uv run tri-planning eval` now names the experiment `design-v2`; compare it with `design-base-6d37af94` (74% over 23). It needs `LANGSMITH_API_KEY` and `ANTHROPIC_API_KEY` and costs model calls, so it is Brian's to run.
