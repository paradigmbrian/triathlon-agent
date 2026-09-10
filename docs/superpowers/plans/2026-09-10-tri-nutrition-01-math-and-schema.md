# tri-nutrition Plan 1 of 4: Math and Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `tri-nutrition` package with the nutrition domain models, the constants table, the pure energy and day-target math (`profile + sessions -> DayTarget per day`), the three bounds validators, the nutrition tables migration and the repository over them, plus the `garmin_spec(enabled_tools=...)` change in tri-core. Every rule is unit-tested; nothing calls a model. This is spec milestone 1.

**Architecture:** `tri_nutrition.nutrition` is a pure layer: Pydantic models, a constants module, and three modules of functions (`energy`, `targets`, `bounds`) with no I/O. `tri_nutrition.repo` is the only module that touches the three new tables and follows the tri-core repository convention (functions take an open connection, callers commit). The graph in Plan 2 composes these; nothing here imports LangChain or LangGraph.

**Tech Stack:** pydantic 2 models, psycopg 3 with `Jsonb`, pytest. Depends on the workspace as it stands after tri-planning Plan 4 (`tri_core.testing.fixtures.db`, `tri_core.db.repo.Conn`).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md` (§1 decisions, §5.2 tables, §6.3 models, §7 nutrition logic, §10 configuration, §11 testing, §13 milestone 1, §15 open items).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root `/Users/brian/Development/paradigm/fitness_agents/triathlon_agent` as `uv run ...`.
- New package: distribution `tri-nutrition`, module `tri_nutrition`, console script `tri-nutrition`. It depends on `tri-core` only and never imports `tri_analyze` or `tri_planning`. Planning's tables are read through SQL.
- Pins carried from the workspace: `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langchain-mcp-adapters==0.3.2`, `langgraph-checkpoint-postgres>=3.1,<4`, `psycopg[binary]==3.3.5`, `pyyaml>=6`. No new dependencies beyond planning's set (spec §10). They are declared now so the lock settles once, even though Plan 2 is the first to import LangGraph.
- Settings (spec §10): `TRI_NUTRITION_HORIZON_DAYS` default `14`; `TRI_NUTRITION_LANGSMITH_PROJECT` default `tri_nutrition`.
- Every number from spec §7 lives in `nutrition/constants.py` and nowhere else: Cunningham `500 + 22 × lean kg`; Mifflin-St Jeor; activity factor default `1.35` bounded `1.2` to `1.5`; bike `TSS × FTP × 36 / 1000`; strength `5 kcal/kg/h`; day-type cutoffs `60` and `120` minutes, long `150` minutes; the macro table (rest/easy `3–4 / 1.8 / ≥0.8`, moderate `5–6 / 1.8 / ≥0.8`, hard/long `7–8 / 2.0 / ≥0.8`, carb_load `10 / 1.6 / ≥0.6`, race `8 / 1.6 / ≥0.6` g/kg); `7700` kcal/kg; deficit cap `500` kcal/day; surplus `200–300` kcal; fluids `35 ml/kg/day` and `500 ml/h`; bounds EA `30 kcal/kg FFM`, protein `1.6 g/kg`, hard-day carbs `6 g/kg`, fuel `60 / 90 / 120 g/h`, fluid `1000 ml/h`, sodium `300–1500 mg/h`, caffeine `6 mg/kg`, pre-race window `2–4 h`.
- Spec §7.1 kJ-as-kcal for the bike is kept as written.
- **Brian runs every git command and applies every migration with `psql`, to both `tri_analyze` and `tri_analyze_test`.** Tests write only through the rolled-back `db` fixture.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Run `uv run ruff format packages/tri-nutrition` first: the test code in this plan is written for readability and some lines exceed the 100-column limit; the formatter wraps them, and any `E501` it cannot fix is wrapped by hand.
- No "LangChain lesson:" framing in docstrings (Brian's standing feedback).
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case file name.

### Spec deviations decided in this plan

- **Migration is `migrations/004_nutrition.sql`, not `003_nutrition.sql`.** `003_rename_skeleton_to_targets.sql` already exists (planning's column rename). The spec's table DDL is copied verbatim under the new number.
- **`build` takes a `PlanContext`, and the model set gains three input types.** Spec §4 gives `build(profile, sessions, phases, today, horizon)` but §7 also needs the athlete's FTP (bike kcal), the goal's event date and priority (race and carb-load days), the goal's weekly hours (the `profile_hours` fallback) and the horizon's source label. These are bundled as `PlanContext`. Sessions are typed as `Session` (what the graph will read out of `plan_weeks.designed` and `workouts` in Plan 2), and the Store's fuel-log entries as `FuelLogEntry` (spec §5.1 describes it in prose; `validate_fuel` needs it typed). All three live in `nutrition/models.py`.
- **`DayTarget` gains `goal_adjust_kcal: int` and the table gains the matching column.** `validate_targets` must know each day's deficit to check the seven-day rate bound and the phase pause; recomputing maintenance from the profile inside the validator would duplicate `energy.py`. The sign convention: negative is a deficit, positive a surplus, zero on `maintain`.
- **`total_kcal` is recomputed from the rounded macros: `4c + 4p + 9f`.** Garmin corrects any calorie goal that disagrees with its macros (spec §2), so the stored target is made consistent at build time. The apply node's consistency check (Plan 2) becomes a defensive no-op for targets built here.
- **Fat-free mass falls back to an assumed body-fat percentage when `body_fat_pct` is `None`:** `18 %` for `m`, `26 %` for `f` (constants `ASSUMED_BODY_FAT_PCT`). Both the Cunningham branch and the energy-availability bound need FFM; the spec only says Mifflin is used for RMR when body fat is unknown.
- **Bike sessions without a planned TSS or without a known FTP, and every brick leg, fall back to `duration_h × weight_kg × sport factor`.** The spec gives the TSS formula for the bike and nothing for the fallback. A brick without explicit legs is split `2/3` bike, `1/3` run by duration (constants `BRICK_BIKE_FRACTION`).
- **The `lose` deficit per day is `min(500, weekly_budget / 7)`** where `weekly_budget = max_weekly_change_pct / 100 × weight_kg × 7700`. Spreading the budget evenly over seven days means the seven-day sum can never exceed the budget however many days qualify; the spec's rate bound in `validate_targets` still checks it.
- **Macro range position is `clamp(session_kcal / 1500, 0, 1)`** (constant `SESSION_KCAL_FULL_RANGE`). The spec says "the position scales with session kcal" without a scale.
- **`RaceFuelStep` gains `products: list[str]`.** `validate_race` must check every product against the library; `what` is prose. `validate_race` checks the per-hour leg bounds against `totals_per_h` (the model reports them; the timeline's leg boundaries are not durations).
- **`profile_hours` days use the active training goal's weekly hours**, spread evenly as endurance-intensity training at `weekly_hours / 7` per day. When there is no goal either, every day is `rest` with source `profile_hours` and a note; intake (Plan 2) tells the athlete.
- **`repo.py` and the DB tests are in this plan** (spec milestone 1 lists only math and schema). The repository is SQL over the new tables, calls no model, and planning's Plan 2 set the precedent.

---

## File Structure

```
packages/tri-nutrition/
  pyproject.toml
  README.md
  src/tri_nutrition/
    __init__.py
    config.py                 NutritionSettings(Settings): horizon days, LangSmith project
    cli.py                    typer app with a callback only (chat/check-in/reset arrive in Plans 2 and 4)
    repo.py                   nutrition_targets, fuel_plans, nutrition_changes reads and writes
    nutrition/
      __init__.py
      models.py               Sex, Goal, Pattern, DayType, Sport, Intensity, ProductForm, Leg, Outcome,
                              Product, NutritionProfile, FuelLogEntry, Session, PlanContext, DayTarget,
                              SessionFuel, RaceFuelStep, RaceFuelPlan, NutritionChange, ReviewDecision,
                              StoredDayTarget, StoredFuelPlan
      constants.py            every tunable number
      energy.py               ffm(), rmr(), non_exercise_kcal(), session_kcal(), day_type()
      targets.py              sessions_by_day(), macro_grams(), goal_adjust(), fluid_baseline_ml(), build()
      bounds.py               validate_targets(), validate_fuel(), validate_race()
  tests/
    test_config.py
    test_models.py
    test_energy.py
    test_targets.py
    test_bounds.py
    test_repo.py              db-marked
migrations/004_nutrition.sql
packages/tri-core/src/tri_core/mcp/servers.py     garmin_spec(settings, enabled_tools=None)
packages/tri-core/tests/test_mcp_client.py        one new test
```

Responsibilities: `models.py` is the vocabulary every other module shares. `constants.py` is the tuning surface (change a number, rerun the tests). `energy.py` answers "how much does this athlete burn" per formula and "what kind of day is this". `targets.py` turns a profile and a horizon of sessions into one `DayTarget` per day and never validates. `bounds.py` judges targets and fuel plans and never changes them. `repo.py` is the only SQL.

---

### Task 1: Package scaffold, settings, migration

**Files:**
- Create: `packages/tri-nutrition/pyproject.toml`, `packages/tri-nutrition/README.md`, `packages/tri-nutrition/src/tri_nutrition/__init__.py`, `packages/tri-nutrition/src/tri_nutrition/nutrition/__init__.py`, `packages/tri-nutrition/src/tri_nutrition/config.py`, `packages/tri-nutrition/src/tri_nutrition/cli.py`, `migrations/004_nutrition.sql`
- Modify: root `pyproject.toml` (member dependency, source, isort first-party, mypy files), `.env.example`
- Test: `packages/tri-nutrition/tests/test_config.py`

**Interfaces:**
- Consumes: `tri_core.config.Settings`.
- Produces: `tri_nutrition.config.NutritionSettings` with `tri_nutrition_horizon_days: int = 14` and `tri_nutrition_langsmith_project: str = "tri_nutrition"`; `tri_nutrition.config.get_nutrition_settings() -> NutritionSettings`; `tri_nutrition.cli.app`; the three tables.

- [ ] **Step 1: Write the failing test**

`packages/tri-nutrition/tests/test_config.py`:
```python
from tri_nutrition.config import NutritionSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_NUTRITION_HORIZON_DAYS", raising=False)
    monkeypatch.delenv("TRI_NUTRITION_LANGSMITH_PROJECT", raising=False)
    s = NutritionSettings(_env_file=None)
    assert s.tri_nutrition_horizon_days == 14
    assert s.tri_nutrition_langsmith_project == "tri_nutrition"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_NUTRITION_HORIZON_DAYS", "7")
    assert NutritionSettings(_env_file=None).tri_nutrition_horizon_days == 7
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-nutrition -q`
Expected: uv refuses to sync (`Workspace member ... is missing a pyproject.toml`) or, once the directory exists, `ModuleNotFoundError: No module named 'tri_nutrition'`. Either is the expected failure.

- [ ] **Step 3: Create the package**

`packages/tri-nutrition/pyproject.toml`:
```toml
[project]
name = "tri-nutrition"
version = "0.1.0"
description = "Endurance nutrition agent: periodized daily targets and per-session fueling from the training plan"
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
tri-nutrition = "tri_nutrition.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tri_nutrition"]

[tool.uv.sources]
tri-core = { workspace = true }
```

`packages/tri-nutrition/src/tri_nutrition/__init__.py` and `nutrition/__init__.py`: empty files.

`packages/tri-nutrition/src/tri_nutrition/config.py`:
```python
"""Nutrition-agent settings: everything in tri_core.config plus the nutrition knobs."""

from functools import lru_cache

from tri_core.config import Settings


class NutritionSettings(Settings):
    tri_nutrition_horizon_days: int = 14
    tri_nutrition_langsmith_project: str = "tri_nutrition"


@lru_cache(maxsize=1)
def get_nutrition_settings() -> NutritionSettings:
    return NutritionSettings()
```

`packages/tri-nutrition/src/tri_nutrition/cli.py`:
```python
"""Command-line entry points for the nutrition agent (chat, check-in, reset arrive in later plans)."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Endurance nutrition agent", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Endurance nutrition agent."""


if __name__ == "__main__":
    app()
```

`packages/tri-nutrition/README.md`:
```markdown
# tri-nutrition

The nutrition agent: interviews the athlete about diet, restrictions and physique goals, derives
periodized daily calorie and macro targets and per-session fueling plans from the training plan,
writes them to Garmin Connect and TrainingPeaks after approval, and checks in against logged
intake and body composition. Design: `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md`.
Plans: `docs/superpowers/plans/2026-09-10-tri-nutrition-0*.md`.
```

Root `pyproject.toml` edits:
- `dependencies = ["tri-core", "tri-analyze", "tri-planning", "tri-nutrition"]`
- under `[tool.uv.sources]` add `tri-nutrition = { workspace = true }`
- `known-first-party = ["tri_core", "tri_analyze", "tri_planning", "tri_nutrition"]`
- mypy `files = ["packages/tri-core/src", "packages/tri-analyze/src", "packages/tri-planning/src", "packages/tri-nutrition/src"]`

`.env.example`: append
```
# tri-nutrition
TRI_NUTRITION_HORIZON_DAYS=14
TRI_NUTRITION_LANGSMITH_PROJECT=tri_nutrition
```

- [ ] **Step 4: Write the migration**

`migrations/004_nutrition.sql`:
```sql
-- 004_nutrition.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists nutrition_targets (
  day               date primary key,
  day_type          text not null,        -- rest | easy | moderate | hard | long | race | carb_load
  session_kcal      int not null,
  total_kcal        int not null,
  carbs_g           int not null,
  protein_g         int not null,
  fat_g             int not null,
  fluid_baseline_ml int not null,
  goal_adjust_kcal  int not null default 0,   -- negative deficit, positive surplus
  notes             jsonb not null default '[]',
  plan_phase        text,                 -- copied from plan_weeks.phase when a plan exists
  source            text not null,        -- plan | tp_calendar | profile_hours
  written_to_garmin boolean not null default false,
  generated_at      timestamptz not null default now()
);

