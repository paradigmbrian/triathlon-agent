# Analyst Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The analyst judge checks derivations instead of demanding shown arithmetic and reads SQL rows by column name and weekdays from a calendar line; then the analyst sees weekdays and the athlete's zones in its context, and its rules forbid invented ranges, baselines and mental arithmetic.

**Architecture:** Two steps on one branch, each ending in a local eval run Brian starts. Step 1 (Tasks 1-4) changes only the judge: `render_judge_prompt` gains a calendar line and renders `query_training_db` envelopes as `col: value` lines, `grounded` and `JUDGE_SYSTEM` are rewritten, and `JUDGE_VERSION = "2"` is recorded in the experiment metadata and every `.evals` row. Step 2 (Tasks 5-8) changes the analyst: weekdays on every context date, a zones block rendered from TrainingPeaks zone groups, new rules with `PROMPT_VERSION = "3"`, and TrainingPeaks-shaped zones on the eval profile, seeded into the test database. The calendar helpers live in `tri_analyze/prompts/analyst.py` and the judge imports them.

**Tech Stack:** Python 3.12, Pydantic v2, LangSmith `aevaluate`, psycopg 3 (jsonb via `Jsonb`), Postgres 16, pytest (`asyncio_mode = "auto"`), ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-09-28-analyst-grounding-design.md` (all sections). Its line numbers are `main` @ 8acf0bf; this plan uses `main` @ 501bb3a (the spec commit only; no code moved).

**Branch:** `feat/analyst-grounding` off `main` @ 501bb3a (created in Task 1).

## Global Constraints

- Analyst `FeedbackJudgement.grounded` description, exactly: `every number in the answer appears in the context or the tool results, or can be reproduced from them by a unit conversion or arithmetic within the answer's rounding; a number that appears nowhere or does not reproduce is ungrounded; a prescribed range must come from the athlete's zones or a stated fraction of a threshold; missing data is stated as missing`.
- `JUDGE_VERSION = "2"` in `tri_analyze/evals/evaluators.py`. `PROMPT_VERSION` stays `"2"` through step 1 and becomes `"3"` in Task 7.
- Judge model unchanged: `Role.JUDGE`, structured output.
- Weekday names come from a fixed English tuple, never `strftime("%a")`/`%A` (locale-dependent).
- Weeks start Monday; the calendar lists six Mondays, from four weeks before this week's Monday to next week's Monday. For today 2026-09-16: `2026-08-17, 2026-08-24, 2026-08-31, 2026-09-07, 2026-09-14, 2026-09-21`.
- The analyst's tool output is unchanged. Only the judge's rendering of `query_training_db` results changes.
- Zone groups: `workoutTypeId` 1 swim, 2 bike, 3 run, 0 default. Speed zones are m/s.
- Zones fallback, exactly: `Zones: not synced; prescribe only as a stated % of a threshold.`
- **Brian's database rule:** no migration and no DDL. The `athlete_profile` zone columns already exist (`migrations/001_initial.sql`, jsonb). The eval's seeding of the test database runs only in the test suite and in `tri-analyze eval`. Never point anything at `tri_analyze` (the athlete's database).
- **Brian's dependency rule:** this plan uses only APIs the repo already uses (`pydantic.Field`, `aevaluate(metadata=...)`, psycopg `Jsonb`) plus the stdlib (`json`, `re`, `datetime`). Before the first edit that touches a Pydantic or LangSmith call, check the installed versions (`uv pip show pydantic langsmith`) against Context7. If Context7 shows no change to those calls, go ahead.
- Run `uv run ruff format packages/tri-analyze packages/tri-core` before each commit.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push.

## Deviations from the spec (decided while planning, 2026-09-28)

1. **Seeded power Z2 is `138-187 W`, not `138-188 W`.** At FTP 250 the 75% cut is 187.5 W. With contiguous integer bounds, Z1 `0-137` and Z2 `…-188` can't both come from one rounding rule. Bounds are `floor(threshold × pct / 100)` in integer arithmetic, with the next zone starting 1 above. So the seed is Z1 0-137, Z2 138-187, Z3 188-225, Z4 226-262, Z5 263-300, Z6 301+.
2. **Seeded zones carry TrainingPeaks names** (Coggan for power, Friel for HR). §4.1's `Z2 Aerobic` labelling therefore shows up in the eval context: `Z2 Endurance 138-187 W`.
3. **Swim bands:** cut-offs at CSS +15, +10, +5 and −5 s/100m. This gives 5 zones, with the threshold zone at CSS ±5.
4. **Open-ended zones:** the last power or HR zone renders as `301+ W`. A pace zone whose slow bound is 0 m/s renders as `slower than 5:29/km`, and the fastest pace zone as `faster than 4:07/km`. Otherwise TrainingPeaks' placeholder tops (2000 W, 36 m/s) would print as nonsense.
5. **`calendar_line(today)` returns only `Weeks start Monday: ….`** Each caller adds its own prefix: the analyst adds `Today is 2026-09-16 (Wed). `, the judge `Calendar: today 2026-09-16 is a Wednesday. `. A second helper, `dated(d)`, renders `2026-09-12 (Sat)`.
6. **`judge_version` is recorded only when the judge runs**, the same way `judge_model` is. `.evals` rows get the metadata through a new keyword argument, `record_rows(..., metadata=...)`, in `tri_core.evals`. Without it the row shape is unchanged, so the other four packages' evals are untouched.
7. **The `last_z2_ride` envelope test builds its own envelope** in the real query's column order, because `test_no_case_cans_sql_any_more` forbids canned SQL in the cases.
8. **After step 2, the judge prompt shows the analyst's today line and the calendar line.** They agree, so the judge does not need its own copy removed.

### Existing tests this plan changes, and why

| Test | Change | Task |
|---|---|---|
| `tri-analyze/tests/test_evals.py::test_grounded_accepts_arithmetic_the_answer_shows` | Replaced by `test_grounded_accepts_derivations_the_judge_can_reproduce` (§3.1 drops shown arithmetic) | 3 |
| `test_evals.py::test_run_eval_uses_the_analyst_and_judge_roles` | Exact metadata dict gains `"judge_version": JUDGE_VERSION` | 4 |
| `test_evals.py::test_run_eval_without_the_judge_records_no_judge_model` | Adds `"judge_version" not in` (additive) | 4 |
| `test_evals.py::test_judge_prompt_carries_the_rendered_system_prompt_question_results_and_answer` | `"Today is 2026-09-16."` → `"Today is 2026-09-16 (Wed)."` | 5 |
| `tri-analyze/tests/test_prompt.py::test_render_includes_profile_load_and_tools` | Today line and workout line gain weekdays | 5 |
| `test_prompt.py::test_render_marks_done_planned_and_missed` | Four workout lines gain weekdays | 5 |
| `tri-analyze/tests/test_agent.py` lines 85-86 | `"Today is 2026-09-06 (Sun)."`, `"Today is 2026-09-07 (Mon)."` | 5 |
| `test_prompt.py::test_render_feedback_rules_present_and_version_is_1` | `PROMPT_VERSION == "3"` | 7 |
| `test_prompt.py::test_the_rules_ask_for_shown_arithmetic_and_a_literal_today` | Replaced by `test_the_rules_drop_shown_arithmetic_and_keep_a_literal_today` | 7 |

## Review Focus

1. **A garbled zone group.** This covers `zones` that is null, not a list, empty, a zone missing `minimum` or `maximum`, a bool or string bound, and a speed `maximum` of 0. The expected behavior: that group is skipped (a fallback group is used if one exists), nothing raises, and the block says "not synced" when no group is left. The tests go in Task 6.
2. **A `query_training_db` result that looks like the envelope but isn't.** This covers an `{"error": …}` result, a row shorter than `columns`, `rows` that isn't a list, and a JSON list. The expected behavior: the content passes through byte for byte, and the judge never sees a half-rendered table. The tests go in Task 2.
3. **Today on a week boundary.** When today is a Monday or a Sunday, the six Mondays must still include this week's Monday, not drift by a week. The tests go in Task 1.
4. **The empty envelope and the truncated envelope.** A result with no rows still tells the judge the query returned nothing (`row_count: 0; truncated: false`). A cut result keeps its note. The tests go in Task 2.
5. **The same zones in two places.** The eval context (`athlete()`) and the seeded `athlete_profile` row, read back through `load_athlete_context`, must render the same zones block; if they drift, the judge checks against a different table than the analyst's SQL. The DB test goes in Task 8.

---

### Task 1: Calendar helpers

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py` (imports, new helpers after `_num`)
- Test: `packages/tri-analyze/tests/test_prompt.py`

