# tri-analyze Plan 1 of 2: Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `tri-analyze` into the siblings' shape (spec milestone 1): flat layout, its own settings and LangSmith project, a system prompt rendered per model call from runtime context by `@dynamic_prompt`, a `TOOL_GUIDE` that describes every bound tool including the two the coach adds, a REPL that survives any turn failure, a `chat` that exits cleanly when the database is down, and `tri-coach` calling the analyst with `context=`. The old `agent/` sub-package and its README go; the package README, root README, `.env.example` and the old spec's status line are updated.

**Architecture:** New flat modules are added next to the old `agent/` sub-package, each with its own tests, so every commit is green. `cli.py` and then `tri-coach` switch to the new modules; the old sub-package is deleted last. `build_agent(model, tools, checkpointer)` returns `create_agent(...).with_config(tags, metadata)` with `context_schema=AthleteContext`; the `analyst_prompt` middleware renders `render_system_prompt(request.runtime.context, [bound tool names])` before each model call, so `/sync` swaps a context holder instead of rebuilding the agent. Callers pass `context=` on `invoke`, `ainvoke` and `astream`.

**Tech Stack:** langchain 1.4.0 (`create_agent`, `langchain.agents.middleware.dynamic_prompt`, `ModelRequest`), langchain-anthropic 1.7.1 (`AnthropicPromptCachingMiddleware`), langgraph `InMemorySaver`, pydantic-settings, typer, rich, psycopg 3, pytest with `tri_core.testing.ScriptedChatModel` and the rolled-back `db` fixture.

**Spec:** `docs/superpowers/specs/2026-09-13-tri-analyze-alignment-design.md` (§3 defects, §4 layout, §5 components, §6 tri-coach, §8 errors, §9 testing, §10 documentation, §11 observability, §12 milestone 1). `main` is at a0105b7. Plan 2 (`2026-09-13-tri-analyze-02-eval.md`) adds `evals/` and `tri-analyze eval` on top of this plan.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-tri-analyze-01 -b feat/tri-analyze-01 main`, `cp .env ../triathlon_agent-tri-analyze-01/.env`, then `uv sync` there. Other Claude sessions share the main checkout. Baseline before Task 1: `775 passed, 5 skipped` (all five are `--live`).
- No new dependencies in this plan (`langsmith` is added by plan 2). No edits under `packages/tri-core`, `packages/tri-planning`, `packages/tri-nutrition`, `packages/tri-wellness`. The root `pyproject.toml` is untouched. `tri_analyze/allowlist.py` is untouched.
- Tests write only through the rolled-back `db` fixture (`tri_core.testing.fixtures`); the test database starts empty for every test. No test needs an Anthropic key, LangSmith or an MCP server unless it carries the `live` marker.
- `PROMPT_VERSION = "1"` in `tri_analyze/prompts/analyst.py`.
- The exact strings the tests assert: thresholds fallback ``Athlete thresholds: not available (run `tri sync`).``; no-live sentence `No live tools are bound this session; work from the database only.`; turn failure `[the turn failed: <Type>: <message>]`; database down `database unreachable: <message>`; REPL thread id `analyze`.
- Every run of the analyst passes `context=`; a missing context is a programming error and is not defended against (spec §5.3).
- Tool order is the order passed to `build_agent`: SQL, Garmin, TrainingPeaks, then any extras. The prompt lists bound tools in that order.
- Git commits are permitted (Brian's standing permission). Commit per task on the feature branch. End every commit message with the `Co-Authored-By:` and `Claude-Session:` trailer lines of the session executing the plan.
- Definition of done per task, in order: `uv run ruff format packages/tri-analyze packages/tri-coach`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. The only acceptable pytest warning is the pre-existing langsmith `ast.Str` DeprecationWarning. Task 10 adds `uv build --package tri-analyze`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, with kebab-case names (`readme.md` for READMEs). SDD scratch (`.superpowers/`) goes to that vault's `.superpowers/sdd/<plan>/` at the end, as for earlier plans.

### Facts verified while writing this plan (against `main` a0105b7)

1. `langchain.agents.middleware` exports `dynamic_prompt`, `ModelRequest` and `AgentMiddleware`. `ModelRequest` has `model, messages, system_message, tool_choice, tools, response_format, state, runtime, model_settings`; `request.tools` items are `BaseTool` or a dict with `"name"`. `ModelRequest[AthleteContext]` types `request.runtime.context` as `AthleteContext` under `mypy --strict`; the middleware list must be annotated `list[AgentMiddleware[Any, Any, Any]]` or mypy rejects mixing `AnthropicPromptCachingMiddleware` with the typed prompt middleware.
2. `create_agent(..., context_schema=AthleteContext, checkpointer=InMemorySaver()).with_config({...})` returns a `CompiledStateGraph`; `invoke`, `ainvoke`, `astream`, `get_state` and `aget_state` all work on it. `invoke(payload, config, context=ctx)` (sync) works; without `context=` the middleware sees `None` and raises `AttributeError`.
3. Probe over `ScriptedChatModel`: two turns on one thread, `ainvoke(context=A)` then `astream(context=B, stream_mode=["messages", "updates"])`. The model saw system prompts rendered from A then B; the thread held both turns. `astream` with `"messages"` mode calls the model's `_stream`, `invoke`/`ainvoke` call `_generate`, so a recording model must override both. The system message content is a plain `str` (the caching middleware with `unsupported_model_behavior="ignore"` leaves it alone on the scripted model).
4. A `BaseCallbackHandler.on_chat_model_start(serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs)` registered via `config["callbacks"]` sees tags `["analyst", "chat", "seq:step:1"]` and metadata containing `analyst_prompt_version` on every model run, for both `ainvoke` and `astream`.
5. `tri_core.db.sql_tool.make_query_tool(url)` opens no connection at construction; its only argument is `sql`.
6. `tri_core.config.Settings` (pydantic-settings, `env_file=".env"`, `extra="ignore"`) has `anthropic_api_key`, `database_url` (default ends in `/tri_analyze`), `test_database_url`, `tri_model`, `langsmith_api_key`. `Settings(_env_file=None, ...)` skips the file.
7. `tri_coach/tools/analyst.py` imports `build_agent` from `tri_analyze.agent.agent` and `load_athlete_context, render_system_prompt` from `tri_analyze.agent.prompt`; `tri_coach/context.py` imports `load_athlete_context` from `tri_analyze.agent.prompt`. Those are the only references to `tri_analyze.agent.*` outside the package. `tri-coach`'s spec names `tri_analyze.agent.build_agent`, which is the new path, so no coach doc changes are needed. The coach's `nocommit` fixture wraps the rolled-back `db` connection; `ask_analyst`'s existing tests are `test_ask_analyst_runs_the_analyst_on_a_throwaway_thread` (db) and `test_ask_analyst_reports_a_failure_as_its_tool_result_instead_of_raising`.
8. Root `README.md` links `packages/tri-analyze/src/tri_analyze/agent/README.md` at lines 32 and 150, lists the package layout as `src/tri_analyze/{cli,allowlist,agent}` at line 142, and has the `tri-analyze` table row at line 9. `packages/tri-core/src/tri_core/{mcp,db}/README.md` also link `../agent/README.md`; those files are out of scope (spec §1, §13) and are left alone.
9. `rich.Console().print(..., style="red")` output is captured by `typer.testing.CliRunner` (`tri-wellness` relies on this).
10. The Obsidian vault already holds `packages/tri-analyze/readme.md`, `packages/tri-analyze/src/tri_analyze/agent/readme.md`, `readme.md` and `docs/superpowers/specs/2026-09-06-tri-analyze-design.md`.

## File Structure

New (all under `packages/tri-analyze/src/tri_analyze/` unless noted):

| File | Responsibility |
|---|---|
| `config.py` | `AnalyzeSettings(Settings)` with `tri_analyze_langsmith_project`; `get_analyze_settings()` |
| `llm.py` | `MAX_TOKENS`, `make_model(settings)` (moved from `agent/agent.py`) |
| `repo.py` | `AthleteContext`, `load_athlete_context(conn, today)` (moved from `agent/prompt.py`) |
| `prompts/__init__.py`, `prompts/analyst.py` | `PROMPT_VERSION`, `FEEDBACK_RULES`, `TOOL_GUIDE`, `NO_LIVE_TOOLS`, `render_system_prompt(ctx, tool_names)` |
| `agent.py` | `analyst_prompt` (`@dynamic_prompt`), `build_agent(model, tools, checkpointer=None)` |
| `tools/__init__.py`, `tools/live.py` | `open_live_tools(settings, log)` (moved from `agent/live_tools.py`) |
| `repl.py` | `text_of`, `TurnPrinter`, `run_turn`, `chat_loop` (moved from `agent/repl.py`, context-aware) |
| `testing.py` | `TODAY`, `athlete_context(**over)`, `RecordingScriptedModel`, `seed_workouts`, `seed_daily_metrics` |
| `tests/test_config.py`, `test_llm.py`, `test_repo.py`, `test_cli.py` | new test files |

Modified: `cli.py` (chat over the new modules, `LANGSMITH_PROJECT`, database-down exit), `tests/test_prompt.py`, `tests/test_agent.py`, `tests/test_repl.py`, `tests/test_live_tools.py` (rewritten against the new modules), `README.md` (package), root `README.md`, `.env.example`, `docs/superpowers/specs/2026-09-06-tri-analyze-design.md` (status line), `packages/tri-coach/src/tri_coach/tools/analyst.py`, `packages/tri-coach/src/tri_coach/context.py`, `packages/tri-coach/tests/test_tools.py`.

Deleted: `src/tri_analyze/agent/` (`__init__.py`, `agent.py`, `live_tools.py`, `prompt.py`, `repl.py`, `README.md`).

---

### Task 1: Settings with the LangSmith project

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/config.py`
- Create: `packages/tri-analyze/tests/test_config.py`
- Modify: `.env.example` (add a `# tri-analyze` block before `# tri-planning`)