create table if not exists fuel_plans (
  id            serial primary key,
  kind          text not null,            -- session | race
  day           date not null,
  tp_workout_id text,                     -- session plans
  tp_note_id    text,                     -- race plans, once written
  payload       jsonb not null,           -- SessionFuel or RaceFuelPlan
  violations    jsonb not null default '[]',
  written       boolean not null default false,
  generated_at  timestamptz not null default now()
);
create unique index if not exists fuel_plans_kind_day_workout_idx
  on fuel_plans (kind, day, coalesce(tp_workout_id, ''));

create table if not exists nutrition_changes (
  id            serial primary key,
  thread_id     text not null,
  operation     text not null,            -- set_day_targets | set_session_note | set_race_note
  target_key    text not null,            -- the date, workout id or note id
  payload       jsonb not null,           -- exactly what we sent
  result        jsonb,                    -- exactly what the server returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index if not exists nutrition_changes_op_key_idx on nutrition_changes (operation, target_key);
```

- [ ] **Step 5: Sync, run the test, apply the migration (Brian)**

```bash
uv sync
uv run pytest packages/tri-nutrition -q
uv run tri-nutrition --help
```
Expected: 2 passed; `--help` prints the app description with no commands.

Brian applies the migration:
```bash
docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/004_nutrition.sql
docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/004_nutrition.sql
```

- [ ] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(nutrition): package scaffold, settings, 004_nutrition migration"
```

---

### Task 2: `garmin_spec(enabled_tools=...)`

**Files:**
- Modify: `packages/tri-core/src/tri_core/mcp/servers.py:30-52`
- Test: `packages/tri-core/tests/test_mcp_client.py`

**Interfaces:**
- Produces: `tri_core.mcp.servers.garmin_spec(settings: Settings, enabled_tools: list[str] | None = None) -> ServerSpec`. `None` keeps `GARMIN_ENABLED_TOOLS`. Every existing caller (`sync/runner.py`, `tri_analyze/agent/live_tools.py`, `scripts/spike_mcp.py`) passes one argument and is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_mcp_client.py`:
```python
def test_garmin_spec_enabled_tools_override():
    s = Settings(_env_file=None)
    default = garmin_spec(s)
    assert default.env["GARMIN_ENABLED_TOOLS"] == ",".join(GARMIN_ENABLED_TOOLS)
    custom = garmin_spec(s, enabled_tools=["get_body_composition", "get_nutrition_daily_settings"])
    assert custom.env["GARMIN_ENABLED_TOOLS"] == "get_body_composition,get_nutrition_daily_settings"
    assert custom.args == default.args
```
and extend the import line to `from tri_core.mcp.servers import GARMIN_ENABLED_TOOLS, garmin_spec, trainingpeaks_spec`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_mcp_client.py::test_garmin_spec_enabled_tools_override -q`
Expected: `TypeError: garmin_spec() got an unexpected keyword argument 'enabled_tools'`.

- [ ] **Step 3: Add the parameter**

In `packages/tri-core/src/tri_core/mcp/servers.py` replace the `garmin_spec` signature and the first `env` line:
```python
def garmin_spec(settings: Settings, enabled_tools: list[str] | None = None) -> ServerSpec:
    """Launch spec for the Garmin server. `enabled_tools` narrows the registered tool set;
    each agent passes the list it needs (default: GARMIN_ENABLED_TOOLS, what sync uses)."""
    env = {
        "GARMIN_ENABLED_TOOLS": ",".join(
            enabled_tools if enabled_tools is not None else GARMIN_ENABLED_TOOLS
        ),
        "GARMIN_MCP_CALL_TIMEOUT": "90",
    }
```
The rest of the function is unchanged.

- [ ] **Step 4: Run the whole tri-core suite**

Run: `uv run pytest packages/tri-core -q`
Expected: all pass (db tests skip if Postgres is down; live tests skip without `--live`).

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-core
git commit -m "feat(core): garmin_spec accepts enabled_tools so each agent registers its own Garmin tool set"
```

---

### Task 3: Domain models

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/nutrition/models.py`
- Test: `packages/tri-nutrition/tests/test_models.py`

**Interfaces:**
- Produces every type the rest of this plan and Plans 2 to 4 import. Field names are the spec's §6.3 names; the additions are listed under deviations. `Session.legs` is the brick decomposition; `PlanContext` carries FTP, event, phases and source.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_models.py`:
```python
from datetime import date

import pytest
from pydantic import ValidationError

from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    NutritionProfile,
    PlanContext,
    Product,
    RaceFuelPlan,
    RaceFuelStep,
    ReviewDecision,
    Session,
    SessionFuel,
)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180,
        weight_kg=75,
        body_fat_pct=15,
        sex="m",
        age=40,
        goal="maintain",
        pattern="omnivore",
        meals_per_day=3,
        cooks=True,
        tracks_food=True,
        scale_days_per_week=3,
        unit_preference="metric",
    )
    base.update(over)
    return NutritionProfile(**base)


def test_profile_defaults_and_lists():
    p = profile()
    assert p.activity_factor == 1.35
    assert p.max_weekly_change_pct == 0.5
    assert p.restrictions == [] and p.tested_products == [] and p.medical_flags == []
    assert p.target_weight_kg is None and p.caffeine_mg_per_day is None


@pytest.mark.parametrize("field,value", [("activity_factor", 1.1), ("activity_factor", 1.6)])
def test_activity_factor_bounded(field, value):
    with pytest.raises(ValidationError):
        profile(**{field: value})


def test_max_weekly_change_pct_bounded():
    with pytest.raises(ValidationError):
        profile(max_weekly_change_pct=1.5)
    assert profile(max_weekly_change_pct=1.0).max_weekly_change_pct == 1.0


def test_lose_goal_needs_target_weight_below_current():
    with pytest.raises(ValidationError):
        profile(goal="lose", target_weight_kg=80)
    assert profile(goal="lose", target_weight_kg=70).goal == "lose"


def test_product_defaults():
    p = Product(name="Gel", form="gel", carbs_g=25)
    assert p.sodium_mg == 0 and p.caffeine_mg == 0 and p.tested is True


def test_session_hours_and_brick_legs():
    bike = Session(day=date(2026, 9, 14), sport="bike", duration_min=90, intensity="endurance")
    run = Session(day=date(2026, 9, 14), sport="run", duration_min=30, intensity="endurance")
    brick = Session(
        day=date(2026, 9, 14), sport="brick", duration_min=120, intensity="endurance",
        legs=[bike, run],
    )
    assert bike.hours == 1.5
    assert brick.legs is not None and len(brick.legs) == 2
    with pytest.raises(ValidationError):
        Session(day=date(2026, 9, 14), sport="bike", duration_min=60, intensity="endurance", legs=[run])


def test_plan_context_defaults():
    ctx = PlanContext(source="plan")
    assert ctx.ftp_watts is None and ctx.event_date is None and ctx.phases == {}
    assert ctx.weekly_hours is None


def test_day_target_json_roundtrip():
    t = DayTarget(
        day=date(2026, 9, 14), day_type="easy", session_kcal=300, total_kcal=2500,
        carbs_g=260, protein_g=135, fat_g=100, fluid_baseline_ml=3000, goal_adjust_kcal=-300,
        plan_phase="base", source="plan", notes=["deficit"],
    )
    assert DayTarget.model_validate(t.model_dump(mode="json")) == t


def test_session_fuel_and_race_plan_shapes():
    sf = SessionFuel(
        tp_workout_id="w1", day=date(2026, 9, 14), pre="toast", carbs_g_per_h=60,
        fluid_ml_per_h=600, sodium_mg_per_h=500, caffeine_mg=None, products=["Gel"],
        post="shake", gut_training=False, note_text="60 g/h",
    )
    assert sf.caffeine_mg is None
    step = RaceFuelStep(
        offset_min=-180, leg="pre", what="oats", carbs_g=100, fluid_ml=500, sodium_mg=300,
        caffeine_mg=0,
    )
    assert step.products == []
    plan = RaceFuelPlan(
        event_date=date(2026, 10, 4), timeline=[step],
        totals_per_h={"bike_carbs": 80, "run_carbs": 60}, contingencies=[], note_text="x",
    )
    assert plan.timeline[0].leg == "pre"


def test_change_and_decision():
    c = NutritionChange(
        op="set_day_targets", target_key="2026-09-14", day=date(2026, 9, 14),
        payload={"calorie_goal": 2500}, reason="new targets",
    )
    d = ReviewDecision(action="edit", note=None, changes=[c])
    assert d.changes is not None and d.changes[0].op == "set_day_targets"
    with pytest.raises(ValidationError):
        NutritionChange(op="nope", target_key="", day=date(2026, 9, 14), payload={}, reason="")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_models.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.nutrition.models'`.

- [ ] **Step 3: Write the models**

`packages/tri-nutrition/src/tri_nutrition/nutrition/models.py`:
```python
"""Nutrition vocabulary shared by the energy math, targets builder, bounds, repository and graph."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Sex = Literal["m", "f"]
Goal = Literal["lose", "maintain", "gain_lean"]
Pattern = Literal["omnivore", "pescatarian", "vegetarian", "vegan", "other"]
DayType = Literal["rest", "easy", "moderate", "hard", "long", "race", "carb_load"]
Sport = Literal["swim", "bike", "run", "brick", "strength"]
Intensity = Literal["recovery", "endurance", "tempo", "threshold", "vo2", "race"]
Phase = Literal["base", "build", "peak", "taper", "race", "recovery"]
Source = Literal["plan", "tp_calendar", "profile_hours"]
ProductForm = Literal["gel", "chew", "drink", "bar", "real_food", "other"]
Leg = Literal["pre", "swim", "t1", "bike", "t2", "run", "post"]
Outcome = Literal["ok", "gi_upset", "bonk", "cramps", "other"]
Operation = Literal["set_day_targets", "set_session_note", "set_race_note"]

HARD_INTENSITIES: frozenset[str] = frozenset({"threshold", "vo2", "race"})
DEFICIT_PAUSE_PHASES: frozenset[str] = frozenset({"peak", "taper", "race", "recovery"})
DEFICIT_FORBIDDEN_PHASES: frozenset[str] = frozenset({"peak", "taper", "race"})


class Product(BaseModel):
    name: str
    form: ProductForm
    carbs_g: float = Field(ge=0)
    sodium_mg: float = Field(default=0, ge=0)
    caffeine_mg: float = Field(default=0, ge=0)
    tested: bool = True


class NutritionProfile(BaseModel):
    height_cm: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    body_fat_pct: float | None = Field(default=None, ge=3, le=60)
    sex: Sex
    age: int = Field(ge=14, le=100)
    activity_factor: float = Field(default=1.35, ge=1.2, le=1.5)
    goal: Goal
    target_weight_kg: float | None = None
    target_date: date | None = None
    max_weekly_change_pct: float = Field(default=0.5, gt=0, le=1.0)
    pattern: Pattern
    restrictions: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    gi_issues: list[str] = Field(default_factory=list)
    meals_per_day: int = Field(ge=1, le=8)
    cooks: bool
    caffeine_mg_per_day: int | None = None
    alcohol_drinks_per_week: int | None = None
    tracks_food: bool
    scale_days_per_week: int = Field(ge=0, le=7)
    known_sweat_rate_l_per_h: float | None = None
    tested_products: list[Product] = Field(default_factory=list)
    fuel_notes: list[str] = Field(default_factory=list)
    unit_preference: Literal["metric", "imperial"]
    constraints: list[str] = Field(default_factory=list)
    medical_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _goal_consistent(self) -> NutritionProfile:
        if self.goal == "lose":
            if self.target_weight_kg is None:
                raise ValueError("a lose goal needs target_weight_kg")
            if self.target_weight_kg >= self.weight_kg:
                raise ValueError("target_weight_kg must be below weight_kg for a lose goal")
        if self.goal == "gain_lean" and self.target_weight_kg is not None:
            if self.target_weight_kg <= self.weight_kg:
                raise ValueError("target_weight_kg must be above weight_kg for a gain_lean goal")
        return self


class FuelLogEntry(BaseModel):
    day: date
    tp_workout_id: str | None = None
    sport: Sport
    duration_min: int = Field(ge=0)
    carbs_g_per_h: int = Field(ge=0)
    products: list[str] = Field(default_factory=list)
    outcome: Outcome
    note: str = ""


class Session(BaseModel):
    """One planned session in the horizon, as read from plan_weeks.designed or workouts."""

    day: date
    sport: Sport
    duration_min: int = Field(ge=0)
    intensity: Intensity
    tp_workout_id: str | None = None
    title: str = ""
    planned_tss: float | None = None
    distance_km: float | None = None
    legs: list[Session] | None = None  # bricks only; None means split by BRICK_BIKE_FRACTION

    @property
    def hours(self) -> float:
        return self.duration_min / 60

    @model_validator(mode="after")
    def _legs_only_on_bricks(self) -> Session:
        if self.legs is not None and self.sport != "brick":
            raise ValueError("legs are only valid on a brick session")
        return self


class PlanContext(BaseModel):
    """What the targets builder needs beyond the profile and the sessions."""

    source: Source
    ftp_watts: int | None = None
    event_date: date | None = None
    event_priority: Literal["A", "B", "C"] | None = None
    phases: dict[date, Phase] = Field(default_factory=dict)  # keyed by week Monday
    weekly_hours: float | None = None  # from the active goal; the profile_hours fallback


class DayTarget(BaseModel):
    day: date
    day_type: DayType
    session_kcal: int
    total_kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    fluid_baseline_ml: int
    goal_adjust_kcal: int = 0
    plan_phase: Phase | None = None
    source: Source
    notes: list[str] = Field(default_factory=list)


class SessionFuel(BaseModel):
    tp_workout_id: str
    day: date
    pre: str
    carbs_g_per_h: int = Field(ge=0)
    fluid_ml_per_h: int = Field(ge=0)
    sodium_mg_per_h: int = Field(ge=0)
    caffeine_mg: int | None = None
    products: list[str]
    post: str
    gut_training: bool
    note_text: str


class RaceFuelStep(BaseModel):
    offset_min: int  # from race start; negative is before
    leg: Leg
    what: str
    carbs_g: int = Field(ge=0)
    fluid_ml: int = Field(ge=0)
    sodium_mg: int = Field(ge=0)
    caffeine_mg: int = Field(default=0, ge=0)
    products: list[str] = Field(default_factory=list)


class RaceFuelPlan(BaseModel):
    event_date: date
    timeline: list[RaceFuelStep]
    totals_per_h: dict[str, int]  # bike_carbs, run_carbs, bike_fluid, run_fluid, bike_sodium, run_sodium
    contingencies: list[str]
    note_text: str


class NutritionChange(BaseModel):
    op: Operation
    target_key: str  # date, tp_workout_id, or tp_note_id (empty when creating)
    day: date
    payload: dict[str, Any]
    reason: str


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    changes: list[NutritionChange] | None = None


class StoredDayTarget(BaseModel):
    target: DayTarget
    written_to_garmin: bool


class StoredFuelPlan(BaseModel):
    id: int
    kind: Literal["session", "race"]
    day: date
    tp_workout_id: str | None
    tp_note_id: str | None
    payload: dict[str, Any]
    violations: list[str]
    written: bool
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_models.py -q`
Expected: 11 passed.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): domain models"
```

---

### Task 4: Constants and energy math

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/nutrition/constants.py`, `packages/tri-nutrition/src/tri_nutrition/nutrition/energy.py`
- Test: `packages/tri-nutrition/tests/test_energy.py`

