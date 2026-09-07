# tri-planning Plan 2 of 4: Skeleton and Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `tri-planning` package with the planning domain models, the periodization constants, the pure skeleton builder (goal + fitness -> week targets), the pure week validator, the planning tables migration and the repository over them. Every rule is unit-tested; nothing calls a model. This is spec milestone 2.

**Architecture:** `tri_planning.planning` is a pure layer: Pydantic models, a constants module, and two functions (`skeleton.build`, `validate.week`) with no I/O. `tri_planning.repo` is the only module that touches the four new tables and follows the tri-core repository convention (functions take an open connection, callers commit). The graph in Plan 3 composes these; nothing here imports LangChain.

**Tech Stack:** pydantic 2 models, psycopg 3 with `Jsonb`, pytest. Depends on Plan 1 (workspace, `tri_core.testing.fixtures.db`).

**Spec:** `docs/superpowers/specs/2026-09-07-tri-planning-design.md` (§5 Data model, §6.3 Models, §7 Planning logic, §10 Configuration, §11 Testing, §13 milestone 2).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- New package: distribution `tri-planning`, module `tri_planning`, console script `tri-planning`. It depends on `tri-core` and never on `tri_analyze`.
- Pins carried from the workspace: `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langchain-mcp-adapters==0.3.2`, `psycopg[binary]==3.3.5`. New: `langgraph-checkpoint-postgres>=3.1,<4`, `pyyaml>=6`. They are declared now so the lock is settled once, even though Plan 3 is the first to import them.
- Every constant from spec §7 lives in `periodization.py` and nowhere else: phase table, `8 %` ramp, `5` CTL points per week, recovery every `4th` week (`3rd` in Ironman build) at `60 %`, taper `80 / 60 / 45 %`, race week `30 %`, recovery goal `50 %`, intensity factors base `0.70` build `0.75` peak `0.80` taper `0.75` recovery `0.65`.
- Validator thresholds from spec §7.3: total TSS within `10 %` of target; structure step sum within `5 minutes` of session duration.
- **Brian runs every git command and applies every migration with `psql`, to both `tri_analyze` and `tri_analyze_test`.** Tests write only through the rolled-back `db` fixture.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`training_goals` gains three columns: `duration_weeks int`, `tp_plan_id text`, `create_tp_event boolean not null default false`.** Goals without a race (`build`, `maintenance`, `recovery`) need a length, and the spec's `TrainingGoal` model carries `tp_plan_id` and `create_tp_event` that the skeleton node reads in a later turn, possibly a later process. They must be persisted with the goal.
- **Race week uses intensity factor `0.75`** (the taper value). The spec table has no race-week IF.
- **The weekly-hours lower bound is only enforced on non-recovery base, build and peak weeks.** Forcing a recovery, taper or race week up to `weekly_hours_min` would defeat those weeks. The upper bound applies to every week.
- **`CalendarChange` gains `athlete_requested: bool = False`.** Spec §9 lets an ownership failure through when "the reason field contains an explicit athlete instruction". A typed flag set by the proposing tool is testable; sniffing prose is not. Plan 3 uses it.
- **Phase inference for bought plans (`infer_phases`) lives in `skeleton.py`** and is written now because it is pure and belongs with the other periodization logic.

---

## File Structure

```
packages/tri-planning/
  pyproject.toml
  README.md
  src/tri_planning/
    __init__.py
    config.py                 PlanningSettings(Settings): horizon weeks, LangSmith project
    cli.py                    typer app with a callback only (chat/check-in/reset arrive in Plans 3 and 4)
    repo.py                   planning-table reads and writes
    planning/
      __init__.py
      models.py               GoalType, Phase, Sport, Weekday, Intensity, TrainingGoal, WeekTarget,
                              PlannedSession, PlannedWeek, CalendarChange, ReviewDecision,
                              FitnessSnapshot, StoredGoal, StoredPlan, PlanWeekRow
      periodization.py        constants only
      skeleton.py             next_monday, count_weeks, allocate_phases, recovery_flags, week1_tss,
                              ctl_after_week, max_tss_for_ctl_rise, hours_for, tss_for, build, infer_phases
      validate.py             week(), structure_seconds(), sport_allowed()
  tests/
    test_config.py
    test_models.py
    test_skeleton.py
    test_validate.py
    test_repo.py              db-marked
migrations/002_planning.sql
```

Responsibilities: `models.py` is the vocabulary every other module shares. `periodization.py` is the tuning surface (change a number, rerun the tests). `skeleton.py` turns a goal into week targets and never looks at sessions. `validate.py` judges a designed week against its target and the goal and never changes it. `repo.py` is the only SQL.

---

### Task 1: Package scaffold, settings, migration

**Files:**
- Create: `packages/tri-planning/pyproject.toml`, `packages/tri-planning/README.md`, `packages/tri-planning/src/tri_planning/__init__.py`, `packages/tri-planning/src/tri_planning/planning/__init__.py`, `packages/tri-planning/src/tri_planning/config.py`, `packages/tri-planning/src/tri_planning/cli.py`, `migrations/002_planning.sql`
- Modify: root `pyproject.toml` (member dependency, source, mypy files), `.env.example`
- Test: `packages/tri-planning/tests/test_config.py`

**Interfaces:**
- Consumes: `tri_core.config.Settings` (Plan 1).
- Produces: `tri_planning.config.PlanningSettings` with `tri_planning_horizon_weeks: int = 3` and `tri_planning_langsmith_project: str = "tri-planning"`; `tri_planning.config.get_planning_settings() -> PlanningSettings`; `tri_planning.cli.app`.

- [ ] **Step 1: Write the failing test**

`packages/tri-planning/tests/test_config.py`:
```python
from tri_planning.config import PlanningSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_PLANNING_HORIZON_WEEKS", raising=False)
    s = PlanningSettings(_env_file=None)
    assert s.tri_planning_horizon_weeks == 3
    assert s.tri_planning_langsmith_project == "tri-planning"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_PLANNING_HORIZON_WEEKS", "2")
    assert PlanningSettings(_env_file=None).tri_planning_horizon_weeks == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-planning -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_planning'`.

- [ ] **Step 3: Create the package**

`packages/tri-planning/pyproject.toml`:
```toml
[project]
name = "tri-planning"
version = "0.1.0"
description = "Triathlon training planning agent: goal, periodized plan, TrainingPeaks calendar"
authors = [{ name = "Brian Flannery", email = "brian@paradigmshiftdev.io" }]
requires-python = ">=3.12,<3.13"
dependencies = [
    "tri-core",
    "langchain==1.4.0",
    "langchain-anthropic==1.7.1",
    "langchain-mcp-adapters==0.3.2",
    "langgraph-checkpoint-postgres>=3.1,<4",
    "psycopg[binary]==3.3.5",
    "pydantic-settings>=2.6",
    "pyyaml>=6",
    "typer>=0.15",
    "rich>=13",
]

[project.scripts]
tri-planning = "tri_planning.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tri_planning"]

[tool.uv.sources]
tri-core = { workspace = true }
```

`packages/tri-planning/src/tri_planning/__init__.py` and `planning/__init__.py`: empty files.

`packages/tri-planning/src/tri_planning/config.py`:
```python
"""Planning-agent settings: everything in tri_core.config plus the planning knobs."""

from functools import lru_cache

from tri_core.config import Settings


class PlanningSettings(Settings):
    tri_planning_horizon_weeks: int = 3
    tri_planning_langsmith_project: str = "tri-planning"


@lru_cache(maxsize=1)
def get_planning_settings() -> PlanningSettings:
    return PlanningSettings()
```

`packages/tri-planning/src/tri_planning/cli.py`:
```python
"""Command-line entry points for the planning agent."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Triathlon training planning agent", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Triathlon training planning agent."""


if __name__ == "__main__":
    app()
```

`packages/tri-planning/README.md`:
```markdown
# tri-planning

The planning agent: establishes a training goal, builds a periodized plan, writes sessions to
the TrainingPeaks calendar after approval, and adjusts the plan as training unfolds.
Design: `docs/superpowers/specs/2026-09-07-tri-planning-design.md`. Plans:
`docs/superpowers/plans/2026-09-07-tri-planning-0*.md`.
```