**Interfaces:**
- Produces: `WEEKDAYS: tuple[str, ...]` (`"Monday"` … `"Sunday"`); `dated(d: date) -> str` (`"2026-09-12 (Sat)"`); `calendar_line(today: date) -> str` (`"Weeks start Monday: 2026-08-17, …, 2026-09-21."`).

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/analyst-grounding
```

- [ ] **Step 2: Write the failing tests** (append to `test_prompt.py`; add `calendar_line, dated, WEEKDAYS` to the `tri_analyze.prompts.analyst` import)

```python
def test_dated_names_the_weekday_in_fixed_english():
    assert dated(date(2026, 9, 12)) == "2026-09-12 (Sat)"
    assert dated(date(2026, 9, 16)) == "2026-09-16 (Wed)"
    assert WEEKDAYS[date(2026, 9, 16).weekday()] == "Wednesday"


def test_calendar_line_lists_six_mondays_from_four_weeks_back_to_next_week():
    expected = (
        "Weeks start Monday: 2026-08-17, 2026-08-24, 2026-08-31, 2026-09-07, 2026-09-14, "
        "2026-09-21."
    )
    assert calendar_line(date(2026, 9, 16)) == expected
    assert calendar_line(date(2026, 9, 14)) == expected  # today is a Monday
    assert calendar_line(date(2026, 9, 20)) == expected  # today is a Sunday
```

- [ ] **Step 3: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py -k "dated or calendar_line" -v`
Expected: collection error, `ImportError: cannot import name 'WEEKDAYS'`.

- [ ] **Step 4: Implement** (in `analyst.py`: change `from datetime import date` to `from datetime import date, timedelta`, then add after `_num`)

```python
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def dated(d: date) -> str:
    """`2026-09-12 (Sat)`. Weekday names are fixed English, not the locale's."""
    return f"{d.isoformat()} ({WEEKDAYS[d.weekday()][:3]})"


def calendar_line(today: date) -> str:
    """The Mondays of the six weeks from four weeks back to next week. The analyst's today line
    and the judge's calendar line both end with it, so both name weeks the same way."""
    monday = today - timedelta(days=today.weekday())
    mondays = [monday + timedelta(weeks=n) for n in range(-4, 2)]
    return "Weeks start Monday: " + ", ".join(m.isoformat() for m in mondays) + "."
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py -v`
Expected: all pass. The prompt text is unchanged, so every existing test still passes.

- [ ] **Step 6: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyze): weekday and week-start calendar helpers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Judge input — calendar line and SQL rows as lines

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (imports; new `_sql_lines`, `_value`; `render_judge_prompt` at `:155-170`)
- Test: `packages/tri-analyze/tests/test_evals.py`

**Interfaces:**
- Consumes: `WEEKDAYS`, `calendar_line` from Task 1.
- Produces: `render_judge_prompt(inputs, outputs) -> str`, now starting `Calendar: today {iso} is a {Weekday}. Weeks start Monday: ….\n\nAnalyst system prompt:\n`.

- [ ] **Step 1: Write the failing tests** (append to `test_evals.py`)

```python
def _judged(content: str, name: str = "query_training_db") -> str:
    return render_judge_prompt(
        case("last_z2_ride").inputs(),
        {"calls": [], "answer": "ok", "tool_results": [{"name": name, "content": content}]},
    )


# The row the analyst fetched in fresh-decision-92, in its column order: a wide row whose
# positions the judge misread (power as HR and cadence).
Z2_ROW = {
    "workout_date": "2026-09-14",
    "sport": "bike",
    "title": "Z2 ride",
    "actual_duration_sec": 5460,
    "actual_tss": 58,
    "actual_if": 0.62,
    "normalized_power": 160,
    "avg_power": 155,
    "avg_hr": 132,
    "avg_cadence": 88,
    "feeling": 7,
    "rpe": 4,
    "comments": None,
}


def test_the_judge_sees_a_calendar_line_before_the_context():
    text = render_judge_prompt(case("last_z2_ride").inputs(), {"calls": [], "answer": "ok"})
    assert text.startswith(
        "Calendar: today 2026-09-16 is a Wednesday. Weeks start Monday: 2026-08-17, "
        "2026-08-24, 2026-08-31, 2026-09-07, 2026-09-14, 2026-09-21.\n\nAnalyst system prompt:\n"
    )


def test_the_judge_reads_sql_rows_as_column_value_lines():
    served = sql_rows(Z2_ROW)
    text = _judged(served)
    assert "query_training_db:\n- workout_date: 2026-09-14; sport: bike; title: Z2 ride; " in text
    assert "normalized_power: 160; avg_power: 155; avg_hr: 132" in text
    assert "comments: null" in text
    assert "row_count: 1; truncated: false" in text
    assert served not in text


def test_the_judge_keeps_the_empty_result_and_the_truncation_note():
    assert "query_training_db:\nrow_count: 0; truncated: false" in _judged(SQL_ENVELOPE_EMPTY)
    cut = json.dumps(
        {
            "columns": ["n", "tags"],
            "rows": [[1, ["a", "b"]], [2, None]],
            "row_count": 2,
            "truncated": True,
            "note": "result cut at 2 rows",
        }
    )
    assert (
        '- n: 1; tags: ["a", "b"]\n- n: 2; tags: null\n'
        "row_count: 2; truncated: true; note: result cut at 2 rows"
    ) in _judged(cut)


@pytest.mark.parametrize(
    "content",
    [
        '{"error": "sql error: boom"}',
        "not json",
        "[1, 2]",
        '{"columns": ["a", "b"], "rows": [[1]], "row_count": 1, "truncated": false}',
        '{"columns": ["a"], "rows": "x", "row_count": 1, "truncated": false}',
    ],
)
def test_the_judge_passes_anything_but_the_envelope_through(content):
    assert f"query_training_db:\n{content}" in _judged(content)


def test_other_tools_pass_through_even_when_shaped_like_the_envelope():
    env = sql_rows({"a": 1})
    assert f"get_activity:\n{env}" in _judged(env, name="get_activity")
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -k "judge_sees or judge_reads or judge_keeps or judge_passes or other_tools" -v`
Expected: the calendar, lines and empty/note tests FAIL. The pass-through tests already pass, since content is verbatim today.