**Interfaces:**
- Consumes: `NutritionProfile`, `Session`, `DayType`, `PlanContext` from Task 3.
- Produces (all pure):
  - `energy.ffm(profile) -> float` fat-free mass in kg.
  - `energy.rmr(profile) -> float` Cunningham when body fat is known, else Mifflin-St Jeor.
  - `energy.non_exercise_kcal(profile) -> float` = `rmr × activity_factor`.
  - `energy.session_kcal(session, profile, ftp_watts) -> float`.
  - `energy.day_type(sessions, day, ctx) -> DayType` from that day's sessions and the event.
  - Every constant named below.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_energy.py`:
```python
from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session

DAY = date(2026, 9, 14)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180, weight_kg=75, body_fat_pct=15, sex="m", age=40, goal="maintain",
        pattern="omnivore", meals_per_day=3, cooks=True, tracks_food=True,
        scale_days_per_week=3, unit_preference="metric",
    )
    base.update(over)
    return NutritionProfile(**base)


def session(**over) -> Session:
    base = dict(day=DAY, sport="bike", duration_min=60, intensity="endurance")
    base.update(over)
    return Session(**base)


# --- RMR ---


def test_ffm_from_body_fat():
    assert energy.ffm(profile()) == pytest.approx(75 * 0.85)


def test_ffm_assumed_when_body_fat_unknown():
    assert energy.ffm(profile(body_fat_pct=None)) == pytest.approx(75 * (1 - C.ASSUMED_BODY_FAT_PCT["m"] / 100))
    assert energy.ffm(profile(body_fat_pct=None, sex="f")) == pytest.approx(75 * (1 - C.ASSUMED_BODY_FAT_PCT["f"] / 100))


def test_rmr_cunningham_when_body_fat_known():
    assert energy.rmr(profile()) == pytest.approx(500 + 22 * 75 * 0.85)


def test_rmr_mifflin_when_body_fat_unknown():
    # 10*75 + 6.25*180 - 5*40 + 5 = 1680
    assert energy.rmr(profile(body_fat_pct=None)) == pytest.approx(1680)
    # female: -161 instead of +5
    assert energy.rmr(profile(body_fat_pct=None, sex="f")) == pytest.approx(1514)


def test_non_exercise_kcal():
    assert energy.non_exercise_kcal(profile(activity_factor=1.4)) == pytest.approx(energy.rmr(profile()) * 1.4)


# --- session kcal ---


def test_bike_from_tss_and_ftp():
    s = session(sport="bike", planned_tss=100)
    assert energy.session_kcal(s, profile(), ftp_watts=250) == pytest.approx(100 * 250 * 36 / 1000)


def test_bike_falls_back_without_tss_or_ftp():
    s = session(sport="bike", duration_min=60, intensity="endurance")
    expected = 1.0 * 75 * C.SPORT_KCAL_PER_KG_H["bike"]["endurance"]
    assert energy.session_kcal(s, profile(), ftp_watts=250) == pytest.approx(expected)
    assert energy.session_kcal(session(sport="bike", planned_tss=100), profile(), ftp_watts=None) == pytest.approx(expected)


def test_run_from_distance():
    s = session(sport="run", distance_km=12)
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(75 * 12)


def test_run_from_duration_and_intensity():
    s = session(sport="run", duration_min=90, intensity="threshold")
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(1.5 * 75 * C.SPORT_KCAL_PER_KG_H["run"]["threshold"])


def test_swim_from_duration_and_intensity():
    s = session(sport="swim", duration_min=45, intensity="endurance")
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(0.75 * 75 * C.SPORT_KCAL_PER_KG_H["swim"]["endurance"])


def test_strength():
    s = session(sport="strength", duration_min=30, intensity="endurance")
    assert energy.session_kcal(s, profile(), ftp_watts=None) == pytest.approx(0.5 * 5 * 75)


def test_brick_sums_legs():
    bike = session(sport="bike", duration_min=90, planned_tss=90)
    run = session(sport="run", duration_min=30, distance_km=5)
    brick = session(sport="brick", duration_min=120, legs=[bike, run])
    expected = energy.session_kcal(bike, profile(), 250) + energy.session_kcal(run, profile(), 250)
    assert energy.session_kcal(brick, profile(), ftp_watts=250) == pytest.approx(expected)


def test_brick_without_legs_splits_by_fraction():
    brick = session(sport="brick", duration_min=120, intensity="tempo")
    bike_h = 2 * C.BRICK_BIKE_FRACTION
    run_h = 2 - bike_h
    expected = bike_h * 75 * C.SPORT_KCAL_PER_KG_H["bike"]["tempo"] + run_h * 75 * C.SPORT_KCAL_PER_KG_H["run"]["tempo"]
    assert energy.session_kcal(brick, profile(), ftp_watts=None) == pytest.approx(expected)


# --- day type ---


def ctx(**over) -> PlanContext:
    base = dict(source="plan")
    base.update(over)
    return PlanContext(**base)


def test_day_type_rest():
    assert energy.day_type([], DAY, ctx()) == "rest"


def test_day_type_easy_under_60_min_endurance():
    assert energy.day_type([session(duration_min=45)], DAY, ctx()) == "easy"
    assert energy.day_type([session(duration_min=59, intensity="recovery")], DAY, ctx()) == "easy"


def test_day_type_moderate_up_to_120_or_one_tempo():
    assert energy.day_type([session(duration_min=60)], DAY, ctx()) == "moderate"
    assert energy.day_type([session(duration_min=120)], DAY, ctx()) == "moderate"
    assert energy.day_type([session(duration_min=40, intensity="tempo")], DAY, ctx()) == "moderate"


@pytest.mark.parametrize("intensity", ["threshold", "vo2", "race"])
def test_day_type_hard(intensity):
    assert energy.day_type([session(duration_min=45, intensity=intensity)], DAY, ctx()) == "hard"


def test_day_type_long_single_session_150_min():
    assert energy.day_type([session(duration_min=150)], DAY, ctx()) == "long"
    # two sessions summing past 150 are not "long"; over 120 total with no hard session is moderate
    two = [session(duration_min=80), session(sport="run", duration_min=80)]
    assert energy.day_type(two, DAY, ctx()) == "moderate"


def test_day_type_long_beats_hard():
    assert energy.day_type([session(duration_min=180, intensity="threshold")], DAY, ctx()) == "long"


def test_day_type_race_and_carb_load_for_a_priority():
    c = ctx(event_date=DAY + timedelta(days=6), event_priority="A")
    assert energy.day_type([session(sport="run", duration_min=30)], DAY + timedelta(days=6), c) == "race"
    assert energy.day_type([session(duration_min=45)], DAY + timedelta(days=5), c) == "carb_load"
    assert energy.day_type([], DAY + timedelta(days=4), c) == "carb_load"
    assert energy.day_type([], DAY + timedelta(days=3), c) == "rest"


def test_day_type_no_carb_load_for_b_priority():
    c = ctx(event_date=DAY + timedelta(days=6), event_priority="B")
    assert energy.day_type([], DAY + timedelta(days=6), c) == "race"
    assert energy.day_type([session(duration_min=45)], DAY + timedelta(days=5), c) == "easy"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_energy.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.nutrition.constants'`.

- [ ] **Step 3: Write the constants**

`packages/tri-nutrition/src/tri_nutrition/nutrition/constants.py`:
```python
"""Every tunable number in the nutrition math. Spec §7. Change a value here, rerun the tests."""

from __future__ import annotations

from tri_nutrition.nutrition.models import DayType, Intensity, Sex, Sport

# --- energy (§7.1) ---
CUNNINGHAM_BASE = 500.0
CUNNINGHAM_PER_KG_FFM = 22.0
# Mifflin-St Jeor: 10*kg + 6.25*cm - 5*age + sex term
MIFFLIN_SEX_TERM: dict[Sex, float] = {"m": 5.0, "f": -161.0}
ASSUMED_BODY_FAT_PCT: dict[Sex, float] = {"m": 18.0, "f": 26.0}  # when the profile has none
BIKE_KCAL_PER_TSS_FTP = 36 / 1000  # kJ per TSS per watt of FTP, taken as kcal
STRENGTH_KCAL_PER_KG_H = 5.0
BRICK_BIKE_FRACTION = 2 / 3  # of a brick's duration when legs are not given
# kcal per kg per hour by sport and intensity: the fallback when TSS/FTP or distance is missing.
# Run values equal km/h at that effort (kcal ~ kg x km); swim and bike are MET-derived.
_S = STRENGTH_KCAL_PER_KG_H
SPORT_KCAL_PER_KG_H: dict[Sport, dict[Intensity, float]] = {
    "run": {
        "recovery": 8.5, "endurance": 10.0, "tempo": 11.5, "threshold": 12.5, "vo2": 13.5,
        "race": 12.5,
    },
    "bike": {
        "recovery": 5.0, "endurance": 7.0, "tempo": 8.5, "threshold": 10.0, "vo2": 11.0,
        "race": 10.0,
    },
    "swim": {
        "recovery": 6.0, "endurance": 7.0, "tempo": 8.0, "threshold": 9.0, "vo2": 10.0,
        "race": 9.0,
    },
    "strength": {
        "recovery": _S, "endurance": _S, "tempo": _S, "threshold": _S, "vo2": _S, "race": _S,
    },
    "brick": {},  # bricks are the sum of their legs
}

# --- day type (§7.2) ---
EASY_MAX_MIN = 60  # strictly under
MODERATE_MAX_MIN = 120  # up to and including
LONG_SESSION_MIN = 150  # any single session at or over
CARB_LOAD_DAYS_BEFORE_RACE = 2  # only for an A-priority event

# --- macros, g per kg body mass (§7.3) ---
# (carbs_lo, carbs_hi, protein, fat_min)
MACRO_TABLE: dict[DayType, tuple[float, float, float, float]] = {
    "rest": (3.0, 4.0, 1.8, 0.8),
    "easy": (3.0, 4.0, 1.8, 0.8),
    "moderate": (5.0, 6.0, 1.8, 0.8),
    "hard": (7.0, 8.0, 2.0, 0.8),
    "long": (7.0, 8.0, 2.0, 0.8),
    "carb_load": (10.0, 10.0, 1.6, 0.6),
    "race": (8.0, 8.0, 1.6, 0.6),
}
SESSION_KCAL_FULL_RANGE = 1500.0  # session kcal at which carbs sit at the top of their range
KCAL_PER_G_CARB = 4
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9

# --- goal adjustment (§7.4) ---
KCAL_PER_KG_BODY_MASS = 7700.0
MAX_DEFICIT_KCAL_PER_DAY = 500
DEFICIT_DAY_TYPES: frozenset[str] = frozenset({"rest", "easy", "moderate"})
SURPLUS_DAY_TYPES: frozenset[str] = frozenset({"hard", "long"})
SURPLUS_KCAL_MIN = 200
SURPLUS_KCAL_MAX = 300

# --- fluids (§7.5) ---
FLUID_ML_PER_KG_DAY = 35
FLUID_ML_PER_TRAINING_H = 500  # when no sweat rate is known

# --- bounds (§7.6) ---
MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM = 30.0
MIN_PROTEIN_G_PER_KG = 1.6
MIN_HARD_DAY_CARBS_G_PER_KG = 6.0
FUEL_CARBS_TIER_1 = 60  # g/h allowed without evidence
FUEL_CARBS_TIER_2 = 90  # g/h allowed with an ok log entry >= 60
FUEL_CARBS_MAX = 120  # g/h never exceeded
FUEL_FLUID_MAX_ML_PER_H = 1000
FUEL_SODIUM_MIN_MG_PER_H = 300
FUEL_SODIUM_MAX_MG_PER_H = 1500
CAFFEINE_MAX_MG_PER_KG_DAY = 6.0
PRE_RACE_WINDOW_MIN = (-240, -120)  # offset_min of the pre-race step, inclusive

# --- notes (strings the builder attaches to DayTarget.notes) ---
NOTE_FAT_FLOOR = "fat_floor"
NOTE_DEFICIT = "deficit"
NOTE_DEFICIT_PAUSED_DAY = "deficit paused: hard, long, carb-load or race day"
NOTE_DEFICIT_PAUSED_PHASE = "deficit paused: peak, taper, race or recovery week"
NOTE_SURPLUS = "surplus"
NOTE_PROFILE_HOURS = "no planned sessions; typed from the goal's weekly hours"
NOTE_NO_SESSIONS = "no planned sessions and no active goal; treated as rest"
```

