# tri-web Plan 2 of 3: Today, Jobs (sync, check-in), Memory, Reset, Static Serving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the server: `GET /api/today` assembles the strip's numbers in one call; `POST /api/jobs/sync` and `POST /api/jobs/checkin` run as in-process jobs whose progress lines replay over `GET /api/jobs/{id}/events`; `GET`/`DELETE /api/coach/memory`, `POST /api/coach/reset`; `web/dist` is served from the same port when it exists.

**Architecture:** `tri_web.today.build_today(rt)` opens one connection, calls `tri_coach.context.load_context` for phase, goal, plan, this week and labs, and adds today's `workouts`, `daily_metrics`, `nutrition_targets` and `fuel_plans` rows. `tri_web.jobs.Jobs` is an in-memory registry: `start(kind, run)` creates a `Job` with a recorded event list and per-follower queues, runs `run(job)` as a task, and `events(id)` replays then follows. The sync job wraps `tri_core.sync.runner.run_sync`; the check-in job takes the runtime lock for its whole duration and wraps `tri_coach.checkin.run_checkin` with `yes=False`, so a paused review lands on the thread where `GET /api/coach/thread` already finds it. Reset deletes the thread through the graph's own checkpointer.

**Tech Stack:** as plan 1 (FastAPI 0.141, langgraph 1.2.11, pydantic 2, httpx `ASGITransport` tests). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-14-tri-web-design.md` (§5.1 `jobs`, §5.2 rows `today`, `memory`, `reset`, `jobs/*`, §6.2 Today, §6.6 jobs, §6.7 settings, §6.8 "frontend not built", §8 `test_today.py`, `test_jobs.py`, `test_routes_memory.py`). Plan 1 (`feat/tri-web-01`) must be merged first.

## Global Constraints

- Everything in plan 1's Global Constraints applies (worktree `../triathlon_agent-web-02` on `feat/tri-web-02` from `main` after plan 1 merges; DoD sequence; commit trailers; vault export; no "LangChain lesson:" docstrings).
- No new Python dependency. No edits outside `packages/tri-web` except `README.md` and `packages/tri-coach/src/tri_coach/cli.py` is **not** touched (reset goes through the graph's checkpointer, see decisions).
- Sync never takes the coach lock; check-in and reset do. A busy lock is `409 {"running": ...}` as in plan 1.
- `today()` is `rt.today()` per request, never cached.
- Every `null` state in `TodayView` is a `null` field, and the model documents what the card says for it (spec §6.2: the frontend renders the sentence).
- Tests write only through the rolled-back `nocommit` fixture; the sync test stubs `run_sync`.

### Facts verified while writing this plan (against `main` 373c558 plus plan 1)

1. `load_context(conn, store, today, pending, *, labs_enabled) -> CoachContext` with `phase`, `goal: StoredGoal | None` (`.goal.event_name`, `.goal.event_date`, `.goal.goal_type`), `plan: StoredPlan | None` (`.id`, `.start_date`, `.end_date`), `this_week: PlanWeekRow | None` (`.phase`, `.target_tss`, `.target_hours`), `actual_tss`, `actual_hours`, `targets_through`, `labs: LabSummary | None` (dataclass: `panel_id`, `drawn_on`, `lab_name`, `report_on`, `outside_optimal`, `markers`, `priorities`), `labs_enabled`, `labs_missing`. It reads `athlete_profile`, `training_goals`, `training_plans`, `plan_weeks`, `daily_metrics`, `workouts`, `nutrition_targets` and (when enabled and present) the lab tables.
2. `tri_core.db.repo.list_workouts_between(conn, start, end) -> list[dict]` (`tp_workout_id`, `workout_date`, `sport`, `title`, `completed`, `planned_duration_sec`, `planned_tss`, `actual_duration_sec`, `actual_tss`, ...); `get_sync_state(conn, source) -> SyncState | None` (`source`, `last_synced_date`, `last_run_at`, `last_status`, `last_error`); `set_sync_state(conn, source, last_synced_date, status, error)`.
3. `daily_metrics` columns: `metric_date`, `sleep_seconds`, `sleep_score`, `hrv_overnight_avg`, `resting_hr`, `body_battery_high`, `body_battery_low`, `stress_avg`, `training_readiness`, `ctl`, `atl`, `tsb`, `tss_day` (numerics come back as `Decimal`).
4. `tri_nutrition.repo.list_targets(conn, start, end) -> list[StoredDayTarget]` (`.target: DayTarget` with `day`, `day_type`, `total_kcal`, `carbs_g`, `protein_g`, `fat_g`, `fluid_baseline_ml`; `.written_to_garmin`); `upsert_targets(conn, [DayTarget])`; `list_fuel_plans(conn, start, end) -> list[StoredFuelPlan]` (`id`, `kind`, `day`, `tp_workout_id`, `payload`, `violations`, `written`); `upsert_fuel_plan(conn, kind, day, tp_workout_id, payload, violations) -> int`.
5. `tri_planning.repo.list_weeks(conn, plan_id) -> list[PlanWeekRow]`; `derive_phase(conn) -> (phase, goal_id, plan_id)`; `week_monday(today)` in `tri_planning.planning.targets`.
6. `tri_coach.testing.seed_active_plan(nocommit) -> (gid, pid)`: an active goal (`GOAL_ARGS`), a plan with three weeks from `MONDAY` (2026-09-14) at 300 TSS / 6 h, phase `build`, the first week written to TP. `tri_nutrition.testing.seed_workouts(conn, rows)` inserts `workouts` rows from dicts (`tp_workout_id`, `workout_date`, `sport`, `planned_duration_sec`, optional `title`, `planned_tss`, `completed`).
7. `tri_core.sync.runner.run_sync(settings, *, since=None, sources=..., full=False, log=print, open_tp=None, open_garmin=None) -> SyncReport` with `.ok` and `.results: list[SourceResult(source, status, rows, error)]`.
8. `tri_coach.checkin.run_checkin(graph, *, has_plan, has_profile, yes, out, thread_id) -> int` (0 ok, 1 error, 2 no plan and no profile, 3 paused or refused); `tri_coach.cli._check_in` derives `has_plan` from `repo.derive_phase(conn)[0] == "active"` and `has_profile` from `await S.get_profile(store) is not None`.
9. `tri_coach.memory`: `get_entries(store) -> list[MemoryEntry]` (`id`, `kind`, `text`, `created`, `until`), `forget_entry(store, id) -> bool`, `active(entries, today)`, `clear(store)`, `add_entry(store, kind, text, today, until=None)`.
10. A compiled LangGraph graph exposes `.checkpointer`; `InMemorySaver` and `AsyncPostgresSaver` both implement `adelete_thread(thread_id)` (`reset_thread` in `tri_coach.cli` and `test_resume.py` call it on the Postgres saver).
11. Plan 1's `Runtime` has no `jobs` field yet; `create_app(rt)` mounts nothing static; `tri_web.thread._review_payload(raw)` converts an interrupt dict or a `ChangeSet` to `ReviewPayload`.

### Decisions this plan makes where the spec is silent or its literal reading fails

- **Reset goes through `rt.graph.checkpointer.adelete_thread(rt.thread_id)` and `M.clear(rt.store)`**, not `tri_coach.cli.reset_thread` (which opens a second Postgres saver from settings; it would not touch the fake runtime's in-memory saver in tests, and the server already holds the saver). Reset takes the lock with `running = "reset"`.
- **Jobs live on `Runtime.jobs`** (a `Jobs()` default) and die with the process. A job's terminal event is recorded like its lines, so a follower that connects after the job ended gets the whole transcript and the result.
- **`POST /jobs/checkin` takes the lock before returning the id** (so a concurrent turn is refused immediately) and releases it in the job's `finally`. `POST /jobs/sync` never touches the lock.
- **The check-in result is `{code, paused, no_plan}`** (`paused = code == 3`, `no_plan = code == 2`); the transcript carries `run_checkin`'s own lines (its refusal text, the review rendering, `PAUSED_HINT`). The frontend maps `paused` to "review pending, see the gate".
- **`TodayView.readiness.is_today`** is false when the row shown is the latest earlier one, with its `date` (spec §6.2 "or the latest row with its date").
- **`TodayView.session` is `null` when there is no workout today** even if a fuel plan exists (a fuel plan without a workout is stale).
- **`TodayView.week` is `null` without a plan week**; sessions by sport still come from `workouts` and go under `week.sessions` only when `week` exists. Without a plan the card says "No plan; ask the coach to build one".
- **`GET /api/today` reports `labs_missing`** alongside `labs_enabled` so the card can say "apply migrations/005_wellness.sql" instead of "no panels".
- **Static serving:** when `settings.tri_web_dist` (relative to the working directory) has an `index.html`, `create_app` mounts it at `/assets` for the built assets and adds a catch-all `GET /{path:path}` (registered after the API routers) that returns `index.html` for any non-`/api` path, so client-side routes survive a reload. Otherwise it logs `frontend not built, API only` once.
- **Out of scope:** everything under `web/` (plan 3).

---

## File Structure

```
packages/tri-web/src/tri_web/runtime.py       modify: + jobs: Jobs field
packages/tri-web/src/tri_web/thread.py        modify: _review_payload -> review_payload (public)
packages/tri-web/src/tri_web/today.py         create: TodayView models, build_today
packages/tri-web/src/tri_web/jobs.py          create: Job, Jobs, JobEvent
packages/tri-web/src/tri_web/schemas.py       modify: + SyncIn, CheckinIn, JobOut, JobStarted, MemoryOut, ResetIn
packages/tri-web/src/tri_web/app.py           modify: include today/jobs/memory routers; static mount
packages/tri-web/src/tri_web/routes/today.py  create
packages/tri-web/src/tri_web/routes/jobs.py   create: sync, checkin, get, events
packages/tri-web/src/tri_web/routes/memory.py create: memory list, forget, reset
packages/tri-web/tests/test_today.py          create
packages/tri-web/tests/test_jobs.py           create
packages/tri-web/tests/test_routes_jobs.py    create
packages/tri-web/tests/test_routes_memory.py  create
packages/tri-web/tests/test_static.py         create
packages/tri-web/README.md                    modify: routes table, layout
README.md                                     modify: Status line
```

---

### Task 1: `TodayView` and `build_today`

**Files:**
- Create: `packages/tri-web/src/tri_web/today.py`, `packages/tri-web/src/tri_web/routes/today.py`
- Modify: `packages/tri-web/src/tri_web/thread.py` (rename `_review_payload` to `review_payload`, update its two uses), `packages/tri-web/src/tri_web/app.py` (include the router at `/api`)
- Test: `packages/tri-web/tests/test_today.py`

**Interfaces:**
- Consumes: `Runtime`, `cfg` (plan 1), `review_payload`, `ReviewPayload` (thread), `load_context`, repo readers (facts 1 to 5).
- Produces: `build_today(rt: Runtime) -> TodayView` and the models below; `GET /api/today -> TodayView`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_today.py`:

```python
"""TodayView with and without a plan, targets, metrics and labs; the pending badge."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from tri_coach.models import ChangeSet, Proposal
from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_core.db import repo as crepo
from tri_nutrition import repo as nrepo
from tri_nutrition.nutrition.models import DayTarget
from tri_nutrition.testing import seed_workouts
from tri_planning.testing import MONDAY, FakeTp
from tri_web.today import TodayView, build_today

pytestmark = pytest.mark.db

TODAY = MONDAY + timedelta(days=2)  # Wednesday 2026-09-16


def seed_day(conn, day: date) -> None:
    seed_workouts(
        conn,
        [
            {"tp_workout_id": "w1", "workout_date": day, "sport": "run", "title": "Tempo", "planned_duration_sec": 3600, "planned_tss": 60},
            {"tp_workout_id": "w0", "workout_date": day - timedelta(days=1), "sport": "bike", "planned_duration_sec": 5400, "planned_tss": 80, "completed": True},
        ],
    )
    conn.execute(
        "insert into daily_metrics (metric_date, sleep_seconds, sleep_score, hrv_overnight_avg, resting_hr, "
        "body_battery_high, training_readiness, ctl, atl, tsb) values (%s, 27000, 81, 62, 48, 92, 77, 45.2, 50.1, -4.9)",
        (day,),
    )
    nrepo.upsert_targets(
        conn,
        [DayTarget(day=day, day_type="moderate", session_kcal=600, total_kcal=2900, carbs_g=380, protein_g=150, fat_g=80, fluid_baseline_ml=2500, source="plan")],
    )
    nrepo.upsert_fuel_plan(conn, "session", day, "w1", {"carbs_g_per_h": 60, "pre": "toast"}, [])
    crepo.set_sync_state(conn, "garmin", day, "ok", None)


async def test_today_with_everything(nocommit, runtime):
    seed_active_plan(nocommit)
    seed_day(nocommit, TODAY)
    rt = runtime(today=TODAY)
    view = await build_today(rt)
    assert isinstance(view, TodayView)
    h = view.header
    assert h.today == TODAY and h.phase == "active"
    assert h.goal is not None and h.goal.event_date is not None and h.goal.days_to_go == (h.goal.event_date - TODAY).days
    assert h.week.start == MONDAY and h.week.number == 1 and h.week.of == 3
    assert [s.source for s in h.last_sync] == ["garmin"] and h.last_sync[0].status == "ok"
    assert view.session is not None
    assert [w.tp_workout_id for w in view.session.workouts] == ["w1"]
    assert view.session.workouts[0].planned_tss == 60 and view.session.workouts[0].completed is False
    assert view.session.fuel is not None and view.session.fuel.payload["carbs_g_per_h"] == 60
    r = view.readiness
    assert r is not None and r.is_today and r.date == TODAY
    assert r.sleep_hours == 7.5 and r.sleep_score == 81 and r.hrv == 62 and r.resting_hr == 48
    assert r.body_battery == 92 and r.training_readiness == 77
    assert (r.ctl, r.atl, r.tsb) == (45.2, 50.1, -4.9)
    assert view.fuel.target is not None and view.fuel.target.total_kcal == 2900 and view.fuel.target.day_type == "moderate"
    assert view.fuel.targets_through == TODAY
    w = view.week
    assert w is not None and w.phase == "build" and w.target_tss == 300 and w.target_hours == 6
    assert w.actual_hours == 0 and w.actual_tss == 0  # w0 has no actual_duration_sec; no tss_day rows
    assert {(s.sport, s.planned, s.completed) for s in w.sessions} == {("run", 1, 0), ("bike", 1, 1)}
    assert view.labs is None and view.labs_enabled is False and view.labs_missing is False
    assert view.pending is None


async def test_today_with_nothing(nocommit, runtime):
    view = await build_today(runtime(today=TODAY))
    assert view.header.phase == "intake" and view.header.goal is None
    assert view.header.week.number is None and view.header.last_sync == []
    assert view.session is None and view.readiness is None
    assert view.fuel.target is None and view.fuel.targets_through is None
    assert view.week is None and view.pending is None


async def test_readiness_falls_back_to_the_latest_earlier_row(nocommit, runtime):
    nocommit.execute(
        "insert into daily_metrics (metric_date, sleep_score, ctl) values (%s, 70, 40)",
        (TODAY - timedelta(days=2),),
    )
    view = await build_today(runtime(today=TODAY))
    r = view.readiness
    assert r is not None and r.is_today is False and r.date == TODAY - timedelta(days=2)
    assert r.sleep_score == 70 and r.ctl == 40 and r.sleep_hours is None


async def test_pending_shows_a_paused_review(nocommit, runtime):
    seed_active_plan(nocommit)
    rt = runtime(
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
        today=TODAY,
    )
    from langchain_core.messages import HumanMessage

    from tri_web.runtime import cfg

    await rt.graph.ainvoke({"messages": [HumanMessage("my knee hurts")]}, {**cfg(rt), "recursion_limit": 60})
    view = await build_today(rt)
    assert view.pending is not None and view.pending.narration == "Move it."
    assert view.pending.proposals[0]["id"] == "p1"


async def test_pending_shows_a_held_change_set(nocommit, runtime):
    rt = runtime(today=TODAY)
    held = ChangeSet(
        narration="Held.",
        proposals=[Proposal(id="p1", domain="planning", summary="s", changes=[])],
    )
    from tri_web.runtime import cfg

    await rt.graph.aupdate_state(cfg(rt), {"pending": held}, as_node="start")
    view = await build_today(rt)
    assert view.pending is not None and view.pending.narration == "Held."


def test_decimals_become_floats():
    from tri_web.today import _f

    assert _f(Decimal("45.20")) == 45.2 and _f(None) is None and _f(3) == 3.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_today.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.today'`.

- [ ] **Step 3: Make `review_payload` public**

In `packages/tri-web/src/tri_web/thread.py` rename `_review_payload` to `review_payload` (definition and both uses in `thread_snapshot`). Run `uv run pytest packages/tri-web/tests/test_thread.py -q` to confirm nothing else referenced it.

- [ ] **Step 4: Write `today.py`**

```python
"""The Today strip in one call: what load_context already knows (phase, goal, plan, this week,
labs) plus today's rows from workouts, daily_metrics, nutrition_targets and fuel_plans."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from tri_coach.context import LabSummary, load_context
from tri_coach.repl import paused_review
from tri_core.db import repo as crepo
from tri_nutrition import repo as nrepo
from tri_planning import repo as prepo
from tri_planning.planning.targets import week_monday
from tri_web.runtime import Runtime, cfg
from tri_web.thread import ReviewPayload, review_payload

SOURCES = ("trainingpeaks", "garmin")


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


class GoalOut(BaseModel):
    goal_type: str
    event_name: str | None
    event_date: date | None
    days_to_go: int | None


class WeekHeader(BaseModel):
    start: date
    number: int | None  # 1-based week of the plan; None without a plan
    of: int | None


class SyncOut(BaseModel):
    source: str
    last_synced_date: date
    last_run_at: datetime
    status: str
    error: str | None


class HeaderOut(BaseModel):
    today: date
    phase: str
    goal: GoalOut | None
    week: WeekHeader
    last_sync: list[SyncOut]


class WorkoutOut(BaseModel):
    tp_workout_id: str
    sport: str
    title: str | None
    completed: bool
    planned_duration_sec: int | None
    planned_tss: float | None
    actual_duration_sec: int | None
    actual_tss: float | None


class FuelPlanOut(BaseModel):
    id: int
    kind: str
    tp_workout_id: str | None
    payload: dict[str, Any]
    violations: list[str]
    written: bool


class SessionOut(BaseModel):
    """null: "No session planned"."""

    workouts: list[WorkoutOut]
    fuel: FuelPlanOut | None  # the plan for the first planned workout, when one is stored


class ReadinessOut(BaseModel):
    """null: "No Garmin data yet, sync first"."""

    date: date
    is_today: bool
    sleep_score: int | None
    sleep_hours: float | None
    hrv: int | None
    resting_hr: int | None
    body_battery: int | None
    training_readiness: int | None
    ctl: float | None
    atl: float | None
    tsb: float | None


class TargetOut(BaseModel):
    day_type: str
    total_kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    fluid_baseline_ml: int
    written_to_garmin: bool


class FuelOut(BaseModel):
    """target null: "No targets yet, ask the coach"."""

    target: TargetOut | None
    targets_through: date | None


class SportCount(BaseModel):
    sport: str
    planned: int
    completed: int


class WeekOut(BaseModel):
    """null: "No plan; ask the coach to build one"."""

    phase: str
    target_hours: float | None
    target_tss: float | None
    actual_hours: float
    actual_tss: float
    sessions: list[SportCount]


class LabsOut(BaseModel):
    """null with labs_enabled: "No panels stored"; labs_missing: "apply migrations/005_wellness.sql"."""

    panel_id: int
    drawn_on: date
    lab_name: str | None
    report_on: date | None
    outside_optimal: int | None
    markers: int | None
    priorities: str | None


class TodayView(BaseModel):
    header: HeaderOut
    session: SessionOut | None
    readiness: ReadinessOut | None
    fuel: FuelOut
    week: WeekOut | None
    labs: LabsOut | None
    labs_enabled: bool
    labs_missing: bool
    pending: ReviewPayload | None = Field(default=None)


def _workout(row: dict[str, Any]) -> WorkoutOut:
    return WorkoutOut(
        tp_workout_id=row["tp_workout_id"],
        sport=row["sport"],
        title=row.get("title"),
        completed=bool(row["completed"]),
        planned_duration_sec=row.get("planned_duration_sec"),
        planned_tss=_f(row.get("planned_tss")),
        actual_duration_sec=row.get("actual_duration_sec"),
        actual_tss=_f(row.get("actual_tss")),
    )


def _readiness(row: dict[str, Any], today: date) -> ReadinessOut:
    secs = row.get("sleep_seconds")
    return ReadinessOut(
        date=row["metric_date"],
        is_today=row["metric_date"] == today,
        sleep_score=row.get("sleep_score"),
        sleep_hours=round(secs / 3600, 2) if secs is not None else None,
        hrv=row.get("hrv_overnight_avg"),
        resting_hr=row.get("resting_hr"),
        body_battery=row.get("body_battery_high"),
        training_readiness=row.get("training_readiness"),
        ctl=_f(row.get("ctl")),
        atl=_f(row.get("atl")),
        tsb=_f(row.get("tsb")),
    )


def _labs(s: LabSummary | None) -> LabsOut | None:
    if s is None:
        return None
    return LabsOut(
        panel_id=s.panel_id,
        drawn_on=s.drawn_on,
        lab_name=s.lab_name,
        report_on=s.report_on,
        outside_optimal=s.outside_optimal,
        markers=s.markers,
        priorities=s.priorities,
    )


async def build_today(rt: Runtime) -> TodayView:
    today = rt.today()
    monday = week_monday(today)
    snap = await rt.graph.aget_state(cfg(rt))
    values = snap.values or {}
    paused = paused_review(snap)
    held = values.get("pending")
    labs_enabled = rt.settings.tri_athlete_sex is not None
    with rt.connect() as conn:
        ctx = await load_context(conn, rt.store, today, held, labs_enabled=labs_enabled)
        todays = crepo.list_workouts_between(conn, today, today)
        week_rows = crepo.list_workouts_between(conn, monday, monday + timedelta(days=6))
        metric = conn.execute(
            "select * from daily_metrics where metric_date <= %s order by metric_date desc limit 1",
            (today,),
        ).fetchone()
        targets = nrepo.list_targets(conn, today, today)
        fuel_plans = nrepo.list_fuel_plans(conn, today, today)
        syncs = [s for s in (crepo.get_sync_state(conn, src) for src in SOURCES) if s is not None]
        weeks = prepo.list_weeks(conn, ctx.plan.id) if ctx.plan is not None else []

    goal = None
    if ctx.goal is not None:
        g = ctx.goal.goal
        goal = GoalOut(
            goal_type=g.goal_type,
            event_name=g.event_name,
            event_date=g.event_date,
            days_to_go=(g.event_date - today).days if g.event_date else None,
        )
    number = of = None
    if ctx.plan is not None and weeks:
        number = (monday - ctx.plan.start_date).days // 7 + 1
        of = len(weeks)
    header = HeaderOut(
        today=today,
        phase=ctx.phase,
        goal=goal,
        week=WeekHeader(start=monday, number=number, of=of),
        last_sync=[
            SyncOut(
                source=s.source,
                last_synced_date=s.last_synced_date,
                last_run_at=s.last_run_at,
                status=s.last_status,
                error=s.last_error,
            )
            for s in syncs
        ],
    )

    session = None
    if todays:
        first = next((w for w in todays if not w["completed"]), todays[0])
        plan = next((p for p in fuel_plans if p.tp_workout_id == first["tp_workout_id"]), None)
        session = SessionOut(
            workouts=[_workout(w) for w in todays],
            fuel=FuelPlanOut(**plan.model_dump()) if plan is not None else None,
        )

    readiness = _readiness(metric, today) if metric is not None else None

    target = None
    if targets:
        t = targets[0]
        target = TargetOut(
            day_type=t.target.day_type,
            total_kcal=t.target.total_kcal,
            carbs_g=t.target.carbs_g,
            protein_g=t.target.protein_g,
            fat_g=t.target.fat_g,
            fluid_baseline_ml=t.target.fluid_baseline_ml,
            written_to_garmin=t.written_to_garmin,
        )
    fuel = FuelOut(target=target, targets_through=ctx.targets_through)

    week = None
    if ctx.this_week is not None:
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for w in week_rows:
            counts[w["sport"]][0] += 1
            counts[w["sport"]][1] += int(bool(w["completed"]))
        week = WeekOut(
            phase=ctx.this_week.phase,
            target_hours=ctx.this_week.target_hours,
            target_tss=ctx.this_week.target_tss,
            actual_hours=round(ctx.actual_hours, 2),
            actual_tss=round(ctx.actual_tss, 1),
            sessions=[SportCount(sport=s, planned=p, completed=c) for s, (p, c) in sorted(counts.items())],
        )

    pending = review_payload(paused) if paused is not None else review_payload(held)
    return TodayView(
        header=header,
        session=session,
        readiness=readiness,
        fuel=fuel,
        week=week,
        labs=_labs(ctx.labs),
        labs_enabled=ctx.labs_enabled,
        labs_missing=ctx.labs_missing,
        pending=pending,
    )
```

`packages/tri-web/src/tri_web/routes/today.py`:

```python
"""GET /api/today: the strip in one call."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tri_web.today import TodayView, build_today

router = APIRouter()


@router.get("/today", response_model=TodayView)
async def get_today(request: Request) -> TodayView:
    from tri_web.app import runtime_of

    return await build_today(runtime_of(request))
```

In `app.py` add `from tri_web.routes import coach, system, today` and `app.include_router(today.router, prefix="/api", tags=["today"])`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_today.py -q`
Expected: `6 passed`. `test_today_with_everything` depends on `seed_active_plan`'s goal having an `event_date` (`GOAL_ARGS` in `tri_planning.testing`); if it is `None`, assert `h.goal.days_to_go is None` instead and keep the rest.

- [ ] **Step 6: Definition of done, then commit**

```bash
git add packages/tri-web
git commit -m "feat(web): GET /api/today assembles the strip: header, session, readiness, fuel, week, labs, pending"
```

---

### Task 2: The job registry

**Files:**
- Create: `packages/tri-web/src/tri_web/jobs.py`
- Modify: `packages/tri-web/src/tri_web/runtime.py` (`jobs: Jobs = field(default_factory=Jobs)`)
- Test: `packages/tri-web/tests/test_jobs.py`

**Interfaces:**
- Produces:

```python
JobStatus = Literal["queued", "running", "done", "failed"]

@dataclass
class JobEvent:
    name: str            # "line" | "done" | "error"
    data: dict[str, Any]

@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[JobEvent]                       # everything emitted, in order
    task: asyncio.Task[None] | None = None
    def line(self, text: str) -> None            # records and fans out a "line" event
    @property
    def finished(self) -> bool

Run = Callable[[Job], Awaitable[dict[str, Any]]]

class Jobs:
    def start(self, kind: str, run: Run) -> Job
    def get(self, job_id: str) -> Job | None
    def events(self, job_id: str) -> AsyncIterator[JobEvent]   # replay, then follow until done/error
```

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_jobs.py`:

```python
"""Replay then follow; a failing job ends with error; two followers see the same events."""

import asyncio

from tri_web.jobs import Job, JobEvent, Jobs


async def collect(jobs: Jobs, job_id: str) -> list[JobEvent]:
    return [ev async for ev in jobs.events(job_id)]


async def test_a_job_records_lines_and_ends_with_done():
    jobs = Jobs()
    gate = asyncio.Event()

    async def run(job: Job) -> dict:
        job.line("one")
        await gate.wait()
        job.line("two")
        return {"rows": 2}

    job = jobs.start("sync", run)
    assert job.kind == "sync" and jobs.get(job.id) is job and len(job.id) == 8
    await asyncio.sleep(0)  # let the task start
    assert job.status == "running" and [e.data["text"] for e in job.events] == ["one"]
    follower = asyncio.create_task(collect(jobs, job.id))
    gate.set()
    events = await follower
    assert [(e.name, e.data) for e in events] == [
        ("line", {"text": "one"}),
        ("line", {"text": "two"}),
        ("done", {"result": {"rows": 2}}),
    ]
    assert job.status == "done" and job.result == {"rows": 2} and job.finished


async def test_a_late_follower_gets_the_whole_transcript():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.line("a")
        return {}

    job = jobs.start("sync", run)
    assert job.task is not None
    await job.task
    events = await collect(jobs, job.id)
    assert [e.name for e in events] == ["line", "done"]


async def test_a_failing_job_ends_with_error():
    jobs = Jobs()

    async def run(job: Job) -> dict:
        job.line("starting")
        raise RuntimeError("garmin down")

    job = jobs.start("sync", run)
    events = await collect(jobs, job.id)
    assert events[-1] == JobEvent("error", {"message": "RuntimeError: garmin down"})
    assert job.status == "failed" and job.error == "RuntimeError: garmin down"


async def test_unknown_job_yields_nothing():
    assert await collect(Jobs(), "nope") == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_jobs.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_web.jobs'`.

- [ ] **Step 3: Write `jobs.py`**

```python
"""In-memory jobs (sync, check-in) with a recorded transcript: a follower that connects late, or
reconnects after a reload, replays what was emitted and then follows live. Jobs die with the
process; that is fine for one athlete on one machine."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class JobEvent:
    name: str
    data: dict[str, Any]


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[JobEvent] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    _followers: list[asyncio.Queue[JobEvent | None]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed")

    def emit(self, name: str, data: dict[str, Any]) -> None:
        ev = JobEvent(name, data)
        self.events.append(ev)
        for q in self._followers:
            q.put_nowait(ev)

    def line(self, text: str) -> None:
        self.emit("line", {"text": text.rstrip("\n")})

    def _close(self) -> None:
        for q in self._followers:
            q.put_nowait(None)


Run = Callable[[Job], Awaitable[dict[str, Any]]]


class Jobs:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def start(self, kind: str, run: Run) -> Job:
        job = Job(id=secrets.token_hex(4), kind=kind)
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, run))
        return job

    async def _run(self, job: Job, run: Run) -> None:
        job.status = "running"
        try:
            job.result = await run(job)
            job.status = "done"
            job.emit("done", {"result": job.result})
        except Exception as exc:  # noqa: BLE001 - the job's failure is its result
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
            job.emit("error", {"message": job.error})
        finally:
            job._close()

    async def events(self, job_id: str) -> AsyncIterator[JobEvent]:
        job = self._jobs.get(job_id)
        if job is None:
            return
        queue: asyncio.Queue[JobEvent | None] = asyncio.Queue()
        job._followers.append(queue)  # registered before the snapshot: nothing can slip between
        recorded = list(job.events)
        try:
            for ev in recorded:
                yield ev
            if job.finished:
                return
            while (ev := await queue.get()) is not None:
                yield ev
        finally:
            job._followers.remove(queue)
```

Why replay is exact: `_followers.append` and `list(job.events)` run with no `await` between them, so an event emitted before the append is in `recorded` only and one emitted after is in the queue only. If the job finished before the follower arrived, `recorded` ends with `done` or `error` and the generator returns.

Then in `runtime.py` add `from tri_web.jobs import Jobs` and the field `jobs: Jobs = field(default_factory=Jobs)` after `turn_task`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_jobs.py packages/tri-web/tests/test_runtime.py -q`
Expected: all pass.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/jobs.py packages/tri-web/src/tri_web/runtime.py packages/tri-web/tests/test_jobs.py
git commit -m "feat(web): job registry with a replayable transcript; Runtime.jobs"
```

---

### Task 3: Job routes: sync, check-in, status, events

**Files:**
- Create: `packages/tri-web/src/tri_web/routes/jobs.py`
- Modify: `packages/tri-web/src/tri_web/schemas.py` (+ `SyncIn`, `CheckinIn`, `JobStarted`, `JobOut`), `packages/tri-web/src/tri_web/app.py` (include at `/api/jobs`)
- Test: `packages/tri-web/tests/test_routes_jobs.py`

**Interfaces:**
- Consumes: `Jobs`, `Job` (Task 2); `Busy`, `format_sse` (plan 1); `run_sync`, `run_checkin`, `derive_phase`, `get_profile` (facts 7, 8).
- Produces: `POST /api/jobs/sync {since?, full?} -> {id}`; `POST /api/jobs/checkin {sync} -> {id}` (409 busy); `GET /api/jobs/{id} -> JobOut`; `GET /api/jobs/{id}/events` SSE `line`, then `done` or `error`. Module-level `run_sync` and `run_checkin` names in `routes/jobs.py` so tests can monkeypatch them.

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_routes_jobs.py`:

```python
"""Sync and check-in as jobs: id now, transcript over SSE, result at the end; check-in holds the
coach lock and a paused check-in leaves the review on the thread."""

import pytest
from langchain_core.messages import AIMessage

from tri_coach.testing import consult, move_call, propose, seed_active_plan
from tri_core.sync.runner import SourceResult, SyncReport
from tri_planning.testing import FakeTp

from .conftest import parse_sse

pytestmark = pytest.mark.db


async def fake_sync(settings, *, since=None, full=False, log=print, **kw):
    log(f"== garmin: {'full' if full else 'incremental'} since {since}")
    return SyncReport(results=[SourceResult("garmin", "ok", 3), SourceResult("trainingpeaks", "error", 0, "boom")])


async def test_sync_job_streams_its_lines_and_result(runtime, client, monkeypatch):
    monkeypatch.setattr("tri_web.routes.jobs.run_sync", fake_sync)
    rt = runtime()
    async with client(rt) as c:
        r = await c.post("/api/jobs/sync", json={"since": "2026-09-01", "full": True})
        assert r.status_code == 200
        job_id = r.json()["id"]
        assert rt.jobs.get(job_id) is not None
        assert not rt.lock.locked()  # sync never takes the coach lock
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
        assert events[0] == ("line", {"text": "== garmin: full since 2026-09-01"})
        assert events[-1][0] == "done"
        assert events[-1][1]["result"] == {
            "ok": False,
            "results": [
                {"source": "garmin", "status": "ok", "rows": 3, "error": None},
                {"source": "trainingpeaks", "status": "error", "rows": 0, "error": "boom"},
            ],
        }
        status = (await c.get(f"/api/jobs/{job_id}")).json()
        assert status["status"] == "done" and status["kind"] == "sync" and status["result"]["ok"] is False
        assert (await c.get("/api/jobs/nope")).status_code == 404


async def test_checkin_job_runs_the_coach_and_reports_the_code(runtime, client):
    rt = runtime(coach=[AIMessage(content="Clean week.")])
    async with client(rt) as c:
        r = await c.post("/api/jobs/checkin", json={"sync": False})
        job_id = r.json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert any("Clean week." in d.get("text", "") for n, d in events if n == "line")
    assert events[-1] == ("done", {"result": {"code": 0, "paused": False, "no_plan": False}})
    assert not rt.lock.locked() and rt.running is None


async def test_checkin_that_proposes_pauses_on_the_thread(nocommit, runtime, client):
    seed_active_plan(nocommit)
    rt = runtime(
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
        assert events[-1][1]["result"]["paused"] is True
        thread = (await c.get("/api/coach/thread")).json()
    assert thread["paused"] is not None and thread["paused"]["proposals"][0]["id"] == "p1"


async def test_checkin_without_plan_or_profile_is_code_2(runtime, client):
    rt = runtime()
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert events[-1][1]["result"] == {"code": 2, "paused": False, "no_plan": True}
    assert any("no active plan" in d.get("text", "") for _, d in events)


async def test_checkin_is_409_while_a_turn_runs_and_holds_the_lock_while_it_runs(runtime, client, monkeypatch):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "turn"
    try:
        async with client(rt) as c:
            r = await c.post("/api/jobs/checkin", json={"sync": False})
            assert r.status_code == 409 and r.json() == {"running": "turn"}
    finally:
        rt.lock.release()
        rt.running = None
    # and a running check-in refuses a turn
    import asyncio

    gate = asyncio.Event()

    async def slow_checkin(graph, *, has_plan, has_profile, yes, out, thread_id="coach"):
        out("waiting\n")
        await gate.wait()
        return 0

    monkeypatch.setattr("tri_web.routes.jobs.run_checkin", slow_checkin)
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": False})).json()["id"]
        await asyncio.sleep(0)
        assert rt.lock.locked() and rt.running == "checkin"
        r = await c.post("/api/coach/turns", json={"text": "hi"})
        assert r.status_code == 409 and r.json() == {"running": "checkin"}
        gate.set()
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert events[-1][0] == "done" and not rt.lock.locked()


async def test_checkin_syncs_first_when_asked(runtime, client, monkeypatch):
    calls = []

    async def fake_sync(settings, *, log=print, **kw):
        calls.append(kw)
        log("== synced")
        return SyncReport(results=[SourceResult("garmin", "ok", 1)])

    monkeypatch.setattr("tri_web.routes.jobs.run_sync", fake_sync)
    rt = runtime(coach=[AIMessage(content="Clean week.")])
    async with client(rt) as c:
        job_id = (await c.post("/api/jobs/checkin", json={"sync": True})).json()["id"]
        events = parse_sse((await c.get(f"/api/jobs/{job_id}/events")).text)
    assert calls == [{}] and events[0] == ("line", {"text": "== synced"})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_routes_jobs.py -q`
Expected: `404` assertions fail (no routes yet) or `AttributeError: module 'tri_web.routes' has no attribute 'jobs'` from the monkeypatch.

- [ ] **Step 3: Add the schemas**

Append to `packages/tri-web/src/tri_web/schemas.py`:

```python
from datetime import date  # add to the imports at the top


class SyncIn(BaseModel):
    since: date | None = None
    full: bool = False


class CheckinIn(BaseModel):
    sync: bool = True


class JobStarted(BaseModel):
    id: str


class JobOut(BaseModel):
    id: str
    kind: str
    status: Literal["queued", "running", "done", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None
```

- [ ] **Step 4: Write `routes/jobs.py`**

```python
"""Sync and check-in as jobs. Sync never takes the coach lock (the graph reads the tables per
turn). Check-in takes it for its whole duration and runs the CLI's check-in with yes=False, so a
proposed change set pauses on the thread where GET /coach/thread finds it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from tri_coach.checkin import run_checkin
from tri_core.sync.runner import run_sync
from tri_nutrition import store as S
from tri_planning import repo as prepo
from tri_web.events import Busy, format_sse
from tri_web.jobs import Job, Jobs
from tri_web.runtime import Runtime
from tri_web.schemas import CheckinIn, JobOut, JobStarted, SyncIn

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


async def _sync(rt: Runtime, job: Job, *, since: Any = None, full: bool = False) -> dict[str, Any]:
    report = await run_sync(rt.settings, since=since, full=full, log=job.line)
    return {"ok": report.ok, "results": [asdict(r) for r in report.results]}


@router.post("/sync", response_model=JobStarted)
async def post_sync(body: SyncIn, request: Request) -> JobStarted:
    rt = _runtime(request)

    async def run(job: Job) -> dict[str, Any]:
        return await _sync(rt, job, since=body.since, full=body.full)

    return JobStarted(id=rt.jobs.start("sync", run).id)


@router.post("/checkin", response_model=JobStarted)
async def post_checkin(body: CheckinIn, request: Request) -> JobStarted:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await rt.lock.acquire()
    rt.running = "checkin"

    async def run(job: Job) -> dict[str, Any]:
        try:
            if body.sync:
                report = await _sync(rt, job)
                if not report["ok"]:
                    job.line("check-in: sync had errors; continuing with existing data")
            with rt.connect() as conn:
                phase, _, _ = prepo.derive_phase(conn)
            profile = await S.get_profile(rt.store)
            code = await run_checkin(
                rt.graph,
                has_plan=phase == "active",
                has_profile=profile is not None,
                yes=False,
                out=job.line,
                thread_id=rt.thread_id,
            )
            return {"code": code, "paused": code == 3, "no_plan": code == 2}
        finally:
            rt.running = None
            rt.lock.release()

    return JobStarted(id=rt.jobs.start("checkin", run).id)


def _job(rt: Runtime, job_id: str) -> Job:
    job = rt.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job {job_id}")
    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, request: Request) -> JobOut:
    job = _job(_runtime(request), job_id)
    return JobOut(id=job.id, kind=job.kind, status=job.status, result=job.result, error=job.error)


async def _events(jobs: Jobs, job_id: str) -> AsyncIterator[str]:
    async for ev in jobs.events(job_id):
        yield format_sse(ev.name, ev.data)


@router.get("/{job_id}/events")
async def get_events(job_id: str, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    _job(rt, job_id)
    return StreamingResponse(
        _events(rt.jobs, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`run_checkin` writes its lines with `out(text)` where `text` may hold several lines and a trailing newline; `Job.line` strips only the trailing newline, so a multi-line review rendering arrives as one `line` event (the frontend renders `text` in a `<pre>`). In `app.py` add `jobs` to the import and `app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_routes_jobs.py -q`
Expected: `6 passed`. If `test_checkin_that_proposes_pauses_on_the_thread` sees `code == 1`, print the transcript: the check-in refuses (code 3) or errors (code 1) before the model when the thread is stuck or a review is pending; a fresh in-memory thread is neither.

- [ ] **Step 6: Definition of done, then commit**

```bash
git add packages/tri-web
git commit -m "feat(web): sync and check-in jobs with replayable SSE transcripts; check-in holds the coach lock"
```

---

### Task 4: Memory and reset routes

**Files:**
- Create: `packages/tri-web/src/tri_web/routes/memory.py`
- Modify: `packages/tri-web/src/tri_web/schemas.py` (+ `MemoryOut`, `ResetIn`), `packages/tri-web/src/tri_web/app.py` (include at `/api/coach`)
- Test: `packages/tri-web/tests/test_routes_memory.py`

**Interfaces:**
- Consumes: `tri_coach.memory` (fact 9), `rt.graph.checkpointer.adelete_thread` (fact 10), `Busy`.
- Produces: `GET /api/coach/memory -> {entries: [MemoryEntry], active_ids: [str]}`; `DELETE /api/coach/memory/{id} -> 204 | 404`; `POST /api/coach/reset {confirm: true, forget_memory: bool} -> 204` (409 busy; 422 when `confirm` is not true).

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_routes_memory.py`:

```python
"""Memory list and forget; reset clears the thread and, when asked, the memory."""

from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tri_coach import memory as M
from tri_planning.testing import MONDAY

pytestmark = pytest.mark.db


async def test_memory_lists_entries_with_the_active_ids(runtime, client, mem_store):
    old = await M.add_entry(mem_store, "injury", "knee", MONDAY - timedelta(days=30), until=MONDAY - timedelta(days=1))
    live = await M.add_entry(mem_store, "preference", "long rides on Saturday", MONDAY)
    async with client(runtime()) as c:
        r = await c.get("/api/coach/memory")
        assert r.status_code == 200
        body = r.json()
        assert [e["id"] for e in body["entries"]] == [old.id, live.id]
        assert body["entries"][1] == {"id": live.id, "kind": "preference", "text": "long rides on Saturday", "created": "2026-09-14", "until": None}
        assert body["active_ids"] == [live.id]
        assert (await c.delete(f"/api/coach/memory/{old.id}")).status_code == 204
        assert (await c.delete(f"/api/coach/memory/{old.id}")).status_code == 404
        assert [e["id"] for e in (await c.get("/api/coach/memory")).json()["entries"]] == [live.id]


async def test_reset_clears_the_thread_and_optionally_the_memory(runtime, client, mem_store):
    await M.add_entry(mem_store, "note", "keep", MONDAY)
    rt = runtime(coach=[AIMessage(content="Hello."), AIMessage(content="Again.")])
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "hi"})
        assert len((await c.get("/api/coach/thread")).json()["messages"]) == 2
        assert (await c.post("/api/coach/reset", json={"confirm": False, "forget_memory": False})).status_code == 422
        r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": False})
        assert r.status_code == 204
        assert (await c.get("/api/coach/thread")).json()["messages"] == []
        assert len(await M.get_entries(mem_store)) == 1
        await c.post("/api/coach/turns", json={"text": "hi again"})  # the thread works after a reset
        assert len((await c.get("/api/coach/thread")).json()["messages"]) == 2
        r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": True})
        assert r.status_code == 204
        assert await M.get_entries(mem_store) == []
    assert not rt.lock.locked() and rt.running is None


async def test_reset_is_409_while_busy(runtime, client):
    rt = runtime()
    await rt.lock.acquire()
    rt.running = "turn"
    try:
        async with client(rt) as c:
            r = await c.post("/api/coach/reset", json={"confirm": True, "forget_memory": False})
        assert r.status_code == 409 and r.json() == {"running": "turn"}
    finally:
        rt.lock.release()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_routes_memory.py -q`
Expected: 404s (routes missing).

- [ ] **Step 3: Add the schemas**

Append to `schemas.py`:

```python
from tri_coach.memory import MemoryEntry  # add to the imports


class MemoryOut(BaseModel):
    entries: list[MemoryEntry]
    active_ids: list[str]


class ResetIn(BaseModel):
    confirm: Literal[True]
    forget_memory: bool = False
```

- [ ] **Step 4: Write `routes/memory.py`**

```python
"""The coach's athlete memory, and the reset that clears the conversation (never Garmin,
TrainingPeaks, the tables or another agent's Store keys)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from tri_coach import memory as M
from tri_web.events import Busy
from tri_web.runtime import Runtime
from tri_web.schemas import MemoryOut, ResetIn

router = APIRouter()


def _runtime(request: Request) -> Runtime:
    from tri_web.app import runtime_of

    return runtime_of(request)


@router.get("/memory", response_model=MemoryOut)
async def get_memory(request: Request) -> MemoryOut:
    rt = _runtime(request)
    entries = await M.get_entries(rt.store)
    return MemoryOut(entries=entries, active_ids=[e.id for e in M.active(entries, rt.today())])


@router.delete("/memory/{entry_id}", status_code=204)
async def forget(entry_id: str, request: Request) -> Response:
    if not await M.forget_entry(_runtime(request).store, entry_id):
        raise HTTPException(status_code=404, detail=f"no memory entry {entry_id}")
    return Response(status_code=204)


@router.post("/reset", status_code=204)
async def reset(body: ResetIn, request: Request) -> Response:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    await rt.lock.acquire()
    rt.running = "reset"
    try:
        await rt.graph.checkpointer.adelete_thread(rt.thread_id)
        if body.forget_memory:
            await M.clear(rt.store)
    finally:
        rt.running = None
        rt.lock.release()
    return Response(status_code=204)
```

In `app.py` include `memory.router` with `prefix="/api/coach", tags=["memory"]`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests/test_routes_memory.py -q`
Expected: `3 passed`. If `adelete_thread` is missing on `InMemorySaver` in the installed langgraph-checkpoint (4.2.0 has it), fall back to `await asyncio.to_thread(rt.graph.checkpointer.delete_thread, rt.thread_id)`.

- [ ] **Step 6: Definition of done, then commit**

```bash
git add packages/tri-web
git commit -m "feat(web): memory list and forget; reset clears the thread through the graph's checkpointer"
```

---

### Task 5: Serve `web/dist` from the same port

**Files:**
- Modify: `packages/tri-web/src/tri_web/app.py`
- Test: `packages/tri-web/tests/test_static.py`

**Interfaces:**
- Consumes: `WebSettings.tri_web_dist`.
- Produces: `create_app(runtime, *, log: Callable[[str], None] = print)`: when `<tri_web_dist>/index.html` exists, `/assets/*` serves `<dist>/assets` and any other non-`/api` path returns `index.html`; otherwise `log("frontend not built, API only")`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-web/tests/test_static.py`:

```python
"""web/dist is served from the same port when built; client routes fall back to index.html."""

import contextlib

import httpx
import pytest

from tri_web.app import create_app
from tri_web.config import WebSettings

pytestmark = pytest.mark.db


async def test_built_frontend_is_served_with_spa_fallback(runtime, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>tri</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    rt = runtime()
    rt.settings = WebSettings(_env_file=None, anthropic_api_key="k", tri_web_dist=str(tmp_path))
    logged: list[str] = []
    transport = httpx.ASGITransport(app=create_app(rt, log=logged.append))
    async with httpx.AsyncClient(transport=transport, base_url="http://tri-web") as c:
        assert (await c.get("/")).text.startswith("<!doctype html>")
        assert (await c.get("/settings")).text.startswith("<!doctype html>")
        r = await c.get("/assets/app.js")
        assert r.status_code == 200 and r.text == "console.log(1)"
        assert (await c.get("/api/coach/thread")).status_code == 200  # the API still wins
        assert (await c.get("/api/nope")).status_code == 404
    assert logged == []


async def test_missing_frontend_logs_api_only(runtime, tmp_path):
    rt = runtime()
    rt.settings = WebSettings(_env_file=None, anthropic_api_key="k", tri_web_dist=str(tmp_path / "none"))
    logged: list[str] = []
    transport = httpx.ASGITransport(app=create_app(rt, log=logged.append))
    async with httpx.AsyncClient(transport=transport, base_url="http://tri-web") as c:
        assert (await c.get("/")).status_code == 404
    assert logged == ["frontend not built, API only"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_static.py -q`
Expected: `TypeError: create_app() got an unexpected keyword argument 'log'`.

- [ ] **Step 3: Mount the frontend in `create_app`**

Add to `app.py` (imports: `from collections.abc import Callable`, `from pathlib import Path`, `from fastapi.responses import FileResponse`, `from fastapi.staticfiles import StaticFiles`), change the signature to `def create_app(runtime: Runtime | None, *, log: Callable[[str], None] = print) -> FastAPI:` and, after the routers and exception handlers and before `return app`:

```python
    if runtime is not None:
        _mount_frontend(app, Path(runtime.settings.tri_web_dist), log)
    return app


def _mount_frontend(app: FastAPI, dist: Path, log: Callable[[str], None]) -> None:
    index = dist / "index.html"
    if not index.is_file():
        log("frontend not built, API only")
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        file = dist / path
        if path and file.is_file() and file.resolve().is_relative_to(dist.resolve()):
            return FileResponse(file)  # favicon and other top-level build outputs
        return FileResponse(index)
```

The catch-all is registered last, so every `/api/*` router route matches first; an unknown `/api/*` path reaches the catch-all and returns 404 rather than `index.html`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web -q`
Expected: all pass. `tri-web openapi` (`create_app(None)`) is unaffected.

- [ ] **Step 5: Definition of done, then commit**

```bash
git add packages/tri-web/src/tri_web/app.py packages/tri-web/tests/test_static.py
git commit -m "feat(web): serve web/dist from the API port with an index.html fallback for client routes"
```

---

### Task 6: Docs and finish

**Files:**
- Modify: `packages/tri-web/README.md`, `README.md`

- [ ] **Step 1: Package README**

Add these rows to the routes table:

```markdown
| `GET /today` | | `TodayView`: header, session, readiness, fuel, week, labs, pending (§6.2) |
| `GET /coach/memory` | | `{entries, active_ids}` |
| `DELETE /coach/memory/{id}` | | 204, or 404 |
| `POST /coach/reset` | `{confirm: true, forget_memory}` | 204; 409 when busy |
| `POST /jobs/sync` | `{since?, full?}` | `{id}` |
| `POST /jobs/checkin` | `{sync}` | `{id}`; 409 when busy |
| `GET /jobs/{id}` | | `{id, kind, status, result?, error?}` |
| `GET /jobs/{id}/events` | | SSE `line {text}`… then `done {result}` or `error {message}`; replays on reconnect |
```

Add under Layout: `src/tri_web/today.py  TodayView, build_today`, `src/tri_web/jobs.py  Job, Jobs`, and `routes/today.py, jobs.py, memory.py`. Add a "Serving the frontend" paragraph: when `web/dist/index.html` exists (plan 3's `npm --prefix web run build`) it is served from the same port with `index.html` for client routes; otherwise the server logs `frontend not built, API only`.

- [ ] **Step 2: Root README Status**

Append to the Status list:

```markdown
- tri-web server (2026-09): `tri-web serve` streams the coach over SSE, recovers a paused review after a reload, runs sync and check-in as jobs, memory and reset; tracked in `docs/superpowers/plans/2026-09-14-tri-web-0*.md`. React app pending (plan 3).
```

- [ ] **Step 3: Definition of done, vault export, commit**

Full DoD sequence. Copy both READMEs to the vault (`readme.md`). Manual check with `uv run tri-web serve --no-live`:

```bash
curl -s localhost:8321/api/today | python -m json.tool | head -40
curl -s -X POST localhost:8321/api/jobs/checkin -H 'content-type: application/json' -d '{"sync": false}'
curl -N -s localhost:8321/api/jobs/<id>/events
```

```bash
git add packages/tri-web/README.md README.md
git commit -m "docs(web): routes for today, jobs, memory, reset; root README status"
```

---

## Self-review against the spec

**Spec coverage for this plan's slice:**
- §5.1 `jobs` on the runtime (Task 2). §5.2 rows `today` (Task 1), `memory`, `memory/{id}`, `reset` (Task 4), `jobs/sync`, `jobs/checkin`, `jobs/{id}`, `jobs/{id}/events` with replay (Task 3).
- §6.2 Today: header (today, phase, goal with days to go, week start/number/of, last sync per source), session (today's workouts, fuel plan for the first planned one), readiness (today's row or the latest with its date), fuel (today's target, targets_through), week (target and actual hours and TSS, sessions by sport), labs and `labs_enabled`, `pending` for the badge; every null documented on the model (Task 1). `today()` per request (`rt.today()`).
- §6.6 jobs: registry, replay then follow, jobs die with the process; sync without the lock and its `{ok, results}`; check-in with the lock, optional sync first, `has_plan`/`has_profile` as the CLI, `yes=False`, code 3 pauses on the thread, code 2 line in the transcript (Tasks 2, 3).
- §6.7 memory table data and forget; reset with `forget_memory`; readiness was plan 1 (Task 4).
- §6.8 "frontend not built, API only" (Task 5).
- §8 `test_today.py`, `test_jobs.py`, `test_routes_memory.py` (Tasks 1, 2, 4); job routes and static serving have their own tests.

**Placeholder scan:** clean.

**Type consistency:**
- `review_payload` (public in Task 1) is what `build_today` imports; plan 1's `thread_snapshot` uses the same name after the rename.
- `Job.line`, `Job.emit`, `Jobs.start(kind, run)`, `Jobs.events(id)` (Task 2) match `routes/jobs.py` (Task 3); `JobOut.status` literal equals `JobStatus`.
- `Busy` from `tri_web.events` is raised by the check-in and reset routes and handled by plan 1's handler.
- `create_app(runtime, *, log=print)` (Task 5) is backward compatible with plan 1's `create_app(rt)` calls in `cli.py` and the test fixture; `cli._serve` should pass `log=_log` so the "API only" line reaches the console.