- [ ] **Step 3: Implement** (in `evaluators.py`: add `import json` to the imports and change the analyst import to `from tri_analyze.prompts.analyst import WEEKDAYS, calendar_line, render_system_prompt`; add before `render_judge_prompt`, then replace `render_judge_prompt`)

```python
def _value(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)


def _sql_lines(content: str) -> str:
    """A query_training_db envelope as one `- col: value; …` line per row and a closing
    `row_count; truncated[; note]` line, so a wide row cannot be read out of position. Anything
    that is not that envelope (an error, a bad row, not JSON) comes back unchanged."""
    try:
        env = json.loads(content)
    except ValueError:
        return content
    if not isinstance(env, dict):
        return content
    columns, body = env.get("columns"), env.get("rows")
    if not isinstance(columns, list) or not isinstance(body, list):
        return content
    if not all(isinstance(r, list) and len(r) == len(columns) for r in body):
        return content
    lines = [
        "- " + "; ".join(f"{c}: {_value(v)}" for c, v in zip(columns, r, strict=True))
        for r in body
    ]
    closing = f"row_count: {len(body)}; truncated: {_value(bool(env.get('truncated')))}"
    if env.get("note"):
        closing += f"; note: {env['note']}"
    return "\n".join([*lines, closing])


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any]) -> str:
    """Grounds the judge on what the analyst actually received: `outputs["tool_results"]`
    (the served `ToolMessage`s from `run_case`), not the case's full canned corpus — a canned
    fixture the analyst never called never appears here. A calendar line names today's weekday
    and the week starts; query_training_db envelopes render as `col: value` lines."""
    ctx = athlete_from_inputs(inputs)
    system = render_system_prompt(ctx, [t.name for t in stub_tools(inputs)])
    served = outputs.get("tool_results") or []
    grouped: dict[str, list[str]] = {}
    for result in served:
        name, content = str(result["name"]), str(result["content"])
        if name == "query_training_db":
            content = _sql_lines(content)
        grouped.setdefault(name, []).append(content)
    rendered = "\n".join(f"{name}:\n" + "\n".join(responses) for name, responses in grouped.items())
    calendar = (
        f"Calendar: today {ctx.today.isoformat()} is a {WEEKDAYS[ctx.today.weekday()]}. "
        f"{calendar_line(ctx.today)}"
    )
    return (
        f"{calendar}\n\n"
        f"Analyst system prompt:\n{system}\n\n"
        f"Question:\n{inputs.get('question', '')}\n\n"
        f"Tool results:\n{rendered or '(none)'}\n\n"
        f"Answer:\n{outputs.get('answer') or ''}"
    )
```

- [ ] **Step 4: Run the whole file and see it pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -v`
Expected: all pass. The existing judge-prompt test still finds `Legs were dead from the start`, because a comment string renders inside its line.

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(evals): the analyst judge gets a calendar line and reads SQL rows by column

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The `grounded` rule and `JUDGE_SYSTEM`

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py:110-116` (`grounded` field), `:137-152` (`JUDGE_SYSTEM`)
- Test: `packages/tri-analyze/tests/test_evals.py:486-492` (replaced)

**Interfaces:**
- Produces: `FeedbackJudgement` with the same field names (so `verdict()` and `test_evals.py:378` still hold) and `JUDGE_SYSTEM: str`.

- [ ] **Step 1: Replace the test** `test_grounded_accepts_arithmetic_the_answer_shows` (lines 486-492) with:

```python
GROUNDED = (
    "every number in the answer appears in the context or the tool results, or can be "
    "reproduced from them by a unit conversion or arithmetic within the answer's rounding; a "
    "number that appears nowhere or does not reproduce is ungrounded; a prescribed range must "
    "come from the athlete's zones or a stated fraction of a threshold; missing data is stated "
    "as missing"
)


def test_grounded_accepts_derivations_the_judge_can_reproduce():
    from tri_analyze.evals.evaluators import JUDGE_SYSTEM

    assert FeedbackJudgement.model_fields["grounded"].description == GROUNDED
    flat = " ".join(JUDGE_SYSTEM.split())
    for sentence in (
        "can be reproduced from them by a unit conversion or arithmetic within the answer's "
        "rounding",
        "Check each derivation yourself; do not flag a correct one because its arithmetic is "
        "not written out.",
        "must come from the athlete's zones or a stated fraction of a threshold",
        "numbers that do not reproduce (give the value you get)",
        "Use the calendar line to name weekdays; never infer a weekday otherwise.",
    ):
        assert sentence in flat, sentence
    assert "arithmetic the answer shows" not in flat
```

- [ ] **Step 2: Run it and see it fail**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py::test_grounded_accepts_derivations_the_judge_can_reproduce -v`
Expected: FAIL on the description equality.

- [ ] **Step 3: Implement.** Replace the `grounded` field:

```python
    grounded: bool = Field(
        description=(
            "every number in the answer appears in the context or the tool results, or can be "
            "reproduced from them by a unit conversion or arithmetic within the answer's "
            "rounding; a number that appears nowhere or does not reproduce is ungrounded; a "
            "prescribed range must come from the athlete's zones or a stated fraction of a "
            "threshold; missing data is stated as missing"
        )
    )