- [ ] **Step 4: Write the energy module**

`packages/tri-nutrition/src/tri_nutrition/nutrition/energy.py`:
```python
"""RMR, session energy and day type. Pure: no I/O, no model calls. Spec §7.1 and §7.2."""

from __future__ import annotations

from datetime import date, timedelta

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    HARD_INTENSITIES,
    DayType,
    NutritionProfile,
    PlanContext,
    Session,
)


def ffm(profile: NutritionProfile) -> float:
    """Fat-free mass in kg. Uses the profile's body fat or the assumed value for the sex."""
    pct = profile.body_fat_pct
    if pct is None:
        pct = C.ASSUMED_BODY_FAT_PCT[profile.sex]
    return profile.weight_kg * (1 - pct / 100)


def rmr(profile: NutritionProfile) -> float:
    """Cunningham when body fat is known, else Mifflin-St Jeor."""
    if profile.body_fat_pct is not None:
        return C.CUNNINGHAM_BASE + C.CUNNINGHAM_PER_KG_FFM * ffm(profile)
    return (
        10 * profile.weight_kg
        + 6.25 * profile.height_cm
        - 5 * profile.age
        + C.MIFFLIN_SEX_TERM[profile.sex]
    )


def non_exercise_kcal(profile: NutritionProfile) -> float:
    return rmr(profile) * profile.activity_factor


def _fallback(session: Session, weight_kg: float) -> float:
    return session.hours * weight_kg * C.SPORT_KCAL_PER_KG_H[session.sport][session.intensity]


def session_kcal(session: Session, profile: NutritionProfile, ftp_watts: int | None) -> float:
    w = profile.weight_kg
    if session.sport == "brick":
        legs = session.legs
        if legs is None:
            bike_min = round(session.duration_min * C.BRICK_BIKE_FRACTION)
            legs = [
                session.model_copy(update={"sport": "bike", "duration_min": bike_min, "legs": None}),
                session.model_copy(
                    update={"sport": "run", "duration_min": session.duration_min - bike_min, "legs": None}
                ),
            ]
        return sum(session_kcal(leg, profile, ftp_watts) for leg in legs)
    if session.sport == "bike":
        if session.planned_tss is not None and ftp_watts:
            return session.planned_tss * ftp_watts * C.BIKE_KCAL_PER_TSS_FTP
        return _fallback(session, w)
    if session.sport == "run":
        if session.distance_km is not None:
            return w * session.distance_km
        return _fallback(session, w)
    if session.sport == "strength":
        return session.hours * C.STRENGTH_KCAL_PER_KG_H * w
    return _fallback(session, w)  # swim


def day_type(sessions: list[Session], day: date, ctx: PlanContext) -> DayType:
    """Spec §7.2. `sessions` are only that day's sessions."""
    if ctx.event_date is not None:
        if day == ctx.event_date:
            return "race"
        gap = (ctx.event_date - day).days
        if ctx.event_priority == "A" and 0 < gap <= C.CARB_LOAD_DAYS_BEFORE_RACE:
            return "carb_load"
    if not sessions:
        return "rest"
    if any(s.duration_min >= C.LONG_SESSION_MIN for s in sessions):
        return "long"
    if any(s.intensity in HARD_INTENSITIES for s in sessions):
        return "hard"
    total = sum(s.duration_min for s in sessions)
    tempo = sum(1 for s in sessions if s.intensity == "tempo")
    if total < C.EASY_MAX_MIN and tempo == 0:
        return "easy"
    return "moderate"


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())
```

Note on `day_type` ordering: the spec lists the rules in ascending order and says "any single session of 150 minutes or more is `long`", so `long` is checked before `hard` (a 3-hour threshold ride is a long day; the hard/long macro row is shared anyway). Two sessions totalling over 120 minutes with nothing above tempo fall through to `moderate`; the spec's "up to 120 minutes" is the easy/moderate split, not a cap.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_energy.py -q`
Expected: 23 passed.

- [ ] **Step 6: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): constants, RMR, session kcal and day type"
```

mypy note: `SPORT_KCAL_PER_KG_H` is typed `dict[Sport, dict[Intensity, float]]`, so every row is written with literal keys; a dict comprehension over a tuple of strings would not type-check under strict mode.

---

### Task 5: Targets builder

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/nutrition/targets.py`
- Test: `packages/tri-nutrition/tests/test_targets.py`

**Interfaces:**
- Consumes: `energy.*`, `constants.*`, models.
- Produces (pure):
  - `targets.sessions_by_day(sessions) -> dict[date, list[Session]]`
  - `targets.macro_grams(day_type, session_kcal, maintenance_kcal, weight_kg) -> tuple[int, int, int, int, bool]` = `(carbs_g, protein_g, fat_g, total_kcal, fat_floor_hit)` with `total_kcal = 4c + 4p + 9f`.
  - `targets.goal_adjust(profile, day_type, phase) -> tuple[int, list[str]]` signed kcal and notes.
  - `targets.fluid_baseline_ml(profile, sessions) -> int`
  - `targets.build(profile, sessions, ctx, today, horizon_days) -> list[DayTarget]` one per day from `today` for `horizon_days` days.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_targets.py`:
```python
from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy, targets
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session

MONDAY = date(2026, 9, 14)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180, weight_kg=80, body_fat_pct=15, sex="m", age=40, goal="maintain",
        pattern="omnivore", meals_per_day=3, cooks=True, tracks_food=True,
        scale_days_per_week=3, unit_preference="metric",
    )
    base.update(over)
    return NutritionProfile(**base)


def session(day=MONDAY, **over) -> Session:
    base = dict(day=day, sport="bike", duration_min=60, intensity="endurance")
    base.update(over)
    return Session(**base)


def ctx(**over) -> PlanContext:
    base = dict(source="plan")
    base.update(over)
    return PlanContext(**base)


# --- macro_grams ---


def test_macro_rest_day_bottom_of_range():
    c, p, f, total, floor = targets.macro_grams("rest", 0, 2500, 80)
    assert c == round(3.0 * 80) and p == round(1.8 * 80)
    assert f == round((2500 - 4 * c - 4 * p) / 9)
    assert total == 4 * c + 4 * p + 9 * f
    assert floor is False


def test_macro_position_scales_with_session_kcal():
    lo, *_ = targets.macro_grams("moderate", 0, 3000, 80)
    mid, *_ = targets.macro_grams("moderate", C.SESSION_KCAL_FULL_RANGE / 2, 3000, 80)
    hi, *_ = targets.macro_grams("moderate", C.SESSION_KCAL_FULL_RANGE * 2, 3000, 80)
    assert lo == round(5.0 * 80) and mid == round(5.5 * 80) and hi == round(6.0 * 80)


@pytest.mark.parametrize(
    "day_type,carbs_lo,protein,fat_min",
    [("rest", 3.0, 1.8, 0.8), ("easy", 3.0, 1.8, 0.8), ("moderate", 5.0, 1.8, 0.8),
     ("hard", 7.0, 2.0, 0.8), ("long", 7.0, 2.0, 0.8), ("carb_load", 10.0, 1.6, 0.6),
     ("race", 8.0, 1.6, 0.6)],
)
def test_macro_table_rows(day_type, carbs_lo, protein, fat_min):
    c, p, f, total, _ = targets.macro_grams(day_type, 0, 6000, 80)
    assert c == round(carbs_lo * 80) and p == round(protein * 80)
    assert f >= round(fat_min * 80)
    assert total == 4 * c + 4 * p + 9 * f


def test_macro_fat_floor_raises_total():
    # 1800 kcal cannot hold 240 g carbs + 144 g protein + 64 g fat
    c, p, f, total, floor = targets.macro_grams("rest", 0, 1800, 80)
    assert floor is True
    assert f == round(0.8 * 80)
    assert total == 4 * c + 4 * p + 9 * f and total > 1800


# --- goal_adjust ---


def test_maintain_no_adjust():
    assert targets.goal_adjust(profile(), "easy", "base") == (0, [])


def test_lose_deficit_on_easy_days_capped():
    p = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=0.5)
    budget = 0.5 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS  # 3080/week
    adj, notes = targets.goal_adjust(p, "easy", "base")
    assert adj == -round(budget / 7) and notes == [C.NOTE_DEFICIT]
    big = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=1.0)
    adj, _ = targets.goal_adjust(big, "rest", "build")
    assert adj == -C.MAX_DEFICIT_KCAL_PER_DAY  # 6160/7 = 880 > 500


@pytest.mark.parametrize("day_type", ["hard", "long", "carb_load", "race"])
def test_lose_paused_on_hard_days(day_type):
    p = profile(goal="lose", target_weight_kg=75)
    assert targets.goal_adjust(p, day_type, "base") == (0, [C.NOTE_DEFICIT_PAUSED_DAY])


@pytest.mark.parametrize("phase", ["peak", "taper", "race", "recovery"])
def test_lose_paused_in_late_phases(phase):
    p = profile(goal="lose", target_weight_kg=75)
    assert targets.goal_adjust(p, "easy", phase) == (0, [C.NOTE_DEFICIT_PAUSED_PHASE])


def test_lose_applies_when_phase_unknown():
    p = profile(goal="lose", target_weight_kg=75)
    adj, _ = targets.goal_adjust(p, "easy", None)
    assert adj < 0


def test_gain_surplus_on_hard_and_long_only():
    p = profile(goal="gain_lean")
    for dt in ("hard", "long"):
        adj, notes = targets.goal_adjust(p, dt, "build")
        assert C.SURPLUS_KCAL_MIN <= adj <= C.SURPLUS_KCAL_MAX and notes == [C.NOTE_SURPLUS]
    assert targets.goal_adjust(p, "easy", "build") == (0, [])
    assert targets.goal_adjust(p, "rest", "build") == (0, [])


# --- fluids ---


def test_fluid_baseline_without_sweat_rate():
    ml = targets.fluid_baseline_ml(profile(), [session(duration_min=90)])
    assert ml == 35 * 80 + round(1.5 * C.FLUID_ML_PER_TRAINING_H)


def test_fluid_baseline_with_sweat_rate():
    ml = targets.fluid_baseline_ml(profile(known_sweat_rate_l_per_h=1.2), [session(duration_min=90)])
    assert ml == 35 * 80 + round(1.5 * 1200)


def test_fluid_baseline_rest_day():
    assert targets.fluid_baseline_ml(profile(), []) == 35 * 80


# --- build ---


def test_build_one_target_per_day_in_order():
    out = targets.build(profile(), [], ctx(), MONDAY, 14)
    assert [t.day for t in out] == [MONDAY + timedelta(days=i) for i in range(14)]
    assert all(t.day_type == "rest" and t.source == "plan" for t in out)


def test_build_maintain_rest_day_equals_non_exercise_kcal():
    p = profile()
    t = targets.build(p, [], ctx(), MONDAY, 1)[0]
    c, pr, f, total, _ = targets.macro_grams("rest", 0, energy.non_exercise_kcal(p), 80)
    assert (t.carbs_g, t.protein_g, t.fat_g, t.total_kcal) == (c, pr, f, total)
    assert t.session_kcal == 0 and t.goal_adjust_kcal == 0


def test_build_session_day_adds_session_kcal_and_types_day():
    p = profile()
    s = session(duration_min=180, planned_tss=180)
    t = targets.build(p, [s], ctx(ftp_watts=250), MONDAY, 1)[0]
    assert t.day_type == "long"
    assert t.session_kcal == round(180 * 250 * 36 / 1000)
    maintenance = energy.non_exercise_kcal(p) + t.session_kcal
    assert abs(t.total_kcal - maintenance) <= 9  # macro rounding only; no goal adjust
    assert t.fluid_baseline_ml == 35 * 80 + round(3 * C.FLUID_ML_PER_TRAINING_H)


