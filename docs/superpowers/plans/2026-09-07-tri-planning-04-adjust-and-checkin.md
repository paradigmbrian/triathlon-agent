# tri-planning Plan 4 of 4: Adjust and Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a plan is active, the graph's `adjust` node runs a `create_agent` sub-agent that reviews the last week against plan, reads live readiness and HRV, proposes calendar changes through `propose_calendar_changes`, and extends the designed window with `design_next_week` when fewer than two designed weeks remain. A non-interactive `tri-planning check-in [--yes]` runs that review on a schedule-friendly path. A LangSmith dataset plus a code evaluator give a validator pass rate per design-prompt version. This is spec milestone 4.

**Architecture:** The adjust node renders a fresh system prompt per turn from the database (goal, this and next week's targets, last seven days planned versus actual, recovery metrics against a 30-day baseline, the agent-authored workout list) and builds the sub-agent with read-only tools only. Proposed changes arrive as the JSON result of two tools, are merged by the node into `pending_changes`, and flow through the existing `review` and `apply` nodes untouched. `check-in` is the same graph invoked with a fixed prompt. The live-tools helper that analyze already has moves into tri-core so both agents bind Garmin tools the same way.

**Tech Stack:** langchain 1.4 `create_agent`, langchain-mcp-adapters 0.3.2 (`MultiServerMCPClient.session` + `load_mcp_tools`), langgraph 1.2, `langsmith` client (`Client.create_dataset`, `evaluate`), pytest `--live`.

**Spec:** `docs/superpowers/specs/2026-09-07-tri-planning-design.md` (§6.2 adjust, §8 `check-in`, §9, §11 live test, §12 Observability, §13 milestone 4). Depends on Plans 1 to 3.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- **The adjust sub-agent binds only read tools:** `query_training_db`, Garmin `get_training_readiness`, `get_hrv_data` (allow-list `GARMIN_LIVE_TOOLS`), a `tp_get_workouts` wrapper, `propose_calendar_changes`, `design_next_week`. No write tool is ever a LangChain tool.
- Lever order in the prompt, verbatim from the spec: swap days, shorten, downgrade intensity, drop, re-plan the week.
- Check-in flags sessions with `RPE >= 8` or `feeling <= 3`; compares 3-day readiness and HRV to the 30-day baseline; notes TSB entering the week; extends the window when fewer than `2` designed weeks remain. `TRI_PLANNING_HORIZON_WEEKS` (default 3) bounds the window.
- Ownership: update, move and delete are proposed only for ids in `plan_changes` unless the athlete explicitly asked, in which case the tool call carries `athlete_requested: true`.
- Thread id stays `planning`. `check-in` never creates a goal; with no active plan it exits with a message.
- **Brian runs every git command and every live test.** The live test creates a workout 400 days out and deletes it; nothing else on the calendar is touched.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`design_next_week` results are merged into the proposal by the node, not by the model.** The tool designs and stores the week and returns its sessions as `create` changes; the node appends them to whatever `propose_calendar_changes` carried. The model cannot drop or alter a designed session by forgetting to repeat it.
- **`tri_core.mcp.live_tools` is generalized from `tri_analyze.agent.live_tools`.** The analyze module becomes a two-line wrapper. tri-core gains `langchain-mcp-adapters` as a dependency: it is MCP-to-tool plumbing, not agent logic.
- **The adjust prompt is rendered per turn**, so its cached prefix changes when the data changes. The stable part (rules, checklist, lever order) comes first so Anthropic prompt caching still covers it.
- **`check-in` does not run when the phase is not `active`.** The spec's fixed prompt presumes a plan; running intake non-interactively would be meaningless.

---

## File Structure

```
packages/tri-core/src/tri_core/mcp/live_tools.py       moved and generalized from tri-analyze
packages/tri-core/tests/test_live_tools.py              moved: filter + dead-server tests
packages/tri-analyze/src/tri_analyze/agent/live_tools.py   wrapper over tri_core
packages/tri-planning/src/tri_planning/
  repo.py                                                + owned_workouts(), recent_sessions(), recovery_baseline()
  graph/nodes/design.py                                  + design_week() helper shared with the tool
  tools/changes.py                                       make_change_tool()
  tools/design_next_week.py                              make_design_next_week_tool(deps)
  tools/tp_read.py                                       make_tp_read_tools(tp) -> [tp_get_workouts]
  prompts/adjust.py                                      AdjustContext, load_adjust_context(), render_adjust_prompt()
  prompts/checkin.py                                     CHECKIN_PROMPT
  graph/nodes/adjust.py                                  make_adjust_node(deps)  (replaces the placeholder)
  graph/graph.py                                         adjust -> review | END
  checkin.py                                             run_checkin(graph, *, yes, out, thread_id)
  cli.py                                                 check-in command; garmin tools in chat
packages/tri-planning/tests/
  test_change_tools.py, test_adjust_prompt.py, test_adjust_node.py (db), test_graph_adjust.py (db),
  test_checkin.py, test_design_eval.py, test_live_tp.py (live)
scripts/design_eval.py                                   LangSmith dataset + evaluator run
```

---

### Task 1: Move live MCP tool binding into tri-core

**Files:**
- Move: `packages/tri-analyze/src/tri_analyze/agent/live_tools.py` -> `packages/tri-core/src/tri_core/mcp/live_tools.py` (generalized); `packages/tri-analyze/tests/test_live_tools.py` -> `packages/tri-core/tests/test_live_tools.py` (the two generic tests)
- Create: new thin `packages/tri-analyze/src/tri_analyze/agent/live_tools.py`, `packages/tri-analyze/tests/test_live_tools.py` (allow-list and live tests)
- Modify: `packages/tri-core/pyproject.toml` (add `"langchain-mcp-adapters==0.3.2"`)

**Interfaces:**
- Produces: `tri_core.mcp.live_tools.filter_tools(tools, allow) -> list[BaseTool]`; `tri_core.mcp.live_tools.open_live_tools(specs: dict[str, tuple[ServerSpec, Sequence[str]]], log) -> AsyncIterator[list[BaseTool]]`; `tri_core.mcp.live_tools.SESSION_TIMEOUT_S = 120`.
- `tri_analyze.agent.live_tools.open_live_tools(settings, log)` keeps its signature (wrapper).

- [ ] **Step 1: Write the failing tests**

`packages/tri-core/tests/test_live_tools.py`:
```python
from langchain_core.tools import tool

from tri_core.config import Settings
from tri_core.mcp.live_tools import filter_tools, open_live_tools
from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec


@tool
def get_activity_splits(activity_id: str) -> str:
    """splits"""
    return ""


@tool
def get_activity(activity_id: str) -> str:
    """activity"""
    return ""


@tool
def delete_activity(activity_id: str) -> str:
    """never"""
    return ""


def test_filter_keeps_allowlisted_in_allowlist_order():
    out = filter_tools([delete_activity, get_activity_splits, get_activity], ["get_activity", "get_activity_splits"])
    assert [t.name for t in out] == ["get_activity", "get_activity_splits"]


async def test_open_live_tools_survives_a_dead_server(monkeypatch):
    s = Settings(_env_file=None, garmin_mcp_ref="0000000", tp_mcp_ref="0000000")
    logs: list[str] = []
    monkeypatch.setattr("tri_core.mcp.live_tools.SESSION_TIMEOUT_S", 5)
    specs = {"garmin": (garmin_spec(s), ["get_activity"]), "trainingpeaks": (trainingpeaks_spec(s), ["tp_get_workout"])}
    async with open_live_tools(specs, logs.append) as tools:
        assert tools == []
    assert any("garmin" in m for m in logs) and any("trainingpeaks" in m for m in logs)
```

`packages/tri-analyze/tests/test_live_tools.py` keeps only `test_allowlists_are_read_only_tools` and the `@pytest.mark.live` test from the current file, importing `open_live_tools` from `tri_analyze.agent.live_tools`.

- [ ] **Step 2: Move and generalize**

```bash
mv packages/tri-analyze/src/tri_analyze/agent/live_tools.py packages/tri-core/src/tri_core/mcp/live_tools.py
```

Edit `packages/tri-core/src/tri_core/mcp/live_tools.py`: drop the `Settings` and allow-list imports and change `open_live_tools` to:

```python
@asynccontextmanager
async def open_live_tools(
    specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    """Start each server, load its tools, keep the allow-listed ones, and keep sessions open.

    A server that fails to start is logged and skipped; the others still bind.
    """
    client = MultiServerMCPClient({name: _connection(spec) for name, (spec, _) in specs.items()})
    tools: list[BaseTool] = []
    async with AsyncExitStack() as stack:
        for name, (_, allow) in specs.items():
            try:
                session = await asyncio.wait_for(
                    stack.enter_async_context(client.session(name)), timeout=SESSION_TIMEOUT_S
                )
                loaded = await load_mcp_tools(session)
                picked = filter_tools(loaded, allow)
                tools.extend(picked)
                log(f"{name}: bound {[t.name for t in picked]}")
            except Exception as exc:  # a dead server must not kill the chat
                log(f"warning: {name} MCP server unavailable ({type(exc).__name__}: {exc}); its tools are not bound")
        yield tools
```

New `packages/tri-analyze/src/tri_analyze/agent/live_tools.py`:
```python
"""Analyze's live tools: the shared opener with this agent's allow-lists."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_core.config import Settings
from tri_core.mcp.live_tools import open_live_tools as _open
from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec


@asynccontextmanager
async def open_live_tools(settings: Settings, log: Callable[[str], None]) -> AsyncIterator[list[BaseTool]]:
    specs = {"garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS), "trainingpeaks": (trainingpeaks_spec(settings), TP_LIVE_TOOLS)}
    async with _open(specs, log) as tools:
        yield tools
```

Add `"langchain-mcp-adapters==0.3.2",` to tri-core's dependencies, then `uv sync`.

- [ ] **Step 3: Run tests, lint, type-check, commit (Brian)**

```bash
uv run pytest packages/tri-core/tests/test_live_tools.py packages/tri-analyze -q
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "refactor: generic live MCP tool binding in tri-core"
```

---

### Task 2: Repository additions and adjust context

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/repo.py`
- Create: `packages/tri-planning/src/tri_planning/prompts/adjust.py`
- Test: `packages/tri-planning/tests/test_adjust_prompt.py` (db for the loaders, pure for the renderer)

**Interfaces:**
- Produces (repo): `owned_workouts(conn, plan_id) -> list[dict]` with keys `tp_workout_id`, `workout_date`, `sport`, `title` (from `create`/`apply_plan` rows minus `delete` rows; sport and title from the payload's `workout` when present); `recent_sessions(conn, start, end) -> list[dict]` (`workout_date, sport, title, completed, planned_tss, actual_tss, planned_duration_sec, actual_duration_sec, rpe, feeling`); `recovery_baseline(conn, as_of) -> dict` with `readiness_3d`, `readiness_30d`, `hrv_3d`, `hrv_30d`, `tsb` (latest), all `float | None`.
- Produces (prompts.adjust): `AdjustContext` dataclass (`today, goal: TrainingGoal, this_week: PlanWeekRow | None, next_week: PlanWeekRow | None, actual_tss_this_week: float, sessions: list[dict], baseline: dict, owned: list[dict], designed_remaining: int, horizon: int, extension_needed: bool, checkin: bool`); `load_adjust_context(conn, today, plan_id, horizon) -> AdjustContext`; `render_adjust_prompt(ctx) -> str`; `ADJUST_RULES: str` (the stable prefix).

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_adjust_prompt.py`:
```python
from datetime import date, timedelta

import pytest

from tri_core.db import repo as core_repo
from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_planning import repo
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal, WeekTarget
from tri_planning.prompts.adjust import AdjustContext, load_adjust_context, render_adjust_prompt
from tri_planning.testing import GOAL_ARGS, MONDAY

pytestmark = pytest.mark.db


def workout(day, **over):
    base = dict(tp_workout_id=f"tp{day}", workout_date=MONDAY + timedelta(days=day), sport="run", sport_raw=None,
                title="Run", description=None, completed=True, planned_duration_sec=3600, planned_distance_m=None,
                planned_tss=50, planned_if=None, actual_duration_sec=3500, actual_distance_m=None, actual_tss=48,
                actual_if=None, normalized_power=None, avg_power=None, avg_hr=None, avg_cadence=None,
                elevation_gain_m=None, calories=None, feeling=None, rpe=None, comments=None, structure=None, raw={})
    base.update(over)
    return WorkoutRow(**base)


def seed(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = [WeekTarget(week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=300, target_hours=6) for i in range(4)]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(date=MONDAY + timedelta(weeks=1), sport="bike", title="Long ride", description="", duration_minutes=120, tss_planned=90, intensity="endurance")
    repo.insert_change(conn, pid, "planning", CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"), tp_workout_id="w9", result={})
    repo.mark_weeks_written(conn, pid, [MONDAY, MONDAY + timedelta(weeks=1)])
    return pid


def test_owned_workouts_carry_title_and_sport(nocommit):
    pid = seed(nocommit)
    owned = repo.owned_workouts(nocommit, pid)
    assert owned == [{"tp_workout_id": "w9", "workout_date": MONDAY + timedelta(weeks=1), "sport": "bike", "title": "Long ride"}]


def test_recovery_baseline_and_sessions(nocommit):
    today = MONDAY + timedelta(days=7)
    rows = [DailyMetricsRow(metric_date=today - timedelta(days=d), training_readiness=60 if d > 3 else 40,
                            hrv_overnight_avg=50 if d > 3 else 45, tsb=-5) for d in range(1, 31)]
    core_repo.upsert_daily_metrics(nocommit, rows)
    core_repo.upsert_workouts(nocommit, [workout(1, rpe=9), workout(3, feeling=2), workout(5)])
    b = repo.recovery_baseline(nocommit, today)
    assert b["readiness_3d"] == 40 and b["readiness_30d"] == pytest.approx((3 * 40 + 27 * 60) / 30)
    assert b["hrv_3d"] == 45 and b["tsb"] == -5
    sessions = repo.recent_sessions(nocommit, today - timedelta(days=7), today)
    assert [s["rpe"] for s in sessions] == [9, None, None] and sessions[1]["feeling"] == 2


def test_load_context_counts_designed_weeks_and_extension(nocommit):
    pid = seed(nocommit)
    ctx = load_adjust_context(nocommit, MONDAY + timedelta(days=2), pid, horizon=3)
    assert ctx.this_week.week_start == MONDAY and ctx.next_week.week_start == MONDAY + timedelta(weeks=1)
    assert ctx.designed_remaining == 2 and ctx.extension_needed is False
    ctx2 = load_adjust_context(nocommit, MONDAY + timedelta(weeks=1, days=1), pid, horizon=3)
    assert ctx2.designed_remaining == 1 and ctx2.extension_needed is True


def test_render_flags_rpe_and_feeling_and_lists_owned_ids():
    goal = TrainingGoal(**GOAL_ARGS)
    ctx = AdjustContext(
        today=date(2026, 9, 21), goal=goal, this_week=None, next_week=None, actual_tss_this_week=0,
        sessions=[{"workout_date": date(2026, 9, 15), "sport": "run", "title": "Tempo", "completed": True,
                   "planned_tss": 60, "actual_tss": 70, "planned_duration_sec": 3600, "actual_duration_sec": 3900,
                   "rpe": 9, "feeling": 2}],
        baseline={"readiness_3d": 40.0, "readiness_30d": 60.0, "hrv_3d": 45.0, "hrv_30d": 50.0, "tsb": -12.0},
        owned=[{"tp_workout_id": "w9", "workout_date": date(2026, 9, 22), "sport": "bike", "title": "Long ride"}],
        designed_remaining=1, horizon=3, extension_needed=True, checkin=False,
    )
    text = render_adjust_prompt(ctx)
    assert "FLAG" in text and "rpe 9" in text and "feeling 2" in text
    assert "w9" in text and "Long ride" in text
    assert "swap days" in text and "re-plan the week" in text
    assert "Window extension needed: yes" in text and "design_next_week" in text
    assert text.index("Lever order") < text.index("Today is")  # stable rules first, data after
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_adjust_prompt.py -q`
Expected: `ImportError` / `AttributeError`.

- [ ] **Step 3: Add the repository functions**

Append to `packages/tri-planning/src/tri_planning/repo.py`:
```python
def owned_workouts(conn: Conn, plan_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select operation, tp_workout_id, workout_date, payload from plan_changes "
        "where plan_id = %s and tp_workout_id is not null order by applied_at, id",
        (plan_id,),
    ).fetchall()
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["operation"] not in ("create", "apply_plan") or r["tp_workout_id"] in deleted:
            continue
        w = (r["payload"] or {}).get("workout") or {}
        out[r["tp_workout_id"]] = {
            "tp_workout_id": r["tp_workout_id"],
            "workout_date": r["workout_date"],
            "sport": w.get("sport"),
            "title": w.get("title"),
        }
    return sorted(out.values(), key=lambda d: (d["workout_date"] or date.min, d["tp_workout_id"]))


def recent_sessions(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select workout_date, sport, title, completed, planned_tss, actual_tss, planned_duration_sec, "
        "actual_duration_sec, rpe, feeling from workouts where workout_date between %s and %s "
        "order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def _avg(conn: Conn, col: str, start: date, end: date) -> float | None:
    row = conn.execute(
        f"select avg({col}) as v from daily_metrics where metric_date between %s and %s", (start, end)
    ).fetchone()
    return float(row["v"]) if row and row["v"] is not None else None


def recovery_baseline(conn: Conn, as_of: date) -> dict[str, float | None]:
    d1, d3, d30 = as_of - timedelta(days=1), as_of - timedelta(days=3), as_of - timedelta(days=30)
    tsb_row = conn.execute(
        "select tsb from daily_metrics where metric_date <= %s and tsb is not null order by metric_date desc limit 1",
        (as_of,),
    ).fetchone()
    return {
        "readiness_3d": _avg(conn, "training_readiness", d3, d1),
        "readiness_30d": _avg(conn, "training_readiness", d30, d1),
        "hrv_3d": _avg(conn, "hrv_overnight_avg", d3, d1),
        "hrv_30d": _avg(conn, "hrv_overnight_avg", d30, d1),
        "tsb": float(tsb_row["tsb"]) if tsb_row else None,
    }
```

- [ ] **Step 4: Write `prompts/adjust.py`**

```python
"""Adjust prompt: stable rules first (cacheable), then this turn's data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_planning import repo
from tri_planning.planning.models import PlanWeekRow, TrainingGoal
from tri_planning.planning.targets import week_monday

MIN_DESIGNED_WEEKS = 2

ADJUST_RULES = """\
You are a self-coached triathlete's planning assistant. The plan is active and its sessions are on
the TrainingPeaks calendar. Your job each turn: review how training is going against the plan and,
only when warranted, propose calendar changes. The athlete approves every change before it is
written, so propose what you would actually do and give a one-line reason per change.

Review checklist:
1. Last 7 days: planned versus actual per session (TSS, duration); missed sessions and why.
2. Sessions marked FLAG below (RPE >= 8 or feeling <= 3): ask whether they cost more than planned.
3. Recovery: 3-day readiness and HRV against the 30-day baseline; use get_training_readiness and
   get_hrv_data for today's numbers when they matter.
4. TSB entering this week; a deeply negative TSB before a hard week is a reason to lighten it.
5. This week's and next week's sessions against their targets; anything now unrealistic.

Lever order when something must give: swap days, shorten, downgrade intensity, drop, re-plan the
week. Use the smallest lever that solves the problem.

Rules:
- You may update, move or delete only agent-authored workouts (listed below with their ids). If
  the athlete explicitly asks you to change a workout that is not in that list, set
  athlete_requested true on that change and say so in the reason.
- tp_get_workouts shows the live calendar (planned and completed) with workout ids.
- query_training_db answers anything about history; do arithmetic in SQL.
- When "Window extension needed" is yes, call design_next_week once; its sessions are added to
  the proposal automatically. Do not repeat them in propose_calendar_changes.
- Finish with exactly one call to propose_calendar_changes, or with a short message saying no
  changes are needed and why. Be concise: findings first, then the proposal."""


@dataclass
class AdjustContext:
    today: date
    goal: TrainingGoal
    this_week: PlanWeekRow | None
    next_week: PlanWeekRow | None
    actual_tss_this_week: float
    sessions: list[dict[str, Any]]
    baseline: dict[str, float | None]
    owned: list[dict[str, Any]]
    designed_remaining: int
    horizon: int
    extension_needed: bool
    checkin: bool = False
    constraints: list[str] = field(default_factory=list)


def load_adjust_context(conn: Conn, today: date, plan_id: int, horizon: int) -> AdjustContext:
    plan = repo.get_plan(conn, plan_id)
    assert plan is not None
    stored = repo.get_goal(conn, plan.goal_id)
    assert stored is not None
    monday = week_monday(today)
    weeks = repo.list_weeks(conn, plan_id)
    this_week = next((w for w in weeks if w.week_start == monday), None)
    next_week = next((w for w in weeks if w.week_start == monday + timedelta(weeks=1)), None)
    actual = conn.execute(
        "select coalesce(sum(tss_day), 0) as t from daily_metrics where metric_date between %s and %s",
        (monday, today),
    ).fetchone()
    designed_remaining = sum(1 for w in weeks if w.designed is not None and w.week_start >= monday)
    return AdjustContext(
        today=today,
        goal=stored.goal,
        this_week=this_week,
        next_week=next_week,
        actual_tss_this_week=float(actual["t"]) if actual else 0.0,
        sessions=repo.recent_sessions(conn, today - timedelta(days=7), today),
        baseline=repo.recovery_baseline(conn, today),
        owned=repo.owned_workouts(conn, plan_id),
        designed_remaining=designed_remaining,
        horizon=horizon,
        extension_needed=designed_remaining < MIN_DESIGNED_WEEKS,
        constraints=stored.goal.constraints,
    )


def _n(v: Any, nd: int = 0) -> str:
    return "-" if v is None else f"{float(v):.{nd}f}"


def _week_line(label: str, w: PlanWeekRow | None) -> str:
    if w is None:
        return f"{label}: not in plan"
    sessions = len(w.designed.sessions) if w.designed else 0
    return (f"{label}: {w.week_start} {w.phase}, target {_n(w.target_tss)} TSS / {_n(w.target_hours, 1)} h, "
            f"{sessions} designed sessions, {'on calendar' if w.written_to_tp else 'not on calendar'}")


def render_adjust_prompt(ctx: AdjustContext) -> str:
    lines = [ADJUST_RULES, "", f"Today is {ctx.today.isoformat()}."]
    g = ctx.goal
    lines.append(f"Goal: {g.goal_type}" + (f", {g.event_name} on {g.event_date}" if g.event_date else "")
                 + f"; {g.weekly_hours_min:g}-{g.weekly_hours_max:g} h/week."
                 + (" Constraints: " + "; ".join(ctx.constraints) if ctx.constraints else ""))
    lines.append(_week_line("This week", ctx.this_week) + f"; actual so far {ctx.actual_tss_this_week:.0f} TSS")
    lines.append(_week_line("Next week", ctx.next_week))
    b = ctx.baseline
    lines.append(f"Recovery: readiness 3d {_n(b.get('readiness_3d'))} vs 30d {_n(b.get('readiness_30d'))}; "
                 f"HRV 3d {_n(b.get('hrv_3d'))} vs 30d {_n(b.get('hrv_30d'))}; TSB {_n(b.get('tsb'), 1)}")
    lines.append("Last 7 days (planned -> actual TSS):")
    for s in ctx.sessions:
        flag = ""
        if (s.get("rpe") or 0) >= 8:
            flag = f" FLAG rpe {s['rpe']}"
        elif s.get("feeling") is not None and s["feeling"] <= 3:
            flag = f" FLAG feeling {s['feeling']}"
        status = "done" if s.get("completed") else ("missed" if s["workout_date"] < ctx.today else "planned")
        lines.append(f"  {s['workout_date']} {s['sport']} {s.get('title') or ''} [{status}] "
                     f"{_n(s.get('planned_tss'))} -> {_n(s.get('actual_tss'))}{flag}")
    lines.append("Agent-authored workouts on the calendar (id date sport title):")
    lines += [f"  {o['tp_workout_id']} {o['workout_date']} {o.get('sport') or ''} {o.get('title') or ''}" for o in ctx.owned] or ["  none"]
    lines.append(f"Designed weeks remaining from this week: {ctx.designed_remaining} (horizon {ctx.horizon}). "
                 f"Window extension needed: {'yes' if ctx.extension_needed else 'no'}.")
    if ctx.checkin:
        lines.append("This is a scheduled check-in with no athlete message; do the full checklist.")
    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests, lint, type-check, commit (Brian)**

```bash
uv run pytest packages/tri-planning/tests/test_adjust_prompt.py -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): adjust context loaders and prompt"
```

---

### Task 3: Adjust tools

**Files:**
- Create: `tools/changes.py`, `tools/tp_read.py`, `tools/design_next_week.py`
- Modify: `graph/nodes/design.py` (extract `design_week`)
- Test: `tests/test_change_tools.py`

**Interfaces:**
- Produces:
  - `tools.changes.make_change_tool() -> BaseTool` named `propose_calendar_changes` with args `summary: str`, `changes: list[CalendarChange]`; returns JSON `{"summary", "changes": [...]}` after validating each with `to_tp_call`, or `{"error": [...]}` listing the bad ones (nothing proposed).
  - `tools.tp_read.make_tp_read_tools(tp: ToolCaller | None) -> list[BaseTool]` with `tp_get_workouts(start_date: str, end_date: str)`; returns the server JSON or an unavailable error.
  - `nodes.design.design_week(deps, goal, target, thresholds, previous, note, config) -> tuple[PlannedWeek, list[str]]` (the validate-and-retry-once loop; the node calls it).
  - `tools.design_next_week.make_design_next_week_tool(deps, plan_id_getter: Callable[[], int | None]) -> BaseTool` named `design_next_week`; designs the first plan week with `designed is None`, stores it, returns JSON `{"week_start", "coach_note", "violations": [...], "changes": [create changes...]}` or `{"error": ...}` when nothing is left to design.
  - `nodes.adjust.changes_from_messages(messages) -> tuple[list[CalendarChange], str | None]` (defined in Task 4; listed here because the tool JSON shapes above are its input).

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_change_tools.py`:
```python
import json
from datetime import date

import pytest

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.testing import FakeTp
from tri_planning.tools.changes import make_change_tool
from tri_planning.tools.tp_read import make_tp_read_tools


def session():
    return PlannedSession(date=date(2026, 9, 22), sport="run", title="Easy run", description="",
                          duration_minutes=40, tss_planned=30, intensity="endurance")


def test_propose_returns_validated_changes():
    tool = make_change_tool()
    out = json.loads(tool.invoke({
        "summary": "lighter Tuesday",
        "changes": [
            {"op": "move", "tp_workout_id": "w9", "new_date": "2026-09-24", "reason": "swap with Thursday"},
            {"op": "create", "workout_date": "2026-09-22", "workout": session().model_dump(mode="json"), "reason": "fill"},
        ],
    }))
    assert out["summary"] == "lighter Tuesday" and [c["op"] for c in out["changes"]] == ["move", "create"]
    assert CalendarChange.model_validate(out["changes"][0]).new_date == date(2026, 9, 24)


def test_propose_rejects_incomplete_changes_without_proposing():
    tool = make_change_tool()
    out = json.loads(tool.invoke({"summary": "s", "changes": [{"op": "delete", "reason": "no id"}]}))
    assert "error" in out and "delete" in out["error"][0] and "changes" not in out


async def test_tp_get_workouts_wrapper():
    (tool,) = make_tp_read_tools(FakeTp(responses={"tp_get_workouts": {"workouts": [{"id": "1"}], "count": 1}}))
    assert '"id": "1"' in await tool.ainvoke({"start_date": "2026-09-21", "end_date": "2026-09-27"})
    (tool,) = make_tp_read_tools(None)
    assert "unavailable" in await tool.ainvoke({"start_date": "2026-09-21", "end_date": "2026-09-27"})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_change_tools.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write the tools and extract `design_week`**

`tools/changes.py`:
```python
"""The adjust sub-agent's only way to change the calendar: a proposal the athlete reviews."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from tri_planning.planning.models import CalendarChange
from tri_planning.planning.tp_calls import to_tp_call


class ProposeArgs(BaseModel):
    summary: str = Field(description="Two or three sentences: what you found and what the changes do")
    changes: list[CalendarChange] = Field(description="Every change, each with a one-line reason")


DESCRIPTION = """\
Propose calendar changes for the athlete to approve. Ops: create (workout required), update
(tp_workout_id and workout), move (tp_workout_id and new_date), delete (tp_workout_id). Only
agent-authored workouts may be updated, moved or deleted unless athlete_requested is true. Call
it once, at the end, with the complete set. Nothing is written until the athlete approves."""


def make_change_tool() -> BaseTool:
    def propose_calendar_changes(summary: str, changes: list[CalendarChange]) -> str:
        errors = []
        for c in changes:
            try:
                to_tp_call(c)
            except ValueError as exc:
                errors.append(f"{c.op}: {exc}")
        if errors:
            return json.dumps({"error": errors})
        return json.dumps({"summary": summary, "changes": [c.model_dump(mode="json") for c in changes]})

    return StructuredTool.from_function(
        func=propose_calendar_changes, name="propose_calendar_changes", description=DESCRIPTION, args_schema=ProposeArgs
    )
```

`tools/tp_read.py`:
```python
"""Read-only TrainingPeaks access for the adjust sub-agent, over the same session apply uses."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool

from tri_core.sync import ToolCaller


def make_tp_read_tools(tp: ToolCaller | None) -> list[BaseTool]:
    async def tp_get_workouts(start_date: str, end_date: str) -> str:
        """Live TrainingPeaks calendar between two dates (YYYY-MM-DD): planned and completed
        workouts with their ids, dates, titles, planned and actual TSS."""
        if tp is None:
            return json.dumps({"error": "TrainingPeaks server unavailable this session"})
        result = await tp.call_json("tp_get_workouts", {"start_date": start_date, "end_date": end_date, "workout_filter": "all"})
        return json.dumps(result, default=str)

    return [StructuredTool.from_function(coroutine=tp_get_workouts, name="tp_get_workouts",
                                         description=tp_get_workouts.__doc__ or "")]
```

In `graph/nodes/design.py`, lift the per-week loop body into a module-level coroutine and have the node call it:

```python
async def design_week(
    deps: GraphDeps,
    goal: TrainingGoal,
    target: WeekTarget,
    thresholds: dict[str, Any] | None,
    previous: PlannedWeek | None,
    note: str | None,
    config: RunnableConfig,
) -> tuple[PlannedWeek, list[str]]:
    structured = deps.model.with_structured_output(PlannedWeek)
    cfg = merge_configs(config, {"tags": [f"week_start:{target.week_start}", f"phase:{target.phase}"]})

    async def one(prompt: str) -> PlannedWeek:
        out = await structured.ainvoke([SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg)
        assert isinstance(out, PlannedWeek)
        return out

    week = await one(render_design_prompt(goal, target, thresholds, previous, note, None, None))
    violations = validate.week(week, target, goal)
    if violations:
        week = await one(render_design_prompt(goal, target, thresholds, previous, note, violations, week))
        violations = validate.week(week, target, goal)
    return week, violations
```

The node's loop becomes `week, violations = await design_week(deps, goal, target, thresholds, previous, note, config)` followed by the same storage and change-building code. Also lift the change-building into `session_changes(week: PlannedWeek, phase: str) -> list[CalendarChange]` (skips `rest`), used by both the node and the tool. Re-run `packages/tri-planning/tests/test_design_node.py` after the refactor.

`tools/design_next_week.py`:
```python
"""Window extension for the adjust sub-agent: design the next target week with the design prompt."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, InjectedToolArg

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.design import design_week, session_changes
from tri_planning.planning.targets import week_monday


def make_design_next_week_tool(deps: GraphDeps, plan_id_getter: Callable[[], int | None]) -> BaseTool:
    async def design_next_week(config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
        """Design the next undesigned week of the plan (sessions, TSS, structure) so the calendar
        keeps at least two designed weeks ahead. Its sessions join the proposal automatically."""
        plan_id = plan_id_getter()
        if plan_id is None:
            return json.dumps({"error": "no active plan"})
        with deps.connect() as conn:
            plan = repo.get_plan(conn, plan_id)
            assert plan is not None
            stored = repo.get_goal(conn, plan.goal_id)
            assert stored is not None
            weeks = repo.list_weeks(conn, plan_id)
            thresholds = repo.athlete_thresholds(conn)
        monday = week_monday(deps.today())
        row = next((w for w in weeks if w.week_start >= monday and w.designed is None), None)
        if row is None:
            return json.dumps({"error": "every remaining week is already designed"})
        target = next(t for t in plan.targets if t.week_start == row.week_start)
        previous = next((w.designed for w in reversed(weeks) if w.designed and w.week_start < row.week_start), None)
        week, violations = await design_week(deps, stored.goal, target, thresholds, previous, None, config)
        with deps.connect() as conn:
            repo.set_week_designed(conn, plan_id, row.week_start, week)
            conn.commit()
        changes = session_changes(week, target.phase)
        return json.dumps({
            "week_start": row.week_start.isoformat(), "coach_note": week.coach_note,
            "violations": violations, "changes": [c.model_dump(mode="json") for c in changes],
        })

    return StructuredTool.from_function(coroutine=design_next_week, name="design_next_week",
                                        description=design_next_week.__doc__ or "")
```

If `InjectedToolArg` on a `RunnableConfig` parameter is not honored by `StructuredTool.from_function` in this langchain version, drop the parameter and pass `{"configurable": {}}` to `design_week`; the LangSmith tags still apply through `merge_configs`.

- [ ] **Step 4: Run the tests, lint, type-check, commit (Brian)**

```bash
uv run pytest packages/tri-planning/tests/test_change_tools.py packages/tri-planning/tests/test_design_node.py -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): propose_calendar_changes, tp_get_workouts wrapper, design_next_week"
```

---

### Task 4: Adjust node and graph edge

**Files:**
- Modify: `graph/nodes/adjust.py` (replace placeholder), `graph/graph.py`
- Test: `tests/test_adjust_node.py`, `tests/test_graph_adjust.py`

**Interfaces:**
- Produces:
  - `nodes.adjust.changes_from_messages(messages) -> tuple[list[CalendarChange], str | None]`: the changes from the last `propose_calendar_changes` ToolMessage (if its JSON has `changes`), plus every `design_next_week` ToolMessage's `changes`, in message order; the summary from the proposal, or a generated one when only designed weeks were added.
  - `nodes.adjust.make_adjust_node(deps) -> async node` returning `{"messages": new}` and, when changes exist, `{"pending_changes", "pending_summary", "changes_from": "adjust", "review_decision": None}`.
  - `graph.after_adjust(state) -> "review" | END`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_adjust_node.py`:
```python
import json
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.nodes.adjust import changes_from_messages, make_adjust_node
from tri_planning.planning.models import CalendarChange, FitnessSnapshot, PlannedSession, TrainingGoal
from tri_planning.planning.targets import build
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def seed(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(date=MONDAY + timedelta(days=2), sport="run", title="Tempo", description="", duration_minutes=60, tss_planned=60, intensity="tempo")
    repo.insert_change(conn, pid, "planning", CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"), tp_workout_id="w1", result={})
    repo.mark_weeks_written(conn, pid, [MONDAY])
    return gid, pid, targets


def test_changes_from_messages_merges_tool_results():
    proposal = {"summary": "lighter", "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "sick"}]}
    designed = {"week_start": "2026-09-21", "coach_note": "n", "violations": [], "changes": [
        {"op": "create", "workout_date": "2026-09-21", "reason": "next week",
         "workout": {"date": "2026-09-21", "sport": "swim", "title": "S", "description": "", "duration_minutes": 45, "tss_planned": 40, "intensity": "endurance"}}]}
    msgs = [
        ToolMessage(content=json.dumps(designed), name="design_next_week", tool_call_id="1"),
        ToolMessage(content=json.dumps(proposal), name="propose_calendar_changes", tool_call_id="2"),
        AIMessage(content="done"),
    ]
    changes, summary = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"] and summary == "lighter"
    assert changes_from_messages([AIMessage(content="no changes")]) == ([], None)


async def test_turn_without_proposal_returns_messages_only(nocommit, make_deps):
    gid, pid, _ = seed(nocommit)
    model = ScriptedChatModel(script=[AIMessage(content="All on track. No changes.")])
    node = make_adjust_node(make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3)))
    out = await node({"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage("how am I doing?")]}, CFG)
    assert "pending_changes" not in out and out["messages"][-1].content.startswith("All on track")


async def test_proposal_becomes_pending_changes(nocommit, make_deps):
    gid, pid, _ = seed(nocommit)
    model = ScriptedChatModel(script=[
        tool_call("propose_calendar_changes", {"summary": "drop tempo", "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "sick"}]}),
        AIMessage(content="Proposed."),
    ])
    node = make_adjust_node(make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3)))
    out = await node({"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage("I'm sick, drop Wednesday")]}, CFG)
    assert out["changes_from"] == "adjust" and out["pending_summary"] == "drop tempo"
    assert [c.op for c in out["pending_changes"]] == ["delete"]


async def test_design_next_week_extends_window(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(script=[
        tool_call("design_next_week", {}),
        tool_call("PlannedWeek", week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)),
        AIMessage(content="Next week designed; nothing else to change."),
    ])
    node = make_adjust_node(make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3), horizon=3))
    out = await node({"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage("check in")]}, CFG)
    assert len(out["pending_changes"]) == 3 and all(c.op == "create" for c in out["pending_changes"])
    assert repo.list_weeks(nocommit, pid)[1].designed is not None
    assert "2026-09-21" in out["pending_summary"]
```

`packages/tri-planning/tests/test_graph_adjust.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.graph import after_adjust, build_graph
from tri_planning.planning.models import CalendarChange, PlannedSession, TrainingGoal, WeekTarget
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "planning"}}


def seed_active(conn):
    goal = TrainingGoal(**GOAL_ARGS)
    gid = repo.insert_goal(conn, goal)
    targets = [WeekTarget(week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=300, target_hours=6) for i in range(3)]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    s = PlannedSession(date=MONDAY + timedelta(days=2), sport="run", title="Tempo", description="", duration_minutes=60, tss_planned=60, intensity="tempo")
    repo.insert_change(conn, pid, "planning", CalendarChange(op="create", workout_date=s.date, workout=s, reason="r"), tp_workout_id="w1", result={})
    return gid, pid


async def test_active_turn_proposes_reviews_and_applies(nocommit, make_deps):
    gid, pid = seed_active(nocommit)
    tp = FakeTp()
    model = ScriptedChatModel(script=[
        tool_call("propose_calendar_changes", {"summary": "move it", "changes": [{"op": "move", "tp_workout_id": "w1", "new_date": (MONDAY + timedelta(days=4)).isoformat(), "reason": "rest day"}]}),
        AIMessage(content="Proposed a move."),
    ])
    graph = build_graph(make_deps(model, tp=tp, today=MONDAY + timedelta(days=1), horizon=3), InMemorySaver())
    await graph.aupdate_state(CFG, {"goal_id": gid, "plan_id": pid, "phase": "active"})
    out = await graph.ainvoke({"messages": [HumanMessage("I need Wednesday off")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][0]["op"] == "move"
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert tp.calls == [("tp_update_workout", {"workout_id": "w1", "date": (MONDAY + timedelta(days=4)).isoformat()})]
    assert out["phase"] == "active" and out["pending_changes"] == []


def test_after_adjust():
    assert after_adjust({"pending_changes": [1]}) == "review"
    assert after_adjust({"pending_changes": []}) == "__end__"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_adjust_node.py packages/tri-planning/tests/test_graph_adjust.py -q`
Expected: `ImportError` / `AttributeError`.

- [ ] **Step 3: Write `graph/nodes/adjust.py`**

```python
"""Adjust node: a create_agent sub-agent that reviews training and proposes calendar changes."""

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
from tri_planning.planning.models import CalendarChange
from tri_planning.prompts.adjust import load_adjust_context, render_adjust_prompt
from tri_planning.tools.changes import make_change_tool
from tri_planning.tools.design_next_week import make_design_next_week_tool
from tri_planning.tools.tp_read import make_tp_read_tools


def _json(msg: ToolMessage) -> dict[str, Any] | None:
    try:
        data = json.loads(str(msg.content))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def changes_from_messages(messages: Sequence[AnyMessage]) -> tuple[list[CalendarChange], str | None]:
    designed: list[CalendarChange] = []
    designed_weeks: list[str] = []
    proposed: list[CalendarChange] = []
    summary: str | None = None
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        data = _json(msg)
        if data is None or "changes" not in data:
            continue
        changes = [CalendarChange.model_validate(c) for c in data["changes"]]
        if msg.name == "design_next_week":
            designed.extend(changes)
            designed_weeks.append(str(data.get("week_start")))
        elif msg.name == "propose_calendar_changes":
            proposed = changes
            summary = str(data.get("summary") or "")
    all_changes = designed + proposed
    if designed_weeks:
        extension = "Designed week(s) " + ", ".join(designed_weeks) + " added to the calendar proposal."
        summary = f"{summary}\n{extension}" if summary else extension
    return all_changes, summary


def make_adjust_node(deps: GraphDeps) -> Any:
    query = make_query_tool(deps.db_url)
    change_tool = make_change_tool()
    tp_tools = make_tp_read_tools(deps.tp)

    async def adjust(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        plan_id = state.get("plan_id")
        assert plan_id is not None, "adjust needs an active plan"
        with deps.connect() as conn:
            ctx = load_adjust_context(conn, deps.today(), plan_id, deps.horizon_weeks)
        design_tool = make_design_next_week_tool(deps, lambda: plan_id)
        tools = [query, *deps.garmin_tools, *tp_tools, design_tool, change_tool]
        agent = make_subagent(deps.model, tools, render_adjust_prompt(ctx))
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before):]
        update: dict[str, Any] = {"messages": new}
        changes, summary = changes_from_messages(new)
        if changes:
            update.update({"pending_changes": changes, "pending_summary": summary,
                           "changes_from": "adjust", "review_decision": None})
        return update

    return adjust
```

In `graph/graph.py` replace `from tri_planning.graph.nodes.adjust import adjust_node` with `make_adjust_node`, register `g.add_node("adjust", make_adjust_node(deps))`, add

```python
def after_adjust(state: PlanningState) -> str:
    return "review" if state.get("pending_changes") else END
```

and replace `g.add_edge("adjust", END)` with `g.add_conditional_edges("adjust", after_adjust, ["review", END])`. Update the docstring diagram. In `tests/test_graph.py`, `test_approve_applies_and_activates` asserted the placeholder text `milestone 4`; change that turn to script an `AIMessage("All on track.")` for the adjust sub-agent and assert it appears.

- [ ] **Step 4: Run the tests, lint, type-check, commit (Brian)**

```bash
uv run pytest packages/tri-planning -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): adjust sub-agent node with window extension"
```

---

### Task 5: `check-in` command and Garmin tools in `chat`

**Files:**
- Create: `packages/tri-planning/src/tri_planning/checkin.py`, `packages/tri-planning/src/tri_planning/prompts/checkin.py`
- Modify: `packages/tri-planning/src/tri_planning/cli.py`
- Test: `packages/tri-planning/tests/test_checkin.py`

**Interfaces:**
- Produces:
  - `prompts.checkin.CHECKIN_PROMPT: str` (the fixed human message).
  - `checkin.run_checkin(graph, *, yes: bool, out, thread_id="planning") -> int` (exit code: 0 applied or nothing to do, 3 paused at review, 2 no active plan).
  - CLI `tri-planning check-in [--yes] [--no-sync] [--no-live]`.
  - `chat` and `check-in` both open Garmin live tools with `tri_core.mcp.live_tools.open_live_tools({"garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS)}, log)` and pass them as `GraphDeps.garmin_tools`.

- [ ] **Step 1: Write the failing test**

`packages/tri-planning/tests/test_checkin.py`:
```python
from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from tri_planning.checkin import run_checkin
from tri_planning.prompts.checkin import CHECKIN_PROMPT


class StubGraph:
    def __init__(self, turns, phase="active"):
        self.turns = list(turns)
        self.inputs = []
        self.phase = phase

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"phase": self.phase, "pending_changes": []}
            next = ()
        return S()


INTERRUPT = ((), "updates", {"__interrupt__": (Interrupt(value={"summary": "s", "changes": [
    {"op": "delete", "tp_workout_id": "w1", "reason": "sick"}], "last_error": None}),)})
APPLIED = ((), "updates", {"apply": {"messages": [AIMessage(content="TrainingPeaks: applied 1 of 1 changes.")]}})


async def test_checkin_pauses_without_yes():
    g = StubGraph([[INTERRUPT]])
    buf = []
    assert await run_checkin(g, yes=False, out=buf.append) == 3
    assert g.inputs[0]["messages"][0].content == CHECKIN_PROMPT
    assert "w1" in "".join(buf) and "paused" in "".join(buf)


async def test_checkin_yes_approves():
    g = StubGraph([[INTERRUPT], [APPLIED]])
    buf = []
    assert await run_checkin(g, yes=True, out=buf.append) == 0
    assert isinstance(g.inputs[1], Command) and g.inputs[1].resume == {"action": "approve"}


async def test_checkin_requires_active_plan():
    g = StubGraph([], phase="intake")
    buf = []
    assert await run_checkin(g, yes=True, out=buf.append) == 2 and "no active plan" in "".join(buf)


async def test_checkin_no_changes_exits_zero():
    g = StubGraph([[((), "updates", {"adjust": {"messages": [AIMessage(content="All on track.")]}})]])
    assert await run_checkin(g, yes=False, out=lambda s: None) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_checkin.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write `prompts/checkin.py` and `checkin.py`**

`prompts/checkin.py`:
```python
"""The fixed message a scheduled check-in sends to the adjust sub-agent."""

CHECKIN_PROMPT = """\
Scheduled check-in. Review the last 7 days against the plan; flag sessions with RPE >= 8 or
feeling <= 3; compare 3-day readiness and HRV to the 30-day baseline; note TSB entering this
week; if the window extension is needed, call design_next_week. Then either propose the calendar
changes you would make (propose_calendar_changes) or say clearly that no changes are needed."""
```

`checkin.py`:
```python
"""Non-interactive review: one graph turn with the fixed check-in prompt."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_planning.prompts.checkin import CHECKIN_PROMPT
from tri_planning.repl import Out, render_changes, run_turn

EXIT_OK, EXIT_NO_PLAN, EXIT_PAUSED = 0, 2, 3


async def run_checkin(graph: Any, *, yes: bool, out: Out, thread_id: str = "planning") -> int:
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = snap.values or {}
    if values.get("phase") != "active" and not values.get("pending_changes"):
        out("check-in: no active plan; run `tri-planning chat` to set a goal first\n")
        return EXIT_NO_PLAN
    printer = await run_turn(graph, {"messages": [HumanMessage(CHECKIN_PROMPT)]}, thread_id, out)
    if printer.interrupt is None:
        return EXIT_OK
    out(render_changes(printer.interrupt) + "\n")
    if not yes:
        out("check-in: paused at review; run `tri-planning chat` and type /pending to decide\n")
        return EXIT_PAUSED
    out("check-in: --yes given, approving\n")
    printer = await run_turn(graph, Command(resume={"action": "approve"}), thread_id, out)
    return EXIT_PAUSED if printer.interrupt is not None else EXIT_OK
```

- [ ] **Step 4: Wire the CLI**

In `cli.py`, factor the resource opening out of `_chat` into an async context manager used by both commands:

```python
@asynccontextmanager
async def _open_graph(*, no_live: bool) -> AsyncIterator[Any]:
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.live_tools import open_live_tools
    from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec
    from tri_planning.allowlist import GARMIN_LIVE_TOOLS
    from tri_planning.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_planning.graph.deps import make_deps
    from tri_planning.graph.graph import build_graph
    from tri_planning.graph.llm import make_model

    settings = get_planning_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        raise typer.Exit(code=2)
    async with AsyncExitStack() as stack:
        tp = None
        garmin_tools: list[Any] = []
        if not no_live:
            try:
                tp = await asyncio.wait_for(
                    stack.enter_async_context(McpToolClient(trainingpeaks_spec(settings))), timeout=TP_START_TIMEOUT_S
                )
                _out("trainingpeaks: connected (writes happen only after you approve)\n")
            except Exception as exc:
                _out(f"warning: trainingpeaks MCP server unavailable ({type(exc).__name__}: {exc}); apply will refuse to write\n")
            garmin_tools = await stack.enter_async_context(
                open_live_tools({"garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS)}, lambda m: _out(m + "\n"))
            )
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        deps = make_deps(settings, make_model(settings), tp)
        deps.garmin_tools = garmin_tools
        yield build_graph(deps, saver)
```

`_chat` becomes `async with _open_graph(no_live=no_live) as graph:` around the existing `read`/`cmd_status`/`cmd_sync`/`edit_in_editor`/`chat_loop` body. Add:

```python
@app.command("check-in")
def check_in(
    yes: bool = typer.Option(False, "--yes", help="Approve the proposed changes without asking"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip `tri sync` first"),
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Sync, review the last week against plan, propose changes; pause at review unless --yes."""
    raise typer.Exit(code=asyncio.run(_check_in(yes=yes, no_sync=no_sync, no_live=no_live)))


async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from tri_core.sync.runner import run_sync
    from tri_planning.checkin import run_checkin

    if not no_sync:
        report = await run_sync(get_planning_settings(), log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("check-in: sync had errors; continuing with existing data\n")
    async with _open_graph(no_live=no_live) as graph:
        return await run_checkin(graph, yes=yes, out=_out, thread_id=THREAD_ID)
```

- [ ] **Step 5: Run the tests and smoke the command**

```bash
uv run pytest packages/tri-planning/tests/test_checkin.py -q
uv run tri-planning check-in --no-sync --no-live   # with no active plan: exit 2 and the message
```

- [ ] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): check-in command; Garmin live tools in chat"
```

---

### Task 6: LangSmith design evaluator

**What this teaches:** a LangSmith dataset of inputs (target weeks) and a code evaluator (`validate.week`) that scores each output, giving a pass rate per prompt version without a judge model.

**Files:**
- Create: `packages/tri-planning/src/tri_planning/evals/__init__.py`, `packages/tri-planning/src/tri_planning/evals/design_eval.py`, `scripts/design_eval.py`
- Modify: `packages/tri-planning/pyproject.toml` (add `"langsmith>=0.3"`)
- Test: `packages/tri-planning/tests/test_design_eval.py`

**Interfaces:**
- Produces:
  - `evals.design_eval.build_examples(today: date) -> list[dict]`: one example per (goal preset, phase) with `inputs = {"goal": TrainingGoal json, "target": WeekTarget json, "thresholds": {...}}`, `metadata = {"goal_type", "phase"}`; presets: sprint 8 weeks, olympic 14 weeks, half_ironman 20 weeks with restricted availability, ironman 24 weeks; phases: first base, first build, first recovery, first peak, first taper, race.
  - `evals.design_eval.validator_pass(inputs: dict, outputs: dict) -> dict` returning `{"key": "validator_pass", "score": 1 | 0, "comment": "; ".join(violations)}`.
  - `evals.design_eval.design_target(deps) -> Callable[[dict], Awaitable[dict]]` that runs `design_week` and returns `{"week": PlannedWeek json, "violations": [...]}`.
  - `scripts/design_eval.py [--dataset NAME] [--prompt-version TAG]` creates or updates the dataset and runs `langsmith.evaluate`.

- [ ] **Step 1: Write the failing test**

`packages/tri-planning/tests/test_design_eval.py`:
```python
from datetime import date

from tri_planning.evals.design_eval import build_examples, validator_pass
from tri_planning.planning.models import TrainingGoal, WeekTarget
from tri_planning.testing import week_json


def test_examples_cover_presets_and_phases():
    ex = build_examples(date(2026, 9, 14))
    kinds = {(e["metadata"]["goal_type"], e["metadata"]["phase"]) for e in ex}
    assert ("olympic", "base") in kinds and ("ironman", "taper") in kinds and ("sprint", "race") in kinds
    for e in ex:
        TrainingGoal.model_validate(e["inputs"]["goal"])
        WeekTarget.model_validate(e["inputs"]["target"])
    assert len(ex) >= 16


def test_validator_pass_scores_week():
    ex = next(e for e in build_examples(date(2026, 9, 14)) if e["metadata"]["goal_type"] == "olympic" and e["metadata"]["phase"] == "base")
    target = WeekTarget.model_validate(ex["inputs"]["target"])
    good = {"week": week_json(target.week_start, target.target_tss)}
    bad = {"week": week_json(target.week_start, target.target_tss * 2)}
    assert validator_pass(ex["inputs"], good)["score"] == 1
    out = validator_pass(ex["inputs"], bad)
    assert out["score"] == 0 and "TSS" in out["comment"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_design_eval.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write the module and script**

`evals/design_eval.py`:
```python
"""Dataset of target weeks and a code evaluator for the design prompt."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.design import design_week
from tri_planning.planning import validate
from tri_planning.planning.models import FitnessSnapshot, PlannedWeek, TrainingGoal, WeekTarget
from tri_planning.planning.targets import build, next_monday

ANY = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
RESTRICTED = {"mon": [], "tue": ["swim", "run"], "wed": ["bike"], "thu": ["run"], "fri": ["swim"], "sat": "any", "sun": ["bike", "run", "brick"]}
THRESHOLDS = {"ftp_watts": 250, "run_threshold_pace_sec_per_km": 270, "swim_css_sec_per_100m": 105, "lthr_bpm": 165}
PHASES = ("base", "build", "recovery", "peak", "taper", "race")


def _presets(start: date) -> list[TrainingGoal]:
    def race(goal_type: str, weeks: int, hours: tuple[float, float], days: dict[str, Any]) -> TrainingGoal:
        return TrainingGoal(goal_type=goal_type, event_name=f"{goal_type} race", priority="A",
                            event_date=start + timedelta(weeks=weeks - 1, days=6),
                            weekly_hours_min=hours[0], weekly_hours_max=hours[1], available_days=days,
                            constraints=["no swimming Mondays" if days is RESTRICTED else "long ride Saturdays"])

    return [race("sprint", 8, (4, 7), ANY), race("olympic", 14, (6, 10), ANY),
            race("half_ironman", 20, (8, 12), RESTRICTED), race("ironman", 24, (10, 16), ANY)]


def build_examples(today: date) -> list[dict[str, Any]]:
    start = next_monday(today)
    fitness = FitnessSnapshot(ctl=45, recent_weekly_tss=320)
    examples: list[dict[str, Any]] = []
    for goal in _presets(start):
        targets = build(goal, fitness, start)
        for phase in PHASES:
            target = next((t for t in targets if (t.phase == phase and not t.is_recovery) or (phase == "recovery" and t.is_recovery)), None)
            if target is None:
                continue
            examples.append({
                "inputs": {"goal": goal.model_dump(mode="json"), "target": target.model_dump(mode="json"), "thresholds": THRESHOLDS},
                "metadata": {"goal_type": goal.goal_type, "phase": phase},
            })
    return examples


def validator_pass(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    goal = TrainingGoal.model_validate(inputs["goal"])
    target = WeekTarget.model_validate(inputs["target"])
    week = PlannedWeek.model_validate(outputs["week"])
    violations = validate.week(week, target, goal)
    return {"key": "validator_pass", "score": 0 if violations else 1, "comment": "; ".join(violations)}


def design_target(deps: GraphDeps) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def run(inputs: dict[str, Any]) -> dict[str, Any]:
        goal = TrainingGoal.model_validate(inputs["goal"])
        target = WeekTarget.model_validate(inputs["target"])
        week, violations = await design_week(deps, goal, target, inputs.get("thresholds"), None, None, {"configurable": {}})
        return {"week": week.model_dump(mode="json"), "violations": violations}

    return run
```

`scripts/design_eval.py`:
```python
"""Create/refresh the LangSmith dataset of target weeks and score the design prompt.

    uv run python scripts/design_eval.py --prompt-version v1

Needs LANGSMITH_API_KEY and ANTHROPIC_API_KEY in .env. Each example costs one or two model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import date

from dotenv import load_dotenv
from langsmith import Client
from langsmith.evaluation import aevaluate

from tri_planning.config import get_planning_settings
from tri_planning.evals.design_eval import build_examples, design_target, validator_pass
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.llm import make_model


def ensure_dataset(client: Client, name: str) -> None:
    examples = build_examples(date.today())
    if client.has_dataset(dataset_name=name):
        return
    ds = client.create_dataset(dataset_name=name, description="Target weeks for the tri-planning design prompt")
    client.create_examples(dataset_id=ds.id, inputs=[e["inputs"] for e in examples], metadata=[e["metadata"] for e in examples])


async def main(dataset: str, version: str) -> None:
    load_dotenv()
    settings = get_planning_settings()
    client = Client()
    ensure_dataset(client, dataset)
    deps = GraphDeps(model=make_model(settings), connect=lambda: contextlib.nullcontext(None), db_url=settings.database_url)  # type: ignore[arg-type]
    results = await aevaluate(design_target(deps), data=dataset, evaluators=[validator_pass],
                              experiment_prefix=f"design-{version}", metadata={"prompt_version": version})
    print(results)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="tri-planning-design-weeks")
    p.add_argument("--prompt-version", default="v1")
    a = p.parse_args()
    asyncio.run(main(a.dataset, a.prompt_version))
```

Add `"langsmith>=0.3",` to tri-planning's dependencies and `uv sync`. `design_week` needs no database, so a null `connect` is acceptable for the eval.

- [ ] **Step 4: Run the tests; Brian runs the eval once**

```bash
uv run pytest packages/tri-planning/tests/test_design_eval.py -q
uv run python scripts/design_eval.py --prompt-version v1
```
Expected: 2 passed; the script prints an experiment URL and a `validator_pass` mean. Record the pass rate in the README's Status section.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): LangSmith design-week dataset and validator evaluator"
```

---

### Task 7: Live TrainingPeaks write test, README, wrap-up

**Files:**
- Create: `packages/tri-planning/tests/test_live_tp.py`
- Modify: `packages/tri-planning/README.md`, root `README.md`, spec §15 (record findings)

- [ ] **Step 1: Write the live test**

`packages/tri-planning/tests/test_live_tp.py`:
```python
"""Opt-in: creates one workout 400 days out on the real calendar, updates it, deletes it."""

from datetime import date, timedelta

import pytest

from tri_core.config import Settings
from tri_core.mcp.client import McpToolClient
from tri_core.mcp.servers import trainingpeaks_spec
from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call

pytestmark = pytest.mark.live


async def test_create_update_delete_roundtrip():
    day = date.today() + timedelta(days=400)
    session = PlannedSession(date=day, sport="bike", title="tri-planning live test", description="delete me",
                             duration_minutes=30, tss_planned=20, intensity="recovery")
    async with McpToolClient(trainingpeaks_spec(Settings())) as tp:
        name, args = to_tp_call(CalendarChange(op="create", workout_date=day, workout=session, reason="test"))
        created = await tp.call_json(name, args)
        wid = result_workout_id(CalendarChange(op="create", workout=session, reason="t"), created)
        assert wid, created
        try:
            name, args = to_tp_call(CalendarChange(op="update", tp_workout_id=wid, workout=session.model_copy(update={"title": "tri-planning live test (updated)"}), reason="t"))
            assert (await tp.call_json(name, args))["success"] is True
            listed = await tp.call_json("tp_get_workouts", {"start_date": day.isoformat(), "end_date": day.isoformat()})
            assert any(w["id"] == wid and "updated" in w["title"] for w in listed["workouts"])
        finally:
            name, args = to_tp_call(CalendarChange(op="delete", tp_workout_id=wid, reason="t"))
            assert (await tp.call_json(name, args))["success"] is True
        listed = await tp.call_json("tp_get_workouts", {"start_date": day.isoformat(), "end_date": day.isoformat()})
        assert all(w["id"] != wid for w in listed["workouts"])
```

Brian runs it: `uv run pytest packages/tri-planning/tests/test_live_tp.py --live -q`. Expected: 1 passed and nothing left on the calendar 400 days out. Record in spec §15 whether `tp_get_workouts` returns ids as strings (the sync module and `FakeTp` assume strings; adjust `weekly_targets_from_workouts` and `owned_workout_ids` comparisons with `str(...)` if the server returns integers).

- [ ] **Step 2: README updates**

`packages/tri-planning/README.md`: add to Commands
```bash
uv run tri-planning check-in [--yes] [--no-sync] [--no-live]   # sync, review last 7 days, propose; exit 3 when paused
uv run python scripts/design_eval.py --prompt-version v2         # LangSmith pass rate for the design prompt
```
and a section:
```markdown
## Adjusting

Once the plan is active every chat turn goes to the adjust sub-agent, which sees this week's and
next week's targets, the last 7 days planned versus actual (RPE >= 8 and feeling <= 3 flagged),
3-day readiness and HRV against a 30-day baseline, TSB, and the list of agent-authored workouts.
It may call `get_training_readiness`, `get_hrv_data`, `tp_get_workouts`, `query_training_db`,
`design_next_week` (when fewer than two designed weeks remain) and finally
`propose_calendar_changes`. Every proposal goes through the same review and apply as the first plan.
`check-in` runs the same review with a fixed prompt; exit code 3 means it is waiting for you.
For a cron job: `uv run tri-planning check-in --yes` applies without asking; leave `--yes` off
to review in the next `chat`.
```

Root `README.md` Run section: add the `check-in` line. Status: add `- tri-planning milestones 2-4 (2026-09): targets, graph with review interrupt, adjust and check-in; design-prompt validator pass rate: the `validator_pass` mean printed by `scripts/design_eval.py`.`

- [ ] **Step 3: Record §15 findings in the spec**

Append to spec §15 a "Resolved" list: `PostgresSaver` via `AsyncPostgresSaver.from_conn_string` (or the explicit-connection fallback, whichever Task 8 of Plan 3 needed); `tp_apply_training_plan` returns counts only, follow-up `tp_get_workouts` used; `tp_create_workout` returns `workout_id`; uv workspace scripts install with a virtual root (or `--all-packages`, whichever Plan 1 needed); `tp_get_workouts` id type from the live test.

- [ ] **Step 4: Docs to the vault, final checks, commit (Brian)**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp README.md $V/readme.md && cp packages/tri-planning/README.md $V/packages/tri-planning/readme.md
cp docs/superpowers/specs/*.md $V/docs/superpowers/specs/ && cp docs/superpowers/plans/*.md $V/docs/superpowers/plans/
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): live TrainingPeaks test; README and spec findings"
git push
```

---

## Self-review notes

- Spec §6.2 adjust: tools (`query_training_db`, Garmin readiness and HRV, `tp_get_workouts`, `propose_calendar_changes`, `design_next_week`) in Tasks 3 and 4; the checklist and lever order verbatim in `ADJUST_RULES` (Task 2, tested); window extension when fewer than two designed weeks remain (`MIN_DESIGNED_WEEKS`, tested in Tasks 2 and 4); ownership read from `plan_changes` before proposing (`owned_workouts` in the prompt, `athlete_requested` rule).
- Spec §8 `check-in`: sync first, fixed prompt with every listed item, prints the change set, exits paused, `--yes` approves (Task 5).
- Spec §11: adjust ends on `propose_calendar_changes` (Task 4), live create/update/delete (Task 7).
- Spec §12: dataset of target weeks and a code evaluator running `validate.week` with a pass rate per prompt version (Task 6).
- Type consistency: `design_week(deps, goal, target, thresholds, previous, note, config)` is the one signature used by the design node, `design_next_week` and the evaluator; `changes_from_messages` consumes the JSON shapes that `propose_calendar_changes` and `design_next_week` return; `run_checkin` uses `run_turn`, `render_changes` and `TurnPrinter.interrupt` from Plan 3.