Root `pyproject.toml`: `dependencies = ["tri-core", "tri-analyze", "tri-planning"]`; add `tri-planning = { workspace = true }` under `[tool.uv.sources]`; mypy `files = ["packages/tri-core/src", "packages/tri-analyze/src", "packages/tri-planning/src"]`; add to `[[tool.mypy.overrides]]` module list `"yaml"` only if `types-PyYAML` is not installed (add `"types-PyYAML"` to the dev group instead, preferred).

`.env.example`: append
```
# tri-planning
TRI_PLANNING_HORIZON_WEEKS=3
TRI_PLANNING_LANGSMITH_PROJECT=tri-planning
```

- [ ] **Step 4: Write the migration**

`migrations/002_planning.sql`:
```sql
-- 002_planning.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists training_goals (
  id                serial primary key,
  goal_type         text not null,      -- sprint | olympic | half_ironman | ironman | maintenance | build | recovery
  event_name        text,
  event_date        date,               -- null for maintenance/build/recovery
  duration_weeks    int,                -- set for goals without an event
  tp_event_id       text,               -- set if we created the race event in TP
  priority          text,               -- A | B | C
  weekly_hours_min  numeric,
  weekly_hours_max  numeric,
  available_days    jsonb not null,     -- {"mon": ["swim"], "tue": ["bike","run"], "sat": "any", "sun": []}
  constraints       jsonb,              -- list of strings from intake
  tp_plan_id        text,               -- bought TrainingPeaks plan to activate instead of generating
  create_tp_event   boolean not null default false,
  status            text not null default 'active',   -- active | completed | abandoned
  created_at        timestamptz not null default now()
);

create table if not exists training_plans (
  id            serial primary key,
  goal_id       int not null references training_goals,
  source        text not null,          -- generated | tp_plan
  tp_plan_id    text,
  start_date    date not null,
  end_date      date not null,
  skeleton      jsonb not null,         -- [WeekTarget as JSON]
  status        text not null default 'active',   -- active | superseded | completed
  created_at    timestamptz not null default now()
);

create table if not exists plan_weeks (
  plan_id       int not null references training_plans,
  week_start    date not null,          -- Monday
  phase         text not null,          -- base | build | peak | taper | race | recovery
  target_tss    numeric,
  target_hours  numeric,
  designed      jsonb,                  -- validated PlannedWeek; null outside the rolling window
  written_to_tp boolean not null default false,
  primary key (plan_id, week_start)
);

create table if not exists plan_changes (
  id            serial primary key,
  plan_id       int references training_plans,
  thread_id     text not null,
  operation     text not null,          -- create | update | delete | move | apply_plan | create_event
  tp_workout_id text,
  workout_date  date,
  payload       jsonb not null,         -- exactly what we sent
  result        jsonb,                  -- exactly what TP returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index if not exists plan_changes_workout_idx on plan_changes (tp_workout_id);
```

- [ ] **Step 5: Sync, run the test, apply the migration (Brian)**

```bash
uv sync
uv run pytest packages/tri-planning -q
uv run tri-planning --help
```
Expected: 2 passed; `--help` prints the app description with no commands.

Brian applies the migration:
```bash
docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/002_planning.sql
docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/002_planning.sql
```

- [ ] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): package scaffold, settings, 002_planning migration"
```

---

### Task 2: Domain models

**Files:**
- Create: `packages/tri-planning/src/tri_planning/planning/models.py`
- Test: `packages/tri-planning/tests/test_models.py`

**Interfaces:**
- Produces (all in `tri_planning.planning.models`):
  - Type aliases `GoalType`, `Phase`, `Sport`, `Weekday`, `Intensity`, `Priority`, `Availability = dict[Weekday, list[Sport] | Literal["any"]]`; constants `WEEKDAYS: tuple[Weekday, ...]`, `RACE_GOALS: frozenset[str]`, `HARD_INTENSITIES: frozenset[str] = {"threshold", "vo2", "race"}`.
  - `TrainingGoal` (fields per spec §6.3 plus `duration_weeks: int | None`); validation: `weekly_hours_min <= weekly_hours_max`; race goals need `event_date`; other goals need `duration_weeks`; missing weekdays in `available_days` are filled with `[]`.
  - `WeekTarget(week_start, phase, target_tss, target_hours, is_recovery=False, flags=[], sport_hint="")`.
  - `PlannedSession`, `PlannedWeek`, `CalendarChange` per spec, plus `CalendarChange.athlete_requested: bool = False`.
  - `ReviewDecision(action: Literal["approve","reject","edit"], note: str | None = None, changes: list[CalendarChange] | None = None)`.
  - `FitnessSnapshot(ctl: float | None = None, recent_weekly_tss: float | None = None)`.
  - Storage shapes: `StoredGoal(id: int, goal: TrainingGoal, status: str, tp_event_id: str | None)`, `StoredPlan(id, goal_id, source, tp_plan_id, start_date, end_date, skeleton: list[WeekTarget], status)`, `PlanWeekRow(plan_id, week_start, phase, target_tss, target_hours, designed: PlannedWeek | None, written_to_tp: bool)`.
  - `PlannedSession.hours` property (`duration_minutes / 60`), `PlannedWeek.total_tss` and `PlannedWeek.total_hours` properties.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_models.py`:
```python
from datetime import date

import pytest
from pydantic import ValidationError

from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    ReviewDecision,
    TrainingGoal,
)


def goal(**over):
    base = dict(
        goal_type="olympic",
        event_name="City Tri",
        event_date=date(2026, 12, 13),
        priority="A",
        weekly_hours_min=6,
        weekly_hours_max=10,
        available_days={"mon": [], "tue": ["swim", "run"], "sat": "any"},
    )
    base.update(over)
    return TrainingGoal(**base)


def test_missing_weekdays_become_unavailable():
    g = goal()
    assert g.available_days["wed"] == []
    assert g.available_days["sat"] == "any"
    assert set(g.available_days) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_race_goal_requires_event_date():
    with pytest.raises(ValidationError, match="event_date"):
        goal(event_date=None)


def test_non_race_goal_requires_duration():
    with pytest.raises(ValidationError, match="duration_weeks"):
        goal(goal_type="build", event_date=None)
    g = goal(goal_type="build", event_date=None, duration_weeks=6)
    assert g.duration_weeks == 6


def test_hours_range_ordered():
    with pytest.raises(ValidationError, match="weekly_hours_min"):
        goal(weekly_hours_min=12, weekly_hours_max=10)


def test_week_totals():
    s1 = PlannedSession(
        date=date(2026, 9, 14), sport="bike", title="Endurance", description="z2",
        duration_minutes=90, tss_planned=70, intensity="endurance", structure=None,
    )
    s2 = PlannedSession(
        date=date(2026, 9, 15), sport="run", title="Tempo", description="",
        duration_minutes=60, tss_planned=65, intensity="tempo", structure=None,
    )
    w = PlannedWeek(week_start=date(2026, 9, 14), sessions=[s1, s2], coach_note="steady")
    assert w.total_tss == 135
    assert w.total_hours == 2.5


def test_calendar_change_roundtrip_json():
    c = CalendarChange(op="delete", tp_workout_id="123", reason="athlete asked", athlete_requested=True)
    again = CalendarChange.model_validate(c.model_dump(mode="json"))
    assert again == c


def test_review_decision_defaults():
    d = ReviewDecision(action="approve")
    assert d.note is None and d.changes is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_models.py -q`
Expected: `ImportError` on `tri_planning.planning.models`.

- [ ] **Step 3: Write the models**