def test_build_deficit_lowers_total_and_records_adjust():
    p = profile(goal="lose", target_weight_kg=75)
    t = targets.build(p, [], ctx(), MONDAY, 1)[0]
    assert t.goal_adjust_kcal < 0 and C.NOTE_DEFICIT in t.notes
    maintenance = energy.non_exercise_kcal(p)
    assert t.total_kcal < maintenance


def test_build_phase_from_week_monday_and_pause():
    p = profile(goal="lose", target_weight_kg=75)
    phases = {MONDAY: "build", MONDAY + timedelta(days=7): "taper"}
    out = targets.build(p, [], ctx(phases=phases), MONDAY + timedelta(days=5), 4)
    assert [t.plan_phase for t in out] == ["build", "build", "taper", "taper"]
    assert out[0].goal_adjust_kcal < 0 and out[2].goal_adjust_kcal == 0
    assert C.NOTE_DEFICIT_PAUSED_PHASE in out[2].notes


def test_build_race_and_carb_load_days():
    c = ctx(event_date=MONDAY + timedelta(days=6), event_priority="A")
    out = targets.build(profile(), [], c, MONDAY, 7)
    assert [t.day_type for t in out] == ["rest", "rest", "rest", "rest", "carb_load", "carb_load", "race"]
    assert out[4].carbs_g == round(10 * 80)


def test_build_fat_floor_note():
    small = profile(weight_kg=60, body_fat_pct=None, activity_factor=1.2, goal="lose", target_weight_kg=55)
    t = targets.build(small, [], ctx(), MONDAY, 1)[0]
    assert C.NOTE_FAT_FLOOR in t.notes
    assert t.total_kcal == 4 * t.carbs_g + 4 * t.protein_g + 9 * t.fat_g


def test_build_profile_hours_fallback_spreads_goal_hours():
    c = ctx(source="profile_hours", weekly_hours=7)
    out = targets.build(profile(), [], c, MONDAY, 7)
    assert all(t.source == "profile_hours" and C.NOTE_PROFILE_HOURS in t.notes for t in out)
    assert all(t.day_type == "moderate" for t in out)  # 60 min endurance per day
    assert all(t.session_kcal > 0 for t in out)


def test_build_profile_hours_without_goal_is_rest():
    c = ctx(source="profile_hours")
    out = targets.build(profile(), [], c, MONDAY, 2)
    assert all(t.day_type == "rest" and C.NOTE_NO_SESSIONS in t.notes for t in out)


def test_build_ignores_sessions_outside_horizon():
    far = session(day=MONDAY + timedelta(days=30), duration_min=200)
    out = targets.build(profile(), [far], ctx(), MONDAY, 7)
    assert all(t.day_type == "rest" for t in out)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_targets.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.nutrition.targets'`.

- [ ] **Step 3: Write the builder**

`packages/tri-nutrition/src/tri_nutrition/nutrition/targets.py`:
```python
"""Profile + horizon of sessions -> one DayTarget per day. Pure: no I/O, no model calls.
Spec §7.3 to §7.5."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import (
    DEFICIT_PAUSE_PHASES,
    DayTarget,
    DayType,
    NutritionProfile,
    Phase,
    PlanContext,
    Session,
)


def sessions_by_day(sessions: list[Session]) -> dict[date, list[Session]]:
    out: dict[date, list[Session]] = defaultdict(list)
    for s in sessions:
        out[s.day].append(s)
    return dict(out)


def macro_grams(
    day_type: DayType, session_kcal: float, maintenance_kcal: float, weight_kg: float
) -> tuple[int, int, int, int, bool]:
    """(carbs_g, protein_g, fat_g, total_kcal, fat_floor_hit). total is 4c + 4p + 9f exactly."""
    carbs_lo, carbs_hi, protein_per_kg, fat_min_per_kg = C.MACRO_TABLE[day_type]
    position = min(max(session_kcal / C.SESSION_KCAL_FULL_RANGE, 0.0), 1.0)
    carbs = round((carbs_lo + (carbs_hi - carbs_lo) * position) * weight_kg)
    protein = round(protein_per_kg * weight_kg)
    fat_min = round(fat_min_per_kg * weight_kg)
    remainder = maintenance_kcal - C.KCAL_PER_G_CARB * carbs - C.KCAL_PER_G_PROTEIN * protein
    fat = round(remainder / C.KCAL_PER_G_FAT)
    floor_hit = fat < fat_min
    if floor_hit:
        fat = fat_min
    total = C.KCAL_PER_G_CARB * carbs + C.KCAL_PER_G_PROTEIN * protein + C.KCAL_PER_G_FAT * fat
    return carbs, protein, fat, total, floor_hit


def daily_deficit_kcal(profile: NutritionProfile) -> int:
    weekly_budget = profile.max_weekly_change_pct / 100 * profile.weight_kg * C.KCAL_PER_KG_BODY_MASS
    return min(C.MAX_DEFICIT_KCAL_PER_DAY, round(weekly_budget / 7))


def goal_adjust(
    profile: NutritionProfile, day_type: DayType, phase: Phase | None
) -> tuple[int, list[str]]:
    """Signed kcal adjustment for the day and the notes explaining it. Spec §7.4."""
    if profile.goal == "lose":
        if day_type not in C.DEFICIT_DAY_TYPES:
            return 0, [C.NOTE_DEFICIT_PAUSED_DAY]
        if phase in DEFICIT_PAUSE_PHASES:
            return 0, [C.NOTE_DEFICIT_PAUSED_PHASE]
        return -daily_deficit_kcal(profile), [C.NOTE_DEFICIT]
    if profile.goal == "gain_lean" and day_type in C.SURPLUS_DAY_TYPES:
        return round((C.SURPLUS_KCAL_MIN + C.SURPLUS_KCAL_MAX) / 2), [C.NOTE_SURPLUS]
    return 0, []


def fluid_baseline_ml(profile: NutritionProfile, sessions: list[Session]) -> int:
    hours = sum(s.hours for s in sessions)
    per_h = (
        profile.known_sweat_rate_l_per_h * 1000
        if profile.known_sweat_rate_l_per_h is not None
        else C.FLUID_ML_PER_TRAINING_H
    )
    return round(C.FLUID_ML_PER_KG_DAY * profile.weight_kg + hours * per_h)


def _profile_hours_session(day: date, weekly_hours: float) -> Session:
    return Session(
        day=day,
        sport="bike",
        duration_min=round(weekly_hours * 60 / 7),
        intensity="endurance",
        title="assumed from weekly hours",
    )


def build(
    profile: NutritionProfile,
    sessions: list[Session],
    ctx: PlanContext,
    today: date,
    horizon_days: int,
) -> list[DayTarget]:
    by_day = sessions_by_day(sessions)
    base_kcal = energy.non_exercise_kcal(profile)
    out: list[DayTarget] = []
    for i in range(horizon_days):
        day = today + timedelta(days=i)
        notes: list[str] = []
        day_sessions = by_day.get(day, [])
        if ctx.source == "profile_hours" and not day_sessions:
            if ctx.weekly_hours:
                day_sessions = [_profile_hours_session(day, ctx.weekly_hours)]
                notes.append(C.NOTE_PROFILE_HOURS)
            else:
                notes.append(C.NOTE_NO_SESSIONS)
        dt = energy.day_type(day_sessions, day, ctx)
        phase = ctx.phases.get(energy.week_monday(day))
        s_kcal = round(sum(energy.session_kcal(s, profile, ctx.ftp_watts) for s in day_sessions))
        adjust, adjust_notes = goal_adjust(profile, dt, phase)
        notes.extend(adjust_notes)
        carbs, protein, fat, total, floor_hit = macro_grams(
            dt, s_kcal, base_kcal + s_kcal + adjust, profile.weight_kg
        )
        if floor_hit:
            notes.append(C.NOTE_FAT_FLOOR)
        out.append(
            DayTarget(
                day=day,
                day_type=dt,
                session_kcal=s_kcal,
                total_kcal=total,
                carbs_g=carbs,
                protein_g=protein,
                fat_g=fat,
                fluid_baseline_ml=fluid_baseline_ml(profile, day_sessions),
                goal_adjust_kcal=adjust,
                plan_phase=phase,
                source=ctx.source,
                notes=notes,
            )
        )
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_targets.py -q`
Expected: 35 passed. If `test_build_fat_floor_note` does not hit the floor, lower `weight_kg` in that test further (the point is a small athlete on a deficit whose carb and protein grams leave under `0.8 g/kg` for fat); it is a test-data tweak, not a code change.

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): day targets builder with macro table, goal adjustment and fluids"
```

---

### Task 6: Bounds validators

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/nutrition/bounds.py`
- Test: `packages/tri-nutrition/tests/test_bounds.py`

**Interfaces:**
- Consumes: `energy.ffm`, `energy.rmr`, models, constants.
- Produces (pure, each returns `list[str]`, empty when valid):
  - `bounds.validate_targets(targets: list[DayTarget], profile: NutritionProfile) -> list[str]`
  - `bounds.validate_fuel(fuel: SessionFuel, profile, library: list[Product], fuel_log: list[FuelLogEntry], other_caffeine_mg_today: int = 0) -> list[str]`
  - `bounds.validate_race(plan: RaceFuelPlan, profile, library, fuel_log) -> list[str]`
  - `bounds.carbs_evidence(fuel_log) -> int` the highest `carbs_g_per_h` with outcome `ok`, `0` when none.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_bounds.py`:
```python
from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition import bounds, energy
from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    RaceFuelPlan,
    RaceFuelStep,
    SessionFuel,
)

MONDAY = date(2026, 9, 14)


def profile(**over) -> NutritionProfile:
    base = dict(
        height_cm=180, weight_kg=80, body_fat_pct=15, sex="m", age=40, goal="maintain",
        pattern="omnivore", meals_per_day=3, cooks=True, tracks_food=True,
        scale_days_per_week=3, unit_preference="metric", caffeine_mg_per_day=200,
    )
    base.update(over)
    return NutritionProfile(**base)


def target(day=MONDAY, **over) -> DayTarget:
    base = dict(
        day=day, day_type="easy", session_kcal=0, total_kcal=2800, carbs_g=280, protein_g=150,
        fat_g=120, fluid_baseline_ml=2800, goal_adjust_kcal=0, plan_phase="base", source="plan",
    )
    base.update(over)
    return DayTarget(**base)


LIB = [Product(name="Gel", form="gel", carbs_g=25, sodium_mg=50, caffeine_mg=0),
       Product(name="Mix", form="drink", carbs_g=40, sodium_mg=400, caffeine_mg=0)]


def fuel(**over) -> SessionFuel:
    base = dict(
        tp_workout_id="w1", day=MONDAY, pre="toast", carbs_g_per_h=60, fluid_ml_per_h=600,
        sodium_mg_per_h=500, caffeine_mg=None, products=["Gel", "Mix"], post="shake",
        gut_training=False, note_text="",
    )
    base.update(over)
    return SessionFuel(**base)


def log(carbs: int, outcome: str = "ok") -> FuelLogEntry:
    return FuelLogEntry(day=MONDAY - timedelta(days=7), sport="bike", duration_min=120,
                        carbs_g_per_h=carbs, outcome=outcome)


# --- validate_targets ---


def test_targets_valid():
    assert bounds.validate_targets([target()], profile()) == []


def test_targets_energy_availability():
    p = profile()
    # EA = (total - session) / ffm < 30
    low = round(30 * energy.ffm(p)) - 50
    out = bounds.validate_targets([target(total_kcal=low + 0, session_kcal=0, protein_g=150, carbs_g=100, fat_g=50)], p)
    assert any("energy availability" in v for v in out)


def test_targets_below_rmr():
    p = profile()
    t = target(total_kcal=round(energy.rmr(p)) - 1, session_kcal=0)
    assert any("below RMR" in v for v in bounds.validate_targets([t], p))


def test_targets_protein_floor():
    t = target(protein_g=round(1.5 * 80))
    assert any("protein" in v for v in bounds.validate_targets([t], profile()))


@pytest.mark.parametrize("day_type", ["hard", "long"])
def test_targets_hard_day_carbs(day_type):
    t = target(day_type=day_type, carbs_g=round(5.9 * 80), total_kcal=4000, session_kcal=1000)
    assert any("carbs" in v for v in bounds.validate_targets([t], profile()))
    ok = target(day_type=day_type, carbs_g=round(6.0 * 80), total_kcal=4000, session_kcal=1000)
    assert bounds.validate_targets([ok], profile()) == []


def test_targets_seven_day_deficit_bound():
    p = profile(goal="lose", target_weight_kg=75, max_weekly_change_pct=0.5)
    budget = 0.5 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS  # 3080
    per_day = -round(budget / 7)
    ok = [target(day=MONDAY + timedelta(days=i), goal_adjust_kcal=per_day) for i in range(7)]
    assert bounds.validate_targets(ok, p) == []
    bad = [target(day=MONDAY + timedelta(days=i), goal_adjust_kcal=per_day - 20) for i in range(7)]
    assert any("seven-day deficit" in v for v in bounds.validate_targets(bad, p))


