# tri-wellness Plan 1 of 3: Ranges and Evaluate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `tri-wellness` package with the lab tables migration, the lab domain models, the curated `markers.yaml` range table and the registry that validates it, the pure `normalize` step (raw lab rows to canonical results), the pure `evaluate` step (results plus contexts to `Finding`s), the training-context reader over `workouts` and `daily_metrics`, and the repository over the new tables. Nothing here calls a model. This is spec milestone 1.

**Architecture:** `tri_wellness.labs` is a pure layer: Pydantic models and two modules of functions (`normalize`, `evaluate`) with no I/O. `tri_wellness.ranges` owns the YAML and the `MarkerRegistry` that loads, validates and resolves it (sex-specific ranges, alias index). `tri_wellness.labs.training_context` and `tri_wellness.repo` are the only SQL and follow the tri-core convention: every function takes an open connection, callers commit. Plan 2 (ingest graph) composes normalize and the repo; Plan 3 (report, chat) composes evaluate and the training context.

**Tech Stack:** pydantic 2, PyYAML, psycopg 3 with `Jsonb`, pytest. Depends on the workspace as it stands after tri-nutrition Plan 4 (`tri_core.testing.fixtures.db`, `tri_core.db.repo.Conn`, `tri_core.db.repo.upsert_workouts`, `upsert_daily_metrics`).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-wellness-design.md` (§1 decisions, §4 layout, §5 data model, §6 models, §7 ranges table, §8 evaluate, §14 configuration, §15 testing, §17 milestone 1, §19 open items).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root `/Users/brian/Development/paradigm/fitness_agents/triathlon_agent` as `uv run ...`.
- New package: distribution `tri-wellness`, module `tri_wellness`, console script `tri-wellness`. It depends on `tri-core` only and never imports `tri_analyze`, `tri_planning` or `tri_nutrition` (spec §4).
- Pins carried from the workspace: `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langgraph-checkpoint-postgres>=3.1,<4`, `langsmith>=0.12,<1`, `psycopg[binary]==3.3.5`, `pyyaml>=6`, `pydantic-settings>=2.6`, `typer>=0.15`, `rich>=13`. No `langchain-mcp-adapters` (spec §3: no live MCP tools). Declared now so the lock settles once, even though Plan 2 is the first to import LangGraph.
- Settings (spec §14): `TRI_ATHLETE_SEX` (`male` | `female`, required), `TRI_WELLNESS_LANGSMITH_PROJECT` default `tri_wellness`. The env-var prefix `TRI_WELLNESS_` for the project name follows planning and nutrition; the spec's bare `LANGSMITH_PROJECT` is tri-core's and stays `tri_analyze`.
- Every threshold from spec §8 lives at the top of `labs/evaluate.py` and nowhere else: `HARD_SESSION_TSS = 150`, `HARD_SESSION_MIN = 120`, `HARD_SESSION_WINDOW_DAYS = 3` (the 72 h), `ACUTE_LOAD_ATL_OVER_CTL = 15`, `POOR_SLEEP_DEFICIT_SEC = 3600` (60 min), `LOW_HRV_FRACTION = 0.10`, `AFTERNOON_DRAW_AFTER = time(10, 0)`. The training-context windows (`3` days of sessions, `2` nights, `30` days) live in `labs/training_context.py`.
- Status rules exactly as spec §6: `conventional_status` uses the lab's printed range when present, else the table's conventional range; `functional_status` uses only the table; `direction: low` or `high` collapses the irrelevant side to `optimal`.
- Alias matching exactly as spec §7: lowercase, strip punctuation and parenthesized qualifiers, collapse whitespace, exact match. No fuzzy matching.
- **Brian runs every migration with `psql`, to both `tri_analyze` and `tri_analyze_test`.** Tests write only through the rolled-back `db` fixture. Git commits are permitted in this repo (Brian's standing permission); commit per task on the feature branch.
- **Execute in a sibling worktree** (`git worktree add ../triathlon_agent-wellness-01 -b feat/tri-wellness-01 main`, copy `.env`, `uv sync` there). Other Claude sessions share the main checkout.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Run `uv run ruff format packages/tri-wellness` first: test code in this plan is written for readability; the formatter wraps long lines, and any `E501` it cannot fix is wrapped by hand.
- No "LangChain lesson:" framing in docstrings (Brian's standing feedback).
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case file name.

### Spec deviations decided in this plan

- **Migration is `migrations/005_wellness.sql`, not `004_wellness.sql`.** `004_nutrition.sql` landed after the spec was written (spec §2 said 004 was next). The spec's DDL is copied verbatim under the new number, with `if not exists` guards and named indexes to match the other migrations.
- **`MarkerSpec` is the resolved form; the YAML file is the unresolved form.** Spec §7 shows `conventional: {low, high}` or `conventional: {male: {...}, female: {...}}`. `registry.py` parses the raw file into `RawMarkerEntry` (either shape) and resolves it into `MarkerSpec` with plain `conventional: Range` and `functional: Range` for the configured sex. Everything downstream (normalize, evaluate, tools) sees only `MarkerSpec`. The `functional` block may be sex-specific the same way.
- **`Range` allows an open side.** `conventional: {low: 30, high: 400}` is the common case, but a `direction: high` marker such as hs-CRP has no meaningful low, so `Range(low=None, high=1.0)` is legal. The registry validation rule "functional range lies within the conventional range" is checked per side that is present on both. `Finding.functional_range` is `tuple[float | None, float | None]` exactly as the spec writes it.
- **`normalize` returns a `NormalizeResult` of `results` (storable `LabResult`s) and `unmapped` (`Unmapped(raw, reason, marker)`)**, where `reason` is `name` (not in the alias index), `unit` (mapped marker, unit missing or not in `conversions` and not the canonical unit), `value` (not numeric after stripping a bound prefix and thousands separators), or `duplicate` (a second row for a marker already taken in this panel; the first row wins). Spec §9.2 says an unknown unit "keeps the row with `note = 'unit?'` and it cannot be stored until edited". A `LabResult` needs a float value in a canonical unit, so such rows cannot be `LabResult`s yet; they stay raw with a reason, and the review node (Plan 2) refuses approve while any `unit` or `value` row remains. `name` and `duplicate` rows are allowed through and live only in `raw_extract`.
- **A missing unit counts as unknown**, not as canonical. Labs print units on every numeric row; an export that omits them is edited at review rather than guessed.
- **Bounded values**: `<5` becomes `5.0` with `note = "value '<5' stored as bound 5"`; `>200` likewise. Prefixes `<`, `>`, `<=`, `>=`, `≤`, `≥` are recognised. Unit matching ignores case and internal spaces (`ng/ml` matches `ng/mL`). Converted values are rounded to four decimals and carry `note = "converted from 5.2 mmol/L"`.
- **Lab reference values are parsed with the same value parser**; an unparsable `ref_low`/`ref_high` becomes `None` rather than failing the row.
- **The 72-hour session window is `workout_date` in `[drawn_on - 3 days, drawn_on - 1 day]`, completed sessions only.** `workouts.start_time_local` is null for sessions without a Garmin match, so the window is by calendar day. Sessions on the draw day itself are excluded (draws are morning events; a same-day session after the draw would be a false confounder). `last_sessions` holds up to three sessions from that window **hardest first** (qualifying hard sessions first, then actual TSS descending, then duration descending, then date), so the `recent_hard_session` rule can be evaluated from the list alone. Each entry is `{date, sport, duration_min, tss, title}` with `date` an ISO string.
- **Sleep and HRV nights**: the night before a draw on `D` is Garmin's `metric_date = D` (Garmin keys a night by its wake date, per `parse_sleep_range`). So the two nights before the draw are `metric_date in {D - 1, D}`, and the 30-day baseline is `metric_date in [D - 30, D - 1]`. Nights with a null value are skipped; a mean over zero nights is `None`, and a confounder whose inputs are `None` does not fire.
- **`ctl`, `atl`, `tsb` come from the `daily_metrics` row for `drawn_on`**; when that row is missing or null, the most recent row in the previous 7 days is used, else `None`. `tss_7d` is `sum(tss_day)` over `[D - 7, D - 1]`, `None` when no row has a value.
- **`previous` per marker is the most recent earlier panel that has it**, earlier meaning `(drawn_on, id)` strictly less than this panel's. `evaluate` is pure and receives `previous: dict[str, tuple[date, float]]`; `repo.previous_values(conn, panel_id)` builds it (Plan 3 calls both).
- **`Finding.previous` is `tuple[date, float] | None` as the spec writes it**; `delta_pct` is `(value - prev) / prev * 100`, rounded to one decimal, and `None` when `prev == 0`.
- **`inflammation` fires from hs-CRP in the same panel above its functional high**, resolved from the registry by canonical key `hs_crp`. If the panel has no hs-CRP the confounder cannot fire.
- **`athlete_note` on a `Finding` is the spec's prose verbatim** (`""` when the YAML omits it). `MarkerSpec.sources` is not copied onto the finding; the report prompt (Plan 3) reads it from the registry.
- **`markers.yaml` is drafted in this plan with the spec's initial set (§7)**; Brian's review closes the milestone (spec §17). Every entry carries `sources`. Where sources disagree the entry uses one and names the alternative in `athlete_note`. The version string is `2026-09-11.1`.
- **`repo.py` and its DB tests are in this plan** (spec milestone 1 lists only pure code). The repository is SQL over the new tables and calls no model; nutrition's Plan 1 set the precedent.
- **`get_marker_history` data access lives in `repo.marker_history`** now (the tool wrapper is Plan 3), so its ordering is tested against the seeded tables here.
- **`cli.py` is a typer app with a callback only.** `ingest`, `report`, `chat` and `panels` arrive in Plans 2 and 3.

---

## File Structure

```
packages/tri-wellness/
  pyproject.toml
  README.md
  src/tri_wellness/
    __init__.py
    config.py                 WellnessSettings(Settings): athlete sex, LangSmith project
    cli.py                    typer app with a callback only
    repo.py                   lab_panels, lab_results, lab_reports reads and writes; previous values;
                              marker history
    ranges/
      __init__.py
      markers.yaml            the curated range table (spec §7)
      registry.py             Range, RawMarkerEntry, MarkerSpec, MarkerRegistry, load_registry(),
                              normalize_alias(), RegistryError
    testing.py                seed_workouts(), seed_daily_metrics() for db tests
    labs/
      __init__.py
      models.py               RawResult, LabResult, PanelContext, TrainingContext, Finding,
                              Unmapped, NormalizeResult, StoredPanel, StoredResult, StoredReport,
                              PanelSummary, ConventionalStatus, FunctionalStatus, Confounder
      normalize.py            parse_value(), normalize()
      evaluate.py             thresholds; active_confounders(); status functions; evaluate()
      training_context.py     load_training_context(conn, drawn_on)
  tests/
    fixtures/
      ranges/
        bad_missing_field.yaml, bad_functional_outside.yaml, bad_duplicate_alias.yaml,
        bad_conversion_target.yaml, good_sexed.yaml
    test_config.py
    test_registry.py
    test_markers_yaml.py      the real file round-trips
    test_models.py
    test_normalize.py
    test_evaluate.py
    test_training_context.py  db-marked
    test_repo.py              db-marked
migrations/005_wellness.sql
```

Responsibilities: `models.py` is the vocabulary every other module shares. `registry.py` is the only reader of `markers.yaml` and the only place sex resolution happens. `normalize.py` turns what a lab printed into canonical numbers and never judges them. `evaluate.py` judges and never does I/O. `training_context.py` and `repo.py` are the only SQL.

---

### Task 1: Package scaffold, settings, migration

**Files:**
- Create: `packages/tri-wellness/pyproject.toml`, `packages/tri-wellness/README.md`, `packages/tri-wellness/src/tri_wellness/__init__.py`, `packages/tri-wellness/src/tri_wellness/ranges/__init__.py`, `packages/tri-wellness/src/tri_wellness/labs/__init__.py`, `packages/tri-wellness/src/tri_wellness/config.py`, `packages/tri-wellness/src/tri_wellness/cli.py`, `migrations/005_wellness.sql`
- Modify: root `pyproject.toml` (member dependency, source, isort first-party, mypy files), `.env.example`
- Test: `packages/tri-wellness/tests/test_config.py`

**Interfaces:**
- Consumes: `tri_core.config.Settings`.
- Produces: `tri_wellness.config.Sex = Literal["male", "female"]`; `WellnessSettings` with `tri_athlete_sex: Sex` (required) and `tri_wellness_langsmith_project: str = "tri_wellness"`; `get_wellness_settings() -> WellnessSettings`; `tri_wellness.cli.app`; the three tables.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from tri_wellness.config import WellnessSettings


def test_defaults(monkeypatch):
    monkeypatch.setenv("TRI_ATHLETE_SEX", "male")
    monkeypatch.delenv("TRI_WELLNESS_LANGSMITH_PROJECT", raising=False)
    s = WellnessSettings(_env_file=None)
    assert s.tri_athlete_sex == "male"
    assert s.tri_wellness_langsmith_project == "tri_wellness"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_sex_is_required_and_validated(monkeypatch):
    monkeypatch.delenv("TRI_ATHLETE_SEX", raising=False)
    with pytest.raises(ValidationError):
        WellnessSettings(_env_file=None)
    monkeypatch.setenv("TRI_ATHLETE_SEX", "other")
    with pytest.raises(ValidationError):
        WellnessSettings(_env_file=None)


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_ATHLETE_SEX", "female")
    monkeypatch.setenv("TRI_WELLNESS_LANGSMITH_PROJECT", "labs")
    s = WellnessSettings(_env_file=None)
    assert s.tri_athlete_sex == "female"
    assert s.tri_wellness_langsmith_project == "labs"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness -q`
Expected: uv refuses to sync (`Workspace member ... is missing a pyproject.toml`) or, once the directory exists, `ModuleNotFoundError: No module named 'tri_wellness'`. Either is the expected failure.

- [ ] **Step 3: Create the package**

`packages/tri-wellness/pyproject.toml`:
```toml
[project]
name = "tri-wellness"
version = "0.1.0"
description = "Functional-medicine lab interpreter: ingests lab panels, evaluates markers against curated ranges, writes interpretations grounded in training data"
authors = [{ name = "Brian Flannery", email = "brian@paradigmshiftdev.io" }]
requires-python = ">=3.12,<3.13"
dependencies = [
    "tri-core",
    "langchain==1.4.0",
    "langchain-anthropic==1.7.1",
    "langgraph-checkpoint-postgres>=3.1,<4",
    "langsmith>=0.12,<1",
    "psycopg[binary]==3.3.5",
    "pydantic-settings>=2.6",
    "pyyaml>=6",
    "typer>=0.15",
    "rich>=13",
]

[project.scripts]
tri-wellness = "tri_wellness.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tri_wellness"]

[tool.uv.sources]
tri-core = { workspace = true }
```

`packages/tri-wellness/src/tri_wellness/__init__.py`, `ranges/__init__.py`, `labs/__init__.py`: empty files.

`packages/tri-wellness/src/tri_wellness/config.py`:
```python
"""Wellness-agent settings: everything in tri_core.config plus the athlete's sex for
sex-specific ranges and the LangSmith project."""

from functools import lru_cache
from typing import Literal

from tri_core.config import Settings

Sex = Literal["male", "female"]


class WellnessSettings(Settings):
    tri_athlete_sex: Sex
    tri_wellness_langsmith_project: str = "tri_wellness"


@lru_cache(maxsize=1)
def get_wellness_settings() -> WellnessSettings:
    return WellnessSettings()
```

`packages/tri-wellness/src/tri_wellness/cli.py`:
```python
"""Command-line entry points for the wellness agent (ingest, report, chat, panels arrive in
later plans)."""

from __future__ import annotations

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(help="Functional-medicine lab interpreter", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Functional-medicine lab interpreter."""


if __name__ == "__main__":
    app()
```

`packages/tri-wellness/README.md`:
```markdown
# tri-wellness

The lab interpreter: ingests the athlete's lab work from PDFs and structured exports, evaluates
every marker against the curated functional-medicine ranges in `src/tri_wellness/ranges/markers.yaml`,
and writes an interpretation grounded in the training, sleep and recovery data tri-core syncs to
Postgres. Design: `docs/superpowers/specs/2026-09-10-tri-wellness-design.md`.
Plans: `docs/superpowers/plans/2026-09-11-tri-wellness-0*.md`.
```

Root `pyproject.toml` edits:
- `dependencies = ["tri-core", "tri-analyze", "tri-planning", "tri-nutrition", "tri-wellness"]`
- under `[tool.uv.sources]` add `tri-wellness = { workspace = true }`
- `known-first-party = ["tri_core", "tri_analyze", "tri_planning", "tri_nutrition", "tri_wellness"]`
- mypy `files = ["packages/tri-core/src", "packages/tri-analyze/src", "packages/tri-planning/src", "packages/tri-nutrition/src", "packages/tri-wellness/src"]`

`.env.example`: append
```
# tri-wellness
TRI_ATHLETE_SEX=male
TRI_WELLNESS_LANGSMITH_PROJECT=tri_wellness
```
Also add `TRI_ATHLETE_SEX=male` to the local `.env` (not committed) so the registry resolves.

- [ ] **Step 4: Write the migration**

`migrations/005_wellness.sql`:
```sql
-- 005_wellness.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists lab_panels (
  id            serial primary key,
  drawn_on      date not null,
  lab_name      text,                  -- Quest, LabCorp, Function Health, ...
  source_file   text,                  -- path as given at ingest
  source_kind   text not null,         -- pdf | export | manual
  context       jsonb not null,        -- PanelContext
  raw_extract   jsonb not null,        -- list[RawResult] exactly as extraction returned them
  created_at    timestamptz not null default now()
);
create index if not exists lab_panels_drawn_on_idx on lab_panels (drawn_on);

create table if not exists lab_results (
  panel_id      int not null references lab_panels,
  marker        text not null,         -- canonical key from markers.yaml
  value         numeric not null,      -- canonical unit
  unit          text not null,
  raw_name      text not null,         -- what the lab printed
  raw_value     text not null,         -- verbatim, including "<5"
  raw_unit      text,
  lab_ref_low   numeric,
  lab_ref_high  numeric,
  flag          text,                  -- lab's own H / L, if printed
  primary key (panel_id, marker)
);
create index if not exists lab_results_marker_idx on lab_results (marker);

create table if not exists lab_reports (
  id             serial primary key,
  panel_id       int not null references lab_panels,
  ranges_version text not null,        -- markers.yaml version used
  findings       jsonb not null,       -- list[Finding], what the report was written from
  report_md      text not null,
  created_at     timestamptz not null default now()
);
```

