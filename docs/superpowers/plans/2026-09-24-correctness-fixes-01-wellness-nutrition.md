# Correctness fixes Plan 1 of 2: wellness and nutrition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the lab-result misreports and the nutrition maths and gates from the correctness-fixes spec, with migration 006.

**Architecture:** Every task is one spec row from `docs/superpowers/specs/2026-09-24-correctness-fixes-design.md` §2: a failing test that shows the defect, the smallest change that makes it pass, a commit. Nothing is refactored beyond the row. Plan 01 covers §2.1 (tri-wellness) and §2.2 (tri-nutrition) plus the migration; plan 02 covers the rest. The two plans are independent branches from main, plan 01 first.

**Tech Stack:** Python 3.12, uv workspace, LangChain 1.4 / LangGraph, langchain-anthropic 1.7.1, pydantic 2, psycopg 3 on Postgres 16, pytest with pytest-asyncio in auto mode, `tri_core.testing.ScriptedChatModel`, `RecordingScriptedModel` in tri-wellness.

**Spec:** `docs/superpowers/specs/2026-09-24-correctness-fixes-design.md`. This plan implements §2.1, §2.2 and §3. Plan 02 (`2026-09-24-correctness-fixes-02-planning-coach-core.md`) implements §2.3 to §2.6.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-fixes-01 -b feat/fixes-01 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout.
- **Baseline B:** run `uv run pytest -q` before Task 1. On `main` @ 4fa41df it is `996 passed, 6 skipped, 1 warning`. Record the actual number; every task's Definition of done expects it to rise by that task's new tests and never to lose a test except where the task says an existing test is rewritten.
- **The database is not yours to migrate.** Migration 006 is a file plan 01 writes; Brian applies it to `tri_analyze` and `tri_analyze_test`. Tests that need a 006 column or index probe for it (`to_regclass` or `information_schema.columns`) and skip until it is applied. When a task says 006 must be on the test database before a step, stop, print `docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/006_fixes.sql`, and ask Brian to run it; do not run it yourself.
- **Every "replace ... with" block is an exact string match against `main` @ 4fa41df.** If a block does not match, stop and report; do not improvise the edit.
- **Test rules:** fixtures keep their signatures. An existing assertion changes only where a task quotes the old test and shows the new one.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages scripts`
  2. `uv run ruff check --fix packages scripts`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing langsmith `DeprecationWarning`. `ruff check --fix` may reorder imports; accept its order. Never add `# type: ignore`.
- **Commits:** git commits are permitted (Brian's standing permission). Commit once per task on `feat/fixes-01`, ending every message with the executing model's attribution line (the `Co-Authored-By:` line the session's git attribution reminder gives).
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file edited is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Stop conditions

Stop and report to Brian without working around it if:
- a "replace" block does not match the current file;
- an existing assertion outside the tests a task names fails;
- a task needs a migration column this plan does not write.

---

## Tasks

1. Migration 006
2. W1 + W2, bound-aware lab values and lab references converted with the value
3. W3, alias lookup keeps parenthesised qualifiers
4. W4, dimensionless markers accept a missing unit
5. W5, block a re-ingest of the same file by its sha
6. W6, a multi-date CSV export is refused naming the dates
7. W7, edited review YAML with a repeated marker is a validation error
8. W8, a report truncated at `max_tokens` is not saved
9. W9, report prompt v2: disclaimer in code, practitioner-first priorities, no dosing
10. N1 brick legs share TSS with the bike leg only
11. N2 sodium and fluid 0 mean none
12. N3 `check-in --yes` skips violating changes and never approves a review it did not produce
13. N4 review persists overrides when there is nothing to review
14. N5 the stored race plan is matched by event date
15. N6 today's completed workouts stay in the horizon
16. N7 the title keeps id-less sessions on one day apart
17. N8 the deficit follows `target_date`, capped at `max_weekly_change_pct`
18. Final checks

---

### Task 1: Migration 006

**Files:**
- Create: `migrations/006_fixes.sql`
- Modify: `README.md` (the layout line)

**Interfaces:**
- Consumes: nothing.
- Produces: `lab_results.bound text`, `lab_panels.source_sha text` with `lab_panels_source_sha_idx`, `fuel_plans_kind_day_workout_title_idx` (replacing `fuel_plans_kind_day_workout_idx`), `training_goals.tp_plan_applied_at timestamptz`. Tasks 2, 5 and 16 of this plan and Task 2 of plan 02 read these.

- [ ] **Step 1: Write the migration**

Create `migrations/006_fixes.sql`:

```sql
-- 006_fixes.sql  (apply to tri_analyze and tri_analyze_test)
-- Correctness fixes, 2026-09-24: bounded lab values, panel file sha, fuel plans keyed by title
-- for id-less sessions, and the bought-plan adoption stamp.

alter table lab_results add column if not exists bound text;             -- '<', '<=', '>', '>='
alter table lab_panels add column if not exists source_sha text;          -- sha256 of the ingested file
create index if not exists lab_panels_source_sha_idx on lab_panels (source_sha);

drop index if exists fuel_plans_kind_day_workout_idx;
create unique index if not exists fuel_plans_kind_day_workout_title_idx
  on fuel_plans (kind, day, coalesce(tp_workout_id, ''), coalesce((payload->>'title'), ''));

alter table training_goals add column if not exists tp_plan_applied_at timestamptz;
```

- [ ] **Step 2: Check the file**

Run: `uv run python -c "import pathlib; s=pathlib.Path('migrations/006_fixes.sql').read_text(); assert s.count(';')==6, s.count(';'); print('ok')"`
Expected: `ok`. Do not apply it to any database; that is Brian's step.

- [ ] **Step 3: The README layout line**

In `README.md`, replace:

```
migrations/             001_initial.sql (sync tables), 002_planning.sql and 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables), 005_wellness.sql (lab tables)
```

with:

```
migrations/             001_initial.sql (sync tables), 002_planning.sql and 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables), 005_wellness.sql (lab tables), 006_fixes.sql (2026-09-24 correctness fixes)
```

Copy `README.md` to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/readme.md`.

- [ ] **Step 4: Commit**

```bash
git add migrations/006_fixes.sql README.md
git commit -m "db: migration 006, correctness fixes"
```

Then tell Brian: "Migration 006 is written. Tasks 2, 5 and 16 skip their db tests until it is on `tri_analyze_test`; apply it when convenient with `docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/006_fixes.sql`." Continue with Task 2 without waiting.

---

### Task 2: W1 + W2, bound-aware lab values and lab references converted with the value

W1 and W2 both rewrite the body of `normalize()`, so they are one task. Line numbers are `main` @ 4fa41df.

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/models.py:10-11, 36-45, 74-88, 121-131`
- Modify: `packages/tri-wellness/src/tri_wellness/labs/normalize.py:10-31, 47-51, 73-90`
- Modify: `packages/tri-wellness/src/tri_wellness/labs/evaluate.py:6-20, 111-114, 126-156`
- Modify: `packages/tri-wellness/src/tri_wellness/repo.py:57-77, 139-151, 161-182, 185-200`
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py:1-25, 59-67, 137-152, 195-222`
- Modify: `packages/tri-wellness/src/tri_wellness/prompts/report.py:152-188`
- Modify: `packages/tri-wellness/src/tri_wellness/evals/target.py:19-38`
- Test: `packages/tri-wellness/tests/test_normalize.py`, `test_evaluate.py`, `test_repo.py`, `test_report_prompt.py`, `test_repl.py` (append and edit)

**Interfaces:**
- Consumes: migration 006 column `lab_results.bound text` (assembler).
- Produces:
  - `tri_wellness.labs.models.Bound = Literal["<", "<=", ">", ">="]`; `PreviousValue = tuple[date, float, Bound | None]`
  - `ConventionalStatus` and `FunctionalStatus` gain `"indeterminate"`
  - `LabResult.bound: Bound | None = None`; `StoredResult.bound: Bound | None = None`
  - `Finding.bound: Bound | None = None`; `Finding.raw_value: str = ""` (default so stored findings written before this change still validate)
  - `normalize.parse_value(text) -> tuple[float, Bound | None] | None`; `normalize.bound_step(raw_value: str, value: float) -> float`; `normalize._ref(text, factor)` multiplies a lab reference by the same factor as the value
  - `evaluate.bounded_conventional_status(value, bound, step, lab_low, lab_high, spec) -> ConventionalStatus`; `evaluate.bounded_functional_status(value, bound, step, spec) -> FunctionalStatus`; `evaluate.evaluate(..., previous: dict[str, PreviousValue], ...)`
  - `repo.previous_values(conn, panel_id) -> dict[str, PreviousValue]`; `lab_results` insert and read carry `bound`
  - `repl.review_from_yaml` reads and validates a `bound` field per result row; `review_to_yaml` writes it; `render_review` shows `<0.3` in the value column
  - `prompts.report._finding_line` prints the bound with the value and `indeterminate (reported as <raw>)`

**Note for the assembler:** the spec's four examples are only consistent when the open end of a bound sits one printed unit inside it: strictly, `<1.0` is `[0, 1.0)`, which contains 0.95, and 0.95 is `high` against 0-0.9, so a literal reading gives `indeterminate` where the spec's test cell says `in_range`. `bound_step` gives the resolution the lab printed (`<1.0` -> 0.1, `<50` -> 1), so `<1.0` is evaluated at 0 and 0.9, `>60` at 61 and infinity. With that, all four spec cases hold. If a strict `[0, x)` reading is preferred instead, drop `bound_step`, evaluate the open end at `x` itself, and change the `tg_ab` assertion below to `indeterminate`. Also: `previous` becomes a 3-tuple everywhere (`repo.previous_values`, `evaluate`, `evals/target.parse_inputs`, four test files) because `delta_pct` must know whether the previous value was bounded; `Finding.previous` stays a 2-tuple. `marker_history` and `get_marker_history` still evaluate stored values as points; a bounded history row is out of this row's scope.

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_normalize.py`: change the import line

```python
from tri_wellness.labs.normalize import normalize, parse_value
```

to

```python
from tri_wellness.labs.normalize import bound_step, normalize, parse_value
```

Replace the five bounded rows of the `test_parse_value` table:

```python
        ("<5", (5.0, "value '<5' stored as bound 5")),
        ("< 0.5", (0.5, "value '< 0.5' stored as bound 0.5")),
        (">200", (200.0, "value '>200' stored as bound 200")),
        ("<=3", (3.0, "value '<=3' stored as bound 3")),
        ("≥ 60", (60.0, "value '≥ 60' stored as bound 60")),
```

with

```python
        ("<5", (5.0, "<")),
        ("< 0.5", (0.5, "<")),
        (">200", (200.0, ">")),
        ("<=3", (3.0, "<=")),
        ("≥ 60", (60.0, ">=")),
```

Replace

```python
def test_bounded_value_keeps_note_and_verbatim_raw(reg):
    [r] = normalize([raw("hs-CRP", "<0.3", "mg/L", None, "3.0", None)], reg).results
    assert r.value == 0.3 and r.note == "value '<0.3' stored as bound 0.3"
    assert r.raw.value == "<0.3" and r.lab_ref_low is None and r.lab_ref_high == 3.0
```

with

```python
def test_bounded_value_keeps_bound_and_verbatim_raw(reg):
    [r] = normalize([raw("hs-CRP", "<0.3", "mg/L", None, "3.0", None)], reg).results
    assert r.value == 0.3 and r.bound == "<" and r.note is None
    assert r.raw.value == "<0.3" and r.lab_ref_low is None and r.lab_ref_high == 3.0


@pytest.mark.parametrize(
    "text, value, step",
    [
        ("<1.0", 1.0, 0.1),
        ("> 60", 60.0, 1.0),
        ("<0.5", 5.0, 1.0),  # converted x10: the step scales with the value
        ("<=3", 3.0, 1.0),
        ("<1,000", 1000.0, 1.0),
        ("abc", 1.0, 0.0),
    ],
)
def test_bound_step(text, value, step):
    assert bound_step(text, value) == pytest.approx(step)


def test_lab_reference_converts_with_the_value(reg):
    [g] = normalize([raw("Glucose", "5.2", "mmol/L", "3.9", "5.8")], reg).results
    assert g.unit == "mg/dL" and g.value == pytest.approx(93.6946, abs=1e-4)
    assert g.lab_ref_low == pytest.approx(70.271, abs=1e-3)
    assert g.lab_ref_high == pytest.approx(104.5056, abs=1e-3)
```

`packages/tri-wellness/tests/test_evaluate.py`: change the import block

```python
from tri_wellness.labs.evaluate import (
    active_confounders,
    conventional_status,
    evaluate,
    functional_status,
)
```

to

```python
from tri_wellness.labs.evaluate import (
    active_confounders,
    bounded_conventional_status,
    bounded_functional_status,
    conventional_status,
    evaluate,
    functional_status,
)
```

Edit the three existing `previous=` arguments to 3-tuples: in `test_evaluate_builds_one_finding_per_result_with_only_declared_confounders` replace `previous={"ferritin": (date(2026, 3, 1), 35.0)},` with `previous={"ferritin": (date(2026, 3, 1), 35.0, None)},`; in `test_evaluate_delta_pct_rounding_and_zero_previous` replace `previous={"ferritin": (D, 45.0)},` with `previous={"ferritin": (D, 45.0, None)},` and `previous={"hs_crp": (D, 0.0)},` with `previous={"hs_crp": (D, 0.0, None)},`. Append:

```python
# ---- bounds ---------------------------------------------------------------------------------


def test_bounded_status_is_the_status_at_both_ends_or_indeterminate(reg):
    tg = reg.get("tg_ab")  # conventional {high: 0.9}, functional {high: 0.9}
    assert bounded_conventional_status(1.0, "<", 0.1, None, None, tg) == "in_range"
    assert bounded_functional_status(1.0, "<", 0.1, tg) == "optimal"
    egfr = reg.get("egfr")  # conventional {low: 60}
    assert bounded_conventional_status(60.0, ">", 1.0, None, None, egfr) == "in_range"
    fer = reg.get("ferritin")  # conventional 30-400 (male)
    assert bounded_conventional_status(15.0, "<", 1.0, None, None, fer) == "low"
    assert bounded_functional_status(15.0, "<", 1.0, fer) == "low"
    assert bounded_conventional_status(50.0, "<", 1.0, 30.0, 100.0, fer) == "indeterminate"
    assert bounded_conventional_status(42.0, None, 0.0, 30.0, 100.0, fer) == "in_range"


def bounded(marker, text, value, unit, lab_low=None, lab_high=None) -> LabResult:
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        bound=text[0],
        raw=RawResult(name=marker, value=text, unit=unit),
        lab_ref_low=lab_low,
        lab_ref_high=lab_high,
    )


def test_evaluate_carries_the_bound_and_drops_the_delta(reg):
    [crp] = evaluate(
        [bounded("hs_crp", "<0.3", 0.3, "mg/L")],
        reg,
        previous={"hs_crp": (D, 0.5, None)},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert crp.bound == "<" and crp.raw_value == "<0.3"
    assert crp.conventional_status == "in_range" and crp.functional_status == "optimal"
    assert crp.previous == (D, 0.5) and crp.delta_pct is None
    [again] = evaluate(
        [lr("hs_crp", 0.5, "mg/L")],
        reg,
        previous={"hs_crp": (D, 0.3, "<")},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert again.previous == (D, 0.3) and again.delta_pct is None  # bounded previous value
    [fer] = evaluate(
        [bounded("ferritin", "<50", 50.0, "ng/mL", 30.0, 100.0)],
        reg,
        previous={},
        context=FASTED_AM,
        training=quiet_training(),
    )
    assert fer.conventional_status == "indeterminate"
    assert fer.functional_status == "indeterminate"
```

`packages/tri-wellness/tests/test_repo.py`: in `test_results_roundtrip_and_lab_results_rebuild` replace

```python
    crp = lr(
        "hs_crp",
        0.3,
        "mg/L",
        raw=raw("hs-CRP", "<0.3", "mg/L", None, "3.0"),
        lab_ref_low=None,
        lab_ref_high=3.0,
    )
```

with

```python
    crp = lr(
        "hs_crp",
        0.3,
        "mg/L",
        raw=raw("hs-CRP", "<0.3", "mg/L", None, "3.0"),
        bound="<",
        lab_ref_low=None,
        lab_ref_high=3.0,
    )
```

and

```python
    c = stored[1]
    assert (c.raw_value, c.lab_ref_low, c.lab_ref_high) == ("<0.3", None, 3.0)
```

with

```python
    c = stored[1]
    assert (c.raw_value, c.bound, c.lab_ref_low, c.lab_ref_high) == ("<0.3", "<", None, 3.0)
    assert f.bound is None
```

and

```python
    assert rebuilt[0].raw.name == "Ferritin, Serum" and rebuilt[1].raw.value == "<0.3"
```

with

```python
    assert rebuilt[0].raw.name == "Ferritin, Serum" and rebuilt[1].raw.value == "<0.3"
    assert rebuilt[1].bound == "<" and rebuilt[0].bound is None
```

In `test_previous_values_and_marker_history` replace

```python
    assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0), "hs_crp": (D1, 0.5)}
    assert repo.previous_values(wdb, p3) == {"ferritin": (D2, 40.0), "hs_crp": (D1, 0.5)}
```

with

```python
    assert repo.previous_values(wdb, p2) == {
        "ferritin": (D1, 35.0, None),
        "hs_crp": (D1, 0.5, None),
    }
    assert repo.previous_values(wdb, p3) == {
        "ferritin": (D2, 40.0, None),
        "hs_crp": (D1, 0.5, None),
    }
```

and in `test_previous_values_same_day_uses_lower_id` replace `assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0)}` with `assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0, None)}`. Append:

```python
def test_previous_values_carry_the_bound(wdb):
    p1 = panel(wdb, D1, [lr("hs_crp", 0.3, "mg/L", bound="<")])
    p2 = panel(wdb, D2, [lr("hs_crp", 0.5, "mg/L")])
    assert repo.previous_values(wdb, p2) == {"hs_crp": (D1, 0.3, "<")}
    assert repo.previous_values(wdb, p1) == {}
```

`packages/tri-wellness/tests/test_report_prompt.py`: in the `findings` fixture replace `{"ferritin": (date(2026, 3, 1), 35.0)},` with `{"ferritin": (date(2026, 3, 1), 35.0, None)},`. Append:

```python
def test_findings_block_shows_bounded_values_as_printed(reg):
    tg = LabResult(
        marker="tg_ab",
        value=1.0,
        unit="IU/mL",
        bound="<",
        raw=RawResult(name="Thyroglobulin Antibody", value="<1.0", unit="IU/mL"),
    )
    fer = LabResult(
        marker="ferritin",
        value=50.0,
        unit="ng/mL",
        bound="<",
        raw=RawResult(name="Ferritin", value="<50", unit="ng/mL"),
        lab_ref_low=30.0,
        lab_ref_high=100.0,
    )
    fs = evaluate([tg, fer], reg, {}, PanelContext(fasting=True), TrainingContext(drawn_on=D))
    text = findings_block(fs, reg)
    assert "optimal: Thyroglobulin antibodies <1.0 IU/mL (up to 0.9)" in text
    assert (
        "- Ferritin: <50 ng/mL — indeterminate (reported as <50) "
        "(functional 50-150; conventional indeterminate)"
    ) in text
```

`packages/tri-wellness/tests/test_repl.py`: replace the helper and the hs_crp payload row

```python
def lr(marker, value, unit, name=None, low=None, high=None, flag=None, note=None):
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        raw=RawResult(name=name or marker, value=str(value), unit=unit, flag=flag),
        lab_ref_low=low,
        lab_ref_high=high,
        note=note,
    )
```

with

```python
def lr(marker, value, unit, name=None, low=None, high=None, flag=None, note=None, bound=None):
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        bound=bound,
        raw=RawResult(
            name=name or marker, value=f"{bound or ''}{value}", unit=unit, flag=flag
        ),
        lab_ref_low=low,
        lab_ref_high=high,
        note=note,
    )
```

and

```python
            lr(
                "hs_crp", 0.3, "mg/L", "hs-CRP", None, 3.0, note="value '<0.3' stored as bound 0.3"
            ).model_dump(mode="json"),
```

with

```python
            lr("hs_crp", 0.3, "mg/L", "hs-CRP", None, 3.0, bound="<").model_dump(mode="json"),
```

In `test_render_review_table_unmapped_duplicates_and_error` replace

```python
    assert "Ferritin, Serum" in text and "hs-CRP" in text and "-3" in text  # one-sided lab range
```

with

```python
    assert "Ferritin, Serum" in text and "hs-CRP" in text and "-3" in text  # one-sided lab range
    assert "<0.3" in text  # a bounded value shows its bound
```

In `test_yaml_round_trip_and_validation` replace

```python
    with pytest.raises(ValueError, match="drawn_on"):
        review_from_yaml(text.replace("2026-08-20", "yesterday"), reg)
```

with

```python
    with pytest.raises(ValueError, match="drawn_on"):
        review_from_yaml(text.replace("2026-08-20", "yesterday"), reg)
    assert "bound: <" in text
    with pytest.raises(ValueError, match=r"results\[1\].*bound"):
        review_from_yaml(text.replace("bound: <", "bound: about"), reg)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_normalize.py packages/tri-wellness/tests/test_evaluate.py packages/tri-wellness/tests/test_repo.py packages/tri-wellness/tests/test_report_prompt.py packages/tri-wellness/tests/test_repl.py -q`
Expected: `ImportError` on `bound_step` and `bounded_conventional_status` (the two modules fail to collect); in test_repo `pydantic ValidationError: bound  Extra inputs are not permitted`; in test_repl `ValidationError` on `bound` in `lr`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/labs/models.py`, replace:

```python
ConventionalStatus = Literal["low", "in_range", "high"]
FunctionalStatus = Literal["low", "suboptimal_low", "optimal", "suboptimal_high", "high"]
```

with:

```python
ConventionalStatus = Literal["low", "in_range", "high", "indeterminate"]
FunctionalStatus = Literal[
    "low", "suboptimal_low", "optimal", "suboptimal_high", "high", "indeterminate"
]
Bound = Literal["<", "<=", ">", ">="]  # the lab printed '<x' or '>x': the value is an interval
PreviousValue = tuple[date, float, Bound | None]
```

replace:

```python
    marker: str
    value: float
    unit: str
    raw: RawResult
    lab_ref_low: float | None = None
    lab_ref_high: float | None = None
    note: str | None = None
```

with:

```python
    marker: str
    value: float
    unit: str
    raw: RawResult
    bound: Bound | None = None
    lab_ref_low: float | None = None
    lab_ref_high: float | None = None
    note: str | None = None
```

replace:

```python
    value: float
    unit: str
    conventional_status: ConventionalStatus
    functional_status: FunctionalStatus
    functional_range: tuple[float | None, float | None]
    previous: tuple[date, float] | None = None
```

with:

```python
    value: float
    unit: str
    bound: Bound | None = None
    raw_value: str = ""  # what the lab printed; shown for bounded rows
    conventional_status: ConventionalStatus
    functional_status: FunctionalStatus
    functional_range: tuple[float | None, float | None]
    previous: tuple[date, float] | None = None
```

and in `StoredResult` replace:

```python
    lab_ref_low: float | None
    lab_ref_high: float | None
    flag: str | None
```

with:

```python
    lab_ref_low: float | None
    lab_ref_high: float | None
    flag: str | None
    bound: Bound | None = None
```

In `packages/tri-wellness/src/tri_wellness/labs/normalize.py`, replace:

```python
from tri_wellness.labs.models import LabResult, NormalizeResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

_BOUND_PREFIXES = ("<=", ">=", "≤", "≥", "<", ">")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")  # e.g. '1,234.5'; '5,2' does not match


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)


def parse_value(text: str) -> tuple[float, str | None] | None:
    """'42' -> (42.0, None); '<5' -> (5.0, note); '1,234.5' -> (1234.5, None); 'Not detected',
    '5,2' (an ambiguous comma) and '-5' (no marker is negative) -> None."""
    s = text.strip()
    prefix = next((p for p in _BOUND_PREFIXES if s.startswith(p)), None)
    body = s[len(prefix) :].strip() if prefix else s
    if _THOUSANDS.match(body):
        body = body.replace(",", "")
    if body.startswith("-") or not _NUMBER.match(body):
        return None
    n = float(body)
    note = f"value '{s}' stored as bound {_fmt(n)}" if prefix else None
    return n, note
```

with:

```python
from tri_wellness.labs.models import Bound, LabResult, NormalizeResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

# Longest prefixes first so '<=' is not read as '<'.
_BOUNDS: dict[str, Bound] = {"<=": "<=", ">=": ">=", "≤": "<=", "≥": ">=", "<": "<", ">": ">"}
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")  # e.g. '1,234.5'; '5,2' does not match


def _split_bound(text: str) -> tuple[str | None, str]:
    s = text.strip()
    prefix = next((p for p in _BOUNDS if s.startswith(p)), None)
    return prefix, (s[len(prefix) :].strip() if prefix else s)


def parse_value(text: str) -> tuple[float, Bound | None] | None:
    """'42' -> (42.0, None); '<5' -> (5.0, "<"); '≥ 60' -> (60.0, ">="); '1,234.5' ->
    (1234.5, None); 'Not detected', '5,2' (an ambiguous comma) and '-5' (no marker is negative)
    -> None."""
    prefix, body = _split_bound(text)
    if _THOUSANDS.match(body):
        body = body.replace(",", "")
    if body.startswith("-") or not _NUMBER.match(body):
        return None
    return float(body), (_BOUNDS[prefix] if prefix else None)


def bound_step(raw_value: str, value: float) -> float:
    """One unit in the last printed decimal place of a bounded raw value, scaled to the canonical
    unit of `value`: '<1.0' -> 0.1, '>60' -> 1, '<0.5' converted x10 -> 1.0. The open end of the
    bound's interval sits one step inside it. 0 when the text does not parse."""
    parsed = parse_value(raw_value)
    if parsed is None or parsed[0] == 0:
        return 0.0
    _, body = _split_bound(raw_value)
    decimals = len(body.partition(".")[2])
    return 10.0**-decimals * value / parsed[0]
```

replace:

```python
def _ref(text: str | None) -> float | None:
    if text is None:
        return None
    parsed = parse_value(text)
    return parsed[0] if parsed else None
```

with:

```python
def _ref(text: str | None, factor: float) -> float | None:
    """A printed reference bound in the canonical unit: converted by the same factor as the value."""
    if text is None:
        return None
    parsed = parse_value(text)
    return round(parsed[0] * factor, 4) if parsed else None
```

and replace:

```python
        number, note = parsed
        notes = [note] if note else []
        if factor != 1.0:
            unit = raw.unit
            assert unit is not None  # _factor returns None above when raw.unit is None
            notes.append(f"converted from {raw.value.strip()} {unit.strip()}")
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
```

with:

```python
        number, bound = parsed
        note: str | None = None
        if factor != 1.0:
            unit = raw.unit
            assert unit is not None  # _factor returns None above when raw.unit is None
            note = f"converted from {raw.value.strip()} {unit.strip()}"
        taken.add(spec.key)
        out.results.append(
            LabResult(
                marker=spec.key,
                value=round(number * factor, 4),
                unit=spec.unit,
                raw=raw,
                bound=bound,
                lab_ref_low=_ref(raw.ref_low, factor),
                lab_ref_high=_ref(raw.ref_high, factor),
                note=note,
            )
        )
```

In `packages/tri-wellness/src/tri_wellness/labs/evaluate.py`, replace:

```python
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
```

with:

```python
from __future__ import annotations

import math
from datetime import time
from typing import Any, get_args

from tri_wellness.labs.models import (
    Bound,
    Confounder,
    ConventionalStatus,
    Finding,
    FunctionalStatus,
    LabResult,
    PanelContext,
    PreviousValue,
    TrainingContext,
)
from tri_wellness.labs.normalize import bound_step
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec
```

replace:

```python
def _delta_pct(value: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)
```

with:

```python
def _ends(value: float, bound: Bound | None, step: float) -> tuple[float, float]:
    """The lowest and highest value a result can stand for: `<x` is [0, x), `>x` is (x, inf),
    with the open end one printed unit (`step`) inside the bound. A plain value is its own ends."""
    if bound is None:
        return value, value
    if bound == "<":
        return 0.0, max(0.0, value - step)
    if bound == "<=":
        return 0.0, value
    if bound == ">":
        return value + step, math.inf
    return value, math.inf


def bounded_conventional_status(
    value: float,
    bound: Bound | None,
    step: float,
    lab_low: float | None,
    lab_high: float | None,
    spec: MarkerSpec,
) -> ConventionalStatus:
    """`conventional_status` at both ends of the interval when they agree, else indeterminate."""
    lo, hi = _ends(value, bound, step)
    at_lo = conventional_status(lo, lab_low, lab_high, spec)
    at_hi = conventional_status(hi, lab_low, lab_high, spec)
    return at_lo if at_lo == at_hi else "indeterminate"


def bounded_functional_status(
    value: float, bound: Bound | None, step: float, spec: MarkerSpec
) -> FunctionalStatus:
    """`functional_status` at both ends of the interval when they agree, else indeterminate."""
    lo, hi = _ends(value, bound, step)
    at_lo, at_hi = functional_status(lo, spec), functional_status(hi, spec)
    return at_lo if at_lo == at_hi else "indeterminate"


def _delta_pct(value: float, prev: float | None) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((value - prev) / prev * 100, 1)
```

and replace:

```python
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
                functional_range=_functional_range(spec),
                previous=prev,
                delta_pct=_delta_pct(r.value, prev[1] if prev else None),
                active_confounders=[c for c in spec.confounders if c in panel_active],
                athlete_note=spec.athlete_note,
            )
        )
    return findings