**Interfaces:**
- Produces: `AnalyzeSettings(Settings)` with `tri_analyze_langsmith_project: str = "tri_analyze"`; `get_analyze_settings() -> AnalyzeSettings` (lru_cache). Tasks 7 and 10 consume these.

- [ ] **Step 1: Create the worktree and confirm the baseline**

```bash
git worktree add ../triathlon_agent-tri-analyze-01 -b feat/tri-analyze-01 main
cp .env ../triathlon_agent-tri-analyze-01/.env
cd ../triathlon_agent-tri-analyze-01 && uv sync && uv run pytest -q
```
Expected: `775 passed, 5 skipped`.

- [ ] **Step 2: Write the failing tests**

`packages/tri-analyze/tests/test_config.py`:

```python
from tri_analyze.config import AnalyzeSettings, get_analyze_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_ANALYZE_LANGSMITH_PROJECT", raising=False)
    s = AnalyzeSettings(_env_file=None)
    assert s.tri_analyze_langsmith_project == "tri_analyze"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_ANALYZE_LANGSMITH_PROJECT", "analyst-dev")
    s = AnalyzeSettings(_env_file=None)
    assert s.tri_analyze_langsmith_project == "analyst-dev"


def test_get_analyze_settings_is_cached():
    get_analyze_settings.cache_clear()
    assert get_analyze_settings() is get_analyze_settings()
    get_analyze_settings.cache_clear()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.config'`.

- [ ] **Step 4: Write the settings module**

`packages/tri-analyze/src/tri_analyze/config.py`:

```python
"""Analyst settings: everything in tri_core.config plus this agent's LangSmith project."""

from functools import lru_cache

from tri_core.config import Settings


class AnalyzeSettings(Settings):
    tri_analyze_langsmith_project: str = "tri_analyze"


@lru_cache(maxsize=1)
def get_analyze_settings() -> AnalyzeSettings:
    return AnalyzeSettings()
```

- [ ] **Step 5: Add the `.env.example` block**

Insert before the `# tri-planning` block:

```
# tri-analyze
TRI_ANALYZE_LANGSMITH_PROJECT=tri_analyze

```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_config.py -q`
Expected: `3 passed`.

- [ ] **Step 7: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/config.py packages/tri-analyze/tests/test_config.py .env.example
git commit -m "feat(analyze): AnalyzeSettings with TRI_ANALYZE_LANGSMITH_PROJECT"
```

---

### Task 2: `llm.py`, `repo.py` and `testing.py`

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/llm.py`
- Create: `packages/tri-analyze/src/tri_analyze/repo.py`
- Create: `packages/tri-analyze/src/tri_analyze/testing.py`
- Create: `packages/tri-analyze/tests/test_llm.py`
- Create: `packages/tri-analyze/tests/test_repo.py`

**Interfaces:**
- Consumes: `tri_core.config.Settings`, `tri_core.db.repo.Conn`, `tri_core.db.repo.upsert_workouts / upsert_daily_metrics`, `tri_core.db.models.WorkoutRow / DailyMetricsRow`, `tri_core.testing.ScriptedChatModel`.
- Produces: `MAX_TOKENS = 16000`; `make_model(settings: Settings) -> ChatAnthropic`; `AthleteContext(today: date, profile: dict | None, recent_days: list[dict] = [], recent_workouts: list[dict] = [])`; `load_athlete_context(conn: Conn, today: date) -> AthleteContext`; `testing.TODAY = date(2026, 9, 6)`; `testing.athlete_context(**over) -> AthleteContext`; `testing.RecordingScriptedModel(script=[...])` with `.received: list[list[BaseMessage]]`; `testing.seed_workouts(conn, rows)`, `testing.seed_daily_metrics(conn, rows)`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-analyze/tests/test_llm.py`:

```python
from tri_analyze.llm import MAX_TOKENS, make_model
from tri_core.config import Settings


def test_make_model_reads_model_and_max_tokens():
    m = make_model(Settings(_env_file=None, tri_model="claude-sonnet-5", anthropic_api_key="k"))
    assert m.model == "claude-sonnet-5"
    assert m.max_tokens == MAX_TOKENS == 16000
```

`packages/tri-analyze/tests/test_repo.py`:

```python
from datetime import date

import pytest

from tri_analyze.repo import AthleteContext, load_athlete_context
from tri_analyze.testing import TODAY, athlete_context, seed_daily_metrics, seed_workouts
from tri_core.db import repo
from tri_core.db.models import AthleteProfileRow


def test_athlete_context_fixture_and_overrides():
    ctx = athlete_context()
    assert isinstance(ctx, AthleteContext) and ctx.today == TODAY == date(2026, 9, 6)
    assert ctx.profile and ctx.profile["ftp_watts"] == 230 and ctx.profile["lthr_bpm"] == 180
    assert ctx.profile["run_threshold_pace_sec_per_km"] == 270
    assert ctx.profile["swim_css_sec_per_100m"] == 104
    assert len(ctx.recent_days) == 1 and len(ctx.recent_workouts) == 1
    assert ctx.recent_workouts[0]["title"] == "Z2 ride" and ctx.recent_workouts[0]["completed"]
    later = athlete_context(today=date(2026, 9, 7), profile=None)
    assert later.today == date(2026, 9, 7) and later.profile is None
    assert AthleteContext(today=TODAY, profile=None).recent_days == []


def _seed_profile(db):
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="1",
            ftp_watts=230,
            run_threshold_pace_sec_per_km=270,
            swim_css_sec_per_100m=104,
            lthr_bpm=180,
            max_hr_bpm=182,
            hr_zones=None,
            power_zones=None,
            pace_zones=None,
            weight_kg=None,
            raw={},
        ),
    )


@pytest.mark.db
def test_load_athlete_context_reads_profile_and_windows(db):
    _seed_profile(db)
    seed_daily_metrics(
        db,
        [
            {"metric_date": date(2026, 8, 29), "ctl": 10.0},  # 8 days back: out
            {"metric_date": date(2026, 8, 30), "ctl": 12.0},  # 7 days back: in
            {"metric_date": date(2026, 9, 5), "ctl": 15.2, "atl": 19.6, "tsb": -7.3},
            {"metric_date": date(2026, 9, 6), "ctl": 15.5},  # today: in
            {"metric_date": date(2026, 9, 7), "ctl": 16.0},  # tomorrow: out
        ],
    )
    seed_workouts(
        db,
        [
            {"tp_workout_id": "w1", "workout_date": date(2026, 8, 29), "sport": "bike", "title": "too old"},
            {"tp_workout_id": "w2", "workout_date": date(2026, 8, 30), "sport": "bike", "title": "edge back"},
            {"tp_workout_id": "w9", "workout_date": date(2026, 9, 8), "sport": "run", "title": "Tempo", "completed": False, "planned_tss": 70},
            {"tp_workout_id": "a0", "workout_date": date(2026, 9, 8), "sport": "swim", "title": "same day, lower id", "completed": False},
            {"tp_workout_id": "w3", "workout_date": date(2026, 9, 13), "sport": "swim", "title": "edge forward", "completed": False},
            {"tp_workout_id": "w4", "workout_date": date(2026, 9, 14), "sport": "swim", "title": "too far", "completed": False},
        ],
    )
    ctx = load_athlete_context(db, TODAY)
    assert ctx.today == TODAY
    assert ctx.profile and ctx.profile["ftp_watts"] == 230 and ctx.profile["weight_kg"] is None
    assert [d["metric_date"] for d in ctx.recent_days] == [
        date(2026, 8, 30),
        date(2026, 9, 5),
        date(2026, 9, 6),
    ]
    assert ctx.recent_days[1]["tsb"] == -7.3
    assert [(w["workout_date"], w["title"]) for w in ctx.recent_workouts] == [
        (date(2026, 8, 30), "edge back"),
        (date(2026, 9, 8), "same day, lower id"),  # ordered by date, then tp_workout_id
        (date(2026, 9, 8), "Tempo"),
        (date(2026, 9, 13), "edge forward"),
    ]
    assert ctx.recent_workouts[2]["planned_tss"] == 70 and ctx.recent_workouts[2]["completed"] is False


@pytest.mark.db
def test_load_athlete_context_with_empty_tables(db):
    ctx = load_athlete_context(db, TODAY)
    assert ctx.profile is None and ctx.recent_days == [] and ctx.recent_workouts == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_llm.py packages/tri-analyze/tests/test_repo.py -q`
Expected: FAIL with `ModuleNotFoundError` for `tri_analyze.llm` and `tri_analyze.repo`.

- [ ] **Step 3: Write `llm.py`**

`packages/tri-analyze/src/tri_analyze/llm.py`:

```python
"""Model construction."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    """Claude via LangChain. No `thinking` kwarg: adaptive thinking is the model default."""
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
```

- [ ] **Step 4: Write `repo.py`**

`packages/tri-analyze/src/tri_analyze/repo.py`:

```python
"""The athlete context: thresholds, the last seven days of load and recovery, and the workouts
one week either side of today. Passed to every analyst run as its runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn


@dataclass
class AthleteContext:
    today: date
    profile: dict[str, Any] | None
    recent_days: list[dict[str, Any]] = field(default_factory=list)
    recent_workouts: list[dict[str, Any]] = field(default_factory=list)


def load_athlete_context(conn: Conn, today: date) -> AthleteContext:
    profile = conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, weight_kg from athlete_profile where id = 1"
    ).fetchone()
    days = conn.execute(
        "select metric_date, tss_day, ctl, atl, tsb, sleep_score, hrv_overnight_avg, "
        "resting_hr, training_readiness from daily_metrics "
        "where metric_date between %s and %s order by metric_date",
        (today - timedelta(days=7), today),
    ).fetchall()
    workouts = conn.execute(
        "select workout_date, sport, title, completed, planned_tss, actual_tss, "
        "planned_duration_sec, actual_duration_sec from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (today - timedelta(days=7), today + timedelta(days=7)),
    ).fetchall()
    return AthleteContext(today=today, profile=profile, recent_days=days, recent_workouts=workouts)
```