- [ ] **Step 5: Sync, run the test, apply the migration (Brian)**

```bash
uv sync
uv run pytest packages/tri-wellness -q
uv run tri-wellness --help
```
Expected: 3 passed; `--help` prints the app description with no commands.

Brian applies the migration:
```bash
docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/005_wellness.sql
docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/005_wellness.sql
```

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "feat(wellness): package scaffold, settings, 005_wellness migration"
```

---

### Task 2: Domain models

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/labs/models.py`
- Test: `packages/tri-wellness/tests/test_models.py`

**Interfaces:**
- Produces: every type below. Later tasks import them from `tri_wellness.labs.models`.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_models.py`:
```python
from datetime import date, time

import pytest
from pydantic import ValidationError

from tri_wellness.labs.models import (
    Finding,
    LabResult,
    PanelContext,
    RawResult,
    TrainingContext,
)


def raw(**over):
    base = dict(name="Ferritin, Serum", value="42", unit="ng/mL", ref_low="30", ref_high="400")
    base.update(over)
    return RawResult(**base)


def test_raw_result_defaults():
    r = raw()
    assert r.flag is None and r.page is None
    assert r.model_dump() == {
        "name": "Ferritin, Serum",
        "value": "42",
        "unit": "ng/mL",
        "ref_low": "30",
        "ref_high": "400",
        "flag": None,
        "page": None,
    }


def test_lab_result_keeps_raw():
    lr = LabResult(marker="ferritin", value=42.0, unit="ng/mL", raw=raw(), lab_ref_low=30, lab_ref_high=400)
    assert lr.note is None
    assert lr.raw.name == "Ferritin, Serum"
    assert LabResult.model_validate_json(lr.model_dump_json()) == lr


def test_panel_context_defaults_and_time():
    c = PanelContext()
    assert c.fasting is None and c.supplements == [] and c.symptoms == []
    c2 = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["iron"], symptoms=["fatigue"])
    again = PanelContext.model_validate(c2.model_dump(mode="json"))
    assert again == c2
    assert again.draw_time == time(7, 30)


def test_training_context_defaults():
    t = TrainingContext(drawn_on=date(2026, 9, 1))
    assert t.ctl is None and t.last_sessions == [] and t.hrv_30d_avg is None


def test_finding_statuses_are_validated():
    kw = dict(
        marker="ferritin",
        display="Ferritin",
        system="iron",
        value=42.0,
        unit="ng/mL",
        conventional_status="in_range",
        functional_status="suboptimal_low",
        functional_range=(50.0, 150.0),
        previous=(date(2026, 3, 1), 38.0),
        delta_pct=10.5,
        active_confounders=["recent_hard_session"],
        athlete_note="note",
    )
    f = Finding(**kw)
    assert f.functional_range == (50.0, 150.0)
    assert Finding.model_validate(f.model_dump(mode="json")) == f
    with pytest.raises(ValidationError):
        Finding(**{**kw, "functional_status": "meh"})
    with pytest.raises(ValidationError):
        Finding(**{**kw, "active_confounders": ["jetlag"]})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_models.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.labs.models'`.

- [ ] **Step 3: Write the models**

`packages/tri-wellness/src/tri_wellness/labs/models.py`:
```python
"""Lab vocabulary shared by the registry, normalize, evaluate, repository, graph and tools."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field

ConventionalStatus = Literal["low", "in_range", "high"]
FunctionalStatus = Literal["low", "suboptimal_low", "optimal", "suboptimal_high", "high"]
Confounder = Literal[
    "recent_hard_session",
    "high_acute_load",
    "poor_sleep",
    "low_hrv",
    "not_fasting",
    "afternoon_draw",
    "inflammation",
]
SourceKind = Literal["pdf", "export", "manual"]


class RawResult(BaseModel):
    """One row as extraction returned it. Verbatim strings; no interpretation."""

    name: str
    value: str
    unit: str | None = None
    ref_low: str | None = None
    ref_high: str | None = None
    flag: str | None = None
    page: int | None = None


class LabResult(BaseModel):
    """A RawResult mapped to a canonical marker and unit."""

    marker: str
    value: float
    unit: str
    raw: RawResult
    lab_ref_low: float | None = None
    lab_ref_high: float | None = None
    note: str | None = None


class PanelContext(BaseModel):
    """What the athlete tells us about the draw. Collected at review."""

    fasting: bool | None = None
    draw_time: time | None = None
    supplements: list[str] = Field(default_factory=list)
    diet_pattern: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    notes: str | None = None


class TrainingContext(BaseModel):
    """Load, sleep and HRV around the draw date, read from workouts and daily_metrics."""

    drawn_on: date
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    tss_7d: float | None = None
    last_sessions: list[dict[str, Any]] = Field(default_factory=list)
    sleep_2n_avg_sec: int | None = None
    sleep_30d_avg_sec: int | None = None
    hrv_2n_avg: int | None = None
    hrv_30d_avg: int | None = None


class Finding(BaseModel):
    """evaluate's output: one per LabResult, everything the report needs about a marker."""

    marker: str
    display: str
    system: str
    value: float
    unit: str
    conventional_status: ConventionalStatus
    functional_status: FunctionalStatus
    functional_range: tuple[float | None, float | None]
    previous: tuple[date, float] | None = None
    delta_pct: float | None = None
    active_confounders: list[Confounder] = Field(default_factory=list)
    athlete_note: str = ""


UnmappedReason = Literal["name", "unit", "value", "duplicate"]


class Unmapped(BaseModel):
    """A raw row normalize could not turn into a LabResult, and why."""

    raw: RawResult
    reason: UnmappedReason
    marker: str | None = None  # set when the name mapped but the unit or value did not


class NormalizeResult(BaseModel):
    """normalize's output. `results` are storable; `unmapped` rows need review."""

    results: list[LabResult] = Field(default_factory=list)
    unmapped: list[Unmapped] = Field(default_factory=list)


class StoredPanel(BaseModel):
    id: int
    drawn_on: date
    lab_name: str | None
    source_file: str | None
    source_kind: SourceKind
    context: PanelContext
    raw_extract: list[RawResult]
    created_at: datetime


class StoredResult(BaseModel):
    panel_id: int
    marker: str
    value: float
    unit: str
    raw_name: str
    raw_value: str
    raw_unit: str | None
    lab_ref_low: float | None
    lab_ref_high: float | None
    flag: str | None


class StoredReport(BaseModel):
    id: int
    panel_id: int
    ranges_version: str
    findings: list[Finding]
    report_md: str
    created_at: datetime


class PanelSummary(BaseModel):
    """One line of `tri-wellness panels`."""

    id: int
    drawn_on: date
    lab_name: str | None
    result_count: int
    unmapped_count: int
    has_report: bool
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_models.py -q`
Expected: 5 passed.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): lab domain models"
```

---

### Task 3: Registry (`ranges/registry.py`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/ranges/registry.py`, `packages/tri-wellness/tests/fixtures/ranges/good_sexed.yaml`, `bad_missing_field.yaml`, `bad_functional_outside.yaml`, `bad_duplicate_alias.yaml`, `bad_conversion_target.yaml`
- Test: `packages/tri-wellness/tests/test_registry.py`

**Interfaces:**
- Consumes: `tri_wellness.config.Sex`, `tri_wellness.labs.models.Confounder`.
- Produces: `Range(low: float | None, high: float | None)`; `MarkerSpec(key, display, system, unit, aliases, conversions, conventional: Range, functional: Range, direction, athlete_note, confounders, sources)`; `MarkerRegistry` with `.version: str`, `.sex: Sex`, `.markers: dict[str, MarkerSpec]`, `.get(key) -> MarkerSpec` (raises `KeyError`), `.lookup(raw_name) -> MarkerSpec | None`, `__len__`, `__iter__` over keys; `normalize_alias(name: str) -> str`; `load_registry(sex: Sex, path: Path = MARKERS_PATH) -> MarkerRegistry`; `RegistryError(ValueError)`; `SYSTEMS: frozenset[str]`; `MARKERS_PATH: Path`.

- [ ] **Step 1: Write the fixture files**

`packages/tri-wellness/tests/fixtures/ranges/good_sexed.yaml`:
```yaml
version: test.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin, "ferritin, serum"]
    conversions: {"µg/L": 1.0, "ug/L": 1.0}
    conventional: {male: {low: 30, high: 400}, female: {low: 15, high: 150}}
    functional: {male: {low: 50, high: 150}, female: {low: 50, high: 120}}
    direction: both
    athlete_note: Below 50 impairs adaptation.
    confounders: [recent_hard_session, inflammation]
    sources: ["Weatherby & Ferguson"]
  hs_crp:
    display: hs-CRP
    system: inflammation
    unit: mg/L
    aliases: [hs-crp, "c-reactive protein, high sensitivity", crp hs]
    conventional: {high: 3.0}
    functional: {high: 1.0}
    direction: high
    sources: ["IFM functional ranges"]
```

`bad_missing_field.yaml` (no `unit`):
```yaml
version: test.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    aliases: [ferritin]
    conventional: {low: 30, high: 400}
    functional: {low: 50, high: 150}
    direction: both
    sources: ["x"]
```

`bad_functional_outside.yaml` (functional high above conventional high):
```yaml
version: test.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin]
    conventional: {low: 30, high: 400}
    functional: {low: 50, high: 450}
    direction: both
    sources: ["x"]
```

`bad_duplicate_alias.yaml` (same alias after normalization on two markers):
```yaml
version: test.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin, "Iron (serum)"]
    conventional: {low: 30, high: 400}
    functional: {low: 50, high: 150}
    direction: both
    sources: ["x"]
  iron_serum:
    display: Iron
    system: iron
    unit: ug/dL
    aliases: [iron, "iron, serum"]
    conventional: {low: 38, high: 169}
    functional: {low: 85, high: 130}
    direction: both
    sources: ["x"]
```

`bad_conversion_target.yaml` (the canonical unit listed with a factor other than 1, and a non-positive factor):
```yaml
version: test.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin]
    conversions: {"ng/mL": 2.0, "ug/L": 0}
    conventional: {low: 30, high: 400}
    functional: {low: 50, high: 150}
    direction: both
    sources: ["x"]
```

- [ ] **Step 2: Write the failing test**

`packages/tri-wellness/tests/test_registry.py`:
```python
from pathlib import Path

import pytest

from tri_wellness.ranges.registry import (
    Range,
    RegistryError,
    load_registry,
    normalize_alias,
)

FIX = Path(__file__).parent / "fixtures" / "ranges"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Ferritin", "ferritin"),
        ("Ferritin, Serum", "ferritin serum"),
        ("  Vitamin D (25-Hydroxy)  ", "vitamin d"),
        ("hs-CRP", "hs crp"),
        ("Testosterone,Free (Direct)", "testosterone free"),
        ("HDL   Cholesterol", "hdl cholesterol"),
        ("Hemoglobin A1c", "hemoglobin a1c"),
    ],
)
def test_normalize_alias(raw, expected):
    assert normalize_alias(raw) == expected


def test_load_resolves_sex_and_indexes_aliases():
    reg = load_registry("female", FIX / "good_sexed.yaml")
    assert reg.version == "test.1"
    assert reg.sex == "female"
    assert len(reg) == 2 and set(reg) == {"ferritin", "hs_crp"}
    f = reg.get("ferritin")
    assert f.key == "ferritin"
    assert f.conventional == Range(low=15, high=150)
    assert f.functional == Range(low=50, high=120)
    assert f.conversions == {"µg/L": 1.0, "ug/L": 1.0}
    assert f.confounders == ["recent_hard_session", "inflammation"]
    assert load_registry("male", FIX / "good_sexed.yaml").get("ferritin").conventional == Range(
        low=30, high=400
    )


def test_unsexed_marker_and_open_range():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    c = reg.get("hs_crp")
    assert c.conventional == Range(low=None, high=3.0)
    assert c.functional == Range(low=None, high=1.0)
    assert c.direction == "high"
    assert c.athlete_note == ""
    assert c.confounders == []


def test_lookup_uses_normalized_aliases():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    assert reg.lookup("FERRITIN, Serum").key == "ferritin"
    assert reg.lookup("C-Reactive Protein, High Sensitivity").key == "hs_crp"
    assert reg.lookup("CRP (hs)") is None  # 'crp' alone is not an alias
    assert reg.lookup("Ferritin (serum)").key == "ferritin"  # qualifier stripped
    assert reg.lookup("Vitamin D") is None


def test_get_unknown_raises_keyerror():
    reg = load_registry("male", FIX / "good_sexed.yaml")
    with pytest.raises(KeyError):
        reg.get("nope")


@pytest.mark.parametrize(
    "file, marker, field",
    [
        ("bad_missing_field.yaml", "ferritin", "unit"),
        ("bad_functional_outside.yaml", "ferritin", "functional"),
        ("bad_duplicate_alias.yaml", "iron_serum", "aliases"),
        ("bad_conversion_target.yaml", "ferritin", "conversions"),
    ],
)
def test_validation_names_marker_and_field(file, marker, field):
    with pytest.raises(RegistryError) as exc:
        load_registry("male", FIX / file)
    msg = str(exc.value)
    assert marker in msg and field in msg


def test_missing_sex_block_is_an_error(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "version: t\nmarkers:\n  x:\n    display: X\n    system: iron\n    unit: u\n"
        "    aliases: [x]\n    conventional: {male: {low: 1, high: 2}}\n"
        "    functional: {low: 1, high: 2}\n    direction: both\n    sources: [s]\n"
    )
    with pytest.raises(RegistryError, match="x.*conventional.*female"):
        load_registry("female", p)


def test_unknown_system_is_an_error(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(
        "version: t\nmarkers:\n  x:\n    display: X\n    system: bones\n    unit: u\n"
        "    aliases: [x]\n    conventional: {low: 1, high: 2}\n"
        "    functional: {low: 1, high: 2}\n    direction: both\n    sources: [s]\n"
    )
    with pytest.raises(RegistryError, match="x.*system"):
        load_registry("male", p)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_registry.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.ranges.registry'`.

- [ ] **Step 4: Write the registry**

`packages/tri-wellness/src/tri_wellness/ranges/registry.py`:
```python
"""Loads and validates markers.yaml into MarkerSpec models and an alias index.

The YAML is the unresolved form: a range block is either `{low, high}` or
`{male: {low, high}, female: {low, high}}`. The registry resolves it for one sex at load time, so
nothing downstream knows about sex-specific ranges. Validation fails on import naming the marker
and the field, so a typo in the table fails the test suite.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from tri_wellness.config import Sex
from tri_wellness.labs.models import Confounder

MARKERS_PATH = Path(__file__).with_name("markers.yaml")

SYSTEMS: frozenset[str] = frozenset(
    {
        "iron",
        "thyroid",
        "metabolic",
        "lipids",
        "inflammation",
        "liver",
        "kidney",
        "cbc",
        "hormones",
        "vitamins_minerals",
        "electrolytes",
    }
)

Direction = Literal["low", "high", "both"]


class RegistryError(ValueError):
    """markers.yaml is invalid. The message names the marker and the field."""


class Range(BaseModel):
    low: float | None = None
    high: float | None = None


class RawMarkerEntry(BaseModel):
    """One YAML entry before sex resolution. Range blocks are validated in `_resolve_range`."""

    display: str
    system: str
    unit: str
    aliases: list[str] = Field(min_length=1)
    conversions: dict[str, float] = Field(default_factory=dict)
    conventional: dict[str, Any]
    functional: dict[str, Any]
    direction: Direction
    athlete_note: str = ""
    confounders: list[Confounder] = Field(default_factory=list)
    sources: list[str] = Field(min_length=1)


class MarkerSpec(BaseModel):
    """One marker, resolved for the athlete's sex. What normalize, evaluate and the tools see."""

    key: str
    display: str
    system: str
    unit: str
    aliases: list[str]
    conversions: dict[str, float]
    conventional: Range
    functional: Range
    direction: Direction
    athlete_note: str
    confounders: list[Confounder]
    sources: list[str]


_PAREN = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize_alias(name: str) -> str:
    """Lowercase, drop parenthesized qualifiers, turn punctuation into spaces, collapse spaces."""
    s = _PAREN.sub(" ", name.lower())
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def _resolve_range(block: dict[str, Any], sex: Sex, marker: str, field: str) -> Range:
    keys = set(block)
    if keys <= {"low", "high"}:
        chosen = block
    elif "male" in keys or "female" in keys:
        if sex not in block:
            raise RegistryError(f"{marker}.{field}: no '{sex}' block")
        chosen = block[sex]
        if not isinstance(chosen, dict) or not set(chosen) <= {"low", "high"}:
            raise RegistryError(f"{marker}.{field}.{sex}: expected {{low, high}}")
    else:
        raise RegistryError(f"{marker}.{field}: expected {{low, high}} or {{male, female}}")
    try:
        r = Range.model_validate(chosen)
    except ValidationError as exc:
        raise RegistryError(f"{marker}.{field}: {exc.errors()[0]['msg']}") from exc
    if r.low is None and r.high is None:
        raise RegistryError(f"{marker}.{field}: needs at least one of low, high")
    if r.low is not None and r.high is not None and r.low >= r.high:
        raise RegistryError(f"{marker}.{field}: low must be below high")
    return r


def _resolve(key: str, raw: dict[str, Any], sex: Sex) -> MarkerSpec:
    try:
        entry = RawMarkerEntry.model_validate(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join(str(p) for p in e["loc"]) or "entry"
        raise RegistryError(f"{key}.{loc}: {e['msg']}") from exc
    if entry.system not in SYSTEMS:
        raise RegistryError(f"{key}.system: '{entry.system}' is not one of {sorted(SYSTEMS)}")
    conventional = _resolve_range(entry.conventional, sex, key, "conventional")
    functional = _resolve_range(entry.functional, sex, key, "functional")
    if (
        conventional.low is not None
        and functional.low is not None
        and functional.low < conventional.low
    ):
        raise RegistryError(f"{key}.functional: low {functional.low} below conventional low")
    if (
        conventional.high is not None
        and functional.high is not None
        and functional.high > conventional.high
    ):
        raise RegistryError(f"{key}.functional: high {functional.high} above conventional high")
    for unit, factor in entry.conversions.items():
        if factor <= 0:
            raise RegistryError(f"{key}.conversions: factor for '{unit}' must be positive")
        if unit == entry.unit and factor != 1.0:
            raise RegistryError(
                f"{key}.conversions: '{unit}' is the canonical unit; its factor must be 1.0"
            )
    return MarkerSpec(
        key=key,
        display=entry.display,
        system=entry.system,
        unit=entry.unit,
        aliases=entry.aliases,
        conversions=entry.conversions,
        conventional=conventional,
        functional=functional,
        direction=entry.direction,
        athlete_note=entry.athlete_note.strip(),
        confounders=entry.confounders,
        sources=entry.sources,
    )


class MarkerRegistry:
    def __init__(self, version: str, sex: Sex, markers: dict[str, MarkerSpec]) -> None:
        self.version = version
        self.sex = sex
        self.markers = markers
        self._alias_index: dict[str, str] = {}
        for key, spec in markers.items():
            for alias in spec.aliases:
                norm = normalize_alias(alias)
                if not norm:
                    raise RegistryError(f"{key}.aliases: '{alias}' normalizes to nothing")
                owner = self._alias_index.get(norm)
                if owner is not None and owner != key:
                    raise RegistryError(
                        f"{key}.aliases: '{alias}' already belongs to '{owner}'"
                    )
                self._alias_index[norm] = key

    def get(self, key: str) -> MarkerSpec:
        return self.markers[key]

    def lookup(self, raw_name: str) -> MarkerSpec | None:
        key = self._alias_index.get(normalize_alias(raw_name))
        return self.markers[key] if key else None

    def __len__(self) -> int:
        return len(self.markers)

    def __iter__(self) -> Iterator[str]:
        return iter(self.markers)


def load_registry(sex: Sex, path: Path = MARKERS_PATH) -> MarkerRegistry:
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "version" not in doc or "markers" not in doc:
        raise RegistryError(f"{path.name}: top level needs 'version' and 'markers'")
    markers_raw = doc["markers"]
    if not isinstance(markers_raw, dict) or not markers_raw:
        raise RegistryError(f"{path.name}: 'markers' must be a non-empty mapping")
    markers = {str(k): _resolve(str(k), v, sex) for k, v in markers_raw.items()}
    return MarkerRegistry(str(doc["version"]), sex, markers)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_registry.py -q`