```

with:

```python
def evaluate(
    results: list[LabResult],
    registry: MarkerRegistry,
    previous: dict[str, PreviousValue],
    context: PanelContext,
    training: TrainingContext,
) -> list[Finding]:
    panel_active = active_confounders(results, registry, context, training)
    findings: list[Finding] = []
    for r in results:
        spec = registry.get(r.marker)
        prev = previous.get(r.marker)
        step = bound_step(r.raw.value, r.value) if r.bound else 0.0
        any_bounded = r.bound is not None or (prev is not None and prev[2] is not None)
        findings.append(
            Finding(
                marker=r.marker,
                display=spec.display,
                system=spec.system,
                value=r.value,
                unit=r.unit,
                bound=r.bound,
                raw_value=r.raw.value.strip(),
                conventional_status=bounded_conventional_status(
                    r.value, r.bound, step, r.lab_ref_low, r.lab_ref_high, spec
                ),
                functional_status=bounded_functional_status(r.value, r.bound, step, spec),
                functional_range=_functional_range(spec),
                previous=(prev[0], prev[1]) if prev else None,
                delta_pct=None if any_bounded else _delta_pct(r.value, prev[1] if prev else None),
                active_confounders=[c for c in spec.confounders if c in panel_active],
                athlete_note=spec.athlete_note,
            )
        )
    return findings
```

In `packages/tri-wellness/src/tri_wellness/repo.py`, replace the import block:

```python
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
```

with:

```python
from tri_wellness.labs.models import (
    Finding,
    LabResult,
    PanelContext,
    PanelSummary,
    PreviousValue,
    RawResult,
    SourceKind,
    StoredPanel,
    StoredReport,
    StoredResult,
)
```

replace:

```python
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
```

with:

```python
            cur.execute(
                """
                insert into lab_results (panel_id, marker, value, unit, raw_name, raw_value,
                    raw_unit, lab_ref_low, lab_ref_high, flag, bound)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    r.bound,
                ),
            )
```

replace:

```python
        lab_ref_low=_f(row["lab_ref_low"]),
        lab_ref_high=_f(row["lab_ref_high"]),
        flag=row["flag"],
    )
```

with:

```python
        lab_ref_low=_f(row["lab_ref_low"]),
        lab_ref_high=_f(row["lab_ref_high"]),
        flag=row["flag"],
        bound=row["bound"],
    )
```

replace:

```python
                lab_ref_low=s.lab_ref_low,
                lab_ref_high=s.lab_ref_high,
            )
        )
    return out
```

with:

```python
                bound=s.bound,
                lab_ref_low=s.lab_ref_low,
                lab_ref_high=s.lab_ref_high,
            )
        )
    return out
```

and replace:

```python
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
```

with:

```python
def previous_values(conn: Conn, panel_id: int) -> dict[str, PreviousValue]:
    """Per marker, the value and bound from the most recent panel strictly earlier than this
    one, ordered by (drawn_on, id)."""
    rows = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select distinct on (r.marker) r.marker, p.drawn_on, r.value, r.bound
        from lab_results r
        join lab_panels p on p.id = r.panel_id
        cross join me
        where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        order by r.marker, p.drawn_on desc, p.id desc
        """,
        (panel_id,),
    ).fetchall()
    return {r["marker"]: (r["drawn_on"], float(r["value"]), r["bound"]) for r in rows}
```

In `packages/tri-wellness/src/tri_wellness/repl.py`, replace:

```python
from datetime import date, time
from typing import Any

import yaml
from langgraph.types import Command

from tri_core.harness.turns import Out as Out
from tri_core.harness.turns import run_agent_turn, stream_turn, turn_config
from tri_wellness.labs.models import (
    BLOCKING_REASONS,
    IngestDecision,
    LabResult,
    PanelContext,
    PanelSummary,
    RawResult,
    Unmapped,
)
```

with:

```python
from datetime import date, time
from typing import Any, get_args

import yaml
from langgraph.types import Command

from tri_core.harness.turns import Out as Out
from tri_core.harness.turns import run_agent_turn, stream_turn, turn_config
from tri_wellness.labs.models import (
    BLOCKING_REASONS,
    Bound,
    IngestDecision,
    LabResult,
    PanelContext,
    PanelSummary,
    RawResult,
    Unmapped,
)
```

replace:

```python
    for r in results:
        raw = r.get("raw") or {}
        lines.append(
            f"{r['marker']:24} {float(r['value']):>10g} {r['unit']:10} "
            f"{_rng(r.get('lab_ref_low'), r.get('lab_ref_high')):12} {(raw.get('flag') or ''):4} "
            f"{raw.get('name') or ''}"
        )
```

with:

```python
    for r in results:
        raw = r.get("raw") or {}
        value = f"{r.get('bound') or ''}{float(r['value']):g}"
        lines.append(
            f"{r['marker']:24} {value:>10} {r['unit']:10} "
            f"{_rng(r.get('lab_ref_low'), r.get('lab_ref_high')):12} {(raw.get('flag') or ''):4} "
            f"{raw.get('name') or ''}"
        )
```

replace:

```python
        "marker": r["marker"],
        "value": r["value"],
        "unit": r["unit"],
        "raw_name": raw.get("name"),
```

with:

```python
        "marker": r["marker"],
        "value": r["value"],
        "unit": r["unit"],
        "bound": r.get("bound"),
        "raw_name": raw.get("name"),