`packages/tri-planning/src/tri_planning/planning/models.py`:
```python
"""Planning vocabulary shared by the skeleton builder, validator, repository and graph."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

GoalType = Literal["sprint", "olympic", "half_ironman", "ironman", "maintenance", "build", "recovery"]
Phase = Literal["base", "build", "peak", "taper", "race", "recovery"]
Sport = Literal["swim", "bike", "run", "brick", "strength", "rest"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Intensity = Literal["recovery", "endurance", "tempo", "threshold", "vo2", "race"]
Priority = Literal["A", "B", "C"]
Availability = dict[Weekday, list[Sport] | Literal["any"]]

WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RACE_GOALS: frozenset[str] = frozenset({"sprint", "olympic", "half_ironman", "ironman"})
HARD_INTENSITIES: frozenset[str] = frozenset({"threshold", "vo2", "race"})


class TrainingGoal(BaseModel):
    goal_type: GoalType
    event_name: str | None = None
    event_date: date | None = None
    priority: Priority | None = None
    weekly_hours_min: float = Field(ge=0)
    weekly_hours_max: float = Field(gt=0)
    available_days: Availability
    constraints: list[str] = Field(default_factory=list)
    tp_plan_id: str | None = None
    create_tp_event: bool = False
    duration_weeks: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> TrainingGoal:
        if self.weekly_hours_min > self.weekly_hours_max:
            raise ValueError("weekly_hours_min must be <= weekly_hours_max")
        if self.goal_type in RACE_GOALS and self.event_date is None:
            raise ValueError(f"{self.goal_type} goals need an event_date")
        if self.goal_type not in RACE_GOALS and self.duration_weeks is None:
            raise ValueError(f"{self.goal_type} goals need duration_weeks")
        for day in WEEKDAYS:
            self.available_days.setdefault(day, [])
        return self


class WeekTarget(BaseModel):
    week_start: date
    phase: Phase
    target_tss: float
    target_hours: float
    is_recovery: bool = False
    flags: list[str] = Field(default_factory=list)
    sport_hint: str = ""


class PlannedSession(BaseModel):
    date: date
    sport: Sport
    title: str
    description: str
    duration_minutes: int = Field(ge=0)
    tss_planned: float = Field(ge=0)
    intensity: Intensity
    structure: dict[str, Any] | None = None

    @property
    def hours(self) -> float:
        return self.duration_minutes / 60


class PlannedWeek(BaseModel):
    week_start: date
    sessions: list[PlannedSession]
    coach_note: str

    @property
    def total_tss(self) -> float:
        return sum(s.tss_planned for s in self.sessions)

    @property
    def total_hours(self) -> float:
        return sum(s.hours for s in self.sessions)


class CalendarChange(BaseModel):
    op: Literal["create", "update", "delete", "move", "apply_plan", "create_event"]
    workout_date: date | None = None
    tp_workout_id: str | None = None
    workout: PlannedSession | None = None
    new_date: date | None = None
    payload: dict[str, Any] | None = None
    reason: str
    athlete_requested: bool = False


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    changes: list[CalendarChange] | None = None


class FitnessSnapshot(BaseModel):
    ctl: float | None = None
    recent_weekly_tss: float | None = None


class StoredGoal(BaseModel):
    id: int
    goal: TrainingGoal
    status: str
    tp_event_id: str | None = None


class StoredPlan(BaseModel):
    id: int
    goal_id: int
    source: Literal["generated", "tp_plan"]
    tp_plan_id: str | None
    start_date: date
    end_date: date
    skeleton: list[WeekTarget]
    status: str


class PlanWeekRow(BaseModel):
    plan_id: int
    week_start: date
    phase: Phase
    target_tss: float | None
    target_hours: float | None
    designed: PlannedWeek | None
    written_to_tp: bool
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/tri-planning/tests/test_models.py -q`
Expected: 7 passed.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): domain models"
```

---

### Task 3: Periodization constants and the skeleton builder

**What this teaches:** the deterministic half of "Python owns periodization; the LLM designs sessions within those bounds." Every number an athlete might want to tune is in one file, and the builder is a pure function you can test row by row against the spec table.

**Files:**
- Create: `packages/tri-planning/src/tri_planning/planning/periodization.py`, `packages/tri-planning/src/tri_planning/planning/skeleton.py`
- Test: `packages/tri-planning/tests/test_skeleton.py`

**Interfaces:**
- Consumes: `TrainingGoal`, `FitnessSnapshot`, `WeekTarget`, `GoalType`, `Phase` from Task 2.
- Produces:
  - `periodization.PhaseSpec(race, taper, peak, build, minimum_weeks, shape)` and `PHASE_TABLE: dict[GoalType, PhaseSpec]`; all constants named in Global Constraints; `SPORT_HINTS: dict[Phase, str]`; `FLAG_COMPRESSED = "compressed"`, `FLAG_HOURS_CAPPED = "hours_capped"`; `PEAK_PLATEAU_FRACTION = 0.9`.
  - `skeleton.next_monday(today: date) -> date` (today if Monday).
  - `skeleton.week_monday(d: date) -> date`.
  - `skeleton.count_weeks(goal, start) -> int`.
  - `skeleton.allocate_phases(goal_type, total_weeks) -> tuple[list[Phase], bool]` (phases in chronological order, `compressed`).
  - `skeleton.recovery_flags(goal_type, phases) -> list[bool]`.
  - `skeleton.week1_tss(goal_type, fitness) -> float`.
  - `skeleton.ctl_after_week(ctl, weekly_tss) -> float`, `skeleton.max_tss_for_ctl_rise(ctl) -> float`.
  - `skeleton.hours_for(tss, phase) -> float`, `skeleton.tss_for(hours, phase) -> float`.
  - `skeleton.build(goal, fitness, start: date) -> list[WeekTarget]` (raises `ValueError` if `start` is not a Monday or the goal has too few weeks).
  - `skeleton.infer_phases(weekly_tss: list[float]) -> list[Phase]`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_skeleton.py`:
```python
from datetime import date, timedelta

import pytest

from tri_planning.planning import periodization as P
from tri_planning.planning import skeleton
from tri_planning.planning.models import FitnessSnapshot, TrainingGoal

MONDAY = date(2026, 9, 14)
ALL_DAYS = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def race_goal(goal_type: str, weeks: int, **over) -> TrainingGoal:
    base = dict(
        goal_type=goal_type,
        event_name="Race",
        event_date=MONDAY + timedelta(weeks=weeks - 1, days=6),  # Sunday of the last week
        priority="A",
        weekly_hours_min=0,
        weekly_hours_max=30,
        available_days=ALL_DAYS,
    )
    base.update(over)
    return TrainingGoal(**base)


def flat_goal(goal_type: str, weeks: int, **over) -> TrainingGoal:
    base = dict(
        goal_type=goal_type,
        weekly_hours_min=0,
        weekly_hours_max=30,
        available_days=ALL_DAYS,
        duration_weeks=weeks,
    )
    base.update(over)
    return TrainingGoal(**base)


FIT = FitnessSnapshot(ctl=50, recent_weekly_tss=350)


def test_next_monday():
    assert skeleton.next_monday(date(2026, 9, 14)) == date(2026, 9, 14)  # a Monday
    assert skeleton.next_monday(date(2026, 9, 16)) == date(2026, 9, 21)
    assert skeleton.next_monday(date(2026, 9, 20)) == date(2026, 9, 21)


def test_count_weeks_inclusive_of_race_week():
    assert skeleton.count_weeks(race_goal("sprint", 10), MONDAY) == 10
    assert skeleton.count_weeks(flat_goal("build", 6), MONDAY) == 6


@pytest.mark.parametrize(
    "goal_type,total,expected",
    [
        ("sprint", 10, {"base": 2, "build": 4, "peak": 2, "taper": 1, "race": 1}),
        ("olympic", 14, {"base": 4, "build": 5, "peak": 3, "taper": 1, "race": 1}),
        ("half_ironman", 20, {"base": 8, "build": 6, "peak": 3, "taper": 2, "race": 1}),
        ("ironman", 24, {"base": 8, "build": 8, "peak": 4, "taper": 3, "race": 1}),
        ("build", 6, {"build": 6}),
        ("maintenance", 4, {"base": 4}),
        ("recovery", 2, {"recovery": 2}),
    ],
)
def test_phase_table_rows(goal_type, total, expected):
    phases, compressed = skeleton.allocate_phases(goal_type, total)
    counts = {p: phases.count(p) for p in set(phases)}
    assert counts == expected
    assert compressed is False
    # chronological order: base, build, peak, taper, race
    order = ["base", "build", "peak", "taper", "race", "recovery"]
    assert phases == sorted(phases, key=order.index)


def test_compression_drops_base_then_build():
    phases, compressed = skeleton.allocate_phases("sprint", 7)  # minimum is 8
    assert compressed is True
    assert phases.count("base") == 0
    assert phases.count("build") == 3
    assert phases[-4:] == ["peak", "peak", "taper", "race"]


def test_too_few_weeks_raises():
    with pytest.raises(ValueError, match="at least 4 weeks"):
        skeleton.allocate_phases("sprint", 3)  # peak 2 + taper 1 + race 1


def test_recovery_every_fourth_week_in_base_and_build_only():
    phases, _ = skeleton.allocate_phases("olympic", 14)  # 4 base, 5 build, 3 peak, 1 taper, 1 race
    flags = skeleton.recovery_flags("olympic", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7]
    assert not any(flags[9:])


def test_ironman_build_recovers_every_third_week():
    phases, _ = skeleton.allocate_phases("ironman", 24)  # 8 base, 8 build
    flags = skeleton.recovery_flags("ironman", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7, 10, 13]


def test_week1_fallback_chain():
    assert skeleton.week1_tss("sprint", FitnessSnapshot(ctl=50, recent_weekly_tss=350)) == 350
    assert skeleton.week1_tss("sprint", FitnessSnapshot(ctl=50)) == 350
    assert skeleton.week1_tss("ironman", FitnessSnapshot()) == P.GOAL_FLOOR_TSS["ironman"]


def test_ramp_is_capped_at_eight_percent():
    weeks = skeleton.build(race_goal("sprint", 10), FIT, MONDAY)
    assert [w.phase for w in weeks[:2]] == ["base", "base"]
    assert weeks[0].target_tss == 350
    assert weeks[1].target_tss == pytest.approx(350 * 1.08, abs=1)
    assert weeks[2].target_tss == pytest.approx(350 * 1.08**2, abs=1)


def test_ctl_cap_binds_before_ramp_when_ctl_is_low():
    fit = FitnessSnapshot(ctl=10, recent_weekly_tss=350)
    weeks = skeleton.build(race_goal("sprint", 10), fit, MONDAY)
    assert weeks[1].target_tss < 350 * 1.08
    # the cap for week 2 uses the CTL modeled after week 1's load, not the starting CTL
    ctl_after_w1 = skeleton.ctl_after_week(10, 350)
    assert weeks[1].target_tss == pytest.approx(skeleton.max_tss_for_ctl_rise(ctl_after_w1), abs=1)


def test_recovery_week_is_sixty_percent_and_ramp_resumes_from_last_load():
    weeks = skeleton.build(race_goal("olympic", 14), FIT, MONDAY)
    assert weeks[3].is_recovery
    assert weeks[3].target_tss == pytest.approx(weeks[2].target_tss * 0.6, abs=1)
    assert weeks[4].target_tss == pytest.approx(weeks[2].target_tss * 1.08, abs=1)


def test_peak_taper_race_factors():
    weeks = skeleton.build(race_goal("ironman", 24), FIT, MONDAY)
    by_phase = {}
    for w in weeks:
        by_phase.setdefault(w.phase, []).append(w)
    peak = by_phase["peak"][0].target_tss
    assert all(w.target_tss == peak for w in by_phase["peak"])
    assert [w.target_tss for w in by_phase["taper"]] == [
        pytest.approx(peak * f, abs=1) for f in (0.80, 0.60, 0.45)
    ]
    assert by_phase["race"][0].target_tss == pytest.approx(peak * 0.30, abs=1)
    assert by_phase["peak"][0].sport_hint == P.SPORT_HINTS["peak"]


def test_maintenance_flat_and_recovery_goal_half():
    m = skeleton.build(flat_goal("maintenance", 4), FIT, MONDAY)
    assert {w.target_tss for w in m} == {350}
    r = skeleton.build(flat_goal("recovery", 2), FIT, MONDAY)
    assert {w.target_tss for w in r} == {175}
    assert {w.phase for w in r} == {"recovery"}


def test_hours_cap_recomputes_tss_and_flags():
    g = race_goal("sprint", 10, weekly_hours_max=5)
    w = skeleton.build(g, FIT, MONDAY)[0]  # base, IF 0.70: 350 TSS would be 7.1 h
    assert w.target_hours == 5
    assert w.target_tss == pytest.approx(5 * 0.70**2 * 100, abs=1)
    assert P.FLAG_HOURS_CAPPED in w.flags


def test_hours_floor_not_applied_to_recovery_taper_race():
    g = race_goal("olympic", 14, weekly_hours_min=8, weekly_hours_max=30)
    weeks = skeleton.build(g, FIT, MONDAY)
    assert weeks[0].target_hours == 8 and P.FLAG_HOURS_CAPPED in weeks[0].flags
    rec = weeks[3]
    assert rec.is_recovery and rec.target_hours < 8
    assert weeks[-1].phase == "race" and weeks[-1].target_hours < 8


def test_compressed_flag_on_every_week():
    weeks = skeleton.build(race_goal("sprint", 7), FIT, MONDAY)
    assert all(P.FLAG_COMPRESSED in w.flags for w in weeks)


def test_build_requires_monday():
    with pytest.raises(ValueError, match="Monday"):
        skeleton.build(race_goal("sprint", 10), FIT, MONDAY + timedelta(days=1))


def test_week_dates_are_consecutive_mondays():
    weeks = skeleton.build(race_goal("sprint", 10), FIT, MONDAY)
    assert [w.week_start for w in weeks] == [MONDAY + timedelta(weeks=i) for i in range(10)]


def test_infer_phases_from_load_curve():
    curve = [300, 320, 340, 360, 380, 390, 400, 320, 250, 120]
    assert skeleton.infer_phases(curve) == [
        "build", "build", "build", "peak", "peak", "peak", "peak", "taper", "taper", "race"
    ]
    assert skeleton.infer_phases([200]) == ["race"]
    assert skeleton.infer_phases([]) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_skeleton.py -q`
Expected: `ImportError` for `periodization`.

- [ ] **Step 3: Write `periodization.py`**

```python
"""Every periodization constant. Change numbers here; the tests in test_skeleton.py pin them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tri_planning.planning.models import GoalType, Phase


@dataclass(frozen=True)
class PhaseSpec:
    race: int
    taper: int
    peak: int
    build: int
    minimum_weeks: int
    shape: Literal["remaining", "all_build", "all_base", "all_recovery"]


# Spec §7.1. "remaining" means: base takes whatever is left after the fixed phases.
PHASE_TABLE: dict[GoalType, PhaseSpec] = {
    "sprint": PhaseSpec(race=1, taper=1, peak=2, build=4, minimum_weeks=8, shape="remaining"),
    "olympic": PhaseSpec(race=1, taper=1, peak=3, build=5, minimum_weeks=12, shape="remaining"),
    "half_ironman": PhaseSpec(race=1, taper=2, peak=3, build=6, minimum_weeks=16, shape="remaining"),
    "ironman": PhaseSpec(race=1, taper=3, peak=4, build=8, minimum_weeks=20, shape="remaining"),
    "build": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=4, shape="all_build"),
    "maintenance": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=2, shape="all_base"),
    "recovery": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=1, shape="all_recovery"),
}

# Spec §7.2 load progression.
MAX_WEEKLY_RAMP = 0.08
MAX_CTL_RISE_PER_WEEK = 5.0
CTL_TIME_CONSTANT_DAYS = 42
RECOVERY_EVERY_N_WEEKS = 4
IRONMAN_BUILD_RECOVERY_EVERY_N_WEEKS = 3
RECOVERY_WEEK_FACTOR = 0.60
TAPER_FACTORS: tuple[float, ...] = (0.80, 0.60, 0.45)
RACE_WEEK_FACTOR = 0.30
RECOVERY_GOAL_FACTOR = 0.50

# Week-1 floor when there is no recent load and no CTL.
GOAL_FLOOR_TSS: dict[GoalType, float] = {
    "sprint": 250,
    "olympic": 300,
    "half_ironman": 350,
    "ironman": 400,
    "build": 300,
    "maintenance": 250,
    "recovery": 200,
}

# Assumed intensity factor per phase: TSS = hours * IF^2 * 100.
PHASE_IF: dict[Phase, float] = {
    "base": 0.70,
    "build": 0.75,
    "peak": 0.80,
    "taper": 0.75,
    "race": 0.75,
    "recovery": 0.65,
}

SPORT_HINTS: dict[Phase, str] = {
    "base": "Swim and run frequency first; bike is aerobic and steady. Mostly endurance intensity, "
    "one tempo session at most.",
    "build": "Bike volume grows and one brick (bike into run) appears each week. One threshold "
    "session per sport at most, never on consecutive days.",
    "peak": "Race-specific: bricks at race pace, race-pace intervals in each sport. Hold volume, "
    "raise intensity.",
    "taper": "Keep session frequency, cut duration sharply. Short race-pace touches only.",
    "race": "Openers early in the week, rest the two days before, the race itself is not planned "
    "here.",
    "recovery": "Easy, short, optional. No intensity above endurance.",
}

FLAG_COMPRESSED = "compressed"
FLAG_HOURS_CAPPED = "hours_capped"

# Bought-plan phase inference: weeks at or above this fraction of the max are "peak".
PEAK_PLATEAU_FRACTION = 0.9
```