Expected: 17 passed. If `test_validation_names_marker_and_field[bad_duplicate_alias.yaml...]` fails because the error names `ferritin` rather than `iron_serum`: dict order is file order, so `iron_serum`'s `iron` alias is indexed second and the error names it; check the fixture order.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): marker registry with sex resolution, alias index and validation"
```

---

### Task 4: The ranges table (`ranges/markers.yaml`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/ranges/markers.yaml`
- Test: `packages/tri-wellness/tests/test_markers_yaml.py`

**Interfaces:**
- Consumes: `load_registry` from Task 3.
- Produces: the file itself. Its canonical keys are the vocabulary `lab_results.marker` stores and every later plan uses; the keys evaluate depends on by name are `hs_crp` (inflammation confounder). Version `2026-09-11.1`.

This is a draft for Brian's review (spec §17). Conventional ranges follow common US lab reference intervals (LabCorp/Quest), nudged where needed so the functional range sits inside them (the registry enforces this). Functional ranges follow Weatherby & Ferguson (*Blood Chemistry and CBC Analysis*) and IFM published optimal ranges; where they disagree the entry uses one and names the other in `athlete_note`. Athlete notes for ferritin, CK, cortisol, testosterone and vitamin D cite endurance literature. Nothing in the code depends on a number in this file; changing a number changes findings, not tests, except `test_markers_yaml.py`'s structural checks.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_markers_yaml.py`:
```python
"""The real markers.yaml loads for both sexes and every alias and conversion round-trips."""

import pytest

from tri_wellness.ranges.registry import MARKERS_PATH, load_registry, normalize_alias

EXPECTED_KEYS = {
    # cbc
    "wbc", "rbc", "hemoglobin", "hematocrit", "mcv", "mch", "mchc", "rdw", "platelets",
    "neutrophils_pct", "lymphocytes_pct", "monocytes_pct", "eosinophils_pct", "basophils_pct",
    # metabolic / kidney / liver / electrolytes
    "glucose", "insulin", "hba1c", "bun", "creatinine", "egfr", "bun_creatinine_ratio",
    "sodium", "potassium", "chloride", "co2", "calcium", "total_protein", "albumin", "globulin",
    "alt", "ast", "alp", "bilirubin_total", "ggt", "uric_acid", "ck",
    # lipids
    "total_cholesterol", "ldl", "hdl", "triglycerides", "apob", "lpa",
    # thyroid
    "tsh", "free_t4", "free_t3", "reverse_t3", "tpo_ab", "tg_ab",
    # iron
    "ferritin", "iron_serum", "tibc", "transferrin_saturation",
    # inflammation
    "hs_crp", "homocysteine",
    # vitamins and minerals
    "vitamin_d", "b12", "folate", "rbc_magnesium", "zinc", "omega3_index",
    # hormones
    "testosterone_total", "testosterone_free", "shbg", "cortisol_am", "dhea_s",
}


@pytest.mark.parametrize("sex", ["male", "female"])
def test_loads_for_both_sexes(sex):
    reg = load_registry(sex, MARKERS_PATH)
    assert reg.version == "2026-09-11.1"
    assert set(reg) == EXPECTED_KEYS


def test_every_alias_round_trips():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        spec = reg.get(key)
        for alias in spec.aliases:
            found = reg.lookup(alias)
            assert found is not None and found.key == key, (key, alias)
        # the display name also resolves, so a lab printing our own label maps
        assert reg.lookup(spec.display) is not None, (key, spec.display)


def test_every_conversion_lands_on_the_canonical_unit():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        spec = reg.get(key)
        for unit, factor in spec.conversions.items():
            assert factor > 0, (key, unit)
            assert normalize_alias(unit) != "" , (key, unit)
            if unit == spec.unit:
                assert factor == 1.0