```

and replace:

```python
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"results[{i}] ({marker}): value '{row.get('value')}' is not a number")
            continue
        results.append(
            LabResult(
                marker=marker,
                value=value,
                unit=spec.unit,
                raw=RawResult(
```

with:

```python
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"results[{i}] ({marker}): value '{row.get('value')}' is not a number")
            continue
        bound = row.get("bound")
        if bound is not None and bound not in get_args(Bound):
            problems.append(f"results[{i}] ({marker}): bound '{bound}' is not one of <, <=, >, >=")
            continue
        results.append(
            LabResult(
                marker=marker,
                value=value,
                unit=spec.unit,
                bound=bound,
                raw=RawResult(
```

In `packages/tri-wellness/src/tri_wellness/prompts/report.py`, replace:

```python
def _finding_line(f: Finding) -> str:
    line = (
        f"- {f.display}: {_g(f.value)} {f.unit} — {f.functional_status} "
        f"(functional {format_range(*f.functional_range)}; conventional {f.conventional_status})"
    )
```

with:

```python
def _shown(f: Finding) -> str:
    """The value as the lab meant it: '<0.3' for a bounded row, '42' otherwise."""
    return f"{f.bound}{_g(f.value)}" if f.bound else _g(f.value)


def _finding_line(f: Finding) -> str:
    status = f.functional_status
    if status == "indeterminate":
        status = f"indeterminate (reported as {f.raw_value})"
    line = (
        f"- {f.display}: {_shown(f)} {f.unit} — {status} "
        f"(functional {format_range(*f.functional_range)}; conventional {f.conventional_status})"
    )
```

and replace:

```python
                    f"{f.display} {_g(f.value)} {f.unit} ({format_range(*f.functional_range)})"
                    for f in optimal
```

with:

```python
                    f"{f.display} {_shown(f)} {f.unit} ({format_range(*f.functional_range)})"
                    for f in optimal
```

In `packages/tri-wellness/src/tri_wellness/evals/target.py`, replace:

```python
from tri_wellness.labs.models import LabResult, PanelContext, TrainingContext
```

with:

```python
from tri_wellness.labs.models import LabResult, PanelContext, PreviousValue, TrainingContext
```

and replace:

```python
) -> tuple[
    list[LabResult],
    PanelContext,
    TrainingContext,
    dict[str, tuple[date, float]],
    dict[str, Any] | None,
]:
    previous = {
        m: (date.fromisoformat(str(d)), float(v))
        for m, (d, v) in (inputs.get("previous") or {}).items()
    }
```

with:

```python
) -> tuple[
    list[LabResult],
    PanelContext,
    TrainingContext,
    dict[str, PreviousValue],
    dict[str, Any] | None,
]:
    previous: dict[str, PreviousValue] = {
        m: (date.fromisoformat(str(d)), float(v), (b[0] if b else None))
        for m, (d, v, *b) in (inputs.get("previous") or {}).items()
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness packages/tri-coach/tests/test_context.py -q`
Expected: all pass (the db-marked tests need migration 006 applied to the test database; `wdb` only checks for `lab_panels`, so without 006 they fail on `column "bound" does not exist` rather than skipping).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/labs/models.py packages/tri-wellness/src/tri_wellness/labs/normalize.py packages/tri-wellness/src/tri_wellness/labs/evaluate.py packages/tri-wellness/src/tri_wellness/repo.py packages/tri-wellness/src/tri_wellness/repl.py packages/tri-wellness/src/tri_wellness/prompts/report.py packages/tri-wellness/src/tri_wellness/evals/target.py packages/tri-wellness/tests/test_normalize.py packages/tri-wellness/tests/test_evaluate.py packages/tri-wellness/tests/test_repo.py packages/tri-wellness/tests/test_report_prompt.py packages/tri-wellness/tests/test_repl.py
git commit -m "fix(wellness): bound-aware lab values; lab references convert with the value"
```

---

### Task 3: W3, alias lookup keeps parenthesised qualifiers

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/ranges/registry.py:89-98`
- Modify: `packages/tri-wellness/src/tri_wellness/ranges/markers.yaml:250, 478, 781, 796, 873, 891, 920`
- Test: `packages/tri-wellness/tests/test_registry.py` (edit and append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `normalize_alias("Testosterone (Free)") == "testosterone free"` (parentheses become spaces, nothing is dropped); `markers.yaml` aliases `creatine kinase (ck)`, `co2 (bicarbonate)`, `vitamin d (25-oh)`, `vitamin d (25-hydroxy)`, `vitamin b12 (total)`, `b12 (total)`, `testosterone (total)`, `testosterone (free)`, `cortisol (am)`.

**Note for the assembler:** "Cortisol (PM)" and "B12 (Active)" have no marker in the table (PM cortisol and holotranscobalamin are different tests), so they stay unmapped by design; the spec's "cortisol AM/PM, B12 active/total" reads as "the qualified labels resolve correctly", which for PM and active means an unmapped review line. The `ck` and `co2` aliases are needed because `test_every_alias_round_trips` also looks up every `display`, and "Creatine kinase (CK)" and "CO2 (bicarbonate)" no longer collapse to their plain aliases.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-wellness/tests/test_registry.py`, replace the two parametrize rows

```python
        ("  Vitamin D (25-Hydroxy)  ", "vitamin d"),
        ("hs-CRP", "hs crp"),
        ("Testosterone,Free (Direct)", "testosterone free"),
```

with

```python
        ("  Vitamin D (25-Hydroxy)  ", "vitamin d 25 hydroxy"),
        ("hs-CRP", "hs crp"),
        ("Testosterone,Free (Direct)", "testosterone free direct"),
        ("Testosterone (Free)", "testosterone free"),
```

Replace

```python
    assert reg.lookup("CRP (hs)") is None  # 'crp' alone is not an alias
    assert reg.lookup("Ferritin (serum)").key == "ferritin"  # qualifier stripped
```

with

```python
    assert reg.lookup("CRP (hs)").key == "hs_crp"  # 'crp hs' is an alias; the qualifier counts
    assert reg.lookup("Ferritin (serum)").key == "ferritin"  # 'ferritin serum' is an alias
    assert reg.lookup("Ferritin (Kit)") is None  # an unknown qualifier is not dropped
```

Add `MARKERS_PATH` to the `tri_wellness.ranges.registry` import and append:

```python
# 40 labels as LabCorp and Quest print them, with the marker each must resolve to.
GOLDEN = [
    ("WBC", "wbc"),
    ("RBC", "rbc"),
    ("Hemoglobin", "hemoglobin"),
    ("Hematocrit", "hematocrit"),
    ("MCV", "mcv"),
    ("Platelets", "platelets"),
    ("Neutrophils", "neutrophils_pct"),
    ("Lymphs", "lymphocytes_pct"),
    ("Glucose", "glucose"),
    ("BUN", "bun"),
    ("Creatinine", "creatinine"),
    ("eGFR", "egfr"),
    ("BUN/Creatinine Ratio", "bun_creatinine_ratio"),
    ("Sodium", "sodium"),
    ("Potassium", "potassium"),
    ("Carbon Dioxide, Total", "co2"),
    ("Protein, Total", "total_protein"),
    ("Bilirubin, Total", "bilirubin_total"),
    ("AST (SGOT)", "ast"),
    ("ALT (SGPT)", "alt"),
    ("Cholesterol, Total", "total_cholesterol"),
    ("HDL Cholesterol", "hdl"),
    ("LDL Chol Calc (NIH)", "ldl"),
    ("TSH", "tsh"),
    ("T4, Free", "free_t4"),
    ("T3, Free", "free_t3"),
    ("Ferritin, Serum", "ferritin"),
    ("Iron, Serum", "iron_serum"),
    ("Iron Bind.Cap.(TIBC)", "tibc"),
    ("Iron Saturation", "transferrin_saturation"),
    ("C-Reactive Protein, Cardiac", "hs_crp"),
    ("Homocyst(e)ine", "homocysteine"),
    ("Vitamin D, 25-Hydroxy", "vitamin_d"),
    ("Vitamin B12", "b12"),
    ("Folate (Folic Acid), Serum", "folate"),
    ("Magnesium, RBC", "rbc_magnesium"),
    ("Testosterone (Free)", "testosterone_free"),
    ("Testosterone (Total)", "testosterone_total"),
    ("Cortisol (AM)", "cortisol_am"),
    ("DHEA-Sulfate", "dhea_s"),
]


def test_qualified_labels_resolve_to_the_qualified_marker():
    reg = load_registry("male", MARKERS_PATH)
    assert reg.lookup("Testosterone (Free)").key == "testosterone_free"
    assert reg.lookup("Testosterone (Total)").key == "testosterone_total"
    assert reg.lookup("Vitamin D (25-OH)").key == "vitamin_d"
    assert reg.lookup("Vitamin B12 (Total)").key == "b12"
    assert reg.lookup("Cortisol (PM)") is None  # no PM cortisol marker: a review line, not AM
    assert reg.lookup("B12 (Active)") is None  # holotranscobalamin is not serum B12


def test_golden_lab_labels_resolve_without_collision():
    reg = load_registry("male", MARKERS_PATH)
    assert len(GOLDEN) == 40
    assert len({normalize_alias(label) for label, _ in GOLDEN}) == 40
    for label, key in GOLDEN:
        found = reg.lookup(label)
        assert found is not None and found.key == key, label
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_registry.py -v`
Expected: the two edited `test_normalize_alias` rows fail (`'vitamin d' != 'vitamin d 25 hydroxy'`), `test_lookup_uses_normalized_aliases` fails (`None` has no `.key`), `test_qualified_labels_resolve_to_the_qualified_marker` fails (`testosterone_total != testosterone_free`), `test_golden_lab_labels_resolve_without_collision` passes only after the aliases are added.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/ranges/registry.py`, replace:

```python
_PAREN = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize_alias(name: str) -> str:
    """Lowercase, drop parenthesized qualifiers, turn punctuation into spaces, collapse spaces."""
    s = _PAREN.sub(" ", name.lower())
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()
```

with:

```python
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize_alias(name: str) -> str:
    """Lowercase, turn punctuation (parentheses included) into spaces, collapse spaces. A
    parenthesised qualifier stays: 'Testosterone (Free)' -> 'testosterone free', so a qualified
    label maps only when the table lists it."""
    s = _NON_ALNUM.sub(" ", name.lower())
    return _WS.sub(" ", s).strip()
```

In `packages/tri-wellness/src/tri_wellness/ranges/markers.yaml`, replace each alias line as follows (one line each; keep the rest of the entry):

line 250 (`ck`):
```yaml
    aliases: [ck, "creatine kinase", "creatine kinase, total", "ck, total", cpk, "creatine phosphokinase", "ck total"]
```
with
```yaml
    aliases: [ck, "creatine kinase", "creatine kinase (ck)", "creatine kinase, total", "ck, total", cpk, "creatine phosphokinase", "ck total"]
```

line 478 (`co2`):
```yaml
    aliases: [co2, "carbon dioxide, total", "carbon dioxide", bicarbonate, "co2, total", hco3]
```
with
```yaml
    aliases: [co2, "co2 (bicarbonate)", "carbon dioxide, total", "carbon dioxide", bicarbonate, "co2, total", hco3]
```

line 781 (`vitamin_d`):
```yaml
    aliases: [vitamin d, "vitamin d, 25-hydroxy", "25-hydroxyvitamin d", "25-oh vitamin d", "vitamin d 25-hydroxy", "25(oh)d", "vitamin d, 25-oh, total", "vit d 25-oh", "vitamin d total", "calcifediol"]
```
with
```yaml
    aliases: [vitamin d, "vitamin d (25-oh)", "vitamin d (25-hydroxy)", "vitamin d, 25-hydroxy", "25-hydroxyvitamin d", "25-oh vitamin d", "vitamin d 25-hydroxy", "25(oh)d", "vitamin d, 25-oh, total", "vit d 25-oh", "vitamin d total", "calcifediol"]
```

line 796 (`b12`):
```yaml
    aliases: [b12, "vitamin b12", "vitamin b-12", cobalamin, "b-12", "vitamin b12, serum"]
```
with
```yaml
    aliases: [b12, "vitamin b12", "vitamin b12 (total)", "b12 (total)", "vitamin b-12", cobalamin, "b-12", "vitamin b12, serum"]
```

line 873 (`testosterone_total`):
```yaml
    aliases: [testosterone, "testosterone, total", "total testosterone", "testosterone, serum", "testosterone total"]
```
with
```yaml
    aliases: [testosterone, "testosterone, total", "testosterone (total)", "total testosterone", "testosterone, serum", "testosterone total"]
```

line 891 (`testosterone_free`):
```yaml
    aliases: [free testosterone, "testosterone, free", "testosterone,free (direct)", "free testosterone (direct)", "testosterone free"]
```
with
```yaml
    aliases: [free testosterone, "testosterone, free", "testosterone (free)", "testosterone,free (direct)", "free testosterone (direct)", "testosterone free"]
```

line 920 (`cortisol_am`):
```yaml
    aliases: [cortisol, "cortisol, am", "cortisol - am", "am cortisol", "cortisol, serum", "cortisol, total", "cortisol am", "morning cortisol"]
```
with
```yaml
    aliases: [cortisol, "cortisol, am", "cortisol (am)", "cortisol - am", "am cortisol", "cortisol, serum", "cortisol, total", "cortisol am", "morning cortisol"]
```

The alias collision check in `MarkerRegistry.__init__` is unchanged and still runs at load; `test_markers_yaml.py` loads the table for both sexes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass (`test_markers_yaml.py::test_every_alias_round_trips` covers every display and alias under the new normalisation).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/ranges/registry.py packages/tri-wellness/src/tri_wellness/ranges/markers.yaml packages/tri-wellness/tests/test_registry.py
git commit -m "fix(wellness): keep parenthesised qualifiers in alias lookup"
```

---

### Task 4: W4, dimensionless markers accept a missing unit

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/normalize.py` (`_factor`, after Task 2 at roughly lines 55-62)
- Test: `packages/tri-wellness/tests/test_normalize.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `normalize.DIMENSIONLESS_UNITS: frozenset[str] = frozenset({"ratio", "%", "index", "score"})`; `_factor(spec, None)` is `1.0` when `spec.unit` is dimensionless, `None` otherwise.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-wellness/tests/test_normalize.py`:

```python
def test_dimensionless_marker_without_unit_is_canonical(reg):
    out = normalize([raw("BUN/Creatinine Ratio", "14"), raw("Hematocrit", "45"), raw("Ferritin", "42")], reg)
    assert [(r.marker, r.value, r.unit, r.raw.unit, r.note) for r in out.results] == [
        ("bun_creatinine_ratio", 14.0, "ratio", None, None),
        ("hematocrit", 45.0, "%", None, None),
    ]
    [u] = out.unmapped
    assert u.reason == "unit" and u.marker == "ferritin"  # a dimensioned marker still blocks
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_normalize.py::test_dimensionless_marker_without_unit_is_canonical -v`
Expected: `AssertionError` (`out.results` is empty; all three rows are unmapped with reason `unit`).

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/labs/normalize.py`, replace:

```python
def _factor(spec: MarkerSpec, unit: str | None) -> float | None:
    if unit is None:
        return None
    table = {_unit_key(spec.unit): 1.0}
```

with:

```python
DIMENSIONLESS_UNITS: frozenset[str] = frozenset({"ratio", "%", "index", "score"})


def _factor(spec: MarkerSpec, unit: str | None) -> float | None:
    """1.0 for the canonical unit, the table's factor for a known printed unit, None otherwise.
    A dimensionless marker printed without a unit is in its canonical unit."""
    if unit is None or not unit.strip():
        return 1.0 if spec.unit in DIMENSIONLESS_UNITS else None
    table = {_unit_key(spec.unit): 1.0}
```

and, in `normalize()`, replace the comment line

```python
            assert unit is not None  # _factor returns None above when raw.unit is None
```

with

```python
            assert unit is not None  # a factor other than 1.0 comes only from a printed unit
```

`ruff format` will reflow the long `normalize([...])` line in the test; accept it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass (`test_unknown_or_missing_unit_is_unmapped_with_marker` and `test_whitespace_only_unit_is_unmapped_with_marker` use ferritin and still block).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/labs/normalize.py packages/tri-wellness/tests/test_normalize.py
git commit -m "fix(wellness): dimensionless markers accept a missing unit"
```

---

### Task 5: W5, block a re-ingest of the same file by its sha

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/models.py:110-118` (`StoredPanel`)
- Modify: `packages/tri-wellness/src/tri_wellness/repo.py:28-56, 81-91, 130-136`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/state.py:16-29`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py:1-46`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/nodes/review.py:25-68`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/nodes/store.py:12-28`
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py:51-57` (`render_review`)
- Test: `packages/tri-wellness/tests/test_repo.py`, `test_graph.py`, `test_repl.py` (append and edit)

**Interfaces:**
- Consumes: migration 006 column `lab_panels.source_sha text` and index `lab_panels_source_sha_idx` (assembler); `tri_wellness.labs.extract.file_sha256`.
- Produces: `repo.insert_panel(..., source_sha: str | None = None)`; `repo.panel_id_for_sha(conn, sha) -> int | None`; `StoredPanel.source_sha: str | None = None`; `IngestState.source_sha: str | None` (set by the extract node); review payload key `already_ingested: int | None`; approve refused with `last_error == "already ingested as panel <id>"`; `render_review` line `blocked: this file is already ingested as panel <id>; reject to end`.

**Note for the assembler:** the thread id is already `ingest:<sha>`, so a rerun on the same checkpointer never reaches review; this block covers a fresh checkpointer, a wiped thread, or a second ingest path (tri-web). The block is at review, as the spec says, so a PDF still costs one extraction call before it is refused; moving the check into the extract node (which has `deps.connect`) would save that call and is a one-line move if wanted.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-wellness/tests/test_repo.py`:

```python
def test_source_sha_round_trips_and_finds_the_panel(wdb):
    pid = repo.insert_panel(
        wdb,
        drawn_on=D1,
        lab_name="Quest",
        source_file="/labs/a.pdf",
        source_kind="pdf",
        context=CTX,
        raw_extract=[],
        results=[],
        source_sha="a" * 64,
    )
    assert repo.get_panel(wdb, pid).source_sha == "a" * 64
    assert repo.panel_id_for_sha(wdb, "a" * 64) == pid
    assert repo.panel_id_for_sha(wdb, "b" * 64) is None
    assert repo.get_panel(wdb, panel(wdb, D2, [lr("ferritin", 40.0)])).source_sha is None
```

In `packages/tri-wellness/tests/test_graph.py`, replace the whole test

```python
async def test_export_path_is_deterministic_and_warns_on_duplicate(nocommit, make_deps):
    model = ScriptedChatModel(script=[])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    c = cfg()
    src = {"source_path": str(FIX / "exports" / "generic.csv"), "source_kind": "export"}
    out = await graph.ainvoke(src, c)
    payload = out["__interrupt__"][0].value
    assert model.calls == 0
    assert [r["marker"] for r in payload["results"]] == [
        "ferritin",
        "hs_crp",
        "glucose",
        "vitamin_d",
    ]
    assert payload["lab_name"] == "Function Health"
    first = (await graph.ainvoke(APPROVE, c))["panel_id"]
    c2 = cfg()
    out = await graph.ainvoke(src, c2)
    assert out["__interrupt__"][0].value["duplicates"] == [first]
    second = (await graph.ainvoke(APPROVE, c2))["panel_id"]
    assert second != first  # a second panel, not a merge
```

with

```python
async def test_export_path_is_deterministic_and_blocks_the_same_file(nocommit, make_deps, tmp_path):
    model = ScriptedChatModel(script=[])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    c = cfg()
    src = {"source_path": str(FIX / "exports" / "generic.csv"), "source_kind": "export"}
    out = await graph.ainvoke(src, c)
    payload = out["__interrupt__"][0].value
    assert model.calls == 0
    assert [r["marker"] for r in payload["results"]] == [
        "ferritin",
        "hs_crp",
        "glucose",
        "vitamin_d",
    ]
    assert payload["lab_name"] == "Function Health"
    assert payload["duplicates"] == [] and payload["already_ingested"] is None
    first = (await graph.ainvoke(APPROVE, c))["panel_id"]
    assert repo.get_panel(nocommit, first).source_sha is not None
    # the same bytes again (a re-download) are blocked at review
    c2 = cfg()
    out = await graph.ainvoke(src, c2)
    payload = out["__interrupt__"][0].value
    assert payload["duplicates"] == [first] and payload["already_ingested"] == first
    out = await graph.ainvoke(APPROVE, c2)
    again = out["__interrupt__"][0].value
    assert again["last_error"] == f"already ingested as panel {first}"
    assert (await graph.aget_state(c2)).next == ("review",)
    # different bytes for the same date and lab: a warning, and approve stores another
    other = tmp_path / "generic-2.csv"
    other.write_text((FIX / "exports" / "generic.csv").read_text().replace(",42,", ",43,"))
    c3 = cfg()
    out = await graph.ainvoke({"source_path": str(other), "source_kind": "export"}, c3)
    payload = out["__interrupt__"][0].value
    assert payload["duplicates"] == [first] and payload["already_ingested"] is None
    second = (await graph.ainvoke(APPROVE, c3))["panel_id"]
    assert second != first  # a second panel, not a merge
```

In `packages/tri-wellness/tests/test_repl.py::test_render_review_table_unmapped_duplicates_and_error`, replace

```python
    assert "panel(s) 7" in text and "approve needs the panel context" in text
```

with

```python
    assert "panel(s) 7" in text and "approve needs the panel context" in text
    assert "already ingested as panel 9" in render_review(payload(already_ingested=9))
    assert "already ingested" not in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_repo.py::test_source_sha_round_trips_and_finds_the_panel packages/tri-wellness/tests/test_graph.py::test_export_path_is_deterministic_and_blocks_the_same_file packages/tri-wellness/tests/test_repl.py::test_render_review_table_unmapped_duplicates_and_error -v`
Expected: `TypeError: insert_panel() got an unexpected keyword argument 'source_sha'`; `KeyError: 'already_ingested'`; `AssertionError` on the render line.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/labs/models.py`, replace:

```python
class StoredPanel(BaseModel):
    id: int
    drawn_on: date
    lab_name: str | None
    source_file: str | None
    source_kind: SourceKind
    context: PanelContext
    raw_extract: list[RawResult]
    created_at: datetime
```

with:

```python
class StoredPanel(BaseModel):
    id: int
    drawn_on: date
    lab_name: str | None
    source_file: str | None
    source_kind: SourceKind
    context: PanelContext
    raw_extract: list[RawResult]
    created_at: datetime
    source_sha: str | None = None  # sha256 of the ingested file; None for manual panels
```

In `packages/tri-wellness/src/tri_wellness/repo.py`, replace:

```python
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
```

with:

```python
    context: PanelContext,
    raw_extract: list[RawResult],
    results: list[LabResult],
    source_sha: str | None = None,
) -> int:
    """Insert the panel and its result rows. Runs inside the caller's transaction, so a
    failing result row leaves no panel behind."""
    row = conn.execute(
        """
        insert into lab_panels (drawn_on, lab_name, source_file, source_kind, context,
            raw_extract, source_sha)
        values (%s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (
            drawn_on,
            lab_name,
            source_file,
            source_kind,
            Jsonb(context.model_dump(mode="json")),
            Jsonb([r.model_dump(mode="json") for r in raw_extract]),
            source_sha,
        ),
    ).fetchone()
```

replace:

```python
        raw_extract=[RawResult.model_validate(r) for r in row["raw_extract"]],
        created_at=row["created_at"],
    )
```

with:

```python
        raw_extract=[RawResult.model_validate(r) for r in row["raw_extract"]],
        created_at=row["created_at"],
        source_sha=row["source_sha"],
    )
```

and replace:

```python
def find_duplicate_panels(conn: Conn, drawn_on: date, lab_name: str | None) -> list[int]:
```

with:

```python
def panel_id_for_sha(conn: Conn, sha: str) -> int | None:
    """The panel already stored from a file with these bytes, if any (lowest id)."""
    row = conn.execute(
        "select id from lab_panels where source_sha = %s order by id limit 1", (sha,)
    ).fetchone()
    return int(row["id"]) if row else None


def find_duplicate_panels(conn: Conn, drawn_on: date, lab_name: str | None) -> list[int]:
```

In `packages/tri-wellness/src/tri_wellness/graph/state.py`, replace:

```python
    source_path: str
    source_kind: IngestKind
    drawn_on_hint: date | None
```

with:

```python
    source_path: str
    source_kind: IngestKind
    source_sha: str | None  # sha256 of the file; set by extract, checked at review, stored
    drawn_on_hint: date | None
```

In `packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py`, replace:

```python
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.extract.exports import extract_export_with_model, parse_export
from tri_wellness.labs.extract.pdf import extract_pdf
```

with:

```python
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.extract import file_sha256
from tri_wellness.labs.extract.exports import extract_export_with_model, parse_export
from tri_wellness.labs.extract.pdf import extract_pdf
```

and replace:

```python
        return {
            "raw_results": panel.results,
            "drawn_on": drawn_on,
            "lab_name": panel.lab_name,
            "page_count": pages,
```

with:

```python
        return {
            "source_sha": file_sha256(path),
            "raw_results": panel.results,
            "drawn_on": drawn_on,
            "lab_name": panel.lab_name,
            "page_count": pages,
```

In `packages/tri-wellness/src/tri_wellness/graph/nodes/review.py`, replace:

```python
        drawn_on = state.get("drawn_on")
        context = state.get("context")
        unmapped = list(state.get("unmapped") or [])
        duplicates: list[int] = []
        if drawn_on is not None:
            with deps.connect() as conn:
                duplicates = repo.find_duplicate_panels(conn, drawn_on, state.get("lab_name"))
        raw = interrupt(
            {
                "source_path": state["source_path"],
                "drawn_on": drawn_on.isoformat() if drawn_on else None,
                "lab_name": state.get("lab_name"),
                "results": [r.model_dump(mode="json") for r in state.get("results") or []],
                "unmapped": [u.model_dump(mode="json") for u in unmapped],
                "context": context.model_dump(mode="json") if context else None,
                "duplicates": duplicates,
                "last_error": state.get("last_error"),
            }
        )
        decision = IngestDecision.model_validate(raw)
        if decision.action == "reject":
            return {"decision": "reject", "last_error": None}
        if decision.action == "edit":
            update: dict[str, Any] = {"decision": None, "last_error": None}
            for field in ("results", "unmapped", "drawn_on", "lab_name", "context"):
                value = getattr(decision, field)
                if value is not None:
                    update[field] = value
            return update
        blocking = blocking_rows(unmapped)
```

with:

```python
        drawn_on = state.get("drawn_on")
        context = state.get("context")
        unmapped = list(state.get("unmapped") or [])
        sha = state.get("source_sha")
        duplicates: list[int] = []
        already_ingested: int | None = None
        if drawn_on is not None or sha is not None:
            with deps.connect() as conn:
                if drawn_on is not None:
                    duplicates = repo.find_duplicate_panels(conn, drawn_on, state.get("lab_name"))
                if sha is not None:
                    already_ingested = repo.panel_id_for_sha(conn, sha)
        raw = interrupt(
            {
                "source_path": state["source_path"],
                "drawn_on": drawn_on.isoformat() if drawn_on else None,
                "lab_name": state.get("lab_name"),
                "results": [r.model_dump(mode="json") for r in state.get("results") or []],
                "unmapped": [u.model_dump(mode="json") for u in unmapped],
                "context": context.model_dump(mode="json") if context else None,
                "duplicates": duplicates,
                "already_ingested": already_ingested,
                "last_error": state.get("last_error"),
            }
        )
        decision = IngestDecision.model_validate(raw)
        if decision.action == "reject":
            return {"decision": "reject", "last_error": None}
        if decision.action == "edit":
            update: dict[str, Any] = {"decision": None, "last_error": None}
            for field in ("results", "unmapped", "drawn_on", "lab_name", "context"):
                value = getattr(decision, field)
                if value is not None:
                    update[field] = value
            return update
        if already_ingested is not None:
            return {
                "decision": None,
                "last_error": f"already ingested as panel {already_ingested}",
            }
        blocking = blocking_rows(unmapped)
```

In `packages/tri-wellness/src/tri_wellness/graph/nodes/store.py`, replace:

```python
                raw_extract=list(state.get("raw_results") or []),
                results=list(state.get("results") or []),
            )
```

with:

```python
                raw_extract=list(state.get("raw_results") or []),
                results=list(state.get("results") or []),
                source_sha=state.get("source_sha"),
            )
```

In `packages/tri-wellness/src/tri_wellness/repl.py`, replace:

```python
    if payload.get("duplicates"):
        ids = ", ".join(str(i) for i in payload["duplicates"])
        lines.append(
            f"warning: panel(s) {ids} already stored for this date and lab; approve stores another"
        )
```

with:

```python
    if payload.get("already_ingested") is not None:
        lines.append(
            f"blocked: this file is already ingested as panel {payload['already_ingested']}; "
            "reject to end"
        )
    elif payload.get("duplicates"):
        ids = ", ".join(str(i) for i in payload["duplicates"])
        lines.append(
            f"warning: panel(s) {ids} already stored for this date and lab; approve stores another"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness packages/tri-coach/tests/test_context.py -q`
Expected: all pass (needs `lab_panels.source_sha` from migration 006 on the test database).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/labs/models.py packages/tri-wellness/src/tri_wellness/repo.py packages/tri-wellness/src/tri_wellness/graph/state.py packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py packages/tri-wellness/src/tri_wellness/graph/nodes/review.py packages/tri-wellness/src/tri_wellness/graph/nodes/store.py packages/tri-wellness/src/tri_wellness/repl.py packages/tri-wellness/tests/test_repo.py packages/tri-wellness/tests/test_graph.py packages/tri-wellness/tests/test_repl.py
git commit -m "fix(wellness): block re-ingest of the same file by source sha"
```

---

### Task 6: W6, a multi-date CSV export is refused naming the dates

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/extract/exports.py:63-94`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py:17-46` (after Task 5)
- Test: `packages/tri-wellness/tests/test_exports.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `exports.ExportError(ValueError)`; `parse_generic_csv` and `parse_export` raise it when rows carry more than one draw date; the extract node turns it into `last_error`, so the run ends before review (as "no rows" does).

**Note for the assembler:** the spec says "a blocking review reason", but nothing in a two-date file can be approved or edited into shape, and the existing extract-level errors ("no rows", "no draw date") already end the run with `last_error` and the `ingest failed:` line; refusing before review keeps that one pattern. If a review pause is wanted instead, put the message in `last_error` without ending (route `after_extract` to `normalize` when `raw_results` is non-empty).

- [ ] **Step 1: Write the failing tests**

In `packages/tri-wellness/tests/test_exports.py`, replace the imports

```python
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage

from tri_core.testing import tool_call
from tri_wellness.labs.extract.exports import (
    detect_format,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.testing import RecordingScriptedModel, load_extracted
```

with

```python
import contextlib
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.nodes.extract import make_extract_node
from tri_wellness.labs.extract.exports import (
    ExportError,
    detect_format,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import RecordingScriptedModel, load_extracted
```

and append:

```python
TWO_DATES = (
    "name,value,unit,collected\n"
    "Ferritin,42,ng/mL,2026-08-20\n"
    "Glucose,92,mg/dL,2026-08-20\n"
    "Vitamin D,38,ng/mL,2026-09-03\n"
)


def test_two_date_csv_is_refused_naming_the_dates(tmp_path):
    p = tmp_path / "two.csv"
    p.write_text(TWO_DATES)
    with pytest.raises(ExportError, match=r"2 draw dates \(2026-08-20, 2026-09-03\).*split"):
        parse_export(p)
    p.write_text(TWO_DATES.replace("2026-09-03", "2026-08-20"))
    assert parse_export(p).drawn_on == date(2026, 8, 20)  # one date across rows is fine


async def test_extract_node_ends_the_run_on_a_two_date_csv(tmp_path):
    p = tmp_path / "two.csv"
    p.write_text(TWO_DATES)
    deps = GraphDeps(
        model=ScriptedChatModel(script=[]),
        connect=lambda: contextlib.nullcontext(None),
        registry=load_registry("male", MARKERS_PATH),
    )
    out = await make_extract_node(deps)(
        {"source_path": str(p), "source_kind": "export", "drawn_on_hint": None}, {}
    )
    assert "2026-08-20, 2026-09-03" in out["last_error"] and "split" in out["last_error"]
    assert out["raw_results"] == [] and deps.model.calls == 0  # no model fallback either
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_exports.py -v`
Expected: `ImportError: cannot import name 'ExportError'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/labs/extract/exports.py`, replace:

```python
MAX_FALLBACK_CHARS = 200_000


def _norm(h: str) -> str:
```

with:

```python
MAX_FALLBACK_CHARS = 200_000


class ExportError(ValueError):
    """The file parsed but cannot be one panel. The message says what to do."""


def _norm(h: str) -> str:
```

and replace:

```python
    results: list[RawResult] = []
    drawn_on: date | None = None
    lab_name: str | None = None
    for row in reader:
        n, v = _cell(row, name), _cell(row, value)
        if not n or not v:
            continue
        results.append(
            RawResult(
                name=n,
                value=v,
                unit=_cell(row, unit),
                ref_low=_cell(row, low),
                ref_high=_cell(row, high),
                flag=_cell(row, flag),
            )
        )
        if drawn_on is None and (d := _cell(row, dcol)):
            try:
                drawn_on = date.fromisoformat(d[:10])
            except ValueError:
                drawn_on = None
        if lab_name is None:
            lab_name = _cell(row, lcol)
    return ExtractedPanel(drawn_on=drawn_on, lab_name=lab_name, results=results)
```

with:

```python
    results: list[RawResult] = []
    dates: list[date] = []  # distinct draw dates across the rows, in file order
    lab_name: str | None = None
    for row in reader:
        n, v = _cell(row, name), _cell(row, value)
        if not n or not v:
            continue
        results.append(
            RawResult(
                name=n,
                value=v,
                unit=_cell(row, unit),
                ref_low=_cell(row, low),
                ref_high=_cell(row, high),
                flag=_cell(row, flag),
            )
        )
        if d := _cell(row, dcol):
            try:
                parsed = date.fromisoformat(d[:10])
            except ValueError:
                parsed = None
            if parsed is not None and parsed not in dates:
                dates.append(parsed)
        if lab_name is None:
            lab_name = _cell(row, lcol)
    if len(dates) > 1:
        listed = ", ".join(d.isoformat() for d in dates)
        raise ExportError(
            f"rows carry {len(dates)} draw dates ({listed}); split the file by date and ingest "
            "each part"
        )
    return ExtractedPanel(drawn_on=dates[0] if dates else None, lab_name=lab_name, results=results)
```

In `packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py`, replace:

```python
from tri_wellness.labs.extract import file_sha256
from tri_wellness.labs.extract.exports import extract_export_with_model, parse_export
from tri_wellness.labs.extract.pdf import extract_pdf


def make_extract_node(deps: GraphDeps) -> Any:
    async def extract(state: IngestState, config: RunnableConfig) -> dict[str, Any]:
        path = Path(state["source_path"])
        hint = state.get("drawn_on_hint")
        pages: int | None = None
        if state["source_kind"] == "pdf":
            panel, pages = await extract_pdf(deps.model, path, hint, config)
        else:
            parsed = parse_export(path)
            panel = parsed or await extract_export_with_model(deps.model, path, hint, config)
        drawn_on = panel.drawn_on or hint
        error: str | None = None
        if not panel.results:
            error = f"extraction returned no rows for {path.name}"
        elif drawn_on is None:
            error = f"extraction found no draw date in {path.name}; rerun with --drawn-on"
```

with:

```python
from tri_wellness.labs.extract import file_sha256
from tri_wellness.labs.extract.exports import (
    ExportError,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.models import ExtractedPanel


def make_extract_node(deps: GraphDeps) -> Any:
    async def extract(state: IngestState, config: RunnableConfig) -> dict[str, Any]:
        path = Path(state["source_path"])
        hint = state.get("drawn_on_hint")
        pages: int | None = None
        panel = ExtractedPanel()
        error: str | None = None
        if state["source_kind"] == "pdf":
            panel, pages = await extract_pdf(deps.model, path, hint, config)
        else:
            try:
                parsed = parse_export(path)
            except ExportError as exc:
                error = f"{path.name}: {exc}"
            else:
                panel = parsed or await extract_export_with_model(deps.model, path, hint, config)
        drawn_on = panel.drawn_on or hint
        if error is not None:
            pass
        elif not panel.results:
            error = f"extraction returned no rows for {path.name}"
        elif drawn_on is None:
            error = f"extraction found no draw date in {path.name}; rerun with --drawn-on"
```

(`ruff` rule SIM may prefer the chain without the `pass` branch; if `SIM102`/`SIM114` fires, write it as `if error is None and not panel.results: ... elif error is None and drawn_on is None: ...`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass (`test_parse_generic_csv` still reads `2026-08-20` from `generic.csv`, whose rows all carry that date).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/labs/extract/exports.py packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py packages/tri-wellness/tests/test_exports.py
git commit -m "fix(wellness): refuse a multi-date CSV export naming the dates"
```

---

### Task 7: W7, edited review YAML with a repeated marker is a validation error

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py` (`review_from_yaml`, after Task 2 at roughly lines 190-200)
- Test: `packages/tri-wellness/tests/test_repl.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `review_from_yaml` raises `ValueError` with `results[<i>]: marker '<key>' appears more than once` before any `LabResult` reaches the graph.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-wellness/tests/test_repl.py`:

```python
def test_yaml_with_a_repeated_marker_is_rejected_before_store():
    reg = load_registry("male", MARKERS_PATH)
    doc = yaml.safe_load(review_to_yaml(payload()))
    doc["results"].append({**doc["results"][0], "value": 43.0})
    with pytest.raises(ValueError, match=r"results\[2\]: marker 'ferritin' appears more than once"):
        review_from_yaml(yaml.safe_dump(doc), reg)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_repl.py::test_yaml_with_a_repeated_marker_is_rejected_before_store -v`
Expected: `Failed: DID NOT RAISE`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/repl.py`, replace:

```python
    problems: list[str] = []
    results: list[LabResult] = []
    for i, row in enumerate(doc.get("results") or []):
        marker = str(row.get("marker") or "")
        if marker not in registry.markers:
            problems.append(f"results[{i}]: unknown marker '{marker}'")
            continue
        spec = registry.get(marker)
```

with:

```python
    problems: list[str] = []
    results: list[LabResult] = []
    seen: set[str] = set()
    for i, row in enumerate(doc.get("results") or []):
        marker = str(row.get("marker") or "")
        if marker not in registry.markers:
            problems.append(f"results[{i}]: unknown marker '{marker}'")
            continue
        if marker in seen:
            problems.append(f"results[{i}]: marker '{marker}' appears more than once")
            continue
        seen.add(marker)
        spec = registry.get(marker)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/repl.py packages/tri-wellness/tests/test_repl.py
git commit -m "fix(wellness): reject a repeated marker in edited review YAML"
```

---

### Task 8: W8, a report truncated at `max_tokens` is not saved

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/report.py:46-61, 99-109`
- Test: `packages/tri-wellness/tests/test_report.py` (append)

**Interfaces:**
- Consumes: nothing new. langchain-anthropic 1.7.1 puts `stop_reason` in `response_metadata` of the final `message_delta` chunk (checked in the installed `chat_models.py`).
- Produces: `report.ReportTruncated(Exception)`; `ReportWriter.write` raises it when the last `stop_reason` seen is `"max_tokens"`; `run_report` prints `[<message>; not saved. Rerun.]` and returns 1 without inserting.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-wellness/tests/test_report.py`, replace the imports

```python
import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage

import tri_core.llm as llm
from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import ReportWriter, run_report
```

with

```python
import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

import tri_core.llm as llm
from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import ReportTruncated, ReportWriter, run_report
```

and append:

```python
class Truncating(ScriptedChatModel):
    """Streams half a report, then the final chunk Anthropic sends when max_tokens is hit."""

    def _stream(self, *a: Any, **k: Any) -> Any:
        yield ChatGenerationChunk(message=AIMessageChunk(content="## Draw conditions\nhalf a"))
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="", response_metadata={"stop_reason": "max_tokens"})
        )


async def test_writer_raises_when_the_stream_stops_at_max_tokens():
    chunks: list[str] = []
    with pytest.raises(ReportTruncated, match="max_tokens"):
        await ReportWriter(Truncating(script=[])).write("prompt", chunks.append, ["panel_id:1"])
    assert "".join(chunks) == "## Draw conditions\nhalf a"  # what streamed is still shown


async def test_run_report_does_not_save_a_truncated_report(nocommit, reg):
    pid = seed_panel(nocommit, D1, [("ferritin", 42.0, "ng/mL")])
    out = []
    code = await run_report(Truncating(script=[]), connect_factory(nocommit), reg, pid, out.append, None)
    assert code == 1
    assert repo.latest_report_for_panel(nocommit, pid) is None
    assert any("not saved" in s and "max_tokens" in s for s in out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_report.py -v`
Expected: `ImportError: cannot import name 'ReportTruncated'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/report.py`, replace:

```python
class ReportWriter:
    """One streaming call. Shared by the command and the evaluation target."""

    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    async def write(self, prompt: str, out: Out, tags: list[str]) -> str:
        parts: list[str] = []
        async for chunk in streaming(self.model).astream(
            [SystemMessage(REPORT_SYSTEM), HumanMessage(prompt)], config={"tags": tags}
        ):
            text = text_of(chunk)
            if text:
                out(text)
                parts.append(text)
        return "".join(parts)
```

with:

```python
class ReportTruncated(Exception):
    """The stream stopped at the model's output limit; the text is not a whole report."""


class ReportWriter:
    """One streaming call. Shared by the command and the evaluation target."""

    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    async def write(self, prompt: str, out: Out, tags: list[str]) -> str:
        parts: list[str] = []
        stop_reason: str | None = None
        async for chunk in streaming(self.model).astream(
            [SystemMessage(REPORT_SYSTEM), HumanMessage(prompt)], config={"tags": tags}
        ):
            text = text_of(chunk)
            if text:
                out(text)
                parts.append(text)
            stop_reason = chunk.response_metadata.get("stop_reason") or stop_reason
        if stop_reason == "max_tokens":
            raise ReportTruncated("the report hit the output limit (stop_reason max_tokens)")
        return "".join(parts)
```

and replace:

```python
    try:
        text = await ReportWriter(model).write(prompt, out, tags)
    except anthropic.RateLimitError as exc:
```

with:

```python
    try:
        text = await ReportWriter(model).write(prompt, out, tags)
    except ReportTruncated as exc:
        out(f"\n[{exc}; not saved. Rerun.]\n")
        return 1
    except anthropic.RateLimitError as exc:
```

`ruff format` will wrap the long `run_report(...)` call in the new test; accept it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass (`test_writer_falls_back_when_the_report_model_is_overloaded` is unaffected: the backup's single chunk carries no `stop_reason`).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/report.py packages/tri-wellness/tests/test_report.py
git commit -m "fix(wellness): do not save a report truncated at max_tokens"
```

---

### Task 9: W9, report prompt v2: disclaimer in code, practitioner-first priorities, no dosing

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/prompts/report.py:12, 43-75`
- Modify: `packages/tri-wellness/src/tri_wellness/report.py` (`run_report`, after Task 8)
- Modify: `packages/tri-wellness/src/tri_wellness/evals/target.py:41-50`
- Modify: `packages/tri-wellness/src/tri_wellness/testing.py:133-178`
- Test: `packages/tri-wellness/tests/test_report_prompt.py`, `test_report.py`, `test_evals.py` (edit and append)

**Interfaces:**
- Consumes: Task 8's `run_report` shape.
- Produces: `prompts.report.PROMPT_VERSION = "2"`; `prompts.report.with_disclaimer(report: str) -> str` (the fixed `DISCLAIMER`, a blank line, the model's text with any copy it wrote of the disclaimer removed, one trailing newline); `REPORT_SYSTEM` no longer contains `DISCLAIMER`; `run_report` prints the disclaimer before streaming and saves `with_disclaimer(text)`; `evals.target.run_case` returns `with_disclaimer(text)` as `report_md`; `testing.REPORT_BODY` (what the model writes) and `testing.REPORT_OK == f"{DISCLAIMER}\n\n{REPORT_BODY}"` (what is stored; unchanged text apart from the Supplements paragraph).

**Note for the assembler:** the code evaluator `has_required_sections` keeps checking that the first line is the disclaimer, which the target now guarantees; whether the evaluator should instead check that the model did not write its own is the evaluators spec's call. After merge Brian reruns `uv run tri-wellness eval` (experiment `report-v2`) and records the rates in `docs/notes/`. `tri-coach/tests/test_context.py` stores `REPORT_OK` as a report and reads only its Priorities; it is unaffected.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-wellness/tests/test_report_prompt.py`, replace

```python
from tri_wellness.prompts.report import (
    CHANGES_TITLE,
    DISCLAIMER,
    REPORT_RULES,
    REPORT_SYSTEM,
    SECTION_TITLES,
    findings_block,
    format_range,
    render_report_prompt,
)
```

with

```python
from tri_wellness.prompts.report import (
    CHANGES_TITLE,
    DISCLAIMER,
    PROMPT_VERSION,
    REPORT_RULES,
    REPORT_SYSTEM,
    SECTION_TITLES,
    findings_block,
    format_range,
    render_report_prompt,
    with_disclaimer,
)
from tri_wellness.testing import REPORT_BODY, REPORT_OK
```

and replace

```python
def test_system_prompt_has_structure_and_rules():
    assert DISCLAIMER in REPORT_SYSTEM
    for title in SECTION_TITLES:
        assert f"## {title}" in REPORT_SYSTEM
    assert CHANGES_TITLE in REPORT_SYSTEM
    assert "pattern suggests" in REPORT_RULES and "no generic" in REPORT_RULES.lower()
    assert REPORT_RULES in REPORT_SYSTEM
```

with

```python
def test_system_prompt_has_structure_and_rules():
    assert PROMPT_VERSION == "2"
    assert DISCLAIMER not in REPORT_SYSTEM and "Do not write a disclaimer" in REPORT_SYSTEM
    for title in SECTION_TITLES:
        assert f"## {title}" in REPORT_SYSTEM
    assert CHANGES_TITLE in REPORT_SYSTEM
    assert "pattern suggests" in REPORT_RULES and "no generic" in REPORT_RULES.lower()
    assert REPORT_RULES in REPORT_SYSTEM
    assert 'opens with "discuss with your practitioner first"' in REPORT_SYSTEM
    assert "No dose, no timing, no duration" in REPORT_SYSTEM
    assert "dose range" not in REPORT_SYSTEM


def test_with_disclaimer_prepends_once():
    assert with_disclaimer(REPORT_BODY) == REPORT_OK
    assert with_disclaimer(REPORT_OK) == REPORT_OK  # a model that wrote it anyway: not doubled
    assert with_disclaimer("\n\n## Draw conditions\nx") == f"{DISCLAIMER}\n\n## Draw conditions\nx\n"
    assert REPORT_OK.startswith(f"{DISCLAIMER}\n\n## Draw conditions")
```

In `packages/tri-wellness/tests/test_report.py`, replace

```python
from tri_wellness.testing import REPORT_OK, seed_daily_metrics, seed_panel
```

with

```python
from tri_wellness.testing import REPORT_BODY, REPORT_OK, seed_daily_metrics, seed_panel
```

and in `test_run_report_evaluates_saves_and_writes_file` replace

```python
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    out = []
    path = tmp_path / "report.md"
    code = await run_report(model, connect_factory(nocommit), reg, None, out.append, path)
    assert code == 0
    assert path.read_text() == REPORT_OK
```

with

```python
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_BODY)])  # no disclaimer from the model
    out = []
    path = tmp_path / "report.md"
    code = await run_report(model, connect_factory(nocommit), reg, None, out.append, path)
    assert code == 0
    assert path.read_text() == REPORT_OK  # the disclaimer was prepended in code
```

and

```python
    model2 = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
```

with

```python
    model2 = ScriptedChatModel(script=[AIMessage(content=REPORT_BODY)])
```

(the existing `assert REPORT_OK in joined` stays: `run_report` prints the disclaimer before the stream.)

In `packages/tri-wellness/tests/test_evals.py`, replace

```python
from tri_wellness.testing import REPORT_OK
```

with

```python
from tri_wellness.testing import REPORT_BODY, REPORT_OK
```

and in `test_target_writes_and_code_evaluators_pass_on_a_good_report` replace

```python
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    out = await make_target(model, reg)(c.inputs())
    assert out["report_md"] == REPORT_OK and model.calls == 1
```

with

```python
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_BODY)])
    out = await make_target(model, reg)(c.inputs())
    assert out["report_md"] == REPORT_OK and model.calls == 1  # disclaimer prepended by the target
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_report_prompt.py packages/tri-wellness/tests/test_report.py packages/tri-wellness/tests/test_evals.py -v`
Expected: `ImportError: cannot import name 'with_disclaimer'` and `cannot import name 'REPORT_BODY'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-wellness/src/tri_wellness/prompts/report.py`, replace:

```python
PROMPT_VERSION = "1"  # bump when REPORT_SYSTEM or REPORT_RULES changes; names the eval experiment
```

with:

```python
PROMPT_VERSION = "2"  # bump when REPORT_SYSTEM or REPORT_RULES changes; names the eval experiment
```

and replace the whole `REPORT_SYSTEM` block:

```python
REPORT_SYSTEM = f"""\
You are a functional-medicine practitioner who works with one endurance athlete. You write a
lab interpretation from findings that Python has already evaluated against a curated range
table. You explain patterns; you do not re-judge the numbers.

Write markdown with exactly this structure, these level-2 headings, in this order:

{DISCLAIMER}

## {SECTION_TITLES[0]}
Fasting, timing, active confounders, and how much weight each carries.
## {SECTION_TITLES[1]}
One level-3 heading per system that has at least one non-optimal marker, describing what the
pattern across its markers says; systems that are entirely optimal get one line each.
## {SECTION_TITLES[2]}
At most three, ranked, with reasoning.
## {SECTION_TITLES[3]}
Load, intensity and recovery over the coming weeks, written so it could be pasted into a
training-plan constraint.
## {SECTION_TITLES[4]}
Nutrition, sleep, stress and training changes tied to specific findings.
## {SECTION_TITLES[5]}
Compound, dose range, timing, target marker, and what would show it worked. Framed for
discussion with a practitioner.
## {SECTION_TITLES[6]}
Which markers, when, and under what draw conditions.
## {SECTION_TITLES[7]}
## {CHANGES_TITLE}
Only when the prompt says a previous panel exists.

The first line of your answer is the disclaimer above, verbatim.

{REPORT_RULES}"""
```

with (verbatim):

```python
REPORT_SYSTEM = f"""\
You are a functional-medicine practitioner who works with one endurance athlete. You write a
lab interpretation from findings that Python has already evaluated against a curated range
table. You explain patterns; you do not re-judge the numbers. The report is for the athlete to
take to their practitioner: it names what to discuss, not what to take.

Write markdown with exactly this structure, these level-2 headings, in this order. Do not write
a disclaimer or a preamble; a fixed one is placed above your text. Start with the first heading.

## {SECTION_TITLES[0]}
Fasting, timing, active confounders, and how much weight each carries.
## {SECTION_TITLES[1]}
One level-3 heading per system that has at least one non-optimal marker, describing what the
pattern across its markers says; systems that are entirely optimal get one line each. A marker
whose status is indeterminate is reported as the lab printed it, with what the bound rules out.
## {SECTION_TITLES[2]}
At most three, ranked, with reasoning. Any marker whose conventional status is low or high
comes first, and its item opens with "discuss with your practitioner first".
## {SECTION_TITLES[3]}
Load, intensity and recovery over the coming weeks, written so it could be pasted into a
training-plan constraint.
## {SECTION_TITLES[4]}
Nutrition, sleep, stress and training changes tied to specific findings.
## {SECTION_TITLES[5]}
Per item: the compound, the marker it targets, and what a retest would show if it worked.
No dose, no timing, no duration; those are the practitioner's call.
## {SECTION_TITLES[6]}
Which markers, when, and under what draw conditions.
## {SECTION_TITLES[7]}
## {CHANGES_TITLE}
Only when the prompt says a previous panel exists.

{REPORT_RULES}"""


def with_disclaimer(report: str) -> str:
    """The saved report: the fixed disclaimer, a blank line, then the model's text (minus its own
    copy of the disclaimer, if it wrote one despite the prompt), ending in one newline."""
    body = report.strip()
    if body.startswith(DISCLAIMER):
        body = body[len(DISCLAIMER) :].lstrip()
    return f"{DISCLAIMER}\n\n{body}\n"
```

In `packages/tri-wellness/src/tri_wellness/report.py`, replace:

```python
from tri_wellness.prompts.report import REPORT_SYSTEM, render_report_prompt
```

with:

```python
from tri_wellness.prompts.report import (
    DISCLAIMER,
    REPORT_SYSTEM,
    render_report_prompt,
    with_disclaimer,
)
```

replace (post-Task 8 text):

```python
    tags = [f"panel_id:{pid}", f"ranges_version:{registry.version}"]
    try:
        text = await ReportWriter(model).write(prompt, out, tags)
    except ReportTruncated as exc:
```

with:

```python
    tags = [f"panel_id:{pid}", f"ranges_version:{registry.version}"]
    out(f"{DISCLAIMER}\n\n")
    try:
        text = await ReportWriter(model).write(prompt, out, tags)
    except ReportTruncated as exc:
```

and replace:

```python
    with connect() as conn:
        report_id = repo.insert_report(conn, pid, registry.version, findings, text)
        conn.commit()
```

with:

```python
    text = with_disclaimer(text)
    with connect() as conn:
        report_id = repo.insert_report(conn, pid, registry.version, findings, text)
        conn.commit()
```

In `packages/tri-wellness/src/tri_wellness/evals/target.py`, replace:

```python
from tri_wellness.prompts.report import render_report_prompt
```

with:

```python
from tri_wellness.prompts.report import render_report_prompt, with_disclaimer
```

and replace:

```python
    text = await writer.write(prompt, lambda _s: None, ["eval"])
    return {"report_md": text, "findings": [f.model_dump(mode="json") for f in findings]}
```

with:

```python
    text = await writer.write(prompt, lambda _s: None, ["eval"])
    return {
        "report_md": with_disclaimer(text),
        "findings": [f.model_dump(mode="json") for f in findings],
    }
```

In `packages/tri-wellness/src/tri_wellness/testing.py`, replace:

```python
from tri_wellness import repo
from tri_wellness.labs.models import LabResult, PanelContext, RawResult
```

with:

```python
from tri_wellness import repo
from tri_wellness.labs.models import LabResult, PanelContext, RawResult
from tri_wellness.prompts.report import DISCLAIMER
```

and replace the whole `REPORT_OK` literal:

```python
REPORT_OK = """\
This is an educational interpretation of lab values against functional-medicine ranges for one \
athlete, prepared for discussion with a qualified practitioner; it is not a diagnosis or a \
prescription.

## Draw conditions
```

with:

```python
# What the model writes (prompt v2: no disclaimer, no dosing). REPORT_OK is what gets stored.
REPORT_BODY = """\
## Draw conditions
```

then replace:

```python
## Supplements
Iron bisglycinate 25 mg every other morning for 8 weeks, target ferritin above 50; retest \
shows it worked. Discuss with your practitioner.
```

with:

```python
## Supplements
Iron bisglycinate, target ferritin above 50; a retest above 50 with hs-CRP under 1 shows it \
worked. Form and amount are for your practitioner to set.
```

and after the closing `"""` of that literal add:

```python
REPORT_OK = f"{DISCLAIMER}\n\n{REPORT_BODY}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness packages/tri-coach/tests/test_context.py -q`
Expected: all pass (`test_sections_evaluator_requires_changes_only_with_a_previous_panel` still uses `REPORT_OK`, whose first line is the disclaimer; `test_run_eval_uses_the_lab_report_role_and_no_judge` reads `PROMPT_VERSION` through the module).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/prompts/report.py packages/tri-wellness/src/tri_wellness/report.py packages/tri-wellness/src/tri_wellness/evals/target.py packages/tri-wellness/src/tri_wellness/testing.py packages/tri-wellness/tests/test_report_prompt.py packages/tri-wellness/tests/test_report.py packages/tri-wellness/tests/test_evals.py
git commit -m "feat(wellness): report prompt v2; disclaimer prepended in code, no dosing"
```

---

### Task 10: N1 brick legs share TSS with the bike leg only

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/nutrition/energy.py:47-63`
- Test: `packages/tri-nutrition/tests/test_energy.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: no signature change; `session_kcal` splits a leg-less brick into a bike leg with `planned_tss * BRICK_BIKE_FRACTION` and `distance_km=None`, and a run leg with `planned_tss=None`, `distance_km=None`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_energy.py` (after `test_brick_without_legs_splits_by_fraction`):

```python
def test_brick_without_legs_shares_tss_with_the_bike_leg_only():
    brick = session(sport="brick", duration_min=150, planned_tss=180, distance_km=40)
    bike_min = round(150 * C.BRICK_BIKE_FRACTION)
    bike = 180 * C.BRICK_BIKE_FRACTION * 250 * C.BIKE_KCAL_PER_TSS_FTP
    run = (150 - bike_min) / 60 * 75 * C.SPORT_KCAL_PER_KG_H["run"]["endurance"]
    kcal = energy.session_kcal(brick, profile(), ftp_watts=250)
    assert kcal == pytest.approx(bike + run)  # 1080 + 625
    assert 1500 < kcal < 1800  # not the whole brick's TSS on the bike plus a 40 km run on top
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_energy.py::test_brick_without_legs_shares_tss_with_the_bike_leg_only -v`
Expected: `assert 4620.0 == 1705.0 ± ...` (the bike leg is priced from TSS 180 and the run leg from the copied 40 km).

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/nutrition/energy.py`, replace:

```python
    if session.sport == "brick":
        legs = session.legs
        if legs is None:
            bike_min = round(session.duration_min * C.BRICK_BIKE_FRACTION)
            legs = [
                session.model_copy(
                    update={"sport": "bike", "duration_min": bike_min, "legs": None}
                ),
                session.model_copy(
                    update={
                        "sport": "run",
                        "duration_min": session.duration_min - bike_min,
                        "legs": None,
                    }
                ),
            ]
        return sum(session_kcal(leg, profile, ftp_watts) for leg in legs)
```

with:

```python
    if session.sport == "brick":
        legs = session.legs
        if legs is None:
            # The bike leg gets its share of the brick's TSS; the run leg is priced by duration
            # and intensity. Neither leg inherits the whole brick's distance.
            bike_min = round(session.duration_min * C.BRICK_BIKE_FRACTION)
            tss = session.planned_tss
            legs = [
                session.model_copy(
                    update={
                        "sport": "bike",
                        "duration_min": bike_min,
                        "planned_tss": tss * C.BRICK_BIKE_FRACTION if tss is not None else None,
                        "distance_km": None,
                        "legs": None,
                    }
                ),
                session.model_copy(
                    update={
                        "sport": "run",
                        "duration_min": session.duration_min - bike_min,
                        "planned_tss": None,
                        "distance_km": None,
                        "legs": None,
                    }
                ),
            ]
        return sum(session_kcal(leg, profile, ftp_watts) for leg in legs)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass (`test_brick_without_legs_splits_by_fraction` still passes: it sets no TSS or distance).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/nutrition/energy.py packages/tri-nutrition/tests/test_energy.py
git commit -m "fix(nutrition): price a leg-less brick from the bike leg's share of TSS"
```

---

### Task 11: N2 sodium and fluid 0 mean none

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/nutrition/bounds.py:76-87`
- Modify: `packages/tri-nutrition/src/tri_nutrition/prompts/fuel.py:17, 35-36`
- Test: `packages/tri-nutrition/tests/test_bounds.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `_fluid_sodium_violations` treats `0` as "none planned" for both fluid and sodium; the sodium range applies to a positive value only. `PROMPT_VERSION = "4"`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_bounds.py` after `test_fuel_fluid_and_sodium`:

```python
def test_fuel_sodium_zero_means_none_and_is_valid():
    # a 40-minute endurance run: nothing during the session is a valid plan
    assert vf(fuel(sodium_mg_per_h=0, fluid_ml_per_h=0)) == []
    assert any("sodium" in v for v in vf(fuel(sodium_mg_per_h=100)))
    assert vf(fuel(sodium_mg_per_h=300)) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_bounds.py::test_fuel_sodium_zero_means_none_and_is_valid -v`
Expected: `AssertionError` on the first assert: `['2026-09-14 w1: sodium 0 mg/h is outside 300 to 1500'] == []`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/nutrition/bounds.py`, replace:

```python
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
```

with:

```python
def _fluid_sodium_violations(label: str, fluid: int | None, sodium: int | None) -> list[str]:
    """0 means none planned and is valid; the bounds apply to a positive value."""
    out: list[str] = []
    if fluid and fluid > C.FUEL_FLUID_MAX_ML_PER_H:
        out.append(f"{label}: fluid {fluid} ml/h exceeds {C.FUEL_FLUID_MAX_ML_PER_H}")
    if sodium and not (C.FUEL_SODIUM_MIN_MG_PER_H <= sodium <= C.FUEL_SODIUM_MAX_MG_PER_H):
        out.append(
            f"{label}: sodium {sodium} mg/h is outside {C.FUEL_SODIUM_MIN_MG_PER_H} to "
            f"{C.FUEL_SODIUM_MAX_MG_PER_H}"
        )
    return out
```

In `packages/tri-nutrition/src/tri_nutrition/prompts/fuel.py`, replace:

```python
PROMPT_VERSION = "3"  # bump when FUEL_SYSTEM or RACE_SYSTEM changes; names the eval experiment
```

with:

```python
PROMPT_VERSION = "4"  # bump when FUEL_SYSTEM or RACE_SYSTEM changes; names the eval experiment
```

and replace:

```
- fluid_ml_per_h at most {C.FUEL_FLUID_MAX_ML_PER_H}; sodium_mg_per_h between
  {C.FUEL_SODIUM_MIN_MG_PER_H} and {C.FUEL_SODIUM_MAX_MG_PER_H}.
```

with:

```
- fluid_ml_per_h at most {C.FUEL_FLUID_MAX_ML_PER_H}; sodium_mg_per_h 0 when none is needed,
  otherwise between {C.FUEL_SODIUM_MIN_MG_PER_H} and {C.FUEL_SODIUM_MAX_MG_PER_H}.
```

The line "Sessions under 90 minutes at endurance intensity need little or nothing during; say so rather than inventing intake." stays as it is.

**Note for the assembler:** the spec does not name a `PROMPT_VERSION` bump, but `FUEL_SYSTEM` changes here and the README rule ("bump `PROMPT_VERSION` whenever a fueling prompt changes") plus the §4 eval rerun both want one; the rerun then lands as `fuel-v4`. Drop the two `PROMPT_VERSION` lines above if the assembler prefers to keep `3`. `validate_race` shares `_fluid_sodium_violations`, so a race leg with `bike_sodium: 0` is now valid too; the race prompt still asks for sodium per leg.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass (`test_fuel_fluid_and_sodium` still fails 299 and 1501; no test pins `PROMPT_VERSION`).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/nutrition/bounds.py packages/tri-nutrition/src/tri_nutrition/prompts/fuel.py packages/tri-nutrition/tests/test_bounds.py
git commit -m "fix(nutrition): sodium and fluid 0 mean none; the range applies to a positive value"
```

---

### Task 12: N3 `check-in --yes` skips violating changes and never approves a review it did not produce

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/state.py:17-27`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py:38, 177-202`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py:23-37`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py:192-200`
- Modify: `packages/tri-nutrition/src/tri_nutrition/repl.py:215-243`
- Modify: `packages/tri-nutrition/src/tri_nutrition/cli.py:279-280`
- Modify: `packages/tri-nutrition/README.md:105-108` (and its copy `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-nutrition/readme.md`)
- Test: `packages/tri-nutrition/tests/test_graph.py` (edit one test, append one), `packages/tri-nutrition/tests/test_repl.py` (append), `packages/tri-nutrition/tests/test_fuel_node.py` (one assertion added)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `NutritionState.pending_violations: dict[str, list[str]]`: fuel violations keyed by `tp_workout_id`, the race plan's under `RACE_VIOLATIONS_KEY`. Set by `fuel`, cleared by `review` on reject and by `apply` when nothing remains.
  - The review interrupt payload gains `"violations": dict[str, list[str]]`.
  - `tri_nutrition.repl.RACE_VIOLATIONS_KEY = "race"`, `ALREADY_PAUSED_HINT`, a new `PAUSED_HINT` text, `violations_for(change, violations) -> list[str]`, `split_violating(changes, violations) -> tuple[list[NutritionChange], list[tuple[NutritionChange, list[str]]]]`.
  - `checkin_run` returns 0 (nothing pending, or approved in full), 1 (approved with violating changes skipped), 3 (paused: this run's review without `approve`, or a review an earlier run left, which is never approved).
  - `ReviewDecision` already accepts `action="edit"` with `changes: list[NutritionChange] | None` (`models.py:186-189`); the resume value `{"action": "edit", "changes": [...]}` validates through `ReviewDecision.model_validate` in `review_node` and replaces `pending_changes`. An empty list is valid and routes to `apply`, which reports `Applied 0 of 0`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-nutrition/tests/test_graph.py`, replace the existing test:

```python
async def test_checkin_run_pauses_then_approves_on_second_run(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    model = ScriptedChatModel(script=proposal_script({}, "extend horizon"))
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=False) == 3
    text = "".join(printed)
    assert "approve / reject" in text and "paused" in text and g.calls == []
    printed.clear()
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=True) == 0
    assert "already waiting at review" in "".join(printed) and len(g.calls) == 1
    assert (await graph.aget_state(CFG)).next == ()
```

with:

```python
async def test_checkin_run_pauses_and_a_later_yes_does_not_approve_it(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    model = ScriptedChatModel(script=proposal_script({}, "extend horizon"))
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=False) == 3
    text = "".join(printed)
    assert "approve / reject" in text and "paused" in text and g.calls == []
    printed.clear()
    # the review belongs to whoever started it: --yes must not approve it
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=True) == 3
    assert "already waiting at review" in "".join(printed) and g.calls == []
    assert (await graph.aget_state(CFG)).next == ("review",)
```

and append:

```python
async def test_checkin_run_yes_skips_violating_changes_and_exits_1(ndb, make_deps, mem_store):
    if ndb.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    tue = MONDAY + timedelta(days=2)
    week = [
        session_json(MONDAY, "bike", 120, "endurance", 100),
        session_json(tue, "run", 45, "threshold", 60),
    ]
    seed_goal_and_plan(ndb, MONDAY, [("build", week)])
    seed_workouts(
        ndb,
        [
            {
                "tp_workout_id": "w1",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 7200,
                "title": "bike 120",
            },
            {
                "tp_workout_id": "w2",
                "workout_date": tue,
                "sport": "run",
                "planned_duration_sec": 2700,
                "title": "run 45",
            },
        ],
    )
    bad = tool_call("SessionFuel", session_fuel_json("w2", tue, products=["Mystery"]))
    model = ScriptedChatModel(
        script=[
            *proposal_script({}, "extend horizon"),
            tool_call("SessionFuel", session_fuel_json("w1", MONDAY)),
            bad,
            bad,  # the retry fails the same way
        ]
    )
    g, tp = FakeGarmin(), FakeTp()
    graph = build_graph(make_deps(model, garmin=g, tp=tp, horizon=7), InMemorySaver(), mem_store)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=True) == 1
    text = "".join(printed)
    assert "skipped set_session_note w2" in text and "Mystery" in text
    assert [c[0] for c in g.calls] == ["set_nutrition_daily_settings"]
    assert [(c[0], c[1]["workout_id"]) for c in tp.calls] == [
        ("tp_get_workout_note", "w1"),
        ("tp_set_workout_note", "w1"),
    ]
    snap = await graph.aget_state(CFG)
    assert snap.next == () and snap.values["pending_changes"] == []
    assert snap.values["pending_violations"] == {}
```

Append to `packages/tri-nutrition/tests/test_repl.py`, adding `split_violating` to the existing `from tri_nutrition.repl import (...)` list:

```python
def test_split_violating_keeps_order_and_matches_notes_by_key():
    note = NutritionChange(
        op="set_session_note", target_key="w2", day=MONDAY, payload={}, reason="r"
    )
    race = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="r")
    violations = {"w2": ["too much"], "race": ["no pre-race step"]}
    clean, skipped = split_violating([change(), note, race], violations)
    assert clean == [change()]
    assert skipped == [(note, ["too much"]), (race, ["no pre-race step"])]
    assert split_violating([note], {}) == ([note], [])
```

In `packages/tri-nutrition/tests/test_fuel_node.py`, replace the end of `test_retries_once_and_keeps_violations`:

```python
    assert "VIOLATIONS" in out["pending_summary"] and "Mystery" in out["pending_summary"]
    # a session plan with violations is still proposed; the athlete decides at review
    assert [c.op for c in out["pending_changes"]].count("set_session_note") == 2
```

with:

```python
    assert "VIOLATIONS" in out["pending_summary"] and "Mystery" in out["pending_summary"]
    # a session plan with violations is still proposed; the athlete decides at review, and
    # check-in --yes reads pending_violations to skip it
    assert [c.op for c in out["pending_changes"]].count("set_session_note") == 2
    assert list(out["pending_violations"]) == ["w2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_graph.py packages/tri-nutrition/tests/test_repl.py packages/tri-nutrition/tests/test_fuel_node.py -v`
Expected: `test_repl.py` fails at import (`ImportError: cannot import name 'split_violating'`); `test_checkin_run_pauses_and_a_later_yes_does_not_approve_it` fails `assert 0 == 3`; `test_checkin_run_yes_skips_violating_changes_and_exits_1` fails `assert 0 == 1`; `test_retries_once_and_keeps_violations` fails `KeyError: 'pending_violations'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/graph/state.py`, replace:

```python
    pending_changes: list[NutritionChange]
    pending_summary: str | None
```

with:

```python
    pending_changes: list[NutritionChange]
    pending_violations: dict[str, list[str]]  # fuel violations by tp_workout_id; race under "race"
    pending_summary: str | None
```

In `packages/tri-nutrition/src/tri_nutrition/repl.py`, replace:

```python
PAUSED_HINT = (
    "paused at review; run `tri-nutrition check-in --yes` to approve, or `tri-nutrition chat` "
    "to answer approve / reject <note> / edit"
)


async def checkin_run(graph: Any, *, thread_id: str, out: Out, approve: bool) -> int:
    """One unattended check-in. 0: nothing pending or approved; 3: a change set waits at review."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    if snap.next == ("review",):
        values = snap.values or {}
        pending = {
            "summary": values.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in values.get("pending_changes") or []],
            "last_error": values.get("last_error"),
        }
        out("a change set is already waiting at review:\n" + render_review(pending) + "\n")
    else:
        request = {"messages": [HumanMessage(CHECKIN_REQUEST)]}
        printer = await run_turn(graph, request, thread_id, out)
        if printer.interrupt is None:
            return 0
        out("\n" + render_review(printer.interrupt) + "\n")
    if not approve:
        out(PAUSED_HINT + "\n")
        return 3
    printer = await run_turn(graph, Command(resume={"action": "approve"}), thread_id, out)
    return 0 if printer.interrupt is None else 3
```

with:

```python
PAUSED_HINT = "paused at review; run `tri-nutrition chat` to answer approve / reject <note> / edit"
ALREADY_PAUSED_HINT = (
    "a change set is already waiting at review; resolve it in `tri-nutrition chat` first"
)
RACE_VIOLATIONS_KEY = "race"  # the race plan's key in pending_violations (sessions use their id)


def violations_for(change: NutritionChange, violations: dict[str, list[str]]) -> list[str]:
    """The fuel violations behind one proposed note, from the review payload's `violations`."""
    if change.op == "set_session_note":
        return list(violations.get(change.target_key) or [])
    if change.op == "set_race_note":
        return list(violations.get(RACE_VIOLATIONS_KEY) or [])
    return []


def split_violating(
    changes: list[NutritionChange], violations: dict[str, list[str]]
) -> tuple[list[NutritionChange], list[tuple[NutritionChange, list[str]]]]:
    """(the clean changes in order, [(violating change, its violations)])."""
    clean: list[NutritionChange] = []
    skipped: list[tuple[NutritionChange, list[str]]] = []
    for c in changes:
        v = violations_for(c, violations)
        if v:
            skipped.append((c, v))
        else:
            clean.append(c)
    return clean, skipped


async def checkin_run(graph: Any, *, thread_id: str, out: Out, approve: bool) -> int:
    """One unattended check-in. 0: nothing pending, or approved in full; 1: approved with the
    violating changes skipped (each is printed with its violations); 3: a change set waits at
    review, either this run's without `approve`, or one an earlier run left, which is never
    approved here."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    if snap.next == ("review",):
        values = snap.values or {}
        pending = {
            "summary": values.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in values.get("pending_changes") or []],
            "last_error": values.get("last_error"),
        }
        out("a change set is already waiting at review:\n" + render_review(pending) + "\n")
        out(ALREADY_PAUSED_HINT + "\n")
        return 3
    request = {"messages": [HumanMessage(CHECKIN_REQUEST)]}
    printer = await run_turn(graph, request, thread_id, out)
    if printer.interrupt is None:
        return 0
    out("\n" + render_review(printer.interrupt) + "\n")
    if not approve:
        out(PAUSED_HINT + "\n")
        return 3
    changes = [NutritionChange.model_validate(c) for c in printer.interrupt.get("changes", [])]
    clean, skipped = split_violating(changes, printer.interrupt.get("violations") or {})
    for change, reasons in skipped:
        out(f"skipped {change.op} {change.target_key or change.day}: {'; '.join(reasons)}\n")
    resume: dict[str, Any] = {"action": "approve"}
    if skipped:
        resume = {"action": "edit", "changes": [c.model_dump(mode="json") for c in clean]}
    printer = await run_turn(graph, Command(resume=resume), thread_id, out)
    if printer.interrupt is not None:
        return 3
    return 1 if skipped else 0
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`, replace:

```python
from tri_nutrition.repl import render_fuel, render_race
```

with:

```python
from tri_nutrition.repl import RACE_VIOLATIONS_KEY, render_fuel, render_race
```

replace:

```python
            plan_r, rv = await planner.race(profile, library, fuel_log, ctx, target, cfg)
            with deps.connect() as conn:
```

with:

```python
            plan_r, rv = await planner.race(profile, library, fuel_log, ctx, target, cfg)
            if rv:
                violations_by_id[RACE_VIOLATIONS_KEY] = rv
            with deps.connect() as conn:
```

and replace:

```python
        summary = (state.get("pending_summary") or "") + "\n\n" + "\n".join(block)
        return {"pending_changes": changes, "pending_summary": summary.strip()}
```

with:

```python
        summary = (state.get("pending_summary") or "") + "\n\n" + "\n".join(block)
        return {
            "pending_changes": changes,
            "pending_violations": violations_by_id,
            "pending_summary": summary.strip(),
        }
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py`, replace:

```python
            "changes": [c.model_dump(mode="json") for c in changes],
            "last_error": state.get("last_error"),
        }
    )
```

with:

```python
            "changes": [c.model_dump(mode="json") for c in changes],
            "violations": state.get("pending_violations") or {},
            "last_error": state.get("last_error"),
        }
    )
```

and replace:

```python
        update["pending_changes"] = []
        update["pending_summary"] = None
        update["profile_overrides"] = None
```

with:

```python
        update["pending_changes"] = []
        update["pending_violations"] = {}
        update["pending_summary"] = None
        update["profile_overrides"] = None
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py`, replace:

```python
        return {
            "pending_changes": r.remaining,
            "pending_summary": state.get("pending_summary") if r.remaining else None,
```

with:

```python
        return {
            "pending_changes": r.remaining,
            "pending_violations": (state.get("pending_violations") or {}) if r.remaining else {},
            "pending_summary": state.get("pending_summary") if r.remaining else None,
```

In `packages/tri-nutrition/src/tri_nutrition/cli.py`, replace:

```python
    """Sync, run the check-in on the nutrition thread, and pause at review (exit code 3) or
    approve with --yes."""
```

with:

```python
    """Sync, run the check-in on the nutrition thread, and pause at review (exit code 3) or
    approve with --yes. Under --yes a change that failed validation is skipped and printed
    (exit code 1); a review left by an earlier run is shown, not approved (exit code 3)."""
```

In `packages/tri-nutrition/README.md`, replace:

```
- `tri-nutrition check-in [--yes] [--no-sync] [--no-live]`: runs `tri sync`, sends the fixed
  check-in request on the nutrition thread, prints the report and any proposed change set, and
  exits 3 while it waits at review. `--yes` approves. Run it again (or `chat`) to resume a
  paused review rather than start a second one.
```

with:

```
- `tri-nutrition check-in [--yes] [--no-sync] [--no-live]`: runs `tri sync`, sends the fixed
  check-in request on the nutrition thread, prints the report and any proposed change set, and
  exits 3 while it waits at review. `--yes` approves the changes that passed validation; a
  note whose plan still has violations is skipped and printed, and the exit code is 1. A review
  left by an earlier run is shown but never approved here (exit 3): answer it in `chat`.
```

Copy the README to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-nutrition/readme.md` (the copy exists; overwrite it).

The interactive review already shows the violations: `render_fuel` prints a `VIOLATIONS:` line per session and `render_race` one for the race inside `pending_summary`, so `render_review` is unchanged. `chat_loop`'s `/pending` payload does not carry `violations`; only `checkin_run` reads it.

**Note for the assembler:** the spec names only `violations_by_id` (sessions). The race plan's violations are keyed `"race"` in the same map so `--yes` skips a violating race note too, since it is the same unattended write; drop the two `RACE_VIOLATIONS_KEY` edits in `fuel.py` and the `set_race_note` branch of `violations_for` if the row is to be read literally. Also: `PAUSED_HINT` loses "run `tri-nutrition check-in --yes` to approve", since that path now returns 3.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass. `tri-coach` embeds this graph (`build_graph(..., embedded=True)`); the extra state key is not read there, so `uv run pytest packages/tri-coach -q` is unchanged.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/graph/state.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py packages/tri-nutrition/src/tri_nutrition/repl.py packages/tri-nutrition/src/tri_nutrition/cli.py packages/tri-nutrition/README.md packages/tri-nutrition/tests/test_graph.py packages/tri-nutrition/tests/test_repl.py packages/tri-nutrition/tests/test_fuel_node.py
git commit -m "fix(nutrition): check-in --yes skips violating notes and never approves an earlier review"
```

---

### Task 13: N4 review persists overrides when there is nothing to review

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py:1-22` (after Task 12 the interrupt block also carries `violations`; this task touches the header, imports and the empty-changes branch only)
- Test: `packages/tri-nutrition/tests/test_graph.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `review_node` becomes `async def review_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]` (LangGraph injects `store` by name, as it does for `fuel`). With no `pending_changes` and non-empty `profile_overrides` it writes `apply_overrides(base, overrides)` to the Store, returns `profile_overrides=None`, `review_decision=None` and the message `No nutrition changes to review; profile updated: {...}`; `after_review` then ends.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_graph.py`:

```python
async def test_override_only_checkin_persists_the_override_and_leaves_state_clean(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    script = [
        *proposal_script({}, "extend horizon"),
        *proposal_script({"scale_days_per_week": 5}, "weigh in more often"),
    ]
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=script), g, horizon=3)
    await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    await graph.ainvoke(APPROVE, CFG)  # today's target is now on Garmin
    # scale_days_per_week changes no target, so the second proposal has no changes to review
    out = await graph.ainvoke({"messages": [HumanMessage("check in again")]}, CFG)
    assert "__interrupt__" not in out and len(g.calls) == 1
    assert (await S.get_profile(mem_store)).scale_days_per_week == 5
    assert out["profile_overrides"] is None and out["pending_changes"] == []
    assert out["review_decision"] is None
    assert "profile updated" in out["messages"][-1].content
    assert (await graph.aget_state(CFG)).next == ()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_graph.py::test_override_only_checkin_persists_the_override_and_leaves_state_clean -v`
Expected: `assert 3 == 5` (the override stays in state; the profile is unchanged).

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py`, replace:

```python
"""Review node: pause the graph until the athlete decides.

`interrupt(value)` stops the run with the value exposed to the caller as `__interrupt__` and the
checkpoint records where we are. On `Command(resume=x)` the node runs again from the top and
`interrupt()` returns x. Nothing before the interrupt may have side effects.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import ReviewDecision


def review_node(state: NutritionState) -> dict[str, Any]:
    changes = state.get("pending_changes") or []
    if not changes:
        return {"review_decision": None, "messages": [AIMessage("No nutrition changes to review.")]}
    raw = interrupt(
```

with:

```python
"""Review node: pause the graph until the athlete decides.

`interrupt(value)` stops the run with the value exposed to the caller as `__interrupt__` and the
checkpoint records where we are. On `Command(resume=x)` the node runs again from the top and
`interrupt()` returns x. Nothing before the interrupt may have side effects. With nothing to
review there is no interrupt, and proposed profile overrides are persisted here, since `apply`
never runs for an empty change set.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from tri_nutrition import store as S
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import ReviewDecision


async def review_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]:
    changes = state.get("pending_changes") or []
    if not changes:
        text = "No nutrition changes to review."
        overrides = state.get("profile_overrides")
        if overrides:
            base = await S.get_profile(store)
            if base is not None:
                await S.put_profile(store, apply_overrides(base, overrides))
                text = f"No nutrition changes to review; profile updated: {overrides}"
        return {"review_decision": None, "profile_overrides": None, "messages": [AIMessage(text)]}
    raw = interrupt(
```

`apply_overrides` lives in `graph/nodes/targets.py`; `targets.py` does not import `review.py`, so there is no cycle. `test_checkin_extend_horizon_reproposes_today_only_when_changed` still matches on `"No nutrition changes to review"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py packages/tri-nutrition/tests/test_graph.py
git commit -m "fix(nutrition): review persists an override-only proposal and clears it from state"
```

---

### Task 14: N5 the stored race plan is matched by event date

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py:142`
- Test: `packages/tri-nutrition/tests/test_fuel_node.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: no signature change; `stored_race` is the stored `race` row whose `day == ctx.event_date`, else `None`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_fuel_node.py` after `test_race_update_uses_stored_note_id`:

```python
async def test_moved_event_date_creates_a_new_note(ndb, mem_store, make_deps):
    model = ScriptedChatModel(
        script=[
            fuel_call("w1", MONDAY),
            fuel_call("w2", TUE),
            tool_call("RaceFuelPlan", race_plan_json(RACE)),
        ]
    )
    deps, graph, h = await seeded(ndb, mem_store, make_deps, model)
    old_day = MONDAY + timedelta(days=6)  # the race was here before the goal moved to RACE
    rid = repo.upsert_fuel_plan(ndb, "race", old_day, None, {"note_text": "old"}, [])
    repo.mark_fuel_written(ndb, rid, "note-77")
    out = await graph.ainvoke({"pending_changes": []}, CFG)
    race = next(c for c in out["pending_changes"] if c.op == "set_race_note")
    assert race.target_key == "" and race.day == RACE  # create, not an update of note-77
    plans = {p.day: p for p in repo.list_fuel_plans(ndb, MONDAY, RACE) if p.kind == "race"}
    assert plans[old_day].written and plans[old_day].tp_note_id == "note-77"
    assert plans[old_day].payload == {"note_text": "old"} and not plans[RACE].written
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_fuel_node.py::test_moved_event_date_creates_a_new_note -v`
Expected: `assert 'note-77' == ''` (the old row is picked as `stored_race` and its note would be overwritten).

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`, replace:

```python
        stored_race = next((p for p in stored if p.kind == "race"), None)
```

with:

```python
        stored_race = next(
            (p for p in stored if p.kind == "race" and p.day == ctx.event_date), None
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass (`test_race_update_uses_stored_note_id` stores its old row on `RACE`, so it still updates `note-77`).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py packages/tri-nutrition/tests/test_fuel_node.py
git commit -m "fix(nutrition): match the stored race plan by event date"
```

---

### Task 15: N6 today's completed workouts stay in the horizon

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/plan_loader.py:119-125`
- Test: `packages/tri-nutrition/tests/test_plan_loader.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: no signature change; `_planned_workouts(conn, start, end)` keeps a completed workout dated `start`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_plan_loader.py` after `test_load_horizon_from_tp_calendar_when_no_designed_weeks`:

```python
def test_load_horizon_keeps_todays_completed_workout(pdb):
    # an afternoon regenerate must not drop the session already done today and lower the target
    seed_goal_and_plan(pdb, MONDAY, [("base", None)])
    seed_workouts(
        pdb,
        [
            {
                "tp_workout_id": "done-today",
                "workout_date": MONDAY,
                "sport": "bike",
                "planned_duration_sec": 5400,
                "completed": True,
            },
            {
                "tp_workout_id": "done-later",
                "workout_date": MONDAY + timedelta(days=1),
                "sport": "run",
                "planned_duration_sec": 2400,
                "completed": True,
            },
            {
                "tp_workout_id": "w3",
                "workout_date": MONDAY + timedelta(days=2),
                "sport": "run",
                "planned_duration_sec": 2400,
            },
        ],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert ctx.source == "tp_calendar"
    assert [s.tp_workout_id for s in sessions] == ["done-today", "w3"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_plan_loader.py::test_load_horizon_keeps_todays_completed_workout -v`
Expected: `assert ['w3'] == ['done-today', 'w3']`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/plan_loader.py`, replace:

```python
def _planned_workouts(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title, planned_duration_sec, "
        "planned_distance_m, planned_tss, planned_if from workouts "
        "where not completed and workout_date between %s and %s order by workout_date",
        (start, end),
    ).fetchall()
```

with:

```python
def _planned_workouts(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    """Workouts in [start, end]. A completed one is dropped unless it is dated `start` (today):
    an afternoon regenerate must not lower today's target."""
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title, planned_duration_sec, "
        "planned_distance_m, planned_tss, planned_if from workouts "
        "where (not completed or workout_date = %s) and workout_date between %s and %s "
        "order by workout_date",
        (start, start, end),
    ).fetchall()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass (`test_load_horizon_from_tp_calendar_when_no_designed_weeks` drops `w2`, completed on `MONDAY + 1`, as before).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/plan_loader.py packages/tri-nutrition/tests/test_plan_loader.py
git commit -m "fix(nutrition): keep today's completed workouts in the horizon"
```

---

### Task 16: N7 the title keeps id-less sessions on one day apart

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/repo.py:94-116`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py:158-167`
- Test: `packages/tri-nutrition/tests/test_repo.py` (append)

**Interfaces:**
- Consumes: migration 006's `fuel_plans_kind_day_workout_title_idx` on `(kind, day, coalesce(tp_workout_id, ''), coalesce((payload->>'title'), ''))` replacing `fuel_plans_kind_day_workout_idx` (assembler).
- Produces: `repo.upsert_fuel_plan(conn, kind, day, tp_workout_id, payload, violations, title: str | None = None) -> int`; when `title` is given it is stored as `payload["title"]`, and the conflict target is the four-expression index. The fuel node passes `title=s.title` for session plans, so a stored session payload now carries `title`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_repo.py` after `test_fuel_plans_roundtrip_and_unique`:

```python
def test_two_idless_sessions_on_one_day_are_two_rows(ndb):
    idx = "select to_regclass('fuel_plans_kind_day_workout_title_idx') as t"
    if ndb.execute(idx).fetchone()["t"] is None:
        pytest.skip("migrations/006_fixes.sql not applied to the test database")
    swim = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "s"}, [], title="Swim")
    bike = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "b"}, [], title="Bike")
    assert swim != bike
    again = repo.upsert_fuel_plan(ndb, "session", MON, None, {"note_text": "s2"}, [], title="Swim")
    assert again == swim
    plans = repo.list_fuel_plans(ndb, MON, MON)
    assert sorted(p.payload["title"] for p in plans) == ["Bike", "Swim"]
    assert next(p for p in plans if p.id == swim).payload["note_text"] == "s2"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_repo.py::test_two_idless_sessions_on_one_day_are_two_rows -v`
Expected: before 006 is applied to the test database the test skips; after it, `TypeError: upsert_fuel_plan() got an unexpected keyword argument 'title'`.

**Note for the assembler:** once 006 drops `fuel_plans_kind_day_workout_idx`, the current `on conflict (kind, day, coalesce(tp_workout_id, ''))` raises `InvalidColumnReference: there is no unique or exclusion constraint matching the ON CONFLICT specification` in every fuel test and in the fuel node, so 006 and this task land together: apply 006 to the test database, then run Step 3, then Step 4. The test database on `main` today still has the old index (`to_regclass` returns `fuel_plans_kind_day_workout_idx`), so the test skips until 006 is applied.

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/repo.py`, replace:

```python
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
```

with:

```python
def upsert_fuel_plan(
    conn: Conn,
    kind: str,
    day: date,
    tp_workout_id: str | None,
    payload: dict[str, Any],
    violations: list[str],
    title: str | None = None,
) -> int:
    """Insert or replace the plan keyed by (kind, day, workout id, title). `title` is stored in
    the payload; it keeps two id-less sessions on one day apart (migration 006)."""
    if title is not None:
        payload = {**payload, "title": title}
    row = conn.execute(
        """
        insert into fuel_plans (kind, day, tp_workout_id, payload, violations, generated_at)
        values (%s, %s, %s, %s, %s, now())
        on conflict (kind, day, coalesce(tp_workout_id, ''), coalesce((payload->>'title'), ''))
        do update set
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
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`, replace:

```python
            with deps.connect() as conn:
                repo.upsert_fuel_plan(
                    conn,
                    "session",
                    s.day,
                    s.tp_workout_id,
                    plan.model_dump(mode="json"),
                    violations,
                )
                conn.commit()
```

with:

```python
            with deps.connect() as conn:
                repo.upsert_fuel_plan(
                    conn,
                    "session",
                    s.day,
                    s.tp_workout_id,
                    plan.model_dump(mode="json"),
                    violations,
                    title=s.title,
                )
                conn.commit()
```