- [ ] **Step 4: Write `skeleton.py`**

```python
"""Goal + fitness -> week targets. Pure: no I/O, no model calls."""

from __future__ import annotations

from datetime import date, timedelta

from tri_planning.planning import periodization as P
from tri_planning.planning.models import (
    FitnessSnapshot,
    GoalType,
    Phase,
    TrainingGoal,
    WeekTarget,
)

_DECAY = (1 - 1 / P.CTL_TIME_CONSTANT_DAYS) ** 7  # CTL carry-over across one week of constant load


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7)


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def count_weeks(goal: TrainingGoal, start: date) -> int:
    if goal.event_date is not None:
        n = (week_monday(goal.event_date) - start).days // 7 + 1
        if n < 1:
            raise ValueError("event_date is before the plan start")
        return n
    assert goal.duration_weeks is not None  # enforced by TrainingGoal
    return goal.duration_weeks


def allocate_phases(goal_type: GoalType, total_weeks: int) -> tuple[list[Phase], bool]:
    spec = P.PHASE_TABLE[goal_type]
    compressed = total_weeks < spec.minimum_weeks
    if spec.shape == "all_build":
        return ["build"] * total_weeks, compressed
    if spec.shape == "all_base":
        return ["base"] * total_weeks, compressed
    if spec.shape == "all_recovery":
        return ["recovery"] * total_weeks, compressed
    fixed_tail = spec.race + spec.taper + spec.peak
    build = min(spec.build, total_weeks - fixed_tail)
    if build < 0:
        raise ValueError(
            f"{goal_type} needs at least {fixed_tail} weeks for peak, taper and race; "
            f"got {total_weeks}"
        )
    base = total_weeks - fixed_tail - build
    phases: list[Phase] = (
        ["base"] * base
        + ["build"] * build
        + ["peak"] * spec.peak
        + ["taper"] * spec.taper
        + ["race"] * spec.race
    )
    return phases, compressed


def recovery_flags(goal_type: GoalType, phases: list[Phase]) -> list[bool]:
    flags: list[bool] = []
    since = 0
    for phase in phases:
        if phase not in ("base", "build"):
            flags.append(False)
            since = 0
            continue
        since += 1
        cadence = (
            P.IRONMAN_BUILD_RECOVERY_EVERY_N_WEEKS
            if goal_type == "ironman" and phase == "build"
            else P.RECOVERY_EVERY_N_WEEKS
        )
        if since >= cadence:
            flags.append(True)
            since = 0
        else:
            flags.append(False)
    return flags


def week1_tss(goal_type: GoalType, fitness: FitnessSnapshot) -> float:
    if fitness.recent_weekly_tss:
        return float(fitness.recent_weekly_tss)
    if fitness.ctl:
        return 7 * float(fitness.ctl)
    return P.GOAL_FLOOR_TSS[goal_type]


def ctl_after_week(ctl: float, weekly_tss: float) -> float:
    daily = weekly_tss / 7
    return daily + (ctl - daily) * _DECAY


def max_tss_for_ctl_rise(ctl: float) -> float:
    """Largest weekly TSS whose modeled CTL rise over the week is <= MAX_CTL_RISE_PER_WEEK."""
    return 7 * (ctl + P.MAX_CTL_RISE_PER_WEEK / (1 - _DECAY))


def hours_for(tss: float, phase: Phase) -> float:
    return tss / (P.PHASE_IF[phase] ** 2 * 100)


def tss_for(hours: float, phase: Phase) -> float:
    return hours * P.PHASE_IF[phase] ** 2 * 100


def _clamp_hours(
    tss: float, phase: Phase, goal: TrainingGoal, apply_min: bool
) -> tuple[float, float, bool]:
    hours = hours_for(tss, phase)
    lo = goal.weekly_hours_min if apply_min else 0.0
    hi = goal.weekly_hours_max
    if hours > hi:
        return tss_for(hi, phase), hi, True
    if hours < lo:
        return tss_for(lo, phase), lo, True
    return tss, hours, False


def build(goal: TrainingGoal, fitness: FitnessSnapshot, start: date) -> list[WeekTarget]:
    if start.weekday() != 0:
        raise ValueError("start must be a Monday")
    total = count_weeks(goal, start)
    phases, compressed = allocate_phases(goal.goal_type, total)
    recovery = recovery_flags(goal.goal_type, phases)
    w1 = week1_tss(goal.goal_type, fitness)
    ctl = float(fitness.ctl) if fitness.ctl else w1 / 7
    last_load: float | None = None  # last non-recovery base/build week, after clamping
    peak_load: float | None = None
    taper_i = 0
    out: list[WeekTarget] = []
    for i, (phase, is_rec) in enumerate(zip(phases, recovery, strict=True)):
        if goal.goal_type == "maintenance":
            tss = w1
        elif goal.goal_type == "recovery":
            tss = w1 * P.RECOVERY_GOAL_FACTOR
        elif phase in ("base", "build"):
            if last_load is None:
                tss = w1
            elif is_rec:
                tss = last_load * P.RECOVERY_WEEK_FACTOR
            else:
                tss = min(last_load * (1 + P.MAX_WEEKLY_RAMP), max_tss_for_ctl_rise(ctl))
        else:
            if peak_load is None:
                peak_load = last_load if last_load is not None else w1
            if phase == "peak":
                tss = peak_load
            elif phase == "taper":
                tss = peak_load * P.TAPER_FACTORS[min(taper_i, len(P.TAPER_FACTORS) - 1)]
                taper_i += 1
            else:  # race
                tss = peak_load * P.RACE_WEEK_FACTOR
        apply_min = phase in ("base", "build", "peak") and not is_rec
        tss, hours, capped = _clamp_hours(tss, phase, goal, apply_min)
        if phase in ("base", "build") and not is_rec:
            last_load = tss
        flags: list[str] = []
        if compressed:
            flags.append(P.FLAG_COMPRESSED)
        if capped:
            flags.append(P.FLAG_HOURS_CAPPED)
        out.append(
            WeekTarget(
                week_start=start + timedelta(weeks=i),
                phase=phase,
                target_tss=round(tss),
                target_hours=round(hours, 1),
                is_recovery=is_rec,
                flags=flags,
                sport_hint=P.SPORT_HINTS[phase],
            )
        )
        ctl = ctl_after_week(ctl, tss)
    return out


def infer_phases(weekly_tss: list[float]) -> list[Phase]:
    """Phases for a bought plan from its weekly planned TSS: rising = build, plateau = peak,
    falling into the event = taper, last week = race."""
    n = len(weekly_tss)
    if n == 0:
        return []
    if n == 1:
        return ["race"]
    peak = max(weekly_tss[:-1])
    m = weekly_tss.index(peak)
    phases: list[Phase] = []
    for i, tss in enumerate(weekly_tss):
        if i == n - 1:
            phases.append("race")
        elif i > m:
            phases.append("taper")
        elif tss >= P.PEAK_PLATEAU_FRACTION * peak:
            phases.append("peak")
        else:
            phases.append("build")
    return phases
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_skeleton.py -q`
Expected: all pass. If `test_hours_floor_not_applied_to_recovery_taper_race` fails on the recovery week, check that the recovery week's TSS (about `0.6 * 408 = 245`, `3.4 h` at IF 0.75... at IF 0.70 base it is `5.0 h`) is below the 8 h floor; it is.

- [ ] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): periodization constants and skeleton builder"
```

---

### Task 4: Week validator

**Files:**
- Create: `packages/tri-planning/src/tri_planning/planning/validate.py`
- Test: `packages/tri-planning/tests/test_validate.py`

**Interfaces:**
- Consumes: `PlannedWeek`, `WeekTarget`, `TrainingGoal`, `HARD_INTENSITIES`, `WEEKDAYS` from Task 2.
- Produces:
  - `validate.structure_seconds(structure: dict[str, Any]) -> int` (sums `duration_seconds`, repetition blocks multiply by `reps`).
  - `validate.sport_allowed(sport: Sport, allowed: list[Sport] | Literal["any"]) -> bool` (`rest` always allowed; `brick` needs both `bike` and `run`).
  - `validate.week(planned: PlannedWeek, target: WeekTarget, goal: TrainingGoal) -> list[str]` (empty list means valid).
  - Constants `TSS_TOLERANCE = 0.10`, `STRUCTURE_TOLERANCE_MIN = 5`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_validate.py`:
```python
from datetime import date, timedelta

from tri_planning.planning import validate
from tri_planning.planning.models import PlannedSession, PlannedWeek, TrainingGoal, WeekTarget

MON = date(2026, 9, 14)


def goal(**over) -> TrainingGoal:
    base = dict(
        goal_type="olympic",
        event_date=date(2026, 12, 13),
        weekly_hours_min=0,
        weekly_hours_max=10,
        available_days={d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
    )
    base.update(over)
    return TrainingGoal(**base)


def target(tss=300.0, hours=6.0) -> WeekTarget:
    return WeekTarget(week_start=MON, phase="build", target_tss=tss, target_hours=hours)


def session(day=0, sport="bike", minutes=60, tss=50.0, intensity="endurance", structure=None):
    return PlannedSession(
        date=MON + timedelta(days=day), sport=sport, title="s", description="",
        duration_minutes=minutes, tss_planned=tss, intensity=intensity, structure=structure,
    )


def week(*sessions) -> PlannedWeek:
    return PlannedWeek(week_start=MON, sessions=list(sessions), coach_note="")


def test_valid_week_has_no_violations():
    w = week(session(0), session(2), session(4), session(5, tss=150, minutes=180))
    assert validate.week(w, target(), goal()) == []


def test_tss_outside_ten_percent():
    w = week(session(0, tss=100), session(2, tss=100))  # 200 vs 300
    out = validate.week(w, target(), goal())
    assert any("TSS" in v and "300" in v for v in out)
    ok = week(session(0, tss=140), session(2, tss=140))  # 280, within 10 %
    assert not any("TSS" in v for v in validate.week(ok, target(), goal()))


def test_session_on_unavailable_day():
    g = goal(available_days={"mon": []})
    out = validate.week(week(session(0, tss=300)), target(), g)
    assert any("mon" in v and "unavailable" in v for v in out)


def test_sport_not_allowed_that_day():
    g = goal(available_days={"tue": ["swim"]})
    out = validate.week(week(session(1, sport="run", tss=300)), target(), g)
    assert any("run" in v and "tue" in v for v in out)


def test_rest_and_brick_rules():
    assert validate.sport_allowed("rest", [])
    assert validate.sport_allowed("brick", ["bike", "run"])
    assert not validate.sport_allowed("brick", ["bike"])
    assert validate.sport_allowed("brick", "any")


def test_consecutive_hard_days():
    w = week(session(0, intensity="threshold", tss=150), session(1, intensity="vo2", tss=150))
    out = validate.week(w, target(), goal())
    assert any("consecutive" in v for v in out)
    spaced = week(session(0, intensity="threshold", tss=150), session(2, intensity="race", tss=150))
    assert not any("consecutive" in v for v in validate.week(spaced, target(), goal()))


def test_hours_over_weekly_max():
    w = week(session(0, minutes=400, tss=150), session(2, minutes=300, tss=150))  # 11.7 h > 10
    out = validate.week(w, target(), goal())
    assert any("hours" in v and "10" in v for v in out)


def test_structure_must_match_duration_within_five_minutes():
    structure = {
        "primaryIntensityMetric": "percentOfFtp",
        "steps": [
            {"name": "wu", "duration_seconds": 600, "intensity_min": 50, "intensity_max": 60},
            {"type": "repetition", "reps": 4, "steps": [
                {"name": "on", "duration_seconds": 300, "intensity_min": 95, "intensity_max": 105},
                {"name": "off", "duration_seconds": 180, "intensity_min": 50, "intensity_max": 60},
            ]},
        ],
    }
    assert validate.structure_seconds(structure) == 600 + 4 * 480
    good = week(session(0, minutes=42, tss=300, structure=structure))
    assert not any("structure" in v for v in validate.week(good, target(), goal()))
    bad = week(session(0, minutes=60, tss=300, structure=structure))
    assert any("structure" in v for v in validate.week(bad, target(), goal()))


def test_session_outside_week():
    out = validate.week(week(session(7, tss=300)), target(), goal())
    assert any("outside" in v for v in out)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_validate.py -q`
Expected: `ImportError`.

- [ ] **Step 3: Write `validate.py`**