def test_directional_markers_have_the_relevant_side():
    reg = load_registry("male", MARKERS_PATH)
    for key in reg:
        s = reg.get(key)
        if s.direction in ("high", "both"):
            assert s.functional.high is not None, key
        if s.direction in ("low", "both"):
            assert s.functional.low is not None, key
        assert s.sources, key
        assert s.athlete_note or s.direction != "both" or key in {"mch", "mchc", "globulin"}, key
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_markers_yaml.py -q`
Expected: `FileNotFoundError` for `markers.yaml`.

- [ ] **Step 3: Write the table, part 1 (CBC, metabolic, kidney, liver, electrolytes)**

`packages/tri-wellness/src/tri_wellness/ranges/markers.yaml` begins:
```yaml
# Curated functional-medicine range table. Reviewed by Brian; every entry cites its sources.
# Field contract (registry.py): unit, aliases, conversions, conventional, functional, direction,
# confounders are read by code. display, system, athlete_note, sources are shown to the model.
# A range block is {low, high} or {male: {low, high}, female: {low, high}}. Either side may be
# omitted for direction: low | high markers. conversions map a printed unit to the factor that
# multiplies it into the canonical unit.
version: 2026-09-11.1
markers:

  # ---- CBC ---------------------------------------------------------------------------------
  wbc:
    display: WBC
    system: cbc
    unit: K/uL
    aliases: [wbc, "white blood cell count", "white blood cells", leukocytes, "wbc count"]
    conversions: {"10^3/uL": 1.0, "x10E3/uL": 1.0, "10*3/uL": 1.0, "10^9/L": 1.0, "G/L": 1.0}
    conventional: {low: 3.4, high: 10.8}
    functional: {low: 5.0, high: 7.5}
    direction: both
    athlete_note: >
      Trained endurance athletes often sit at 4-5 at rest; a value under 5.0 with a normal
      differential is usually training adaptation, not immune suppression. A rise for 24 h after
      a hard session is normal (neutrophilia).
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  rbc:
    display: RBC
    system: cbc
    unit: M/uL
    aliases: [rbc, "red blood cell count", "red blood cells", erythrocytes, "rbc count"]
    conversions: {"10^6/uL": 1.0, "x10E6/uL": 1.0, "10*6/uL": 1.0, "10^12/L": 1.0, "T/L": 1.0}
    conventional: {male: {low: 4.14, high: 5.80}, female: {low: 3.77, high: 5.28}}
    functional: {male: {low: 4.2, high: 4.9}, female: {low: 3.9, high: 4.5}}
    direction: both
    athlete_note: >
      Plasma volume expands with aerobic training, so RBC, hemoglobin and hematocrit read low
      by dilution ("sports anemia"). Judge with MCV, ferritin and transferrin saturation.
    confounders: [high_acute_load]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  hemoglobin:
    display: Hemoglobin
    system: cbc
    unit: g/dL
    aliases: [hemoglobin, hgb, hb, haemoglobin]
    conversions: {"g/L": 0.1, "mmol/L": 1.611}
    conventional: {male: {low: 13.0, high: 17.7}, female: {low: 11.1, high: 15.9}}
    functional: {male: {low: 14.0, high: 15.5}, female: {low: 13.5, high: 14.5}}
    direction: both
    athlete_note: >
      Dilutional lowering from plasma volume expansion is common in endurance athletes; a value
      just under the functional low with normal ferritin and MCV is not iron deficiency. Below the
      conventional low with low ferritin is iron-deficiency anemia and affects performance.
    confounders: [high_acute_load]
    sources: ["Weatherby & Ferguson", "Sim et al. 2019, iron considerations for the athlete"]
  hematocrit:
    display: Hematocrit
    system: cbc
    unit: "%"
    aliases: [hematocrit, hct, haematocrit, "packed cell volume", pcv]
    conversions: {"L/L": 100.0}
    conventional: {male: {low: 37.5, high: 51.0}, female: {low: 34.0, high: 46.6}}
    functional: {male: {low: 40.0, high: 48.0}, female: {low: 37.0, high: 44.0}}
    direction: both
    athlete_note: >
      Reads low with plasma volume expansion and high with dehydration; a same-day long session
      or a hot, unfasted draw can move it 2-3 points either way.
    confounders: [high_acute_load, recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  mcv:
    display: MCV
    system: cbc
    unit: fL
    aliases: [mcv, "mean corpuscular volume", "mean cell volume"]
    conventional: {low: 79, high: 97}
    functional: {low: 85, high: 92}
    direction: both
    athlete_note: >
      Low MCV points to iron deficiency; high MCV to B12 or folate shortfall or alcohol. Read
      with ferritin, B12 and folate before naming a cause.
    confounders: []
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  mch:
    display: MCH
    system: cbc
    unit: pg
    aliases: [mch, "mean corpuscular hemoglobin"]
    conventional: {low: 26.6, high: 33.0}
    functional: {low: 28.0, high: 32.0}
    direction: both
    confounders: []
    sources: ["Weatherby & Ferguson"]
  mchc:
    display: MCHC
    system: cbc
    unit: g/dL
    aliases: [mchc, "mean corpuscular hemoglobin concentration"]
    conventional: {low: 31.5, high: 35.7}
    functional: {low: 32.0, high: 35.0}
    direction: both
    confounders: []
    sources: ["Weatherby & Ferguson"]
  rdw:
    display: RDW
    system: cbc
    unit: "%"
    aliases: [rdw, "red cell distribution width", "rdw-cv", "rdw cv"]
    conventional: {low: 11.7, high: 15.4}
    functional: {low: 11.7, high: 13.0}
    direction: high
    athlete_note: >
      A rising RDW is often the earliest sign of iron, B12 or folate deficiency, before MCV moves.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  platelets:
    display: Platelets
    system: cbc
    unit: K/uL
    aliases: [platelets, "platelet count", plt, thrombocytes]
    conversions: {"10^3/uL": 1.0, "x10E3/uL": 1.0, "10*3/uL": 1.0, "10^9/L": 1.0, "G/L": 1.0}
    conventional: {low: 150, high: 450}
    functional: {low: 175, high: 250}
    direction: both
    athlete_note: >
      Platelets rise transiently after intense exercise and with inflammation.
    confounders: [recent_hard_session, inflammation]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  neutrophils_pct:
    display: Neutrophils %
    system: cbc
    unit: "%"
    aliases: [neutrophils, "neutrophils %", "neutrophils percent", "neutrophil %", neut, "segs", "segmented neutrophils"]
    conventional: {low: 40, high: 74}
    functional: {low: 40, high: 60}
    direction: both
    athlete_note: >
      Neutrophils rise for up to 24 h after a hard session; a high value with a recent session
      and a normal WBC is not an infection signal.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  lymphocytes_pct:
    display: Lymphocytes %
    system: cbc
    unit: "%"
    aliases: [lymphocytes, "lymphocytes %", "lymphocytes percent", "lymphocyte %", lymphs]
    conventional: {low: 14, high: 46}
    functional: {low: 24, high: 44}
    direction: both
    athlete_note: >
      Lymphocytes drop for several hours after prolonged intense exercise (the "open window").
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  monocytes_pct:
    display: Monocytes %
    system: cbc
    unit: "%"
    aliases: [monocytes, "monocytes %", "monocytes percent", "monocyte %", monos]
    conventional: {low: 4, high: 13}
    functional: {high: 7}
    direction: high
    athlete_note: Elevated monocytes with a normal WBC suggest recovery from infection or tissue repair.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  eosinophils_pct:
    display: Eosinophils %
    system: cbc
    unit: "%"
    aliases: [eosinophils, "eosinophils %", "eosinophils percent", "eosinophil %", eos]
    conventional: {low: 0, high: 7}
    functional: {high: 3}
    direction: high
    athlete_note: Allergy, asthma or parasites raise eosinophils; seasonal for many athletes.
    confounders: []
    sources: ["Weatherby & Ferguson"]
  basophils_pct:
    display: Basophils %
    system: cbc
    unit: "%"
    aliases: [basophils, "basophils %", "basophils percent", "basophil %", basos]
    conventional: {low: 0, high: 3}
    functional: {high: 1}
    direction: high
    athlete_note: Rarely informative alone; read with eosinophils.
    confounders: []
    sources: ["Weatherby & Ferguson"]

  # ---- Metabolic ----------------------------------------------------------------------------
  glucose:
    display: Fasting glucose
    system: metabolic
    unit: mg/dL
    aliases: [glucose, "glucose, serum", "glucose, fasting", "fasting glucose", "glucose, plasma", "blood glucose"]
    conversions: {"mmol/L": 18.0182}
    conventional: {low: 65, high: 99}
    functional: {low: 75, high: 86}
    direction: both
    athlete_note: >
      Fasted morning glucose in the low 90s is common in endurance athletes after a heavy
      training block (cortisol-driven), and after a hard session the previous evening. IFM's
      optimal upper bound is 90; this table uses Weatherby's 86 and treats 86-90 as a soft flag.
      Read with insulin and HbA1c before calling it dysglycemia.
    confounders: [not_fasting, recent_hard_session, poor_sleep]
    sources: ["Weatherby & Ferguson", "IFM functional ranges (86-90 upper)"]
  insulin:
    display: Fasting insulin
    system: metabolic
    unit: uIU/mL
    aliases: [insulin, "insulin, fasting", "fasting insulin", "insulin, serum"]
    conversions: {"mIU/L": 1.0, "pmol/L": 0.1441}
    conventional: {low: 2.6, high: 24.9}
    functional: {high: 5.0}
    direction: high
    athlete_note: >
      The most sensitive marker of insulin resistance; trained athletes are typically 2-4.
      Meaningless if not fasted.
    confounders: [not_fasting]
    sources: ["IFM functional ranges", "Weatherby & Ferguson"]
  hba1c:
    display: HbA1c
    system: metabolic
    unit: "%"
    aliases: [hba1c, "hemoglobin a1c", "haemoglobin a1c", a1c, "glycated hemoglobin", "glycohemoglobin"]
    conventional: {low: 4.8, high: 5.6}
    functional: {low: 4.8, high: 5.3}
    direction: high
    athlete_note: >
      Endurance training shortens red cell lifespan, which can read HbA1c 0.2-0.3 lower than
      the true average glucose; iron deficiency reads it higher. Read with fasting glucose and
      insulin.
    confounders: []
    sources: ["IFM functional ranges", "Weatherby & Ferguson"]
  uric_acid:
    display: Uric acid
    system: metabolic
    unit: mg/dL
    aliases: [uric acid, "uric acid, serum", urate]
    conversions: {"umol/L": 0.01681, "µmol/L": 0.01681}
    conventional: {male: {low: 3.7, high: 8.6}, female: {low: 2.5, high: 7.1}}
    functional: {male: {low: 3.7, high: 5.9}, female: {low: 3.0, high: 5.5}}
    direction: both
    athlete_note: >
      Rises for 24-48 h after long or very hard sessions (purine turnover) and with
      dehydration and fructose-heavy fueling. Low values can reflect low purine intake or
      oxidative stress.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  ck:
    display: Creatine kinase (CK)
    system: metabolic
    unit: U/L
    aliases: [ck, "creatine kinase", "creatine kinase, total", "ck, total", cpk, "creatine phosphokinase", "ck total"]
    conversions: {"IU/L": 1.0, "ukat/L": 60.0}
    conventional: {male: {low: 39, high: 308}, female: {low: 26, high: 192}}
    functional: {male: {low: 40, high: 200}, female: {low: 30, high: 150}}
    direction: high
    athlete_note: >
      The clearest training-proximity marker: CK peaks 24-72 h after hard, long or eccentric
      (running, downhill) sessions and can exceed 1000 U/L without pathology. Resting values in
      trained athletes are higher than the general population, so the functional high applies
      only to a draw after 48+ h of easy training. A persistently high CK across rested draws
      suggests under-recovery. Read with AST, ALT and hs-CRP.
    confounders: [recent_hard_session, high_acute_load]
    sources: ["Brancaccio et al. 2007, creatine kinase monitoring in sport medicine", "LabCorp reference intervals"]

  # ---- Kidney -------------------------------------------------------------------------------
  bun:
    display: BUN
    system: kidney
    unit: mg/dL
    aliases: [bun, "blood urea nitrogen", "urea nitrogen", "urea nitrogen, serum"]
    conversions: {"mmol/L": 2.801}
    conventional: {low: 6, high: 24}
    functional: {low: 10, high: 16}
    direction: both
    athlete_note: >
      High BUN with normal creatinine follows a high-protein diet, dehydration or catabolic
      training weeks; low BUN follows low protein intake. Read with the BUN/creatinine ratio.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  creatinine:
    display: Creatinine
    system: kidney
    unit: mg/dL
    aliases: [creatinine, "creatinine, serum", "creatinine, plasma"]
    conversions: {"umol/L": 0.01131, "µmol/L": 0.01131}
    conventional: {male: {low: 0.76, high: 1.27}, female: {low: 0.57, high: 1.00}}
    functional: {male: {low: 0.8, high: 1.1}, female: {low: 0.7, high: 0.9}}
    direction: both
    athlete_note: >
      Tracks muscle mass and creatine supplementation, and rises for 24-48 h after hard sessions
      and with dehydration. An athlete's stable baseline near the conventional high is normal;
      the concern is a rise from baseline with a falling eGFR on a rested draw.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  egfr:
    display: eGFR
    system: kidney
    unit: mL/min/1.73m2
    aliases: [egfr, "estimated gfr", "gfr, estimated", "egfr (ckd-epi)", "glomerular filtration rate"]
    conventional: {low: 60}
    functional: {low: 90}
    direction: low
    athlete_note: >
      Computed from creatinine, so every creatinine caveat applies. A value between 60 and 90
      on a rested, hydrated draw deserves a retest; below 60 is a practitioner conversation.
    confounders: [recent_hard_session]
    sources: ["KDIGO 2012 CKD staging", "IFM functional ranges"]
  bun_creatinine_ratio:
    display: BUN/creatinine ratio
    system: kidney
    unit: ratio
    aliases: ["bun/creatinine ratio", "bun creatinine ratio", "bun/creat ratio", "urea nitrogen/creatinine"]
    conventional: {low: 9, high: 20}
    functional: {low: 10, high: 16}
    direction: both
    athlete_note: >
      High with dehydration or a high-protein diet; low with low protein intake or high muscle
      mass. Adds little when BUN and creatinine are both optimal.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]

  # ---- Liver --------------------------------------------------------------------------------
  alt:
    display: ALT
    system: liver
    unit: U/L
    aliases: [alt, "alt (sgpt)", sgpt, "alanine aminotransferase", "alanine transaminase"]
    conversions: {"IU/L": 1.0}
    conventional: {low: 0, high: 44}
    functional: {low: 10, high: 26}
    direction: high
    athlete_note: >
      Present in muscle as well as liver; rises for 24-72 h after hard or eccentric sessions
      alongside CK and AST. A high ALT with a normal CK and GGT points to the liver (fatty
      liver, alcohol, medication); with a high CK it is muscle.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  ast:
    display: AST
    system: liver
    unit: U/L
    aliases: [ast, "ast (sgot)", sgot, "aspartate aminotransferase", "aspartate transaminase"]
    conversions: {"IU/L": 1.0}
    conventional: {low: 0, high: 40}
    functional: {low: 10, high: 26}
    direction: high
    athlete_note: >
      More muscle-derived than ALT; an AST above ALT with a high CK is exercise, not liver.
      Low AST (under 10) can reflect B6 insufficiency.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  alp:
    display: Alkaline phosphatase
    system: liver
    unit: U/L
    aliases: [alp, "alkaline phosphatase", "alk phos", "alkaline phosphatase, serum"]
    conversions: {"IU/L": 1.0}
    conventional: {low: 44, high: 121}
    functional: {low: 45, high: 100}
    direction: both
    athlete_note: >
      Low ALP suggests zinc or magnesium insufficiency; high ALP points to bone turnover
      (stress fracture healing) or biliary issues. Read with GGT: GGT normal and ALP high is
      bone.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  bilirubin_total:
    display: Bilirubin, total
    system: liver
    unit: mg/dL
    aliases: [bilirubin, "bilirubin, total", "total bilirubin", "bilirubin total"]
    conversions: {"umol/L": 0.05848, "µmol/L": 0.05848}
    conventional: {low: 0.0, high: 1.2}
    functional: {low: 0.1, high: 0.9}
    direction: both
    athlete_note: >
      Mildly high bilirubin after long sessions reflects red cell breakdown (foot-strike
      hemolysis in runners); persistently 1.2-3.0 with everything else normal is usually
      Gilbert's syndrome.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  ggt:
    display: GGT
    system: liver
    unit: U/L
    aliases: [ggt, "gamma-glutamyl transferase", "gamma gt", "gamma glutamyl transpeptidase", "ggtp"]
    conversions: {"IU/L": 1.0}
    conventional: {low: 0, high: 65}
    functional: {low: 10, high: 25}
    direction: high
    athlete_note: >
      The liver-specific enzyme: unaffected by training. Rises with alcohol, fatty liver and
      glutathione demand; the best discriminator when ALT or AST is high.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  total_protein:
    display: Total protein
    system: liver
    unit: g/dL
    aliases: [total protein, "protein, total", "total protein, serum"]
    conversions: {"g/L": 0.1}
    conventional: {low: 6.0, high: 8.5}
    functional: {low: 6.9, high: 7.4}
    direction: both
    athlete_note: Reads high with dehydration and low with plasma volume expansion or low protein intake.
    confounders: [high_acute_load]
    sources: ["Weatherby & Ferguson"]
  albumin:
    display: Albumin
    system: liver
    unit: g/dL
    aliases: [albumin, "albumin, serum"]
    conversions: {"g/L": 0.1}
    conventional: {low: 3.8, high: 4.9}
    functional: {low: 4.0, high: 4.9}
    direction: both
    athlete_note: >
      Falls with inflammation and low protein intake, rises with dehydration. A low albumin
      with a high hs-CRP is inflammation, not nutrition.
    confounders: [inflammation, high_acute_load]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  globulin:
    display: Globulin
    system: liver
    unit: g/dL
    aliases: [globulin, "globulin, total", "globulin, calculated"]
    conversions: {"g/L": 0.1}
    conventional: {low: 1.5, high: 4.5}
    functional: {low: 2.4, high: 2.8}
    direction: both
    confounders: [inflammation]
    sources: ["Weatherby & Ferguson"]

  # ---- Electrolytes -------------------------------------------------------------------------
  sodium:
    display: Sodium
    system: electrolytes
    unit: mmol/L
    aliases: [sodium, "sodium, serum", na]
    conversions: {"mEq/L": 1.0}
    conventional: {low: 134, high: 144}
    functional: {low: 135, high: 140}
    direction: both
    athlete_note: >
      Low sodium after a long session usually means over-drinking plain water; high sodium
      means dehydration. Read with the draw's hydration state, not as a diet marker.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  potassium:
    display: Potassium
    system: electrolytes
    unit: mmol/L
    aliases: [potassium, "potassium, serum", k]
    conversions: {"mEq/L": 1.0}
    conventional: {low: 3.5, high: 5.2}
    functional: {low: 4.0, high: 4.5}
    direction: both
    athlete_note: >
      Leaks from muscle after hard sessions and from red cells with a slow or hemolyzed draw,
      both reading high. Low potassium with low magnesium is a mineral-intake pattern.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  chloride:
    display: Chloride
    system: electrolytes
    unit: mmol/L
    aliases: [chloride, "chloride, serum", cl]
    conversions: {"mEq/L": 1.0}
    conventional: {low: 96, high: 106}
    functional: {low: 100, high: 106}
    direction: both
    athlete_note: Tracks sodium and hydration; low with metabolic alkalosis, high with dehydration.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  co2:
    display: CO2 (bicarbonate)
    system: electrolytes
    unit: mmol/L
    aliases: [co2, "carbon dioxide, total", "carbon dioxide", bicarbonate, "co2, total", hco3]
    conversions: {"mEq/L": 1.0}
    conventional: {low: 20, high: 29}
    functional: {low: 25, high: 29}
    direction: both
    athlete_note: Low CO2 after a hard session reflects lactate buffering; persistently low suggests a metabolic acidosis pattern.
    confounders: [recent_hard_session]
    sources: ["Weatherby & Ferguson"]
  calcium:
    display: Calcium
    system: electrolytes
    unit: mg/dL
    aliases: [calcium, "calcium, serum", "calcium, total", ca]
    conversions: {"mmol/L": 4.008}
    conventional: {low: 8.7, high: 10.2}
    functional: {low: 9.2, high: 10.0}
    direction: both
    athlete_note: >
      Serum calcium is tightly regulated and says little about intake or bone; read with
      vitamin D and albumin (low albumin reads calcium low).
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
```

- [ ] **Step 4: Write the table, part 2 (lipids, thyroid, iron, inflammation, vitamins and minerals, hormones)**

Continue `markers.yaml`:
```yaml

  # ---- Lipids -------------------------------------------------------------------------------
  total_cholesterol:
    display: Total cholesterol
    system: lipids
    unit: mg/dL
    aliases: [total cholesterol, "cholesterol, total", cholesterol, "cholesterol total"]
    conversions: {"mmol/L": 38.67}
    conventional: {low: 100, high: 200}
    functional: {low: 160, high: 200}
    direction: both
    athlete_note: >
      Total cholesterol alone says little; ApoB and LDL particle burden carry the risk. Low
      total cholesterol (under 160) in an endurance athlete can mean under-fueling or low fat
      intake and travels with low testosterone and cortisol.
    confounders: [not_fasting]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  ldl:
    display: LDL cholesterol
    system: lipids
    unit: mg/dL
    aliases: [ldl, "ldl cholesterol", "ldl-c", "ldl chol calc (nih)", "ldl cholesterol, calculated", "ldl, calculated", "ldl-cholesterol"]
    conversions: {"mmol/L": 38.67}
    conventional: {low: 0, high: 100}
    functional: {high: 100}
    direction: high
    athlete_note: >
      Calculated LDL is unreliable when triglycerides are high or the draw is not fasted. When
      LDL is flagged and ApoB is optimal, the particles are large and the risk reading is
      softer; when ApoB is also high, treat it as real.
    confounders: [not_fasting]
    sources: ["IFM functional ranges", "AHA/ACC 2018 cholesterol guideline"]
  hdl:
    display: HDL cholesterol
    system: lipids
    unit: mg/dL
    aliases: [hdl, "hdl cholesterol", "hdl-c", "hdl-cholesterol", "hdl chol"]
    conversions: {"mmol/L": 38.67}
    conventional: {male: {low: 40}, female: {low: 50}}
    functional: {male: {low: 55, high: 85}, female: {low: 60, high: 95}}
    direction: low
    athlete_note: >
      Endurance training raises HDL; very high values (over 90) are not extra protective and
      can reflect alcohol or genetics.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  triglycerides:
    display: Triglycerides
    system: lipids
    unit: mg/dL
    aliases: [triglycerides, tg, trig, "triglycerides, serum"]
    conversions: {"mmol/L": 88.57}
    conventional: {low: 0, high: 149}
    functional: {low: 50, high: 90}
    direction: both
    athlete_note: >
      The most fasting-sensitive lipid; a non-fasted value is uninterpretable. Under 50 with
      low total cholesterol suggests under-fueling. Over 90 fasted with high insulin is the
      insulin-resistance pattern; over 90 with high HbA1c and normal insulin is the carb-
      overload pattern.
    confounders: [not_fasting]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  apob:
    display: ApoB
    system: lipids
    unit: mg/dL
    aliases: [apob, "apolipoprotein b", "apo b", "apolipoprotein b-100", "apo-b"]
    conversions: {"g/L": 100.0}
    conventional: {high: 90}
    functional: {high: 80}
    direction: high
    athlete_note: >
      The particle count that drives atherosclerosis; the number to act on when LDL and ApoB
      disagree. Many lipidologists target under 80, some under 60 for high genetic risk; this
      table uses 80 and names 60 as the aggressive target.
    confounders: []
    sources: ["Sniderman et al. 2019, ApoB particles and cardiovascular disease", "IFM functional ranges"]
  lpa:
    display: Lp(a)
    system: lipids
    unit: nmol/L
    aliases: [lpa, "lp(a)", "lipoprotein (a)", "lipoprotein a", "lipoprotein(a)"]
    conventional: {high: 75}
    functional: {high: 75}
    direction: high
    athlete_note: >
      Genetic and stable across a lifetime; measure once. No linear conversion from mg/dL (a
      lab printing mg/dL is flagged unit? and needs a manual entry with a note). Over 75
      nmol/L (about 30 mg/dL) raises lifetime risk and argues for a lower ApoB target.
    confounders: []
    sources: ["EAS 2022 Lp(a) consensus", "LabCorp reference intervals"]

  # ---- Thyroid ------------------------------------------------------------------------------
  tsh:
    display: TSH
    system: thyroid
    unit: mIU/L
    aliases: [tsh, "thyroid stimulating hormone", "thyrotropin", "tsh, 3rd generation"]
    conversions: {"uIU/mL": 1.0, "µIU/mL": 1.0, "mU/L": 1.0}
    conventional: {low: 0.45, high: 4.5}
    functional: {low: 1.0, high: 2.0}
    direction: both
    athlete_note: >
      TSH is highest overnight and falls through the morning, so an afternoon draw reads lower.
      Heavy training blocks and low energy availability push TSH up and free T3 down (the
      non-thyroidal illness pattern); read with free T3, reverse T3 and the load context.
      IFM's optimal is 0.5-2.0; this table uses Weatherby's 1.0-2.0 floor.
    confounders: [afternoon_draw, high_acute_load, poor_sleep]
    sources: ["Weatherby & Ferguson", "IFM functional ranges (0.5-2.0)"]
  free_t4:
    display: Free T4
    system: thyroid
    unit: ng/dL
    aliases: [free t4, "t4, free", "free thyroxine", ft4, "t4 free", "thyroxine, free"]
    conversions: {"pmol/L": 0.07776}
    conventional: {low: 0.82, high: 1.77}
    functional: {low: 1.0, high: 1.5}
    direction: both
    athlete_note: The storage hormone; normal free T4 with low free T3 is a conversion problem, not production.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  free_t3:
    display: Free T3
    system: thyroid
    unit: pg/mL
    aliases: [free t3, "t3, free", "free triiodothyronine", ft3, "t3 free", "triiodothyronine, free"]
    conversions: {"pmol/L": 0.6512, "pg/dL": 0.01}
    conventional: {low: 2.0, high: 4.4}
    functional: {low: 3.0, high: 4.0}
    direction: both
    athlete_note: >
      The active hormone and the most training-sensitive thyroid marker: it falls with low
      energy availability, hard blocks and poor sleep before TSH moves. Low free T3 with
      normal TSH and free T4 in a heavy block is usually under-fueling, not thyroid disease.
    confounders: [high_acute_load, poor_sleep]
    sources: ["Weatherby & Ferguson", "Loucks 2004, energy availability and the thyroid axis"]
  reverse_t3:
    display: Reverse T3
    system: thyroid
    unit: ng/dL
    aliases: [reverse t3, "t3, reverse", rt3, "reverse triiodothyronine", "t3 reverse"]
    conversions: {"pmol/L": 0.06514, "pg/mL": 0.1, "ng/mL": 100.0}
    conventional: {low: 9.2, high: 24.1}
    functional: {low: 9.2, high: 15.0}
    direction: high
    athlete_note: >
      Rises when the body brakes metabolism: caloric deficit, overreaching, inflammation,
      cortisol excess. High reverse T3 with low-normal free T3 is the strongest lab signal of
      under-recovery in this panel. Read the free T3 : reverse T3 ratio (over 20 with both in
      pg/mL is the usual target).
    confounders: [high_acute_load, inflammation, poor_sleep]
    sources: ["IFM functional ranges", "Weatherby & Ferguson"]
  tpo_ab:
    display: TPO antibodies
    system: thyroid
    unit: IU/mL
    aliases: [tpo ab, "thyroid peroxidase antibodies", "thyroid peroxidase (tpo) ab", "tpo antibodies", "anti-tpo", "thyroperoxidase antibodies", "tpo"]
    conversions: {"kIU/L": 1.0, "U/mL": 1.0}
    conventional: {high: 34}
    functional: {high: 9}
    direction: high
    athlete_note: >
      Any detectable value above 9 suggests autoimmune activity even when TSH is normal; trend
      it. Not affected by training.
    confounders: []
    sources: ["IFM functional ranges", "LabCorp reference intervals"]
  tg_ab:
    display: Thyroglobulin antibodies
    system: thyroid
    unit: IU/mL
    aliases: [tg ab, "thyroglobulin antibodies", "thyroglobulin antibody", "anti-thyroglobulin", "anti-tg", "thyroglobulin ab"]
    conversions: {"kIU/L": 1.0, "U/mL": 1.0}
    conventional: {high: 0.9}
    functional: {high: 0.9}
    direction: high
    athlete_note: Read with TPO antibodies; either positive is the autoimmune signal.
    confounders: []
    sources: ["LabCorp reference intervals", "IFM functional ranges"]

  # ---- Iron ---------------------------------------------------------------------------------
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin, "ferritin, serum"]
    conversions: {"µg/L": 1.0, "ug/L": 1.0}
    conventional: {male: {low: 30, high: 400}, female: {low: 15, high: 150}}
    functional: {male: {low: 50, high: 150}, female: {low: 50, high: 120}}
    direction: both
    athlete_note: >
      Endurance athletes: below 50 impairs adaptation even with normal hemoglobin; below 30 is
      actionable (the 2019 consensus uses 35 for stage 1 deficiency). Ferritin is an
      acute-phase reactant and rises for 24-72 h after hard or long sessions, so read with
      hs-CRP and training proximity: a "normal" ferritin with a high hs-CRP may be hiding a
      deficiency. Over 150 on a rested draw with a high transferrin saturation deserves an
      iron-overload workup (hemochromatosis screen).
    confounders: [recent_hard_session, inflammation]
    sources: ["Sim et al. 2019, iron considerations for the athlete: a narrative review", "Weatherby & Ferguson", "IFM functional ranges"]
  iron_serum:
    display: Serum iron
    system: iron
    unit: ug/dL
    aliases: [iron, "iron, serum", "serum iron", "iron, total", "total iron"]
    conversions: {"µg/dL": 1.0, "umol/L": 5.585, "µmol/L": 5.585}
    conventional: {low: 38, high: 169}
    functional: {low: 85, high: 130}
    direction: both
    athlete_note: >
      Swings 30 % through the day and with meals, supplements and recent sessions; the least
      reliable iron marker on its own. Use it only through transferrin saturation.
    confounders: [not_fasting, recent_hard_session]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  tibc:
    display: TIBC
    system: iron
    unit: ug/dL
    aliases: [tibc, "total iron binding capacity", "iron binding capacity, total", "iron bind.cap.(tibc)"]
    conversions: {"µg/dL": 1.0, "umol/L": 5.585, "µmol/L": 5.585}
    conventional: {low: 250, high: 450}
    functional: {low: 250, high: 350}
    direction: both
    athlete_note: >
      Rises as iron stores fall (the body makes more transferrin), so a high TIBC with a low
      ferritin confirms deficiency; a low TIBC with a high ferritin points to overload or
      inflammation.
    confounders: [inflammation]
    sources: ["Weatherby & Ferguson"]
  transferrin_saturation:
    display: Transferrin saturation
    system: iron
    unit: "%"
    aliases: [transferrin saturation, "iron saturation", "iron sat", "% saturation", "saturation, iron", "tsat", "transferrin sat"]
    conventional: {low: 15, high: 55}
    functional: {low: 25, high: 35}
    direction: both
    athlete_note: >
      Serum iron / TIBC. Under 20 with ferritin under 50 is functional iron deficiency in an
      athlete; over 45 on two draws is the hemochromatosis screen threshold. Inherits serum
      iron's diurnal and meal variability.
    confounders: [not_fasting, recent_hard_session]
    sources: ["Sim et al. 2019", "Weatherby & Ferguson"]

  # ---- Inflammation -------------------------------------------------------------------------
  hs_crp:
    display: hs-CRP
    system: inflammation
    unit: mg/L
    aliases: [hs-crp, hscrp, "crp, high sensitivity", "c-reactive protein, high sensitivity", "c-reactive protein, cardiac", "high sensitivity crp", "crp hs", "cardio crp", "hs crp"]
    conversions: {"mg/dL": 10.0}
    conventional: {high: 3.0}
    functional: {high: 1.0}
    direction: high
    athlete_note: >
      Rises for 24-48 h after long or hard sessions and stays up with muscle damage, illness
      or poor sleep. A value over 1.0 on a rested draw is the signal; over 3.0 on a rested
      draw with no illness is a practitioner conversation. This marker drives the
      `inflammation` confounder for ferritin, platelets, albumin, globulin, reverse T3 and TIBC
      in the same panel.
    confounders: [recent_hard_session, poor_sleep]
    sources: ["IFM functional ranges", "AHA/CDC 2003 CRP risk categories"]
  homocysteine:
    display: Homocysteine
    system: inflammation
    unit: umol/L
    aliases: [homocysteine, "homocysteine, plasma", "homocyst(e)ine", hcy]
    conversions: {"µmol/L": 1.0, "mg/L": 7.397}
    conventional: {low: 0, high: 15}
    functional: {low: 5, high: 8}
    direction: high
    athlete_note: >
      A methylation and B-vitamin marker (folate, B12, B6) more than an inflammation marker.
      Over 8 with low-normal B12 or folate is a B-vitamin pattern; over 8 with both replete
      suggests an MTHFR-type conversion limit. IFM uses under 7 as optimal; this table uses 8.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges (under 7)"]

  # ---- Vitamins and minerals ----------------------------------------------------------------
  vitamin_d:
    display: Vitamin D (25-OH)
    system: vitamins_minerals
    unit: ng/mL
    aliases: [vitamin d, "vitamin d, 25-hydroxy", "25-hydroxyvitamin d", "25-oh vitamin d", "vitamin d 25-hydroxy", "25(oh)d", "vitamin d, 25-oh, total", "vit d 25-oh", "vitamin d total", "calcifediol"]
    conversions: {"nmol/L": 0.4006}
    conventional: {low: 30, high: 100}
    functional: {low: 50, high: 80}
    direction: both
    athlete_note: >
      Athletes below 50 have higher stress-fracture and upper-respiratory illness rates and
      slower recovery; indoor and winter training predicts insufficiency. Repletion takes 8-12
      weeks at 2000-5000 IU/day with a retest; over 100 is toxicity territory. Read with calcium.
    confounders: []
    sources: ["Owens et al. 2018, vitamin D and the athlete: current perspectives", "IFM functional ranges", "Endocrine Society 2011"]
  b12:
    display: Vitamin B12
    system: vitamins_minerals
    unit: pg/mL
    aliases: [b12, "vitamin b12", "vitamin b-12", cobalamin, "b-12", "vitamin b12, serum"]
    conversions: {"pmol/L": 1.355, "ng/L": 1.0}
    conventional: {low: 232, high: 1245}
    functional: {low: 500, high: 900}
    direction: both
    athlete_note: >
      Serum B12 overstates tissue status; 232-500 with a high MCV, high homocysteine or
      symptoms is functional deficiency. Values over 900 are usually supplementation and not
      harmful; over 1245 without supplementation deserves a look at the liver.
    confounders: []
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  folate:
    display: Folate
    system: vitamins_minerals
    unit: ng/mL
    aliases: [folate, "folate, serum", "folic acid", "folate (folic acid), serum", "serum folate"]
    conversions: {"nmol/L": 0.4413, "ug/L": 1.0}
    conventional: {low: 3.0}
    functional: {low: 10, high: 20}
    direction: low
    athlete_note: >
      Serum folate reflects the last few days of intake. Low-normal with high homocysteine or
      a high MCV is the actionable pattern; RBC folate is the tissue measure if it is
      available.
    confounders: [not_fasting]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  rbc_magnesium:
    display: RBC magnesium
    system: vitamins_minerals
    unit: mg/dL
    aliases: [rbc magnesium, "magnesium, rbc", "magnesium, red blood cell", "red blood cell magnesium", "mg, rbc", "erythrocyte magnesium"]
    conversions: {"mmol/L": 2.431}
    conventional: {low: 4.2, high: 6.8}
    functional: {low: 5.5, high: 6.8}
    direction: low
    athlete_note: >
      Serum magnesium is held constant at the expense of tissue stores, so RBC magnesium is the
      marker. Endurance athletes lose magnesium in sweat; below 5.5 is common in high-volume
      blocks and associates with cramping, poor sleep and low HRV.
    confounders: []
    sources: ["IFM functional ranges", "Nielsen & Lukaski 2006, magnesium and exercise"]
  zinc:
    display: Zinc
    system: vitamins_minerals
    unit: ug/dL
    aliases: [zinc, "zinc, plasma", "zinc, serum", "zinc, rbc", "plasma zinc", zn]
    conversions: {"µg/dL": 1.0, "umol/L": 6.538, "µmol/L": 6.538, "mg/L": 100.0}
    conventional: {low: 60, high: 130}
    functional: {low: 90, high: 120}
    direction: both
    athlete_note: >
      Falls with inflammation and after hard sessions (redistribution), rises with recent
      supplements; a fasted, rested draw is needed. Low zinc with a low ALP is the classic
      pattern. Plasma and RBC zinc share this range for the table's purpose; the RBC value is
      the slower-moving one.
    confounders: [inflammation, recent_hard_session, not_fasting]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
  omega3_index:
    display: Omega-3 index
    system: vitamins_minerals
    unit: "%"
    aliases: [omega-3 index, "omega 3 index", "omega3 index", "omegacheck", "epa+dha index"]
    conventional: {low: 4}
    functional: {low: 8, high: 12}
    direction: low
    athlete_note: >
      RBC EPA+DHA as a percentage of total fatty acids; reflects 3-4 months of intake. Under 4
      is high cardiovascular risk; 8-12 is the target. Roughly 1-2 g/day of EPA+DHA moves it
      from 4 to 8 over 3-4 months.
    confounders: []
    sources: ["Harris & von Schacky 2004, the omega-3 index", "IFM functional ranges"]

  # ---- Hormones -----------------------------------------------------------------------------
  testosterone_total:
    display: Testosterone, total
    system: hormones
    unit: ng/dL
    aliases: [testosterone, "testosterone, total", "total testosterone", "testosterone, serum", "testosterone total"]
    conversions: {"nmol/L": 28.84, "ng/mL": 100.0}
    conventional: {male: {low: 264, high: 916}, female: {low: 8, high: 60}}
    functional: {male: {low: 550, high: 900}, female: {low: 25, high: 50}}
    direction: both
    athlete_note: >
      Peaks in the early morning and falls 20-30 % by afternoon; only an AM fasted draw is
      comparable across panels. Falls with high training load, low energy availability and
      poor sleep, and recovers within weeks of a lighter block, so a low value in a heavy block
      is a load signal before it is an endocrine one. Read with SHBG and free testosterone;
      with cortisol for the catabolic ratio. Male functional low: IFM 500, Weatherby 550
      (used).
    confounders: [afternoon_draw, high_acute_load, poor_sleep, low_hrv, not_fasting]
    sources: ["Hackney 2020, hypogonadism in exercising males", "Weatherby & Ferguson", "IFM functional ranges (500)"]
  testosterone_free:
    display: Testosterone, free
    system: hormones
    unit: pg/mL
    aliases: [free testosterone, "testosterone, free", "testosterone,free (direct)", "free testosterone (direct)", "testosterone free"]
    conversions: {"pmol/L": 0.2884, "ng/dL": 10.0}
    conventional: {male: {low: 8.7, high: 25.1}, female: {low: 0.0, high: 4.2}}
    functional: {male: {low: 15.0, high: 25.0}, female: {low: 1.0, high: 4.0}}
    direction: both
    athlete_note: >
      The bioavailable fraction; a normal total with a low free value means SHBG is high, which
      itself rises with low energy availability and high volume. Same timing rules as total
      testosterone. Direct (analog) assays are less reliable than calculated free T; note the
      method if the lab prints it.
    confounders: [afternoon_draw, high_acute_load, poor_sleep, low_hrv]
    sources: ["Hackney 2020", "Weatherby & Ferguson"]
  shbg:
    display: SHBG
    system: hormones
    unit: nmol/L
    aliases: [shbg, "sex hormone binding globulin", "sex hormone-binding globulin", "sex hormone binding glob"]
    conventional: {male: {low: 16.5, high: 55.9}, female: {low: 24.6, high: 122.0}}
    functional: {male: {low: 20, high: 45}, female: {low: 40, high: 100}}
    direction: both
    athlete_note: >
      Rises with high training volume, low energy availability, low insulin and aging; a high
      SHBG lowers free testosterone without changing total. Falls with insulin resistance.
    confounders: [high_acute_load]
    sources: ["Weatherby & Ferguson", "LabCorp reference intervals"]
  cortisol_am:
    display: Cortisol (AM)
    system: hormones
    unit: ug/dL
    aliases: [cortisol, "cortisol, am", "cortisol - am", "am cortisol", "cortisol, serum", "cortisol, total", "cortisol am", "morning cortisol"]
    conversions: {"µg/dL": 1.0, "nmol/L": 0.03625}
    conventional: {low: 6.2, high: 19.4}
    functional: {low: 10, high: 18}
    direction: both
    athlete_note: >
      Only a draw before 10:00 is interpretable; cortisol halves by afternoon. High AM cortisol
      with a low testosterone, low free T3 and a high reverse T3 is the overreaching pattern;
      a flat, low AM cortisol after a long heavy block suggests HPA down-regulation. One
      serum value cannot show the daily rhythm; a 4-point salivary curve does. Read with the
      testosterone : cortisol ratio.
    confounders: [afternoon_draw, high_acute_load, poor_sleep, low_hrv, recent_hard_session]
    sources: ["Hackney & Walz 2013, hormonal adaptation and the stress of exercise training", "Weatherby & Ferguson"]
  dhea_s:
    display: DHEA-S
    system: hormones
    unit: ug/dL
    aliases: [dhea-s, "dhea sulfate", "dhea-sulfate", "dehydroepiandrosterone sulfate", dheas, "dhea s"]
    conversions: {"µg/dL": 1.0, "umol/L": 36.85, "µmol/L": 36.85}
    conventional: {male: {low: 102, high: 416}, female: {low: 45, high: 320}}
    functional: {male: {low: 250, high: 400}, female: {low: 150, high: 300}}
    direction: both
    athlete_note: >
      The adrenal counterweight to cortisol; declines with age (the conventional range is for
      ages 30-50 and should be re-read against the lab's age band). A low DHEA-S with a
      high cortisol is the chronic-stress pattern; stable across the day, so timing matters
      less than for cortisol.
    confounders: [high_acute_load]
    sources: ["Weatherby & Ferguson", "IFM functional ranges"]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_markers_yaml.py packages/tri-wellness/tests/test_registry.py -q`
Expected: 22 passed. A `RegistryError` here names the offending marker and field; fix the YAML, not the test.

- [ ] **Step 6: Lint, commit; hand the file to Brian for review**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): markers.yaml draft, 65 markers with functional ranges and athlete notes"
```

Brian's review of the YAML closes milestone 1 (spec §17). Review points to raise: every functional range against his own past panels; the male functional lows for testosterone (550 vs 500) and glucose (86 vs 90); the sex-specific hemoglobin and ferritin blocks; whether Lp(a) in mg/dL should carry an approximate conversion (`1 mg/dL ≈ 2.4 nmol/L`) rather than being refused.

---

### Task 5: Normalize (`labs/normalize.py`, pure)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/labs/normalize.py`
- Test: `packages/tri-wellness/tests/test_normalize.py`

**Interfaces:**
- Consumes: `RawResult`, `LabResult`, `Unmapped`, `NormalizeResult` (Task 2); `MarkerRegistry`, `MarkerSpec` (Task 3).
- Produces: `parse_value(text: str) -> tuple[float, str | None] | None` (number and an optional note; `None` when not numeric); `normalize(raw_results: list[RawResult], registry: MarkerRegistry) -> NormalizeResult`. Plan 2's normalize node calls `normalize`; Plan 2's YAML editor re-runs it after an edit.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_normalize.py`:
```python
import pytest

from tri_wellness.labs.models import RawResult
from tri_wellness.labs.normalize import normalize, parse_value
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def raw(name, value, unit=None, ref_low=None, ref_high=None, flag=None):
    return RawResult(name=name, value=value, unit=unit, ref_low=ref_low, ref_high=ref_high, flag=flag)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("42", (42.0, None)),
        (" 12.4 ", (12.4, None)),
        ("1,245", (1245.0, None)),
        ("<5", (5.0, "value '<5' stored as bound 5")),
        ("< 0.5", (0.5, "value '< 0.5' stored as bound 0.5")),
        (">200", (200.0, "value '>200' stored as bound 200")),
        ("<=3", (3.0, "value '<=3' stored as bound 3")),
        ("≥ 60", (60.0, "value '≥ 60' stored as bound 60")),
        ("Not detected", None),
        ("", None),
        ("12.4 ng/mL", None),
    ],
)
def test_parse_value(text, expected):
    assert parse_value(text) == expected