```

Replace `JUDGE_SYSTEM`:

```python
JUDGE_SYSTEM = """\
You audit one answer a triathlon coach's analyst gave to an athlete. You are given a calendar
line, the analyst's system prompt (the athlete's context, the bound tools and the feedback
rules), the athlete's question, the tool results the analyst received, and the analyst's answer.

Grounded: every number in the answer (durations, distances, watts, paces, heart rates, TSS,
scores, dates) appears in the system prompt's context or in the tool results, or can be
reproduced from them by a unit conversion or arithmetic within the answer's rounding (for
example 5460 s is 91:00, and 132 of 172 bpm is 77%). Check each derivation yourself; do not flag
a correct one because its arithmetic is not written out. A prescribed range (power, HR, pace)
must come from the athlete's zones or a stated fraction of a threshold. List in problems only
numbers that appear nowhere, numbers that do not reproduce (give the value you get), and
prescriptions with no zone or threshold behind them. When the tool results are empty or lack
what the question needs, the answer says so instead of inventing figures.

Dates: the calendar line gives today's weekday and the Monday of each week. Use the calendar
line to name weekdays; never infer a weekday otherwise.

Feedback quality applies to a session review: the five feedback rules are covered, the
athlete's own comments, feeling and RPE are used when the tool results carry them, there are
one or two concrete takeaways for the next similar session, and there is no generic
encouragement. Judge the answer's text literally; return a FeedbackJudgement."""
```

Also update `FeedbackJudgement.problems`' description to `"one line per ungrounded number (with the value you get when it does not reproduce) or missing element"`.

- [ ] **Step 4: Run the file and see it pass**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(evals): grounded means reproducible from the evidence, not shown arithmetic

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `JUDGE_VERSION` in the experiment and the `.evals` rows

**Files:**
- Modify: `packages/tri-core/src/tri_core/evals.py:153-168` (`record_rows`)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py` (constant after the imports)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/run.py:15` (import), `:94-130` (metadata, `record_rows` call)
- Test: `packages/tri-core/tests/test_evals.py`, `packages/tri-analyze/tests/test_evals.py:462-483`

**Interfaces:**
- Produces: `JUDGE_VERSION: str = "2"`; `record_rows(rows, experiment, *, directory=None, metadata: dict[str, Any] | None = None) -> Path`. When `metadata` is given, each line gets a trailing `"metadata"` key; without it the line is unchanged.

- [ ] **Step 1: Write the failing tests.** In `tri-core/tests/test_evals.py` (next to `test_record_rows_writes_one_json_line_per_example`; `_row` is that file's helper):

```python
def test_record_rows_writes_the_experiment_metadata_on_every_line_when_given(tmp_path):
    path = record_rows(
        [_row("z2", []), _row("run", [])], "x", directory=tmp_path, metadata={"judge_version": "2"}
    )
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["metadata"] for line in lines] == [{"judge_version": "2"}] * 2
    bare = record_rows([_row("z2", [])], "y", directory=tmp_path)
    assert "metadata" not in json.loads(bare.read_text())
```

In `tri-analyze/tests/test_evals.py`, add `JUDGE_VERSION` to the `tri_analyze.evals.evaluators` import. Add `"judge_version": JUDGE_VERSION,` to the exact dict in `test_run_eval_uses_the_analyst_and_judge_roles`. In `test_run_eval_without_the_judge_records_no_judge_model`, change the last line to:

```python
    assert roles == [Role.ANALYST] and "judge_model" not in captured["metadata"]
    assert "judge_version" not in captured["metadata"]
