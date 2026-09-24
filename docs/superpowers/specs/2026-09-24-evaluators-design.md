# Evaluators: judges that see the evidence, an analyst target on real SQL, counts in every report

**Date:** 2026-09-24
**Status:** Draft
**Purpose:** Make the eval suites measure truth rather than shape, so the model-routing gate in `docs/superpowers/specs/2026-09-15-model-routing-design.md` §7.2 rests on numbers that mean something. Fourth of five specs; assumes the correctness fixes are in and is independent of the data layer and guardrails specs. Line numbers are `main` @ 6540055.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Coach judge input | The judge sees the context block, memory, the full history and the sub-agent answers the stub served, and grades a new `grounded` field per brief (chosen 2026-09-24). | Today it sees the athlete's last message and the brief; a hallucinated "Ferritin 18" passes. |
| Analyst grounding | A number is grounded when it appears in the evidence or is derived from it with the arithmetic shown; the field description and the system prompt say the same thing (chosen 2026-09-24). | The field says "appears in", the prompt allows arithmetic, and the structured field wins. The tool docstring tells the analyst to do arithmetic in SQL, which the canned stubs cannot run. |
| Analyst target | Runs against a seeded Postgres with the real SQL tool; live Garmin and TrainingPeaks tools stay canned (chosen 2026-09-24). | "Compute with SQL" is testable only when SQL runs. |
| Output | Every eval prints the scored count per key, `key 75% (3/4)`, from one shared `tri_core.evals` module. | The one-example gate needs counts; four packages carry the same `pass_rates` and three `render_pass_rates` variants. |
| Judge role | Unchanged: `claude-opus-5`, structured, no effort, never tuned. | Comparability across experiments. |

## 2. Feasibility, verified 2026-09-24

- Coach: `render_judge_prompt` (`tri_coach/evals/evaluators.py:66-69`) renders only the last message and the brief; `EvalCase.inputs()` (`evals/cases.py:145-155`) already carries `context`, `memory`, `messages`, `analyst_answer`, `wellness_answer`; `run_case` (`evals/target.py:107-126`) returns `calls`, `route`, `briefs`, `answer` and drops the stub answers. `make_brief_judge` has no `try` around the judge call. LangSmith binds evaluator parameters by name (`langsmith/evaluation/evaluator.py:663-722`), so `brief_quality(inputs, outputs)` needs no wiring change.
- Analyst: `FeedbackJudgement.grounded` (`tri_analyze/evals/evaluators.py:100-105`) says "appears in"; `JUDGE_SYSTEM` (`:126-139`) allows "an arithmetic step you can verify"; `render_judge_prompt` (`:142-157`) already renders the system prompt and served tool results. `stub_tools` (`evals/target.py:76-130`) answers any SQL from `Canned`; `SQL_DESCRIPTION` is the real tool's. `run_readonly_query` opens its own connection from a URL, so seeded rows must be committed. `tri_analyze.testing.seed_workouts` (`testing.py:85-120`) hard-codes most `WorkoutRow` fields to `None`; there is no profile seeder. Cases: 12, fixtures `Z2_RIDE`, `INTERVAL_RUN`, `WEEKLY_TSS`, `SLEEP_HRV` and others in `cases.py`, on dates around `TODAY = date(2026, 9, 16)`.
- `pass_rates` is identical in tri-analyze (`evals/run.py:43-49`), tri-nutrition, tri-wellness and tri-planning; tri-coach imports tri-nutrition's. `render_pass_rates` has width 26 in three packages, 24 in nutrition, and no version line in planning; `tri-planning/tests/test_eval_run.py:19-21` pins the exact line.
- `aevaluate` rows carry `run`, `example` (with `metadata["case"]`) and `evaluation_results`.

## 3. Layout

```
packages/tri-core/src/tri_core/evals.py             NEW: pass_rates, scored_counts, errored, render_pass_rates
packages/tri-core/tests/test_evals.py               NEW
packages/tri-{analyze,coach,nutrition,wellness,planning}/src/*/evals/run.py   import from tri_core.evals
packages/tri-analyze/src/tri_analyze/evals/{evaluators.py,target.py,cases.py,seed.py (NEW),run.py}
packages/tri-analyze/src/tri_analyze/testing.py     seed_workouts takes every WorkoutRow field; seed_profile
packages/tri-coach/src/tri_coach/evals/{evaluators.py,target.py}
packages/tri-analyze/README.md, packages/tri-coach/README.md
```

## 4. Interfaces

### 4.1 `tri_core.evals`

```python
def pass_rates(rows) -> dict[str, float]                 # unchanged semantics
def scored_counts(rows) -> dict[str, tuple[int, int]]    # key -> (passed, scored)
def errored(rows) -> int
def render_pass_rates(rates, counts, n, *, version: str | None) -> str
```

Output:

```
pass rate over 12 examples (prompt version 1):
  feedback_quality           100% (6/6)
  grounded                    33% (4/12)
```

Width 26 everywhere; the version line is omitted when `version` is `None`. Each `run_eval` logs this and, when `errored > 0`, `n errored`. The five package copies are deleted; `tri-coach` stops importing from `tri-nutrition`. Tests that pin the old strings are updated to the new format.

