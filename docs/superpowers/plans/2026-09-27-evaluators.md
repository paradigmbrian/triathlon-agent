# Evaluators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The eval suites measure truth rather than shape: the coach judge sees the evidence a brief could cite, the analyst judge accepts derivations it can check, the analyst's SQL runs against a seeded Postgres, and every eval prints scored counts from one shared module.

**Architecture:** `tri_core.evals` owns `pass_rates`, `scored_counts`, `errored` and `render_pass_rates`; the five `run.py` files import them. The coach eval target records every stub answer it served, and the judge renders context, memory, conversation, those answers and the brief. The analyst's judge and prompt allow derivation with shown arithmetic, and `SCHEMA_DOC` tells every agent to write today's date as a literal. `tri_analyze/evals/seed.py` builds one synthetic athlete history (2026-06-01 to 2026-09-19) around the cases' sessions; `run_eval` seeds it into the test database, binds the real SQL tool as `tri_reader`, and empties the tables afterwards.

**Tech Stack:** Python 3.12, LangSmith `aevaluate`, langchain-core 1.6, Pydantic v2, psycopg 3, Postgres 16, pytest, Typer.

**Spec:** `docs/superpowers/specs/2026-09-24-evaluators-design.md` (all sections). Line numbers there are `main` @ 6540055; this plan uses `main` @ 8545f8e.

**Branch:** `feat/evaluators` off `main` @ 8545f8e (created with this plan).

## Global Constraints