def test_plain_row_maps_to_canonical(reg):
    out = normalize([raw("Ferritin, Serum", "42", "ng/mL", "30", "400")], reg)
    assert out.unmapped == []
    [r] = out.results
    assert (r.marker, r.value, r.unit) == ("ferritin", 42.0, "ng/mL")
    assert (r.lab_ref_low, r.lab_ref_high) == (30.0, 400.0)
    assert r.note is None
    assert r.raw.name == "Ferritin, Serum"


def test_unit_conversion_and_case_insensitive_units(reg):
    out = normalize([raw("Glucose", "5.2", "mmol/L"), raw("Hemoglobin", "150", "g/l")], reg)
    g, h = out.results
    assert g.marker == "glucose" and g.unit == "mg/dL" and g.value == pytest.approx(93.6946, abs=1e-4)
    assert g.note == "converted from 5.2 mmol/L"
    assert h.marker == "hemoglobin" and h.value == 15.0 and h.note == "converted from 150 g/l"


def test_bounded_value_keeps_note_and_verbatim_raw(reg):
    [r] = normalize([raw("hs-CRP", "<0.3", "mg/L", None, "3.0", None)], reg).results
    assert r.value == 0.3 and r.note == "value '<0.3' stored as bound 0.3"
    assert r.raw.value == "<0.3" and r.lab_ref_low is None and r.lab_ref_high == 3.0


def test_bounded_lab_reference_is_parsed(reg):
    [r] = normalize([raw("HDL Cholesterol", "62", "mg/dL", ">39", None)], reg).results
    assert r.lab_ref_low == 39.0 and r.lab_ref_high is None


def test_unknown_name_goes_to_unmapped(reg):
    out = normalize([raw("Sedimentation Rate", "4", "mm/hr")], reg)
    assert out.results == []
    [u] = out.unmapped
    assert u.reason == "name" and u.marker is None and u.raw.name == "Sedimentation Rate"


def test_unknown_or_missing_unit_is_unmapped_with_marker(reg):
    out = normalize([raw("Ferritin", "42", "furlongs"), raw("Ferritin", "42")], reg)
    assert out.results == []
    assert [(u.reason, u.marker) for u in out.unmapped] == [("unit", "ferritin"), ("unit", "ferritin")]


def test_non_numeric_value_is_unmapped_with_marker(reg):
    out = normalize([raw("TPO Antibodies", "Negative", "IU/mL")], reg)
    [u] = out.unmapped
    assert u.reason == "value" and u.marker == "tpo_ab"


def test_duplicate_marker_first_row_wins(reg):
    out = normalize([raw("Iron", "90", "ug/dL"), raw("Iron, Serum", "95", "ug/dL")], reg)
    [r] = out.results
    assert r.value == 90.0 and r.raw.name == "Iron"
    [u] = out.unmapped
    assert u.reason == "duplicate" and u.marker == "iron_serum" and u.raw.value == "95"


def test_order_is_preserved_and_flag_kept(reg):
    rows = [raw("Glucose", "92", "mg/dL", flag="H"), raw("TSH", "2.4", "uIU/mL"), raw("ALT", "31", "IU/L")]
    out = normalize(rows, reg)
    assert [r.marker for r in out.results] == ["glucose", "tsh", "alt"]
    assert out.results[0].raw.flag == "H"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_normalize.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.labs.normalize'`.

- [ ] **Step 3: Write normalize**