`mark_fuel_written_for` still matches on `(kind, day, coalesce(tp_workout_id, ''))`; id-less sessions are never written (the node `continue`s before proposing them), so a title collision cannot reach it. `tri-web/tests/test_today.py:67` and the nutrition tests call `upsert_fuel_plan` positionally without a title and are unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests packages/tri-web/tests/test_today.py -q`
Expected: all pass, with 006 applied to the test database (otherwise the fuel node and repo tests fail on the missing index as described above).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/repo.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py packages/tri-nutrition/tests/test_repo.py
git commit -m "fix(nutrition): fuel plans keyed by title so id-less sessions on one day stay apart"
```

---

### Task 17: N8 the deficit follows `target_date`, capped at `max_weekly_change_pct`

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/nutrition/targets.py:47-66, 112`
- Modify: `packages/tri-nutrition/src/tri_nutrition/nutrition/constants.py:102-109`
- Modify: `packages/tri-nutrition/src/tri_nutrition/tools/profile.py:9-17, 49-58`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py:39`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py:47`
- Test: `packages/tri-nutrition/tests/test_targets.py` (append), `packages/tri-nutrition/tests/test_profile_tools.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `targets.weekly_change_pct_needed(profile, today: date) -> float | None`: percent of body mass per week that reaches `target_weight_kg` by `target_date`; `None` without a target weight or date, or when the date is not after `today`.
  - `targets.rate_capped(profile, today: date | None) -> bool`: the needed rate exceeds `max_weekly_change_pct`.
  - `targets.effective_weekly_change_pct(profile, today: date | None) -> float`: `min(needed, cap)`, or the cap when there is nothing to work from.
  - `targets.daily_deficit_kcal(profile, today: date | None = None) -> int` and `targets.goal_adjust(profile, day_type, phase, today: date | None = None)`; `build` passes its `today`. Without `today` both behave as before (the cap rate).
  - `targets.rate_note(profile, today: date) -> str | None`: the sentence for the athlete when the rate is capped.
  - `constants.NOTE_RATE_CAPPED = "rate capped: target_date needs more than max_weekly_change_pct per week"`, appended to a deficit day's notes when capped.
  - `make_profile_tools(today: Callable[[], date] = date.today)`; `save_nutrition_profile` returns `rate_note` in its JSON when the rate is capped.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-nutrition/tests/test_targets.py`:

```python
# --- target_date ---


