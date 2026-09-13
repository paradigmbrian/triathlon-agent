# tri-analyze Plan 2 of 2: Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tri-analyze eval` (spec milestone 2): twelve analyst cases in a LangSmith dataset `tri_analyze_feedback`, a target that runs the real `build_agent` over stub tools with canned results, three code checks over the tool calls and the answer, one LLM judge scoring grounding and feedback quality, and an experiment named `analyst-v<PROMPT_VERSION>`. Exit 0 only when every evaluator passes and no example errored.

**Architecture:** `evals/cases.py` holds `EvalCase` (question, an `AthleteContext` for a fixed today, which tools to bind, canned tool results, the flags the checks read). `evals/target.py` builds stub tools with the real names, argument names and (for SQL) the real description, runs `build_agent(model, stubs)` with `context=`, and returns the tool calls and the final answer. `evals/evaluators.py` has `uses_sql`, `pulls_splits`, `states_window` and `make_judge(model)`, which returns both `grounded` and `feedback_quality` from one structured-output call. `evals/run.py` creates the dataset once and runs `aevaluate`, reporting pass rates and the errored count. `cli.py` gains `eval`.

**Tech Stack:** langsmith 0.12.2 (`Client`, `aevaluate`, `EvaluationResult`, `EvaluationResults`; evaluators taking `inputs`, `outputs`, `reference_outputs`; `row["run"].error` on an errored example), langchain 1.4.0 `create_agent` via `tri_analyze.agent.build_agent`, `with_structured_output` on the judge model, pydantic 2, typer, pytest with `tri_core.testing.ScriptedChatModel`.