`packages/tri-wellness/src/tri_wellness/labs/normalize.py`:
```python
"""Raw lab rows to canonical results: alias mapping, unit conversion, bound handling. Pure."""

from __future__ import annotations

import re

from tri_wellness.labs.models import LabResult, NormalizeResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

_BOUND_PREFIXES = ("<=", ">=", "≤", "≥", "<", ">")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)


def parse_value(text: str) -> tuple[float, str | None] | None:
    """'42' -> (42.0, None); '<5' -> (5.0, note); 'Not detected' -> None."""
    s = text.strip()
    prefix = next((p for p in _BOUND_PREFIXES if s.startswith(p)), None)
    body = s[len(prefix) :].strip() if prefix else s
    body = body.replace(",", "")
    if not _NUMBER.match(body):
        return None
    n = float(body)
    note = f"value '{s}' stored as bound {_fmt(n)}" if prefix else None
    return n, note


def _unit_key(unit: str) -> str:
    return unit.strip().lower().replace(" ", "")


def _factor(spec: MarkerSpec, unit: str | None) -> float | None:
    if unit is None:
        return None
    table = {_unit_key(spec.unit): 1.0}
    for u, f in spec.conversions.items():
        table.setdefault(_unit_key(u), f)
    return table.get(_unit_key(unit))


def _ref(text: str | None) -> float | None:
    if text is None:
        return None
    parsed = parse_value(text)
    return parsed[0] if parsed else None


def normalize(raw_results: list[RawResult], registry: MarkerRegistry) -> NormalizeResult:
    out = NormalizeResult()
    taken: set[str] = set()
    for raw in raw_results:
        spec = registry.lookup(raw.name)
        if spec is None:
            out.unmapped.append(Unmapped(raw=raw, reason="name"))
            continue
        if spec.key in taken:
            out.unmapped.append(Unmapped(raw=raw, reason="duplicate", marker=spec.key))
            continue
        parsed = parse_value(raw.value)
        if parsed is None:
            out.unmapped.append(Unmapped(raw=raw, reason="value", marker=spec.key))
            continue
        factor = _factor(spec, raw.unit)
        if factor is None:
            out.unmapped.append(Unmapped(raw=raw, reason="unit", marker=spec.key))
            continue
        number, note = parsed
        notes = [note] if note else []
        if factor != 1.0:
            notes.append(f"converted from {raw.value.strip()} {raw.unit}")
        taken.add(spec.key)
        out.results.append(
            LabResult(
                marker=spec.key,
                value=round(number * factor, 4),
                unit=spec.unit,
                raw=raw,
                lab_ref_low=_ref(raw.ref_low),
                lab_ref_high=_ref(raw.ref_high),
                note="; ".join(notes) or None,
            )
        )
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_normalize.py -q`
Expected: 20 passed. If `test_unit_conversion_and_case_insensitive_units` fails on the glucose value, check the `mmol/L` factor in `markers.yaml` is `18.0182` (5.2 × 18.0182 = 93.6946).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): normalize raw lab rows to canonical results"
```

---

### Task 6: Evaluate (`labs/evaluate.py`, pure)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/labs/evaluate.py`
- Test: `packages/tri-wellness/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `LabResult`, `PanelContext`, `TrainingContext`, `Finding`, `Confounder` (Task 2); `MarkerRegistry`, `MarkerSpec`, `Range` (Task 3).
- Produces: the threshold constants; `conventional_status(value: float, lab_low: float | None, lab_high: float | None, spec: MarkerSpec) -> ConventionalStatus`; `functional_status(value: float, spec: MarkerSpec) -> FunctionalStatus`; `active_confounders(results: list[LabResult], registry: MarkerRegistry, context: PanelContext, training: TrainingContext) -> list[Confounder]` (panel-level, in `Confounder` declaration order); `evaluate(results: list[LabResult], registry: MarkerRegistry, previous: dict[str, tuple[date, float]], context: PanelContext, training: TrainingContext) -> list[Finding]`. Plan 3's report command and `get_panel_findings` tool call `evaluate` with `repo.previous_values` and `load_training_context`.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_evaluate.py`:
```python
from datetime import date, time

import pytest

from tri_wellness.labs.evaluate import (
    active_confounders,
    conventional_status,
    evaluate,
    functional_status,
)
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, TrainingContext
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry

D = date(2026, 9, 1)


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def lr(marker, value, unit, lab_low=None, lab_high=None) -> LabResult:
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        raw=RawResult(name=marker, value=str(value), unit=unit),
        lab_ref_low=lab_low,
        lab_ref_high=lab_high,
    )


def quiet_training(**over) -> TrainingContext:
    base = dict(
        drawn_on=D,
        ctl=60.0,
        atl=62.0,
        tsb=-2.0,
        tss_7d=350.0,
        last_sessions=[],
        sleep_2n_avg_sec=27000,
        sleep_30d_avg_sec=27000,
        hrv_2n_avg=60,
        hrv_30d_avg=60,
    )
    base.update(over)
    return TrainingContext(**base)


FASTED_AM = PanelContext(fasting=True, draw_time=time(7, 30))


# ---- status rules (spec §6) ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (29.9, "low"),          # below table conventional low 30
        (30.0, "suboptimal_low"),
        (49.9, "suboptimal_low"),
        (50.0, "optimal"),
        (150.0, "optimal"),
        (150.1, "suboptimal_high"),
        (400.0, "suboptimal_high"),
        (400.1, "high"),
    ],
)
def test_functional_status_boundaries_direction_both(reg, value, expected):
    assert functional_status(value, reg.get("ferritin")) == expected


def test_functional_status_direction_high_collapses_low_side(reg):
    crp = reg.get("hs_crp")  # conventional {high: 3.0}, functional {high: 1.0}
    assert functional_status(0.0, crp) == "optimal"
    assert functional_status(1.0, crp) == "optimal"
    assert functional_status(1.1, crp) == "suboptimal_high"
    assert functional_status(3.1, crp) == "high"
    ldl = reg.get("ldl")  # direction high, conventional {low: 0, high: 100}
    assert functional_status(0.0, ldl) == "optimal"


def test_functional_status_direction_low_collapses_high_side(reg):
    hdl = reg.get("hdl")  # male conventional {low: 40}, functional {low: 55, high: 85}
    assert functional_status(39.0, hdl) == "low"
    assert functional_status(50.0, hdl) == "suboptimal_low"
    assert functional_status(70.0, hdl) == "optimal"
    assert functional_status(120.0, hdl) == "optimal"  # high side collapsed


def test_conventional_status_prefers_lab_range(reg):
    f = reg.get("ferritin")
    assert conventional_status(25.0, 20.0, 300.0, f) == "in_range"  # lab range 20-300
    assert conventional_status(25.0, None, None, f) == "low"  # table range 30-400
    assert conventional_status(350.0, 20.0, 300.0, f) == "high"
    assert conventional_status(45.0, 39.0, None, reg.get("hdl")) == "in_range"  # one-sided lab
    assert conventional_status(38.0, 39.0, None, reg.get("hdl")) == "low"


# ---- confounders (spec §8) -------------------------------------------------------------------


def test_no_confounders_on_a_quiet_fasted_morning(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training()) == []


def test_recent_hard_session_by_tss_or_duration(reg):
    easy = {"date": "2026-08-31", "sport": "run", "duration_min": 45, "tss": 40, "title": "easy"}
    big_tss = {**easy, "tss": 151}
    long_ride = {**easy, "sport": "bike", "duration_min": 121, "tss": 100}
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[easy])) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[big_tss])) == [
        "recent_hard_session"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[long_ride])) == [
        "recent_hard_session"
    ]
    boundary = {**easy, "tss": 150, "duration_min": 120}
    assert active_confounders([], reg, FASTED_AM, quiet_training(last_sessions=[boundary])) == []
    no_tss = {**easy, "tss": None, "duration_min": 130}
    assert "recent_hard_session" in active_confounders(
        [], reg, FASTED_AM, quiet_training(last_sessions=[no_tss])
    )


def test_high_acute_load(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=60, atl=75)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=60, atl=75.1)) == [
        "high_acute_load"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(ctl=None, atl=90)) == []


def test_poor_sleep(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_2n_avg_sec=23400)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_2n_avg_sec=23399)) == [
        "poor_sleep"
    ]
    assert active_confounders([], reg, FASTED_AM, quiet_training(sleep_30d_avg_sec=None)) == []


def test_low_hrv(reg):
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=54)) == []
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=53)) == ["low_hrv"]
    assert active_confounders([], reg, FASTED_AM, quiet_training(hrv_2n_avg=None)) == []


def test_not_fasting_and_afternoon_draw(reg):
    t = quiet_training()
    assert active_confounders([], reg, PanelContext(fasting=False), t) == ["not_fasting"]
    assert active_confounders([], reg, PanelContext(fasting=None), t) == []
    assert active_confounders([], reg, PanelContext(draw_time=time(10, 0)), t) == []
    assert active_confounders([], reg, PanelContext(draw_time=time(10, 1)), t) == ["afternoon_draw"]


def test_inflammation_from_hs_crp_in_the_same_panel(reg):
    t = quiet_training()
    assert active_confounders([lr("hs_crp", 1.0, "mg/L")], reg, FASTED_AM, t) == []
    assert active_confounders([lr("hs_crp", 1.1, "mg/L")], reg, FASTED_AM, t) == ["inflammation"]
    assert active_confounders([lr("ferritin", 20.0, "ng/mL")], reg, FASTED_AM, t) == []


def test_confounder_order_is_declaration_order(reg):
    hard = {"date": "2026-08-31", "sport": "bike", "duration_min": 180, "tss": 200, "title": "long"}
    out = active_confounders(
        [lr("hs_crp", 2.0, "mg/L")],
        reg,
        PanelContext(fasting=False, draw_time=time(14, 0)),
        quiet_training(last_sessions=[hard], atl=90, sleep_2n_avg_sec=20000, hrv_2n_avg=40),
    )
    assert out == [
        "recent_hard_session",
        "high_acute_load",
        "poor_sleep",
        "low_hrv",
        "not_fasting",
        "afternoon_draw",
        "inflammation",
    ]


# ---- evaluate ---------------------------------------------------------------------------------


def test_evaluate_builds_one_finding_per_result_with_only_declared_confounders(reg):
    hard = {"date": "2026-08-31", "sport": "run", "duration_min": 150, "tss": 180, "title": "long"}
    results = [
        lr("ferritin", 42.0, "ng/mL", 30.0, 400.0),
        lr("hs_crp", 2.5, "mg/L", None, 3.0),
        lr("tsh", 1.5, "mIU/L", 0.45, 4.5),
    ]
    findings = evaluate(
        results,
        reg,
        previous={"ferritin": (date(2026, 3, 1), 35.0)},
        context=PanelContext(fasting=False, draw_time=time(8, 0)),
        training=quiet_training(last_sessions=[hard]),
    )
    assert [f.marker for f in findings] == ["ferritin", "hs_crp", "tsh"]
    fer, crp, tsh = findings
    assert fer.display == "Ferritin" and fer.system == "iron" and fer.unit == "ng/mL"
    assert fer.conventional_status == "in_range" and fer.functional_status == "suboptimal_low"
    assert fer.functional_range == (50.0, 150.0)
    assert fer.previous == (date(2026, 3, 1), 35.0) and fer.delta_pct == 20.0
    # panel-level active: recent_hard_session, not_fasting, inflammation; ferritin declares two
    assert fer.active_confounders == ["recent_hard_session", "inflammation"]
    assert fer.athlete_note.startswith("Endurance athletes: below 50")
    assert crp.functional_status == "suboptimal_high" and crp.functional_range == (None, 1.0)
    assert crp.active_confounders == ["recent_hard_session"]
    assert crp.previous is None and crp.delta_pct is None
    assert tsh.functional_status == "optimal" and tsh.active_confounders == []


def test_evaluate_delta_pct_rounding_and_zero_previous(reg):
    [f] = evaluate(
        [lr("ferritin", 47.0, "ng/mL")],
        reg,
        previous={"ferritin": (D, 45.0)},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert f.delta_pct == 4.4  # 2/45 = 4.444...
    [z] = evaluate(
        [lr("hs_crp", 0.5, "mg/L")],
        reg,
        previous={"hs_crp": (D, 0.0)},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert z.previous == (D, 0.0) and z.delta_pct is None


def test_evaluate_uses_lab_range_for_conventional_status_only(reg):
    [f] = evaluate(
        [lr("ferritin", 25.0, "ng/mL", 20.0, 300.0)],
        reg,
        previous={},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert f.conventional_status == "in_range"
    assert f.functional_status == "low"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_evaluate.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.labs.evaluate'`.

- [ ] **Step 3: Write evaluate**

`packages/tri-wellness/src/tri_wellness/labs/evaluate.py`:
```python
"""LabResults plus contexts to Findings. Pure: no I/O, no model.

Every threshold from the spec's confounder table is a constant here and nowhere else.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any, get_args

from tri_wellness.labs.models import (
    Confounder,
    ConventionalStatus,
    Finding,
    FunctionalStatus,
    LabResult,
    PanelContext,
    TrainingContext,
)
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

HARD_SESSION_TSS = 150.0  # a session above this in the 72 h before the draw
HARD_SESSION_MIN = 120  # or longer than this
ACUTE_LOAD_ATL_OVER_CTL = 15.0  # ATL exceeds CTL by more than this on the draw day
POOR_SLEEP_DEFICIT_SEC = 3600  # two-night mean more than 60 min under the 30-day mean
LOW_HRV_FRACTION = 0.10  # two-night mean more than 10 % under the 30-day mean
AFTERNOON_DRAW_AFTER = time(10, 0)  # draws after this are 'afternoon' for cortisol/testosterone
INFLAMMATION_MARKER = "hs_crp"  # above its functional high fires 'inflammation'

CONFOUNDER_ORDER: tuple[Confounder, ...] = get_args(Confounder)


def conventional_status(
    value: float, lab_low: float | None, lab_high: float | None, spec: MarkerSpec
) -> ConventionalStatus:
    """The lab's printed range when it printed one (either side), else the table's."""
    if lab_low is None and lab_high is None:
        lab_low, lab_high = spec.conventional.low, spec.conventional.high
    if lab_low is not None and value < lab_low:
        return "low"
    if lab_high is not None and value > lab_high:
        return "high"
    return "in_range"


def functional_status(value: float, spec: MarkerSpec) -> FunctionalStatus:
    """Table ranges only. `direction` collapses the irrelevant side to optimal."""
    c, f = spec.conventional, spec.functional
    if spec.direction in ("low", "both"):
        if c.low is not None and value < c.low:
            return "low"
        if f.low is not None and value < f.low:
            return "suboptimal_low"
    if spec.direction in ("high", "both"):
        if c.high is not None and value > c.high:
            return "high"
        if f.high is not None and value > f.high:
            return "suboptimal_high"
    return "optimal"


def _is_hard(session: dict[str, Any]) -> bool:
    tss = session.get("tss")
    minutes = session.get("duration_min")
    return (tss is not None and float(tss) > HARD_SESSION_TSS) or (
        minutes is not None and float(minutes) > HARD_SESSION_MIN
    )


def active_confounders(
    results: list[LabResult],
    registry: MarkerRegistry,
    context: PanelContext,
    training: TrainingContext,
) -> list[Confounder]:
    """Panel-level confounders, in Confounder declaration order. A rule whose inputs are missing
    does not fire."""
    fired: set[Confounder] = set()
    if any(_is_hard(s) for s in training.last_sessions):
        fired.add("recent_hard_session")
    if (
        training.atl is not None
        and training.ctl is not None
        and training.atl - training.ctl > ACUTE_LOAD_ATL_OVER_CTL
    ):
        fired.add("high_acute_load")
    if (
        training.sleep_2n_avg_sec is not None
        and training.sleep_30d_avg_sec is not None
        and training.sleep_30d_avg_sec - training.sleep_2n_avg_sec > POOR_SLEEP_DEFICIT_SEC
    ):
        fired.add("poor_sleep")
    if (
        training.hrv_2n_avg is not None
        and training.hrv_30d_avg is not None
        and training.hrv_2n_avg < training.hrv_30d_avg * (1 - LOW_HRV_FRACTION)
    ):
        fired.add("low_hrv")
    if context.fasting is False:
        fired.add("not_fasting")
    if context.draw_time is not None and context.draw_time > AFTERNOON_DRAW_AFTER:
        fired.add("afternoon_draw")
    crp = next((r for r in results if r.marker == INFLAMMATION_MARKER), None)
    if crp is not None and INFLAMMATION_MARKER in registry.markers:
        high = registry.get(INFLAMMATION_MARKER).functional.high
        if high is not None and crp.value > high:
            fired.add("inflammation")
    return [c for c in CONFOUNDER_ORDER if c in fired]


def _delta_pct(value: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)


def evaluate(
    results: list[LabResult],
    registry: MarkerRegistry,
    previous: dict[str, tuple[date, float]],
    context: PanelContext,
    training: TrainingContext,
) -> list[Finding]:
    panel_active = active_confounders(results, registry, context, training)
    findings: list[Finding] = []
    for r in results:
        spec = registry.get(r.marker)
        prev = previous.get(r.marker)
        findings.append(
            Finding(
                marker=r.marker,
                display=spec.display,
                system=spec.system,
                value=r.value,
                unit=r.unit,
                conventional_status=conventional_status(
                    r.value, r.lab_ref_low, r.lab_ref_high, spec
                ),
                functional_status=functional_status(r.value, spec),
                functional_range=(spec.functional.low, spec.functional.high),
                previous=prev,
                delta_pct=_delta_pct(r.value, prev[1] if prev else None),
                active_confounders=[c for c in spec.confounders if c in panel_active],
                athlete_note=spec.athlete_note,
            )
        )
    return findings
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_evaluate.py -q`
Expected: 22 passed. If `test_evaluate_builds_one_finding...` fails on `fer.active_confounders`, check `markers.yaml` still declares `confounders: [recent_hard_session, inflammation]` on ferritin and `[recent_hard_session, poor_sleep]` on hs_crp in that order.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): evaluate findings with status rules and confounders"
```

---

### Task 7: Training context (`labs/training_context.py`) and test seeds

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/labs/training_context.py`, `packages/tri-wellness/src/tri_wellness/testing.py`, `packages/tri-wellness/tests/conftest.py`
- Test: `packages/tri-wellness/tests/test_training_context.py` (db-marked)

**Interfaces:**
- Consumes: `tri_core.db.repo.Conn`, `upsert_workouts`, `upsert_daily_metrics`, `tri_core.db.models.WorkoutRow`, `DailyMetricsRow`; `TrainingContext` (Task 2).
- Produces: `load_training_context(conn: Conn, drawn_on: date) -> TrainingContext`; window constants `SESSION_WINDOW_DAYS = 3`, `MAX_SESSIONS = 3`, `NIGHTS = 2`, `BASELINE_DAYS = 30`, `LOAD_FALLBACK_DAYS = 7`, `TSS_WINDOW_DAYS = 7`; `tri_wellness.testing.seed_workouts(conn, rows)` and `seed_daily_metrics(conn, rows)`. Plan 3's report command calls `load_training_context`.

- [ ] **Step 1: Write the seeds and conftest**