```

and append:

```python
async def test_run_eval_records_the_judge_version_in_the_experiment_and_the_results_file(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    captured = _stub_langsmith(monkeypatch, analyze_run)
    row = {
        "run": SimpleNamespace(outputs={"answer": "ok"}, error=None),
        "example": SimpleNamespace(id="e1", inputs={}, metadata={"case": "last_z2_ride"}),
        "evaluation_results": {"results": []},
    }

    class OneRow(_FakeResults):
        def __aiter__(self):
            async def rows():
                yield row

            return rows()

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return OneRow()

    monkeypatch.setattr(analyze_run, "aevaluate", fake_aevaluate)
    models, _ = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, log=lambda m: None)
    assert captured["metadata"]["judge_version"] == JUDGE_VERSION == "2"
    line = json.loads((tmp_path / "exp.jsonl").read_text().splitlines()[0])
    assert line["metadata"] == captured["metadata"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-core/tests/test_evals.py packages/tri-analyze/tests/test_evals.py -k "metadata or judge_version or roles or without_the_judge" -v`
Expected: `ImportError: cannot import name 'JUDGE_VERSION'`, and `TypeError: record_rows() got an unexpected keyword argument 'metadata'`.

- [ ] **Step 3: Implement.** In `tri_core/evals.py`, change `record_rows`'s signature and body:

```python
def record_rows(
    rows: list[dict[str, Any]],
    experiment: str,
    *,
    directory: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Writes `<experiment>.jsonl` under `directory` (default `$TRI_EVAL_DIR`, else `.evals`):
    one line per example with its case, inputs, outputs, error and evaluator results, and the
    experiment's `metadata` when given (so a results file says which prompt and judge scored it)."""
```

After the `line = {...}` dict literal, add:

```python
            if metadata is not None:
                line["metadata"] = metadata
```

In `evaluators.py`, after the imports:

```python
# Bump whenever JUDGE_SYSTEM or FeedbackJudgement's descriptions change; recorded in each
# experiment's metadata and results file, so a pass rate says which judge scored it.
JUDGE_VERSION = "2"
```

In `run.py`, import `JUDGE_VERSION` alongside `make_judge`. Before `seed_database(url)`, build the metadata once:

```python
    metadata: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        **eval_metadata(settings, Role.ANALYST, judge=judge),
    }
    if judge:
        metadata["judge_version"] = JUDGE_VERSION
```

Pass `metadata=metadata` to `aevaluate`, and change the last log line to `log(f"results: {record_rows(dict_rows, experiment, metadata=metadata)}")`.

- [ ] **Step 4: Run both packages and see them pass**

Run: `uv run pytest packages/tri-core packages/tri-analyze -q`
Expected: all pass. `test_record_rows_writes_one_json_line_per_example`'s exact dict still matches, because it passes no metadata.

- [ ] **Step 5: Step-1 checks** (the Definition of Done for step 1)

Run: `uv run pytest -q && uv run ruff format --check . && uv run ruff check . && uv run mypy`
Expected: all pass, with no skips other than `needs --live`. There is no build step for the Python packages; `uv sync --locked` stands in for it:
Run: `uv sync --locked`

- [ ] **Step 6: Commit**

```bash
uv run ruff format packages/tri-analyze packages/tri-core
git add packages/tri-analyze packages/tri-core
git commit -m "feat(evals): JUDGE_VERSION 2 in the experiment metadata and every results row

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Checkpoint: Brian's step-1 run.** Stop here and ask Brian to run:

```bash
uv run tri-analyze eval --local --prefix analyst-v2-judge2
```

(This is the current analyst under judge 2, compared with `.evals/fresh-decision-92.jsonl`, which scored grounded 1/12.) Record the printed pass rates and the `failed checks` block for Task 9. Do not start Task 5 until Brian says the run is done.

---

### Task 5: Weekdays in the analyst's context

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py` (`_days_block` `:86`, `_workouts_block` `:106`, the today line `:132`)
- Test: `packages/tri-analyze/tests/test_prompt.py`, `packages/tri-analyze/tests/test_agent.py:85-86`, `packages/tri-analyze/tests/test_evals.py:315`

**Interfaces:**
- Consumes: `dated`, `calendar_line` (Task 1).
- Produces: the analyst's today line, `Today is 2026-09-16 (Wed). Weeks start Monday: 2026-08-17, …, 2026-09-21.`, day lines `- 2026-09-05 (Sat): TSS 55, …`, and workout lines `- 2026-09-05 (Sat) bike: Z2 ride [done] 60 -> 55`.

- [ ] **Step 1: Update the existing assertions and add one** (the `athlete_context()` today, 2026-09-06, is a Sunday):
  - `test_prompt.py:19`: `assert "Today is 2026-09-06 (Sun). Weeks start Monday: 2026-08-03, 2026-08-10, 2026-08-17, 2026-08-24, 2026-08-31, 2026-09-07." in text`
  - `test_prompt.py:23` and `:64`: `"2026-09-05 (Sat) bike: Z2 ride [done] 60 -> 55"`
  - `test_prompt.py:63`: `"2026-09-04 (Fri) swim: Drills [missed] 30 -> -"`
  - `test_prompt.py:65`: `"2026-09-06 (Sun) run: (untitled) [planned] 40 -> -"`
  - `test_prompt.py:66`: `"2026-09-08 (Tue) run: Tempo [planned] 70 -> -"`
  - add to `test_render_includes_profile_load_and_tools`: `assert "- 2026-09-05 (Sat): TSS 55, CTL 15.2" in text`
  - `test_agent.py:85-86`: `"Today is 2026-09-06 (Sun)."` and `"Today is 2026-09-07 (Mon)."`
  - `test_evals.py:315`: `"Today is 2026-09-16 (Wed)."`

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py packages/tri-analyze/tests/test_agent.py packages/tri-analyze/tests/test_evals.py -q`
Expected: the eight changed assertions FAIL.

- [ ] **Step 3: Implement** (in `analyst.py`):
  - `_days_block`: `f"- {d['metric_date']}: TSS …"` → `f"- {dated(d['metric_date'])}: TSS …"`
  - `_workouts_block`: `f"- {w['workout_date']} {w['sport']}: …"` → `f"- {dated(w['workout_date'])} {w['sport']}: …"`
  - `render_system_prompt`: `f"Today is {ctx.today.isoformat()}."` → `f"Today is {dated(ctx.today)}. {calendar_line(ctx.today)}"`

- [ ] **Step 4: Run the package and see it pass**

Run: `uv run pytest packages/tri-analyze -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyze): weekdays on every context date and the week starts on the today line

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The zones block and `load_athlete_context` zones

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py` (new zone helpers and `_zones_block`; `render_system_prompt` puts the block after `_profile_block`)
- Modify: `packages/tri-analyze/src/tri_analyze/repo.py:23-25` (profile select)
- Test: `packages/tri-analyze/tests/test_prompt.py`, `packages/tri-analyze/tests/test_repo.py`

**Interfaces:**
- Consumes: the existing `_pace(sec, unit)`.
- Produces: `_zones_block(p: dict[str, Any] | None) -> str`, which reads `p["power_zones"]`, `p["hr_zones"]` and `p["pace_zones"]` (TrainingPeaks group lists, any of them possibly missing or None). `load_athlete_context(...).profile` gains the keys `hr_zones`, `power_zones` and `pace_zones`.

The fixture's expected strings below were computed by hand from `tp_get_athlete_settings.json`, as pace = round(metres / speed). If a test disagrees, recompute from the fixture before changing code.

- [ ] **Step 1: Write the failing tests** (append to `test_prompt.py`; add `import json`, `from pathlib import Path`, and `_zones_block` to the analyst import)

```python
TP_SETTINGS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "tri-core/tests/fixtures/mcp/tp_get_athlete_settings.json"
    ).read_text()
)["result"]["settings"]


def _tp_zones(**over):
    return {
        "hr_zones": TP_SETTINGS["heartRateZones"],
        "power_zones": TP_SETTINGS["powerZones"],
        "pace_zones": TP_SETTINGS["speedZones"],
        **over,
    }


def test_zones_block_renders_the_synced_groups():
    block = _zones_block(_tp_zones())
    assert block.splitlines() == [
        "Athlete zones (from TrainingPeaks):",
        "- Bike power: Z1 0-135 W, Z2 136-184 W, Z3 185-220 W, Z4 221-257 W, Z5 258+ W",
        "- Run HR: Z1 117-152 bpm, Z2 153-161 bpm, Z3 162-170 bpm, Z4 171-179 bpm, Z5 180+ bpm",
        "- Bike HR: Z1 89-110 bpm, Z2 111-135 bpm, Z3 136-152 bpm, Z4 153-170 bpm, Z5 171+ bpm",
        "- Run pace: Z1 6:00-5:38/km, Z2 5:38-5:00/km, Z3 5:00-4:45/km, Z4 4:45-4:30/km, "
        "Z5 faster than 4:30/km",
        "- Swim pace: Z1 2:15-1:59/100m, Z2 1:59-1:49/100m, Z3 1:49-1:46/100m, "
        "Z4 1:46-1:40/100m, Z5 faster than 1:40/100m",
    ]


def test_zones_block_falls_back_to_the_default_groups_and_keeps_names():
    hr0 = [g for g in TP_SETTINGS["heartRateZones"] if g["workoutTypeId"] == 0]
    power0 = [g for g in TP_SETTINGS["powerZones"] if g["workoutTypeId"] == 0]
    block = _zones_block({"hr_zones": hr0, "power_zones": power0, "pace_zones": None})
    assert "- Bike power: Z1 0-102 W, Z2 103-139 W," in block
    assert "- Run HR: Z1 Recovery 0-126 bpm, Z2 Aerobic 127-141 bpm," in block
    assert "Z5A SuperThreshold 158-161 bpm" in block and "Z5C Anaerobic Capacity 169+ bpm" in block
    assert "Bike HR" not in block and "pace" not in block


def test_bike_hr_is_left_out_when_it_equals_run_hr():
    run = next(g for g in TP_SETTINGS["heartRateZones"] if g["workoutTypeId"] == 3)
    block = _zones_block(_tp_zones(hr_zones=[run, {**run, "workoutTypeId": 2}]))
    assert "- Run HR:" in block and "Bike HR" not in block


NOT_SYNCED = "Zones: not synced; prescribe only as a stated % of a threshold."


def test_zones_block_says_not_synced_without_zones():
    assert _zones_block(None) == NOT_SYNCED
    assert _zones_block({"ftp_watts": 250}) == NOT_SYNCED
    assert _zones_block({"hr_zones": None, "power_zones": [], "pace_zones": "x"}) == NOT_SYNCED
    assert NOT_SYNCED in render_system_prompt(athlete_context(), [])


@pytest.mark.parametrize(
    "garbled",
    [
        {"workoutTypeId": 2, "zones": None},
        {"workoutTypeId": 2, "zones": "Zone 1"},
        {"workoutTypeId": 2, "zones": []},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": 0}]},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": "0", "maximum": 9}]},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": True, "maximum": 9}]},
        {"workoutTypeId": 2, "zones": ["Zone 1"]},
        "not a group",
    ],
)
def test_a_garbled_group_is_skipped(garbled):
    assert _zones_block({"power_zones": [garbled]}) == NOT_SYNCED
    power0 = next(g for g in TP_SETTINGS["powerZones"] if g["workoutTypeId"] == 0)
    assert "- Bike power: Z1 0-102 W" in _zones_block({"power_zones": [garbled, power0]})


def test_a_zero_speed_bound_skips_the_pace_group():
    run = next(g for g in TP_SETTINGS["speedZones"] if g["workoutTypeId"] == 3)
    broken = {**run, "zones": [{"label": "Zone 1", "minimum": 0, "maximum": 0}]}
    assert _zones_block({"pace_zones": [broken]}) == NOT_SYNCED


def test_render_puts_the_zones_after_the_thresholds():
    profile = {**athlete_context().profile, **_tp_zones()}
    text = render_system_prompt(athlete_context(profile=profile), [])
    assert text.index("Athlete thresholds") < text.index("Athlete zones") < text.index(
        "Recent load"
    )
```

Also add `import pytest` to `test_prompt.py`. In `test_repo.py`, add `import json` and `from pathlib import Path`, and append:

```python
@pytest.mark.db
def test_load_athlete_context_reads_the_zone_groups(db):
    settings = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "tri-core/tests/fixtures/mcp/tp_get_athlete_settings.json"
        ).read_text()
    )["result"]["settings"]
    repo.upsert_athlete_profile(
        db,
        AthleteProfileRow(
            tp_athlete_id="1",
            ftp_watts=230,
            run_threshold_pace_sec_per_km=270,
            swim_css_sec_per_100m=104,
            lthr_bpm=180,
            max_hr_bpm=182,
            hr_zones=settings["heartRateZones"],
            power_zones=settings["powerZones"],
            pace_zones=settings["speedZones"],
            weight_kg=70.5,
            raw={},
        ),
    )
    profile = load_athlete_context(db, TODAY).profile
    assert profile is not None
    assert profile["hr_zones"] == settings["heartRateZones"]
    assert profile["power_zones"] == settings["powerZones"]
    assert profile["pace_zones"] == settings["speedZones"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py packages/tri-analyze/tests/test_repo.py -q`
Expected: `ImportError: cannot import name '_zones_block'`; the repo test fails on `KeyError: 'hr_zones'`, or skips if Postgres is down. It must run before the commit: start Postgres if needed.

- [ ] **Step 3: Implement.** In `repo.py`, the profile select becomes:

```python
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, weight_kg, hr_zones, power_zones, pace_zones from athlete_profile "
        "where id = 1"
```

In `analyst.py`, add `import re`, then after `_profile_block`:

```python
# TrainingPeaks zone groups are keyed by workoutTypeId: 1 swim, 2 bike, 3 run (0 = default).
_DEFAULT, _SWIM, _BIKE, _RUN = 0, 1, 2, 3
_ZONE_LABEL = re.compile(r"Zone\s+(\w+)(?:\s*:\s*(.*))?")
NO_ZONES = "Zones: not synced; prescribe only as a stated % of a threshold."

Zone = tuple[str, float, float]  # name, minimum, maximum


def _zone_name(label: Any, n: int) -> str:
    """`Zone 2: Aerobic` -> `Z2 Aerobic`, `Zone 5A` -> `Z5A`; anything else is `Z<position>`."""
    m = _ZONE_LABEL.fullmatch(str(label or "").strip())
    if not m:
        return f"Z{n}"
    return f"Z{m.group(1)} {m.group(2).strip()}" if m.group(2) else f"Z{m.group(1)}"


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _zones(group: Any) -> list[Zone] | None:
    """A group's zones sorted slow to fast, or None when the group or any zone is garbled."""
    zs = group.get("zones") if isinstance(group, dict) else None
    if not isinstance(zs, list) or not zs:
        return None
    out: list[Zone] = []
    for n, z in enumerate(zs, 1):
        if not isinstance(z, dict) or not (_is_num(z.get("minimum")) and _is_num(z.get("maximum"))):
            return None
        out.append((_zone_name(z.get("label"), n), float(z["minimum"]), float(z["maximum"])))
    return sorted(out, key=lambda z: z[1])


def _pick(groups: Any, *types: int) -> list[Zone] | None:
    """The first well-formed group for each workoutTypeId in turn."""
    if not isinstance(groups, list):
        return None
    for t in types:
        for g in groups:
            if isinstance(g, dict) and g.get("workoutTypeId") == t:
                zones = _zones(g)
                if zones:
                    return zones
    return None


def _numeric_zones(zones: list[Zone], unit: str) -> str:
    last = len(zones) - 1
    return ", ".join(
        f"{name} {round(lo)}+ {unit}" if i == last else f"{name} {round(lo)}-{round(hi)} {unit}"
        for i, (name, lo, hi) in enumerate(zones)
    )


def _pace_zones(zones: list[Zone] | None, metres: int, unit: str) -> str | None:
    """Speed zones (m/s) as min:ss per `metres`, slowest first; None if a bound is unusable."""
    if not zones or any(hi <= 0 for _, _, hi in zones):
        return None
    last = len(zones) - 1
    parts: list[str] = []
    for i, (name, lo, hi) in enumerate(zones):
        if lo <= 0:
            parts.append(f"{name} slower than {_pace(round(metres / hi), unit)}")
        elif i == last:
            parts.append(f"{name} faster than {_pace(round(metres / lo), unit)}")
        else:
            slow, fast = round(metres / lo), round(metres / hi)
            parts.append(f"{name} {_pace(slow, '')}-{_pace(fast, unit)}")
    return ", ".join(parts)


def _zones_block(p: dict[str, Any] | None) -> str:
    """Bike power, run HR, bike HR (when it differs), run and swim pace, from the synced
    TrainingPeaks groups. Garbled groups are skipped; with none left, the not-synced line."""
    p = p or {}
    lines: list[str] = []
    power = _pick(p.get("power_zones"), _BIKE, _DEFAULT)
    if power:
        lines.append(f"- Bike power: {_numeric_zones(power, 'W')}")
    run_hr = _pick(p.get("hr_zones"), _RUN, _DEFAULT)
    if run_hr:
        lines.append(f"- Run HR: {_numeric_zones(run_hr, 'bpm')}")
    bike_hr = _pick(p.get("hr_zones"), _BIKE)
    if bike_hr and bike_hr != run_hr:
        lines.append(f"- Bike HR: {_numeric_zones(bike_hr, 'bpm')}")
    run_pace = _pace_zones(_pick(p.get("pace_zones"), _RUN), 1000, "/km")
    if run_pace:
        lines.append(f"- Run pace: {run_pace}")
    swim_pace = _pace_zones(_pick(p.get("pace_zones"), _SWIM), 100, "/100m")
    if swim_pace:
        lines.append(f"- Swim pace: {swim_pace}")
    if not lines:
        return NO_ZONES
    return "Athlete zones (from TrainingPeaks):\n" + "\n".join(lines)
```

In `render_system_prompt`'s list, add `_zones_block(ctx.profile),` directly after `_profile_block(ctx.profile),`.

Note: a garbled run pace group is `_pick`'d as None only when `_zones` rejects it. A group that parses but has a zero `maximum` is rejected by `_pace_zones` and not replaced, since pace has no fallback group. That is what `test_a_zero_speed_bound_skips_the_pace_group` pins.

- [ ] **Step 4: Run the package and see it pass**

Run: `uv run pytest packages/tri-analyze -q`
Expected: all pass, and `test_load_athlete_context_reads_the_zone_groups` runs (not skipped).

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyze): the athlete's power, HR and pace zones in the analyst's context

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Rules and `PROMPT_VERSION` 3

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/prompts/analyst.py:13` and `:37-51` (`FEEDBACK_RULES`)
- Test: `packages/tri-analyze/tests/test_prompt.py:126-143`

**Interfaces:**
- Produces: `PROMPT_VERSION = "3"`; `FEEDBACK_RULES` with a `Numbers:` section.

- [ ] **Step 1: Update the tests.** In `test_render_feedback_rules_present_and_version_is_1`, change `assert PROMPT_VERSION == "2"` to `assert PROMPT_VERSION == "3"`. Replace `test_the_rules_ask_for_shown_arithmetic_and_a_literal_today` with:

```python
RULE_SENTENCES = (
    "Prescriptions: every prescribed range (power, HR, pace) names a zone from the context, or "
    'states a fraction of a threshold together with the result, for example "56-75% of FTP '
    '250 W, 140-188 W". No other ranges.',
    "No invented numbers: no invented thresholds, baselines or cutoffs. A baseline is computed "
    "in SQL over a window you state (for example a 28-day mean HRV), or not given.",
    "SQL for arithmetic: counts, sums, averages, ratios and percentages come from SQL, not "
    "mental arithmetic. Quote the query's numbers.",
    "Weekdays: name a weekday only as the context shows it, or from SQL (to_char(d, 'Dy')).",
)