def test_targets_deficit_in_forbidden_phase():
    p = profile(goal="lose", target_weight_kg=75)
    for phase in ("peak", "taper", "race"):
        t = target(goal_adjust_kcal=-300, plan_phase=phase)
        assert any("deficit" in v and phase in v for v in bounds.validate_targets([t], p))
    ok = target(goal_adjust_kcal=-300, plan_phase="recovery")
    assert bounds.validate_targets([ok], p) == []  # pause is the builder's job; not forbidden


# --- validate_fuel ---


def test_fuel_valid():
    assert bounds.validate_fuel(fuel(), profile(), LIB, []) == []


def test_carbs_evidence():
    assert bounds.carbs_evidence([]) == 0
    assert bounds.carbs_evidence([log(70), log(95, "gi_upset"), log(65)]) == 70


def test_fuel_carbs_tiers():
    assert any("60" in v for v in bounds.validate_fuel(fuel(carbs_g_per_h=61), profile(), LIB, []))
    assert bounds.validate_fuel(fuel(carbs_g_per_h=90), profile(), LIB, [log(60)]) == []
    assert any("90" in v for v in bounds.validate_fuel(fuel(carbs_g_per_h=91), profile(), LIB, [log(60)]))
    assert bounds.validate_fuel(fuel(carbs_g_per_h=120), profile(), LIB, [log(90)]) == []
    assert any("120" in v for v in bounds.validate_fuel(fuel(carbs_g_per_h=121), profile(), LIB, [log(130)]))


def test_fuel_gi_upset_is_not_evidence():
    assert any("60" in v for v in bounds.validate_fuel(fuel(carbs_g_per_h=70), profile(), LIB, [log(70, "gi_upset")]))


def test_fuel_fluid_and_sodium():
    assert any("fluid" in v for v in bounds.validate_fuel(fuel(fluid_ml_per_h=1001), profile(), LIB, []))
    assert any("sodium" in v for v in bounds.validate_fuel(fuel(sodium_mg_per_h=299), profile(), LIB, []))
    assert any("sodium" in v for v in bounds.validate_fuel(fuel(sodium_mg_per_h=1501), profile(), LIB, []))


def test_fuel_caffeine_rules():
    assert any("caffeine" in v for v in bounds.validate_fuel(fuel(caffeine_mg=50), profile(caffeine_mg_per_day=0), LIB, []))
    assert bounds.validate_fuel(fuel(caffeine_mg=100), profile(), LIB, []) == []
    # 6 mg/kg * 80 = 480; 300 in this session + 200 elsewhere today = 500
    assert any("caffeine" in v for v in bounds.validate_fuel(fuel(caffeine_mg=300), profile(), LIB, [], other_caffeine_mg_today=200))
    assert bounds.validate_fuel(fuel(caffeine_mg=300), profile(caffeine_mg_per_day=None), LIB, []) == []


def test_fuel_unknown_product():
    out = bounds.validate_fuel(fuel(products=["Gel", "Mystery"]), profile(), LIB, [])
    assert any("Mystery" in v for v in out)


# --- validate_race ---


def race(**over) -> RaceFuelPlan:
    base = dict(
        event_date=MONDAY,
        timeline=[
            RaceFuelStep(offset_min=-180, leg="pre", what="oats", carbs_g=120, fluid_ml=500, sodium_mg=300, caffeine_mg=100),
            RaceFuelStep(offset_min=30, leg="bike", what="gel", carbs_g=25, fluid_ml=250, sodium_mg=200, products=["Gel"]),
            RaceFuelStep(offset_min=150, leg="run", what="gel", carbs_g=25, fluid_ml=200, sodium_mg=150, products=["Gel"]),
        ],
        totals_per_h={"bike_carbs": 80, "run_carbs": 60, "bike_fluid": 700, "run_fluid": 500,
                      "bike_sodium": 600, "run_sodium": 400},
        contingencies=["if GI: drop to water and gels"],
        note_text="",
    )
    base.update(over)
    return RaceFuelPlan(**base)


def test_race_valid_with_evidence():
    assert bounds.validate_race(race(), profile(), LIB, [log(80)]) == []


def test_race_leg_carbs_need_evidence():
    out = bounds.validate_race(race(), profile(), LIB, [])
    assert any("bike" in v and "60" in v for v in out)


def test_race_leg_fluid_and_sodium_bounds():
    t = race(totals_per_h={"bike_carbs": 60, "run_carbs": 60, "bike_fluid": 1100, "run_fluid": 500,
                           "bike_sodium": 600, "run_sodium": 200})
    out = bounds.validate_race(t, profile(), LIB, [])
    assert any("bike" in v and "fluid" in v for v in out)
    assert any("run" in v and "sodium" in v for v in out)


def test_race_pre_step_window():
    early = race(timeline=[RaceFuelStep(offset_min=-300, leg="pre", what="x", carbs_g=50, fluid_ml=0, sodium_mg=0)],
                 totals_per_h={"bike_carbs": 60, "run_carbs": 60})
    assert any("pre-race" in v for v in bounds.validate_race(early, profile(), LIB, []))
    late = race(timeline=[RaceFuelStep(offset_min=-60, leg="pre", what="x", carbs_g=50, fluid_ml=0, sodium_mg=0)],
                totals_per_h={"bike_carbs": 60, "run_carbs": 60})
    assert any("pre-race" in v for v in bounds.validate_race(late, profile(), LIB, []))
    missing = race(timeline=[], totals_per_h={"bike_carbs": 60, "run_carbs": 60})
    assert any("pre-race" in v for v in bounds.validate_race(missing, profile(), LIB, []))


def test_race_total_caffeine():
    steps = [RaceFuelStep(offset_min=-180, leg="pre", what="x", carbs_g=50, fluid_ml=0, sodium_mg=0, caffeine_mg=300),
             RaceFuelStep(offset_min=60, leg="bike", what="x", carbs_g=25, fluid_ml=0, sodium_mg=0, caffeine_mg=200)]
    t = race(timeline=steps, totals_per_h={"bike_carbs": 60, "run_carbs": 60})
    assert any("caffeine" in v for v in bounds.validate_race(t, profile(), LIB, []))  # 500 > 480


def test_race_unknown_product():
    steps = [RaceFuelStep(offset_min=-180, leg="pre", what="x", carbs_g=50, fluid_ml=0, sodium_mg=0),
             RaceFuelStep(offset_min=60, leg="bike", what="x", carbs_g=25, fluid_ml=0, sodium_mg=0, products=["Nope"])]
    t = race(timeline=steps, totals_per_h={"bike_carbs": 60, "run_carbs": 60})
    assert any("Nope" in v for v in bounds.validate_race(t, profile(), LIB, []))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_bounds.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.nutrition.bounds'`.

- [ ] **Step 3: Write the validators**

`packages/tri-nutrition/src/tri_nutrition/nutrition/bounds.py`:
```python
"""Safety bounds over targets and fuel plans. Pure; returns violations, never edits. Spec §7.6."""

from __future__ import annotations

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import (
    DEFICIT_FORBIDDEN_PHASES,
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    RaceFuelPlan,
    SessionFuel,
)


def validate_targets(targets: list[DayTarget], profile: NutritionProfile) -> list[str]:
    out: list[str] = []
    ffm = energy.ffm(profile)
    rmr = energy.rmr(profile)
    w = profile.weight_kg
    for t in targets:
        ea = (t.total_kcal - t.session_kcal) / ffm
        if ea < C.MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM:
            out.append(
                f"{t.day}: energy availability {ea:.0f} kcal/kg FFM is below "
                f"{C.MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM:.0f}"
            )
        if t.total_kcal < rmr:
            out.append(f"{t.day}: total {t.total_kcal} kcal is below RMR {rmr:.0f}")
        if t.protein_g < C.MIN_PROTEIN_G_PER_KG * w:
            out.append(
                f"{t.day}: protein {t.protein_g} g is below {C.MIN_PROTEIN_G_PER_KG} g/kg"
            )
        if t.day_type in ("hard", "long") and t.carbs_g < C.MIN_HARD_DAY_CARBS_G_PER_KG * w:
            out.append(
                f"{t.day}: carbs {t.carbs_g} g on a {t.day_type} day is below "
                f"{C.MIN_HARD_DAY_CARBS_G_PER_KG} g/kg"
            )
        if t.goal_adjust_kcal < 0 and t.plan_phase in DEFICIT_FORBIDDEN_PHASES:
            out.append(f"{t.day}: deficit of {-t.goal_adjust_kcal} kcal in a {t.plan_phase} week")
    weekly_budget = profile.max_weekly_change_pct / 100 * w * C.KCAL_PER_KG_BODY_MASS
    ordered = sorted(targets, key=lambda t: t.day)
    for i in range(len(ordered)):
        window = [t for t in ordered[i:] if (t.day - ordered[i].day).days < 7]
        deficit = -sum(min(t.goal_adjust_kcal, 0) for t in window)
        if deficit > weekly_budget + 0.5:
            out.append(
                f"{ordered[i].day}: seven-day deficit {deficit:.0f} kcal exceeds the "
                f"{profile.max_weekly_change_pct:g} %/week bound ({weekly_budget:.0f} kcal)"
            )
            break
    return out


def carbs_evidence(fuel_log: list[FuelLogEntry]) -> int:
    """Highest carbs/h the athlete has taken with outcome ok; 0 without evidence."""
    return max((e.carbs_g_per_h for e in fuel_log if e.outcome == "ok"), default=0)


def _carbs_per_h_violations(label: str, carbs: int, evidence: int) -> list[str]:
    if carbs > C.FUEL_CARBS_MAX:
        return [f"{label}: {carbs} g/h carbs exceeds the {C.FUEL_CARBS_MAX} g/h ceiling"]
    if carbs > C.FUEL_CARBS_TIER_2 and evidence < C.FUEL_CARBS_TIER_2:
        return [
            f"{label}: {carbs} g/h carbs needs a logged ok session at or above "
            f"{C.FUEL_CARBS_TIER_2} g/h (best so far: {evidence})"
        ]
    if carbs > C.FUEL_CARBS_TIER_1 and evidence < C.FUEL_CARBS_TIER_1:
        return [
            f"{label}: {carbs} g/h carbs needs a logged ok session at or above "
            f"{C.FUEL_CARBS_TIER_1} g/h (best so far: {evidence})"
        ]
    return []


def _fluid_sodium_violations(label: str, fluid: int | None, sodium: int | None) -> list[str]:
    out: list[str] = []
    if fluid is not None and fluid > C.FUEL_FLUID_MAX_ML_PER_H:
        out.append(f"{label}: fluid {fluid} ml/h exceeds {C.FUEL_FLUID_MAX_ML_PER_H}")
    if sodium is not None and not (
        C.FUEL_SODIUM_MIN_MG_PER_H <= sodium <= C.FUEL_SODIUM_MAX_MG_PER_H
    ):
        out.append(
            f"{label}: sodium {sodium} mg/h is outside {C.FUEL_SODIUM_MIN_MG_PER_H} to "
            f"{C.FUEL_SODIUM_MAX_MG_PER_H}"
        )
    return out


def _product_violations(label: str, names: list[str], library: list[Product]) -> list[str]:
    known = {p.name for p in library}
    return [f"{label}: product {n!r} is not in the product library" for n in names if n not in known]


def _caffeine_violations(label: str, total_mg: float, profile: NutritionProfile) -> list[str]:
    if total_mg <= 0:
        return []
    if profile.caffeine_mg_per_day == 0:
        return [f"{label}: caffeine planned but the athlete takes none"]
    cap = C.CAFFEINE_MAX_MG_PER_KG_DAY * profile.weight_kg
    if total_mg > cap:
        return [
            f"{label}: caffeine {total_mg:.0f} mg exceeds {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg/kg "
            f"({cap:.0f} mg)"
        ]
    return []


def validate_fuel(
    fuel: SessionFuel,
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    other_caffeine_mg_today: int = 0,
) -> list[str]:
    label = f"{fuel.day} {fuel.tp_workout_id}"
    out = _carbs_per_h_violations(label, fuel.carbs_g_per_h, carbs_evidence(fuel_log))
    out += _fluid_sodium_violations(label, fuel.fluid_ml_per_h, fuel.sodium_mg_per_h)
    caffeine = fuel.caffeine_mg or 0
    if caffeine:
        out += _caffeine_violations(label, caffeine + other_caffeine_mg_today, profile)
    out += _product_violations(label, fuel.products, library)
    return out


def validate_race(
    plan: RaceFuelPlan,
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
) -> list[str]:
    out: list[str] = []
    evidence = carbs_evidence(fuel_log)
    for leg in ("bike", "run"):
        label = f"{plan.event_date} {leg}"
        carbs = plan.totals_per_h.get(f"{leg}_carbs")
        if carbs is not None:
            out += _carbs_per_h_violations(label, carbs, evidence)
        out += _fluid_sodium_violations(
            label, plan.totals_per_h.get(f"{leg}_fluid"), plan.totals_per_h.get(f"{leg}_sodium")
        )
    lo, hi = C.PRE_RACE_WINDOW_MIN
    pre = [s for s in plan.timeline if s.leg == "pre"]
    if not pre:
        out.append(f"{plan.event_date}: no pre-race step")
    elif not any(lo <= s.offset_min <= hi for s in pre):
        out.append(
            f"{plan.event_date}: pre-race meal must fall {-hi // 60} to {-lo // 60} hours before "
            f"the start (offsets: {[s.offset_min for s in pre]})"
        )
    total_caffeine = sum(s.caffeine_mg for s in plan.timeline)
    out += _caffeine_violations(f"{plan.event_date} race", total_caffeine, profile)
    for s in plan.timeline:
        out += _product_violations(f"{plan.event_date} {s.leg} +{s.offset_min}", s.products, library)
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_bounds.py -q`
Expected: 21 passed. `test_targets_energy_availability` builds a low-total target by hand; if it trips the RMR or protein rule as well that is fine (the assertion only looks for the EA message).

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): bounds validators for targets, session fuel and race plans"
```

---

### Task 7: Nutrition repository

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/repo.py`
- Test: `packages/tri-nutrition/tests/test_repo.py`