`packages/tri-wellness/src/tri_wellness/testing.py`:
```python
"""Test doubles and SQL seeds for the wellness package. Imported by tests only."""

from __future__ import annotations

from typing import Any

from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, and optional title,
    actual_duration_sec, actual_tss, completed (default True)."""
    out: list[WorkoutRow] = []
    for r in rows:
        out.append(
            WorkoutRow(
                tp_workout_id=r["tp_workout_id"],
                workout_date=r["workout_date"],
                sport=r["sport"],
                sport_raw=None,
                title=r.get("title", ""),
                description=None,
                completed=bool(r.get("completed", True)),
                planned_duration_sec=r.get("planned_duration_sec"),
                planned_distance_m=None,
                planned_tss=r.get("planned_tss"),
                planned_if=None,
                actual_duration_sec=r.get("actual_duration_sec"),
                actual_distance_m=None,
                actual_tss=r.get("actual_tss"),
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=None,
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        )
    upsert_workouts(conn, out)


def seed_daily_metrics(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with metric_date and any other DailyMetricsRow field."""
    upsert_daily_metrics(conn, [DailyMetricsRow(**r) for r in rows])
```

`packages/tri-wellness/tests/conftest.py`:
```python
import pytest


@pytest.fixture
def wdb(db):
    """The rolled-back test connection, skipped until 005_wellness.sql is applied."""
    if db.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied to the test database")
    return db
```

- [ ] **Step 2: Write the failing test**

`packages/tri-wellness/tests/test_training_context.py`:
```python
from datetime import date, timedelta

import pytest

from tri_wellness.labs.training_context import load_training_context
from tri_wellness.testing import seed_daily_metrics, seed_workouts

pytestmark = pytest.mark.db

D = date(2031, 1, 15)  # far from any synced data


def day(n: int) -> date:
    return D + timedelta(days=n)


def seed_quiet_month(db, sleep=27000, hrv=60):
    seed_daily_metrics(
        db,
        [
            {
                "metric_date": day(-n),
                "sleep_seconds": sleep,
                "hrv_overnight_avg": hrv,
                "ctl": 60.0 + n,
                "atl": 62.0 + n,
                "tsb": -2.0,
                "tss_day": 50.0,
            }
            for n in range(0, 31)
        ],
    )


def test_empty_database_gives_nones(db):
    t = load_training_context(db, D)
    assert t.drawn_on == D
    assert t.ctl is None and t.atl is None and t.tsb is None and t.tss_7d is None
    assert t.last_sessions == []
    assert t.sleep_2n_avg_sec is None and t.hrv_30d_avg is None


def test_sessions_window_hardest_first_completed_only(db):
    seed_workouts(
        db,
        [
            {"tp_workout_id": "w-ride", "workout_date": day(-2), "sport": "bike", "title": "long ride", "actual_duration_sec": 10800, "actual_tss": 200},
            {"tp_workout_id": "w-run", "workout_date": day(-1), "sport": "run", "title": "easy", "actual_duration_sec": 2700, "actual_tss": 40},
            {"tp_workout_id": "w-swim", "workout_date": day(-3), "sport": "swim", "title": "swim", "actual_duration_sec": 3600, "actual_tss": 60},
            {"tp_workout_id": "w-planned", "workout_date": day(-2), "sport": "run", "title": "skipped", "completed": False, "planned_tss": 300},
            {"tp_workout_id": "w-drawday", "workout_date": day(0), "sport": "bike", "title": "same day", "actual_duration_sec": 7200, "actual_tss": 180},
            {"tp_workout_id": "w-old", "workout_date": day(-4), "sport": "run", "title": "too old", "actual_duration_sec": 9000, "actual_tss": 220},
            {"tp_workout_id": "w-notss", "workout_date": day(-1), "sport": "strength", "title": "gym", "actual_duration_sec": 1800, "actual_tss": None},
        ],
    )
    t = load_training_context(db, D)
    assert [s["title"] for s in t.last_sessions] == ["long ride", "swim", "easy"]
    assert t.last_sessions[0] == {
        "date": day(-2).isoformat(),
        "sport": "bike",
        "duration_min": 180,
        "tss": 200.0,
        "title": "long ride",
    }


def test_load_from_draw_day_row_and_seven_day_tss(db):
    seed_quiet_month(db)
    t = load_training_context(db, D)
    assert (t.ctl, t.atl, t.tsb) == (60.0, 62.0, -2.0)
    assert t.tss_7d == 350.0  # seven days before the draw, not the draw day


def test_load_falls_back_to_most_recent_row_in_seven_days(db):
    seed_daily_metrics(db, [{"metric_date": day(-3), "ctl": 55.0, "atl": 70.0, "tsb": -15.0}])
    seed_daily_metrics(db, [{"metric_date": day(-9), "ctl": 40.0, "atl": 40.0, "tsb": 0.0}])
    t = load_training_context(db, D)
    assert (t.ctl, t.atl, t.tsb) == (55.0, 70.0, -15.0)
    assert load_training_context(db, day(-10)).ctl is None  # both rows are after that draw


def test_sleep_and_hrv_two_nights_versus_thirty_days(db):
    seed_quiet_month(db)
    seed_daily_metrics(
        db,
        [
            {"metric_date": day(-1), "sleep_seconds": 21600, "hrv_overnight_avg": 50},
            {"metric_date": day(0), "sleep_seconds": 18000, "hrv_overnight_avg": 40},
        ],
    )
    t = load_training_context(db, D)
    assert t.sleep_2n_avg_sec == 19800  # mean of the two nights ending on the draw morning
    assert t.hrv_2n_avg == 45
    # the baseline is the 30 days before the draw day; day(-1) is in it, day(0) is not
    assert t.sleep_30d_avg_sec == round((29 * 27000 + 21600) / 30)
    assert t.hrv_30d_avg == round((29 * 60 + 50) / 30)


def test_null_nights_are_skipped(db):
    seed_daily_metrics(
        db,
        [
            {"metric_date": day(-1), "sleep_seconds": None, "hrv_overnight_avg": None},
            {"metric_date": day(0), "sleep_seconds": 25200, "hrv_overnight_avg": 55},
        ],
    )
    t = load_training_context(db, D)
    assert t.sleep_2n_avg_sec == 25200 and t.hrv_2n_avg == 55
    assert t.sleep_30d_avg_sec is None
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_training_context.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.labs.training_context'` (or the tests skip when Postgres is down; start it with `docker compose up -d db`).

- [ ] **Step 4: Write the reader**

`packages/tri-wellness/src/tri_wellness/labs/training_context.py`:
```python
"""Load, sleep and HRV around a draw date, from the tables tri-core syncs. Read-only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_wellness.labs.models import TrainingContext

SESSION_WINDOW_DAYS = 3  # sessions on the three calendar days before the draw (the 72 h)
MAX_SESSIONS = 3
NIGHTS = 2  # the two nights ending on the draw morning: metric_date in {D-1, D}
BASELINE_DAYS = 30  # metric_date in [D-30, D-1]
LOAD_FALLBACK_DAYS = 7  # newest ctl within this many days when the draw-day row is missing
TSS_WINDOW_DAYS = 7  # tss_day summed over [D-7, D-1]

_NIGHT_COLUMNS = frozenset({"sleep_seconds", "hrv_overnight_avg"})


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _sessions(conn: Conn, drawn_on: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select workout_date, sport, title, actual_duration_sec, actual_tss
        from workouts
        where completed and workout_date between %s and %s
        order by actual_tss desc nulls last, actual_duration_sec desc nulls last, workout_date desc
        limit %s
        """,
        (drawn_on - timedelta(days=SESSION_WINDOW_DAYS), drawn_on - timedelta(days=1), MAX_SESSIONS),
    ).fetchall()
    return [
        {
            "date": r["workout_date"].isoformat(),
            "sport": r["sport"],
            "duration_min": (
                None if r["actual_duration_sec"] is None else r["actual_duration_sec"] // 60
            ),
            "tss": _f(r["actual_tss"]),
            "title": r["title"],
        }
        for r in rows
    ]


def _night_avg(conn: Conn, column: str, start: date, end: date) -> int | None:
    assert column in _NIGHT_COLUMNS
    row = conn.execute(
        f"select avg({column}) as v from daily_metrics where metric_date between %s and %s",
        (start, end),
    ).fetchone()
    return None if row is None or row["v"] is None else round(float(row["v"]))


def load_training_context(conn: Conn, drawn_on: date) -> TrainingContext:
    eve = drawn_on - timedelta(days=1)
    load = conn.execute(
        """
        select ctl, atl, tsb from daily_metrics
        where metric_date between %s and %s and ctl is not null
        order by metric_date desc limit 1
        """,
        (drawn_on - timedelta(days=LOAD_FALLBACK_DAYS), drawn_on),
    ).fetchone()
    tss = conn.execute(
        "select sum(tss_day) as v from daily_metrics where metric_date between %s and %s",
        (drawn_on - timedelta(days=TSS_WINDOW_DAYS), eve),
    ).fetchone()
    first_night = drawn_on - timedelta(days=NIGHTS - 1)
    baseline_start = drawn_on - timedelta(days=BASELINE_DAYS)
    return TrainingContext(
        drawn_on=drawn_on,
        ctl=_f(load["ctl"]) if load else None,
        atl=_f(load["atl"]) if load else None,
        tsb=_f(load["tsb"]) if load else None,
        tss_7d=_f(tss["v"]) if tss else None,
        last_sessions=_sessions(conn, drawn_on),
        sleep_2n_avg_sec=_night_avg(conn, "sleep_seconds", first_night, drawn_on),
        sleep_30d_avg_sec=_night_avg(conn, "sleep_seconds", baseline_start, eve),
        hrv_2n_avg=_night_avg(conn, "hrv_overnight_avg", first_night, drawn_on),
        hrv_30d_avg=_night_avg(conn, "hrv_overnight_avg", baseline_start, eve),
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_training_context.py -q`
Expected: 6 passed (or 6 skipped without Postgres; the task is not done until they pass against `tri_analyze_test`). In `test_sessions_window_hardest_first_completed_only` the `strength` session with null TSS sorts last and is cut by the limit; the swim (60 TSS) outranks the easy run (40).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): training context around the draw date; test seeds"
```

---

### Task 8: Lab repository (`repo.py`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/repo.py`
- Test: `packages/tri-wellness/tests/test_repo.py` (db-marked, uses the `wdb` fixture from Task 7)

**Interfaces:**
- Consumes: `tri_core.db.repo.Conn`; `PanelContext`, `RawResult`, `LabResult`, `Finding`, `StoredPanel`, `StoredResult`, `StoredReport`, `PanelSummary`, `SourceKind` (Task 2).
- Produces (every function takes an open connection; callers commit):
  - `insert_panel(conn, *, drawn_on: date, lab_name: str | None, source_file: str | None, source_kind: SourceKind, context: PanelContext, raw_extract: list[RawResult], results: list[LabResult]) -> int` (Plan 2's store node)
  - `get_panel(conn, panel_id: int) -> StoredPanel | None`
  - `latest_panel_id(conn) -> int | None` (newest `drawn_on`, then highest id)
  - `list_panels(conn) -> list[PanelSummary]` (newest first; `unmapped_count = len(raw_extract) - result_count`)
  - `find_duplicate_panels(conn, drawn_on: date, lab_name: str | None) -> list[int]` (Plan 2's review warning)
  - `list_results(conn, panel_id: int) -> list[StoredResult]` (marker order)
  - `lab_results_for_panel(conn, panel_id: int) -> list[LabResult]` (what evaluate consumes; `raw` rebuilt from the `raw_*` columns, `ref_low`/`ref_high` from the numeric columns)
  - `previous_values(conn, panel_id: int) -> dict[str, tuple[date, float]]` (per marker, the most recent panel strictly earlier by `(drawn_on, id)`)
  - `marker_history(conn, marker: str) -> list[tuple[int, date, float, str]]` (`panel_id, drawn_on, value, unit`, oldest first; Plan 3's `get_marker_history`)
  - `insert_report(conn, panel_id: int, ranges_version: str, findings: list[Finding], report_md: str) -> int`
  - `get_report(conn, report_id: int) -> StoredReport | None`
  - `latest_report_for_panel(conn, panel_id: int) -> StoredReport | None`

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_repo.py`:
```python
from datetime import date, time

import pytest

from tri_wellness import repo
from tri_wellness.labs.models import Finding, LabResult, PanelContext, RawResult

pytestmark = pytest.mark.db

D1, D2, D3 = date(2031, 1, 15), date(2031, 4, 15), date(2031, 7, 15)
CTX = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["vitamin d"], symptoms=[])


def raw(name, value, unit="ng/mL", ref_low=None, ref_high=None, flag=None):
    return RawResult(name=name, value=value, unit=unit, ref_low=ref_low, ref_high=ref_high, flag=flag)


def lr(marker, value, unit="ng/mL", name=None, **over) -> LabResult:
    base = dict(
        marker=marker,
        value=value,
        unit=unit,
        raw=raw(name or marker, str(value), unit, "30", "400", "L" if value < 30 else None),
        lab_ref_low=30.0,
        lab_ref_high=400.0,
    )
    base.update(over)
    return LabResult(**base)


def panel(conn, drawn_on, results, lab="Quest", extra_raw=()):
    return repo.insert_panel(
        conn,
        drawn_on=drawn_on,
        lab_name=lab,
        source_file=f"/labs/{drawn_on}.pdf",
        source_kind="pdf",
        context=CTX,
        raw_extract=[r.raw for r in results] + list(extra_raw),
        results=results,
    )


def test_insert_and_get_panel_roundtrip(wdb):
    pid = panel(wdb, D1, [lr("ferritin", 42.0), lr("hs_crp", 0.4, "mg/L")], extra_raw=[raw("ESR", "4", "mm/hr")])
    p = repo.get_panel(wdb, pid)
    assert p is not None and p.id == pid
    assert (p.drawn_on, p.lab_name, p.source_kind) == (D1, "Quest", "pdf")
    assert p.source_file == f"/labs/{D1}.pdf"
    assert p.context == CTX
    assert [r.name for r in p.raw_extract] == ["ferritin", "hs_crp", "ESR"]
    assert repo.get_panel(wdb, pid + 1000) is None


def test_results_roundtrip_and_lab_results_rebuild(wdb):
    fer = lr("ferritin", 42.0, name="Ferritin, Serum", note="converted from 42 ug/L")
    crp = lr("hs_crp", 0.3, "mg/L", raw=raw("hs-CRP", "<0.3", "mg/L", None, "3.0"), lab_ref_low=None, lab_ref_high=3.0)
    pid = panel(wdb, D1, [fer, crp])
    stored = repo.list_results(wdb, pid)
    assert [s.marker for s in stored] == ["ferritin", "hs_crp"]  # marker order
    f = stored[0]
    assert (f.value, f.unit, f.raw_name, f.raw_value, f.raw_unit) == (42.0, "ng/mL", "Ferritin, Serum", "42.0", "ng/mL")
    assert (f.lab_ref_low, f.lab_ref_high, f.flag) == (30.0, 400.0, None)
    c = stored[1]
    assert (c.raw_value, c.lab_ref_low, c.lab_ref_high) == ("<0.3", None, 3.0)
    rebuilt = repo.lab_results_for_panel(wdb, pid)
    assert [(r.marker, r.value, r.unit, r.lab_ref_low, r.lab_ref_high) for r in rebuilt] == [
        ("ferritin", 42.0, "ng/mL", 30.0, 400.0),
        ("hs_crp", 0.3, "mg/L", None, 3.0),
    ]
    assert rebuilt[0].raw.name == "Ferritin, Serum" and rebuilt[1].raw.value == "<0.3"
    assert rebuilt[0].note is None  # notes are not stored; the report reads the raw columns


def test_insert_panel_is_atomic_on_duplicate_marker(wdb):
    import psycopg

    with pytest.raises(psycopg.errors.UniqueViolation):
        with wdb.transaction():
            panel(wdb, D1, [lr("ferritin", 42.0), lr("ferritin", 43.0)])
    assert all(p.drawn_on != D1 for p in repo.list_panels(wdb))  # no panel row left behind


def test_latest_panel_and_list_panels(wdb):
    a = panel(wdb, D2, [lr("ferritin", 40.0)])
    b = panel(wdb, D1, [lr("ferritin", 35.0), lr("hs_crp", 0.5, "mg/L")], extra_raw=[raw("ESR", "4")])
    c = panel(wdb, D2, [lr("ferritin", 41.0)], lab="LabCorp")
    assert repo.latest_panel_id(wdb) == c  # same drawn_on as a, higher id
    summaries = [s for s in repo.list_panels(wdb) if s.id in (a, b, c)]
    assert [s.id for s in summaries] == [c, a, b]
    by_id = {s.id: s for s in summaries}
    assert (by_id[b].result_count, by_id[b].unmapped_count, by_id[b].has_report) == (2, 1, False)
    assert (by_id[a].result_count, by_id[a].unmapped_count) == (1, 0)
    repo.insert_report(wdb, b, "2026-09-11.1", [], "# report")
    assert {s.id: s.has_report for s in repo.list_panels(wdb) if s.id in (a, b)} == {a: False, b: True}


def test_find_duplicate_panels(wdb):
    a = panel(wdb, D1, [lr("ferritin", 40.0)])
    panel(wdb, D1, [lr("ferritin", 40.0)], lab="LabCorp")
    panel(wdb, D2, [lr("ferritin", 40.0)])
    assert repo.find_duplicate_panels(wdb, D1, "Quest") == [a]
    assert repo.find_duplicate_panels(wdb, D3, "Quest") == []
    n = panel(wdb, D3, [lr("ferritin", 40.0)], lab=None)
    assert repo.find_duplicate_panels(wdb, D3, None) == [n]


def test_previous_values_and_marker_history(wdb):
    p1 = panel(wdb, D1, [lr("ferritin", 35.0), lr("hs_crp", 0.5, "mg/L")])
    p2 = panel(wdb, D2, [lr("ferritin", 40.0)])
    p3 = panel(wdb, D3, [lr("ferritin", 48.0), lr("hs_crp", 0.9, "mg/L"), lr("tsh", 1.5, "mIU/L")])
    assert repo.previous_values(wdb, p1) == {}
    assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0), "hs_crp": (D1, 0.5)}
    assert repo.previous_values(wdb, p3) == {"ferritin": (D2, 40.0), "hs_crp": (D1, 0.5)}
    assert repo.marker_history(wdb, "ferritin") == [
        (p1, D1, 35.0, "ng/mL"),
        (p2, D2, 40.0, "ng/mL"),
        (p3, D3, 48.0, "ng/mL"),
    ]
    assert repo.marker_history(wdb, "tsh") == [(p3, D3, 1.5, "mIU/L")]
    assert repo.marker_history(wdb, "nope") == []