- [ ] **Step 5: Write `testing.py`**

`packages/tri-analyze/src/tri_analyze/testing.py`:

```python
"""Test doubles and SQL seeds for the analyst package. Imported by tests only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from tri_analyze.repo import AthleteContext
from tri_core.db.models import DailyMetricsRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_daily_metrics, upsert_workouts
from tri_core.testing import ScriptedChatModel

TODAY = date(2026, 9, 6)


def athlete_context(**over: Any) -> AthleteContext:
    """The prompt fixture: FTP 230, LTHR 180, run threshold 4:30/km, CSS 1:44/100m, one day of
    metrics and one completed Z2 ride. Keyword overrides replace whole fields."""
    base: dict[str, Any] = {
        "today": TODAY,
        "profile": {
            "ftp_watts": 230,
            "lthr_bpm": 180,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 104,
            "max_hr_bpm": 182,
        },
        "recent_days": [
            {
                "metric_date": date(2026, 9, 5),
                "tss_day": 55,
                "ctl": 15.2,
                "atl": 19.6,
                "tsb": -7.3,
                "sleep_score": 79,
                "hrv_overnight_avg": 71,
                "training_readiness": 51,
            }
        ],
        "recent_workouts": [
            {
                "workout_date": date(2026, 9, 5),
                "sport": "bike",
                "title": "Z2 ride",
                "completed": True,
                "planned_tss": 60,
                "actual_tss": 55,
            }
        ],
    }
    base.update(over)
    return AthleteContext(**base)


class RecordingScriptedModel(ScriptedChatModel):
    """ScriptedChatModel that keeps every message list it received, for invoke and stream."""

    received: list[list[BaseMessage]] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received = [*self.received, list(messages)]
        return super()._generate(messages, stop, run_manager, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self.received = [*self.received, list(messages)]
        yield from super()._stream(messages, stop, run_manager, **kwargs)


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, and optional title, planned_tss,
    planned_duration_sec, actual_duration_sec, actual_tss, completed (default True)."""
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

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_llm.py packages/tri-analyze/tests/test_repo.py -q`
Expected: `4 passed` (the two `db` tests skip only when Postgres is down; on Brian's machine they run).

- [ ] **Step 7: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/llm.py packages/tri-analyze/src/tri_analyze/repo.py packages/tri-analyze/src/tri_analyze/testing.py packages/tri-analyze/tests/test_llm.py packages/tri-analyze/tests/test_repo.py
git commit -m "feat(analyze): llm, repo and testing modules in the flat layout"
```

---

### Task 3: The prompt module with `TOOL_GUIDE` and the `tri sync` fix

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/prompts/__init__.py` (empty)
- Create: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py`
- Rewrite: `packages/tri-analyze/tests/test_prompt.py`

**Interfaces:**
- Consumes: `tri_analyze.repo.AthleteContext`, `tri_analyze.testing.athlete_context`, `tri_analyze.allowlist.GARMIN_LIVE_TOOLS / TP_LIVE_TOOLS`.
- Produces: `PROMPT_VERSION = "1"`; `FEEDBACK_RULES: str`; `TOOL_GUIDE: dict[str, str]` (eight entries); `NO_LIVE_TOOLS: str`; `render_system_prompt(ctx: AthleteContext, tool_names: list[str]) -> str`. Tasks 4, 7 and plan 2 consume these.

- [ ] **Step 1: Write the failing tests**

Replace `packages/tri-analyze/tests/test_prompt.py` with:

```python
from datetime import date

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.prompts.analyst import (
    FEEDBACK_RULES,
    NO_LIVE_TOOLS,
    PROMPT_VERSION,
    TOOL_GUIDE,
    render_system_prompt,
)
from tri_analyze.testing import athlete_context

STANDALONE = ["query_training_db", *GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
COACH_EXTRAS = ["read_body_composition", "read_intake_vs_targets"]


def test_render_includes_profile_load_and_tools():
    text = render_system_prompt(athlete_context(), ["query_training_db", "get_activity_splits"])
    assert "Today is 2026-09-06." in text
    assert "FTP 230 W" in text and "4:30/km" in text and "1:44/100m" in text
    assert "LTHR 180 bpm, max HR 182 bpm" in text
    assert "CTL 15.2" in text and "TSB -7.3" in text and "readiness 51" in text
    assert "2026-09-05 bike: Z2 ride [done] 60 -> 55" in text
    assert "Tools bound this session: query_training_db, get_activity_splits." in text


def test_render_marks_done_planned_and_missed():
    workouts = [
        {"workout_date": date(2026, 9, 4), "sport": "swim", "title": "Drills", "completed": False, "planned_tss": 30, "actual_tss": None},
        {"workout_date": date(2026, 9, 5), "sport": "bike", "title": "Z2 ride", "completed": True, "planned_tss": 60, "actual_tss": 55},
        {"workout_date": date(2026, 9, 6), "sport": "run", "title": None, "completed": False, "planned_tss": 40, "actual_tss": None},
        {"workout_date": date(2026, 9, 8), "sport": "run", "title": "Tempo", "completed": False, "planned_tss": 70, "actual_tss": None},
    ]
    text = render_system_prompt(athlete_context(recent_workouts=workouts), [])
    assert "2026-09-04 swim: Drills [missed] 30 -> -" in text
    assert "2026-09-05 bike: Z2 ride [done] 60 -> 55" in text
    assert "2026-09-06 run: (untitled) [planned] 40 -> -" in text  # today counts as planned
    assert "2026-09-08 run: Tempo [planned] 70 -> -" in text


def test_render_without_profile_or_data_hints_tri_sync():
    text = render_system_prompt(
        athlete_context(profile=None, recent_days=[], recent_workouts=[]), ["query_training_db"]
    )
    assert "Athlete thresholds: not available (run `tri sync`)." in text
    assert "tri-analyze sync" not in text
    assert "Recent load: not available." in text
    assert "Recent and upcoming workouts: not available." in text


def test_no_live_sentence_only_when_sql_alone_is_bound():
    assert NO_LIVE_TOOLS in render_system_prompt(athlete_context(), ["query_training_db"])
    assert NO_LIVE_TOOLS in render_system_prompt(athlete_context(), [])
    assert "Tools bound this session: none." in render_system_prompt(athlete_context(), [])
    with_live = render_system_prompt(athlete_context(), ["query_training_db", "get_hrv_data"])
    assert NO_LIVE_TOOLS not in with_live


def test_guide_lines_only_for_bound_tools_including_coach_extras():
    bound = ["query_training_db", "get_activity_splits", "read_body_composition"]
    text = render_system_prompt(athlete_context(), bound)
    assert (
        "Tools bound this session: query_training_db, get_activity_splits, read_body_composition."
        in text
    )
    for name in bound:
        assert f"- {name}: {TOOL_GUIDE[name]}" in text, name
    for name in ("get_training_readiness", "get_hrv_data", "tp_get_workout", "read_intake_vs_targets"):
        assert name not in text, name
    assert "- get_activity:" not in text  # a prefix of a bound name, not bound itself


def test_guide_lines_follow_bound_order():
    text = render_system_prompt(athlete_context(), ["tp_get_workout", "query_training_db"])
    assert text.index("- tp_get_workout:") < text.index("- query_training_db:")


def test_unknown_bound_tool_is_listed_without_a_guide_line():
    text = render_system_prompt(athlete_context(), ["query_training_db", "mystery_tool"])
    assert "Tools bound this session: query_training_db, mystery_tool." in text
    assert "- mystery_tool:" not in text
    assert "- query_training_db:" in text


def test_every_allow_listed_and_coach_tool_has_a_guide_entry():
    for name in STANDALONE + COACH_EXTRAS:
        assert name in TOOL_GUIDE, name
    assert set(TOOL_GUIDE) == set(STANDALONE + COACH_EXTRAS)
    assert "workouts.garmin_activity_id" in TOOL_GUIDE["get_activity_splits"]
    assert "days" in TOOL_GUIDE["read_body_composition"]


def test_render_feedback_rules_present_and_version_is_1():
    text = render_system_prompt(athlete_context(), [])
    assert FEEDBACK_RULES in text
    for phrase in ("planned vs", "zones", "CTL/ATL/TSB", "takeaway", "SQL"):
        assert phrase.lower() in text.lower(), phrase
    assert PROMPT_VERSION == "1"


def test_render_is_deterministic_and_pure():
    ctx = athlete_context()
    first = render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(athlete_context(), list(STANDALONE))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.prompts'`.

- [ ] **Step 3: Write the prompt module**

Create an empty `packages/tri-analyze/src/tri_analyze/prompts/__init__.py`, then `packages/tri-analyze/src/tri_analyze/prompts/analyst.py`:

```python
"""The analyst's system prompt, rendered from the athlete context and the names of the bound
tools. A pure function of its arguments: equal inputs give equal bytes, which is what Anthropic's
prompt cache matches on."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_analyze.repo import AthleteContext

# Bump whenever the prompt text changes; names the eval experiment analyst-v<N>.
PROMPT_VERSION = "1"

TOOL_GUIDE: dict[str, str] = {
    "query_training_db": (
        "anything already synced: workouts, planned vs actual, weekly volume, CTL/ATL/TSB, "
        "sleep, HRV, readiness, thresholds and zones. Prefer it over live tools for synced data."
    ),
    "get_activity_splits": (
        "lap and interval detail for one activity; activity_id is workouts.garmin_activity_id."
    ),
    "get_activity": "a Garmin activity summary; activity_id is workouts.garmin_activity_id.",
    "get_training_readiness": "Garmin readiness for a date not yet synced, such as today.",
    "get_hrv_data": "overnight HRV for a date not yet synced, such as today.",
    "tp_get_workout": "the coach's structured plan and comments for one session.",
    "read_body_composition": (
        "index-scale weight, body fat and muscle mass over the last `days` days."
    ),
    "read_intake_vs_targets": (
        "logged intake against the nutrition targets over the last `days` days."
    ),
}

NO_LIVE_TOOLS = "No live tools are bound this session; work from the database only."

FEEDBACK_RULES = """\
How to give feedback on a completed session:
1. Planned vs actual: duration, distance, TSS, intensity factor; was the structure executed?
2. Execution quality: time in zones versus the session's intent, HR drift or decoupling on
   steady work, pacing consistency across intervals (pull laps when it matters).
3. Context: where the session sits in the week and against the current CTL/ATL/TSB; sleep,
   HRV and readiness going in.
4. The athlete's own comments, feeling and RPE when present.
5. One or two concrete takeaways for the next similar session. No generic encouragement.

For trend questions: compute with SQL (group by week, averages, sums), state the date window
you used, and say when data is missing rather than guessing. Distances are metres, durations
seconds, paces derive from those. Today is the reference for "this week" and "yesterday"."""


def _pace(sec: Any, unit: str) -> str:
    if sec is None:
        return "n/a"
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}{unit}"


def _num(v: Any, nd: int = 1) -> str:
    if v is None:
        return "-"
    return f"{float(v):.{nd}f}" if nd else str(int(round(float(v))))


def _profile_block(p: dict[str, Any] | None) -> str:
    if not p:
        return "Athlete thresholds: not available (run `tri sync`)."
    return (
        "Athlete thresholds (from TrainingPeaks):\n"
        f"- FTP {p.get('ftp_watts') or 'n/a'} W\n"
        f"- Run threshold pace {_pace(p.get('run_threshold_pace_sec_per_km'), '/km')}\n"
        f"- Swim CSS {_pace(p.get('swim_css_sec_per_100m'), '/100m')}\n"
        f"- LTHR {p.get('lthr_bpm') or 'n/a'} bpm, max HR {p.get('max_hr_bpm') or 'n/a'} bpm\n"
        "Zone tables are in athlete_profile.hr_zones / power_zones / pace_zones (jsonb)."
    )


def _days_block(days: list[dict[str, Any]]) -> str:
    if not days:
        return "Recent load: not available."
    lines = ["Recent load and recovery (last 7 days):"]
    for d in days:
        lines.append(
            f"- {d['metric_date']}: TSS {_num(d.get('tss_day'), 0)}, CTL {_num(d.get('ctl'))}, "
            f"ATL {_num(d.get('atl'))}, TSB {_num(d.get('tsb'))}, "
            f"sleep {_num(d.get('sleep_score'), 0)}, HRV {_num(d.get('hrv_overnight_avg'), 0)}, "
            f"readiness {_num(d.get('training_readiness'), 0)}"
        )
    return "\n".join(lines)


def _workouts_block(ws: list[dict[str, Any]], today: date) -> str:
    if not ws:
        return "Recent and upcoming workouts: not available."
    lines = ["Workouts, last 7 days and next 7 days (planned TSS -> actual TSS):"]
    for w in ws:
        if w.get("completed"):
            marker = "done"
        elif w["workout_date"] >= today:
            marker = "planned"
        else:
            marker = "missed"
        lines.append(
            f"- {w['workout_date']} {w['sport']}: {w.get('title') or '(untitled)'} "
            f"[{marker}] {_num(w.get('planned_tss'), 0)} -> {_num(w.get('actual_tss'), 0)}"
        )
    return "\n".join(lines)


def _tools_block(tool_names: list[str]) -> str:
    lines = ["Tools bound this session: " + (", ".join(tool_names) or "none") + "."]
    guided = [name for name in tool_names if name in TOOL_GUIDE]
    if guided:
        lines.append("What each is for:")
        lines += [f"- {name}: {TOOL_GUIDE[name]}" for name in guided]
    if all(name == "query_training_db" for name in tool_names):
        lines.append(NO_LIVE_TOOLS)
    return "\n".join(lines)


def render_system_prompt(ctx: AthleteContext, tool_names: list[str]) -> str:
    """Role, today, thresholds, recent load, workouts, tools, rules. `tool_names` is the bound
    list in bound order; every name is listed, and the guide line is added for names it knows."""
    return "\n\n".join(
        [
            "You are a triathlon coach's analyst. You answer questions about one athlete's "
            "training using the query_training_db tool (Postgres, read-only) and the other "
            "tools listed below. Be specific and quantitative. Use the athlete's thresholds to "
            "interpret intensity.",
            f"Today is {ctx.today.isoformat()}.",
            _profile_block(ctx.profile),
            _days_block(ctx.recent_days),
            _workouts_block(ctx.recent_workouts, ctx.today),
            _tools_block(tool_names),
            FEEDBACK_RULES,
        ]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Definition of done, then commit**

The old `agent/prompt.py` still exists and is still imported by `cli.py` and `tri-coach`; it is removed in Task 9.

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/prompts packages/tri-analyze/tests/test_prompt.py
git commit -m "feat(analyze): prompts/analyst with PROMPT_VERSION, TOOL_GUIDE and the tri sync hint"
```

---

### Task 4: `agent.py` with `@dynamic_prompt` and the run config

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/agent.py`
- Rewrite: `packages/tri-analyze/tests/test_agent.py`

**Interfaces:**
- Consumes: `render_system_prompt`, `PROMPT_VERSION` (Task 3), `AthleteContext` (Task 2), `RecordingScriptedModel`, `athlete_context` (Task 2).
- Produces: `analyst_prompt` (an `AgentMiddleware`); `build_agent(model: BaseChatModel, tools: Sequence[BaseTool], checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any`. Every call on the returned graph must pass `context=<AthleteContext>`. Tasks 6, 7, 8 and plan 2 consume this.

- [ ] **Step 1: Write the failing tests**

Replace `packages/tri-analyze/tests/test_agent.py` with:

```python
from datetime import date

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.agent import build_agent
from tri_analyze.prompts.analyst import PROMPT_VERSION, render_system_prompt
from tri_analyze.testing import RecordingScriptedModel, athlete_context
from tri_core.testing import ScriptedChatModel, tool_call


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def mul(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


CTX = athlete_context()


def cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def test_agent_runs_tool_loop_and_stops():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add])
    out = agent.invoke({"messages": [HumanMessage("add 2 and 3")]}, cfg("t1"), context=CTX)
    msgs = out["messages"]
    assert [type(m).__name__ for m in msgs] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    assert isinstance(msgs[2], ToolMessage) and msgs[2].content == "5"
    assert msgs[-1].content == "It is 5."
    assert model.calls == 2


def test_agent_remembers_across_turns_on_same_thread():
    model = ScriptedChatModel(script=[AIMessage(content="hi"), AIMessage(content="again")])
    saver = InMemorySaver()
    agent = build_agent(model, [add], checkpointer=saver)
    agent.invoke({"messages": [HumanMessage("one")]}, cfg("t2"), context=CTX)
    agent.invoke({"messages": [HumanMessage("two")]}, cfg("t2"), context=CTX)
    state = agent.get_state(cfg("t2")).values["messages"]
    assert [m.content for m in state] == ["one", "hi", "two", "again"]


def test_agent_threads_are_isolated():
    model = ScriptedChatModel(script=[AIMessage(content="a"), AIMessage(content="b")])
    agent = build_agent(model, [add])
    agent.invoke({"messages": [HumanMessage("x")]}, cfg("A"), context=CTX)
    agent.invoke({"messages": [HumanMessage("y")]}, cfg("B"), context=CTX)
    assert len(agent.get_state(cfg("B")).values["messages"]) == 2


def test_model_sees_the_prompt_rendered_from_the_context_and_bound_tools():
    model = RecordingScriptedModel(script=[AIMessage(content="hi")])
    agent = build_agent(model, [add, mul])
    agent.invoke({"messages": [HumanMessage("x")]}, cfg("t"), context=CTX)
    system = model.received[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == render_system_prompt(CTX, ["add", "mul"])
    assert "Tools bound this session: add, mul." in system.content


def test_a_new_context_changes_the_prompt_and_keeps_the_history():
    model = RecordingScriptedModel(script=[AIMessage(content="a"), AIMessage(content="b")])
    agent = build_agent(model, [add])
    agent.invoke({"messages": [HumanMessage("one")]}, cfg("t"), context=CTX)
    later = athlete_context(today=date(2026, 9, 7))
    agent.invoke({"messages": [HumanMessage("two")]}, cfg("t"), context=later)
    assert "Today is 2026-09-06." in model.received[0][0].content
    assert "Today is 2026-09-07." in model.received[1][0].content
    assert [m.content for m in model.received[1][1:]] == ["one", "a", "two"]
    assert [m.content for m in agent.get_state(cfg("t")).values["messages"]] == [
        "one",
        "a",
        "two",
        "b",
    ]


def test_tool_order_is_preserved_in_the_prompt():
    model = RecordingScriptedModel(script=[AIMessage(content="x")])
    build_agent(model, [mul, add]).invoke({"messages": [HumanMessage("x")]}, cfg("t"), context=CTX)
    assert "Tools bound this session: mul, add." in model.received[0][0].content


async def test_analyst_tag_and_prompt_version_reach_the_model_run():
    class Spy(BaseCallbackHandler):
        def __init__(self) -> None:
            self.tags: list[list[str]] = []
            self.metadata: list[dict] = []

        def on_chat_model_start(self, serialized, messages, *, tags=None, metadata=None, **kw):
            self.tags.append(list(tags or []))
            self.metadata.append(dict(metadata or {}))

    spy = Spy()
    model = ScriptedChatModel(script=[AIMessage(content="x")])
    agent = build_agent(model, [add])
    await agent.ainvoke(
        {"messages": [HumanMessage("x")]},
        {**cfg("t"), "tags": ["chat"], "callbacks": [spy]},
        context=CTX,
    )
    assert spy.tags and "analyst" in spy.tags[0] and "chat" in spy.tags[0]
    assert spy.metadata[0]["analyst_prompt_version"] == PROMPT_VERSION
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_agent.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_agent' from 'tri_analyze.agent'` (the name resolves to the old sub-package `agent/__init__.py`, which is empty).

- [ ] **Step 3: Write `agent.py`**

`packages/tri-analyze/src/tri_analyze/agent.py`:

```python
"""The analyst agent: a model-and-tools loop whose system prompt is rendered before each model
call from the athlete context passed as runtime context and the names of the bound tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, dynamic_prompt
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.prompts.analyst import PROMPT_VERSION, render_system_prompt
from tri_analyze.repo import AthleteContext


@dynamic_prompt
def analyst_prompt(request: ModelRequest[AthleteContext]) -> str:
    """Render the system prompt from the run's context and the tools bound to this request."""
    names = [t.name if isinstance(t, BaseTool) else str(t["name"]) for t in request.tools]
    return render_system_prompt(request.runtime.context, names)


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools. Every run must pass
    `context=<AthleteContext>`. The prompt middleware runs first so the caching middleware marks
    the rendered system prompt; tool order is the order given, which keeps the cached prefix
    stable. Runs carry the `analyst` tag and the prompt version as metadata."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        analyst_prompt,
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
    ]
    agent = create_agent(
        model,
        list(tools),
        middleware=middleware,
        context_schema=AthleteContext,
        checkpointer=checkpointer or InMemorySaver(),
    )
    return agent.with_config(
        {"tags": ["analyst"], "metadata": {"analyst_prompt_version": PROMPT_VERSION}}
    )
```

- [ ] **Step 4: Resolve the module-versus-package name clash**

`tri_analyze/agent.py` and `tri_analyze/agent/` cannot coexist: Python imports the package. Rename the old sub-package for the rest of this plan:

```bash
git mv packages/tri-analyze/src/tri_analyze/agent packages/tri-analyze/src/tri_analyze/_old_agent
```

Then update the four remaining importers of the old path so they keep working until Tasks 7 and 8 replace them:

- `packages/tri-analyze/src/tri_analyze/cli.py` lines 45 to 48: `tri_analyze.agent.agent` -> `tri_analyze._old_agent.agent`, `tri_analyze.agent.live_tools` -> `tri_analyze._old_agent.live_tools`, `tri_analyze.agent.prompt` -> `tri_analyze._old_agent.prompt`, `tri_analyze.agent.repl` -> `tri_analyze._old_agent.repl`.
- `packages/tri-analyze/tests/test_repl.py` lines 6 and 7 and `tests/test_live_tools.py` line 3: same substitution.
- `packages/tri-coach/src/tri_coach/tools/analyst.py` lines 19 and 20 and `packages/tri-coach/src/tri_coach/context.py` line 12: same substitution.

Run: `grep -rn "tri_analyze\.agent\." packages --include='*.py'`
Expected: no output.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze packages/tri-coach -q`
Expected: all pass; `test_agent.py` reports `7 passed`.

- [ ] **Step 6: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A packages/tri-analyze packages/tri-coach
git commit -m "feat(analyze): build_agent renders the prompt per call from runtime context; analyst tag and prompt version on every run"
```

---

### Task 5: `tools/live.py`

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/tools/__init__.py` (empty)
- Create: `packages/tri-analyze/src/tri_analyze/tools/live.py`
- Rewrite: `packages/tri-analyze/tests/test_live_tools.py`

**Interfaces:**
- Consumes: `tri_analyze.allowlist`, `tri_core.mcp.live_tools.open_live_tools`, `tri_core.mcp.servers.garmin_spec / trainingpeaks_spec`.
- Produces: `open_live_tools(settings: Settings, log: Callable[[str], None]) -> AsyncIterator[list[BaseTool]]` (async context manager). Task 7 consumes it.

- [ ] **Step 1: Write the failing tests**

Replace `packages/tri-analyze/tests/test_live_tools.py` with:

```python
import pytest

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.tools.live import open_live_tools
from tri_core.config import Settings


def test_allowlists_are_read_only_tools():
    for name in GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS:
        assert name.startswith(("get_", "tp_get_"))


@pytest.mark.live
async def test_live_tools_bind_expected_names():
    async with open_live_tools(Settings(), print) as tools:
        names = [t.name for t in tools]
        assert names == GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS
        readiness = next(t for t in tools if t.name == "get_training_readiness")
        text = await readiness.ainvoke({"date": "2026-09-06"})
        assert "score" in str(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_live_tools.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.tools'`.

- [ ] **Step 3: Write the module**

Create an empty `packages/tri-analyze/src/tri_analyze/tools/__init__.py`, then `packages/tri-analyze/src/tri_analyze/tools/live.py`:

```python
"""The analyst's live tools: the shared MCP opener with this agent's allow-lists."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_core.config import Settings
from tri_core.mcp.live_tools import open_live_tools as _open
from tri_core.mcp.servers import ServerSpec, garmin_spec, trainingpeaks_spec


@asynccontextmanager
async def open_live_tools(
    settings: Settings, log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    specs: dict[str, tuple[ServerSpec, Sequence[str]]] = {
        "garmin": (garmin_spec(settings), GARMIN_LIVE_TOOLS),
        "trainingpeaks": (trainingpeaks_spec(settings), TP_LIVE_TOOLS),
    }
    async with _open(specs, log) as tools:
        yield tools
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_live_tools.py -q`
Expected: `1 passed, 1 skipped` (the live test needs `--live`).

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/tools packages/tri-analyze/tests/test_live_tools.py
git commit -m "feat(analyze): tools/live in the flat layout"
```

---

### Task 6: `repl.py` with context per turn and a catch-all

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/repl.py`
- Rewrite: `packages/tri-analyze/tests/test_repl.py`

**Interfaces:**
- Consumes: `AthleteContext` (Task 2), `build_agent` (Task 4) in tests.
- Produces: `text_of(msg: BaseMessage) -> str`; `TurnPrinter(out)` with `.on_event(mode, data)` and `.final_text`; `run_turn(agent, text, thread_id, out, *, context: AthleteContext, tags: list[str] | None = None) -> str`; `chat_loop(agent, *, read, out, context: Callable[[], AthleteContext], thread_id: str = "analyze", commands: dict[str, Command] | None = None) -> None` where `Command = Callable[[], Awaitable[str]]`. Task 7 and plan 2 (`text_of`) consume these.

- [ ] **Step 1: Write the failing tests**

Replace `packages/tri-analyze/tests/test_repl.py` with:

```python
from datetime import date

import anthropic
import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from tri_analyze.agent import build_agent
from tri_analyze.repl import TurnPrinter, chat_loop, run_turn, text_of
from tri_analyze.testing import athlete_context
from tri_core.testing import ScriptedChatModel, tool_call

CTX = athlete_context()


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def _capture():
    buf: list[str] = []
    return buf, buf.append


class FakeAgent:
    """Records what run_turn hands to astream and answers with one final message."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def astream(self, payload, config=None, stream_mode=None, context=None):
        self.calls.append((payload, config, stream_mode, context))
        yield ("updates", {"model": {"messages": [AIMessage(content="ok")]}})


async def test_run_turn_streams_text_and_shows_tool_calls():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add])
    buf, out = _capture()
    final = await run_turn(agent, "add 2 and 3", "t", out, context=CTX)
    text = "".join(buf)
    assert final == "It is 5."
    assert "→ add({'a': 2, 'b': 3})" in text
    assert "← add: 1 chars" in text
    assert text.rstrip().endswith("It is 5.")


async def test_run_turn_passes_context_tags_thread_and_stream_modes():
    fake = FakeAgent()
    buf, out = _capture()
    final = await run_turn(fake, "hi", "t9", out, context=CTX, tags=["chat"])
    assert final == "ok"
    payload, config, mode, context = fake.calls[0]
    assert payload["messages"][0].content == "hi"
    assert config["configurable"]["thread_id"] == "t9" and config["tags"] == ["chat"]
    assert mode == ["messages", "updates"] and context is CTX
    await run_turn(fake, "again", "t9", out, context=CTX)
    assert "tags" not in fake.calls[1][1]


async def test_run_turn_reports_api_errors_without_raising():
    class Boom(ScriptedChatModel):
        def _stream(self, *a, **k):
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.com")
            )

    agent = build_agent(Boom(script=[]), [add])
    buf, out = _capture()
    final = await run_turn(agent, "hi", "t", out, context=CTX)
    assert final == ""
    assert any("connection" in s.lower() for s in buf)


async def test_run_turn_reports_any_other_exception_and_returns():
    class Boom(ScriptedChatModel):
        def _stream(self, *a, **k):
            raise RuntimeError("kaboom")

    agent = build_agent(Boom(script=[]), [add])
    buf, out = _capture()
    final = await run_turn(agent, "hi", "t", out, context=CTX)
    assert final == ""
    assert "[the turn failed: RuntimeError: kaboom]" in "".join(buf)


async def test_chat_loop_reads_the_context_holder_before_each_turn():
    fake = FakeAgent()
    holder = [athlete_context()]
    lines = iter(["one", "/sync", "two"])

    async def read():
        return next(lines, None)

    async def sync():
        holder[0] = athlete_context(today=date(2026, 9, 7))
        return "context swapped"

    buf, out = _capture()
    await chat_loop(fake, read=read, out=out, context=lambda: holder[0], commands={"sync": sync})
    assert [c[3].today for c in fake.calls] == [date(2026, 9, 6), date(2026, 9, 7)]
    assert all(c[1]["tags"] == ["chat"] for c in fake.calls)
    assert all(c[1]["configurable"]["thread_id"] == "analyze" for c in fake.calls)
    assert "context swapped" in "".join(buf)


async def test_chat_loop_runs_commands_and_quits():
    model = ScriptedChatModel(script=[AIMessage(content="hello")])
    agent = build_agent(model, [add])
    inputs = iter(["/tools", "hi there", "/quit", "never read"])

    async def read():
        return next(inputs, None)

    buf, out = _capture()

    async def tools_cmd():
        return "tools: add"

    await chat_loop(agent, read=read, out=out, context=lambda: CTX, commands={"tools": tools_cmd})
    text = "".join(buf)
    assert "tri-analyze chat" in text and "/quit" in text and "tools" in text
    assert "tools: add" in text
    assert "hello" in text
    assert model.calls == 1


async def test_chat_loop_handles_eof_and_unknown_command():
    agent = build_agent(ScriptedChatModel(script=[]), [add])
    inputs = iter(["/nope", "   "])

    async def read():
        return next(inputs, None)

    buf, out = _capture()
    await chat_loop(agent, read=read, out=out, context=lambda: CTX)
    assert any("unknown command: /nope" in s for s in buf)


def test_turn_printer_ignores_non_text_chunks_and_text_of_reads_blocks():
    p = TurnPrinter(lambda s: None)
    p.on_event(
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert p.final_text == "x"
    assert text_of(AIMessage(content=[{"type": "text", "text": "a"}, "b"])) == "ab"
    assert text_of(AIMessage(content="plain")) == "plain"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_repl.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.repl'`.

- [ ] **Step 3: Write `repl.py`**

`packages/tri-analyze/src/tri_analyze/repl.py`:

```python
"""Terminal REPL: stream a turn, show tool calls, loop.

`stream_mode=["messages", "updates"]` yields ("messages", (chunk, meta)) for token-level output
and ("updates", {node: {...}}) when a node finishes. Tool calls are visible in the model node's
update; tool results arrive as ToolMessages from the tools node.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from tri_analyze.repo import AthleteContext

Out = Callable[[str], None]
Command = Callable[[], Awaitable[str]]


def text_of(msg: BaseMessage) -> str:
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
    """Renders agent stream events to `out`. Text streams inline; tool activity gets lines."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""

    def on_event(self, mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode == "updates":
            for node, payload in data.items():
                for msg in (payload or {}).get("messages", []):
                    if node == "model" and isinstance(msg, AIMessage):
                        for tc in msg.tool_calls:
                            self.out(f"\n→ {tc['name']}({tc['args']})\n")
                        if not msg.tool_calls:
                            # the update carries the whole final message; prefer it to the
                            # accumulated chunks, which may include text from earlier tool turns
                            self.final_text = text_of(msg) or self.final_text
                            self.out("\n")
                    elif node == "tools" and isinstance(msg, ToolMessage):
                        self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")


async def run_turn(
    agent: Any,
    text: str,
    thread_id: str,
    out: Out,
    *,
    context: AthleteContext,
    tags: list[str] | None = None,
) -> str:
    """One turn: stream the agent, print as it goes, return the final text. Anthropic errors and
    any other failure are printed; the loop continues and the thread keeps its last checkpoint."""
    printer = TurnPrinter(out)
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if tags:
        cfg["tags"] = list(tags)
    try:
        async for mode, data in agent.astream(
            {"messages": [HumanMessage(text)]},
            config=cfg,
            stream_mode=["messages", "updates"],
            context=context,
        ):
            printer.on_event(mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    except Exception as exc:
        out(f"\n[the turn failed: {type(exc).__name__}: {exc}]\n")
    return printer.final_text


async def chat_loop(
    agent: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    context: Callable[[], AthleteContext],
    thread_id: str = "analyze",
    commands: dict[str, Command] | None = None,
) -> None:
    """Read lines until EOF or /quit. `context()` is called before each turn, so a command that
    replaces what it returns (such as /sync) changes the next turn's prompt."""
    commands = dict(commands or {})
    out(
        "tri-analyze chat. Type a question, /quit to exit, /<command> for: "
        + ", ".join(sorted(["quit", *commands]))
        + "\n"
    )
    while True:
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
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        await run_turn(agent, line, thread_id, out, context=context(), tags=["chat"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_repl.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/repl.py packages/tri-analyze/tests/test_repl.py
git commit -m "feat(analyze): repl passes the context per turn, tags chat turns, and survives any turn failure"
```

---

### Task 7: `cli.py` over the new modules

**Files:**
- Rewrite: `packages/tri-analyze/src/tri_analyze/cli.py`
- Create: `packages/tri-analyze/tests/test_cli.py`

**Interfaces:**
- Consumes: `get_analyze_settings` (Task 1), `make_model` (Task 2), `load_athlete_context`, `AthleteContext` (Task 2), `render_system_prompt` (Task 3), `build_agent` (Task 4), `open_live_tools` (Task 5), `chat_loop` (Task 6), `tri_core.db.connection.connect`, `tri_core.db.sql_tool.make_query_tool`, `tri_core.sync.runner.run_sync`.
- Produces: `app` (typer), `console`, `THREAD_ID = "analyze"`, `_out(s)`, `_read()`, `chat` command, `_chat(*, no_live) -> int`. Plan 2 adds `eval` here.

- [ ] **Step 1: Write the failing tests**

`packages/tri-analyze/tests/test_cli.py`:

```python
import os

import psycopg
from typer.testing import CliRunner

from tri_analyze import cli
from tri_analyze.cli import THREAD_ID, app
from tri_analyze.config import AnalyzeSettings

runner = CliRunner()


def test_help_lists_chat():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "chat" in result.output


def test_langsmith_project_is_set_on_import():
    assert os.environ["LANGSMITH_PROJECT"] == cli.get_analyze_settings().tri_analyze_langsmith_project
    assert THREAD_ID == "analyze"


def test_chat_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli, "get_analyze_settings", lambda: AnalyzeSettings(_env_file=None, anthropic_api_key=None)
    )
    result = runner.invoke(app, ["chat", "--no-live"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_chat_exits_2_when_the_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        cli, "get_analyze_settings", lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k")
    )

    def down(url):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("tri_core.db.connection.connect", down)
    result = runner.invoke(app, ["chat", "--no-live"])
    assert result.exit_code == 2
    assert "database unreachable: connection refused" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_cli.py -q`
Expected: `test_langsmith_project_is_set_on_import` and `test_chat_exits_2_when_the_database_is_unreachable` FAIL (`ImportError: cannot import name 'THREAD_ID'`, then no `database unreachable` output); the other two may already pass.

- [ ] **Step 3: Rewrite `cli.py`**

`packages/tri-analyze/src/tri_analyze/cli.py`:

```python
"""Command-line entry points: chat (plan 2 adds eval)."""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import TYPE_CHECKING

import typer
from dotenv import load_dotenv
from rich.console import Console

from tri_analyze.config import get_analyze_settings

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

load_dotenv()
# The agents share one .env; give the analyst its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_analyze_settings().tri_analyze_langsmith_project

app = typer.Typer(
    help="Triathlon training analysis agent (run `tri sync` to load data)", no_args_is_help=True
)
console = Console()
THREAD_ID = "analyze"


@app.callback()
def main() -> None:
    """Triathlon training analysis agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


async def _read() -> str | None:
    try:
        return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
    except EOFError:
        return None


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Bind only the database tool"),
) -> None:
    """Chat with the training analyst agent."""
    raise typer.Exit(code=asyncio.run(_chat(no_live=no_live)))


async def _chat(*, no_live: bool) -> int:
    from contextlib import AsyncExitStack

    import psycopg

    from tri_analyze.agent import build_agent
    from tri_analyze.llm import make_model
    from tri_analyze.prompts.analyst import render_system_prompt
    from tri_analyze.repl import chat_loop
    from tri_analyze.repo import AthleteContext, load_athlete_context
    from tri_analyze.tools.live import open_live_tools
    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_core.sync.runner import run_sync

    settings = get_analyze_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2

    def load_context() -> AthleteContext:
        with connect(settings.database_url) as conn:
            return load_athlete_context(conn, date.today())

    # Load the context before the MCP servers start, so a down database fails in well under
    # a second instead of after a 10 to 20 s server launch.
    try:
        current: list[AthleteContext] = [load_context()]
    except psycopg.OperationalError as exc:
        console.print(f"database unreachable: {exc}", style="red")
        return 2

    async with AsyncExitStack() as stack:
        live_tools: list[BaseTool] = []
        if not no_live:
            live_tools = await stack.enter_async_context(
                open_live_tools(settings, lambda m: _out(m + "\n"))
            )
        tools: list[BaseTool] = [make_query_tool(settings.database_url), *live_tools]
        agent = build_agent(make_model(settings), tools)

        async def cmd_tools() -> str:
            return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)

        async def cmd_prompt() -> str:
            return render_system_prompt(current[0], [t.name for t in tools])

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            status = "sync " + ("ok" if report.ok else "had errors")
            try:
                current[0] = load_context()
            except psycopg.OperationalError as exc:
                return f"{status}; athlete context not refreshed: database unreachable: {exc}"
            return f"{status}; athlete context refreshed"

        await chat_loop(
            agent,
            read=_read,
            out=_out,
            context=lambda: current[0],
            thread_id=THREAD_ID,
            commands={"tools": cmd_tools, "prompt": cmd_prompt, "sync": cmd_sync},
        )
    return 0


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_cli.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Manual check (optional; needs `.env` with keys and Postgres up)**

```bash
uv run tri-analyze chat --no-live
  /prompt
  /tools
  /sync
  /quit
```
Expected: the prompt prints with `Tools bound this session: query_training_db.` and the no-live sentence; `/sync` reports and says `athlete context refreshed`; `/quit` exits 0. Stop Postgres (`docker compose stop db`), rerun: prints `database unreachable: ...`, exit code 2. Start it again.

- [ ] **Step 6: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/cli.py packages/tri-analyze/tests/test_cli.py
git commit -m "feat(analyze): chat over the flat modules; LANGSMITH_PROJECT from settings; database down exits 2; /sync swaps the context"
```

---

### Task 8: `tri-coach` calls the analyst with `context=`

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/tools/analyst.py`
- Modify: `packages/tri-coach/src/tri_coach/context.py:12`
- Modify: `packages/tri-coach/tests/test_tools.py` (one test added after `test_ask_analyst_runs_the_analyst_on_a_throwaway_thread`)

**Interfaces:**
- Consumes: `tri_analyze.agent.build_agent`, `tri_analyze.repo.load_athlete_context`, `tri_analyze.testing.RecordingScriptedModel`.
- Produces: `make_analyst_tool(model, tools, connect, today) -> BaseTool` unchanged in name, description and failure texts.

- [ ] **Step 1: Write the failing test**

Add to `packages/tri-coach/tests/test_tools.py`, after `test_ask_analyst_runs_the_analyst_on_a_throwaway_thread`:

```python
@pytest.mark.db
async def test_ask_analyst_passes_the_context_and_the_analyst_sees_its_prompt(nocommit):
    from langchain_core.messages import SystemMessage

    from tri_analyze.testing import RecordingScriptedModel

    @tool
    def query_training_db(sql: str) -> str:
        """fake db tool"""
        return "[]"

    analyst = RecordingScriptedModel(script=[AIMessage(content="Nothing synced yet.")])
    ask = make_analyst_tool(
        analyst,
        [query_training_db],
        lambda: contextlib.nullcontext(nocommit),
        lambda: date(2026, 9, 14),
    )
    assert await ask.ainvoke({"question": "how was the week?"}) == "Nothing synced yet."
    system = analyst.received[0][0]
    assert isinstance(system, SystemMessage)
    assert "Today is 2026-09-14." in system.content
    assert "Athlete thresholds: not available (run `tri sync`)." in system.content
    assert "Tools bound this session: query_training_db." in system.content
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py -q -k ask_analyst`
Expected: the new test FAILS (the old `build_agent` signature takes a prompt string, so `TypeError`, or the prompt is rendered without `Today is 2026-09-14.` from the context).

- [ ] **Step 3: Rewrite the analyst tool**

`packages/tri-coach/src/tri_coach/tools/analyst.py`:

```python
"""ask_analyst: the tri-analyze agent as a tool. Each call runs the analyst on a throwaway
in-memory thread with the coach's read-only tools and returns its final text, or the failure as
text (spec 9)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp

from tri_analyze.agent import build_agent
from tri_analyze.repo import load_athlete_context
from tri_coach.text import last_ai_text
from tri_core.db.repo import Conn

ANALYST_RECURSION_LIMIT = 40


def make_analyst_tool(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    connect: Callable[[], AbstractContextManager[Conn]],
    today: Callable[[], date],
) -> BaseTool:
    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
        logged intake against nutrition targets, or how training compares to plan. It reads the
        database and the devices; it changes nothing. Ask one specific question at a time."""
        try:
            with connect() as conn:
                ctx = load_athlete_context(conn, today())
            agent = build_agent(model, tools, InMemorySaver())
            out = await agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"analyst-{uuid4()}"},
                    "recursion_limit": ANALYST_RECURSION_LIMIT,
                },
                context=ctx,
            )
        except GraphBubbleUp:
            raise  # interrupts and other langgraph control flow must keep propagating
        except Exception as exc:
            return (
                f"The analyst failed ({type(exc).__name__}: {exc}); "
                "do not guess at the data it could not read."
            )
        return last_ai_text(out["messages"]) or (
            "The analyst returned no answer; ask a narrower question."
        )

    return StructuredTool.from_function(
        coroutine=ask_analyst,
        name="ask_analyst",
        description=inspect.cleandoc(ask_analyst.__doc__ or ""),
    )
```

- [ ] **Step 4: Point `context.py` at `tri_analyze.repo`**

In `packages/tri-coach/src/tri_coach/context.py`, replace the import line
`from tri_analyze._old_agent.prompt import load_athlete_context` with
`from tri_analyze.repo import load_athlete_context`.

- [ ] **Step 5: Run the coach tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass, including `test_evals.py::test_stub_descriptions_match_the_real_tools` (the description text is unchanged) and both existing `ask_analyst` tests.

- [ ] **Step 6: Definition of done, then commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach/src/tri_coach/tools/analyst.py packages/tri-coach/src/tri_coach/context.py packages/tri-coach/tests/test_tools.py
git commit -m "feat(coach): ask_analyst runs the analyst with context=; load_athlete_context from tri_analyze.repo"
```

---

### Task 9: Delete the old `agent/` sub-package

**Files:**
- Delete: `packages/tri-analyze/src/tri_analyze/_old_agent/` (`__init__.py`, `agent.py`, `live_tools.py`, `prompt.py`, `repl.py`, `README.md`)

**Interfaces:** none produced. After this task the only public modules are those in the File Structure table.

- [ ] **Step 1: Confirm nothing imports the old package**

Run: `grep -rn "_old_agent\|tri_analyze\.agent\.\(agent\|prompt\|repl\|live_tools\)" packages docs/superpowers/specs README.md --include='*.py' --include='*.md'`
Expected: matches only inside `packages/tri-analyze/src/tri_analyze/_old_agent/` itself (its README names its own modules) and the root README's two `agent/README.md` links, which Task 10 changes.

- [ ] **Step 2: Delete it**

```bash
git rm -r packages/tri-analyze/src/tri_analyze/_old_agent
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass. Count: 775 baseline, minus the 9 old tri-analyze tests (`test_agent` 4, `test_prompt` 5, `test_repl` 5, `test_live_tools` 1 non-live) replaced by the new ones (`test_config` 3, `test_llm` 1, `test_repo` 3, `test_prompt` 10, `test_agent` 7, `test_live_tools` 1, `test_repl` 8, `test_cli` 4), plus 1 coach test: `798 passed, 5 skipped`. Report the real number.

- [ ] **Step 4: Definition of done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
git commit -m "refactor(analyze): remove the agent/ sub-package; the flat layout is the package"
```

---

### Task 10: Documentation and the Obsidian copies

**Files:**
- Rewrite: `packages/tri-analyze/README.md`
- Modify: `README.md` (root; lines 30 to 41 links, 135 to 150 layout, Status list)
- Modify: `docs/superpowers/specs/2026-09-06-tri-analyze-design.md` (Status line only)
- Vault: `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/` copies

- [ ] **Step 1: Write the package README**

Replace `packages/tri-analyze/README.md` with:

````markdown
# tri-analyze

The analyst: `tri-analyze chat` answers questions about one athlete's training from the Postgres
store that `tri sync` fills (package `tri-core`) and, when bound, five live Garmin and
TrainingPeaks reads. Feedback on completed sessions, trends over weeks and months, readiness
today. `tri-coach` runs the same agent as its `ask_analyst` tool. Design:
`docs/superpowers/specs/2026-09-13-tri-analyze-alignment-design.md` (supersedes the 2026-09-06
spec for the agent; sync and the data layer moved to `tri-core`). Plans:
`docs/superpowers/plans/2026-09-13-tri-analyze-0*.md`.

## How it works

A LangChain agent is three things: a chat model, a list of tools, and a loop.

1. The model receives the conversation plus a description of every tool.
2. It replies either with text or with a structured request: "call this tool with these
   arguments."
3. LangChain runs the tool, appends the result to the conversation, and calls the model again.
4. The loop ends when the model replies with text and no tool call.

### The model, the tools and the loop

`llm.make_model` wraps Claude in `ChatAnthropic` (no `thinking` parameter; adaptive thinking is
the model default). `agent.build_agent(model, tools, checkpointer)` calls `create_agent` with
two middlewares and an `InMemorySaver`, and returns the graph with a run config: tag `analyst`
and metadata `analyst_prompt_version`. The graph is a state machine with a `model` node and a
`tools` node and an edge that loops while tool calls exist. The checkpointer stores state per
`thread_id`; each REPL turn sends only the new human message and LangGraph loads the prior
messages, which is what makes it a conversation. Threads are isolated from each other.

### The system prompt is rendered per model call from runtime context

`repo.load_athlete_context` reads thresholds, the last seven days of load and recovery, and the
workouts one week either side of today into an `AthleteContext`. Every run passes it as
`context=`; `agent.analyst_prompt`, a `@dynamic_prompt` middleware, renders
`prompts.analyst.render_system_prompt(context, [bound tool names])` before each model call.
The prompt is not stored in the checkpoint, so `/sync` swaps the context and the next turn sees
fresh data while the thread keeps its history. The renderer is a pure function: same data, same
bytes. Anthropic's prompt cache matches on an exact prefix, so a stable prompt plus a stable tool
list means every turn after the first reads the prefix from cache. The prompt middleware is
listed before `AnthropicPromptCachingMiddleware` so the rendered prompt is what gets the
`cache_control` marker; `unsupported_model_behavior="ignore"` lets the same graph run on the
scripted test model.

`FEEDBACK_RULES` encode what a good session review covers (planned vs actual, execution
quality, load context, athlete comments, concrete takeaways) and the rule "compute with SQL, not
in your head."

### Tools described by name

`prompts.analyst.TOOL_GUIDE` has one line per tool name: what it is for and which argument to
pass. The prompt lists every bound tool in bound order, then the guide line for each name it
knows; an unknown tool is listed without a line. When only `query_training_db` is bound the
prompt says so and tells the model to work from the database. Under `tri-coach` two extra tools
from `tri-nutrition` are bound, `read_body_composition` and `read_intake_vs_targets`, and
their guide lines appear only then.

### `query_training_db`: the tool is a function plus a docstring

`tri_core.db.sql_tool.make_query_tool` wraps a typed function with `@tool`; the docstring plus
`SCHEMA_DOC` is the model's only knowledge of the database. `validate_select` rejects anything
that is not one `SELECT`/`WITH`; the query runs on a `read_only=True` connection with a 5 s
statement timeout and a 200-row cap; SQL errors come back as `{"error": ...}` text and the model
retries with better SQL.

### Live tools: MCP tools become LangChain tools

`tools/live.py` hands this agent's allow-lists (`allowlist.py`) and the two server specs to
`tri_core.mcp.live_tools.open_live_tools`. `langchain-mcp-adapters` launches each server over
stdio, fetches its tool list and turns each JSON schema into a `BaseTool`. The servers expose
about 190 tools; the agent sees five: Garmin `get_activity`, `get_activity_splits`,
`get_training_readiness`, `get_hrv_data`, and TrainingPeaks `tp_get_workout`. Sessions stay
open for the whole chat inside an `AsyncExitStack`; a server that fails to start is logged and
skipped.

### Streaming REPL

`repl.run_turn` calls `agent.astream(..., stream_mode=["messages", "updates"], context=...)`.
`messages` events are token chunks, printed inline. `updates` events fire when a node finishes:
a finished `model` node prints its tool calls as `→ name(args)`, a finished `tools` node prints
`← name: N chars`. Anthropic errors (rate limit, status, connection) and any other exception are
printed as one bracketed line; the loop continues and the thread keeps its last checkpoint.
REPL turns carry the `chat` tag.

### Testing without a model

`tri_core.testing.ScriptedChatModel` replays a list of `AIMessage`s for both `invoke` and
`stream`; `tri_analyze.testing.RecordingScriptedModel` also keeps every message list it was sent,
so tests assert on the rendered system prompt. `testing.athlete_context()` is the prompt fixture;
`seed_workouts` and `seed_daily_metrics` fill the rolled-back test database.

## Commands

```
uv run tri-analyze chat [--no-live]     # /tools /prompt /sync /quit
```

`--no-live` binds only the database tool. Exit 2 when `ANTHROPIC_API_KEY` is unset or the
database is unreachable. A failed MCP server is logged and skipped.

## Layout

```
src/tri_analyze/
  config.py           AnalyzeSettings (tri_core Settings + TRI_ANALYZE_LANGSMITH_PROJECT)
  llm.py              make_model, MAX_TOKENS
  repo.py             AthleteContext, load_athlete_context
  prompts/analyst.py  PROMPT_VERSION, FEEDBACK_RULES, TOOL_GUIDE, render_system_prompt
  agent.py            analyst_prompt (@dynamic_prompt), build_agent
  allowlist.py        the Garmin and TrainingPeaks tools the agent may call live
  tools/live.py       open_live_tools over tri_core.mcp with the allow-lists
  repl.py             text_of, TurnPrinter, run_turn, chat_loop
  cli.py              chat
  testing.py          athlete_context, RecordingScriptedModel, seed_workouts, seed_daily_metrics
```

## One question, end to end

> "Give me feedback on my last completed ride. Pull the laps."

1. The REPL reads the context holder and sends a `HumanMessage` into the graph on thread
   `analyze` with `context=` the current `AthleteContext`.
2. `analyst_prompt` renders the system prompt from that context and the bound names.
3. Model node: emits a `query_training_db` call to find the ride and its `garmin_activity_id`.
4. Tools node: runs the SQL on a read-only connection, appends the JSON as a `ToolMessage`.
5. Model node (prompt rendered again, same bytes): emits `get_activity_splits(activity_id=...)`.
6. Tools node: the MCP session forwards the call to the Garmin server; laps come back.
7. Model node: writes the review following `FEEDBACK_RULES`, no further tool calls.
8. The loop exits; the saver stores all six messages under the thread for the next turn.

With `LANGSMITH_TRACING=true`, every hop is recorded in project `tri_analyze` with the exact
prompt, tool schema JSON and token counts (look for `cache_read_input_tokens` on the second turn).

## Design decisions

| Decision | Why |
|---|---|
| One flexible read-only SQL tool instead of many narrow query tools | The model composes its own questions. Safety comes from the connection mode, not from limiting what it can ask. |
| System prompt rendered from runtime context, not fetched via tools | Cheaper and faster; the model always has thresholds and current load in view, and `/sync` refreshes it without rebuilding the agent. |
| Tools described by name in `TOOL_GUIDE` | The same prompt serves the standalone chat and the coach, which binds two extra tools; each session's prompt describes exactly what is bound. |
| Raw MCP tools with an allow-list, not hand-written wrappers | Less code, and it is the real LangChain-plus-MCP integration rather than a facade. |
| Tool binding order is fixed (SQL, Garmin, TrainingPeaks, extras) | The tool list is part of the cached prompt prefix; reordering invalidates the cache. |
| In-memory checkpointer | The analyst has no interrupts and no multi-step workflow state, so nothing needs to survive the process. A persistent thread would grow token cost and carry answers computed from older synced data; `tri-coach` uses a throwaway thread per question regardless. |
| Async REPL | MCP sessions are async and must stay open across turns. |

## Knobs

- **The model writes bad SQL:** edit `SCHEMA_DOC` in `tri_core/db/sql_tool.py`.
- **Feedback is vague or misses something:** edit `FEEDBACK_RULES` in `prompts/analyst.py` and
  bump `PROMPT_VERSION`.
- **The model ignores a tool or picks the wrong one:** edit its `TOOL_GUIDE` line, or
  `allowlist.py` for which tools are bound.
- **Model or cost:** `TRI_MODEL` in `.env`; `MAX_TOKENS` in `llm.py`.
- **How much context the prompt carries:** the date windows in `repo.load_athlete_context`.
- **Where traces go:** `TRI_ANALYZE_LANGSMITH_PROJECT` (default `tri_analyze`).
````

- [ ] **Step 2: Edit the root README**

In `README.md`:

1. Replace the bullet at lines 32 and 33 with:
   ```
   - [`packages/tri-analyze/README.md`](packages/tri-analyze/README.md):
     how the analyst agent works, module by module, one question traced end to end.
   ```
2. Line 142: `packages/tri-analyze/   src/tri_analyze/{cli,allowlist,agent}` becomes
   `packages/tri-analyze/   src/tri_analyze/{config,cli,llm,agent,repo,repl,testing,allowlist,prompts,tools}`.
3. Lines 149 and 150 (the `Module-level READMEs:` sentence) become:
   ```
   Module-level READMEs: `packages/tri-core/src/tri_core/{mcp,db,sync}/README.md`; each agent
   package documents itself in its own `README.md`.
   ```
4. Append to the Status list:
   ```
   - tri-analyze alignment (2026-09): flat layout, settings and LangSmith project, prompt rendered per call
     from runtime context with a tool guide, chat hardening, coach passes the context; tracked in
     `docs/superpowers/plans/2026-09-13-tri-analyze-01-alignment.md`. Eval pending (plan 2).
   ```

- [ ] **Step 3: Mark the old spec superseded**

In `docs/superpowers/specs/2026-09-06-tri-analyze-design.md`, replace the line
`**Status:** Approved design, pending implementation plan` with
```
**Status:** Implemented 2026-09-06 (plans `2026-09-06-foundation-and-sync.md`, `2026-09-06-agent-v1.md`). Superseded for the agent by `2026-09-13-tri-analyze-alignment-design.md`; sync and the data layer now live in `tri-core`.
```

- [ ] **Step 4: Copy to the Obsidian vault**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp packages/tri-analyze/README.md "$V/packages/tri-analyze/readme.md"
cp README.md "$V/readme.md"
cp docs/superpowers/specs/2026-09-06-tri-analyze-design.md "$V/docs/superpowers/specs/2026-09-06-tri-analyze-design.md"
rm "$V/packages/tri-analyze/src/tri_analyze/agent/readme.md"
rmdir "$V/packages/tri-analyze/src/tri_analyze/agent" "$V/packages/tri-analyze/src/tri_analyze" "$V/packages/tri-analyze/src"
ls "$V/packages/tri-analyze"
```
Expected: only `readme.md`.

- [ ] **Step 5: Definition of done including the build, then commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv build --package tri-analyze
git add packages/tri-analyze/README.md README.md docs/superpowers/specs/2026-09-06-tri-analyze-design.md
git commit -m "docs(analyze): package README in the siblings' shape; root README links and layout; old spec superseded"
```

---

## After the last task

1. Run the full definition of done once more from the worktree root and paste the counts into the merge message: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv build --package tri-analyze`.
2. Merge from the shared checkout once no other session is open: `git merge --no-ff feat/tri-analyze-01` on `main`, then `git worktree remove ../triathlon_agent-tri-analyze-01`.
3. Copy `.superpowers/` scratch to the vault's `.superpowers/sdd/2026-09-13-tri-analyze-01-alignment/`.
4. Plan 2 (`2026-09-13-tri-analyze-02-eval.md`) branches from the merged `main`.