```python
"""Judge a designed week against its target and the athlete's constraints. Pure."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from tri_planning.planning.models import (
    HARD_INTENSITIES,
    WEEKDAYS,
    PlannedWeek,
    Sport,
    TrainingGoal,
    WeekTarget,
)

TSS_TOLERANCE = 0.10
STRUCTURE_TOLERANCE_MIN = 5


def structure_seconds(structure: dict[str, Any]) -> int:
    total = 0
    for step in structure.get("steps", []):
        if step.get("type") == "repetition":
            inner = sum(int(s["duration_seconds"]) for s in step.get("steps", []))
            total += int(step.get("reps", 1)) * inner
        else:
            total += int(step["duration_seconds"])
    return total


def sport_allowed(sport: Sport, allowed: list[Sport] | Literal["any"]) -> bool:
    if sport == "rest" or allowed == "any":
        return True
    if sport == "brick":
        return "bike" in allowed and "run" in allowed
    return sport in allowed


def week(planned: PlannedWeek, target: WeekTarget, goal: TrainingGoal) -> list[str]:
    out: list[str] = []
    week_end = planned.week_start + timedelta(days=6)

    total = planned.total_tss
    if target.target_tss and abs(total - target.target_tss) > TSS_TOLERANCE * target.target_tss:
        out.append(f"total TSS {total:.0f} is more than 10% from target {target.target_tss:.0f}")

    for s in planned.sessions:
        if not planned.week_start <= s.date <= week_end:
            out.append(f"{s.date} {s.sport}: outside the week starting {planned.week_start}")
            continue
        day = WEEKDAYS[s.date.weekday()]
        allowed = goal.available_days[day]
        if allowed != "any" and not allowed and s.sport != "rest":
            out.append(f"{s.date} ({day}) is unavailable but has {s.sport}")
        elif not sport_allowed(s.sport, allowed):
            out.append(f"{s.date} ({day}) does not allow {s.sport}; allowed: {allowed}")
        if s.structure is not None:
            secs = structure_seconds(s.structure)
            if abs(secs / 60 - s.duration_minutes) > STRUCTURE_TOLERANCE_MIN:
                out.append(
                    f"{s.date} {s.title}: structure sums to {secs // 60} min but duration is "
                    f"{s.duration_minutes} min"
                )

    hard_days = sorted({s.date for s in planned.sessions if s.intensity in HARD_INTENSITIES})
    for a, b in zip(hard_days, hard_days[1:], strict=False):
        if (b - a).days == 1:
            out.append(f"hard sessions on consecutive days {a} and {b}")

    hours = planned.total_hours
    if hours > goal.weekly_hours_max:
        out.append(f"total hours {hours:.1f} exceed weekly max {goal.weekly_hours_max:g}")
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_validate.py -q`
Expected: 10 passed.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): week validator"
```

---

### Task 5: Planning repository

**What this teaches:** the same repository convention as tri-core (functions over an open connection, callers commit) applied to JSON-heavy rows, and how ownership of calendar workouts is derived from the audit table rather than stored separately.

**Files:**
- Create: `packages/tri-planning/src/tri_planning/repo.py`
- Test: `packages/tri-planning/tests/test_repo.py`

**Interfaces:**
- Consumes: `tri_core.db.repo.Conn`, models from Task 2, the `db` fixture.
- Produces (all in `tri_planning.repo`, every function takes `conn: Conn` first):
  - `insert_goal(conn, goal: TrainingGoal) -> int`
  - `get_goal(conn, goal_id: int) -> StoredGoal | None`
  - `get_active_goal(conn) -> StoredGoal | None` (newest active)
  - `set_goal_event(conn, goal_id: int, tp_event_id: str) -> None`
  - `insert_plan(conn, goal_id: int, source: str, tp_plan_id: str | None, skeleton: list[WeekTarget]) -> int` (also inserts one `plan_weeks` row per target)
  - `get_plan(conn, plan_id: int) -> StoredPlan | None`
  - `get_active_plan(conn, goal_id: int) -> StoredPlan | None`
  - `list_weeks(conn, plan_id: int) -> list[PlanWeekRow]` ordered by `week_start`
  - `set_week_designed(conn, plan_id: int, week_start: date, week: PlannedWeek) -> None`
  - `mark_weeks_written(conn, plan_id: int, week_starts: list[date]) -> None`
  - `insert_change(conn, plan_id: int | None, thread_id: str, change: CalendarChange, *, tp_workout_id: str | None, result: dict[str, Any] | None) -> int`
  - `owned_workout_ids(conn, plan_id: int) -> set[str]` (ids from `create`/`apply_plan` rows minus ids from `delete` rows)
  - `abandon_active(conn) -> tuple[int, int]` (goals set `abandoned`, plans set `superseded`; returns counts)
  - `fitness_snapshot(conn, as_of: date) -> FitnessSnapshot` (latest non-null `ctl` on or before `as_of`; mean weekly `tss_day` over the 28 days ending the day before `as_of`, `None` when no rows)
  - `athlete_thresholds(conn) -> dict[str, Any] | None` (the `athlete_profile` row's thresholds and zone tables)

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_repo.py`:
```python
from datetime import date, timedelta

import pytest

from tri_core.db import repo as core_repo
from tri_core.db.models import DailyMetricsRow
from tri_planning import repo
from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    TrainingGoal,
    WeekTarget,
)

pytestmark = pytest.mark.db

MON = date(2026, 9, 14)


@pytest.fixture
def pdb(db):
    if db.execute("select to_regclass('training_goals') as t").fetchone()["t"] is None:
        pytest.skip("migrations/002_planning.sql not applied to the test database")
    return db


def goal(**over) -> TrainingGoal:
    base = dict(
        goal_type="olympic",
        event_name="City Tri",
        event_date=date(2026, 12, 13),
        priority="A",
        weekly_hours_min=6,
        weekly_hours_max=10,
        available_days={"mon": [], "sat": "any"},
        constraints=["pool closed Fridays"],
    )
    base.update(over)
    return TrainingGoal(**base)


def targets(n=3):
    return [
        WeekTarget(week_start=MON + timedelta(weeks=i), phase="base", target_tss=300 + i,
                   target_hours=6, sport_hint="h")
        for i in range(n)
    ]


def test_goal_roundtrip(pdb):
    gid = repo.insert_goal(pdb, goal())
    stored = repo.get_goal(pdb, gid)
    assert stored is not None and stored.id == gid and stored.status == "active"
    assert stored.goal.available_days["mon"] == [] and stored.goal.available_days["sat"] == "any"
    assert stored.goal.constraints == ["pool closed Fridays"]
    assert repo.get_active_goal(pdb).id == gid
    repo.set_goal_event(pdb, gid, "evt-1")
    assert repo.get_goal(pdb, gid).tp_event_id == "evt-1"


def test_plan_and_weeks(pdb):
    gid = repo.insert_goal(pdb, goal())
    pid = repo.insert_plan(pdb, gid, "generated", None, targets())
    plan = repo.get_plan(pdb, pid)
    assert plan.start_date == MON and plan.end_date == MON + timedelta(weeks=2, days=6)
    assert [t.target_tss for t in plan.skeleton] == [300, 301, 302]
    assert repo.get_active_plan(pdb, gid).id == pid
    weeks = repo.list_weeks(pdb, pid)
    assert [w.week_start for w in weeks] == [MON, MON + timedelta(weeks=1), MON + timedelta(weeks=2)]
    assert all(w.designed is None and not w.written_to_tp for w in weeks)

    designed = PlannedWeek(
        week_start=MON,
        sessions=[PlannedSession(date=MON, sport="swim", title="Swim", description="",
                                 duration_minutes=45, tss_planned=40, intensity="endurance")],
        coach_note="easy start",
    )
    repo.set_week_designed(pdb, pid, MON, designed)
    repo.mark_weeks_written(pdb, pid, [MON])
    first = repo.list_weeks(pdb, pid)[0]
    assert first.designed == designed and first.written_to_tp is True


def test_changes_and_ownership(pdb):
    gid = repo.insert_goal(pdb, goal())
    pid = repo.insert_plan(pdb, gid, "generated", None, targets(1))
    create = CalendarChange(op="create", workout_date=MON, reason="plan")
    repo.insert_change(pdb, pid, "planning", create, tp_workout_id="w1", result={"success": True})
    repo.insert_change(pdb, pid, "planning", create, tp_workout_id="w2", result={"success": True})
    assert repo.owned_workout_ids(pdb, pid) == {"w1", "w2"}
    delete = CalendarChange(op="delete", tp_workout_id="w2", reason="dropped")
    repo.insert_change(pdb, pid, "planning", delete, tp_workout_id="w2", result={"success": True})
    assert repo.owned_workout_ids(pdb, pid) == {"w1"}
    row = pdb.execute("select * from plan_changes where tp_workout_id = 'w1'").fetchone()
    assert row["operation"] == "create" and row["payload"]["op"] == "create"
    assert row["workout_date"] == MON and row["reason"] == "plan"


def test_abandon_active(pdb):
    gid = repo.insert_goal(pdb, goal())
    repo.insert_plan(pdb, gid, "generated", None, targets(1))
    assert repo.abandon_active(pdb) == (1, 1)
    assert repo.get_active_goal(pdb) is None
    assert repo.get_active_plan(pdb, gid) is None
    assert repo.get_goal(pdb, gid).status == "abandoned"


def test_fitness_snapshot(pdb):
    as_of = date(2026, 9, 14)
    rows = [
        DailyMetricsRow(metric_date=as_of - timedelta(days=d), tss_day=70.0, ctl=40.0 + d)
        for d in range(1, 29)
    ]
    core_repo.upsert_daily_metrics(pdb, rows)
    snap = repo.fitness_snapshot(pdb, as_of)
    assert snap.ctl == 41  # the latest row, one day before as_of
    assert snap.recent_weekly_tss == pytest.approx(70 * 28 / 4)


def test_fitness_snapshot_empty(pdb):
    snap = repo.fitness_snapshot(pdb, date(1999, 1, 1))
    assert snap.ctl is None and snap.recent_weekly_tss is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/tri-planning/tests/test_repo.py -q`
Expected: `ImportError` (or skip if Postgres is down; start it with `docker compose up -d` for this task).

- [ ] **Step 3: Write `repo.py`**