def test_the_rules_drop_shown_arithmetic_and_keep_a_literal_today():
    flat = " ".join(FEEDBACK_RULES.split())
    for sentence in RULE_SENTENCES:
        assert sentence in flat, sentence
    assert "show the arithmetic" not in FEEDBACK_RULES
    assert "never use current_date" in FEEDBACK_RULES
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_prompt.py -k "rules" -v`
Expected: FAIL.

- [ ] **Step 3: Implement.** Set `PROMPT_VERSION = "3"`. Replace the trend paragraph's last sentence and add the `Numbers:` section, so `FEEDBACK_RULES` ends:

```python
For trend questions: compute with SQL (group by week, averages, sums), state the date window
you used, and say when data is missing rather than guessing. Distances are metres, durations
seconds, paces derive from those. Today is the reference for "this week" and "yesterday"; in
SQL write it as a literal (date 'YYYY-MM-DD'), never use current_date.

Numbers:
- Prescriptions: every prescribed range (power, HR, pace) names a zone from the context, or
  states a fraction of a threshold together with the result, for example "56-75% of FTP 250 W,
  140-188 W". No other ranges.
- No invented numbers: no invented thresholds, baselines or cutoffs. A baseline is computed in
  SQL over a window you state (for example a 28-day mean HRV), or not given.