**Interfaces:**
- Consumes: `tri_core.db.repo.Conn`, `psycopg.types.json.Jsonb`, models, `migrations/004_nutrition.sql`.
- Produces (every function takes an open connection; callers commit):
  - `upsert_targets(conn, targets: list[DayTarget]) -> None` (resets `written_to_garmin` to false when kcal or macros changed; keeps it otherwise)
  - `list_targets(conn, start: date, end: date) -> list[StoredDayTarget]` inclusive
  - `mark_targets_written(conn, days: list[date]) -> None`
  - `delete_unwritten_targets(conn) -> int`
  - `upsert_fuel_plan(conn, kind, day, tp_workout_id, payload: dict, violations: list[str]) -> int`
  - `list_fuel_plans(conn, start, end) -> list[StoredFuelPlan]`
  - `mark_fuel_written(conn, plan_id: int, tp_note_id: str | None) -> None`
  - `delete_unwritten_fuel_plans(conn) -> int`
  - `insert_change(conn, thread_id, change: NutritionChange, result: dict | None) -> int`
  - `owned_note_ids(conn) -> set[str]` note ids from `set_race_note` rows
  - `last_change_at(conn) -> datetime | None`

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_repo.py`:
```python
from datetime import date, timedelta

import pytest

from tri_nutrition import repo
from tri_nutrition.nutrition.models import DayTarget, NutritionChange

pytestmark = pytest.mark.db

MON = date(2026, 9, 14)


@pytest.fixture
def ndb(db):
    if db.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied to the test database")
    return db


def target(day=MON, **over) -> DayTarget:
    base = dict(
        day=day, day_type="easy", session_kcal=300, total_kcal=2800, carbs_g=280, protein_g=150,
        fat_g=120, fluid_baseline_ml=2800, goal_adjust_kcal=0, plan_phase="base", source="plan",
        notes=["deficit"],
    )
    base.update(over)
    return DayTarget(**base)


def test_targets_roundtrip(ndb):
    ts = [target(MON + timedelta(days=i), total_kcal=2800 + i) for i in range(3)]
    repo.upsert_targets(ndb, ts)
    stored = repo.list_targets(ndb, MON, MON + timedelta(days=2))
    assert [s.target for s in stored] == ts
    assert all(s.written_to_garmin is False for s in stored)
    assert repo.list_targets(ndb, MON + timedelta(days=1), MON + timedelta(days=1))[0].target.total_kcal == 2801


def test_upsert_keeps_written_flag_when_unchanged(ndb):
    repo.upsert_targets(ndb, [target()])
    repo.mark_targets_written(ndb, [MON])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is True
    repo.upsert_targets(ndb, [target(notes=["different note only"])])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is True
    repo.upsert_targets(ndb, [target(carbs_g=300)])
    assert repo.list_targets(ndb, MON, MON)[0].written_to_garmin is False


def test_delete_unwritten_targets(ndb):
    repo.upsert_targets(ndb, [target(MON), target(MON + timedelta(days=1))])
    repo.mark_targets_written(ndb, [MON])
    assert repo.delete_unwritten_targets(ndb) == 1
    assert [s.target.day for s in repo.list_targets(ndb, MON, MON + timedelta(days=1))] == [MON]


def test_fuel_plans_roundtrip_and_unique(ndb):
    pid = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"carbs_g_per_h": 60}, [])
    again = repo.upsert_fuel_plan(ndb, "session", MON, "w1", {"carbs_g_per_h": 70}, ["too much"])
    assert again == pid
    rid = repo.upsert_fuel_plan(ndb, "race", MON, None, {"note_text": "race"}, [])
    plans = repo.list_fuel_plans(ndb, MON, MON)
    assert {p.kind for p in plans} == {"session", "race"}
    sess = next(p for p in plans if p.kind == "session")
    assert sess.payload == {"carbs_g_per_h": 70} and sess.violations == ["too much"]
    assert sess.written is False and sess.tp_note_id is None
    repo.mark_fuel_written(ndb, rid, "note-9")
    race = next(p for p in repo.list_fuel_plans(ndb, MON, MON) if p.kind == "race")
    assert race.written is True and race.tp_note_id == "note-9"
    assert repo.delete_unwritten_fuel_plans(ndb) == 1


def test_changes_and_note_ownership(ndb):
    assert repo.last_change_at(ndb) is None
    day_change = NutritionChange(op="set_day_targets", target_key=MON.isoformat(), day=MON,
                                 payload={"calorie_goal": 2800}, reason="new")
    repo.insert_change(ndb, "nutrition", day_change, {"ok": True})
    note = NutritionChange(op="set_race_note", target_key="note-9", day=MON,
                           payload={"title": "Race fuel"}, reason="race")
    repo.insert_change(ndb, "nutrition", note, {"id": "note-9"})
    assert repo.owned_note_ids(ndb) == {"note-9"}
    row = ndb.execute("select * from nutrition_changes where target_key = 'note-9'").fetchone()
    assert row["operation"] == "set_race_note" and row["payload"]["op"] == "set_race_note"
    assert row["result"] == {"id": "note-9"} and row["reason"] == "race"
    assert repo.last_change_at(ndb) is not None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_repo.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.repo'` (or 5 skips if Postgres is down; start it with `docker compose up -d`).

- [ ] **Step 3: Write the repository**

`packages/tri-nutrition/src/tri_nutrition/repo.py`:
```python
"""Nutrition-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    StoredDayTarget,
    StoredFuelPlan,
)


def upsert_targets(conn: Conn, targets: list[DayTarget]) -> None:
    """Insert or replace one row per day. written_to_garmin is cleared only when kcal or a macro
    changed, so unchanged days are not re-sent."""
    with conn.cursor() as cur:
        for t in targets:
            cur.execute(
                """
                insert into nutrition_targets (day, day_type, session_kcal, total_kcal, carbs_g,
                    protein_g, fat_g, fluid_baseline_ml, goal_adjust_kcal, notes, plan_phase,
                    source, generated_at)
                values (%(day)s, %(day_type)s, %(session_kcal)s, %(total_kcal)s, %(carbs_g)s,
                    %(protein_g)s, %(fat_g)s, %(fluid_baseline_ml)s, %(goal_adjust_kcal)s,
                    %(notes)s, %(plan_phase)s, %(source)s, now())
                on conflict (day) do update set
                    day_type = excluded.day_type,
                    session_kcal = excluded.session_kcal,
                    total_kcal = excluded.total_kcal,
                    carbs_g = excluded.carbs_g,
                    protein_g = excluded.protein_g,
                    fat_g = excluded.fat_g,
                    fluid_baseline_ml = excluded.fluid_baseline_ml,
                    goal_adjust_kcal = excluded.goal_adjust_kcal,
                    notes = excluded.notes,
                    plan_phase = excluded.plan_phase,
                    source = excluded.source,
                    written_to_garmin = nutrition_targets.written_to_garmin
                        and nutrition_targets.total_kcal = excluded.total_kcal
                        and nutrition_targets.carbs_g = excluded.carbs_g
                        and nutrition_targets.protein_g = excluded.protein_g
                        and nutrition_targets.fat_g = excluded.fat_g,
                    generated_at = now()
                """,
                {**t.model_dump(mode="json"), "day": t.day, "notes": Jsonb(t.notes)},
            )


def _target(row: dict[str, Any]) -> StoredDayTarget:
    return StoredDayTarget(
        target=DayTarget(
            day=row["day"],
            day_type=row["day_type"],
            session_kcal=row["session_kcal"],
            total_kcal=row["total_kcal"],
            carbs_g=row["carbs_g"],
            protein_g=row["protein_g"],
            fat_g=row["fat_g"],
            fluid_baseline_ml=row["fluid_baseline_ml"],
            goal_adjust_kcal=row["goal_adjust_kcal"],
            plan_phase=row["plan_phase"],
            source=row["source"],
            notes=row["notes"] or [],
        ),
        written_to_garmin=row["written_to_garmin"],
    )


def list_targets(conn: Conn, start: date, end: date) -> list[StoredDayTarget]:
    rows = conn.execute(
        "select * from nutrition_targets where day between %s and %s order by day", (start, end)
    ).fetchall()
    return [_target(r) for r in rows]


def mark_targets_written(conn: Conn, days: list[date]) -> None:
    if not days:
        return
    conn.execute(
        "update nutrition_targets set written_to_garmin = true where day = any(%s)", (days,)
    )


def delete_unwritten_targets(conn: Conn) -> int:
    return conn.execute("delete from nutrition_targets where not written_to_garmin").rowcount


def upsert_fuel_plan(
    conn: Conn,
    kind: str,
    day: date,
    tp_workout_id: str | None,
    payload: dict[str, Any],
    violations: list[str],
) -> int:
    row = conn.execute(
        """
        insert into fuel_plans (kind, day, tp_workout_id, payload, violations, generated_at)
        values (%s, %s, %s, %s, %s, now())
        on conflict (kind, day, coalesce(tp_workout_id, '')) do update set
            payload = excluded.payload,
            violations = excluded.violations,
            written = false,
            generated_at = now()
        returning id
        """,
        (kind, day, tp_workout_id, Jsonb(payload), Jsonb(violations)),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _fuel(row: dict[str, Any]) -> StoredFuelPlan:
    return StoredFuelPlan(
        id=row["id"],
        kind=row["kind"],
        day=row["day"],
        tp_workout_id=row["tp_workout_id"],
        tp_note_id=row["tp_note_id"],
        payload=row["payload"],
        violations=row["violations"] or [],
        written=row["written"],
    )


def list_fuel_plans(conn: Conn, start: date, end: date) -> list[StoredFuelPlan]:
    rows = conn.execute(
        "select * from fuel_plans where day between %s and %s order by day, kind, id",
        (start, end),
    ).fetchall()
    return [_fuel(r) for r in rows]


def mark_fuel_written(conn: Conn, plan_id: int, tp_note_id: str | None) -> None:
    conn.execute(
        "update fuel_plans set written = true, tp_note_id = coalesce(%s::text, tp_note_id) "
        "where id = %s",
        (tp_note_id, plan_id),
    )


def delete_unwritten_fuel_plans(conn: Conn) -> int:
    return conn.execute("delete from fuel_plans where not written").rowcount


def insert_change(
    conn: Conn, thread_id: str, change: NutritionChange, result: dict[str, Any] | None
) -> int:
    row = conn.execute(
        """
        insert into nutrition_changes (thread_id, operation, target_key, payload, result, reason)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (
            thread_id,
            change.op,
            change.target_key,
            Jsonb(change.model_dump(mode="json")),
            Jsonb(result) if result is not None else None,
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def owned_note_ids(conn: Conn) -> set[str]:
    rows = conn.execute(
        "select distinct target_key from nutrition_changes "
        "where operation = 'set_race_note' and target_key <> ''"
    ).fetchall()
    return {r["target_key"] for r in rows}


def last_change_at(conn: Conn) -> datetime | None:
    row = conn.execute("select max(applied_at) as at from nutrition_changes").fetchone()
    return row["at"] if row else None
```

The `on conflict (kind, day, coalesce(tp_workout_id, ''))` clause must name the same expression as the unique index in `004_nutrition.sql`; Postgres matches expression indexes by expression text, so keep them identical.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_repo.py -q`
Expected: 5 passed (or 5 skipped with the migration-not-applied reason until Brian applies `004_nutrition.sql` to `tri_analyze_test`).

- [ ] **Step 5: Lint, type-check, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): repository over nutrition_targets, fuel_plans, nutrition_changes"
```

---

### Task 8: Record the Garmin nutrition fixtures (spec §15, opt-in)

**What this does:** answers the first two open items in spec §15 before Plan 2 needs them: the JSON shapes of `get_body_composition`, `get_nutrition_daily_food_log`, `get_nutrition_daily_meals`, `get_nutrition_daily_settings`, and whether `set_nutrition_daily_settings` on a future date creates a per-day override. Read-only except for one round-trip write 400 days out that restores the previous values. Needs Garmin auth; run when Brian is present.

**Files:**
- Create: `scripts/spike_nutrition.py`
- Create (recorded, scrubbed, committed): `packages/tri-nutrition/tests/fixtures/mcp/get_body_composition.json`, `get_nutrition_daily_food_log.json`, `get_nutrition_daily_meals.json`, `get_nutrition_daily_settings.json`, `set_nutrition_daily_settings.json`

- [ ] **Step 1: Write the spike**