- Pass-rate output, exactly: a header `pass rate over <n> examples (prompt version <v>):` (the parenthesis omitted when `version` is `None`), then one line per key sorted by key: two spaces, the key left-aligned to width 26, a space, the rate as `{rate:>4.0%}`, a space, `(<passed>/<scored>)`. Example: `  grounded                    33% (4/12)`.
- Every `run_eval` logs `experiment: <name>`, the pass-rate block, and `<n> errored` when any example errored.
- Judge role unchanged: `Role.JUDGE`, structured output, never tuned.
- A judge call that raises scores 0 with `judge failed: <Type>: <message>` as the comment, in both the coach and analyst judges.
- Coach `BriefJudgement.grounded` description, exactly: `every number, date and lab value in the brief appears in the context block, the memory, the conversation or a sub-agent answer`.
- Analyst `FeedbackJudgement.grounded` description, exactly: `every number in the answer appears in the context or the tool results, or is derived from them by a unit conversion or arithmetic the answer shows (for example 800 m in 200 s gives 4:10/km); missing data is stated as missing`.
- Analyst `PROMPT_VERSION = "2"`; the coach's stays `"4"` (its prompt does not change; only its judge and eval context do).
- Every seeded workout's `tp_workout_id` starts with `eval-`; the seeded profile's `tp_athlete_id` is `eval`. `seed_database` refuses (raises `EvalDatabaseInUse`) when the database holds any other workout or profile row.
- The analyst eval runs against `settings.test_database_url` unless `--eval-db` names another; it never runs against `settings.database_url` (exit 2), and it empties the seeded tables when it finishes, pass or fail.
- **Brian's database rule:** no migration and no DDL. The eval's own seeding of the test database (insert, truncate) is the feature under test and runs only in the test suite and in `tri-analyze eval`, which Brian runs. The implementer never points anything at `tri_analyze` (the athlete's database).
- **Brian's dependency rule:** before the first edit touching LangSmith or langchain APIs (`aevaluate` rows, `EvaluationResult`, `StructuredTool`), check the installed versions (`uv pip show langsmith langchain-core`) in Context7. Nothing here needs an API the repo does not already use.
- Run `uv run ruff format` on the touched packages before each commit.

## Deviations from the spec (decided while planning, 2026-09-27)

1. **One shared history instead of a `seed` per case.** The cases share their week (`WEEK_DAYS`, `WEEK_WORKOUTS`) and the trends overlap it, so a union of per-case seeds would conflict by construction. `tri_analyze/evals/seed.py` builds a single history: a run block in June (no bike, so `trend_no_data` still finds nothing), a triathlon build from 2026-07-06 with a recovery week from 2026-08-10, and the cases' own sessions for the week of 2026-09-07. `tss_day` is the sum of each day's completed `actual_tss`, and CTL/ATL follow the 42/7-day curve, except the seven `WEEK_DAYS` rows, which stay exactly as the context block shows them.
2. **The test database, filled and emptied per run.** The spec seeds `test_database_url` and leaves the rows. Those rows would break tests that expect empty tables, so `run_eval` empties the four tables in a `finally`. The spec's "refuse a real `athlete_profile.name`" has no column to read; the guard refuses any workout whose id does not start with `eval-` and any profile whose `tp_athlete_id` is not `eval`. That also covers the athlete's database, which `--eval-db` additionally refuses by URL.
3. **`stub_tools(inputs, sql_tool=None)` keeps the canned SQL stub** for tests that run without Postgres; `make_target(model, sql_url=None)` binds the real tool when given a URL. `EvalCase.tool_results` loses every `query_training_db` entry.
4. **`SCHEMA_DOC` writes today as a literal.** Its examples use `:today`, and a new sentence says to write today's date from the context as `date 'YYYY-MM-DD'` because `current_date` is the database server's day. This is the review's timezone finding; it changes the SQL tool description for the coach's and planning's agents too.
5. **The coach eval context shows `Consults left this turn: planning 2, nutrition 2.`** Guardrails 02 made `COACH_RULES` say the context shows it; the eval's context did not (a deferred minor from that branch).
6. **Package pass-rate tests move to tri-core.** The four packages' `pass_rates`/`render_pass_rates` tests exercise functions this plan deletes; `tri-core/tests/test_evals.py` covers them once. Each package's existing `run_eval` test gains an assertion that its log names its prompt version.
7. **Coach baseline naming.** The coach prompt is v4 since Guardrails 02, so the spec's `coach-v3-base` becomes `coach-v4-base`. To separate the prompt change from the judge change, Brian can run `tri-coach eval` on `main` before this branch merges.

### Existing tests this plan changes, and why

- `tri-analyze/tests/test_evals.py`: `test_pass_rates_skip_none_and_rendering_names_the_prompt_version` and `test_errored_counts_rows_whose_run_carries_an_error` move to tri-core (the functions move). `test_stubs_answer_from_the_case`, `test_target_returns_the_calls_and_the_final_answer` and `test_judge_prompt_carries_the_rendered_system_prompt_question_results_and_answer` read a case's canned SQL, which the cases no longer carry: each builds its own `EvalCase` with the same canned result instead, and keeps every assertion. `_stub_langsmith` also stubs the seeding. `test_run_eval_*` gain a log assertion.
- `tri-analyze/tests/test_prompt.py`: `PROMPT_VERSION == "2"`.
- `tri-coach/tests/test_evals.py`: the scripted judge verdict gains `"grounded": True`; `test_render_pass_rates_names_the_prompt_version` becomes a `run_eval` log assertion.
- `tri-nutrition`, `tri-wellness`: their `pass_rates` tests move to tri-core; `test_run_eval_*` gain a log assertion.
- `tri-planning/tests/test_eval_run.py`: `test_render_pass_rates_lists_each_key` becomes a `run_eval` log assertion.

## Review Focus

- **`tri-analyze eval --eval-db` pointed at the athlete's database, or at any database holding real rows:** exit 2 before anything is written. Tests: `test_eval_refuses_the_athletes_database` (Task 5), `test_seeding_refuses_a_database_with_rows_it_did_not_write` (Task 4).
- **An eval run that was killed and left its rows:** the next run replaces them (they are all `eval-`), and `clear_database` empties them. Test: `test_seeding_twice_replaces_the_first_run` (Task 4).
- **The SQL tool connects as `tri_reader` to the test database** (migration 010 granted it) and reads the seeded rows. Test: `test_the_seeded_rows_are_readable_through_the_real_sql_tool` (Task 4).
- **A brief whose number appears only in a sub-agent's answer** (the analyst said "TSB -18"): the judge sees that answer. Test: `test_the_judge_sees_context_memory_conversation_and_served_answers` (Task 2).
- **A question the history cannot answer** (bike TSS in June): the seeded history has no June bike rows. Test: `test_the_history_is_one_consistent_athlete` (Task 4).

---

### Task 1: `tri_core.evals`, one pass-rate format

**Files:**
- Create: `packages/tri-core/src/tri_core/evals.py`
- Create: `packages/tri-core/tests/test_evals.py`
- Modify: `packages/tri-{analyze,coach,nutrition,wellness,planning}/src/*/evals/run.py`
- Modify (tests): `packages/tri-analyze/tests/test_evals.py`, `packages/tri-coach/tests/test_evals.py`, `packages/tri-nutrition/tests/test_evals.py`, `packages/tri-wellness/tests/test_evals.py`, `packages/tri-planning/tests/test_eval_run.py`

**Interfaces:**
- Produces: `tri_core.evals.pass_rates(rows) -> dict[str, float]`, `scored_counts(rows) -> dict[str, tuple[int, int]]`, `errored(rows) -> int`, `render_pass_rates(rates, counts, n, *, version: str | None) -> str`, `KEY_WIDTH = 26`. `rows` are `dict(row)` of `aevaluate` rows: `row["evaluation_results"]["results"]` items with `.key` and `.score`, and `row["run"]` with `.error`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-core/tests/test_evals.py`:

```python
from types import SimpleNamespace

from tri_core.evals import errored, pass_rates, render_pass_rates, scored_counts


def R(key, score):
    return SimpleNamespace(key=key, score=score)


ROWS = [
    {"evaluation_results": {"results": [R("uses_sql", 1), R("pulls_splits", None), R("grounded", 0)]}},
    {"evaluation_results": {"results": [R("uses_sql", 0), R("pulls_splits", 1), R("grounded", 1)]}},
    {"evaluation_results": {"results": [R("uses_sql", 1), R("grounded", 1)]}},
]


def test_pass_rates_and_counts_leave_out_unscored_keys():
    assert pass_rates(ROWS) == {"uses_sql": 2 / 3, "pulls_splits": 1.0, "grounded": 2 / 3}
    assert scored_counts(ROWS) == {"uses_sql": (2, 3), "pulls_splits": (1, 1), "grounded": (2, 3)}
    assert pass_rates([]) == {} and scored_counts([]) == {}


def test_a_row_without_results_counts_for_nothing():
    rows = [{"evaluation_results": {"results": []}}, {"run": SimpleNamespace(error="boom")}]
    assert pass_rates(rows) == {} and scored_counts(rows) == {}


def test_render_names_the_version_and_shows_counts():
    text = render_pass_rates(pass_rates(ROWS), scored_counts(ROWS), 3, version="2")
    assert text.splitlines() == [
        "pass rate over 3 examples (prompt version 2):",
        "  grounded                    67% (2/3)",
        "  pulls_splits               100% (1/1)",
        "  uses_sql                    67% (2/3)",
    ]


def test_render_without_a_version_has_no_parenthesis():
    text = render_pass_rates({"a": 1.0}, {"a": (4, 4)}, 4, version=None)
    assert text.splitlines()[0] == "pass rate over 4 examples:"


def test_errored_counts_rows_whose_run_carries_an_error():
    rows = [
        {"run": SimpleNamespace(error=None)},
        {"run": SimpleNamespace(error="IndexError: list index out of range")},
        {"run": SimpleNamespace(error="")},
        {},
    ]
    assert errored(rows) == 1 and errored([]) == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_evals.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.evals'`.

- [ ] **Step 3: Write `tri_core/evals.py`**

```python
"""Pass rates for every package's LangSmith eval, in one format: the rate and the scored count
per evaluator key, so "every example passed" can be read from the log without LangSmith."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

KEY_WIDTH = 26


def _scores(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in (row.get("evaluation_results") or {}).get("results") or []:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return scores


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    """The mean score per key; a None score (the check did not apply) is left out."""
    return {key: sum(v) / len(v) for key, v in _scores(rows).items()}


def scored_counts(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """(passed, scored) per key; a score of 1 passes."""
    return {key: (sum(1 for s in v if s >= 1.0), len(v)) for key, v in _scores(rows).items()}


def errored(rows: list[dict[str, Any]]) -> int:
    """Examples whose target raised: LangSmith keeps the run with its error text."""
    return sum(1 for row in rows if getattr(row.get("run"), "error", None))


def render_pass_rates(
    rates: dict[str, float],
    counts: dict[str, tuple[int, int]],
    n: int,
    *,
    version: str | None,
) -> str:
    head = f"pass rate over {n} examples"
    if version is not None:
        head += f" (prompt version {version})"
    lines = [head + ":"]
    for key, rate in sorted(rates.items()):
        passed, scored = counts.get(key, (0, 0))
        lines.append(f"  {key:{KEY_WIDTH}} {rate:>4.0%} ({passed}/{scored})")
    return "\n".join(lines)
```

- [ ] **Step 4: Point the five `run.py` files at it**

In each of `tri_analyze`, `tri_coach`, `tri_nutrition`, `tri_wellness`, `tri_planning` `evals/run.py`: delete the local `pass_rates`, `render_pass_rates` and (analyze) `errored`, and the `defaultdict` import if now unused; add `from tri_core.evals import errored, pass_rates, render_pass_rates, scored_counts` (tri-coach drops `from tri_nutrition.evals.run import pass_rates`). Replace the tail of each `run_eval` after `rows = ...` with:

```python
    dict_rows = [dict(r) for r in rows]
    rates = pass_rates(dict_rows)
    errors = errored(dict_rows)
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, scored_counts(dict_rows), len(rows), version=PROMPT_VERSION))
    if errors:
        log(f"{errors} errored")
```

followed by each function's existing return (`return rates, errors` in tri-analyze, `return rates` elsewhere).

- [ ] **Step 5: Package tests**

- `tri-analyze/tests/test_evals.py`: delete `test_pass_rates_skip_none_and_rendering_names_the_prompt_version` and `test_errored_counts_rows_whose_run_carries_an_error` and their imports (`errored`, `pass_rates`, `render_pass_rates`); in `test_run_eval_uses_the_analyst_and_judge_roles` replace `log=lambda m: None` with `log=logged.append` (declare `logged: list[str] = []`) and add `assert f"(prompt version {PROMPT_VERSION}):" in "\n".join(logged)`.
- `tri-coach/tests/test_evals.py`: delete `test_render_pass_rates_names_the_prompt_version` and the `render_pass_rates` import; add the same log assertion to `test_run_eval_uses_the_coach_and_judge_roles`.
- `tri-nutrition/tests/test_evals.py`, `tri-wellness/tests/test_evals.py`: delete the `pass_rates` test and imports; add the log assertion to their `run_eval` test (import `PROMPT_VERSION` from `tri_nutrition.prompts.fuel` / `tri_wellness.prompts.report`).
- `tri-planning/tests/test_eval_run.py`: delete `test_render_pass_rates_lists_each_key` and its import; add the log assertion to `test_run_eval_designs_on_the_design_role` (import `PROMPT_VERSION` from `tri_planning.prompts.design`).

- [ ] **Step 6: Run everything the change touches**

Run: `uv run pytest packages/tri-core packages/tri-analyze packages/tri-coach packages/tri-nutrition packages/tri-wellness packages/tri-planning -q -k "eval"` then `git grep -n "def pass_rates\|def render_pass_rates\|def errored" -- packages`.
Expected: all pass; the grep lists only `packages/tri-core/src/tri_core/evals.py`.

- [ ] **Step 7: Commit**

```bash
uv run ruff format packages
git add packages
git commit -m "refactor(evals): one pass-rate module in tri_core with scored counts per key"
```

---

### Task 2: The coach judge sees the evidence

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/evals/evaluators.py` (`BriefJudgement`, `JUDGE_SYSTEM`, `render_judge_prompt`, `make_brief_judge`)
- Modify: `packages/tri-coach/src/tri_coach/evals/target.py` (`stub_tools`, `run_case`)
- Modify: `packages/tri-coach/src/tri_coach/evals/cases.py` (`case_context` sets `consults_left`)
- Test: `packages/tri-coach/tests/test_evals.py`

**Interfaces:**
- Consumes: `tri_coach.context.CoachContext.consults_left` (Guardrails 02).
- Produces: `run_case` output gains `served: list[{"name": str, "answer": str}]`; `stub_tools(inputs, served: list[dict[str, str]] | None = None)`; `render_judge_prompt(inputs, outputs, brief) -> str`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-coach/tests/test_evals.py`, add `"grounded": True` to the `verdict` dict in `test_brief_judge_scores_every_brief_and_skips_a_turn_without_one`, add `render_judge_prompt` to the evaluators import, and append:

```python
async def test_the_target_returns_every_answer_it_served():
    c = case("knee_pain_planning")
    model = ScriptedChatModel(
        script=[
            tool_call("ask_analyst", {"question": "Runs since Sunday?"}, "a1"),
            tool_call("consult_planning", {"instruction": "Knee. No running 7 days."}, "c1"),
            AIMessage(content="Planning will move the runs."),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert [s["name"] for s in out["served"]] == ["ask_analyst", "consult_planning"]
    assert out["served"][0]["answer"] == c.inputs()["analyst_answer"]
    assert out["served"][1]["answer"].startswith("p1 (planning)")


def test_the_judge_sees_context_memory_conversation_and_served_answers():
    c = case("knee_pain_planning")
    served = [{"name": "ask_analyst", "answer": "TSB -18 entering the week."}]
    text = render_judge_prompt(c.inputs(), {"served": served}, "TSB -18. Drop Thursday's run.")
    inputs = c.inputs()
    assert inputs["context"] in text and inputs["memory"] in text
    assert all(m["content"] in text for m in inputs["messages"])
    assert "ask_analyst: TSB -18 entering the week." in text
    assert text.rstrip().endswith("TSB -18. Drop Thursday's run.")
    bare = render_judge_prompt(c.inputs(), {}, "b")
    assert "Tool answers this turn:\n(none)" in bare


async def test_an_ungrounded_brief_fails_naming_its_index():
    good = {
        "bounded": True,
        "names_signal": True,
        "names_lever": True,
        "names_constraint": True,
        "grounded": True,
        "problems": [],
    }
    bad = {**good, "grounded": False, "problems": ["Ferritin 18 appears nowhere"]}
    judge = make_brief_judge(
        ScriptedChatModel(
            script=[tool_call("BriefJudgement", good), tool_call("BriefJudgement", bad)]
        )
    )
    res = await judge(case("knee_pain_planning").inputs(), {"briefs": ["one", "two"]})
    assert res["score"] == 0 and res["comment"] == "brief 2: Ferritin 18 appears nowhere"


async def test_a_raising_brief_judge_scores_zero_with_the_error():
    judge = make_brief_judge(ScriptedChatModel(script=[]))  # IndexError on the first call
    res = await judge(case("knee_pain_planning").inputs(), {"briefs": ["one"]})
    assert res["score"] == 0 and res["comment"].startswith("judge failed: IndexError")


def test_the_eval_context_names_the_consults_left():
    assert "Consults left this turn: planning 2, nutrition 2." in case("knee_pain_planning").context
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_evals.py -v`
Expected: the new tests FAIL (`KeyError: 'served'`, `TypeError` on `render_judge_prompt`'s arguments, no index in the comment, an uncaught `IndexError`, no consults line).

- [ ] **Step 3: The target records what it served**

In `evals/target.py`, give `stub_tools` a `served: list[dict[str, str]] | None = None` parameter and record every stub answer that could reach a brief:

```python
def stub_tools(inputs: dict[str, Any], served: list[dict[str, str]] | None = None) -> list[BaseTool]:
    n = 0
    log = served if served is not None else []

    def record(name: str, answer: str) -> str:
        log.append({"name": name, "answer": answer})
        return answer

    async def ask_analyst(question: str) -> str:
        """..."""  # docstring unchanged
        return record("ask_analyst", str(inputs.get("analyst_answer") or "No data found for that question."))

    async def ask_wellness(question: str) -> str:
        """..."""  # docstring unchanged
        return record("ask_wellness", str(inputs.get("wellness_answer") or "No panel stored."))

    ...

    async def consult_planning(instruction: str) -> str:
        return record("consult_planning", proposal("planning"))

    async def consult_nutrition(instruction: str) -> str:
        return record("consult_nutrition", proposal("nutrition"))
```

(keep both docstrings and every other tool exactly as they are). In `run_case`, create `served: list[dict[str, str]] = []`, pass it to `stub_tools(inputs, served)`, and add `"served": served` to the returned dict.

- [ ] **Step 4: The judge reads the evidence**

In `evals/evaluators.py`:

```python
class BriefJudgement(BaseModel):
    bounded: bool = Field(
        description="asks for one specific change, not a review, a re-plan or an open question"
    )
    names_signal: bool = Field(description="states what was observed or reported that warrants it")
    names_lever: bool = Field(description="states what to change")
    names_constraint: bool = Field(description="states what must hold while changing it")
    grounded: bool = Field(
        description=(
            "every number, date and lab value in the brief appears in the context block, the "
            "memory, the conversation or a sub-agent answer"
        )
    )
    problems: list[str] = Field(
        description="one line per missing element, overreach, or number that appears nowhere"
    )


JUDGE_SYSTEM = """\
You audit one brief a head coach wrote to a planning or nutrition sub-agent. A good brief is
bounded (one specific change the sub-agent can carry out without deciding anything else) and
names three things: the signal (what was observed or reported, with numbers or dates when the
conversation has them), the lever (what to change) and the constraint (what must hold, such as
a weekly TSS band, a session to keep, or the nutrition goal).

You are given what the coach knew: its context block, its memory, the whole conversation and
the answers its tools returned this turn (the analyst, the lab interpreter, earlier
consultations). Grounded: every number, date and lab value in the brief appears in one of
those. A figure that appears nowhere is invented, however plausible: name it in problems.
Judge the brief's text literally; return a BriefJudgement."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any], brief: str) -> str:
    conversation = "\n".join(
        f"{m['role']}: {m['content']}" for m in inputs.get("messages") or []
    )
    served = "\n".join(f"{s['name']}: {s['answer']}" for s in outputs.get("served") or [])
    return (
        f"Context block:\n{inputs.get('context', '')}\n\n"
        f"Memory:\n{inputs.get('memory', '')}\n\n"
        f"Conversation:\n{conversation or '(none)'}\n\n"
        f"Tool answers this turn:\n{served or '(none)'}\n\n"
        f"Brief:\n{brief}"
    )


def make_brief_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = structured(model, BriefJudgement)

    async def brief_quality(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        briefs = [b for b in outputs.get("briefs") or [] if b]
        if not briefs:
            return {"key": "brief_quality", "score": None, "comment": "no brief"}
        failed: list[str] = []
        for i, brief in enumerate(briefs, 1):
            try:
                out = await judge.ainvoke(
                    [
                        SystemMessage(JUDGE_SYSTEM),
                        HumanMessage(render_judge_prompt(inputs, outputs, brief)),
                    ]
                )
                assert isinstance(out, BriefJudgement)
            except Exception as exc:  # noqa: BLE001 - scored, not raised, like the analyst judge
                comment = f"judge failed: {type(exc).__name__}: {exc}"
                return {"key": "brief_quality", "score": 0, "comment": comment}
            ok = (
                out.bounded
                and out.names_signal
                and out.names_lever
                and out.names_constraint
                and out.grounded
            )
            if not ok:
                failed.append(f"brief {i}: " + ("; ".join(out.problems) or "no problem named"))
        return {
            "key": "brief_quality",
            "score": int(not failed),
            "comment": " | ".join(failed) or "ok",
        }

    return brief_quality
```

Update the module docstring's last sentence: `The judge sees the context, memory, conversation and every tool answer the target served, so an invented number fails.`

- [ ] **Step 5: The eval context shows the budget**

In `evals/cases.py`, `case_context`'s `CoachContext(...)` gains `consults_left={"planning": MAX_CONSULTS, "nutrition": MAX_CONSULTS},` with `from tri_coach.evals.target import MAX_CONSULTS` if `cases.py` does not import `target` (it must not create an import cycle: `target.py` imports `Route` from `cases.py`; if it would, define `EVAL_MAX_CONSULTS = 2` in `cases.py` and have `target.py`'s `MAX_CONSULTS = EVAL_MAX_CONSULTS`).

- [ ] **Step 6: Run the coach suite**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
uv run ruff format packages/tri-coach
git add packages/tri-coach
git commit -m "feat(coach-eval): the brief judge grades grounding against everything the coach saw"
```

---

### Task 3: The analyst's judge accepts shown arithmetic; SQL uses today's date

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (`FeedbackJudgement.grounded`, `JUDGE_SYSTEM`)
- Modify: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py` (`FEEDBACK_RULES`, `PROMPT_VERSION`)
- Modify: `packages/tri-core/src/tri_core/db/sql_tool.py` (`SCHEMA_DOC`)
- Test: `packages/tri-analyze/tests/test_evals.py`, `packages/tri-analyze/tests/test_prompt.py`, `packages/tri-core/tests/test_sql_tool.py`

**Interfaces:**
- Produces: `tri_analyze.prompts.analyst.PROMPT_VERSION = "2"`; `SCHEMA_DOC` examples written with `:today`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-analyze/tests/test_evals.py`, append:

```python
def test_grounded_accepts_arithmetic_the_answer_shows():
    field = FeedbackJudgement.model_fields["grounded"].description or ""
    assert "derived from them by a unit conversion or arithmetic the answer shows" in field
    assert "800 m in 200 s gives 4:10/km" in field
    from tri_analyze.evals.evaluators import JUDGE_SYSTEM

    assert "list each in problems" in JUDGE_SYSTEM and "arithmetic" in JUDGE_SYSTEM
```

`packages/tri-analyze/tests/test_prompt.py`: change `PROMPT_VERSION == "1"` to `PROMPT_VERSION == "2"` and append:

```python
def test_the_rules_ask_for_shown_arithmetic_and_a_literal_today():
    assert "show the arithmetic" in FEEDBACK_RULES
    assert "never use current_date" in FEEDBACK_RULES
```

(import `FEEDBACK_RULES` if the file does not already.)

`packages/tri-core/tests/test_sql_tool.py`, append:

```python
def test_the_schema_examples_write_today_as_a_literal():
    examples = SCHEMA_DOC.split("Examples:")[1]
    assert "current_date" not in examples and ":today" in examples
    assert "date 'YYYY-MM-DD'" in SCHEMA_DOC and "database server's day" in SCHEMA_DOC
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py packages/tri-analyze/tests/test_prompt.py packages/tri-core/tests/test_sql_tool.py -v -k "arithmetic or literal or version"`
Expected: FAIL.

- [ ] **Step 3: The judge**

`FeedbackJudgement.grounded` becomes:

```python
    grounded: bool = Field(
        description=(
            "every number in the answer appears in the context or the tool results, or is "
            "derived from them by a unit conversion or arithmetic the answer shows (for example "
            "800 m in 200 s gives 4:10/km); missing data is stated as missing"
        )
    )
```

In `JUDGE_SYSTEM`, replace the `Grounded:` paragraph with:

```
Grounded: every number in the answer (durations, distances, watts, paces, heart rates, TSS,
scores, dates) appears in the system prompt's context or in the tool results, or is derived
from them by a unit conversion or arithmetic the answer shows (for example "800 m in 200 s,
4:10/km"). A derived number whose arithmetic is not shown, or a number that appears nowhere, is
ungrounded: list each in problems with what you expected to find. When the tool results are
empty or lack what the question needs, the answer says so instead of inventing figures.
```

- [ ] **Step 4: The analyst's rules**

In `prompts/analyst.py`: `PROMPT_VERSION = "2"`, and the trend paragraph of `FEEDBACK_RULES` becomes:

```
For trend questions: compute with SQL (group by week, averages, sums), state the date window
you used, and say when data is missing rather than guessing. Distances are metres, durations
seconds, paces derive from those. Today is the reference for "this week" and "yesterday"; in
SQL write it as a literal (date 'YYYY-MM-DD'), never use current_date. When you derive a
number, show the arithmetic in a few words.
```

- [ ] **Step 5: `SCHEMA_DOC`**

In `tri_core/db/sql_tool.py`, after the first line of `SCHEMA_DOC` (`Tables (Postgres). All dates are the athlete's local calendar day.`) add:

```
In the examples, :today stands for today's date from your context, written as a literal
(date 'YYYY-MM-DD'); current_date is the database server's day and can differ from the athlete's.
```

and in the Examples block replace every `current_date` with `:today` (six places). Then run `git grep -n "current_date" -- 'packages/*/src'` and report any other prompt text that tells a model to use `current_date`; change none outside `SCHEMA_DOC` without saying so in the report.

- [ ] **Step 6: Run the affected suites**

Run: `uv run pytest packages/tri-core packages/tri-analyze packages/tri-coach packages/tri-planning -q`
Expected: all pass (the analyst stub's SQL description is built from `SCHEMA_DOC`, so it follows).

- [ ] **Step 7: Commit**

```bash
uv run ruff format packages/tri-core packages/tri-analyze
git add packages/tri-core packages/tri-analyze
git commit -m "feat(analyst): grounded accepts shown arithmetic; SQL writes today as a literal; prompt v2"
```

---

### Task 4: One seeded athlete history

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/evals/seed.py`
- Modify: `packages/tri-analyze/src/tri_analyze/testing.py` (`seed_workouts` takes every `WorkoutRow` field)
- Test: `packages/tri-analyze/tests/test_seed.py` (new)

**Interfaces:**
- Consumes: `tri_analyze.evals.cases` fixtures (`Z2_RIDE`, `INTERVAL_RUN`, `MISSED_SWIM`, `THRESHOLD_RIDE`, `BRICK`, `BRICK_SPLITS`, `WEEK_DAYS`, `SLEEP_HRV`, `PROFILE`, `TODAY`).
- Produces: `seed.EVAL_ID = "eval"`, `seed.SEEDED_TABLES`, `seed.workouts() -> list[dict]`, `seed.daily_metrics(workouts) -> list[dict]`, `seed.workout_row(r: dict) -> WorkoutRow`, `seed.seed_database(url: str) -> None`, `seed.clear_database(url: str) -> None`, `class seed.EvalDatabaseInUse(RuntimeError)`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-analyze/tests/test_seed.py`:

```python
"""The eval's seeded history: pure checks, then a round trip through the test database."""

import json
from collections import defaultdict
from datetime import date

import psycopg
import pytest

from tri_analyze.evals import seed
from tri_analyze.evals.cases import TODAY, WEEK_DAYS
from tri_core.config import Settings, reader_url
from tri_core.db.connection import connect
from tri_core.db.sql_tool import run_readonly_query


def test_the_history_is_one_consistent_athlete():
    ws = seed.workouts()
    ids = [w["tp_workout_id"] for w in ws]
    assert len(ids) == len(set(ids)) and all(i.startswith("eval-") for i in ids)
    # June is a run block: no bike, so "average weekly bike TSS in June" has no data
    assert not [w for w in ws if w["sport"] == "bike" and w["workout_date"] < date(2026, 7, 1)]
    by_title = {(w["workout_date"], w["title"]) for w in ws}
    for d, title in [
        (date(2026, 9, 9), "Threshold 3x10"),
        (date(2026, 9, 13), "Brick: 2h ride + 20 min run"),
        (date(2026, 9, 14), "Z2 ride"),
        (date(2026, 9, 15), "Intervals 6x800"),
        (date(2026, 9, 19), "Long ride"),
    ]:
        assert (d, title) in by_title
    # tss_day is the day's completed load, and the cases' own days are unchanged
    load: dict[date, float] = defaultdict(float)
    for w in ws:
        if w["completed"] and w.get("actual_tss") is not None:
            load[w["workout_date"]] += float(w["actual_tss"])
    days = seed.daily_metrics(ws)
    assert all(abs(float(d["tss_day"]) - load[d["metric_date"]]) < 0.01 for d in days)
    assert [d for d in days if d["metric_date"] >= date(2026, 9, 9)] == WEEK_DAYS
    assert max(d["metric_date"] for d in days) < TODAY
    # the recovery week carries less load than the week before it
    def week(monday):
        return sum(load[d] for d in load if monday <= d < date.fromordinal(monday.toordinal() + 7))
    assert week(date(2026, 8, 10)) < 0.8 * week(date(2026, 8, 3))


def _url() -> str:
    url = Settings().test_database_url
    try:
        psycopg.connect(url).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable at {url}: {exc}")
    return url


@pytest.mark.db
def test_the_seeded_rows_are_readable_through_the_real_sql_tool():
    url = _url()
    try:
        seed.seed_database(url)
        out = run_readonly_query(
            reader_url(url),
            "select title, rpe, comments from workouts where workout_date = date '2026-09-09'",
        )
        assert out["rows"][0][0] == "Threshold 3x10" and out["rows"][0][1] == 9
        assert "Legs were dead" in json.dumps(out["rows"][0][2])
        legs = run_readonly_query(
            reader_url(url),
            "select count(*) from garmin_activities where tp_workout_id = 'eval-brick'",
        )
        assert legs["rows"][0][0] == 2
    finally:
        seed.clear_database(url)
    with connect(url) as conn:
        assert conn.execute("select count(*) as n from workouts").fetchone()["n"] == 0


@pytest.mark.db
def test_seeding_twice_replaces_the_first_run():
    url = _url()
    try:
        seed.seed_database(url)
        seed.seed_database(url)  # a killed run's rows are the eval's own: replaced, not refused
        with connect(url) as conn:
            n = conn.execute("select count(*) as n from workouts").fetchone()["n"]
        assert n == len(seed.workouts())
    finally:
        seed.clear_database(url)


@pytest.mark.db
def test_seeding_refuses_a_database_with_rows_it_did_not_write():
    url = _url()
    with connect(url) as conn:
        conn.execute(
            "insert into workouts (tp_workout_id, workout_date, sport, raw) "
            "values ('real-1', '2026-09-01', 'run', '{}')"
        )
        conn.commit()
    try:
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.seed_database(url)
        with pytest.raises(seed.EvalDatabaseInUse):
            seed.clear_database(url)
    finally:
        with connect(url) as conn:
            conn.execute("delete from workouts where tp_workout_id = 'real-1'")
            conn.commit()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_seed.py -v`
Expected: collection error, `ImportError: cannot import name 'seed'`.

- [ ] **Step 3: Write `evals/seed.py`**

```python
"""One synthetic athlete history for the analyst eval, seeded into Postgres so the analyst's SQL
runs for real. June is a run block (no bike), then a triathlon build from 2026-07-06 with a
recovery week from 2026-08-10, then the cases' own week from 2026-09-07. tss_day is each day's
completed load and CTL/ATL follow it, except the seven WEEK_DAYS rows the context block shows.

Every row the eval writes is marked (workout ids start "eval-", the profile's tp_athlete_id is
"eval"); seeding refuses a database that holds anything else."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from tri_analyze.evals.cases import (
    BRICK,
    BRICK_SPLITS,
    INTERVAL_RUN,
    MISSED_SWIM,
    PROFILE,
    SLEEP_HRV,
    THRESHOLD_RIDE,
    TODAY,
    WEEK_DAYS,
    Z2_RIDE,
)
from tri_core.db.connection import connect
from tri_core.db.models import AthleteProfileRow, DailyMetricsRow, GarminActivityRow, WorkoutRow
from tri_core.db.repo import (
    Conn,
    set_garmin_match,
    upsert_athlete_profile,
    upsert_daily_metrics,
    upsert_garmin_activities,
    upsert_workouts,
)

EVAL_ID = "eval"
SEEDED_TABLES = ("garmin_activities", "workouts", "daily_metrics", "athlete_profile")
START = date(2026, 6, 1)  # a Monday
BUILD_START = date(2026, 7, 6)
RECOVERY_WEEK = date(2026, 8, 10)
CASE_WEEK = date(2026, 9, 7)  # from here on, the cases' own sessions

# (weekday, sport, title, planned TSS, intensity factor, metres per hour)
Template = tuple[int, str, str, int, float, int]
RUN_BLOCK: list[Template] = [
    (1, "run", "Intervals 6x800", 70, 0.90, 12000),
    (2, "swim", "CSS 10x100", 40, 0.85, 3300),
    (3, "run", "Easy 45 min", 45, 0.72, 10900),
    (5, "run", "Long run", 80, 0.75, 10600),
    (6, "swim", "Easy swim", 35, 0.70, 3000),
]
BUILD: list[Template] = [
    (1, "bike", "Threshold 3x10", 85, 0.88, 30000),
    (2, "swim", "CSS 10x100", 40, 0.85, 3300),
    (3, "run", "Easy 45 min", 45, 0.72, 10900),
    (5, "bike", "Long ride", 150, 0.70, 28500),
    (6, "run", "Long run", 75, 0.75, 10600),
]

EASY_SWIM = {
    "workout_date": "2026-09-08",
    "sport": "swim",
    "title": "Easy swim",
    "completed": True,
    "planned_tss": 35,
    "actual_tss": 34,
    "planned_duration_sec": 2600,
    "actual_duration_sec": 2580,
    "actual_distance_m": 2300,
}
EASY_RUN = {
    "workout_date": "2026-09-11",
    "sport": "run",
    "title": "Easy 45 min",
    "completed": True,
    "planned_tss": 45,
    "actual_tss": 45,
    "planned_duration_sec": 2700,
    "actual_duration_sec": 2760,
    "actual_distance_m": 8300,
    "avg_hr": 138,
    "feeling": 7,
    "rpe": 3,
}
TEMPO = {
    "workout_date": "2026-09-17",
    "sport": "run",
    "title": "Tempo 40 min",
    "completed": False,
    "planned_tss": 55,
    "planned_duration_sec": 3600,
}
LONG_RIDE = {
    "workout_date": "2026-09-19",
    "sport": "bike",
    "title": "Long ride",
    "completed": False,
    "planned_tss": 150,
    "planned_duration_sec": 11000,
}
CASE_WEEK_ROWS: list[tuple[str, dict[str, Any]]] = [
    ("easy-swim", EASY_SWIM),
    ("threshold", THRESHOLD_RIDE),
    ("easy-run", EASY_RUN),
    ("missed-swim", MISSED_SWIM),
    ("brick", BRICK),
    ("z2", Z2_RIDE),
    ("intervals", INTERVAL_RUN),
    ("tempo", TEMPO),
    ("long-ride", LONG_RIDE),
]


class EvalDatabaseInUse(RuntimeError):
    """The eval database holds rows the eval did not write."""


def workout_row(r: dict[str, Any]) -> WorkoutRow:
    """A WorkoutRow from a dict holding any of its fields; the rest are None, `completed` True
    and `raw` {}. `workout_date` may be an ISO string; keys that are not fields are ignored."""
    fields: dict[str, Any] = dict.fromkeys(WorkoutRow.__dataclass_fields__)
    fields.update(completed=True, raw={}, title="")
    fields.update({k: v for k, v in r.items() if k in fields})
    if isinstance(fields["workout_date"], str):
        fields["workout_date"] = date.fromisoformat(fields["workout_date"])
    return WorkoutRow(**fields)


def _seconds(tss: float, intensity: float) -> int:
    return round(tss / (intensity * intensity * 100) * 3600)


def _templated(d: date, t: Template, factor: float) -> dict[str, Any]:
    _, sport, title, tss, intensity, speed = t
    planned = round(tss * factor)
    actual = planned + d.toordinal() % 7 - 3
    secs = _seconds(actual, intensity)
    row: dict[str, Any] = {
        "tp_workout_id": f"{EVAL_ID}-{d.isoformat()}-{sport}",
        "workout_date": d,
        "sport": sport,
        "title": title,
        "completed": True,
        "planned_tss": planned,
        "planned_duration_sec": _seconds(planned, intensity),
        "actual_tss": actual,
        "actual_duration_sec": secs,
        "actual_distance_m": round(speed * secs / 3600),
        "actual_if": intensity,
        "avg_hr": round(100 + intensity * 70),
        "feeling": 6,
        "rpe": round(intensity * 10) - 2,
    }
    if sport == "bike":
        row["normalized_power"] = round(intensity * PROFILE["ftp_watts"])
        row["avg_power"] = round(intensity * PROFILE["ftp_watts"] * 0.95)
    return row


def workouts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = START
    while d < CASE_WEEK:
        monday = d - timedelta(days=d.weekday())
        plan = RUN_BLOCK if d < BUILD_START else BUILD
        factor = 0.65 if monday == RECOVERY_WEEK else 1.0
        out += [_templated(d, t, factor) for t in plan if t[0] == d.weekday()]
        d += timedelta(days=1)
    for slug, row in CASE_WEEK_ROWS:
        out.append(
            {
                **row,
                "tp_workout_id": f"{EVAL_ID}-{slug}",
                "workout_date": date.fromisoformat(str(row["workout_date"])),
            }
        )
    return out


def daily_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    load: dict[date, float] = defaultdict(float)
    for w in rows:
        if w.get("completed") and w.get("actual_tss") is not None:
            load[w["workout_date"]] += float(w["actual_tss"])
    fixed = {d["metric_date"]: d for d in WEEK_DAYS}
    sleep = {date.fromisoformat(str(s["metric_date"])): s for s in SLEEP_HRV}
    ctl = atl = 40.0
    out: list[dict[str, Any]] = []
    d = START
    while d < TODAY:
        tss = load.get(d, 0.0)
        ctl += (tss - ctl) / 42
        atl += (tss - atl) / 7
        if d in fixed:
            out.append(dict(fixed[d]))  # the cases' own days, exactly as the context shows them
            ctl, atl = float(fixed[d]["ctl"]), float(fixed[d]["atl"])
        else:
            n = d.toordinal()
            s = sleep.get(d) or {"sleep_score": 70 + n * 7 % 15, "hrv_overnight_avg": 58 + n * 5 % 11}
            score, hrv = int(s["sleep_score"]), int(s["hrv_overnight_avg"])
            out.append(
                {
                    "metric_date": d,
                    "tss_day": tss,
                    "ctl": round(ctl, 1),
                    "atl": round(atl, 1),
                    "tsb": round(ctl - atl, 1),
                    "sleep_score": score,
                    "hrv_overnight_avg": hrv,
                    "resting_hr": 46,
                    "training_readiness": max(20, min(95, 40 + (score - 60) + (hrv - 55))),
                }
            )
        d += timedelta(days=1)
    return out


def _activities(rows: list[dict[str, Any]]) -> list[tuple[GarminActivityRow, str]]:
    """One Garmin activity per linked session, and the brick's run leg as a second one."""
    out: list[tuple[GarminActivityRow, str]] = []
    for w in rows:
        gid = w.get("garmin_activity_id")
        if not gid:
            continue
        start = datetime.combine(w["workout_date"], time(7, 0))
        sport = "cycling" if w["sport"] in ("bike", "brick") else w["sport"]
        first = BRICK_SPLITS[0] if w["sport"] == "brick" else {}
        out.append(
            (
                GarminActivityRow(
                    id=gid,
                    type_key=sport,
                    sport=sport,
                    start_time_local=start,
                    duration_sec=first.get("duration_sec", w.get("actual_duration_sec")),
                    distance_m=first.get("distance_m", w.get("actual_distance_m")),
                    avg_hr=first.get("avg_hr", w.get("avg_hr")),
                    name=w["title"],
                    raw={},
                ),
                w["tp_workout_id"],
            )
        )
        if w["sport"] == "brick":
            leg = BRICK_SPLITS[1]
            out.append(
                (
                    GarminActivityRow(
                        id=f"{gid}-run",
                        type_key="running",
                        sport="running",
                        start_time_local=start + timedelta(seconds=int(first["duration_sec"])),
                        duration_sec=leg["duration_sec"],
                        distance_m=leg["distance_m"],
                        avg_hr=leg["avg_hr"],
                        name=f"{w['title']} (run)",
                        raw={},
                    ),
                    w["tp_workout_id"],
                )
            )
    return out


def _refuse_foreign_rows(conn: Conn) -> None:
    foreign = conn.execute(
        "select (select count(*) from workouts where tp_workout_id not like %s) "
        "+ (select count(*) from athlete_profile where tp_athlete_id is distinct from %s) as n",
        (f"{EVAL_ID}-%", EVAL_ID),
    ).fetchone()
    if foreign and foreign["n"]:
        raise EvalDatabaseInUse(
            "the eval database holds workouts or a profile the eval did not write; refusing to "
            "replace them (use the test database, or an empty one with --eval-db)"
        )


def clear_database(url: str) -> None:
    with connect(url) as conn:
        _refuse_foreign_rows(conn)
        conn.execute("truncate " + ", ".join(SEEDED_TABLES))
        conn.commit()


def seed_database(url: str) -> None:
    """Replace the seeded tables' contents with the history. Committed: the SQL tool reads them
    on its own connection."""
    rows = workouts()
    with connect(url) as conn:
        _refuse_foreign_rows(conn)
        conn.execute("truncate " + ", ".join(SEEDED_TABLES))
        upsert_athlete_profile(
            conn,
            AthleteProfileRow(
                tp_athlete_id=EVAL_ID,
                ftp_watts=PROFILE["ftp_watts"],
                run_threshold_pace_sec_per_km=PROFILE["run_threshold_pace_sec_per_km"],
                swim_css_sec_per_100m=PROFILE["swim_css_sec_per_100m"],
                lthr_bpm=PROFILE["lthr_bpm"],
                max_hr_bpm=PROFILE["max_hr_bpm"],
                hr_zones=None,
                power_zones=None,
                pace_zones=None,
                weight_kg=PROFILE["weight_kg"],
                raw={},
            ),
        )
        upsert_workouts(conn, [workout_row(r) for r in rows])
        acts = _activities(rows)
        upsert_garmin_activities(conn, [a for a, _ in acts])
        for a, tp_id in acts:
            conn.execute(
                "update garmin_activities set tp_workout_id = %s where id = %s", (tp_id, a.id)
            )
            if not a.id.endswith("-run"):
                set_garmin_match(conn, tp_id, a.id, a.start_time_local)
        upsert_daily_metrics(conn, [DailyMetricsRow(**m) for m in daily_metrics(rows)])
        conn.commit()
```

(If `truncate` fails because another table references one of `SEEDED_TABLES`, stop and report which; do not add `cascade`.)

- [ ] **Step 4: `seed_workouts` takes every field**

In `packages/tri-analyze/src/tri_analyze/testing.py`, replace `seed_workouts`'s body with `upsert_workouts(conn, [workout_row(r) for r in rows])` (import `workout_row` from `tri_analyze.evals.seed`) and its docstring with `rows: dicts with tp_workout_id, workout_date, sport and any other WorkoutRow field (the rest None; completed True).` Remove the now-unused `WorkoutRow` import if any.

- [ ] **Step 5: Run the analyst suite**

Run: `uv run pytest packages/tri-analyze -q -rs`
Expected: all pass, the three `db` tests pass (not skip); if they skip, Postgres is down: `docker compose up -d db`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyst-eval): one seeded athlete history, refused on a database it did not write"
```

---

### Task 5: The analyst eval runs its SQL against the seeded database

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/target.py` (`stub_tools`, `run_case`, `make_target`)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/cases.py` (drop every `query_training_db` canned result)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/run.py` (`run_eval` seeds, binds, clears)
- Modify: `packages/tri-analyze/src/tri_analyze/cli.py` (`eval --eval-db`)
- Test: `packages/tri-analyze/tests/test_evals.py`, `packages/tri-analyze/tests/test_cli.py`

**Interfaces:**
- Consumes: `seed.seed_database`, `seed.clear_database`, `seed.EvalDatabaseInUse` (Task 4); `tri_core.config.reader_url`.
- Produces: `stub_tools(inputs, sql_tool: BaseTool | None = None)`; `make_target(model, sql_url: str | None = None)`; `run_eval(settings, models, *, judge=True, prefix=None, recreate=False, log=print, eval_db_url=None) -> tuple[dict[str, float], int]`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-analyze/tests/test_evals.py`:

- Replace `_stub_langsmith` so it also stubs the seeding and records it:

```python
def _stub_langsmith(monkeypatch, run_module) -> dict:
    captured: dict = {"seeded": [], "cleared": []}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    monkeypatch.setattr(run_module, "Client", _FakeClient)
    monkeypatch.setattr(run_module, "aevaluate", fake_aevaluate)
    monkeypatch.setattr(run_module, "seed_database", captured["seeded"].append)
    monkeypatch.setattr(run_module, "clear_database", captured["cleared"].append)
    return captured
```

- `test_stubs_answer_from_the_case`, `test_target_returns_the_calls_and_the_final_answer` and `test_judge_prompt_carries_the_rendered_system_prompt_question_results_and_answer`: build the case they need with its SQL result explicitly, for example at the top of `test_stubs_answer_from_the_case`:

```python
    base = case("run_intervals")
    c = EvalCase(
        **{
            **base.__dict__,
            "tool_results": {**base.tool_results, "query_training_db": [sql_rows(INTERVAL_RUN)]},
        }
    )
```

  (import `sql_rows`, `INTERVAL_RUN`, `THRESHOLD_RIDE` from `tri_analyze.evals.cases`; the judge-prompt test uses `THRESHOLD_RIDE` with `case("threshold_rpe9")`). Every existing assertion stays.

- Append:

```python
def test_no_case_cans_sql_any_more():
    assert all("query_training_db" not in c.tool_results for c in CASES)


async def test_the_target_binds_the_given_sql_tool():
    seen: list[str] = []

    async def query_training_db(sql: str) -> str:
        seen.append(sql)
        return SQL_ENVELOPE_EMPTY

    from langchain_core.tools import StructuredTool

    real = StructuredTool.from_function(
        coroutine=query_training_db, name="query_training_db", description="the real tool"
    )
    tools = stub_tools(case("trend_no_data").inputs(), sql_tool=real)
    assert tools[0] is real


async def test_run_eval_seeds_the_test_database_and_clears_it_after(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert captured["seeded"] == [settings.test_database_url]
    assert captured["cleared"] == [settings.test_database_url]


async def test_run_eval_clears_even_when_the_run_fails(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)

    async def boom(target, **kw):
        raise RuntimeError("langsmith down")

    monkeypatch.setattr(analyze_run, "aevaluate", boom)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    with pytest.raises(RuntimeError):
        await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert captured["cleared"] == [settings.test_database_url]


async def test_run_eval_refuses_the_athletes_database(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    with pytest.raises(ValueError, match="athlete's database"):
        await analyze_run.run_eval(
            settings, models, log=lambda m: None, eval_db_url=settings.database_url
        )
    assert captured["seeded"] == []


@pytest.mark.db
async def test_the_target_runs_real_sql_against_the_seeded_history():
    from tri_analyze.evals import seed
    from tri_core.config import Settings, reader_url

    url = Settings().test_database_url
    try:
        seed.seed_database(url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable: {exc}")
    try:
        sql = "select title, actual_tss from workouts where workout_date = date '2026-09-14'"
        model = ScriptedChatModel(
            script=[
                tool_call("query_training_db", {"sql": sql}, "c1"),
                AIMessage(content="The Z2 ride scored 58 TSS."),
            ]
        )
        out = await make_target(model, reader_url(url))(case("last_z2_ride").inputs())
        assert '"Z2 ride"' in out["tool_results"][0]["content"]
        assert "58" in out["tool_results"][0]["content"]
    finally:
        seed.clear_database(url)
```

(add `import psycopg` to the test imports.)

In `packages/tri-analyze/tests/test_cli.py`, append:

```python
def test_eval_refuses_the_athletes_database(monkeypatch):
    settings = AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls")
    monkeypatch.setattr(cli, "get_analyze_settings", lambda: settings)
    result = runner.invoke(app, ["eval", "--eval-db", settings.database_url])
    assert result.exit_code == 2 and "athlete's database" in result.output


def test_eval_passes_the_eval_database_through(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_analyze_settings",
        lambda: AnalyzeSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen: list[dict] = []

    async def run_eval(settings, model, **kw):
        seen.append(kw)
        return {"uses_sql": 1.0}, 0

    monkeypatch.setattr("tri_analyze.evals.run.run_eval", run_eval)
    result = runner.invoke(app, ["eval", "--eval-db", "postgresql://u:p@h:1/evaldb"])
    assert result.exit_code == 0 and seen[-1]["eval_db_url"] == "postgresql://u:p@h:1/evaldb"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py packages/tri-analyze/tests/test_cli.py -v`
Expected: the new tests FAIL (`sql_tool` unknown, seeding not called, no `--eval-db`).

- [ ] **Step 3: The target**

In `evals/target.py`: `stub_tools(inputs: dict[str, Any], sql_tool: BaseTool | None = None)`; the first tool becomes `sql_tool if sql_tool is not None else make(query_training_db, "query_training_db", SQL_DESCRIPTION)`. The docstring gains: `sql_tool: the real query tool on the eval database; without it a canned stub answers (tests).` `run_case(model, inputs, sql_url: str | None = None)` passes `make_query_tool(sql_url) if sql_url else None`; `make_target(model, sql_url: str | None = None)` passes it through. Update the module docstring's "No database" to: `The SQL tool runs against the seeded eval database when a URL is given; the live tools stay canned.`

- [ ] **Step 4: The cases**

In `evals/cases.py`, remove the `"query_training_db": [...]` entry from every case's `tool_results` (the six cases whose only entry was SQL lose `tool_results` entirely; the others keep their live-tool entries). Keep `sql_rows`, `SQL_ENVELOPE_EMPTY` and the session fixtures (the seed and the tests use them); delete `WEEKLY_TSS` and `RUN_VOLUME` if `git grep` shows nothing else uses them, since the seeded history now answers those questions. Update the module docstring: `canned results for the live tools (the SQL runs against evals/seed.py's history)`.

- [ ] **Step 5: `run_eval`**

In `evals/run.py`, add `from tri_analyze.evals.seed import clear_database, seed_database` and `from tri_core.config import reader_url`, and change `run_eval`:

```python
async def run_eval(
    settings: AnalyzeSettings,
    models: ModelProvider,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
    eval_db_url: str | None = None,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples. The analyst
    runs on its role's model and the judge on the judge role's. The history in evals/seed.py is
    seeded into the eval database (the test database unless given) and the tables are emptied
    afterwards, pass or fail."""
    url = eval_db_url or settings.test_database_url
    if url == settings.database_url:
        raise ValueError("refusing to seed the athlete's database; use the test database")
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(models(Role.JUDGE)))
    seed_database(url)
    try:
        results = await aevaluate(
            make_target(models(Role.ANALYST), reader_url(url)),
            data=DATASET_NAME,
            evaluators=evaluators,
            experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}",
            metadata={
                "prompt_version": PROMPT_VERSION,
                **eval_metadata(settings, Role.ANALYST, judge=judge),
            },
            client=client,
            max_concurrency=2,
        )
        rows: list[Any] = [row async for row in results]
    finally:
        clear_database(url)
    dict_rows = [dict(r) for r in rows]
    ...  # Task 1's tail, unchanged
```

- [ ] **Step 6: The CLI**

In `cli.py`, the `eval` command gains:

```python
    eval_db: str | None = typer.Option(
        None,
        "--eval-db",
        help="Postgres URL the eval seeds and empties (default: TEST_DATABASE_URL); never the "
        "athlete's database",
    ),
```

passed to `_eval(prefix=..., recreate=..., eval_db=eval_db)`. In `_eval`, after the key checks:

```python
    if eval_db is not None and eval_db == settings.database_url:
        console.print("refusing: --eval-db is the athlete's database", style="red")
        return 2
    try:
        rates, errors = await run_eval(
            settings,
            lambda role: make_model(settings, role),
            prefix=prefix,
            recreate=recreate,
            log=lambda m: _out(m + "\n"),
            eval_db_url=eval_db,
        )
    except (psycopg.OperationalError, EvalDatabaseInUse, ValueError) as exc:
        console.print(f"eval database: {exc}", style="red")
        return 2
```

(import `psycopg` and `from tri_analyze.evals.seed import EvalDatabaseInUse` inside `_eval` next to the other lazy imports). The command docstring gains: `The analyst's SQL runs against a history seeded into the test database (or --eval-db), which is emptied afterwards.`

- [ ] **Step 7: Run the analyst suite**

Run: `uv run pytest packages/tri-analyze -q -rs`
Expected: all pass, `db` tests pass (not skip).

- [ ] **Step 8: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyst-eval): SQL runs against the seeded history; --eval-db; never the athlete's database"
```

---

### Task 6: Docs, full checks, vault copies, hand-off

**Files:**
- Modify: `packages/tri-analyze/README.md` (the eval section), `packages/tri-coach/README.md` (the eval section)
- Mirror: the vault copies of every markdown file this branch changed, and this plan

- [ ] **Step 1: README edits**

`packages/tri-analyze/README.md`, in the eval section (find it with `grep -n -i "eval" packages/tri-analyze/README.md`), replace the description of canned SQL results with:

```
The analyst's SQL runs for real: `tri-analyze eval` seeds one synthetic athlete history
(`evals/seed.py`: a June run block, a triathlon build from July with a recovery week, and the
cases' own week of 2026-09-07) into the test database, binds the real `query_training_db` as
`tri_reader`, and empties the tables when it finishes. `--eval-db URL` points it at another
empty database; it refuses the athlete's database and any database holding rows it did not
write. Garmin and TrainingPeaks tools stay canned. The judge accepts a derived number when the
answer shows the arithmetic. Needs Postgres, `LANGSMITH_API_KEY` and `ANTHROPIC_API_KEY`.
```

and add `--eval-db URL` to the `tri-analyze eval` usage line.

`packages/tri-coach/README.md`, in the eval section, add:

```
The brief judge sees what the coach saw: the context block, the memory, the conversation and
every answer the stub tools served. `brief_quality` fails a brief with a number, date or lab
value that appears in none of them (`grounded`), naming the brief by index.
```

Both packages' eval sections: where the pass-rate output is shown, show the new format with counts (for example `  grounded                    67% (8/12)`).

- [ ] **Step 2: Full checks, in the Definition of Done order**

```bash
uv run pytest -q -rs
uv run ruff format --check . && uv run ruff check . && uv run mypy
(cd web && npm run lint && npm test && npm run build)
```

Expected: pytest all pass, `SKIPPED` only for `needs --live`; ruff and mypy clean; web checks pass (untouched).

- [ ] **Step 3: Vault copies**

For each markdown file this branch changed (`git diff --name-only main...HEAD -- '*.md'`), compare `git show main:<path>` with its vault copy under `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/` (package READMEs are `packages/<pkg>/readme.md`). If they matched, copy the repo file over; if the vault had drifted, apply only this branch's edits and say so. Make sure this plan's vault copy matches the repo.

- [ ] **Step 4: Commit**

```bash
git add packages/tri-analyze/README.md packages/tri-coach/README.md
git commit -m "docs: the analyst eval seeds a history; the coach judge grades grounding"
```

- [ ] **Step 5: Hand-off for Brian**

Tell Brian, in order:
1. Optional, before merging: `uv run tri-coach eval` on `main` gives `coach-v4` with the old judge, so the prompt change and the judge change can be told apart.
2. After merging: `uv run tri-analyze eval --prefix analyst-v2-base` (needs the test database up, `LANGSMITH_API_KEY`, `ANTHROPIC_API_KEY`) and `uv run tri-coach eval --prefix coach-v4-base`. These are the new baselines future routing experiments compare against; the old `grounded` 8% baseline is expected to move.
3. `uv run tri-planning eval` (`design-v2`) from Guardrails 01 is still pending.
4. Once they have run, the results go in `docs/notes/` (spec §7).