```python
"""Planning-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_planning.planning.models import (
    CalendarChange,
    FitnessSnapshot,
    PlannedWeek,
    PlanWeekRow,
    StoredGoal,
    StoredPlan,
    TrainingGoal,
    WeekTarget,
)


def insert_goal(conn: Conn, goal: TrainingGoal) -> int:
    row = conn.execute(
        """
        insert into training_goals (goal_type, event_name, event_date, duration_weeks, priority,
            weekly_hours_min, weekly_hours_max, available_days, constraints, tp_plan_id,
            create_tp_event)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            goal.goal_type,
            goal.event_name,
            goal.event_date,
            goal.duration_weeks,
            goal.priority,
            goal.weekly_hours_min,
            goal.weekly_hours_max,
            Jsonb(goal.available_days),
            Jsonb(goal.constraints),
            goal.tp_plan_id,
            goal.create_tp_event,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _goal(row: dict[str, Any]) -> StoredGoal:
    return StoredGoal(
        id=row["id"],
        status=row["status"],
        tp_event_id=row["tp_event_id"],
        goal=TrainingGoal(
            goal_type=row["goal_type"],
            event_name=row["event_name"],
            event_date=row["event_date"],
            duration_weeks=row["duration_weeks"],
            priority=row["priority"],
            weekly_hours_min=float(row["weekly_hours_min"]),
            weekly_hours_max=float(row["weekly_hours_max"]),
            available_days=row["available_days"],
            constraints=row["constraints"] or [],
            tp_plan_id=row["tp_plan_id"],
            create_tp_event=row["create_tp_event"],
        ),
    )


def get_goal(conn: Conn, goal_id: int) -> StoredGoal | None:
    row = conn.execute("select * from training_goals where id = %s", (goal_id,)).fetchone()
    return _goal(row) if row else None


def get_active_goal(conn: Conn) -> StoredGoal | None:
    row = conn.execute(
        "select * from training_goals where status = 'active' order by created_at desc, id desc "
        "limit 1"
    ).fetchone()
    return _goal(row) if row else None


def set_goal_event(conn: Conn, goal_id: int, tp_event_id: str) -> None:
    conn.execute(
        "update training_goals set tp_event_id = %s where id = %s", (tp_event_id, goal_id)
    )


def insert_plan(
    conn: Conn, goal_id: int, source: str, tp_plan_id: str | None, skeleton: list[WeekTarget]
) -> int:
    if not skeleton:
        raise ValueError("skeleton is empty")
    start = skeleton[0].week_start
    end = skeleton[-1].week_start + timedelta(days=6)
    row = conn.execute(
        """
        insert into training_plans (goal_id, source, tp_plan_id, start_date, end_date, skeleton)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (goal_id, source, tp_plan_id, start, end, Jsonb([t.model_dump(mode="json") for t in skeleton])),
    ).fetchone()
    assert row is not None
    plan_id = int(row["id"])
    with conn.cursor() as cur:
        for t in skeleton:
            cur.execute(
                "insert into plan_weeks (plan_id, week_start, phase, target_tss, target_hours) "
                "values (%s, %s, %s, %s, %s)",
                (plan_id, t.week_start, t.phase, t.target_tss, t.target_hours),
            )
    return plan_id


def _plan(row: dict[str, Any]) -> StoredPlan:
    return StoredPlan(
        id=row["id"],
        goal_id=row["goal_id"],
        source=row["source"],
        tp_plan_id=row["tp_plan_id"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        skeleton=[WeekTarget.model_validate(t) for t in row["skeleton"]],
        status=row["status"],
    )


def get_plan(conn: Conn, plan_id: int) -> StoredPlan | None:
    row = conn.execute("select * from training_plans where id = %s", (plan_id,)).fetchone()
    return _plan(row) if row else None


def get_active_plan(conn: Conn, goal_id: int) -> StoredPlan | None:
    row = conn.execute(
        "select * from training_plans where goal_id = %s and status = 'active' "
        "order by created_at desc, id desc limit 1",
        (goal_id,),
    ).fetchone()
    return _plan(row) if row else None


def list_weeks(conn: Conn, plan_id: int) -> list[PlanWeekRow]:
    rows = conn.execute(
        "select * from plan_weeks where plan_id = %s order by week_start", (plan_id,)
    ).fetchall()
    return [
        PlanWeekRow(
            plan_id=r["plan_id"],
            week_start=r["week_start"],
            phase=r["phase"],
            target_tss=float(r["target_tss"]) if r["target_tss"] is not None else None,
            target_hours=float(r["target_hours"]) if r["target_hours"] is not None else None,
            designed=PlannedWeek.model_validate(r["designed"]) if r["designed"] else None,
            written_to_tp=r["written_to_tp"],
        )
        for r in rows
    ]


def set_week_designed(conn: Conn, plan_id: int, week_start: date, week: PlannedWeek) -> None:
    conn.execute(
        "update plan_weeks set designed = %s where plan_id = %s and week_start = %s",
        (Jsonb(week.model_dump(mode="json")), plan_id, week_start),
    )


def mark_weeks_written(conn: Conn, plan_id: int, week_starts: list[date]) -> None:
    if not week_starts:
        return
    conn.execute(
        "update plan_weeks set written_to_tp = true where plan_id = %s and week_start = any(%s)",
        (plan_id, week_starts),
    )


def insert_change(
    conn: Conn,
    plan_id: int | None,
    thread_id: str,
    change: CalendarChange,
    *,
    tp_workout_id: str | None,
    result: dict[str, Any] | None,
) -> int:
    row = conn.execute(
        """
        insert into plan_changes (plan_id, thread_id, operation, tp_workout_id, workout_date,
            payload, result, reason)
        values (%s, %s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (
            plan_id,
            thread_id,
            change.op,
            tp_workout_id,
            change.workout_date,
            Jsonb(change.model_dump(mode="json")),
            Jsonb(result) if result is not None else None,
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def owned_workout_ids(conn: Conn, plan_id: int) -> set[str]:
    rows = conn.execute(
        "select operation, tp_workout_id from plan_changes "
        "where plan_id = %s and tp_workout_id is not null",
        (plan_id,),
    ).fetchall()
    created = {r["tp_workout_id"] for r in rows if r["operation"] in ("create", "apply_plan")}
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    return created - deleted


def abandon_active(conn: Conn) -> tuple[int, int]:
    plans = conn.execute(
        "update training_plans set status = 'superseded' where status = 'active'"
    ).rowcount
    goals = conn.execute(
        "update training_goals set status = 'abandoned' where status = 'active'"
    ).rowcount
    return goals, plans


def fitness_snapshot(conn: Conn, as_of: date) -> FitnessSnapshot:
    ctl_row = conn.execute(
        "select ctl from daily_metrics where metric_date <= %s and ctl is not null "
        "order by metric_date desc limit 1",
        (as_of,),
    ).fetchone()
    tss_row = conn.execute(
        "select sum(tss_day) as total, count(tss_day) as n from daily_metrics "
        "where metric_date between %s and %s",
        (as_of - timedelta(days=28), as_of - timedelta(days=1)),
    ).fetchone()
    weekly = None
    if tss_row and tss_row["n"]:
        weekly = float(tss_row["total"]) / 4
    return FitnessSnapshot(
        ctl=float(ctl_row["ctl"]) if ctl_row else None, recent_weekly_tss=weekly
    )


def athlete_thresholds(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, hr_zones, power_zones, pace_zones from athlete_profile where id = 1"
    ).fetchone()
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-planning/tests/test_repo.py -q`
Expected: 6 passed (Postgres up, 002 applied). `test_fitness_snapshot` asserts `snap.ctl == 41`: the newest row on or before `as_of` is `as_of - 1 day` with `ctl = 40 + 1`.

- [ ] **Step 5: Full suite, lint, type-check, commit (Brian)**

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(planning): planning repository over goals, plans, weeks and changes"
```

---

### Task 6: Package README, docs sync

**Files:**
- Modify: `packages/tri-planning/README.md`, root `README.md` (setup step 2 already loops over `migrations/*.sql`; add a line under Layout for `packages/tri-planning/`)

- [ ] **Step 1: Extend the package README**

Append to `packages/tri-planning/README.md`:
```markdown
## Layout so far

- `planning/models.py`: goal, week target, session, week, calendar change.
- `planning/periodization.py`: every tunable number (phase table, ramp, recovery, taper, IF).
- `planning/skeleton.py`: `build(goal, fitness, start)` -> week targets. Pure.
- `planning/validate.py`: `week(planned, target, goal)` -> violations. Pure.
- `repo.py`: the four planning tables (`migrations/002_planning.sql`).

Try the skeleton without a database:

```bash
uv run python -c "
from datetime import date
from tri_planning.planning.models import TrainingGoal, FitnessSnapshot
from tri_planning.planning.skeleton import build, next_monday
g = TrainingGoal(goal_type='olympic', event_date=date(2026,12,13), weekly_hours_min=6,
                 weekly_hours_max=10, available_days={d:'any' for d in ('mon','tue','wed','thu','fri','sat','sun')})
for w in build(g, FitnessSnapshot(ctl=45), next_monday(date.today())):
    print(w.week_start, w.phase, w.target_tss, w.target_hours, 'R' if w.is_recovery else '', w.flags)
"
```
```

- [ ] **Step 2: Copy docs to the vault and commit (Brian)**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/packages/tri-planning
cp packages/tri-planning/README.md $V/packages/tri-planning/readme.md
cp README.md $V/readme.md
cp docs/superpowers/plans/*.md $V/docs/superpowers/plans/
git add -A
git commit -m "docs(planning): package README"
```

---

## Self-review notes

- Spec §5: all four tables and the index (Task 1); the three extra `training_goals` columns are listed as deviations. LangGraph checkpoint tables are created by `PostgresSaver.setup()` in Plan 3.
- Spec §6.3 models: all four plus `ReviewDecision` (needed by §6.1 state) in Task 2.
- Spec §7.1 every row of the phase table is a parametrized test case; compression and the minimum are tested. §7.2 each bullet has a test: week-1 chain, 8 % ramp, CTL cap, recovery 60 % with ramp resuming from the last real week, Ironman 3-week cadence, peak hold, taper 80/60/45, race 30 %, maintenance flat, recovery 50 %, hours clamp with TSS recompute and flag, sport hints per phase, bought-plan phase inference. §7.3 each rule has a test in Task 4.
- Spec §10: `TRI_PLANNING_HORIZON_WEEKS` in `PlanningSettings`; the LangSmith project is a planning-specific env var so one `.env` can serve both agents (Plan 3 exports it as `LANGSMITH_PROJECT` before LangChain loads).
- Type consistency: `validate.week` signature `(planned, target, goal)` and `skeleton.build(goal, fitness, start)` are the names Plan 3's design and skeleton nodes call; `repo` function names above are the ones Plan 3 imports.