`scripts/spike_nutrition.py`:
```python
"""One-off spike for the nutrition agent: record the Garmin body-composition and nutrition tool
payloads, and probe whether set_nutrition_daily_settings on a far-future date is per-day.

Run:  uv run python scripts/spike_nutrition.py [--days 14] [--probe-write]
Writes packages/tri-nutrition/tests/fixtures/mcp/<tool>.json. Review each file before
committing: scrub anything you consider private. Numbers are fine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tri_core.config import get_settings
from tri_core.mcp.client import McpToolClient, McpToolError
from tri_core.mcp.servers import garmin_spec

OUT = Path("packages/tri-nutrition/tests/fixtures/mcp")
NUTRITION_TOOLS = [
    "get_body_composition",
    "get_daily_weigh_ins",
    "get_user_profile",
    "get_nutrition_daily_food_log",
    "get_nutrition_daily_meals",
    "get_nutrition_daily_settings",
    "set_nutrition_daily_settings",
    "get_hydration_data",
    "get_stats",
]


async def record(client: McpToolClient, tool: str, args: dict[str, Any], suffix: str = "") -> Any:
    name = f"{tool}{suffix}"
    try:
        result = await client.call_json(tool, args)
        status = "ok" if result is not None else "empty"
    except McpToolError as exc:
        result = {"__error__": str(exc)}
        status = "ERROR"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps({"args": args, "result": result}, indent=2, default=str)
    )
    print(f"{status:5} {name:40} {len(json.dumps(result, default=str)):>8} bytes")
    return result


async def main(days: int, probe_write: bool) -> None:
    settings = get_settings()
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    async with McpToolClient(garmin_spec(settings, enabled_tools=NUTRITION_TOOLS)) as g:
        print("tools:", await g.list_tool_names())
        await record(g, "get_user_profile", {})
        await record(g, "get_body_composition", {"start_date": start, "end_date": yesterday})
        await record(g, "get_daily_weigh_ins", {"date": yesterday})
        await record(g, "get_nutrition_daily_food_log", {"date": yesterday})
        await record(g, "get_nutrition_daily_meals", {"date": yesterday})
        await record(g, "get_nutrition_daily_settings", {"date": yesterday})
        await record(g, "get_hydration_data", {"date": yesterday})
        if not probe_write:
            return
        far = (today + timedelta(days=400)).isoformat()
        before = await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_before")
        await record(
            g,
            "set_nutrition_daily_settings",
            {"date": far, "calorie_goal": 2345, "carbs_grams": 300, "protein_grams": 150,
             "fat_grams": 61},
        )
        await record(g, "get_nutrition_daily_settings", {"date": far}, "_far_after")
        after_next = await record(
            g, "get_nutrition_daily_settings",
            {"date": (today + timedelta(days=401)).isoformat()}, "_far_next_day",
        )
        print("per-day override?", "yes" if after_next != before else "NO: default changed")
        if isinstance(before, dict):
            restore = {
                "date": far,
                "calorie_goal": before.get("calorie_goal") or before.get("calorieGoal"),
                "carbs_grams": before.get("carbs_grams") or before.get("carbsGoal"),
                "protein_grams": before.get("protein_grams") or before.get("proteinGoal"),
                "fat_grams": before.get("fat_grams") or before.get("fatGoal"),
            }
            await record(g, "set_nutrition_daily_settings", restore, "_restore")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--probe-write", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.days, a.probe_write))
```

- [ ] **Step 2: Run it (Brian, with Garmin auth), scrub, record findings**

```bash
uv run python scripts/spike_nutrition.py
uv run python scripts/spike_nutrition.py --probe-write   # only if the read-only run looked right
```

Open every file under `packages/tri-nutrition/tests/fixtures/mcp/`, remove names and emails, then append the findings to this plan's "Execution notes" section: the field names for weight, body fat, muscle mass and water; the food-log item shape; whether the write is per-day; the restore key names that worked. Plan 2's Garmin reader and apply node are written from these.

- [ ] **Step 3: Lint, commit (Brian)**

```bash
uv run ruff check . && uv run ruff format --check .
git add scripts/spike_nutrition.py packages/tri-nutrition/tests/fixtures
git commit -m "chore(nutrition): Garmin nutrition tool spike and scrubbed fixtures"
```

---

### Task 9: Package README, root README, docs sync

**Files:**
- Modify: `packages/tri-nutrition/README.md`, root `README.md` (package table row, Layout block, migrations line)

- [ ] **Step 1: Extend the package README**

Append to `packages/tri-nutrition/README.md`:
```markdown
## Layout so far

- `nutrition/models.py`: profile, product, session, day target, session fuel, race plan, change.
- `nutrition/constants.py`: every tunable number (formulas, macro table, deficit sizes, bounds).
- `nutrition/energy.py`: `rmr`, `session_kcal`, `day_type`. Pure.
- `nutrition/targets.py`: `build(profile, sessions, ctx, today, horizon_days)` -> one `DayTarget`
  per day. Pure.
- `nutrition/bounds.py`: `validate_targets`, `validate_fuel`, `validate_race` -> violations. Pure.
- `repo.py`: the three nutrition tables (`migrations/004_nutrition.sql`).

Try the targets builder without a database:

```bash
uv run python -c "
from datetime import date, timedelta
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session
from tri_nutrition.nutrition.targets import build
from tri_nutrition.nutrition.bounds import validate_targets
p = NutritionProfile(height_cm=180, weight_kg=80, body_fat_pct=15, sex='m', age=40, goal='lose',
    target_weight_kg=76, pattern='omnivore', meals_per_day=3, cooks=True, tracks_food=True,
    scale_days_per_week=3, unit_preference='metric')
today = date.today()
s = [Session(day=today+timedelta(days=1), sport='bike', duration_min=90, intensity='endurance', planned_tss=80),
     Session(day=today+timedelta(days=3), sport='run', duration_min=50, intensity='threshold'),
     Session(day=today+timedelta(days=5), sport='bike', duration_min=180, intensity='endurance', planned_tss=170)]
ts = build(p, s, PlanContext(source='plan', ftp_watts=250), today, 7)
for t in ts:
    print(t.day, f'{t.day_type:9}', t.session_kcal, t.total_kcal, f'{t.carbs_g}/{t.protein_g}/{t.fat_g}', t.notes)
print(validate_targets(ts, p) or 'within bounds')
"
```
```

- [ ] **Step 2: Root README**

Add to the package table (after the tri-planning row):
```
| `packages/tri-nutrition` | `tri_nutrition` | `tri-nutrition chat` | Nutrition agent: profile intake, periodized daily targets and fueling plans, approved writes to Garmin Connect and TrainingPeaks. |
```
In the Layout block change the migrations line to `migrations/             001_initial.sql (sync tables), 002_planning.sql, 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables)` and add `packages/tri-nutrition/  src/tri_nutrition/{config,cli,repo,nutrition}`.

- [ ] **Step 3: Copy docs to the vault and commit (Brian)**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/packages/tri-nutrition $V/docs/superpowers/specs $V/docs/superpowers/plans
cp packages/tri-nutrition/README.md $V/packages/tri-nutrition/readme.md
cp README.md $V/readme.md
cp docs/superpowers/specs/2026-09-10-tri-nutrition-design.md $V/docs/superpowers/specs/
cp docs/superpowers/plans/2026-09-10-tri-nutrition-01-math-and-schema.md $V/docs/superpowers/plans/
git add -A
git commit -m "docs(nutrition): package README, root README, plan 1"
```

---

## Self-review notes

- Spec §5.2: all three tables and both indexes (Task 1) under `004_`; the extra `goal_adjust_kcal` column is a listed deviation. Store and checkpoint tables arrive in Plan 2 with `scripts/setup_checkpointer.py`.
- Spec §6.3 models: all eight plus `ReviewDecision`, and the three input types (`Session`, `PlanContext`, `FuelLogEntry`) and two stored-row types the repo returns (Task 3).
- Spec §7.1: both RMR formulas, non-exercise expenditure, every sport branch including brick-as-legs and the fallback (Task 4). §7.2: every day-type rule has a test, including race and A-priority carb-load days and the B-priority case. §7.3: every macro row is a parametrized case; range position; fat floor raising total. §7.4: deficit sizing and the 500 cap, the day-type pause, the phase pause, the surplus on hard/long only. §7.5: both fluid branches. §7.6: each `validate_targets` bound, each `validate_fuel` rule (three carb tiers, gi_upset not counting as evidence, fluid, sodium both ends, caffeine both rules, unknown product), each `validate_race` rule (per-leg bounds via `totals_per_h`, pre-race window including a missing step, total caffeine, products).
- Spec §10: `NutritionSettings` with both knobs; `garmin_spec(enabled_tools=...)` with the default unchanged (Task 2).
- Spec §11 unit list: covered except "the Garmin calorie consistency fix", "`NutritionChange` to server-call translation" and "YAML edit round trip", which belong with the apply node and REPL in Plans 2 and 3.
- Spec §15: items 1 and 2 are Task 8; items 3 to 5 (TP note visibility, `tp_create_note` return payload, `get_store()` inside `create_agent` tools) are Plan 2 and Plan 3 work and are noted there.
- Type consistency: `targets.build(profile, sessions, ctx, today, horizon_days)`, `bounds.validate_targets(targets, profile)`, `bounds.validate_fuel(fuel, profile, library, fuel_log, other_caffeine_mg_today=0)`, `bounds.validate_race(plan, profile, library, fuel_log)` and the `repo` names above are the signatures Plan 2's `targets`, `fuel` and `apply` nodes call. `energy.week_monday` is the phase lookup key; Plan 2 builds `PlanContext.phases` from `plan_weeks.week_start`.

## Execution notes (2026-09-10, for Plan 2 to pick up)

- Executed inline on branch `feat/tri-nutrition-01`, one commit per task. Brian granted git commits for this session; the database rule still holds, so `004_nutrition.sql` is Brian's to apply and Task 7's five db tests skip until it lands on `tri_analyze_test`.
- **Task 1:** the CLI docstring exceeded 100 columns; shortened. Everything else as written.
- **Task 4:** `SPORT_KCAL_PER_KG_H` rows are written one key per line (ruff format).
- **Task 5:** all 35 tests passed first run; no test-data tweak was needed for the fat-floor case.
- **Task 6:** the tests use two small helpers (`vf`, `vr`, `step`) instead of the plan's inline calls to stay under the line limit. Same assertions.
- **Task 8, run 2026-09-10 (spec §15 items 1 and 2):**
  - `get_body_composition(start, end)` returns `{startDate, endDate, dateWeightList: [...], totalAverage: {...}}`. Each entry: `calendarDate` (YYYY-MM-DD), `weight` in **grams**, `bmi`, `bodyFat` (%), `bodyWater` (%), `boneMass` and `muscleMass` in **grams**, `sourceType` (`INDEX_SCALE`), `timestampGMT` (epoch ms). Plan 2's reader divides the mass fields by 1000.
  - `get_daily_weigh_ins(date)` returned the empty convention for a day without a weigh-in. Use `get_body_composition` with a range instead.
  - `get_nutrition_daily_settings(date)` returns `{weightChangeType, userDefinedActiveCalories, macroGoals: {...}, effectiveDate, nutritionStatus, ...}`. On this account `macroGoals` is `{}` (no goals set yet), so the key names inside it are still unverified; the apply node must handle an empty dict.
  - `get_nutrition_daily_food_log(date)` returns `{mealDate, mealDetails: [{meal: {mealId, mealName, startTime, endTime}, mealNutritionGoals, loggedFoods: [...]}], loggedFoodsWithServingSizes: [...]}`. The recorded day had no logged food, so the item shape (calories and macros per item) is still unverified; rerun with `--date` on a day with entries.
  - `get_nutrition_daily_meals(date)` returns `{meals: [{mealId, mealIndex, mealName, startTime, endTime, goals, enabled}], dailyTimelineStartTime, ...}`: meal definitions, not per-meal totals.
  - `get_hydration_data(date)` returns `{calendarDate, valueInML, goalInML, sweatLossInML, activityIntakeInML, ...}`.
  - `get_user_profile()` returns `{id, userData: {gender, weight (g), height (cm), birthDate, activityLevel, vo2MaxRunning, vo2MaxCycling, lactateThresholdHeartRate, availableTrainingDays, preferredLongTrainingDays, ...}, userSleep, userSleepWindows}`.
  - **Garmin rejects nutrition reads and writes more than 90 days out** (`API Error 400 - Provided date ... is after 90 days from current date`). The probe at +400 days errored on every call, so the "per-day override? yes" line printed by the first version was a false positive; the question is still open. The 14-day horizon is well inside the window. The spike now probes at +60 days and refuses to write when the day has no goals, because there is no tool to clear a day's goals afterwards.
  - Fixtures are scrubbed (user id and birth date replaced) and committed under `packages/tri-nutrition/tests/fixtures/mcp/`.
- **Smoke (README snippet, 80 kg, 15 % BF, lose, FTP 250):** rest days 2256 kcal (240/144/80) with a 440 kcal deficit; a 50-minute threshold run day comes out `hard` at 3632 kcal (604/160/64) and hits `fat_floor` because 7.5 g/kg carbs plus 2 g/kg protein leave under 0.8 g/kg fat at that session size. That is the spec's rule working, but expect the floor on most hard days for athletes around 80 kg with sub-1000 kcal sessions; the total rises above maintenance by roughly 100 kcal on those days.
- **For Plan 2:** `PlanContext.phases` is keyed by week Monday (`energy.week_monday`); build it from `plan_weeks.week_start`. `Session` for a `workouts` row: `duration_min = planned_duration_sec // 60`, `distance_km = planned_distance_m / 1000`, intensity from `planned_if` (below 0.75 endurance, below 0.85 tempo, below 0.95 threshold, else vo2) until the workout carries a structured intensity.