def test_weekly_change_pct_needed():
    p = profile(goal="lose", target_weight_kg=75, target_date=MONDAY + timedelta(days=70))
    assert targets.weekly_change_pct_needed(p, MONDAY) == pytest.approx(0.625)  # 6.25 % in 10 wk
    assert targets.weekly_change_pct_needed(profile(), MONDAY) is None
    past = profile(goal="lose", target_weight_kg=75, target_date=MONDAY)
    assert targets.weekly_change_pct_needed(past, MONDAY) is None


def test_deficit_follows_target_date_and_the_cap_wins():
    far = profile(goal="lose", target_weight_kg=75, target_date=MONDAY + timedelta(days=140))
    slow = round(0.3125 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS / 7)  # 275/day
    assert targets.daily_deficit_kcal(far, MONDAY) == slow
    near = profile(goal="lose", target_weight_kg=75, target_date=MONDAY + timedelta(days=70))
    capped = round(0.5 / 100 * 80 * C.KCAL_PER_KG_BODY_MASS / 7)  # 440/day
    assert targets.daily_deficit_kcal(near, MONDAY) == capped
    assert targets.daily_deficit_kcal(near) == capped  # no today: the cap rate, as before
    adj, notes = targets.goal_adjust(near, "easy", "base", MONDAY)
    assert adj == -capped and notes == [C.NOTE_DEFICIT, C.NOTE_RATE_CAPPED]
    assert targets.goal_adjust(far, "easy", "base", MONDAY)[1] == [C.NOTE_DEFICIT]
    note = targets.rate_note(near, MONDAY)
    assert note is not None and "capped at 0.5" in note and "2026-11-23" in note
    assert targets.rate_note(far, MONDAY) is None