def test_previous_values_same_day_uses_lower_id(wdb):
    p1 = panel(wdb, D1, [lr("ferritin", 35.0)])
    p2 = panel(wdb, D1, [lr("ferritin", 36.0)], lab="LabCorp")
    assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0)}
    assert repo.previous_values(wdb, p1) == {}


def test_reports_roundtrip(wdb):
    pid = panel(wdb, D1, [lr("ferritin", 42.0)])
    finding = Finding(
        marker="ferritin",
        display="Ferritin",
        system="iron",
        value=42.0,
        unit="ng/mL",
        conventional_status="in_range",
        functional_status="suboptimal_low",
        functional_range=(50.0, 150.0),
        previous=(date(2030, 10, 1), 35.0),
        delta_pct=20.0,
        active_confounders=["recent_hard_session"],
        athlete_note="note",
    )
    assert repo.latest_report_for_panel(wdb, pid) is None
    r1 = repo.insert_report(wdb, pid, "2026-09-11.1", [finding], "# first")
    r2 = repo.insert_report(wdb, pid, "2026-09-11.2", [finding], "# second")
    got = repo.get_report(wdb, r1)
    assert got is not None and got.panel_id == pid and got.ranges_version == "2026-09-11.1"
    assert got.findings == [finding] and got.report_md == "# first"
    latest = repo.latest_report_for_panel(wdb, pid)
    assert latest is not None and latest.id == r2 and latest.report_md == "# second"
    assert repo.get_report(wdb, r2 + 1000) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_repo.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.repo'` (skips if `005_wellness.sql` is not applied; Brian applies it, Task 1 step 5).

- [ ] **Step 3: Write the repository**

`packages/tri-wellness/src/tri_wellness/repo.py`:
```python
"""Lab-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_wellness.labs.models import (
    Finding,
    LabResult,
    PanelContext,
    PanelSummary,
    RawResult,
    SourceKind,
    StoredPanel,
    StoredReport,
    StoredResult,
)


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def insert_panel(
    conn: Conn,
    *,
    drawn_on: date,
    lab_name: str | None,
    source_file: str | None,
    source_kind: SourceKind,
    context: PanelContext,
    raw_extract: list[RawResult],
    results: list[LabResult],
) -> int:
    """Insert the panel and its result rows. Runs inside the caller's transaction, so a
    failing result row leaves no panel behind."""
    row = conn.execute(
        """
        insert into lab_panels (drawn_on, lab_name, source_file, source_kind, context, raw_extract)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (
            drawn_on,
            lab_name,
            source_file,
            source_kind,
            Jsonb(context.model_dump(mode="json")),
            Jsonb([r.model_dump(mode="json") for r in raw_extract]),
        ),
    ).fetchone()
    assert row is not None
    panel_id = int(row["id"])
    with conn.cursor() as cur:
        for r in results:
            cur.execute(
                """
                insert into lab_results (panel_id, marker, value, unit, raw_name, raw_value,
                    raw_unit, lab_ref_low, lab_ref_high, flag)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    panel_id,
                    r.marker,
                    r.value,
                    r.unit,
                    r.raw.name,
                    r.raw.value,
                    r.raw.unit,
                    r.lab_ref_low,
                    r.lab_ref_high,
                    r.raw.flag,
                ),
            )
    return panel_id


def _panel(row: dict[str, Any]) -> StoredPanel:
    return StoredPanel(
        id=row["id"],
        drawn_on=row["drawn_on"],
        lab_name=row["lab_name"],
        source_file=row["source_file"],
        source_kind=row["source_kind"],
        context=PanelContext.model_validate(row["context"]),
        raw_extract=[RawResult.model_validate(r) for r in row["raw_extract"]],
        created_at=row["created_at"],
    )


def get_panel(conn: Conn, panel_id: int) -> StoredPanel | None:
    row = conn.execute("select * from lab_panels where id = %s", (panel_id,)).fetchone()
    return _panel(row) if row else None


def latest_panel_id(conn: Conn) -> int | None:
    row = conn.execute(
        "select id from lab_panels order by drawn_on desc, id desc limit 1"
    ).fetchone()
    return int(row["id"]) if row else None


def list_panels(conn: Conn) -> list[PanelSummary]:
    rows = conn.execute(
        """
        select p.id, p.drawn_on, p.lab_name,
               jsonb_array_length(p.raw_extract) as raw_count,
               (select count(*) from lab_results r where r.panel_id = p.id) as result_count,
               exists (select 1 from lab_reports x where x.panel_id = p.id) as has_report
        from lab_panels p
        order by p.drawn_on desc, p.id desc
        """
    ).fetchall()
    return [
        PanelSummary(
            id=r["id"],
            drawn_on=r["drawn_on"],
            lab_name=r["lab_name"],
            result_count=int(r["result_count"]),
            unmapped_count=int(r["raw_count"]) - int(r["result_count"]),
            has_report=bool(r["has_report"]),
        )
        for r in rows
    ]


def find_duplicate_panels(conn: Conn, drawn_on: date, lab_name: str | None) -> list[int]:
    rows = conn.execute(
        "select id from lab_panels where drawn_on = %s and lab_name is not distinct from %s "
        "order by id",
        (drawn_on, lab_name),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _result(row: dict[str, Any]) -> StoredResult:
    return StoredResult(
        panel_id=row["panel_id"],
        marker=row["marker"],
        value=float(row["value"]),
        unit=row["unit"],
        raw_name=row["raw_name"],
        raw_value=row["raw_value"],
        raw_unit=row["raw_unit"],
        lab_ref_low=_f(row["lab_ref_low"]),
        lab_ref_high=_f(row["lab_ref_high"]),
        flag=row["flag"],
    )


def list_results(conn: Conn, panel_id: int) -> list[StoredResult]:
    rows = conn.execute(
        "select * from lab_results where panel_id = %s order by marker", (panel_id,)
    ).fetchall()
    return [_result(r) for r in rows]


def lab_results_for_panel(conn: Conn, panel_id: int) -> list[LabResult]:
    """Stored rows as LabResults for evaluate. `raw` is rebuilt from the raw_* columns."""
    out: list[LabResult] = []
    for s in list_results(conn, panel_id):
        out.append(
            LabResult(
                marker=s.marker,
                value=s.value,
                unit=s.unit,
                raw=RawResult(
                    name=s.raw_name,
                    value=s.raw_value,
                    unit=s.raw_unit,
                    ref_low=None if s.lab_ref_low is None else str(s.lab_ref_low),
                    ref_high=None if s.lab_ref_high is None else str(s.lab_ref_high),
                    flag=s.flag,
                ),
                lab_ref_low=s.lab_ref_low,
                lab_ref_high=s.lab_ref_high,
            )
        )
    return out


def previous_values(conn: Conn, panel_id: int) -> dict[str, tuple[date, float]]:
    """Per marker, the value from the most recent panel strictly earlier than this one,
    ordered by (drawn_on, id)."""
    rows = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select distinct on (r.marker) r.marker, p.drawn_on, r.value
        from lab_results r
        join lab_panels p on p.id = r.panel_id
        cross join me
        where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        order by r.marker, p.drawn_on desc, p.id desc
        """,
        (panel_id,),
    ).fetchall()
    return {r["marker"]: (r["drawn_on"], float(r["value"])) for r in rows}


def marker_history(conn: Conn, marker: str) -> list[tuple[int, date, float, str]]:
    rows = conn.execute(
        """
        select p.id, p.drawn_on, r.value, r.unit
        from lab_results r join lab_panels p on p.id = r.panel_id
        where r.marker = %s
        order by p.drawn_on, p.id
        """,
        (marker,),
    ).fetchall()
    return [(int(r["id"]), r["drawn_on"], float(r["value"]), r["unit"]) for r in rows]


def insert_report(
    conn: Conn, panel_id: int, ranges_version: str, findings: list[Finding], report_md: str
) -> int:
    row = conn.execute(
        """
        insert into lab_reports (panel_id, ranges_version, findings, report_md)
        values (%s, %s, %s, %s) returning id
        """,
        (
            panel_id,
            ranges_version,
            Jsonb([f.model_dump(mode="json") for f in findings]),
            report_md,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _report(row: dict[str, Any]) -> StoredReport:
    return StoredReport(
        id=row["id"],
        panel_id=row["panel_id"],
        ranges_version=row["ranges_version"],
        findings=[Finding.model_validate(f) for f in row["findings"]],
        report_md=row["report_md"],
        created_at=row["created_at"],
    )


def get_report(conn: Conn, report_id: int) -> StoredReport | None:
    row = conn.execute("select * from lab_reports where id = %s", (report_id,)).fetchone()
    return _report(row) if row else None


def latest_report_for_panel(conn: Conn, panel_id: int) -> StoredReport | None:
    row = conn.execute(
        "select * from lab_reports where panel_id = %s order by id desc limit 1", (panel_id,)
    ).fetchone()
    return _report(row) if row else None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_repo.py -q`
Expected: 8 passed. Notes: `test_insert_panel_is_atomic_on_duplicate_marker` uses a savepoint (`conn.transaction()` inside the rolled-back fixture) so the `UniqueViolation` does not poison the fixture connection. `Finding.functional_range` and `previous` are tuples; pydantic serialises them as JSON arrays and validates them back into tuples, so equality holds.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): lab repository: panels, results, previous values, history, reports"
```

---

### Task 9: Package README, root README, docs sync

**Files:**
- Modify: `packages/tri-wellness/README.md`, `README.md`
- Copy: this plan and the spec to the vault

- [ ] **Step 1: Package README**

Replace `packages/tri-wellness/README.md` with:
```markdown
# tri-wellness

The lab interpreter: ingests the athlete's lab work from PDFs and structured exports, evaluates
every marker against the curated functional-medicine ranges in
`src/tri_wellness/ranges/markers.yaml`, and writes an interpretation grounded in the training,
sleep and recovery data tri-core syncs to Postgres. Design:
`docs/superpowers/specs/2026-09-10-tri-wellness-design.md`. Plans:
`docs/superpowers/plans/2026-09-11-tri-wellness-0*.md`.

## After Plan 1

Pure layer, no model, no commands yet:

- `ranges/markers.yaml`: 65 markers with conventional and functional ranges, aliases, unit
  conversions, athlete notes and sources. `ranges/registry.py` loads it for the configured
  `TRI_ATHLETE_SEX`, validates every rule, and builds the alias index. A bad entry fails the
  test suite naming the marker and field.
- `labs/models.py`: `RawResult` (what a lab printed), `LabResult` (canonical marker, unit and
  value), `PanelContext`, `TrainingContext`, `Finding`.
- `labs/normalize.py`: raw rows to `LabResult`s; unmapped names, unknown units, non-numeric
  values and duplicates are returned with a reason instead of being guessed.
- `labs/evaluate.py`: `Finding`s with conventional and functional status, the previous value,
  and the confounders that apply. Every threshold is a constant at the top of the module.
- `labs/training_context.py`: load, sessions, sleep and HRV around the draw date.
- `repo.py`: `lab_panels`, `lab_results`, `lab_reports` (`migrations/005_wellness.sql`).

Try the registry and evaluate without a database:

```bash
uv run python -c "
from datetime import date, time
from tri_wellness.ranges.registry import load_registry
from tri_wellness.labs.models import RawResult, PanelContext, TrainingContext
from tri_wellness.labs.normalize import normalize
from tri_wellness.labs.evaluate import evaluate
reg = load_registry('male')
rows = [RawResult(name='Ferritin, Serum', value='42', unit='ng/mL', ref_low='30', ref_high='400'),
        RawResult(name='hs-CRP', value='<0.3', unit='mg/L', ref_high='3.0'),
        RawResult(name='Glucose', value='5.2', unit='mmol/L'),
        RawResult(name='Sed Rate', value='4', unit='mm/hr')]
n = normalize(rows, reg)
print('unmapped:', [(u.raw.name, u.reason) for u in n.unmapped])
ctx = PanelContext(fasting=True, draw_time=time(7, 30))
tr = TrainingContext(drawn_on=date.today(), last_sessions=[{'date': '', 'sport': 'bike', 'duration_min': 180, 'tss': 200, 'title': 'long'}])
for f in evaluate(n.results, reg, {}, ctx, tr):
    print(f.display, f.value, f.unit, f.conventional_status, f.functional_status, f.functional_range, f.active_confounders)
"
```
```

- [ ] **Step 2: Root README**

Add to the package table (after the tri-nutrition row):
```
| `packages/tri-wellness` | `tri_wellness` | `tri-wellness ingest \| report \| chat \| panels` | Lab interpreter: PDF and export ingest with review, functional-range evaluation, written interpretation grounded in training data. |
```
Change the dependency sentence to: `` `tri-analyze`, `tri-planning`, `tri-nutrition` and `tri-wellness` depend on `tri-core`; no agent depends on another. ``

In the Layout block change the migrations line to `migrations/             001_initial.sql (sync tables), 002_planning.sql and 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables), 005_wellness.sql (lab tables)` and add after the tri-nutrition line: `packages/tri-wellness/  src/tri_wellness/{config,cli,repo,testing,ranges,labs}`.

Under Status add: `- tri-wellness milestone 1 (2026-09-11): ranges table, registry, normalize, evaluate, training context, lab tables; tracked in docs/superpowers/plans/2026-09-11-tri-wellness-0*.md.`

- [ ] **Step 3: Copy docs to the vault and commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/packages/tri-wellness $V/docs/superpowers/specs $V/docs/superpowers/plans
cp packages/tri-wellness/README.md $V/packages/tri-wellness/readme.md
cp README.md $V/readme.md
cp docs/superpowers/specs/2026-09-10-tri-wellness-design.md $V/docs/superpowers/specs/
cp docs/superpowers/plans/2026-09-11-tri-wellness-01-ranges-and-evaluate.md $V/docs/superpowers/plans/
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "docs(wellness): package README, root README, plan 1"
```

Then Brian reviews `markers.yaml` (Task 4 step 6) and merges `feat/tri-wellness-01` into `main` from the shared checkout once no other session is open.

---

## Layout after this plan

```
packages/tri-wellness/
  pyproject.toml, README.md
  src/tri_wellness/{__init__,config,cli,repo,testing}.py
  src/tri_wellness/ranges/{__init__,registry}.py, markers.yaml
  src/tri_wellness/labs/{__init__,models,normalize,evaluate,training_context}.py
  tests/{conftest,test_config,test_models,test_registry,test_markers_yaml,test_normalize,
         test_evaluate,test_training_context,test_repo}.py
  tests/fixtures/ranges/{good_sexed,bad_missing_field,bad_functional_outside,
                         bad_duplicate_alias,bad_conversion_target}.yaml
migrations/005_wellness.sql
```

Signatures the next plans call:

- Plan 2 (ingest): `normalize(raw_results, registry) -> NormalizeResult`; `repo.insert_panel(conn, *, drawn_on, lab_name, source_file, source_kind, context, raw_extract, results) -> int`; `repo.find_duplicate_panels(conn, drawn_on, lab_name)`; `load_registry(settings.tri_athlete_sex)`; `Unmapped.reason in ("unit", "value")` blocks approve.
- Plan 3 (report, chat): `evaluate(results, registry, previous, context, training)`; `repo.lab_results_for_panel`, `repo.previous_values(conn, panel_id)`, `repo.get_panel`, `repo.latest_panel_id`, `repo.list_panels`, `repo.marker_history`, `repo.insert_report`, `repo.latest_report_for_panel`; `load_training_context(conn, drawn_on)`; `registry.version` for `ranges_version`; `MarkerSpec` fields for `get_marker_spec`.

## Self-review notes

- Spec §4 layout: `config`, `repo`, `ranges/{markers.yaml,registry}`, `labs/{models,normalize,evaluate,training_context}` are here; `cli` is a stub; `repl`, `labs/extract`, `graph`, `prompts`, `tools` are Plans 2 and 3. `testing.py` is added (nutrition precedent).
- Spec §5: all three tables and both indexes (Task 1) under `005_`. `lab_results` keeps raw and canonical side by side; `previous_values` and `marker_history` read canonical values only.
- Spec §6: every model, with the listed deviations (`Unmapped`, `NormalizeResult`, stored-row types, `PanelSummary`). Status rules: both functions in Task 6 with boundary tests on both directions and the collapse rule.
- Spec §7: version, systems, sex-specific blocks, the seven code fields, every validation rule (required field, functional inside conventional, unique aliases, conversion targets, plus systems and sex blocks) each with a failing fixture; alias normalization exactly as written; the initial marker set (65: the CBC differential is five percentages; ApoB, Lp(a), reverse T3, the antibodies, RBC magnesium, omega-3 index, SHBG and DHEA-S are all present). Brian's review is Task 4 step 6.
- Spec §8: seven confounder rules, each with a boundary test; declared-only filtering; `delta_pct` and null `previous` (Task 6). Inputs are exactly the spec's five.
- Spec §14: `TRI_ATHLETE_SEX` required and validated; project name knob; `pyyaml` declared.
- Spec §15 unit list: registry validation fixtures, YAML round-trip, normalize (`<5`, unknown unit, unmapped), evaluate boundaries and confounders: covered. "Report prompt builder output" and "YAML edit round trip" are Plan 3 and Plan 2. DB tests: repo reads and writes, `marker_history` ordering, training context around a seeded draw date: Tasks 7 and 8.
- Spec §19 open items: item 3 (`sql_tool.SCHEMA_DOC` is a module constant and `make_query_tool(url)` takes no doc parameter; Plan 3 adds an `extra_doc` parameter or a wellness-side wrapper) is answered here for Plan 3. Items 1, 2 and 4 need a real panel and a real export and stay open for Plan 2 and Brian's review.
- Spec §16 observability: nothing in this plan calls a model, so no tracing tags; Plan 2 tags extraction runs, Plan 3 tags report runs.
- Type consistency: `Range`, `MarkerSpec`, `MarkerRegistry.get/lookup`, `Unmapped.reason`, `NormalizeResult.results/unmapped`, `evaluate(results, registry, previous, context, training)`, `load_training_context(conn, drawn_on)`, and the `repo` names are used with the same spellings in Tasks 5 to 9 and in the "Layout after this plan" section.