**Spec:** `docs/superpowers/specs/2026-09-13-tri-analyze-alignment-design.md` (§7 evaluation, §8 errors, §9 testing, §10 documentation, §11 observability, §12 milestone 2). Plan 1 (`2026-09-13-tri-analyze-01-alignment.md`) must be merged first: this plan imports `tri_analyze.agent.build_agent`, `tri_analyze.repo.AthleteContext`, `tri_analyze.prompts.analyst.{PROMPT_VERSION, FEEDBACK_RULES, render_system_prompt}`, `tri_analyze.repl.text_of`, `tri_analyze.config.get_analyze_settings`, `tri_analyze.llm.make_model` and `tri_analyze.cli.{app, console, _out}`.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree** from the `main` that contains plan 1: `git worktree add ../triathlon_agent-tri-analyze-02 -b feat/tri-analyze-02 main`, `cp .env ../triathlon_agent-tri-analyze-02/.env`, then `uv sync` there. Other Claude sessions share the main checkout. Record the baseline (`uv run pytest -q`) before Task 1; plan 1 predicts `798 passed, 5 skipped`.
- One new dependency: `langsmith>=0.12,<1` in `packages/tri-analyze/pyproject.toml` (already in the lock through `tri-wellness`, `tri-nutrition` and `tri-coach`). No other dependency changes. No edits under `packages/tri-core`, `packages/tri-planning`, `packages/tri-nutrition`, `packages/tri-wellness`, `packages/tri-coach`. The root `pyproject.toml` is untouched.
- Eval tests need no database, no LangSmith and no Anthropic key. The one `live` test (stub argument names against the real MCP tools) runs only with `--live`.
- `DATASET_NAME = "tri_analyze_feedback"`; experiment prefix `analyst-v<PROMPT_VERSION>` (`analyst-v1` today); experiment metadata `{"prompt_version": PROMPT_VERSION, "model": settings.tri_model}`; `max_concurrency=2`; target runs carry the `eval` tag; `TODAY = date(2026, 9, 16)` (the date `tri-coach`'s eval uses).
- Evaluator keys are exactly `uses_sql`, `pulls_splits`, `states_window`, `grounded`, `feedback_quality`. A check that does not apply scores `None`.
- The stub `query_training_db` carries the real tool's description (`make_query_tool("postgresql://unused/db").description`); stub argument names equal the real tools' (`sql`; `activity_id`; `date`; `workout_id`; `days`).
- Git commits are permitted (Brian's standing permission). Commit per task on the feature branch. End every commit message with the `Co-Authored-By:` and `Claude-Session:` trailer lines of the session executing the plan.
- Definition of done per task, in order: `uv run ruff format packages/tri-analyze`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. The only acceptable pytest warning is the pre-existing langsmith `ast.Str` DeprecationWarning. Task 7 adds `uv build --package tri-analyze`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, with kebab-case names (`readme.md` for READMEs). SDD scratch (`.superpowers/`) goes to that vault's `.superpowers/sdd/<plan>/` at the end.

### Facts verified while writing this plan (against `main` a0105b7 plus plan 1's design)

1. `langsmith.evaluation.EvaluationResult(key=..., score=..., comment=...)` is a pydantic model; `EvaluationResults` is the TypedDict `{"results": list[EvaluationResult]}`, and an evaluator may return it to score several keys from one call. `aevaluate` passes `inputs`, `outputs` and `reference_outputs` (the example's outputs) to function evaluators by parameter name, sync or async. Each row of the result is `ExperimentResultRow(run, example, evaluation_results)`; a target that raised leaves `row["run"].error` set (a string) and is counted as errored.
2. `tri_nutrition.evals.run.pass_rates(rows)` (which `tri-coach` imports) reads `row["evaluation_results"]["results"]` and skips `score is None`; this plan copies it rather than importing across packages.
3. `ScriptedChatModel.with_structured_output(Model)` parses a scripted `tool_call("Model", {...})` into `Model` (the `tri-coach` judge tests rely on this). A `ScriptedChatModel(script=[])` raises `IndexError` on its first call.
4. `tri_core.db.sql_tool.make_query_tool(url)` opens no connection; the real tool's only argument is `sql`. The real Garmin tools take `activity_id` (`get_activity`, `get_activity_splits`) and `date` (`get_training_readiness`, `get_hrv_data`); `tp_get_workout` takes `workout_id`; `tri-nutrition`'s `read_body_composition(days: int = 28)` and `read_intake_vs_targets(days: int = 7)` are the two coach extras (`tri_coach/graph/deps.py` `analyst_tools_for`).
5. `BaseTool.args` is the dict of schema properties, so `set(stub.args) == set(real.args)` compares argument names.
6. `build_agent(model, tools)` (plan 1) accepts `ainvoke(payload, config, context=AthleteContext)`; `config["tags"]` reaches every model run; `recursion_limit` is honoured in the config dict.
7. `tri_analyze.cli` (plan 1) has `app`, `console`, `_out`, `get_analyze_settings` imported at module level, and `chat`. `tri-wellness`'s `eval` command is the shape to copy.

## File Structure

New (all under `packages/tri-analyze/`):

| File | Responsibility |
|---|---|
| `src/tri_analyze/evals/__init__.py` | empty |
| `src/tri_analyze/evals/cases.py` | `TODAY`, `Kind`, `KINDS`, `EvalCase`, `jsonable`, the fixture builders, `CASES` |
| `src/tri_analyze/evals/target.py` | `SQL_DESCRIPTION`, `LIVE_DESCRIPTIONS`, `EXTRA_DESCRIPTIONS`, `athlete_from_inputs`, `Canned`, `stub_tools`, `run_case`, `make_target` |
| `src/tri_analyze/evals/evaluators.py` | `uses_sql`, `pulls_splits`, `states_window`, `WINDOW_PATTERNS`, `FeedbackJudgement`, `JUDGE_SYSTEM`, `render_judge_prompt`, `make_judge` |
| `src/tri_analyze/evals/run.py` | `DATASET_NAME`, `DATASET_DESCRIPTION`, `case_examples`, `ensure_dataset`, `pass_rates`, `render_pass_rates`, `errored`, `run_eval` |
| `tests/test_evals.py` | everything above without LangSmith or a real model |

Modified: `pyproject.toml` (package), `uv.lock`, `src/tri_analyze/cli.py` (`eval`), `tests/test_cli.py`, `tests/test_live_tools.py`, `README.md` (package), root `README.md`.

---

### Task 1: Cases

**Files:**
- Modify: `packages/tri-analyze/pyproject.toml` (add `"langsmith>=0.12,<1",` after the `langchain-mcp-adapters` line)
- Create: `packages/tri-analyze/src/tri_analyze/evals/__init__.py` (empty)
- Create: `packages/tri-analyze/src/tri_analyze/evals/cases.py`
- Create: `packages/tri-analyze/tests/test_evals.py`

**Interfaces:**
- Consumes: `tri_analyze.repo.AthleteContext`.
- Produces: `TODAY = date(2026, 9, 16)`; `Kind = Literal["session", "trend", "readiness"]`; `KINDS`; `EXTRA_TOOLS = ("read_body_composition", "read_intake_vs_targets")`; `jsonable(value) -> Any`; `EvalCase(name, question, athlete, kind, live=True, extra_tools=[], tool_results={}, requires_sql=True, requires_splits=False, expects_window=False)` with `.inputs() -> dict` (`question, athlete, live, extra_tools, tool_results`) and `.outputs() -> dict` (`kind, requires_sql, requires_splits, expects_window`); `CASES: list[EvalCase]` (twelve). Tasks 2 to 5 consume these.

- [ ] **Step 1: Add the dependency and sync**

In `packages/tri-analyze/pyproject.toml` add `"langsmith>=0.12,<1",` after `"langchain-mcp-adapters==0.3.2",`. Then `uv sync`. Expected: `uv.lock` changes only in the `tri-analyze` package's dependency list.

- [ ] **Step 2: Write the failing tests**

`packages/tri-analyze/tests/test_evals.py` (this file grows in later tasks; start with):

```python
"""The analyst eval without LangSmith, a database or a real model."""

import json
from datetime import date

import pytest

from tri_analyze.evals.cases import CASES, EXTRA_TOOLS, KINDS, TODAY, EvalCase, jsonable
from tri_analyze.repo import AthleteContext


def case(name: str) -> EvalCase:
    return next(c for c in CASES if c.name == name)


def test_cases_are_valid_and_cover_every_kind():
    assert len({c.name for c in CASES}) == len(CASES) == 12
    assert TODAY == date(2026, 9, 16)
    assert {c.kind for c in CASES} == set(KINDS)
    for c in CASES:
        assert c.athlete.today == TODAY, c.name
        assert c.question.strip(), c.name
        assert set(c.extra_tools) <= set(EXTRA_TOOLS), c.name
        for name, responses in c.tool_results.items():
            assert responses and all(isinstance(r, str) for r in responses), (c.name, name)
        i, o = c.inputs(), c.outputs()
        assert set(i) == {"question", "athlete", "live", "extra_tools", "tool_results"}, c.name
        assert o == {
            "kind": c.kind,
            "requires_sql": c.requires_sql,
            "requires_splits": c.requires_splits,
            "expects_window": c.expects_window,
        }, c.name
        json.dumps(i)  # JSON-safe: dates are ISO strings
        json.dumps(o)
        assert i["athlete"]["today"] == "2026-09-16"
    assert all(c.requires_sql for c in CASES if c.requires_splits)  # splits need the activity id
    assert any(c.requires_splits and c.live for c in CASES)
    assert any(c.requires_splits and not c.live for c in CASES)
    assert any(not c.requires_sql for c in CASES)
    assert any(c.expects_window for c in CASES)
    assert any("read_body_composition" in c.extra_tools for c in CASES)
    assert any(not c.tool_results for c in CASES)  # a case whose SQL returns []


def test_jsonable_converts_nested_dates():
    ctx = AthleteContext(
        today=date(2026, 9, 16),
        profile={"ftp_watts": 250},
        recent_days=[{"metric_date": date(2026, 9, 15), "ctl": 48.0}],
    )
    from dataclasses import asdict

    out = jsonable(asdict(ctx))
    assert out["today"] == "2026-09-16"
    assert out["recent_days"][0]["metric_date"] == "2026-09-15" and out["profile"] == {"ftp_watts": 250}
    assert jsonable([date(2026, 1, 2), 3, "x"]) == ["2026-01-02", 3, "x"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.evals'`.

- [ ] **Step 4: Write `cases.py`**

Create an empty `packages/tri-analyze/src/tri_analyze/evals/__init__.py`, then `packages/tri-analyze/src/tri_analyze/evals/cases.py`:

```python
"""The analyst's eval cases: a question, an athlete context for a fixed today (Wednesday
2026-09-16, the date the tri-coach eval uses), which tools to bind, canned tool results, and the
flags the code checks read. Inputs are JSON-safe so they can live in a LangSmith dataset."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

from tri_analyze.repo import AthleteContext

TODAY = date(2026, 9, 16)
Kind = Literal["session", "trend", "readiness"]
KINDS: tuple[Kind, ...] = ("session", "trend", "readiness")
EXTRA_TOOLS = ("read_body_composition", "read_intake_vs_targets")

PROFILE: dict[str, Any] = {
    "ftp_watts": 250,
    "run_threshold_pace_sec_per_km": 255,
    "swim_css_sec_per_100m": 100,
    "lthr_bpm": 172,
    "max_hr_bpm": 188,
    "weight_kg": 74.0,
}


def jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def rows(*items: dict[str, Any]) -> str:
    """A tool result: JSON text, as query_training_db and the MCP tools return."""
    return json.dumps(list(items), default=str)


def _day(d: date, tss: int, ctl: float, atl: float, sleep: int, hrv: int, ready: int) -> dict[str, Any]:
    return {
        "metric_date": d,
        "tss_day": tss,
        "ctl": ctl,
        "atl": atl,
        "tsb": round(ctl - atl, 1),
        "sleep_score": sleep,
        "hrv_overnight_avg": hrv,
        "resting_hr": 46,
        "training_readiness": ready,
    }


def _workout(
    d: date, sport: str, title: str, planned: int, actual: int | None, *, completed: bool = True
) -> dict[str, Any]:
    return {
        "workout_date": d,
        "sport": sport,
        "title": title,
        "completed": completed,
        "planned_tss": planned,
        "actual_tss": actual,
        "planned_duration_sec": None,
        "actual_duration_sec": None,
    }


WEEK_DAYS = [
    _day(date(2026, 9, 9), 92, 47.0, 52.0, 74, 62, 55),
    _day(date(2026, 9, 10), 0, 46.7, 49.4, 81, 66, 68),
    _day(date(2026, 9, 11), 45, 46.6, 48.8, 78, 64, 66),
    _day(date(2026, 9, 12), 0, 46.3, 46.0, 83, 68, 74),
    _day(date(2026, 9, 13), 128, 47.7, 55.4, 72, 60, 58),
    _day(date(2026, 9, 14), 58, 47.9, 55.7, 77, 63, 61),
    _day(date(2026, 9, 15), 74, 48.3, 57.7, 70, 58, 49),
]

WEEK_WORKOUTS = [
    _workout(date(2026, 9, 9), "bike", "Threshold 3x10", 85, 92),
    _workout(date(2026, 9, 11), "run", "Easy 45 min", 45, 45),
    _workout(date(2026, 9, 12), "swim", "CSS 10x100", 40, None, completed=False),
    _workout(date(2026, 9, 13), "brick", "Brick: 2h ride + 20 min run", 130, 128),
    _workout(date(2026, 9, 14), "bike", "Z2 ride", 60, 58),
    _workout(date(2026, 9, 15), "run", "Intervals 6x800", 70, 74),
    _workout(date(2026, 9, 17), "run", "Tempo 40 min", 55, None, completed=False),
    _workout(date(2026, 9, 19), "bike", "Long ride", 150, None, completed=False),
]


def athlete(**over: Any) -> AthleteContext:
    base: dict[str, Any] = {
        "today": TODAY,
        "profile": dict(PROFILE),
        "recent_days": [dict(d) for d in WEEK_DAYS],
        "recent_workouts": [dict(w) for w in WEEK_WORKOUTS],
    }
    base.update(over)
    return AthleteContext(**base)


@dataclass(frozen=True)
class EvalCase:
    name: str
    question: str
    athlete: AthleteContext
    kind: Kind
    live: bool = True
    extra_tools: list[str] = field(default_factory=list)
    tool_results: dict[str, list[str]] = field(default_factory=dict)  # per tool, in call order
    requires_sql: bool = True
    requires_splits: bool = False
    expects_window: bool = False

    def inputs(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "athlete": jsonable(asdict(self.athlete)),
            "live": self.live,
            "extra_tools": list(self.extra_tools),
            "tool_results": {k: list(v) for k, v in self.tool_results.items()},
        }

    def outputs(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requires_sql": self.requires_sql,
            "requires_splits": self.requires_splits,
            "expects_window": self.expects_window,
        }


Z2_RIDE = {
    "workout_date": "2026-09-14",
    "sport": "bike",
    "title": "Z2 ride",
    "completed": True,
    "planned_duration_sec": 5400,
    "actual_duration_sec": 5460,
    "planned_tss": 60,
    "actual_tss": 58,
    "actual_if": 0.62,
    "avg_power": 155,
    "normalized_power": 160,
    "avg_hr": 132,
    "feeling": 7,
    "rpe": 4,
    "comments": None,
    "garmin_activity_id": "g-1401",
}
INTERVAL_RUN = {
    "workout_date": "2026-09-15",
    "sport": "run",
    "title": "Intervals 6x800",
    "completed": True,
    "description": "WU 15 min, 6x800 m at threshold pace (4:15/km) with 2 min jog, CD 10 min",
    "actual_duration_sec": 3540,
    "actual_distance_m": 10600,
    "planned_tss": 70,
    "actual_tss": 74,
    "avg_hr": 158,
    "feeling": 6,
    "rpe": 7,
    "comments": None,
    "garmin_activity_id": "g-1502",
}
INTERVAL_SPLITS = [
    {"lap": 1, "type": "warmup", "distance_m": 2500, "duration_sec": 900, "avg_hr": 128},
    {"lap": 2, "type": "work", "distance_m": 800, "duration_sec": 200, "avg_pace_sec_per_km": 250, "avg_hr": 168},
    {"lap": 3, "type": "rest", "distance_m": 260, "duration_sec": 120, "avg_hr": 150},
    {"lap": 4, "type": "work", "distance_m": 800, "duration_sec": 202, "avg_pace_sec_per_km": 252, "avg_hr": 172},
    {"lap": 5, "type": "rest", "distance_m": 255, "duration_sec": 120, "avg_hr": 152},
    {"lap": 6, "type": "work", "distance_m": 800, "duration_sec": 203, "avg_pace_sec_per_km": 254, "avg_hr": 175},
    {"lap": 7, "type": "rest", "distance_m": 250, "duration_sec": 120, "avg_hr": 154},
    {"lap": 8, "type": "work", "distance_m": 800, "duration_sec": 206, "avg_pace_sec_per_km": 258, "avg_hr": 177},
    {"lap": 9, "type": "rest", "distance_m": 245, "duration_sec": 120, "avg_hr": 156},
    {"lap": 10, "type": "work", "distance_m": 800, "duration_sec": 211, "avg_pace_sec_per_km": 264, "avg_hr": 179},
    {"lap": 11, "type": "rest", "distance_m": 240, "duration_sec": 120, "avg_hr": 157},
    {"lap": 12, "type": "work", "distance_m": 800, "duration_sec": 218, "avg_pace_sec_per_km": 272, "avg_hr": 181},
    {"lap": 13, "type": "cooldown", "distance_m": 1850, "duration_sec": 600, "avg_hr": 140},
]
MISSED_SWIM = {
    "workout_date": "2026-09-12",
    "sport": "swim",
    "title": "CSS 10x100",
    "completed": False,
    "description": "400 WU, 10x100 at CSS on 1:50, 200 CD",
    "planned_duration_sec": 3000,
    "planned_tss": 40,
    "actual_duration_sec": None,
    "actual_tss": None,
    "comments": None,
    "garmin_activity_id": None,
}
THRESHOLD_RIDE = {
    "workout_date": "2026-09-09",
    "sport": "bike",
    "title": "Threshold 3x10",
    "completed": True,
    "description": "3x10 min at 95-100% FTP, 5 min easy between",
    "planned_duration_sec": 4500,
    "actual_duration_sec": 4380,
    "planned_tss": 85,
    "actual_tss": 92,
    "actual_if": 0.87,
    "avg_power": 205,
    "normalized_power": 218,
    "avg_hr": 164,
    "feeling": 3,
    "rpe": 9,
    "comments": [
        {"author": "athlete", "text": "Legs were dead from the start; the third rep fell apart at 6 min."}
    ],
    "garmin_activity_id": "g-0901",
}
BRICK = {
    "workout_date": "2026-09-13",
    "sport": "brick",
    "title": "Brick: 2h ride + 20 min run",
    "completed": True,
    "description": "2 h ride, 3x15 min at race power (200 W), then 20 min run at race pace",
    "planned_duration_sec": 8400,
    "actual_duration_sec": 8520,
    "planned_tss": 130,
    "actual_tss": 128,
    "actual_if": 0.74,
    "avg_power": 178,
    "normalized_power": 186,
    "avg_hr": 149,
    "feeling": 6,
    "rpe": 7,
    "comments": [{"author": "athlete", "text": "Run legs came around after 8 min."}],
    "garmin_activity_id": "g-1301",
}
BRICK_SPLITS = [
    {"lap": 1, "type": "bike", "distance_m": 60500, "duration_sec": 7200, "avg_power": 178, "avg_hr": 146},
    {"lap": 2, "type": "run", "distance_m": 4300, "duration_sec": 1320, "avg_pace_sec_per_km": 307, "avg_hr": 163},
]
WEEKLY_TSS = [
    {"week_start": "2026-07-20", "tss": 388},
    {"week_start": "2026-07-27", "tss": 412},
    {"week_start": "2026-08-03", "tss": 445},
    {"week_start": "2026-08-10", "tss": 290},
    {"week_start": "2026-08-17", "tss": 430},
    {"week_start": "2026-08-24", "tss": 462},
    {"week_start": "2026-08-31", "tss": 470},
    {"week_start": "2026-09-07", "tss": 397},
]
RUN_VOLUME = [
    {"month": "2026-06", "sessions": 12, "distance_m": 118400, "duration_sec": 38160},
    {"month": "2026-07", "sessions": 14, "distance_m": 141900, "duration_sec": 45600},
    {"month": "2026-08", "sessions": 15, "distance_m": 156200, "duration_sec": 49800},
]
SLEEP_HRV = [
    {"metric_date": f"2026-09-{d:02d}", "sleep_score": s, "hrv_overnight_avg": h}
    for d, s, h in [
        (2, 84, 69), (3, 79, 66), (4, 61, 55), (5, 66, 57), (6, 82, 67), (7, 80, 66),
        (8, 58, 54), (9, 74, 62), (10, 81, 66), (11, 78, 64), (12, 83, 68), (13, 72, 60),
        (14, 77, 63), (15, 70, 58),
    ]
]
READINESS_TODAY = {
    "date": "2026-09-16",
    "score": 42,
    "level": "LOW",
    "sleep_score": 64,
    "recovery_time_hours": 31,
    "hrv_status": "UNBALANCED",
    "acute_load": 356,
}
HRV_TODAY = {
    "date": "2026-09-16",
    "last_night_avg": 54,
    "weekly_avg": 61,
    "baseline_low": 58,
    "baseline_high": 70,
    "status": "UNBALANCED",
}
BODY_COMP = [
    {"date": "2026-08-17", "weight_kg": 75.4, "body_fat_pct": 12.8, "muscle_mass_kg": 36.1},
    {"date": "2026-08-24", "weight_kg": 75.0, "body_fat_pct": 12.6, "muscle_mass_kg": 36.1},
    {"date": "2026-08-31", "weight_kg": 74.6, "body_fat_pct": 12.3, "muscle_mass_kg": 36.0},
    {"date": "2026-09-07", "weight_kg": 74.2, "body_fat_pct": 12.1, "muscle_mass_kg": 36.0},
    {"date": "2026-09-14", "weight_kg": 74.0, "body_fat_pct": 12.0, "muscle_mass_kg": 35.9},
]

CASES: list[EvalCase] = [
    EvalCase(
        name="last_z2_ride",
        question="Give me feedback on my last completed ride.",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(Z2_RIDE)],
            "get_activity": [rows({"activityId": "g-1401", "averageHR": 132, "maxHR": 148, "avgPower": 155, "duration": 5460, "distance": 45200})],
        },
    ),
    EvalCase(
        name="run_intervals",
        question="How did yesterday's interval run go? Look at the reps.",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(INTERVAL_RUN)],
            "get_activity_splits": [rows(*INTERVAL_SPLITS)],
        },
        requires_splits=True,
    ),
    EvalCase(
        name="missed_swim",
        question="What happened with Saturday's swim?",
        athlete=athlete(),
        kind="session",
        tool_results={"query_training_db": [rows(MISSED_SWIM)]},
    ),
    EvalCase(
        name="threshold_rpe9",
        question="Feedback on last Wednesday's threshold ride please. I felt awful.",
        athlete=athlete(),
        kind="session",
        tool_results={"query_training_db": [rows(THRESHOLD_RIDE)]},
    ),
    EvalCase(
        name="brick_sunday",
        question="How did Sunday's brick go?",
        athlete=athlete(),
        kind="session",
        tool_results={
            "query_training_db": [rows(BRICK)],
            "get_activity_splits": [rows(*BRICK_SPLITS)],
        },
    ),
    EvalCase(
        name="weekly_tss_8w",
        question="Show my weekly TSS for the last 8 weeks.",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*WEEKLY_TSS)]},
        expects_window=True,
    ),
    EvalCase(
        name="run_volume_mom",
        question="How has my run volume changed month over month?",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*RUN_VOLUME)]},
        expects_window=True,
    ),
    EvalCase(
        name="sleep_vs_hrv",
        question="Is my sleep affecting my HRV?",
        athlete=athlete(),
        kind="trend",
        tool_results={"query_training_db": [rows(*SLEEP_HRV)]},
        expects_window=True,
    ),
    EvalCase(
        name="go_hard_today",
        question="Should I go hard today?",
        athlete=athlete(),
        kind="readiness",
        tool_results={
            "get_training_readiness": [rows(READINESS_TODAY)],
            "get_hrv_data": [rows(HRV_TODAY)],
        },
        requires_sql=False,
    ),
    EvalCase(
        name="trend_no_data",
        question="What was my average weekly bike TSS in June?",
        athlete=athlete(),
        kind="trend",
        expects_window=True,
    ),
    EvalCase(
        name="intervals_no_live",
        question="Break down the reps from yesterday's interval run.",
        athlete=athlete(),
        kind="session",
        live=False,
        tool_results={"query_training_db": [rows(INTERVAL_RUN)]},
        requires_splits=True,
    ),
    EvalCase(
        name="body_composition",
        question="How has my weight trended over the last month?",
        athlete=athlete(),
        kind="trend",
        extra_tools=["read_body_composition"],
        tool_results={"read_body_composition": [rows(*BODY_COMP)]},
        requires_sql=False,
        expects_window=True,
    ),
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: `2 passed`.

- [ ] **Step 6: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/pyproject.toml uv.lock packages/tri-analyze/src/tri_analyze/evals packages/tri-analyze/tests/test_evals.py
git commit -m "feat(analyze): twelve analyst eval cases with canned tool results"
```

---

### Task 2: Target over stub tools

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/evals/target.py`
- Modify: `packages/tri-analyze/tests/test_evals.py` (append)
- Modify: `packages/tri-analyze/tests/test_live_tools.py` (append one live test)

**Interfaces:**
- Consumes: `build_agent`, `AthleteContext`, `text_of`, `GARMIN_LIVE_TOOLS`, `TP_LIVE_TOOLS`, `make_query_tool`, `EvalCase.inputs()` shape.
- Produces: `TARGET_RECURSION_LIMIT = 30`; `SQL_DESCRIPTION: str`; `LIVE_DESCRIPTIONS: dict[str, str]`; `EXTRA_DESCRIPTIONS: dict[str, str]`; `athlete_from_inputs(inputs) -> AthleteContext`; `Canned(results)` callable `(name) -> str`; `stub_tools(inputs) -> list[BaseTool]`; `run_case(model, inputs) -> {"calls": [{name, args}], "answer": str}`; `make_target(model) -> Callable[[dict], Awaitable[dict]]`. Tasks 3, 4, 5 consume these.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-analyze/tests/test_evals.py`:

```python
from langchain_core.messages import AIMessage

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.evals.target import Canned, athlete_from_inputs, make_target, stub_tools
from tri_core.db.sql_tool import make_query_tool
from tri_core.testing import ScriptedChatModel, tool_call


def test_athlete_round_trips_through_inputs():
    for c in CASES:
        assert athlete_from_inputs(c.inputs()) == c.athlete, c.name


def test_stub_names_and_order_match_the_real_binding():
    live = [t.name for t in stub_tools({"live": True})]
    assert live == ["query_training_db", *GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
    assert [t.name for t in stub_tools({"live": False})] == ["query_training_db"]
    coach = [t.name for t in stub_tools({"live": True, "extra_tools": list(EXTRA_TOOLS)})]
    assert coach == [*live, *EXTRA_TOOLS]
    only_extra = stub_tools({"live": False, "extra_tools": ["read_intake_vs_targets"]})
    assert [t.name for t in only_extra] == ["query_training_db", "read_intake_vs_targets"]


def test_stub_sql_description_equals_the_real_tool_and_arguments_are_named_like_the_real_ones():
    stubs = {t.name: t for t in stub_tools({"live": True, "extra_tools": list(EXTRA_TOOLS)})}
    real = make_query_tool("postgresql://unused/db")
    assert stubs["query_training_db"].description == real.description
    assert set(stubs["query_training_db"].args) == set(real.args) == {"sql"}
    assert set(stubs["get_activity"].args) == {"activity_id"}
    assert set(stubs["get_activity_splits"].args) == {"activity_id"}
    assert set(stubs["get_training_readiness"].args) == {"date"}
    assert set(stubs["get_hrv_data"].args) == {"date"}
    assert set(stubs["tp_get_workout"].args) == {"workout_id"}
    assert set(stubs["read_body_composition"].args) == {"days"}
    assert set(stubs["read_intake_vs_targets"].args) == {"days"}
    for name, t in stubs.items():
        assert t.description.strip(), name


def test_every_case_only_cans_results_for_tools_it_binds():
    for c in CASES:
        bound = {t.name for t in stub_tools(c.inputs())}
        assert set(c.tool_results) <= bound, c.name


def test_canned_serves_in_order_repeats_the_last_and_defaults_to_empty():
    canned = Canned({"query_training_db": ["[1]", "[2]"]})
    assert [canned("query_training_db") for _ in range(3)] == ["[1]", "[2]", "[2]"]
    assert canned("get_activity") == "[]"


async def test_stubs_answer_from_the_case():
    c = case("run_intervals")
    stubs = {t.name: t for t in stub_tools(c.inputs())}
    assert await stubs["query_training_db"].ainvoke({"sql": "select 1"}) == c.tool_results["query_training_db"][0]
    assert await stubs["get_activity_splits"].ainvoke({"activity_id": "g-1502"}) == c.tool_results["get_activity_splits"][0]
    assert await stubs["tp_get_workout"].ainvoke({"workout_id": "w"}) == "[]"


async def test_target_returns_the_calls_and_the_final_answer():
    c = case("run_intervals")
    model = ScriptedChatModel(
        script=[
            tool_call("query_training_db", {"sql": "select * from workouts where workout_date = '2026-09-15'"}, "c1"),
            tool_call("get_activity_splits", {"activity_id": "g-1502"}, "c2"),
            AIMessage(content="Reps 1-4 held 4:10-4:18/km; 5 and 6 drifted to 4:24 and 4:32."),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert model.calls == 3
    assert [x["name"] for x in out["calls"]] == ["query_training_db", "get_activity_splits"]
    assert out["calls"][1]["args"] == {"activity_id": "g-1502"}
    assert out["answer"].startswith("Reps 1-4 held")


async def test_target_propagates_an_exception_so_langsmith_records_an_error():
    c = case("last_z2_ride")
    with pytest.raises(IndexError):
        await make_target(ScriptedChatModel(script=[]))(c.inputs())
```

Append to `packages/tri-analyze/tests/test_live_tools.py`:

```python
@pytest.mark.live
async def test_live_stub_argument_names_equal_the_real_tools():
    from tri_analyze.evals.target import stub_tools

    stubs = {t.name: t for t in stub_tools({"live": True})}
    async with open_live_tools(Settings(), print) as tools:
        for real in tools:
            assert set(stubs[real.name].args) == set(real.args), real.name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.evals.target'`.

- [ ] **Step 3: Write `target.py`**

`packages/tri-analyze/src/tri_analyze/evals/target.py`:

```python
"""The function under evaluation: the real analyst agent over stub tools that answer from the
case's canned results. No database, no MCP servers. Exceptions propagate so LangSmith records
the example as errored."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool

from tri_analyze.agent import build_agent
from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.repl import text_of
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool

TARGET_RECURSION_LIMIT = 30
SQL_DESCRIPTION = make_query_tool("postgresql://unused/db").description
LIVE_DESCRIPTIONS = {
    "get_activity": "A Garmin activity summary by activity_id.",
    "get_activity_splits": "Lap and interval detail for a Garmin activity by activity_id.",
    "get_training_readiness": "Garmin training readiness for a date (YYYY-MM-DD).",
    "get_hrv_data": "Garmin overnight HRV for a date (YYYY-MM-DD).",
    "tp_get_workout": "One TrainingPeaks workout with its structure and comments, by workout_id.",
}
EXTRA_DESCRIPTIONS = {
    "read_body_composition": (
        "Index-scale readings for the last `days` days: date, weight_kg, body_fat_pct, "
        "muscle_mass_kg, oldest first."
    ),
    "read_intake_vs_targets": (
        "Logged intake against the nutrition targets for the last `days` days, one row per day."
    ),
}


def athlete_from_inputs(inputs: dict[str, Any]) -> AthleteContext:
    """The inverse of EvalCase.inputs(): ISO strings back to dates."""
    a = inputs["athlete"]
    return AthleteContext(
        today=date.fromisoformat(str(a["today"])),
        profile=a.get("profile"),
        recent_days=[
            {**r, "metric_date": date.fromisoformat(str(r["metric_date"]))}
            for r in a.get("recent_days") or []
        ],
        recent_workouts=[
            {**w, "workout_date": date.fromisoformat(str(w["workout_date"]))}
            for w in a.get("recent_workouts") or []
        ],
    )


class Canned:
    """Serves each tool's responses in call order, repeating the last; "[]" when none."""

    def __init__(self, results: dict[str, list[str]]) -> None:
        self.results = {k: list(v) for k, v in results.items() if v}
        self.served: dict[str, int] = defaultdict(int)

    def __call__(self, name: str) -> str:
        queue = self.results.get(name) or ["[]"]
        i = min(self.served[name], len(queue) - 1)
        self.served[name] += 1
        return queue[i]


def stub_tools(inputs: dict[str, Any]) -> list[BaseTool]:
    """query_training_db (real description), the five live tools when `live`, then each name in
    `extra_tools`. Same names, argument names and order as the real binding."""
    canned = Canned(inputs.get("tool_results") or {})

    async def query_training_db(sql: str) -> str:
        return canned("query_training_db")

    async def get_activity(activity_id: str) -> str:
        return canned("get_activity")

    async def get_activity_splits(activity_id: str) -> str:
        return canned("get_activity_splits")

    async def get_training_readiness(date: str) -> str:
        return canned("get_training_readiness")

    async def get_hrv_data(date: str) -> str:
        return canned("get_hrv_data")

    async def tp_get_workout(workout_id: str) -> str:
        return canned("tp_get_workout")

    async def read_body_composition(days: int = 28) -> str:
        return canned("read_body_composition")

    async def read_intake_vs_targets(days: int = 7) -> str:
        return canned("read_intake_vs_targets")

    live_fns: dict[str, Callable[..., Awaitable[str]]] = {
        "get_activity": get_activity,
        "get_activity_splits": get_activity_splits,
        "get_training_readiness": get_training_readiness,
        "get_hrv_data": get_hrv_data,
        "tp_get_workout": tp_get_workout,
    }
    extra_fns: dict[str, Callable[..., Awaitable[str]]] = {
        "read_body_composition": read_body_composition,
        "read_intake_vs_targets": read_intake_vs_targets,
    }

    def make(fn: Callable[..., Awaitable[str]], name: str, description: str) -> BaseTool:
        return StructuredTool.from_function(coroutine=fn, name=name, description=description)

    tools = [make(query_training_db, "query_training_db", SQL_DESCRIPTION)]
    if inputs.get("live"):
        tools += [
            make(live_fns[n], n, LIVE_DESCRIPTIONS[n]) for n in [*GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
        ]
    tools += [make(extra_fns[n], n, EXTRA_DESCRIPTIONS[n]) for n in inputs.get("extra_tools") or []]
    return tools


async def run_case(model: BaseChatModel, inputs: dict[str, Any]) -> dict[str, Any]:
    agent = build_agent(model, stub_tools(inputs))
    out = await agent.ainvoke(
        {"messages": [HumanMessage(str(inputs["question"]))]},
        {
            "configurable": {"thread_id": f"eval-{uuid4()}"},
            "recursion_limit": TARGET_RECURSION_LIMIT,
            "tags": ["eval"],
        },
        context=athlete_from_inputs(inputs),
    )
    messages = out["messages"]
    calls = [
        {"name": tc["name"], "args": tc["args"]}
        for m in messages
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    ]
    answer = next(
        (text_of(m) for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls),
        "",
    )
    return {"calls": calls, "answer": answer}


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(model, inputs)

    return target
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py packages/tri-analyze/tests/test_live_tools.py -q`
Expected: `11 passed, 2 skipped` (the two live tests).

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/evals/target.py packages/tri-analyze/tests/test_evals.py packages/tri-analyze/tests/test_live_tools.py
git commit -m "feat(analyze): eval target runs the analyst over stub tools with canned results"
```

---

### Task 3: Code checks

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (the judge is added in Task 4)
- Modify: `packages/tri-analyze/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: the target's output shape `{"calls": [{name, args}], "answer": str}` and `EvalCase.outputs()`.
- Produces: `uses_sql(outputs, reference_outputs) -> dict`; `pulls_splits(inputs, outputs, reference_outputs) -> dict`; `states_window(outputs, reference_outputs) -> dict`; `WINDOW_PATTERNS`. Each returns `{"key", "score" (1, 0 or None), "comment"}`. Task 5 consumes these.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-analyze/tests/test_evals.py`:

```python
from tri_analyze.evals.evaluators import pulls_splits, states_window, uses_sql


def calls(*names: str) -> dict:
    return {"calls": [{"name": n, "args": {}} for n in names], "answer": ""}


def test_uses_sql_pass_fail_and_not_applicable():
    ref = case("last_z2_ride").outputs()
    assert uses_sql(calls("query_training_db", "get_activity"), ref) == {
        "key": "uses_sql",
        "score": 1,
        "comment": "1 query_training_db call(s)",
    }
    assert uses_sql(calls("get_activity"), ref)["score"] == 0
    assert uses_sql(calls(), case("go_hard_today").outputs())["score"] is None


def test_pulls_splits_pass_fail_and_not_applicable():
    live = case("run_intervals")
    assert pulls_splits(live.inputs(), calls("query_training_db", "get_activity_splits"), live.outputs())["score"] == 1
    r = pulls_splits(live.inputs(), calls("query_training_db", "get_activity"), live.outputs())
    assert r["score"] == 0 and r["key"] == "pulls_splits"
    no_live = case("intervals_no_live")
    assert pulls_splits(no_live.inputs(), calls("query_training_db"), no_live.outputs())["score"] is None
    plain = case("last_z2_ride")
    assert pulls_splits(plain.inputs(), calls("query_training_db"), plain.outputs())["score"] is None


def test_states_window_accepts_iso_month_day_and_relative_windows():
    ref = case("weekly_tss_8w").outputs()

    def answer(text: str) -> dict:
        return {"calls": [], "answer": text}

    for text in (
        "Weeks from 2026-07-20 to 2026-09-13: TSS rose from 388 to 470.",
        "Between Jul 20 and Sep 13 the weekly TSS climbed steadily.",
        "Over the last 8 weeks TSS averaged 412.",
        "Looking at the past two months, volume grew.",
        "Since 20 July the trend is up.",
    ):
        assert states_window(answer(text), ref)["score"] == 1, text
    r = states_window(answer("TSS averaged 412 with one recovery week."), ref)
    assert r["score"] == 0 and r["key"] == "states_window"
    assert states_window(answer("anything"), case("last_z2_ride").outputs())["score"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.evals.evaluators'`.

- [ ] **Step 3: Write the code checks**

`packages/tri-analyze/src/tri_analyze/evals/evaluators.py`:

```python
"""Evaluators over one analyst answer: three code checks over the tool calls and the answer
(SQL for data questions, splits for interval questions, a stated window for trends) and, in
make_judge, an LLM judge for grounding and feedback quality. A check that does not apply to a
case scores None, which the pass rate leaves out."""

from __future__ import annotations

import re
from typing import Any

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
WINDOW_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date
    re.compile(  # month and day, either order: "Sep 13", "September 13th", "13 September"
        rf"\b{_MONTH}\.? {_DAY}\b|\b{_DAY} {_MONTH}\b", re.IGNORECASE
    ),
    re.compile(  # relative window: "last 8 weeks", "past two months", "previous 30 days"
        r"\b(?:last|past|previous) (?:\d+|two|three|four|five|six|seven|eight|nine|ten|twelve)"
        r" (?:days?|weeks?|months?)\b",
        re.IGNORECASE,
    ),
)


def _names(outputs: dict[str, Any]) -> list[str]:
    return [str(c["name"]) for c in outputs.get("calls") or []]


def uses_sql(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("requires_sql"):
        return {"key": "uses_sql", "score": None, "comment": "SQL not required"}
    n = _names(outputs).count("query_training_db")
    return {"key": "uses_sql", "score": int(n > 0), "comment": f"{n} query_training_db call(s)"}


def pulls_splits(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not (reference_outputs.get("requires_splits") and inputs.get("live")):
        return {
            "key": "pulls_splits",
            "score": None,
            "comment": "splits not required, or no live tools bound",
        }
    n = _names(outputs).count("get_activity_splits")
    return {
        "key": "pulls_splits",
        "score": int(n > 0),
        "comment": f"{n} get_activity_splits call(s)",
    }


def states_window(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("expects_window"):
        return {"key": "states_window", "score": None, "comment": "no window expected"}
    answer = str(outputs.get("answer") or "")
    hit: str | None = None
    for pattern in WINDOW_PATTERNS:
        match = pattern.search(answer)
        if match:
            hit = match.group(0)
            break
    return {
        "key": "states_window",
        "score": int(hit is not None),
        "comment": f"window: {hit}" if hit else "no date or relative window in the answer",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/evals/evaluators.py packages/tri-analyze/tests/test_evals.py
git commit -m "feat(analyze): uses_sql, pulls_splits and states_window code checks"
```

---

### Task 4: The judge

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (append)
- Modify: `packages/tri-analyze/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `render_system_prompt`, `FEEDBACK_RULES` (plan 1), `athlete_from_inputs`, `stub_tools` (Task 2), `langsmith.evaluation.EvaluationResult / EvaluationResults`.
- Produces: `FeedbackJudgement` (pydantic); `JUDGE_SYSTEM`; `render_judge_prompt(inputs, outputs) -> str`; `make_judge(model) -> AsyncEvaluator` where the evaluator is `async (inputs, outputs, reference_outputs) -> EvaluationResults` with keys `grounded` and `feedback_quality`. Task 5 consumes `make_judge`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-analyze/tests/test_evals.py`:

```python
from tri_analyze.evals.evaluators import FeedbackJudgement, make_judge, render_judge_prompt
from tri_analyze.prompts.analyst import FEEDBACK_RULES


def verdict(**over) -> dict:
    base = {
        "grounded": True,
        "covers_rules": True,
        "uses_athlete_comments": True,
        "concrete_takeaways": True,
        "no_generic_encouragement": True,
        "problems": [],
    }
    base.update(over)
    return base


def test_judge_prompt_carries_the_rendered_system_prompt_question_results_and_answer():
    c = case("threshold_rpe9")
    text = render_judge_prompt(c.inputs(), {"calls": [], "answer": "Third rep fell apart."})
    assert "Today is 2026-09-16." in text and FEEDBACK_RULES in text
    assert "Tools bound this session: query_training_db, get_activity, get_activity_splits" in text
    assert c.question in text
    assert "Legs were dead from the start" in text  # the canned SQL row
    assert text.rstrip().endswith("Third rep fell apart.")
    bare = render_judge_prompt(case("trend_no_data").inputs(), {"calls": [], "answer": ""})
    assert "Tool results:\n(none)" in bare


async def test_judge_scores_grounded_and_feedback_quality_for_a_session():
    c = case("threshold_rpe9")
    judge = make_judge(
        ScriptedChatModel(
            script=[tool_call("FeedbackJudgement", verdict(uses_athlete_comments=False, problems=["ignores the athlete's comment"]))]
        )
    )
    res = await judge(c.inputs(), {"calls": [], "answer": "A hard ride."}, c.outputs())
    by_key = {r.key: r for r in res["results"]}
    assert set(by_key) == {"grounded", "feedback_quality"}
    assert by_key["grounded"].score == 1
    assert by_key["feedback_quality"].score == 0
    assert "ignores the athlete's comment" in str(by_key["feedback_quality"].comment)


async def test_judge_skips_feedback_quality_outside_session_reviews():
    c = case("weekly_tss_8w")
    judge = make_judge(ScriptedChatModel(script=[tool_call("FeedbackJudgement", verdict(grounded=False, problems=["470 is not in the data"]))]))
    res = await judge(c.inputs(), {"calls": [], "answer": "TSS peaked at 470."}, c.outputs())
    by_key = {r.key: r for r in res["results"]}
    assert by_key["grounded"].score == 0 and "470 is not in the data" in str(by_key["grounded"].comment)
    assert by_key["feedback_quality"].score is None
    assert by_key["feedback_quality"].comment == "not a session review"


async def test_a_raising_judge_scores_both_keys_zero_with_the_error():
    c = case("last_z2_ride")
    res = await make_judge(ScriptedChatModel(script=[]))(c.inputs(), {"calls": [], "answer": "x"}, c.outputs())
    for r in res["results"]:
        assert r.score == 0 and str(r.comment).startswith("judge failed: IndexError")
    assert {r.key for r in res["results"]} == {"grounded", "feedback_quality"}
    assert FeedbackJudgement.model_fields.keys() == verdict().keys()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: FAIL with `ImportError: cannot import name 'FeedbackJudgement'`.

- [ ] **Step 3: Append the judge to `evaluators.py`**

Add these imports at the top of `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (keep them sorted; `ruff format` and `ruff check --fix` will order them):

```python
from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith.evaluation import EvaluationResult, EvaluationResults
from pydantic import BaseModel, Field

from tri_analyze.evals.target import athlete_from_inputs, stub_tools
from tri_analyze.prompts.analyst import render_system_prompt
```

and append to the module:

```python
AsyncEvaluator = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], Awaitable[EvaluationResults]
]


class FeedbackJudgement(BaseModel):
    grounded: bool = Field(
        description=(
            "every number in the answer appears in the system prompt's context or in the tool "
            "results, and data that is missing is stated as missing rather than guessed"
        )
    )
    covers_rules: bool = Field(
        description=(
            "for a session review: planned vs actual, execution quality, load context "
            "(week position, CTL/ATL/TSB, sleep, HRV, readiness), the athlete's comments and "
            "RPE when present, and takeaways are all covered; true for a non-session answer"
        )
    )
    uses_athlete_comments: bool = Field(
        description=(
            "when the tool results carry athlete comments, feeling or RPE, the answer uses "
            "them; true when there are none"
        )
    )
    concrete_takeaways: bool = Field(
        description="one or two concrete takeaways for the next similar session"
    )
    no_generic_encouragement: bool = Field(
        description="no filler praise or generic encouragement"
    )
    problems: list[str] = Field(description="one line per ungrounded number or missing element")


JUDGE_SYSTEM = """\
You audit one answer a triathlon coach's analyst gave to an athlete. You are given the
analyst's system prompt (the athlete's context, the bound tools and the feedback rules), the
athlete's question, the tool results the analyst received, and the analyst's answer.

Grounded: every number in the answer (durations, distances, watts, paces, heart rates, TSS,
scores, dates) appears in the system prompt's context or in the tool results, possibly after
a unit conversion or an arithmetic step you can verify; when the tool results are empty or
lack what the question needs, the answer says so instead of inventing figures.

Feedback quality applies to a session review: the five feedback rules are covered, the
athlete's own comments, feeling and RPE are used when the tool results carry them, there are
one or two concrete takeaways for the next similar session, and there is no generic
encouragement. Judge the answer's text literally; return a FeedbackJudgement."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any]) -> str:
    system = render_system_prompt(
        athlete_from_inputs(inputs), [t.name for t in stub_tools(inputs)]
    )
    results = inputs.get("tool_results") or {}
    rendered = "\n".join(
        f"{name}:\n" + "\n".join(str(r) for r in responses) for name, responses in results.items()
    )
    return (
        f"Analyst system prompt:\n{system}\n\n"
        f"Question:\n{inputs.get('question', '')}\n\n"
        f"Tool results:\n{rendered or '(none)'}\n\n"
        f"Answer:\n{outputs.get('answer') or ''}"
    )


def make_judge(model: BaseChatModel) -> AsyncEvaluator:
    """One structured-output call per example, scoring `grounded` always and
    `feedback_quality` for session reviews. A judge call that raises scores both keys 0 with the
    error as the comment."""
    judge = model.with_structured_output(FeedbackJudgement)

    async def feedback_judge(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> EvaluationResults:
        session = reference_outputs.get("kind") == "session"
        try:
            out = await judge.ainvoke(
                [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, outputs))]
            )
            assert isinstance(out, FeedbackJudgement)
        except Exception as exc:
            comment = f"judge failed: {type(exc).__name__}: {exc}"
            return {
                "results": [
                    EvaluationResult(key="grounded", score=0, comment=comment),
                    EvaluationResult(key="feedback_quality", score=0, comment=comment),
                ]
            }
        problems = "; ".join(out.problems) or "ok"
        quality = (
            out.covers_rules
            and out.uses_athlete_comments
            and out.concrete_takeaways
            and out.no_generic_encouragement
        )
        return {
            "results": [
                EvaluationResult(key="grounded", score=int(out.grounded), comment=problems),
                EvaluationResult(
                    key="feedback_quality",
                    score=int(quality) if session else None,
                    comment=problems if session else "not a session review",
                ),
            ]
        }

    return feedback_judge
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: `17 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run ruff check --fix packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/evals/evaluators.py packages/tri-analyze/tests/test_evals.py
git commit -m "feat(analyze): LLM judge scores grounded and feedback_quality from one structured call"
```

---

### Task 5: Dataset and runner

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/evals/run.py`
- Modify: `packages/tri-analyze/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `CASES` (Task 1), `make_target` (Task 2), `uses_sql`, `pulls_splits`, `states_window`, `make_judge` (Tasks 3, 4), `PROMPT_VERSION` (plan 1), `AnalyzeSettings` (plan 1), `langsmith.Client`, `langsmith.aevaluate`.
- Produces: `DATASET_NAME = "tri_analyze_feedback"`; `DATASET_DESCRIPTION`; `case_examples() -> list[dict]`; `ensure_dataset(client, *, recreate=False)`; `pass_rates(rows) -> dict[str, float]`; `render_pass_rates(rates, n) -> str`; `errored(rows) -> int`; `run_eval(settings, model, *, judge=True, prefix=None, recreate=False, log=print) -> tuple[dict[str, float], int]`. Task 6 consumes `run_eval`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-analyze/tests/test_evals.py`:

```python
from types import SimpleNamespace

from tri_analyze.evals.run import (
    DATASET_NAME,
    case_examples,
    ensure_dataset,
    errored,
    pass_rates,
    render_pass_rates,
)


class FakeClient:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.created: list[str] = []
        self.examples: list[dict] = []
        self.deleted = 0

    def has_dataset(self, dataset_name):
        return dataset_name in self.names

    def delete_dataset(self, dataset_name):
        self.names.discard(dataset_name)
        self.deleted += 1

    def create_dataset(self, name, description):
        self.names.add(name)
        self.created.append(name)

    def create_examples(self, dataset_name, examples):
        self.examples += examples


def test_dataset_examples_are_created_once_and_recreated_on_request():
    examples = case_examples()
    assert DATASET_NAME == "tri_analyze_feedback" and len(examples) == len(CASES)
    assert examples[0]["inputs"] == CASES[0].inputs()
    assert examples[0]["outputs"] == CASES[0].outputs()
    assert examples[0]["metadata"] == {"case": CASES[0].name}
    client = FakeClient()
    ensure_dataset(client)
    ensure_dataset(client)
    assert client.created == [DATASET_NAME] and len(client.examples) == len(CASES)
    ensure_dataset(client, recreate=True)
    assert client.deleted == 1 and client.created == [DATASET_NAME, DATASET_NAME]


def test_pass_rates_skip_none_and_rendering_names_the_prompt_version():
    def R(key, score):
        return SimpleNamespace(key=key, score=score)

    rows = [
        {"evaluation_results": {"results": [R("uses_sql", 1), R("pulls_splits", None), R("grounded", 0)]}},
        {"evaluation_results": {"results": [R("uses_sql", 0), R("pulls_splits", 1), R("grounded", 1)]}},
    ]
    rates = pass_rates(rows)
    assert rates == {"uses_sql": 0.5, "pulls_splits": 1.0, "grounded": 0.5}
    text = render_pass_rates(rates, 2)
    assert text.startswith("pass rate over 2 examples (prompt version 1):")
    assert "uses_sql" in text and "50%" in text and "100%" in text


def test_errored_counts_rows_whose_run_carries_an_error():
    rows = [
        {"run": SimpleNamespace(error=None)},
        {"run": SimpleNamespace(error="IndexError: list index out of range")},
        {"run": SimpleNamespace(error="")},
    ]
    assert errored(rows) == 1 and errored([]) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.evals.run'`.

- [ ] **Step 3: Write `run.py`**

`packages/tri-analyze/src/tri_analyze/evals/run.py`:

```python
"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import CASES
from tri_analyze.evals.evaluators import make_judge, pulls_splits, states_window, uses_sql
from tri_analyze.evals.target import make_target
from tri_analyze.prompts.analyst import PROMPT_VERSION

DATASET_NAME = "tri_analyze_feedback"
DATASET_DESCRIPTION = (
    "Analyst questions (question, athlete context, bound tools, canned tool results) with the "
    "flags the checks read. Evaluators: uses_sql, pulls_splits, states_window, and an LLM judge "
    "for grounded and feedback_quality."
)


def case_examples() -> list[dict[str, Any]]:
    return [
        {"inputs": c.inputs(), "outputs": c.outputs(), "metadata": {"case": c.name}} for c in CASES
    ]


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples())


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


def errored(rows: list[dict[str, Any]]) -> int:
    """Examples whose target raised: LangSmith keeps the run with its error text."""
    return sum(1 for row in rows if getattr(row.get("run"), "error", None))


async def run_eval(
    settings: AnalyzeSettings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model},
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    dict_rows = [dict(r) for r in rows]
    rates = pass_rates(dict_rows)
    errors = errored(dict_rows)
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    if errors:
        log(f"{errors} errored")
    return rates, errors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -q`
Expected: `20 passed`.

- [ ] **Step 5: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/evals/run.py packages/tri-analyze/tests/test_evals.py
git commit -m "feat(analyze): tri_analyze_feedback dataset and the analyst-v<PROMPT_VERSION> experiment runner"
```

---

### Task 6: `tri-analyze eval`

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/cli.py` (append the command; update the module docstring)
- Modify: `packages/tri-analyze/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `run_eval` (Task 5), `make_model`, `get_analyze_settings`, `console`, `_out`.
- Produces: `eval [--prefix NAME] [--recreate-dataset]` exiting 2 (missing key), 1 (any rate below 1.0, no rates, or any errored example), else 0.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-analyze/tests/test_cli.py`:

```python
def test_help_lists_eval():
    result = runner.invoke(app, ["--help"])
    assert "eval" in result.output


def test_eval_exits_2_without_langsmith_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "LANGSMITH_API_KEY" in result.output


def test_eval_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key=None, langsmith_api_key="ls"),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_eval_exit_code_follows_rates_and_errors(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen: list[dict] = []

    def stub(rates, errors):
        async def run_eval(settings, model, **kw):
            seen.append(kw)
            kw["log"]("experiment: analyst-v1-test")
            return rates, errors

        monkeypatch.setattr("tri_analyze.evals.run.run_eval", run_eval)

    stub({"uses_sql": 1.0, "grounded": 1.0}, 0)
    result = runner.invoke(app, ["eval", "--prefix", "try", "--recreate-dataset"])
    assert result.exit_code == 0 and "experiment: analyst-v1-test" in result.output
    assert seen[-1]["prefix"] == "try" and seen[-1]["recreate"] is True
    stub({"uses_sql": 0.5, "grounded": 1.0}, 0)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({"uses_sql": 1.0}, 2)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({}, 0)
    assert runner.invoke(app, ["eval"]).exit_code == 1
    assert seen[-1]["prefix"] is None and seen[-1]["recreate"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_cli.py -q`
Expected: the four new tests FAIL (`eval` is not a command: `No such command 'eval'`, exit code 2 with usage text and no key name in the output).

- [ ] **Step 3: Add the command**

In `packages/tri-analyze/src/tri_analyze/cli.py`, change the module docstring to `"""Command-line entry points: chat and eval."""` and append before `if __name__ == "__main__":`:

```python
@app.command(name="eval")
def eval_cmd(
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default analyst-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate-dataset",
        help="Delete and re-create the LangSmith dataset from the cases in code",
    ),
) -> None:
    """Run the analyst over the feedback dataset in LangSmith and print the pass rate per
    evaluator (exit 1 when any evaluator is below 100% or any example errored)."""
    raise typer.Exit(code=asyncio.run(_eval(prefix=prefix, recreate=recreate)))


async def _eval(*, prefix: str | None, recreate: bool) -> int:
    from tri_analyze.evals.run import run_eval
    from tri_analyze.llm import make_model

    settings = get_analyze_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates, errors = await run_eval(
        settings,
        make_model(settings),
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and errors == 0 and all(r == 1.0 for r in rates.values()) else 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests/test_cli.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Run the real eval once (needs `LANGSMITH_API_KEY` and `ANTHROPIC_API_KEY` in `.env`)**

Run: `uv run tri-analyze eval`
Expected: it creates the dataset `tri_analyze_feedback` (12 examples), prints `experiment: analyst-v1-<suffix>` and the pass rate per key, and exits 0 or 1. Record the printed rates for the README in Task 7. If the run is not possible (no keys), say so in the task report and write `not run yet` in the README.

- [ ] **Step 6: Definition of done, then commit**

```bash
uv run ruff format packages/tri-analyze && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-analyze/src/tri_analyze/cli.py packages/tri-analyze/tests/test_cli.py
git commit -m "feat(analyze): tri-analyze eval runs the feedback dataset as experiment analyst-v<PROMPT_VERSION>"
```

---

### Task 7: Documentation and the Obsidian copies

**Files:**
- Modify: `packages/tri-analyze/README.md` (Commands, Layout, a new Evaluation section before Design decisions, an Observability line)
- Modify: `README.md` (root: table row, Run line, Layout line, Status bullet)
- Vault copies

- [ ] **Step 1: Package README**

In `packages/tri-analyze/README.md`:

1. Commands block becomes:
   ```
   uv run tri-analyze chat [--no-live]                    # /tools /prompt /sync /quit
   uv run tri-analyze eval [--prefix P] [--recreate-dataset]   # the LangSmith feedback eval
   ```
   and add this sentence to the paragraph below it:
   ```
   `eval` exits 2 when `LANGSMITH_API_KEY` or `ANTHROPIC_API_KEY` is unset, 1 when any
   evaluator is below 100% or any example errored, else 0.
   ```
2. Layout block: add after the `cli.py` line `  cli.py              chat, eval` (replacing the `chat` line) and add
   `  evals/              cases, target (stub tools), evaluators (code checks and the judge), run`.
3. Insert a new section before `## Design decisions`:

   ````markdown
   ## Evaluation

   `tri-analyze eval` runs the real agent (`build_agent`) over stub tools with canned results,
   so no database or MCP server is involved, on the LangSmith dataset `tri_analyze_feedback`
   (twelve cases in `evals/cases.py`: five session reviews, three trends, one readiness
   question and three edge cases: empty SQL, an interval question without live tools, a
   body-composition question with the coach's `read_body_composition` bound). The stubs carry
   the real tool names and argument names, and `query_training_db` carries the real
   description, so the model sees what it sees in production. Today is fixed at 2026-09-16.

   Evaluators (a check that does not apply scores nothing):

   | Key | Applies when | Passes when |
   |---|---|---|
   | `uses_sql` | the case needs data | at least one `query_training_db` call |
   | `pulls_splits` | an interval question with live tools | at least one `get_activity_splits` call |
   | `states_window` | a trend question | the answer names an ISO date, a month-and-day date, or a relative window such as "last 8 weeks" |
   | `grounded` | always (LLM judge) | every number in the answer is in the context or the tool results, and missing data is stated |
   | `feedback_quality` | session reviews (LLM judge) | the five feedback rules are covered, athlete comments and RPE are used, one or two concrete takeaways, no generic encouragement |

   The judge is one `with_structured_output(FeedbackJudgement)` call per example over the
   case's rendered system prompt, the question, the tool results and the answer. The
   experiment is `analyst-v<PROMPT_VERSION>` with `prompt_version` and `model` as metadata,
   so bump `PROMPT_VERSION` whenever the prompt text changes and compare runs. Latest run:
   not run yet.
   ````
   (Replace `not run yet` with the rates from Task 6 Step 5 when it ran.)
4. Add to the Knobs list:
   ```
   - **The eval disagrees with you:** the cases are in `evals/cases.py`; `--recreate-dataset`
     pushes edits to LangSmith.
   ```
5. In the "One question, end to end" section, append to the closing paragraph (the one that
   names project `tri_analyze`):
   ```
   Tags: `analyst` on every run, `chat` on REPL turns, `eval` on eval targets; under `tri-coach`
   the analyst's runs appear in `tri_coach` with the `analyst` tag.
   ```

- [ ] **Step 2: Root README**

1. Table row (line 9) becomes:
   ```
   | `packages/tri-analyze` | `tri_analyze` | `tri-analyze chat \| eval` | Analyst agent: feedback on completed sessions, trends. |
   ```
2. Run block: after the `tri-analyze chat` line add
   `uv run tri-analyze eval [--recreate-dataset]   # LangSmith feedback eval`
3. Layout line: `packages/tri-analyze/   src/tri_analyze/{config,cli,llm,agent,repo,repl,testing,allowlist,prompts,tools,evals}`
4. Status: replace the trailing `Eval pending (plan 2).` on the tri-analyze alignment bullet with:
   ```
   Eval (2026-09): `tri-analyze eval`, twelve cases, three code checks and a judge; tracked in
   `docs/superpowers/plans/2026-09-13-tri-analyze-02-eval.md`.
   ```

- [ ] **Step 3: Copy to the Obsidian vault**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp packages/tri-analyze/README.md "$V/packages/tri-analyze/readme.md"
cp README.md "$V/readme.md"
```

- [ ] **Step 4: Definition of done including the build, then commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv build --package tri-analyze
git add packages/tri-analyze/README.md README.md
git commit -m "docs(analyze): evaluation in the package README; root README row, run line and status"
```

---

## After the last task

1. Run the full definition of done once more from the worktree root and paste the counts into the merge message: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv build --package tri-analyze`.
2. Merge from the shared checkout once no other session is open: `git merge --no-ff feat/tri-analyze-02` on `main`, then `git worktree remove ../triathlon_agent-tri-analyze-02`.
3. Update the spec's Status line to `Implemented (plans 01 and 02 merged <date>)` and copy the spec to the vault.
4. Copy `.superpowers/` scratch to the vault's `.superpowers/sdd/2026-09-13-tri-analyze-02-eval/`.