def test_build_uses_target_date():
    far = profile(goal="lose", target_weight_kg=75, target_date=MONDAY + timedelta(days=140))
    t = targets.build(far, [], ctx(), MONDAY, 1)[0]
    assert t.goal_adjust_kcal == -targets.daily_deficit_kcal(far, MONDAY)
    assert t.goal_adjust_kcal > -targets.daily_deficit_kcal(far)
```

Append to `packages/tri-nutrition/tests/test_profile_tools.py`, adding `from datetime import date` at the top:

```python
async def test_save_reports_a_capped_rate(mem_store):
    made = {t.name: t for t in make_profile_tools(lambda: date(2026, 9, 14))}
    args = {**PROFILE_ARGS, "goal": "lose", "target_weight_kg": 75, "target_date": "2026-11-23"}
    out = json.loads(await run_tool_in_graph(mem_store, made["save_nutrition_profile"], args))
    assert out["saved"] is True and "capped at 0.5" in out["rate_note"]
    slow = {**args, "target_date": "2027-02-01"}
    out = json.loads(await run_tool_in_graph(mem_store, made["save_nutrition_profile"], slow))
    assert out["saved"] is True and "rate_note" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_targets.py packages/tri-nutrition/tests/test_profile_tools.py -v`
Expected: the three new `test_targets.py` tests fail with `AttributeError: module 'tri_nutrition.nutrition.targets' has no attribute 'weekly_change_pct_needed'` (and `TypeError ... takes 1 positional argument`); `test_save_reports_a_capped_rate` fails with `TypeError: make_profile_tools() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-nutrition/src/tri_nutrition/nutrition/constants.py`, replace:

```python
NOTE_PROFILE_HOURS = "no planned sessions; typed from the goal's weekly hours"
NOTE_NO_SESSIONS = "no planned sessions and no active goal; treated as rest"
```

with:

```python
NOTE_PROFILE_HOURS = "no planned sessions; typed from the goal's weekly hours"
NOTE_NO_SESSIONS = "no planned sessions and no active goal; treated as rest"
NOTE_RATE_CAPPED = "rate capped: target_date needs more than max_weekly_change_pct per week"
```

In `packages/tri-nutrition/src/tri_nutrition/nutrition/targets.py`, replace:

```python
def daily_deficit_kcal(profile: NutritionProfile) -> int:
    weekly_budget = (
        profile.max_weekly_change_pct / 100 * profile.weight_kg * C.KCAL_PER_KG_BODY_MASS
    )
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
```

with:

```python
def weekly_change_pct_needed(profile: NutritionProfile, today: date) -> float | None:
    """Percent of body mass per week that reaches target_weight_kg by target_date; None without
    a target weight or date, or when the date is not after today."""
    if profile.target_weight_kg is None or profile.target_date is None:
        return None
    weeks = (profile.target_date - today).days / 7
    if weeks <= 0:
        return None
    return abs(profile.weight_kg - profile.target_weight_kg) / profile.weight_kg * 100 / weeks