### 4.2 Coach judge

```python
class BriefJudgement(BaseModel):
    bounded: bool
    names_signal: bool
    names_lever: bool
    names_constraint: bool
    grounded: bool = Field(description="every number, date and lab value in the brief appears in the context block, the memory, the conversation or a sub-agent answer")
    problems: list[str]
```

`render_judge_prompt(inputs, outputs, brief)` renders: the context block, the memory block, the conversation (all turns), the sub-agent answers the target served (`outputs["served"]`, a list of `{"name", "answer"}` that `run_case` now returns), and the brief. `JUDGE_SYSTEM` adds the grounding rule. `brief_quality` scores each brief and returns `score = int(all ok)` with a comment naming the failing brief by index and its problems; the judge call is wrapped so a failure scores 0 with `judge failed: ...` like the analyst's.

### 4.3 Analyst grounding

`FeedbackJudgement.grounded` description becomes: "every number in the answer appears in the context or the tool results, or is derived from them by a unit conversion or arithmetic the answer shows (for example 800 m in 200 s gives 4:10/km); missing data is stated as missing". `JUDGE_SYSTEM` says the same and asks the judge to list each ungrounded number in `problems` with what it expected. `FEEDBACK_RULES` in `prompts/analyst.py` gains one sentence: "When you derive a number, show the arithmetic in a few words." `PROMPT_VERSION = "2"`.

### 4.4 Seeded Postgres target

`EvalCase` gains `seed: Seed` where `Seed` holds `workouts: list[dict]`, `daily_metrics: list[dict]`, `profile: dict | None`; the SQL entries in `tool_results` go, the live-tool entries stay. `tri_analyze.evals.seed`:

```python
EVAL_ATHLETE_ID = "eval"   # not used by the schema; cases share one athlete
def seed_database(url: str, cases: list[EvalCase]) -> None
```

`seed_database` truncates `workouts`, `garmin_activities`, `daily_metrics` and `athlete_profile` in the database at `url`, inserts the union of every case's seed rows through `seed_workouts` (extended to accept every `WorkoutRow` field, including `garmin_activity_id`, `avg_power`, `avg_hr`, `feeling`, `rpe`, `comments`, `description`) and `seed_daily_metrics`, and commits. Cases keep distinct dates so the union is consistent; a test asserts no two cases seed the same primary key with different rows.

`run_eval(settings, models, *, judge, prefix, recreate, log, eval_db_url=None)` seeds `eval_db_url or settings.test_database_url` once before `aevaluate`, and `make_target(model, sql_url)` binds `make_query_tool(sql_url)` in place of the SQL stub. `tri-analyze eval` gains `--eval-db URL` and refuses to run against `settings.database_url` (the athlete's data) with exit 2. The eval's `TODAY` stays a fixed date; the analyst's "Today" comes from `inputs["athlete"]["today"]` as now, so `current_date` in SQL examples is a known mismatch: `SCHEMA_DOC`'s examples use `:today` wording and the analyst prompt says to use the given date (this also fixes the review's timezone finding).

The judge's evidence is `outputs["tool_results"]` exactly as today, now containing what SQL returned.

## 5. Behaviour

- `tri-analyze eval` needs Postgres and both keys; without a reachable eval database it exits 2 naming the URL.
- Grounded now fails only for numbers the answer neither cites nor derives visibly. The 8% baseline is expected to move; the new baseline is `analyst-v2-base` and is what future routing experiments compare against.
- `tri-coach eval` gains a `grounded` signal inside `brief_quality`; a brief that invents a lab value fails with the value named.
- Every eval prints counts, so the "one example" gate is applied without LangSmith.

## 6. Errors

- A judge exception scores 0 with the error in the comment in both packages.
- `seed_database` on a database that holds a non-eval row set (a real `athlete_profile.name`) refuses unless the URL is the test database or `--eval-db` was given explicitly.

## 7. Testing

- `tri-core/tests/test_evals.py`: `scored_counts`, `render_pass_rates` with and without a version, `errored`.
- `tri-analyze/tests/test_evals.py`: the judge prompt renders served SQL results; the grounded field description mentions derivation; `seed_database` round-trips a case's rows through the real `run_readonly_query` (db-marked); `make_target` with a fake model runs SQL against the seeded test database; case seeds have no conflicting keys.
- `tri-coach/tests/test_evals.py`: `render_judge_prompt` includes context, memory, history and served answers; a scripted judge verdict with `grounded=False` fails with the brief index in the comment; `run_case` returns `served`.
- Every package's `test_evals.py`: the new render format.
- Athlete-run after merge: `analyst-v2-base`, `coach-v3-base` (judge change only), recorded in `docs/notes/`.

## 8. Out of scope

- Labelled (answer, expected) pairs to calibrate the judges; worth a follow-up once the seeded target exists.
- Recording `response_metadata.model` per call.
- Evals for the four ungated roles.
- Switching the judge to `method="json_schema"` to allow thinking.

## 9. Rollout

One plan: `tri_core.evals` and the five `run.py` files first (pure refactor, counts appear), then the coach judge, then the analyst judge and prompt, then the seeded target and `--eval-db`. Brian runs the two baselines after merge.