- SQL for arithmetic: counts, sums, averages, ratios and percentages come from SQL, not mental
  arithmetic. Quote the query's numbers.
- Weekdays: name a weekday only as the context shows it, or from SQL (to_char(d, 'Dy'))."""
```

(Items 1-5 of the session-feedback list are unchanged.)

- [ ] **Step 4: Run the package and see it pass**

Run: `uv run pytest packages/tri-analyze -q`
Expected: all pass. `test_agent.py:121` reads `PROMPT_VERSION` by name, so it follows.

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(analyze): prompt v3 — zone-backed prescriptions, SQL arithmetic, no invented baselines

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Eval profile zones, seeded

**Files:**
- Create: `packages/tri-analyze/src/tri_analyze/evals/zones.py`
- Modify: `packages/tri-analyze/src/tri_analyze/evals/cases.py:20-27` (`PROFILE`)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/seed.py:351-353`
- Test: `packages/tri-analyze/tests/test_seed.py`

**Interfaces:**
- Produces: `power_zones(ftp: int) -> list[dict]`, `hr_zones(lthr: int, max_hr: int) -> list[dict]`, `pace_zones(run_sec_per_km: int, css_sec_per_100m: int) -> list[dict]`. Each returns TrainingPeaks groups (`workoutTypeId`, `threshold`, `zones: [{label, minimum, maximum}]`). `PROFILE` gains `hr_zones`, `power_zones` and `pace_zones`.

- [ ] **Step 1: Write the failing tests** (append to `test_seed.py`; add `from tri_analyze.evals.cases import PROFILE, athlete`, `from tri_analyze.prompts.analyst import _zones_block, render_system_prompt`, `from tri_analyze.repo import load_athlete_context`)

```python
def test_the_eval_profile_carries_zones_built_from_its_thresholds():
    block = _zones_block(PROFILE)
    assert block.splitlines() == [
        "Athlete zones (from TrainingPeaks):",
        "- Bike power: Z1 Active Recovery 0-137 W, Z2 Endurance 138-187 W, Z3 Tempo 188-225 W, "
        "Z4 Threshold 226-262 W, Z5 VO2 Max 263-300 W, Z6 Anaerobic 301+ W",
        "- Run HR: Z1 Recovery 0-146 bpm, Z2 Aerobic 147-153 bpm, Z3 Tempo 154-161 bpm, "
        "Z4 SubThreshold 162-172 bpm, Z5A SuperThreshold 173-177 bpm, "
        "Z5B Aerobic Capacity 178+ bpm",
        "- Run pace: Z1 slower than 5:29/km, Z2 5:29-4:51/km, Z3 4:51-4:30/km, "
        "Z4 4:30-4:15/km, Z5 4:15-4:07/km, Z6 faster than 4:07/km",
        "- Swim pace: Z1 slower than 1:55/100m, Z2 1:55-1:50/100m, Z3 1:50-1:45/100m, "
        "Z4 1:45-1:35/100m, Z5 faster than 1:35/100m",
    ]
    assert "Z2 Endurance 138-187 W" in render_system_prompt(athlete(), ["query_training_db"])


@pytest.mark.db
def test_the_seeded_profile_has_the_eval_profiles_zones():
    url = _url()
    try:
        seed.seed_database(url)
        with connect(url) as conn:
            profile = load_athlete_context(conn, TODAY).profile
        assert profile is not None
        for key in ("hr_zones", "power_zones", "pace_zones"):
            assert profile[key] == PROFILE[key], key
        assert _zones_block(profile) == _zones_block(PROFILE)
    finally:
        seed.clear_database(url)
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest packages/tri-analyze/tests/test_seed.py -k zones -v`
Expected: FAIL. The pure test gets the not-synced line; the DB test gets `KeyError: 'hr_zones'`.

- [ ] **Step 3: Implement.** Create `evals/zones.py`:

```python
"""TrainingPeaks-shaped zone groups built from the eval athlete's thresholds, so the analyst's
context (cases.PROFILE) and the seeded athlete_profile row carry the same zones. Power and HR
bounds are integer: zone n ends at floor(threshold x cut / 100) and the next starts 1 above.
Speed bounds are m/s; zone 1 starts at 0 and the last ends at 10x its start (TrainingPeaks'
open top)."""

from __future__ import annotations

from typing import Any

_SWIM, _BIKE, _RUN = 1, 2, 3
_COGGAN = (
    "Zone 1: Active Recovery",
    "Zone 2: Endurance",
    "Zone 3: Tempo",
    "Zone 4: Threshold",
    "Zone 5: VO2 Max",
    "Zone 6: Anaerobic",
)
_FRIEL = (
    "Zone 1: Recovery",
    "Zone 2: Aerobic",
    "Zone 3: Tempo",
    "Zone 4: SubThreshold",
    "Zone 5A: SuperThreshold",
    "Zone 5B: Aerobic Capacity",
)


def _cut(threshold: int, cuts: tuple[int, ...], labels: tuple[str, ...], top: int) -> list[Any]:
    ends = [threshold * c // 100 for c in cuts]
    lows, highs = [0, *(e + 1 for e in ends)], [*ends, top]
    return [
        {"label": label, "minimum": lo, "maximum": hi}
        for label, lo, hi in zip(labels, lows, highs, strict=True)
    ]


def _speed(metres: int, bounds_sec: list[float]) -> list[Any]:
    """`bounds_sec`: pace cut-offs in seconds per `metres`, slowest first."""
    speeds = [metres / s for s in bounds_sec]
    lows, highs = [0.0, *speeds], [*speeds, speeds[-1] * 10]
    return [
        {"label": f"Zone {n}", "minimum": lo, "maximum": hi}
        for n, (lo, hi) in enumerate(zip(lows, highs, strict=True), 1)
    ]


def power_zones(ftp: int) -> list[dict[str, Any]]:
    """Coggan: cut-offs at 55/75/90/105/120% of FTP."""
    return [
        {
            "workoutTypeId": _BIKE,
            "threshold": ftp,
            "zones": _cut(ftp, (55, 75, 90, 105, 120), _COGGAN, 2000),
        }
    ]


def hr_zones(lthr: int, max_hr: int) -> list[dict[str, Any]]:
    """Friel run: cut-offs at 85/89/94/100/103% of LTHR."""
    return [
        {
            "workoutTypeId": _RUN,
            "threshold": lthr,
            "maximumHeartRate": max_hr,
            "zones": _cut(lthr, (85, 89, 94, 100, 103), _FRIEL, max_hr),
        }
    ]


def pace_zones(run_sec_per_km: int, css_sec_per_100m: int) -> list[dict[str, Any]]:
    """Run: cut-offs at 129/114/106/100/97% of threshold time. Swim: CSS +15/+10/+5/-5 s."""
    run = [run_sec_per_km * c / 100 for c in (129, 114, 106, 100, 97)]
    swim = [float(css_sec_per_100m + d) for d in (15, 10, 5, -5)]
    return [
        {"workoutTypeId": _RUN, "threshold": 1000 / run_sec_per_km, "zones": _speed(1000, run)},
        {"workoutTypeId": _SWIM, "threshold": 100 / css_sec_per_100m, "zones": _speed(100, swim)},
    ]
```

In `cases.py`, add `from tri_analyze.evals.zones import hr_zones, pace_zones, power_zones` and make `PROFILE`:

```python
PROFILE: dict[str, Any] = {
    "ftp_watts": 250,
    "run_threshold_pace_sec_per_km": 255,
    "swim_css_sec_per_100m": 100,
    "lthr_bpm": 172,
    "max_hr_bpm": 188,
    "weight_kg": 74.0,
    "hr_zones": hr_zones(172, 188),
    "power_zones": power_zones(250),
    "pace_zones": pace_zones(255, 100),
}
```

In `seed.py:351-353`:

```python
                hr_zones=PROFILE["hr_zones"],
                power_zones=PROFILE["power_zones"],
                pace_zones=PROFILE["pace_zones"],
```

- [ ] **Step 4: Run the package and see it pass**

Run: `uv run pytest packages/tri-analyze -q`
Expected: all pass, and both new seed tests run (not skipped). `test_athlete_round_trips_through_inputs` still passes, since the zone lists are JSON-safe.

- [ ] **Step 5: Full checks** (Definition of Done)

Run: `uv run pytest -q -rs && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv sync --locked`
Expected: all pass, with no SKIPPED line other than `needs --live`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format packages/tri-analyze
git add packages/tri-analyze
git commit -m "feat(evals): the eval athlete has TrainingPeaks-shaped zones, in context and seeded

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Checkpoint: Brian's step-2 run.** Stop and ask Brian to run:

```bash
uv run tri-analyze eval --local --prefix analyst-v3-judge2
```

A non-local run needs `--recreate`, because the cases' inputs changed (zones in the profile).

---

### Task 9: Run notes

**Files:**
- Create: `docs/notes/2026-09-28-analyst-grounding-runs.md`
- Copy to: `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/docs/notes/2026-09-28-analyst-grounding-runs.md`

- [ ] **Step 1: Write the notes** from the two results files (`.evals/analyst-v2-judge2-local-*.jsonl`, `.evals/analyst-v3-judge2-local-*.jsonl`) and the pass-rate blocks Brian's runs printed. Structure:
  - Baseline: `fresh-decision-92`, grounded 1/12, and its other rates.
  - Step 1 (judge 2, prompt 2): the pass-rate block verbatim, then the `failed checks` lines verbatim.
  - Step 2 (judge 2, prompt 3): the same.
  - Two or three sentences naming what moved and what still fails. Quote the judge's `problems` lines; don't paraphrase them.

- [ ] **Step 2: Copy it to the vault** and commit:

```bash
mkdir -p /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/docs/notes
cp docs/notes/2026-09-28-analyst-grounding-runs.md /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/docs/notes/
git add docs/notes/2026-09-28-analyst-grounding-runs.md
git commit -m "docs(notes): analyst grounding — judge 2 and prompt 3 local runs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3:** Hand off to superpowers:finishing-a-development-branch. Do not push without Brian's approval.