def rate_capped(profile: NutritionProfile, today: date | None) -> bool:
    """True when target_date asks for more than max_weekly_change_pct per week."""
    needed = weekly_change_pct_needed(profile, today) if today is not None else None
    return needed is not None and needed > profile.max_weekly_change_pct


def effective_weekly_change_pct(profile: NutritionProfile, today: date | None) -> float:
    """The rate the deficit is built from: what target_date needs, capped at
    max_weekly_change_pct; the cap alone when there is no date to work from."""
    needed = weekly_change_pct_needed(profile, today) if today is not None else None
    if needed is None:
        return profile.max_weekly_change_pct
    return min(needed, profile.max_weekly_change_pct)


def rate_note(profile: NutritionProfile, today: date) -> str | None:
    """What the athlete is told when target_date asks for more than the cap allows."""
    if profile.goal != "lose" or not rate_capped(profile, today):
        return None
    needed = weekly_change_pct_needed(profile, today) or 0.0
    return (
        f"reaching {profile.target_weight_kg} kg by {profile.target_date} needs {needed:.2f} % "
        f"of body mass per week; the deficit is capped at {profile.max_weekly_change_pct:g} "
        "%/week, so the target date will slip"
    )


def daily_deficit_kcal(profile: NutritionProfile, today: date | None = None) -> int:
    pct = effective_weekly_change_pct(profile, today)
    weekly_budget = pct / 100 * profile.weight_kg * C.KCAL_PER_KG_BODY_MASS
    return min(C.MAX_DEFICIT_KCAL_PER_DAY, round(weekly_budget / 7))


def goal_adjust(
    profile: NutritionProfile,
    day_type: DayType,
    phase: Phase | None,
    today: date | None = None,
) -> tuple[int, list[str]]:
    """Signed kcal adjustment for the day and the notes explaining it. Spec §7.4. With `today`
    the deficit follows target_date; without it the cap rate is used."""
    if profile.goal == "lose":
        if day_type not in C.DEFICIT_DAY_TYPES:
            return 0, [C.NOTE_DEFICIT_PAUSED_DAY]
        if phase in DEFICIT_PAUSE_PHASES:
            return 0, [C.NOTE_DEFICIT_PAUSED_PHASE]
        notes = [C.NOTE_DEFICIT]
        if rate_capped(profile, today):
            notes.append(C.NOTE_RATE_CAPPED)
        return -daily_deficit_kcal(profile, today), notes
    if profile.goal == "gain_lean" and day_type in C.SURPLUS_DAY_TYPES:
        return round((C.SURPLUS_KCAL_MIN + C.SURPLUS_KCAL_MAX) / 2), [C.NOTE_SURPLUS]
    return 0, []
```

and replace:

```python
        adjust, adjust_notes = goal_adjust(profile, dt, phase)
```

with:

```python
        adjust, adjust_notes = goal_adjust(profile, dt, phase, today)
```

In `packages/tri-nutrition/src/tri_nutrition/tools/profile.py`, replace:

```python
import json
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, ValidationError

from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile
```

with:

```python
import json
from collections.abc import Callable
from datetime import date
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, ValidationError

from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.nutrition.targets import rate_note
```

and replace:

```python
def make_profile_tools() -> list[BaseTool]:
    async def save_nutrition_profile(**kwargs: Any) -> str:
        try:
            profile = NutritionProfile(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        if profile.goal == "lose" and DISORDERED_EATING_FLAG in profile.medical_flags:
            return json.dumps({"error": REFERRAL_MESSAGE})
        await S.put_profile(get_store(), profile)
        return json.dumps({"saved": True, "weight_kg": profile.weight_kg, "goal": profile.goal})
```

with:

```python
def make_profile_tools(today: Callable[[], date] = date.today) -> list[BaseTool]:
    async def save_nutrition_profile(**kwargs: Any) -> str:
        try:
            profile = NutritionProfile(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        if profile.goal == "lose" and DISORDERED_EATING_FLAG in profile.medical_flags:
            return json.dumps({"error": REFERRAL_MESSAGE})
        await S.put_profile(get_store(), profile)
        result: dict[str, Any] = {
            "saved": True,
            "weight_kg": profile.weight_kg,
            "goal": profile.goal,
        }
        note = rate_note(profile, today())
        if note is not None:
            result["rate_note"] = note  # the intake agent relays it; the cap wins in the targets
        return json.dumps(result)
```

Also add to the end of `SAVE_DESCRIPTION`, replacing:

```
caffeine_mg} per serving; fuel_notes; unit_preference (metric | imperial). Returns JSON with
saved: true, or an error explaining what to fix. Do not call it more than once per confirmation."""
```

with:

```
caffeine_mg} per serving; fuel_notes; unit_preference (metric | imperial). Returns JSON with
saved: true (plus rate_note when target_date needs a faster loss than max_weekly_change_pct
allows: tell the athlete the cap applies and the date will slip), or an error explaining what
to fix. Do not call it more than once per confirmation."""
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py`, replace:

```python
        *make_profile_tools(),
```

with:

```python
        *make_profile_tools(deps.today),
```

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py`, replace:

```python
        *make_profile_tools(),
```

with:

```python
        *make_profile_tools(deps.today),
```

`bounds.validate_targets` keeps `max_weekly_change_pct` as the seven-day budget; the effective rate never exceeds it, so a capped or slower deficit always passes. `apply_overrides` goes through `NutritionProfile`, so a `target_date` proposed at check-in reaches `build` the same way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests -q`
Expected: all pass. The existing `goal_adjust` and `daily_deficit_kcal` tests set no `target_date`, so they see the cap rate as before.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-nutrition/src/tri_nutrition/nutrition/targets.py packages/tri-nutrition/src/tri_nutrition/nutrition/constants.py packages/tri-nutrition/src/tri_nutrition/tools/profile.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py packages/tri-nutrition/tests/test_targets.py packages/tri-nutrition/tests/test_profile_tools.py
git commit -m "fix(nutrition): the deficit follows target_date, capped at max_weekly_change_pct"
```


---

### Task 18: Final checks

**Files:**
- Modify: nothing new; this task verifies the branch.

**Interfaces:**
- Consumes: every task above.
- Produces: nothing.

- [ ] **Step 1: The suite, with 006 applied**

If Brian has applied 006 to the test database, run `uv run pytest -q -rs` and confirm no test in this plan's files is skipped for a missing column or index: `uv run pytest -q -rs 2>&1 | grep -i "006\|bound\|source_sha\|title_idx\|tp_plan_applied"` prints nothing. If 006 is not applied yet, report the skipped names and continue.

- [ ] **Step 2: Nothing this plan touched still reads the old shapes**

Run: `rg -n "stored as bound|_ref\(raw\.ref_low\)|weekly = float" packages`
Expected: no output.

- [ ] **Step 3: Vault copies**

For every `*.md` file changed on this branch (`git diff --name-only main...HEAD -- '*.md'`), copy it to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, READMEs as `readme.md`.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints.
Expected: all pass; `git status` clean.

- [ ] **Step 5: Report**

List for Brian: the final test count against B, the tests that skip until 006 is applied, and the evals to rerun after merge (`tri-wellness eval` as `report-v2`, `tri-nutrition eval` as `fuel-v4`).
