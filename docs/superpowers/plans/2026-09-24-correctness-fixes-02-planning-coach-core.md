# Correctness fixes Plan 2 of 2: planning, coach, core, analyze and web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the planning, coach, core, analyst and web defects from the correctness-fixes spec.

**Architecture:** Every task is one spec row from `docs/superpowers/specs/2026-09-24-correctness-fixes-design.md` §2: a failing test that shows the defect, the smallest change that makes it pass, a commit. Nothing is refactored beyond the row. Plan 02 covers §2.3 (tri-planning), §2.5 (tri-coach), §2.4 (tri-core) and §2.6 (tri-analyze, tri-web); plan 01 covers wellness, nutrition and the migration. Task 2 here needs `training_goals.tp_plan_applied_at` from migration 006, which plan 01 writes.

**Tech Stack:** Python 3.12, uv workspace, LangChain 1.4 / LangGraph, langchain-anthropic 1.7.1, pydantic 2, psycopg 3 on Postgres 16, pytest with pytest-asyncio in auto mode, `tri_core.testing.ScriptedChatModel`, Vitest and Playwright for `web/`.

**Spec:** `docs/superpowers/specs/2026-09-24-correctness-fixes-design.md`. This plan implements §2.3, §2.4, §2.5 and §2.6. Plan 01 (`2026-09-24-correctness-fixes-01-wellness-nutrition.md`) implements §2.1, §2.2 and the migration.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-fixes-02 -b feat/fixes-02 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout. Plan 01 must be merged first: `test -f migrations/006_fixes.sql` on `main` prints nothing and exits 0.
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
  7. `npm --prefix web run lint && npm --prefix web test && npm --prefix web run build` (the two web tasks only)

  The only acceptable pytest warning is the existing langsmith `DeprecationWarning`. `ruff check --fix` may reorder imports; accept its order. Never add `# type: ignore`.
- **Commits:** git commits are permitted (Brian's standing permission). Commit once per task on `feat/fixes-02`, ending every message with the executing model's attribution line (the `Co-Authored-By:` line the session's git attribution reminder gives).
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file edited is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Stop conditions

Stop and report to Brian without working around it if:
- a "replace" block does not match the current file;
- an existing assertion outside the tests a task names fails;
- a task needs a migration column this plan does not write.

---

## Tasks

1. P1 + P3, review node: reject on a bought plan ends clean; designed-week violations reach the review and `check-in --yes`
2. P2 + P5, targets node: an empty adoption ends the run and is never re-proposed; adoption owns only the workouts the plan added
3. P4, apply marks only designed weeks as written
4. P6, recent weekly TSS scales the days present
5. P7, the design window starts at the first plan week
6. P8, peak gets recovery weeks and the recovery count resets at a phase change
7. P9, validation against the target week; distance steps and a missing week are violations
8. review de-duplicates repeated proposal ids
9. agent tools tag their run; the REPL labels ask_wellness as wellness
10. the apply report lists each applied change
11. proposal ids continue across an apply within a turn
12. C1 a failing `initialize` leaks the subprocess
13. C2 `Decimal` returned as a string
14. C3 the SQL tool caps rows, not bytes
15. C4 Garmin readiness keeps the day's highest score
16. C5 the sync runner's `except` path can raise on a dead connection
17. A1 a bare `/` raises `IndexError`
18. A2 `states_window` matches "decoupling 5%"
19. B1 a turn during a paused review drops the review
20. B2 500 bodies carry the exception text
21. Final checks

---

### Task 1: P1 + P3, review node: reject on a bought plan ends clean; designed-week violations reach the review and `check-in --yes`

P1 and P3 both change `review_node`, so they are one task.

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/state.py:17-27`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/adjust.py:31-62,81-98`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/review.py:19-37`
- Modify: `packages/tri-planning/src/tri_planning/repl.py:41-44,163-167`
- Modify: `packages/tri-planning/src/tri_planning/checkin.py:3-4,9-17,33-39,52-68`
- Test: `packages/tri-planning/tests/test_graph.py` (append)
- Test: `packages/tri-planning/tests/test_adjust_node.py` (edit + append)
- Test: `packages/tri-planning/tests/test_graph_adjust.py` (append)
- Test: `packages/tri-planning/tests/test_checkin.py` (append)
- Test: `packages/tri-planning/tests/test_repl.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `PlanningState.pending_violations: dict[str, list[str]]` (week_start ISO date -> validator violations; only weeks that have any).
  - `changes_from_messages(messages) -> tuple[list[CalendarChange], str | None, dict[str, list[str]]]`.
  - The review interrupt payload and the `/pending` payload gain `"violations": dict[str, list[str]]`; `render_changes` prints them under the summary as `violations, week of <date>: <v1>; <v2>`.
  - `tri_planning.checkin.changes_without_violations(payload) -> tuple[list[CalendarChange], list[str]]`; `run_checkin` with `yes=True` resumes with `{"action": "edit", "changes": [...]}` holding only changes outside violating weeks when any week has violations (otherwise `{"action": "approve"}` as today), prints `check-in: skipping week of <date>: <reasons>` per week, and returns `EXIT_ERROR` (1) when any week was skipped.
  - `review_node` on `reject` with `changes_from` not in `("design", "adjust")` also sets `pending_changes: []` and `pending_summary: None`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-planning/tests/test_graph.py` (all names used are already imported there):

```python
async def test_reject_on_a_bought_plan_ends_clean_and_the_next_message_reaches_adjust(
    nocommit, make_deps
):
    args = {**GOAL_ARGS, "tp_plan_id": "p1"}
    model = ScriptedChatModel(
        script=[
            tool_call("set_training_goal", args),
            AIMessage(content="Goal saved."),
            AIMessage(content="All on track."),
        ]
    )
    tp = FakeTp()
    graph = build_graph(make_deps(model, tp=tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("use my bought plan p1")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][-1]["op"] == "apply_plan"
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "not yet"}), CFG)
    assert "__interrupt__" not in out and out["pending_changes"] == []
    assert (await graph.aget_state(CFG)).next == ()
    # The athlete gets a plan on the calendar another way; the next message must reach the
    # adjust sub-agent, not the stale review.
    gid = repo.get_active_goal(nocommit).id
    pid = repo.insert_plan(
        nocommit,
        gid,
        "generated",
        None,
        [WeekTarget(week_start=MONDAY, phase="base", target_tss=300, target_hours=6)],
    )
    repo.mark_weeks_written(nocommit, pid, [MONDAY])
    out = await graph.ainvoke({"messages": [HumanMessage("how's it going")]}, CFG)
    assert "__interrupt__" not in out and out["messages"][-1].content == "All on track."
    assert "tp_apply_training_plan" not in [c[0] for c in tp.calls]
```

In `packages/tri-planning/tests/test_adjust_node.py`, replace the two helpers (lines 52-81):

```python
def design_result(week_start="2026-09-21", title="S"):
    return {
        "week_start": week_start,
        "coach_note": "n",
        "violations": [],
        "changes": [
```

with:

```python
def design_result(week_start="2026-09-21", title="S", violations=()):
    return {
        "week_start": week_start,
        "coach_note": "n",
        "violations": list(violations),
        "changes": [
```

and:

```python
def design_message(week_start="2026-09-21", title="S", call_id="1"):
    return ToolMessage(
        content=json.dumps(design_result(week_start, title)),
```

with:

```python
def design_message(week_start="2026-09-21", title="S", call_id="1", violations=()):
    return ToolMessage(
        content=json.dumps(design_result(week_start, title, violations)),
```

Replace (lines 96-98):

```python
    changes, summary = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"] and summary == "lighter"
    assert changes_from_messages([AIMessage(content="no changes")]) == ([], None)
```

with:

```python
    changes, summary, violations = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"] and summary == "lighter"
    assert violations == {}
    assert changes_from_messages([AIMessage(content="no changes")]) == ([], None, {})
```

Replace (lines 108-109):

```python
    changes, summary = changes_from_messages(msgs)
    assert [c.workout.title for c in changes] == ["second try", "week after"]
```

with:

```python
    changes, summary, _ = changes_from_messages(msgs)
    assert [c.workout.title for c in changes] == ["second try", "week after"]
```

Replace (lines 124-126):

```python
    changes, summary = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"]
    assert summary is not None and "2026-09-21" in summary
```

with:

```python
    changes, summary, _ = changes_from_messages(msgs)
    assert [c.op for c in changes] == ["create", "delete"]
    assert summary is not None and "2026-09-21" in summary
```

Replace (lines 142-143, in `test_turn_without_proposal_clears_pending_changes`):

```python
    assert out["pending_changes"] == [] and out["changes_from"] is None
    assert out["pending_summary"] is None and out["review_decision"] is None
```

with:

```python
    assert out["pending_changes"] == [] and out["changes_from"] is None
    assert out["pending_summary"] is None and out["review_decision"] is None
    assert out["pending_violations"] == {}
```

Append to the same file:

```python
def test_changes_from_messages_keys_violations_by_week_and_drops_them_on_redesign():
    msgs = [
        design_message(violations=["hard sessions on consecutive days"], call_id="1"),
        design_message(week_start="2026-09-28", title="clean", call_id="2"),
        AIMessage(content="done"),
    ]
    _, _, violations = changes_from_messages(msgs)
    assert violations == {"2026-09-21": ["hard sessions on consecutive days"]}
    redesigned = [*msgs[:1], design_message(title="second try", call_id="3")]
    assert changes_from_messages(redesigned)[2] == {}


async def test_design_violations_become_pending_violations(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    bad = week_json(
        MONDAY + timedelta(weeks=1), targets[1].target_tss, hard_on_consecutive_days=True
    )
    model = ScriptedChatModel(
        script=[
            tool_call("design_next_week", {}),
            tool_call("PlannedWeek", bad),
            tool_call("PlannedWeek", bad),  # the retry is as bad
            AIMessage(content="Next week designed."),
        ]
    )
    node = make_adjust_node(
        make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3), horizon=3)
    )
    out = await node(
        {"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage("check in")]},
        CFG,
    )
    assert list(out["pending_violations"]) == ["2026-09-21"]
    assert any("consecutive" in v for v in out["pending_violations"]["2026-09-21"])
    assert len(out["pending_changes"]) == 3
```

In `packages/tri-planning/tests/test_graph_adjust.py`, replace the import line:

```python
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp
```

with:

```python
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json
```

and append:

```python
async def test_review_payload_carries_the_designed_weeks_violations(nocommit, make_deps):
    seed_active(nocommit)
    bad = week_json(MONDAY + timedelta(weeks=1), 300, hard_on_consecutive_days=True)
    model = ScriptedChatModel(
        script=[
            tool_call("design_next_week", {}),
            tool_call("PlannedWeek", bad),
            tool_call("PlannedWeek", bad),
            AIMessage(content="Next week designed."),
        ]
    )
    graph = build_graph(
        make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=1), horizon=3),
        InMemorySaver(),
    )
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    payload = out["__interrupt__"][0].value
    assert list(payload["violations"]) == ["2026-09-21"]
    assert "consecutive" in payload["violations"]["2026-09-21"][0]
```

Append to `packages/tri-planning/tests/test_checkin.py`:

```python
VIOLATING = (
    (),
    "updates",
    {
        "__interrupt__": (
            Interrupt(
                value={
                    "summary": "s",
                    "changes": [
                        {"op": "create", "workout_date": "2026-09-22", "reason": "next week"},
                        {"op": "delete", "tp_workout_id": "w1", "reason": "sick"},
                    ],
                    "violations": {"2026-09-21": ["hard sessions on consecutive days"]},
                    "last_error": None,
                }
            ),
        )
    },
)


async def test_checkin_yes_skips_weeks_with_violations_and_exits_one():
    g = StubGraph([[VIOLATING], [APPLIED]])
    buf = []
    assert await run_checkin(g, phase="active", yes=True, out=buf.append) == 1
    resume = g.inputs[1].resume
    assert resume["action"] == "edit" and [c["op"] for c in resume["changes"]] == ["delete"]
    text = "".join(buf)
    assert "skipping week of 2026-09-21: hard sessions on consecutive days" in text
```

Append to `packages/tri-planning/tests/test_repl.py`:

```python
def test_render_changes_prints_violations_under_the_summary():
    payload = {
        "summary": "week one",
        "changes": [change().model_dump(mode="json")],
        "violations": {"2026-09-14": ["hard sessions on consecutive days"]},
        "last_error": None,
    }
    text = render_changes(payload)
    line = "violations, week of 2026-09-14: hard sessions on consecutive days"
    assert text.index("week one") < text.index(line) < text.index("Ride")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_graph.py packages/tri-planning/tests/test_adjust_node.py packages/tri-planning/tests/test_graph_adjust.py packages/tri-planning/tests/test_checkin.py packages/tri-planning/tests/test_repl.py -v`
Expected: `test_reject_on_a_bought_plan_...` fails at `out["pending_changes"] == []` (the apply_plan change is still pending); the three edited `changes_from_messages` tests fail with `ValueError: too many values to unpack` / `not enough values to unpack`; `test_turn_without_proposal_...` and `test_design_violations_...` fail with `KeyError: 'pending_violations'`; `test_review_payload_...` fails with `KeyError: 'violations'`; `test_checkin_yes_skips_...` fails with `assert 0 == 1`; `test_render_changes_prints_violations_...` fails with `ValueError: substring not found`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/graph/state.py`, replace:

```python
    pending_changes: list[CalendarChange]
    pending_summary: str | None
```

with:

```python
    pending_changes: list[CalendarChange]
    pending_summary: str | None
    pending_violations: dict[str, list[str]]  # week_start ISO -> validator violations
```

In `packages/tri-planning/src/tri_planning/graph/nodes/adjust.py`, replace:

```python
def changes_from_messages(
    messages: Sequence[AnyMessage],
) -> tuple[list[CalendarChange], str | None]:
    """Changes from the last `propose_calendar_changes` result plus the last `design_next_week`
    result per week, in week order of first appearance; the proposal's summary, or a generated
    one when only designed weeks were added.

    A week designed twice in one turn would otherwise be created twice, so a repeat replaces
    the earlier result instead of adding to it.
    """
    designed: dict[str, list[CalendarChange]] = {}
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
            designed[str(data.get("week_start"))] = changes
        elif msg.name == "propose_calendar_changes":
            proposed = changes
            summary = data.get("summary") or None
    designed_weeks = list(designed)
    all_changes = [c for week in designed_weeks for c in designed[week]] + proposed
    if summary is None and designed_weeks:
        summary = (
            "Designed week(s) " + ", ".join(designed_weeks) + " added to the calendar proposal."
        )
    return all_changes, summary
```

with:

```python
def changes_from_messages(
    messages: Sequence[AnyMessage],
) -> tuple[list[CalendarChange], str | None, dict[str, list[str]]]:
    """Changes from the last `propose_calendar_changes` result plus the last `design_next_week`
    result per week, in week order of first appearance; the proposal's summary, or a generated
    one when only designed weeks were added; and the validator violations of each designed
    week that has any, keyed by week_start ISO date.

    A week designed twice in one turn would otherwise be created twice, so a repeat replaces
    the earlier result (and its violations) instead of adding to it.
    """
    designed: dict[str, list[CalendarChange]] = {}
    violations: dict[str, list[str]] = {}
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
            week = str(data.get("week_start"))
            designed[week] = changes
            violations.pop(week, None)
            if data.get("violations"):
                violations[week] = [str(v) for v in data["violations"]]
        elif msg.name == "propose_calendar_changes":
            proposed = changes
            summary = data.get("summary") or None
    designed_weeks = list(designed)
    all_changes = [c for week in designed_weeks for c in designed[week]] + proposed
    if summary is None and designed_weeks:
        summary = (
            "Designed week(s) " + ", ".join(designed_weeks) + " added to the calendar proposal."
        )
    return all_changes, summary, violations
```

and replace:

```python
        changes, summary = changes_from_messages(new)
        if changes:
            return {
                "messages": new,
                "pending_changes": changes,
                "pending_summary": summary,
                "changes_from": "adjust",
                "review_decision": None,
            }
        # adjust is entered with either no pending changes or its own rejected proposal;
        # a turn that proposes nothing must clear that proposal so it isn't re-reviewed.
        return {
            "messages": new,
            "pending_changes": [],
            "pending_summary": None,
            "changes_from": None,
            "review_decision": None,
        }
```

with:

```python
        changes, summary, violations = changes_from_messages(new)
        if changes:
            return {
                "messages": new,
                "pending_changes": changes,
                "pending_summary": summary,
                "pending_violations": violations,
                "changes_from": "adjust",
                "review_decision": None,
            }
        # adjust is entered with either no pending changes or its own rejected proposal;
        # a turn that proposes nothing must clear that proposal so it isn't re-reviewed.
        return {
            "messages": new,
            "pending_changes": [],
            "pending_summary": None,
            "pending_violations": {},
            "changes_from": None,
            "review_decision": None,
        }
```

In `packages/tri-planning/src/tri_planning/graph/nodes/review.py`, replace:

```python
    raw = interrupt(
        {
            "summary": state.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in changes],
            "last_error": state.get("last_error"),
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {"review_decision": decision}
    if decision.action == "reject":
        note = decision.note or "no note given"
        update["messages"] = [HumanMessage(f"Plan review rejected: {note}")]
    elif decision.action == "edit" and decision.changes is not None:
```

with:

```python
    raw = interrupt(
        {
            "summary": state.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in changes],
            "violations": state.get("pending_violations") or {},
            "last_error": state.get("last_error"),
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {"review_decision": decision}
    if decision.action == "reject":
        note = decision.note or "no note given"
        update["messages"] = [HumanMessage(f"Plan review rejected: {note}")]
        if state.get("changes_from") not in ("design", "adjust"):
            # Nothing re-proposes after this reject; the set must not linger for route_start.
            update["pending_changes"] = []
            update["pending_summary"] = None
    elif decision.action == "edit" and decision.changes is not None:
```

In `packages/tri-planning/src/tri_planning/repl.py`, replace:

```python
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
```

with:

```python
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    violations: dict[str, list[str]] = payload.get("violations") or {}
    for week in sorted(violations):
        lines.append(f"violations, week of {week}: " + "; ".join(violations[week]))
    if violations:
        lines.append("")
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
```

and replace:

```python
                    pending = {
                        "summary": snap.values.get("pending_summary") or "",
                        "changes": [c.model_dump(mode="json") for c in changes],
                        "last_error": snap.values.get("last_error"),
                    }
```

with:

```python
                    pending = {
                        "summary": snap.values.get("pending_summary") or "",
                        "changes": [c.model_dump(mode="json") for c in changes],
                        "violations": snap.values.get("pending_violations") or {},
                        "last_error": snap.values.get("last_error"),
                    }
```

In `packages/tri-planning/src/tri_planning/checkin.py`, replace:

```python
Exit codes: 0 applied or nothing to do, 1 model/API error or apply failure, 2 no active plan,
3 paused at review.
```

with:

```python
Exit codes: 0 applied or nothing to do, 1 model/API error, apply failure, or a week skipped
for validator violations under --yes, 2 no active plan, 3 paused at review.
```

replace:

```python
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_planning.prompts.checkin import CHECKIN_PROMPT
from tri_planning.repl import Out, render_changes, run_turn

EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3
```

with:

```python
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.prompts.checkin import CHECKIN_PROMPT
from tri_planning.repl import Out, render_changes, run_turn

EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3


def changes_without_violations(
    payload: dict[str, Any],
) -> tuple[list[CalendarChange], list[str]]:
    """The review payload's changes minus every change dated inside a week that has validator
    violations, and those weeks (ISO Mondays, sorted). A change without a date is kept."""
    violations: dict[str, list[str]] = payload.get("violations") or {}
    kept = [
        c
        for c in (CalendarChange.model_validate(x) for x in payload.get("changes", []))
        if c.workout_date is None or week_monday(c.workout_date).isoformat() not in violations
    ]
    return kept, sorted(violations)
```

replace:

```python
                {
                    "summary": values.get("pending_summary") or "",
                    "changes": [c.model_dump(mode="json") for c in pending],
                    "last_error": values.get("last_error"),
                }
```

with:

```python
                {
                    "summary": values.get("pending_summary") or "",
                    "changes": [c.model_dump(mode="json") for c in pending],
                    "violations": values.get("pending_violations") or {},
                    "last_error": values.get("last_error"),
                }
```

and replace:

```python
    out("check-in: --yes given, approving\n")
    printer = await run_turn(graph, Command(resume={"action": "approve"}), thread_id, out)
    if printer.error is not None:
        return EXIT_ERROR
    if printer.interrupt is not None:
        return EXIT_PAUSED
    # The apply node reports a failed or partial write through state, not an interrupt.
    after = (await graph.aget_state(cfg)).values or {}
    if after.get("last_error") or after.get("pending_changes"):
        reason = after.get("last_error") or "changes still pending"
        out(f"check-in: apply did not complete: {reason}\n")
        return EXIT_ERROR
    return EXIT_OK
```

with:

```python
    kept, skipped = changes_without_violations(printer.interrupt)
    resume: dict[str, Any] = {"action": "approve"}
    if skipped:
        # A designed week that still fails validation is not written unattended: resume with
        # an edit holding the other weeks' changes, and exit 1 so the cron run is noticed.
        for week in skipped:
            reasons = "; ".join(printer.interrupt["violations"][week])
            out(f"check-in: skipping week of {week}: {reasons}\n")
        out(f"check-in: --yes given, approving {len(kept)} change(s) from other weeks\n")
        resume = {"action": "edit", "changes": [c.model_dump(mode="json") for c in kept]}
    else:
        out("check-in: --yes given, approving\n")
    printer = await run_turn(graph, Command(resume=resume), thread_id, out)
    if printer.error is not None:
        return EXIT_ERROR
    if printer.interrupt is not None:
        return EXIT_PAUSED
    # The apply node reports a failed or partial write through state, not an interrupt.
    after = (await graph.aget_state(cfg)).values or {}
    if after.get("last_error") or after.get("pending_changes"):
        reason = after.get("last_error") or "changes still pending"
        out(f"check-in: apply did not complete: {reason}\n")
        return EXIT_ERROR
    return EXIT_ERROR if skipped else EXIT_OK
```

`ReviewDecision` (`planning/models.py:102-105`) already accepts `action="edit"` with `changes: list[CalendarChange] | None`, and `review_node` replaces `pending_changes` with `decision.changes` when it is not `None`; an edit with an empty list therefore clears the set and `apply` reports `applied 0 of 0`, which is the intended outcome when every proposed week has violations.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/graph/state.py packages/tri-planning/src/tri_planning/graph/nodes/adjust.py packages/tri-planning/src/tri_planning/graph/nodes/review.py packages/tri-planning/src/tri_planning/repl.py packages/tri-planning/src/tri_planning/checkin.py packages/tri-planning/tests/test_graph.py packages/tri-planning/tests/test_adjust_node.py packages/tri-planning/tests/test_graph_adjust.py packages/tri-planning/tests/test_checkin.py packages/tri-planning/tests/test_repl.py
git commit -m "fix(planning): reject on a bought plan clears the review; designed-week violations reach review and check-in --yes"
```

---

### Task 2: P2 + P5, targets node: an empty adoption ends the run and is never re-proposed; adoption owns only the workouts the plan added

P2 and P5 both change `targets_node` and `_adopt_tp_plan`, so they are one task.

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/models.py:5,114-118`
- Modify: `packages/tri-planning/src/tri_planning/repo.py:51-69,85-87,231-239`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/targets.py:63-133`
- Modify: `packages/tri-planning/src/tri_planning/graph/graph.py:6,45-50`
- Modify: `packages/tri-planning/src/tri_planning/testing.py:73-78,100-101`
- Test: `packages/tri-planning/tests/test_targets_node.py` (edit + append)
- Test: `packages/tri-planning/tests/test_graph.py` (edit `test_bought_plan_path`)
- Test: `packages/tri-coach/tests/test_graph_apply.py` (edit two assertions; see the note)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - Migration column `training_goals.tp_plan_applied_at timestamptz` (assumed to exist; see the note).
  - `StoredGoal.tp_plan_applied_at: datetime | None = None`.
  - `repo.set_goal_plan_applied(conn, goal_id: int) -> None`; `repo.calendar_before(conn, tp_plan_id: str) -> list[str]`.
  - The `apply_plan` change's payload gains `"calendar_before": list[str]` (planned workout ids in the plan window at proposal time). `to_tp_call` reads only `plan_id` and `start_date`, so nothing new is sent to TrainingPeaks.
  - `after_targets` returns `END` when `plan_id` is absent (and no changes are pending).
  - `FakeTp(listings=[...])`: successive `tp_get_workouts` answers, one list of workouts per call.

**Note for the assembler:** the spec says "records the adoption in `training_goals`"; that table has no column for it, so this task needs `alter table training_goals add column if not exists tp_plan_applied_at timestamptz;` in migration 006. Every tri-planning db test reads `training_goals` through `repo._goal`, so the column must be on the test database before Step 4. The "before" listing is carried in the `apply_plan` payload rather than in state because the coach runs the proposal and the adoption in different checkpoint namespaces of the embedded planning graph (`tri_coach/graph/graph.py:69-74`), so state would not reach the adoption there; `plan_changes` does. Two tri-coach assertions on the exact `tp.calls` sequence change as a result and are edited here, although the section is 2.3.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_targets_node.py`, replace the imports:

```python
import pytest
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.nodes.targets import make_targets_node, weekly_targets_from_workouts
```

with:

```python
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END

from tri_core.testing import ScriptedChatModel
from tri_planning import repo
from tri_planning.graph.graph import after_targets
from tri_planning.graph.nodes.targets import make_targets_node, weekly_targets_from_workouts
```

Replace (lines 44-47, in `test_bought_plan_proposes_apply_plan`):

```python
    assert out["pending_changes"][1].payload == {
        "plan_id": "p1",
        "start_date": MONDAY.isoformat(),
    }
```

with:

```python
    assert out["pending_changes"][1].payload == {
        "plan_id": "p1",
        "start_date": MONDAY.isoformat(),
        "calendar_before": [],
    }
```

Append:

```python
async def test_empty_adoption_ends_the_run_and_is_not_proposed_again(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    tp = FakeTp()  # its tp_get_workouts answers with no workouts
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    state = {"goal_id": gid, "phase": "planning", "tp_plan_applied": True}
    out = await node(state, CFG)
    assert "plan_id" not in out and "p1" in out["messages"][0].content
    assert after_targets({**state, **out}) == END
    assert repo.get_goal(nocommit, gid).tp_plan_applied_at is not None
    # a later run starts from the tables: the plan is on TrainingPeaks, so it is adopted
    # again, never proposed again
    again = await node({"goal_id": gid, "phase": "planning"}, CFG)
    assert "pending_changes" not in again and "plan_id" not in again
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_get_workouts"]


async def test_adoption_owns_only_the_workouts_the_plan_added(nocommit, make_deps):
    gid = stored_goal(nocommit, tp_plan_id="p1")
    mine = {
        "id": "a1",
        "date": (MONDAY + timedelta(days=1)).isoformat(),
        "tss_planned": 30,
        "duration_planned": 0.5,
    }
    added = {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0}
    tp = FakeTp(listings=[[mine], [mine, added]])
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    proposed = await node({"goal_id": gid, "phase": "planning"}, CFG)
    apply_plan = proposed["pending_changes"][-1]
    assert apply_plan.payload["calendar_before"] == ["a1"]
    assert tp.calls[0][1]["workout_filter"] == "planned"
    # the apply node records the change as sent; the adoption reads the listing back from it
    repo.insert_change(
        nocommit, None, "t", apply_plan, tp_workout_id=None, result={"success": True}
    )
    out = await node({"goal_id": gid, "phase": "planning", "tp_plan_applied": True}, CFG)
    assert repo.owned_workout_ids(nocommit, out["plan_id"]) == {"w1"}
    assert [c[0] for c in tp.calls] == ["tp_get_workouts", "tp_get_workouts"]
```

In `packages/tri-planning/tests/test_graph.py`, in `test_bought_plan_path`, replace:

```python
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 2}})
```

with:

```python
    tp = FakeTp(listings=[[], workouts])  # empty before the plan is applied, two after
```

and replace:

```python
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert out["phase"] == "active" and out["plan_id"] is not None
```

with:

```python
    assert [c[0] for c in tp.calls] == [
        "tp_get_workouts",
        "tp_apply_training_plan",
        "tp_get_workouts",
    ]
    assert out["phase"] == "active" and out["plan_id"] is not None
```

In `packages/tri-coach/tests/test_graph_apply.py`, replace (lines 144-145):

```python
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert repo.derive_phase(nocommit)[0] == "active" and out["pending"] is None
```

with:

```python
    assert [c[0] for c in tp.calls] == [
        "tp_get_workouts",  # what was on the calendar before the plan
        "tp_apply_training_plan",
        "tp_get_workouts",
    ]
    assert repo.derive_phase(nocommit)[0] == "active" and out["pending"] is None
```

and replace (lines 150 and 162-163):

```python
    tp = FakeTp(fail_on_call=2)  # tp_apply_training_plan lands; the adopt's read blows up
```

with:

```python
    # the listing and tp_apply_training_plan land; the adopt's read blows up
    tp = FakeTp(fail_on_call=3)
```

and:

```python
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert "boom" in out["last_error"] and "adopt" in out["last_error"]
```

with:

```python
    assert [c[0] for c in tp.calls] == [
        "tp_get_workouts",
        "tp_apply_training_plan",
        "tp_get_workouts",
    ]
    assert "boom" in out["last_error"] and "adopt" in out["last_error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_targets_node.py packages/tri-planning/tests/test_graph.py::test_bought_plan_path packages/tri-coach/tests/test_graph_apply.py -v`
Expected: `test_bought_plan_proposes_apply_plan` fails on the payload (no `calendar_before`); `test_empty_adoption_...` fails with `AttributeError: 'StoredGoal' object has no attribute 'tp_plan_applied_at'` (after `after_targets` returned `"design"`); `test_adoption_owns_only_...` fails with `TypeError: FakeTp.__init__() got an unexpected keyword argument 'listings'`; `test_bought_plan_path` and the two coach tests fail the same way or on the call sequence.

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/planning/models.py`, replace:

```python
from datetime import date
```

with:

```python
from datetime import date, datetime
```

and replace:

```python
class StoredGoal(BaseModel):
    id: int
    goal: TrainingGoal
    status: str
    tp_event_id: str | None = None
```

with:

```python
class StoredGoal(BaseModel):
    id: int
    goal: TrainingGoal
    status: str
    tp_event_id: str | None = None
    tp_plan_applied_at: datetime | None = None  # set once the bought plan is on TrainingPeaks
```

In `packages/tri-planning/src/tri_planning/repo.py`, replace:

```python
        tp_event_id=row["tp_event_id"],
        goal=TrainingGoal(
```

with:

```python
        tp_event_id=row["tp_event_id"],
        tp_plan_applied_at=row["tp_plan_applied_at"],
        goal=TrainingGoal(
```

replace:

```python
def set_goal_event(conn: Conn, goal_id: int, tp_event_id: str) -> None:
    conn.execute("update training_goals set tp_event_id = %s where id = %s", (tp_event_id, goal_id))
```

with:

```python
def set_goal_event(conn: Conn, goal_id: int, tp_event_id: str) -> None:
    conn.execute("update training_goals set tp_event_id = %s where id = %s", (tp_event_id, goal_id))


def set_goal_plan_applied(conn: Conn, goal_id: int) -> None:
    """Record that the goal's bought plan is on TrainingPeaks, so it is never proposed again
    even when the adoption that follows finds nothing to adopt."""
    conn.execute(
        "update training_goals set tp_plan_applied_at = now() where id = %s", (goal_id,)
    )
```

and replace:

```python
    created = {r["tp_workout_id"] for r in rows if r["operation"] in ("create", "apply_plan")}
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    return created - deleted
```

with:

```python
    created = {r["tp_workout_id"] for r in rows if r["operation"] in ("create", "apply_plan")}
    deleted = {r["tp_workout_id"] for r in rows if r["operation"] == "delete"}
    return created - deleted


def calendar_before(conn: Conn, tp_plan_id: str) -> list[str]:
    """Planned workout ids that were on the calendar when the latest apply_plan for
    `tp_plan_id` was proposed (carried in its payload); empty when none was recorded."""
    row = conn.execute(
        "select payload from plan_changes where operation = 'apply_plan' "
        "and payload->'payload'->>'plan_id' = %s order by applied_at desc, id desc limit 1",
        (tp_plan_id,),
    ).fetchone()
    if row is None:
        return []
    inner = row["payload"].get("payload") or {}
    return [str(i) for i in inner.get("calendar_before") or []]
```

In `packages/tri-planning/src/tri_planning/graph/nodes/targets.py`, replace:

```python
def make_targets_node(deps: GraphDeps) -> Any:
    async def _adopt_tp_plan(stored: StoredGoal, thread_id: str) -> dict[str, Any]:
        assert deps.tp is not None and stored.goal.event_date is not None
        start = next_monday(deps.today())
        end = stored.goal.event_date + timedelta(days=7)
        result = await deps.tp.call_json(
            "tp_get_workouts",
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "workout_filter": "planned",
            },
        )
        workouts = list((result or {}).get("workouts", []))
        targets = weekly_targets_from_workouts(workouts, start)
        if not targets:
            return {
                "last_error": "no planned workouts found after applying the TrainingPeaks plan",
                "tp_plan_applied": False,
            }
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "tp_plan", stored.goal.tp_plan_id, targets)
            for w in workouts:
                wid = str(w["id"])
                change = CalendarChange(
```

with:

```python
def make_targets_node(deps: GraphDeps) -> Any:
    async def _planned_workouts(start: date, end: date) -> list[dict[str, Any]]:
        assert deps.tp is not None
        result = await deps.tp.call_json(
            "tp_get_workouts",
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "workout_filter": "planned",
            },
        )
        return list((result or {}).get("workouts", []))

    async def _adopt_tp_plan(stored: StoredGoal, thread_id: str) -> dict[str, Any]:
        assert deps.tp is not None and stored.goal.event_date is not None
        assert stored.goal.tp_plan_id is not None
        with deps.connect() as conn:
            # The plan is on TrainingPeaks whatever the listing finds: never propose it again.
            repo.set_goal_plan_applied(conn, stored.id)
            before = set(repo.calendar_before(conn, stored.goal.tp_plan_id))
            conn.commit()
        start = next_monday(deps.today())
        end = stored.goal.event_date + timedelta(days=7)
        workouts = await _planned_workouts(start, end)
        targets = weekly_targets_from_workouts(workouts, start)
        if not targets:
            return {
                "last_error": "no planned workouts found after applying the TrainingPeaks plan",
                "tp_plan_applied": False,
                "messages": [
                    AIMessage(
                        f"TrainingPeaks plan {stored.goal.tp_plan_id} was applied, but the "
                        f"calendar from {start} has no planned workouts; nothing to adopt. "
                        "Check the plan in TrainingPeaks and send another message to retry."
                    )
                ],
            }
        with deps.connect() as conn:
            plan_id = repo.insert_plan(conn, stored.id, "tp_plan", stored.goal.tp_plan_id, targets)
            for w in workouts:
                wid = str(w["id"])
                if wid in before:
                    continue  # the athlete's own workout; the plan did not add it
                change = CalendarChange(
```

and replace:

```python
        if goal.tp_plan_id:
            if state.get("tp_plan_applied"):
                return await _adopt_tp_plan(stored, thread_id)
            start = next_monday(deps.today())
            changes: list[CalendarChange] = []
            if goal.create_tp_event and stored.tp_event_id is None:
                changes.append(event_change(goal))
            changes.append(
                CalendarChange(
                    op="apply_plan",
                    payload={"plan_id": goal.tp_plan_id, "start_date": start.isoformat()},
                    reason=f"activate TrainingPeaks plan {goal.tp_plan_id} from {start}",
                )
            )
```

with:

```python
        if goal.tp_plan_id:
            if state.get("tp_plan_applied") or stored.tp_plan_applied_at is not None:
                return await _adopt_tp_plan(stored, thread_id)
            start = next_monday(deps.today())
            before: list[str] = []
            if deps.tp is not None and goal.event_date is not None:
                # What is on the calendar now; the adoption owns only what the plan adds.
                listed = await _planned_workouts(start, goal.event_date + timedelta(days=7))
                before = [str(w["id"]) for w in listed]
            changes: list[CalendarChange] = []
            if goal.create_tp_event and stored.tp_event_id is None:
                changes.append(event_change(goal))
            changes.append(
                CalendarChange(
                    op="apply_plan",
                    payload={
                        "plan_id": goal.tp_plan_id,
                        "start_date": start.isoformat(),
                        "calendar_before": before,
                    },
                    reason=f"activate TrainingPeaks plan {goal.tp_plan_id} from {start}",
                )
            )
```

In `packages/tri-planning/src/tri_planning/graph/graph.py`, replace:

```python
targets  -> review (bought plan) | design (generated) | END (bought plan adopted)
```

with:

```python
targets  -> review (bought plan) | design (generated) | END (bought plan adopted, or nothing
            to adopt)
```

and replace:

```python
def after_targets(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("phase") == "active":
        return END
    return "design"
```

with:

```python
def after_targets(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("phase") == "active" or state.get("plan_id") is None:
        # an adoption that found nothing leaves no plan, and there is nothing to design
        return END
    return "design"
```

In `packages/tri-planning/src/tri_planning/testing.py`, replace:

```python
    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call
```

with:

```python
    def __init__(
        self,
        *,
        responses: dict[str, Any] | None = None,
        fail_on_call: int | None = None,
        listings: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call
        # successive tp_get_workouts answers, one list of workouts per call
        self.listings = list(listings) if listings is not None else None
```

and replace:

```python
        if tool == "tp_get_workouts":
            return {"workouts": [], "count": 0}
```

with:

```python
        if tool == "tp_get_workouts":
            if self.listings:
                workouts = self.listings.pop(0)
                return {"workouts": workouts, "count": len(workouts)}
            return {"workouts": [], "count": 0}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests packages/tri-coach/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/planning/models.py packages/tri-planning/src/tri_planning/repo.py packages/tri-planning/src/tri_planning/graph/nodes/targets.py packages/tri-planning/src/tri_planning/graph/graph.py packages/tri-planning/src/tri_planning/testing.py packages/tri-planning/tests/test_targets_node.py packages/tri-planning/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py
git commit -m "fix(planning): empty adoption ends the run and is never re-proposed; adoption owns only the plan's workouts"
```

---

### Task 3: P4, apply marks only designed weeks as written

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/apply.py:130-133`
- Test: `packages/tri-planning/tests/test_apply_node.py` (edit)

**Interfaces:**
- Consumes: nothing new.
- Produces: `apply_changes` marks `written_to_tp` only for weeks that received a `create` and whose `plan_weeks.designed` is not null.

- [ ] **Step 1: Write the failing test**

In `packages/tri-planning/tests/test_apply_node.py`, replace the models import:

```python
from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    TrainingGoal,
    WeekTarget,
)
```

with:

```python
from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    TrainingGoal,
    WeekTarget,
)
```

and replace the existing test:

```python
async def test_applies_all_records_rows_marks_weeks_and_activates(nocommit, make_deps):
    gid, pid = seed(nocommit)
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(7, "Ride 2")]), CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert out["phase"] == "active"
    assert [c[0] for c in tp.calls] == ["tp_create_workout", "tp_create_workout"]
    assert len(repo.owned_workout_ids(nocommit, pid)) == 2
    assert [w.written_to_tp for w in repo.list_weeks(nocommit, pid)] == [True, True]
    assert "applied 2" in out["messages"][0].content
```

with:

```python
async def test_applies_all_records_rows_marks_designed_weeks_and_activates(nocommit, make_deps):
    gid, pid = seed(nocommit)
    repo.set_week_designed(
        nocommit, pid, MONDAY, PlannedWeek(week_start=MONDAY, sessions=[], coach_note="n")
    )
    tp = FakeTp()
    node = make_apply_node(make_deps(ScriptedChatModel(script=[]), tp=tp))
    out = await node(state(gid, pid, [create(0), create(7, "Ride 2")]), CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert out["phase"] == "active"
    assert [c[0] for c in tp.calls] == ["tp_create_workout", "tp_create_workout"]
    assert len(repo.owned_workout_ids(nocommit, pid)) == 2
    # week 2 received a create but was never designed, so it is not a written plan week
    assert [w.written_to_tp for w in repo.list_weeks(nocommit, pid)] == [True, False]
    assert "applied 2" in out["messages"][0].content
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py::test_applies_all_records_rows_marks_designed_weeks_and_activates -v`
Expected: `AssertionError: assert [True, True] == [True, False]`

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/graph/nodes/apply.py`, replace:

```python
    if plan_id is not None and written:
        with deps.connect() as conn:
            repo.mark_weeks_written(conn, plan_id, sorted(written))
            conn.commit()
```

with:

```python
    if plan_id is not None and written:
        with deps.connect() as conn:
            # Only a designed week is on the calendar as a plan week; a one-off create in an
            # undesigned week must not stop the design node from designing it.
            designed = {w.week_start for w in repo.list_weeks(conn, plan_id) if w.designed}
            repo.mark_weeks_written(conn, plan_id, sorted(written & designed))
            conn.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests packages/tri-coach/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/graph/nodes/apply.py packages/tri-planning/tests/test_apply_node.py
git commit -m "fix(planning): apply marks only designed weeks as written"
```

---

### Task 4: P6, recent weekly TSS scales the days present

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/repo.py:262-265`
- Test: `packages/tri-planning/tests/test_repo.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `fitness_snapshot(...).recent_weekly_tss` is `total / days_with_data * 7` when at least 7 of the last 28 days have `tss_day`, else `None` (so `week1_tss` falls back to CTL).

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-planning/tests/test_repo.py`:

```python
def test_fitness_snapshot_scales_the_days_present(pdb):
    as_of = date(2026, 9, 14)
    five = [
        DailyMetricsRow(metric_date=as_of - timedelta(days=d), tss_day=70.0) for d in range(1, 6)
    ]
    core_repo.upsert_daily_metrics(pdb, five)
    assert repo.fitness_snapshot(pdb, as_of).recent_weekly_tss is None
    rest = [
        DailyMetricsRow(metric_date=as_of - timedelta(days=d), tss_day=70.0) for d in range(6, 15)
    ]
    core_repo.upsert_daily_metrics(pdb, rest)
    # 14 days of 70 is a 490 TSS week, not 14 * 70 / 4
    assert repo.fitness_snapshot(pdb, as_of).recent_weekly_tss == pytest.approx(490)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-planning/tests/test_repo.py::test_fitness_snapshot_scales_the_days_present -v`
Expected: `assert 87.5 is None` fails.

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/repo.py`, replace:

```python
    weekly = None
    if tss_row and tss_row["n"]:
        weekly = float(tss_row["total"]) / 4
```

with:

```python
    weekly = None
    if tss_row and tss_row["n"] >= 7:
        # scale the days that have data to a week; fewer than seven is no basis for a load
        weekly = float(tss_row["total"]) / float(tss_row["n"]) * 7
```

The existing `test_fitness_snapshot` (28 days of 70) still expects 490.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/repo.py packages/tri-planning/tests/test_repo.py
git commit -m "fix(planning): recent weekly TSS scales the days with data; None under a week"
```

---

### Task 5: P7, the design window starts at the first plan week

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/design.py:29-32`
- Test: `packages/tri-planning/tests/test_design_node.py` (edit `seed` + append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `window_weeks(weeks, today, horizon)` starts at `max(week_monday(today), weeks[0].week_start)` and returns `[]` for no weeks.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_design_node.py`, replace:

```python
def seed(conn, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), MONDAY)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid, targets
```

with:

```python
def seed(conn, start=MONDAY, **over):
    goal = TrainingGoal(**{**GOAL_ARGS, **over})
    gid = repo.insert_goal(conn, goal)
    targets = build(goal, FitnessSnapshot(ctl=45, recent_weekly_tss=300), start)
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    return gid, pid, targets
```

and append:

```python
def test_window_starts_at_the_first_plan_week_when_today_is_before_it():
    rows = [
        PlanWeekRow(
            plan_id=1,
            week_start=MONDAY + timedelta(weeks=i),
            phase="base",
            target_tss=1,
            target_hours=1,
            designed=None,
            written_to_tp=False,
        )
        for i in range(1, 6)
    ]
    # a Wednesday; the plan starts the Monday after it
    picked = window_weeks(rows, MONDAY + timedelta(days=2), 3)
    assert [w.week_start for w in picked] == [MONDAY + timedelta(weeks=i) for i in (1, 2, 3)]
    assert window_weeks([], MONDAY, 3) == []


async def test_horizon_three_on_a_wednesday_designs_three_weeks(nocommit, make_deps):
    gid, pid, targets = seed(nocommit, start=MONDAY + timedelta(weeks=1))
    model = ScriptedChatModel(
        script=[structured(week_json(t.week_start, t.target_tss)) for t in targets[:3]]
    )
    node = make_design_node(make_deps(model, today=MONDAY + timedelta(days=2), horizon=3))
    out = await node({"goal_id": gid, "plan_id": pid, "messages": []}, CFG)
    assert model.calls == 3 and len(out["pending_changes"]) == 9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py -v`
Expected: the unit test fails with only weeks 1 and 2 picked; the node test fails with `assert 2 == 3`. The existing tests pass (`seed` keeps its default).

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/graph/nodes/design.py`, replace:

```python
def window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]:
    first = week_monday(today)
    last = first + timedelta(weeks=horizon - 1)
    return [w for w in weeks if first <= w.week_start <= last and not w.written_to_tp]
```

with:

```python
def window_weeks(weeks: list[PlanWeekRow], today: date, horizon: int) -> list[PlanWeekRow]:
    """The next `horizon` unwritten plan weeks from this week on. A plan that starts next
    Monday gets its full horizon; a week before the plan is not a plan week."""
    if not weeks:
        return []
    first = max(week_monday(today), weeks[0].week_start)
    last = first + timedelta(weeks=horizon - 1)
    return [w for w in weeks if first <= w.week_start <= last and not w.written_to_tp]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/graph/nodes/design.py packages/tri-planning/tests/test_design_node.py
git commit -m "fix(planning): design window starts at the first plan week"
```

---

### Task 6: P8, peak gets recovery weeks and the recovery count resets at a phase change

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/targets.py:67-86,155-156`
- Test: `packages/tri-planning/tests/test_targets.py` (edit + append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `recovery_flags` treats `peak` as a loading phase on `RECOVERY_EVERY_N_WEEKS` and restarts its count whenever the phase changes; `build` gives a peak recovery week `peak_load * RECOVERY_WEEK_FACTOR`.

**Note for the assembler:** the spec row names only `recovery_flags`, but a flagged peak week whose TSS stays at the peak load would tell the design prompt "recovery week" against a full-load target. `build` already skips the hours floor for `is_rec` in peak (`targets.py:162`), so the TSS factor is the missing half; it is included here and pinned by the new test. One existing assertion (`all peak weeks equal the peak load`) is narrowed to non-recovery peak weeks.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_targets.py`, replace:

```python
def test_ironman_build_recovers_every_third_week():
    phases, _ = targets.allocate_phases("ironman", 24)  # 8 base, 8 build
    flags = targets.recovery_flags("ironman", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7, 10, 13]
```

with:

```python
def test_ironman_build_recovers_every_third_week():
    phases, _ = targets.allocate_phases("ironman", 24)  # 8 base, 8 build, 4 peak
    flags = targets.recovery_flags("ironman", phases)
    assert [i for i, f in enumerate(flags) if f] == [3, 7, 10, 13, 19]


def test_peak_block_has_a_recovery_week_at_sixty_percent():
    phases, _ = targets.allocate_phases("ironman", 24)
    flags = targets.recovery_flags("ironman", phases)
    peak = [i for i, p in enumerate(phases) if p == "peak"]
    assert [i for i in peak if flags[i]] == [peak[-1]]
    weeks = targets.build(race_goal("ironman", 24), FIT, MONDAY)
    rec, full = weeks[peak[-1]], weeks[peak[0]]
    assert rec.is_recovery and not full.is_recovery
    assert rec.target_tss == pytest.approx(full.target_tss * 0.6, abs=1)


def test_recovery_count_resets_at_a_phase_change():
    phases, _ = targets.allocate_phases("ironman", 22)  # 6 base, 8 build, 4 peak
    flags = targets.recovery_flags("ironman", phases)
    assert not flags[phases.index("build")]  # base ended two weeks after its recovery week
    assert [i for i, f in enumerate(flags) if f] == [3, 8, 11, 17]
```

and replace (in `test_peak_taper_race_factors`):

```python
    peak = by_phase["peak"][0].target_tss
    assert all(w.target_tss == peak for w in by_phase["peak"])
```

with:

```python
    peak = by_phase["peak"][0].target_tss
    assert all(w.target_tss == peak for w in by_phase["peak"] if not w.is_recovery)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_targets.py -v`
Expected: `test_ironman_build_recovers_every_third_week` fails (`[3, 7, 10, 13]`), `test_peak_block_has_a_recovery_week_...` fails (no flagged peak week), `test_recovery_count_resets_at_a_phase_change` fails (`flags[6]` is True).

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/planning/targets.py`, replace:

```python
def recovery_flags(goal_type: GoalType, phases: list[Phase]) -> list[bool]:
    flags: list[bool] = []
    since = 0
    for phase in phases:
        if phase not in ("base", "build"):
            flags.append(False)
            since = 0
            continue
        since += 1
```

with:

```python
def recovery_flags(goal_type: GoalType, phases: list[Phase]) -> list[bool]:
    """Every Nth week of a loading phase (base, build, peak) is a recovery week; the count
    restarts at each phase change so a new block never opens on a recovery week."""
    flags: list[bool] = []
    since = 0
    prev: Phase | None = None
    for phase in phases:
        if phase != prev:
            since = 0
            prev = phase
        if phase not in ("base", "build", "peak"):
            flags.append(False)
            continue
        since += 1
```

and replace:

```python
            if phase == "peak":
                tss = peak_load
```

with:

```python
            if phase == "peak":
                tss = peak_load * P.RECOVERY_WEEK_FACTOR if is_rec else peak_load
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests -q`
Expected: all pass (`test_design_eval` picks the first non-recovery week per phase, which is unchanged).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/planning/targets.py packages/tri-planning/tests/test_targets.py
git commit -m "fix(planning): peak block gets a recovery week; recovery count resets per phase"
```

---

### Task 7: P9, validation against the target week; distance steps and a missing week are violations

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/validate.py:21-29,40-64`
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/design.py:49-63`
- Test: `packages/tri-planning/tests/test_validate.py` (append)
- Test: `packages/tri-planning/tests/test_design_node.py` (append)

**Interfaces:**
- Consumes: Task 5's `design.py` (different function; no overlap).
- Produces: `structure_seconds(structure) -> int | None` (`None` when a step has no `duration_seconds`); `validate.week` adds `week_start <a> does not match the target week <b>` and bounds session dates by `target.week_start`; `design.NO_WEEK = "the designer returned no week in two attempts"`; `design_week` retries a `None` structured result once and then returns an empty `PlannedWeek` for the target week with `[NO_WEEK]` as its violations.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-planning/tests/test_validate.py`:

```python
def test_week_start_must_match_the_target():
    shifted = PlannedWeek(
        week_start=MON + timedelta(days=7), sessions=[session(7, tss=300)], coach_note=""
    )
    out = validate.week(shifted, target(), goal())
    assert any("does not match" in v and "2026-09-14" in v for v in out)
    assert any("outside the week starting 2026-09-14" in v for v in out)


def test_structure_step_without_duration_is_a_violation_not_an_error():
    structure = {
        "primaryIntensityMetric": "percentOfFtp",
        "steps": [
            {"name": "swim", "distance_meters": 400, "intensity_min": 80, "intensity_max": 90}
        ],
    }
    assert validate.structure_seconds(structure) is None
    out = validate.week(week(session(0, tss=300, structure=structure)), target(), goal())
    assert any("duration_seconds" in v for v in out)
```

Append to `packages/tri-planning/tests/test_design_node.py`:

```python
async def test_a_reply_without_a_week_is_retried_once_then_reported(nocommit, make_deps):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            AIMessage(content="I need more information."),
            structured(week_json(MONDAY, targets[0].target_tss)),
        ]
    )
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and "VIOLATIONS" not in out["pending_summary"]
    assert len(out["pending_changes"]) == 3

    model = ScriptedChatModel(script=[AIMessage(content="no"), AIMessage(content="still no")])
    out = await node_out(make_deps(model), gid, pid)
    assert model.calls == 2 and out["pending_changes"] == []
    assert "VIOLATIONS" in out["pending_summary"] and "no week" in out["pending_summary"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_validate.py packages/tri-planning/tests/test_design_node.py -v`
Expected: `test_week_start_must_match_the_target` fails (no "does not match" violation); `test_structure_step_without_duration_...` fails with `KeyError: 'duration_seconds'`; `test_a_reply_without_a_week_...` fails with `AssertionError` from `assert isinstance(out, PlannedWeek)`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-planning/src/tri_planning/planning/validate.py`, replace:

```python
def structure_seconds(structure: dict[str, Any]) -> int:
    total = 0
    for step in structure.get("steps", []):
        if step.get("type") == "repetition":
            inner = sum(int(s["duration_seconds"]) for s in step.get("steps", []))
            total += int(step.get("reps", 1)) * inner
        else:
            total += int(step["duration_seconds"])
    return total
```

with:

```python
def structure_seconds(structure: dict[str, Any]) -> int | None:
    """Seconds the steps add up to, or None when a step has no duration_seconds (a distance
    step, or a malformed one)."""
    total = 0
    for step in structure.get("steps", []):
        if step.get("type") == "repetition":
            inner = [s.get("duration_seconds") for s in step.get("steps", [])]
            if any(d is None for d in inner):
                return None
            total += int(step.get("reps", 1)) * sum(int(d) for d in inner)
        elif step.get("duration_seconds") is None:
            return None
        else:
            total += int(step["duration_seconds"])
    return total
```

replace:

```python
def week(planned: PlannedWeek, target: WeekTarget, goal: TrainingGoal) -> list[str]:
    out: list[str] = []
    week_end = planned.week_start + timedelta(days=6)
```

with:

```python
def week(planned: PlannedWeek, target: WeekTarget, goal: TrainingGoal) -> list[str]:
    out: list[str] = []
    week_end = target.week_start + timedelta(days=6)
    if planned.week_start != target.week_start:
        out.append(
            f"week_start {planned.week_start} does not match the target week {target.week_start}"
        )
```

replace:

```python
        if not planned.week_start <= s.date <= week_end:
            out.append(f"{s.date} {s.sport}: outside the week starting {planned.week_start}")
            continue
```

with:

```python
        if not target.week_start <= s.date <= week_end:
            out.append(f"{s.date} {s.sport}: outside the week starting {target.week_start}")
            continue
```

and replace:

```python
        if s.structure is not None:
            secs = structure_seconds(s.structure)
            if abs(secs / 60 - s.duration_minutes) > STRUCTURE_TOLERANCE_MIN:
```

with:

```python
        if s.structure is not None:
            secs = structure_seconds(s.structure)
            if secs is None:
                out.append(f"{s.date} {s.title}: structure has a step without duration_seconds")
            elif abs(secs / 60 - s.duration_minutes) > STRUCTURE_TOLERANCE_MIN:
```

In `packages/tri-planning/src/tri_planning/graph/nodes/design.py`, replace:

```python
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt


def window_weeks(
```

with:

```python
from tri_planning.prompts.design import DESIGN_SYSTEM, render_design_prompt

NO_WEEK = "the designer returned no week in two attempts"


def window_weeks(
```

(If Task 5 has already been applied, `def window_weeks(` is the same anchor.) Then replace:

```python
    async def one(prompt: str) -> PlannedWeek:
        out = await designer.ainvoke(
            [SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg
        )
        assert isinstance(out, PlannedWeek)
        return out

    week = await one(render_design_prompt(goal, target, thresholds, previous, note, None, None))
    violations = validate.week(week, target, goal)
    if violations:
        week = await one(
            render_design_prompt(goal, target, thresholds, previous, note, violations, week)
        )
        violations = validate.week(week, target, goal)
    return week, violations
```

with:

```python
    async def one(prompt: str) -> PlannedWeek | None:
        out = await designer.ainvoke(
            [SystemMessage(DESIGN_SYSTEM), HumanMessage(prompt)], config=cfg
        )
        return out if isinstance(out, PlannedWeek) else None

    first = render_design_prompt(goal, target, thresholds, previous, note, None, None)
    week = await one(first)
    if week is None:
        week = await one(first)  # a reply without the structured week gets one more try
    if week is None:
        empty = PlannedWeek(week_start=target.week_start, sessions=[], coach_note=NO_WEEK)
        return empty, [NO_WEEK]
    violations = validate.week(week, target, goal)
    if violations:
        retry = await one(
            render_design_prompt(goal, target, thresholds, previous, note, violations, week)
        )
        if retry is not None:
            week, violations = retry, validate.week(retry, target, goal)
    return week, violations
```

The design node stores the empty week like any other and reports it as `0 sessions ... VIOLATIONS: the designer returned no week in two attempts`; `session_changes` yields nothing for it, so nothing is proposed for that week and the next run re-designs it (the week is never marked written).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-planning/src/tri_planning/planning/validate.py packages/tri-planning/src/tri_planning/graph/nodes/design.py packages/tri-planning/tests/test_validate.py packages/tri-planning/tests/test_design_node.py
git commit -m "fix(planning): validate against the target week; distance steps and a missing week are violations"
```

---

### Task 8: review de-duplicates repeated proposal ids

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/review.py:35-49`
- Test: `packages/tri-coach/tests/test_review_node.py` (create)

**Interfaces:**
- Consumes: nothing new
- Produces: no signature change; `review_node` reviews and applies each id in `ProposalRequest.ids` once, first occurrence wins the order.

- [ ] **Step 1: Write the failing test**

`review_node` calls `langgraph.types.interrupt`, which needs a running graph; the test swaps the module's binding for a recorder so the node runs over plain state. Create `packages/tri-coach/tests/test_review_node.py`:

```python
"""The review node over plain state: interrupt() is replaced so the node runs outside a graph."""

import tri_coach.graph.nodes.review as review
from tri_coach.graph.nodes.review import review_node
from tri_coach.models import Proposal, ProposalRequest


def proposal(pid: str) -> Proposal:
    return Proposal.model_validate(
        {
            "id": pid,
            "domain": "planning",
            "summary": "move it",
            "changes": [
                {"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "rest"}
            ],
        }
    )


def test_a_repeated_proposal_id_is_reviewed_and_applied_once(monkeypatch):
    shown = []

    def fake_interrupt(payload):
        shown.append(payload)
        return {"action": "approve"}

    monkeypatch.setattr(review, "interrupt", fake_interrupt)
    state = {
        "proposals": [proposal("p1"), proposal("p2")],
        "proposal_request": ProposalRequest(narration="Move it.", ids=["p1", "p1", "p2", "p1"]),
        "pending": None,
    }
    out = review_node(state)
    assert [p["id"] for p in shown[0]["proposals"]] == ["p1", "p2"]
    assert [p.id for p in out["pending"].proposals] == ["p1", "p2"]
    assert out["review_decision"].action == "approve" and out["carried"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-coach/tests/test_review_node.py::test_a_repeated_proposal_id_is_reviewed_and_applied_once -v`
Expected: `AssertionError` on the first assert: `['p1', 'p1', 'p2', 'p1'] == ['p1', 'p2']`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-coach/src/tri_coach/graph/nodes/review.py`, replace:

```python
    missing = [i for i in request.ids if i not in proposals]
    if missing or not request.ids:
        what = ", ".join(missing) if missing else "none given"
        return _refusal(
            f"unknown proposal ids {what}; propose again with ids from this "
            "turn or a held id from the context block"
        )
    empty = [i for i in request.ids if not proposals[i].changes]
    if empty:
        return _refusal(
            f"{', '.join(empty)} carry no changes (a question, or nothing to write); answer the "
            "question or consult again, and propose only proposals with changes"
        )
    pending = ChangeSet(narration=request.narration, proposals=[proposals[i] for i in request.ids])
    carried = [p for p in held_proposals if p.id not in request.ids]
```

with:

```python
    ids = list(dict.fromkeys(request.ids))  # a repeated id would apply its changes twice
    missing = [i for i in ids if i not in proposals]
    if missing or not ids:
        what = ", ".join(missing) if missing else "none given"
        return _refusal(
            f"unknown proposal ids {what}; propose again with ids from this "
            "turn or a held id from the context block"
        )
    empty = [i for i in ids if not proposals[i].changes]
    if empty:
        return _refusal(
            f"{', '.join(empty)} carry no changes (a question, or nothing to write); answer the "
            "question or consult again, and propose only proposals with changes"
        )
    pending = ChangeSet(narration=request.narration, proposals=[proposals[i] for i in ids])
    carried = [p for p in held_proposals if p.id not in ids]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-coach/src/tri_coach/graph/nodes/review.py packages/tri-coach/tests/test_review_node.py
git commit -m "fix(coach): review applies a repeated proposal id once"
```

---

### Task 9: agent tools tag their run; the REPL labels ask_wellness as wellness

**Files:**
- Modify: `packages/tri-core/src/tri_core/harness/agent_tool.py:1-2, 40-47`
- Modify: `packages/tri-coach/src/tri_coach/repl.py:6-8, 12, 36-60, 67-69, 73-84, 94, 109`
- Test: `packages/tri-core/tests/test_harness_agent_tool.py` (edit line 47)
- Test: `packages/tri-coach/tests/test_repl.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `agent_tool` runs the agent with config `tags=[f"tool:{name}"]` (so `tool:ask_analyst`, `tool:ask_wellness`).
  - `tri_coach.repl.TOOL_TAG_PREFIX = "tool:ask_"`
  - `tri_coach.repl.tool_speaker(tags: Sequence[str]) -> str`: `"wellness"` for `tool:ask_wellness`, `"analyst"` for `tool:ask_analyst` or when no `tool:ask_*` tag is present.
  - `_tag(where: str, node: str = "", tags: Sequence[str] = ()) -> str` and `where_of(namespace_label: str, node: str, tags: Sequence[str] = ()) -> str`; the two-argument calls keep their result.
  - `TurnClassifier._root_tags: list[str]`: the tags of the last chat-model event at the root namespace, used to label the root `model`/`tools` update events, which carry no tags.

**Note for the assembler:** the spec says `_tag` reads the tag. Verified in the installed langgraph (`langgraph/pregel/_messages.py`): `on_chat_model_start` copies the run's user tags into the `messages`-mode metadata (`metadata["tags"]`, minus `seq:step:*`), but `on_chain_start` does not, and `updates`-mode events carry no metadata at all. So the tag is readable on the streamed tokens only; the classifier remembers the root run's tags from the last chat-model event and applies them to the root `model`/`tools` update events that follow it (a tool run always begins with a model call). The nested agent's model call inherits the tool tag through the callback manager, alongside the parent turn's tags such as `checkin`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-core/tests/test_harness_agent_tool.py`, replace line 47:

```python
    assert c1["recursion_limit"] == 7 and k1 == {}
```

with:

```python
    assert c1["recursion_limit"] == 7 and c1["tags"] == ["tool:ask_fake"] and k1 == {}
```

Append to `packages/tri-coach/tests/test_repl.py` (its imports already cover `AIMessage`, `AIMessageChunk`, `ToolMessage`, `TurnPrinter`, `where_of`):

```python
def test_printer_labels_the_wellness_tool_by_its_run_tag():
    out: list[str] = []
    p = TurnPrinter(out.append)
    tags = ["checkin", "tool:ask_wellness"]
    # the lab interpreter's own agent streams at the root namespace, tagged by agent_tool
    p.on_event(
        (),
        "messages",
        (AIMessageChunk(content="Ferritin is 30."), {"langgraph_node": "model", "tags": tags}),
    )
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "list_findings", "args": {"panel_id": 3}, "id": "f1", "type": "tool_call"}
        ],
    )
    p.on_event((), "updates", {"model": {"messages": [call]}})
    p.on_event(
        (),
        "updates",
        {
            "tools": {
                "messages": [ToolMessage(content="[]", name="list_findings", tool_call_id="f1")]
            }
        },
    )
    text = "".join(out)
    assert "[wellness] Ferritin is 30." in text
    assert "[wellness] → list_findings" in text and "[wellness] ← list_findings" in text
    assert "[analyst]" not in text and p.final_text == ""
    # the next root run is the analyst's
    p.on_event(
        (),
        "messages",
        (
            AIMessageChunk(content="CTL 45"),
            {"langgraph_node": "model", "tags": ["checkin", "tool:ask_analyst"]},
        ),
    )
    assert "[analyst] CTL 45" in "".join(out)


def test_where_of_reads_the_agent_tool_tag():
    assert where_of("", "model", ["tool:ask_wellness"]) == "wellness"
    assert where_of("", "tools", ["checkin", "tool:ask_analyst"]) == "analyst"
    assert where_of("", "model", ["checkin"]) == "analyst"
    assert where_of("coach", "model", ["tool:ask_wellness"]) == "coach"
    assert where_of("planning", "model", ["tool:ask_wellness"]) == "planning"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_harness_agent_tool.py packages/tri-coach/tests/test_repl.py -v`
Expected: `test_agent_tool_runs_on_a_fresh_throwaway_thread_and_returns_the_final_text` fails with `KeyError: 'tags'`; `test_printer_labels_the_wellness_tool_by_its_run_tag` fails on `"[wellness] Ferritin is 30." in text` (it printed `[analyst]`); `test_where_of_reads_the_agent_tool_tag` fails with `TypeError: where_of() takes 2 positional arguments but 3 were given`. The other tests pass.

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/harness/agent_tool.py`, replace:

```python
"""An agent run as a tool: each call prepares the agent, runs it on a throwaway thread and returns
its final text, or the failure as text. Interrupts and other graph control flow propagate."""
```

with:

```python
"""An agent run as a tool: each call prepares the agent, runs it on a throwaway thread and returns
its final text, or the failure as text. Interrupts and other graph control flow propagate. The run
is tagged `tool:<name>` so a caller streaming the parent graph can tell whose events they are."""
```

and replace:

```python
            out = await invocation.agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"{thread_prefix}-{uuid4()}"},
                    "recursion_limit": recursion_limit,
                },
                **kwargs,
            )
```

with:

```python
            out = await invocation.agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"{thread_prefix}-{uuid4()}"},
                    "recursion_limit": recursion_limit,
                    "tags": [f"tool:{name}"],
                },
                **kwargs,
            )
```

In `packages/tri-coach/src/tri_coach/repl.py`, replace the end of the module docstring:

```python
inside a consultation; the first segment's name is the label. ask_analyst runs its own agent
inside a tool, which streams at the root namespace under nodes `model` and `tools`; the coach
graph has no such nodes, so those events are the analyst's."""
```

with:

```python
inside a consultation; the first segment's name is the label. ask_analyst and ask_wellness each
run their own agent inside a tool, which streams at the root namespace under nodes `model` and
`tools`; the coach graph has no such nodes, so those events are the tool's, and the `tool:ask_*`
tag agent_tool puts on the run says which."""
```

replace:

```python
from collections.abc import Awaitable, Callable
```

with:

```python
from collections.abc import Awaitable, Callable, Sequence
```

replace:

```python
# Only a consultation's output is tagged: the coach speaks to the athlete in its own voice.
TAGGED = frozenset({"planning", "nutrition"})
# Nodes of the coach graph itself; any other node at the root namespace belongs to the analyst.
ROOT_NODES = frozenset({"start", "coach", "planning", "nutrition", "review", "apply"})


Event = tuple[str, dict[str, Any]]


def label(namespace: tuple[str, ...]) -> str:
    return namespace[0].split(":", 1)[0] if namespace else ""


def _tag(where: str, node: str = "") -> str:
    """The bracket label: a consultation's, the analyst's, or "" for the coach and the root."""
    if where in TAGGED:
        return where
    if not where and node in ("model", "tools"):
        return "analyst"
    return ""


def where_of(namespace_label: str, node: str) -> str:
    """Who is speaking: the tag, or "coach" for the coach's own voice and the root nodes."""
    return _tag(namespace_label, node) or "coach"
```

with:

```python
# Only a consultation's output is tagged: the coach speaks to the athlete in its own voice.
TAGGED = frozenset({"planning", "nutrition"})
# Nodes of the coach graph itself; any other node at the root namespace belongs to an agent tool.
ROOT_NODES = frozenset({"start", "coach", "planning", "nutrition", "review", "apply"})
# agent_tool tags each run "tool:<name>"; the coach's agent tools are ask_analyst and ask_wellness.
TOOL_TAG_PREFIX = "tool:ask_"


Event = tuple[str, dict[str, Any]]


def label(namespace: tuple[str, ...]) -> str:
    return namespace[0].split(":", 1)[0] if namespace else ""


def tool_speaker(tags: Sequence[str]) -> str:
    """The agent tool a run's tags name ("analyst", "wellness"); the analyst when none does."""
    for tag in tags:
        if tag.startswith(TOOL_TAG_PREFIX):
            return tag[len(TOOL_TAG_PREFIX) :]
    return "analyst"


def _tag(where: str, node: str = "", tags: Sequence[str] = ()) -> str:
    """The bracket label: a consultation's, the agent tool's, or "" for the coach and the root."""
    if where in TAGGED:
        return where
    if not where and node in ("model", "tools"):
        return tool_speaker(tags)
    return ""


def where_of(namespace_label: str, node: str, tags: Sequence[str] = ()) -> str:
    """Who is speaking: the tag, or "coach" for the coach's own voice and the root nodes. `tags`
    are the run's, from the messages stream metadata; they say which agent tool is at the root."""
    return _tag(namespace_label, node, tags) or "coach"
```

replace:

```python
    def __init__(self) -> None:
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
```

with:

```python
    def __init__(self) -> None:
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
        self._root_tags: list[str] = []  # the last root model call's tags: which agent tool
```

replace:

```python
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    if where == "coach":
                        self.final_text += text
                    return [("token", {"where": where_of(where, "model"), "text": text})]
            return []
```

with:

```python
        if mode == "messages":
            chunk, meta = data
            if not where and meta.get("tags"):
                # updates carry no tags: the root run's model and tools nodes are labelled by
                # the tags its model call streamed with
                self._root_tags = list(meta["tags"])
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    if where == "coach":
                        self.final_text += text
                    who = where_of(where, "model", self._root_tags)
                    return [("token", {"where": who, "text": text})]
            return []
```

replace:

```python
                if node == "model" and isinstance(msg, AIMessage):
                    who = where_of(where, node)
```

with:

```python
                if node == "model" and isinstance(msg, AIMessage):
                    who = where_of(where, node, self._root_tags)
```

and replace:

```python
                            {
                                "where": where_of(where, node),
                                "name": msg.name,
                                "chars": len(text_of(msg)),
                            },
```

with:

```python
                            {
                                "where": where_of(where, node, self._root_tags),
                                "name": msg.name,
                                "chars": len(text_of(msg)),
                            },
```

tri-web's `TurnEmitter` subclasses `TurnPrinter` and forwards the `where` value unchanged; its tests feed untagged root events, which the `"analyst"` default keeps labelled as before.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests packages/tri-coach/tests packages/tri-web/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/agent_tool.py packages/tri-core/tests/test_harness_agent_tool.py packages/tri-coach/src/tri_coach/repl.py packages/tri-coach/tests/test_repl.py
git commit -m "fix(coach): label ask_wellness output as wellness via the agent tool's run tag"
```

---

### Task 10: the apply report lists each applied change

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/models.py:70-87`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/apply.py:31-50` (plus a new `describe` helper above `report_from_planning`)
- Test: `packages/tri-coach/tests/test_graph_apply.py` (edit lines 86 and 122)
- Test: `packages/tri-coach/tests/test_models.py` (append)
- Test: `packages/tri-coach/tests/test_graph.py` (edit line 281), `packages/tri-web/tests/test_routes_coach.py` (edit lines 76 and 122): existing exact-match assertions on the apply message

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `ApplyReport.applied_changes: list[str] = Field(default_factory=list)`; `ApplyReport.line()` returns the summary line followed by one `  applied: <change>` line per entry.
  - `tri_coach.graph.nodes.apply.describe(change: CalendarChange | NutritionChange) -> str`: `"<op> <target>[ -> <new_date>]: <reason>"` for a calendar change without a workout body, `"<op> <date> <sport> '<title>': <reason>"` with one, `"<op> <target_key or day>: <reason>"` for a nutrition change.
  - `report_from_planning` and `report_from_nutrition` fill `applied_changes` from `r.applied`; `raised_report` leaves it empty.

The apply node's `AIMessage(name="apply")` is the only record of the apply in the coach's history, and the review node's edit branch replaces `pending` without touching the messages, so after an edit the coach (and the `remember(checkin)` paragraph it writes from that history) saw only the original proposal. Listing what was written fixes that without adding a message.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_models.py`, adding the import `from tri_coach.graph.nodes.apply import describe`:

```python
def test_apply_report_lists_each_applied_change():
    moved = CalendarChange.model_validate(
        {"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-19", "reason": "rest day"}
    )
    assert describe(moved) == "move w1 -> 2026-09-19: rest day"
    assert describe(CalendarChange.model_validate(planning_change())) == "delete w1: knee pain"
    nutrition = NutritionChange.model_validate(nutrition_change())
    assert describe(nutrition) == "set_day_targets 2026-09-14: extend horizon"
    r = ApplyReport(
        domain="planning",
        applied=1,
        skipped=[],
        remaining=0,
        error=None,
        sessions_changed=True,
        applied_changes=[describe(moved)],
    )
    assert r.line() == "planning: applied 1\n  applied: move w1 -> 2026-09-19: rest day"
```

In `packages/tri-coach/tests/test_graph_apply.py`, replace line 86 of `test_edit_replaces_the_change_set_before_apply`:

```python
    assert out["pending"] is None
```

with:

```python
    assert out["pending"] is None
    friday = (MONDAY + timedelta(days=5)).isoformat()
    # the coach's history holds what was written, not the proposal the athlete edited
    assert out["messages"][-1].content == (
        f"planning: applied 1\n  applied: move w1 -> {friday}: rest day"
    )
    assert (MONDAY + timedelta(days=4)).isoformat() not in out["messages"][-1].content
```

and replace line 122 of `test_nutrition_handoff_proposes_and_apply_persists_overrides`:

```python
    assert out["messages"][-1].content == "nutrition: applied 1"
```

with:

```python
    assert out["messages"][-1].content.startswith(
        "nutrition: applied 1\n  applied: set_day_targets "
    )
```

In `packages/tri-coach/tests/test_graph.py`, replace line 281 of `test_approve_dispatches_planning_apply_with_thread_coach`:

```python
    assert out["messages"][-1].content == "planning: applied 1"
```

with:

```python
    assert out["messages"][-1].content.startswith("planning: applied 1\n  applied: move w1 -> ")
```

In `packages/tri-web/tests/test_routes_coach.py`, replace line 76 of `test_a_proposing_coach_streams_the_interrupt_and_pauses`:

```python
        assert ("report", {"text": "planning: applied 1"}) in events
```

with:

```python
        reports = [d["text"] for n, d in events if n == "report"]
        assert reports and reports[0].startswith("planning: applied 1\n  applied: move w1 -> ")
```

and replace line 122 (the edit test):

```python
        assert ("report", {"text": "planning: applied 1"}) in parse_sse(r.text)
```

with:

```python
        reports = [d["text"] for n, d in parse_sse(r.text) if n == "report"]
        assert reports[0].startswith("planning: applied 1\n  applied: move w1 -> 2026-09-19")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_models.py packages/tri-coach/tests/test_graph_apply.py packages/tri-coach/tests/test_graph.py packages/tri-web/tests/test_routes_coach.py -v`
Expected: `test_models.py` fails at collection with `ImportError: cannot import name 'describe'`; the four edited graph tests fail on their message assertions (the message is still the one-line `planning: applied 1` / `nutrition: applied 1`).

- [ ] **Step 3: Write the implementation**

In `packages/tri-coach/src/tri_coach/models.py`, replace:

```python
class ApplyReport(BaseModel):
    domain: Domain
    applied: int
    skipped: list[str]
    remaining: int
    error: str | None
    sessions_changed: bool  # planning: any create/update/delete/move applied

    def line(self) -> str:
        parts = [f"applied {self.applied}"]
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.remaining:
            parts.append(f"{self.remaining} still pending")
        text = f"{self.domain}: " + ", ".join(parts)
        if self.error:
            text += f"; stopped: {self.error}"
        return text
```

with:

```python
class ApplyReport(BaseModel):
    domain: Domain
    applied: int
    skipped: list[str]
    remaining: int
    error: str | None
    sessions_changed: bool  # planning: any create/update/delete/move applied
    applied_changes: list[str] = Field(default_factory=list)  # one line per change as written

    def line(self) -> str:
        parts = [f"applied {self.applied}"]
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.remaining:
            parts.append(f"{self.remaining} still pending")
        text = f"{self.domain}: " + ", ".join(parts)
        if self.error:
            text += f"; stopped: {self.error}"
        return "\n".join([text, *(f"  applied: {c}" for c in self.applied_changes)])
```

In `packages/tri-coach/src/tri_coach/graph/nodes/apply.py`, replace:

```python
def report_from_planning(r: PlanningResult) -> ApplyReport:
    return ApplyReport(
        domain="planning",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=r.sessions_changed,
    )


def report_from_nutrition(r: NutritionResult) -> ApplyReport:
    return ApplyReport(
        domain="nutrition",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=False,
    )
```

with:

```python
def describe(change: CalendarChange | NutritionChange) -> str:
    """One line for a change as it was written, so the coach's history holds what the athlete
    approved or edited, not only what was proposed."""
    if isinstance(change, NutritionChange):
        return f"{change.op} {change.target_key or change.day.isoformat()}: {change.reason}"
    if change.workout is not None:
        w = change.workout
        return f"{change.op} {w.date} {w.sport} '{w.title}': {change.reason}"
    target = change.tp_workout_id or ""
    if not target and change.workout_date is not None:
        target = change.workout_date.isoformat()
    if change.new_date is not None:
        target += f" -> {change.new_date.isoformat()}"
    head = f"{change.op} {target}".rstrip()
    return f"{head}: {change.reason}"


def report_from_planning(r: PlanningResult) -> ApplyReport:
    return ApplyReport(
        domain="planning",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=r.sessions_changed,
        applied_changes=[describe(c) for c in r.applied],
    )


def report_from_nutrition(r: NutritionResult) -> ApplyReport:
    return ApplyReport(
        domain="nutrition",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=False,
        applied_changes=[describe(c) for c in r.applied],
    )
```

`CalendarChange` and `NutritionChange` are already imported in `apply.py`. `raised_report` is unchanged: nothing is known to have been written. `ApplyReport` is in `STATE_TYPES`; the new field has a default, so checkpoints written before this change still load.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests packages/tri-web/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-coach/src/tri_coach/models.py packages/tri-coach/src/tri_coach/graph/nodes/apply.py packages/tri-coach/tests/test_models.py packages/tri-coach/tests/test_graph_apply.py packages/tri-coach/tests/test_graph.py packages/tri-web/tests/test_routes_coach.py
git commit -m "fix(coach): the apply report lists each applied change as written"
```

---

### Task 11: proposal ids continue across an apply within a turn

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/state.py:26`
- Modify: `packages/tri-coach/src/tri_coach/graph/graph.py:44-54`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/planning.py:61-67`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py:88-89, 102-107, 112-116`
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/apply.py:214` (comment only)
- Test: `packages/tri-coach/tests/test_nodes.py` (append)
- Test: `packages/tri-coach/tests/test_graph_apply.py` (edit lines 516 and 527): an existing assertion that pins the follow-on's id as `p1`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `CoachState.next_proposal_id: int`: the number the next proposal of this turn takes; `start_node` sets it to `1`; the planning and nutrition nodes read it (absent or falsy reads as `1`), name their proposal `p{n}` and write back `n + 1`; `apply` leaves it alone while still emptying `proposals`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_nodes.py`, changing the existing import `from tri_coach.graph.graph import after_apply` to `from tri_coach.graph.graph import after_apply, start_node`:

```python
def test_start_resets_the_proposal_counter():
    assert start_node({})["next_proposal_id"] == 1


async def test_proposal_ids_continue_from_the_turn_counter():
    graph = Recorder({"pending_changes": [], "messages": [AIMessage(content="Which day?")]})
    node = make_planning_node(graph)
    brief = Brief(domain="planning", instruction="x", tool_call_id="c1", message_id="m1")
    out = await node({"brief": brief, "proposals": [], "next_proposal_id": 2}, CONFIG)
    assert out["proposals"][0].id == "p2" and out["next_proposal_id"] == 3


async def test_the_follow_on_after_an_apply_is_not_numbered_p1_again():
    change = {
        "op": "set_day_targets",
        "target_key": "2026-09-14",
        "day": "2026-09-14",
        "payload": {"calorie_goal": 2800},
        "reason": "easy day",
    }
    graph = Recorder(
        {"pending_changes": [change], "pending_summary": "Daily targets", "last_error": None}
    )
    node = make_nutrition_node(graph)
    brief = Brief(domain="nutrition", instruction="regenerate", regenerate=True)
    # apply consumed p1 and emptied `proposals`; the counter is what carries the numbering
    out = await node({"brief": brief, "proposals": [], "next_proposal_id": 2}, CONFIG)
    assert out["proposals"][0].id == "p2" and out["next_proposal_id"] == 3
    assert "call propose_changes with p2" in out["messages"][0].content
```

In `packages/tri-coach/tests/test_graph_apply.py`, `test_a_plan_change_that_moves_sessions_regenerates_nutrition_and_opens_a_second_gate` pins the old numbering. Replace line 516:

```python
            propose("Today's targets follow the moved session.", ["p1"], "c10"),
```

with:

```python
            propose("Today's targets follow the moved session.", ["p2"], "c10"),
```

and line 527:

```python
    assert [(p["id"], p["domain"]) for p in second["proposals"]] == [("p1", "nutrition")]
```

with:

```python
    assert [(p["id"], p["domain"]) for p in second["proposals"]] == [("p2", "nutrition")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_nodes.py packages/tri-coach/tests/test_graph_apply.py::test_a_plan_change_that_moves_sessions_regenerates_nutrition_and_opens_a_second_gate -v`
Expected: `test_start_resets_the_proposal_counter` fails with `KeyError: 'next_proposal_id'`; the two node tests fail on `.id == "p2"` (they get `p1`); the graph test fails at the second gate: the coach proposes `p2`, review refuses it as an unknown id, so `out` has no `__interrupt__` (`KeyError: '__interrupt__'`).

- [ ] **Step 3: Write the implementation**

In `packages/tri-coach/src/tri_coach/graph/state.py`, replace:

```python
    proposals: list[Proposal]  # accumulated this turn
```

with:

```python
    proposals: list[Proposal]  # accumulated this turn; apply empties it
    next_proposal_id: int  # the number the next proposal takes; ids keep counting past an apply
```

In `packages/tri-coach/src/tri_coach/graph/graph.py`, replace:

```python
    return {
        "pending": state.get("pending"),
        "brief": None,
        "proposals": [],
        "proposal_request": None,
```

with:

```python
    return {
        "pending": state.get("pending"),
        "brief": None,
        "proposals": [],
        "next_proposal_id": 1,
        "proposal_request": None,
```

In `packages/tri-coach/src/tri_coach/graph/nodes/planning.py`, replace:

```python
        proposals = list(state.get("proposals") or [])
        proposal = proposal_from_planning(out, f"p{len(proposals) + 1}")
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }
```

with:

```python
        proposals = list(state.get("proposals") or [])
        n = state.get("next_proposal_id") or 1
        proposal = proposal_from_planning(out, f"p{n}")
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "next_proposal_id": n + 1,
            "messages": [result_message(brief, proposal)],
        }
```

In `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py`, replace:

```python
        proposals = list(state.get("proposals") or [])
        pid = f"p{len(proposals) + 1}"
```

with:

```python
        proposals = list(state.get("proposals") or [])
        n = state.get("next_proposal_id") or 1
        pid = f"p{n}"
```

replace:

```python
            return {
                "brief": None,
                "regenerate_after_apply": False,
                "proposals": [*proposals, proposal],
                "messages": [follow_on_message(proposal)],
            }
```

with:

```python
            return {
                "brief": None,
                "regenerate_after_apply": False,
                "proposals": [*proposals, proposal],
                "next_proposal_id": n + 1,
                "messages": [follow_on_message(proposal)],
            }
```

and replace:

```python
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }
```

with:

```python
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "next_proposal_id": n + 1,
            "messages": [result_message(brief, proposal)],
        }
```

In `packages/tri-coach/src/tri_coach/graph/nodes/apply.py`, replace:

```python
            "proposals": [],  # consumed: the follow-on proposal is p1, an applied id is gone
```

with:

```python
            "proposals": [],  # consumed: an applied id is gone; next_proposal_id keeps counting
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests packages/tri-web/tests -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add packages/tri-coach/src/tri_coach/graph/state.py packages/tri-coach/src/tri_coach/graph/graph.py packages/tri-coach/src/tri_coach/graph/nodes/planning.py packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py packages/tri-coach/src/tri_coach/graph/nodes/apply.py packages/tri-coach/tests/test_nodes.py packages/tri-coach/tests/test_graph_apply.py
git commit -m "fix(coach): proposal ids keep counting past an apply within a turn"
```

---

### Task 12: C1 a failing `initialize` leaks the subprocess

**Files:**
- Modify: `packages/tri-core/src/tri_core/mcp/client.py:3-8, 54-64`
- Test: `packages/tri-core/tests/test_mcp_client.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `tri_core.mcp.client.SESSION_TIMEOUT_S = 120`; `McpToolClient._open(self, params: StdioServerParameters) -> None` (private); `__aenter__` closes the exit stack and re-raises on any exception, and times out after `SESSION_TIMEOUT_S`.

**Note for the assembler:** `tri_core/mcp/live_tools.py:22` already has its own `SESSION_TIMEOUT_S = 120` for the LangChain adapter path. This task adds a second copy in `client.py` rather than importing across (live_tools pulls in `langchain_mcp_adapters`; client.py must stay light). Leave both.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_mcp_client.py`. Add to the imports at the top of the file (ruff sorts them):

```python
from contextlib import asynccontextmanager

from tri_core.mcp.servers import ServerSpec
```

(`from tri_core.mcp.servers import GARMIN_ENABLED_TOOLS, garmin_spec, trainingpeaks_spec` is already there; merge `ServerSpec` into that line.) Then append:

```python
async def test_a_failing_initialize_closes_the_stack_and_reraises(monkeypatch):
    closed: list[str] = []

    @asynccontextmanager
    async def fake_stdio_client(params):
        try:
            yield ("read", "write")
        finally:
            closed.append("transport")

    class FakeSession:
        def __init__(self, read, write) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            closed.append("session")

        async def initialize(self):
            raise RuntimeError("handshake failed")

    monkeypatch.setattr("tri_core.mcp.client.stdio_client", fake_stdio_client)
    monkeypatch.setattr("tri_core.mcp.client.ClientSession", FakeSession)
    client = McpToolClient(ServerSpec(name="fake", command="x", args=[]))
    with pytest.raises(RuntimeError, match="handshake failed"):
        async with client:
            pass
    assert closed == ["session", "transport"]
    assert client._stack is None and client._session is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_mcp_client.py::test_a_failing_initialize_closes_the_stack_and_reraises -v`
Expected: fails at `assert closed == ["session", "transport"]` with `closed == []` (the exception escapes `__aenter__` before `__aexit__` ever runs, so nothing is closed).

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/mcp/client.py`, replace:

```python
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any
```

with:

```python
from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from typing import Any
```

and replace:

```python
from tri_core.mcp.servers import ServerSpec


class McpToolError(Exception):
```

with:

```python
from tri_core.mcp.servers import ServerSpec

SESSION_TIMEOUT_S = 120  # uvx cold start + Garmin login can take a while


class McpToolError(Exception):
```

and replace:

```python
    async def __aenter__(self) -> McpToolClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.spec.command,
            args=self.spec.args,
            env={**os.environ, **self.spec.env},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self
```

with:

```python
    async def __aenter__(self) -> McpToolClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.spec.command,
            args=self.spec.args,
            env={**os.environ, **self.spec.env},
        )
        try:
            await asyncio.wait_for(self._open(params), timeout=SESSION_TIMEOUT_S)
        except Exception:
            # a failed or hung handshake must not leave the server subprocess running
            await self.__aexit__(None, None, None)
            raise
        return self

    async def _open(self, params: StdioServerParameters) -> None:
        assert self._stack is not None
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass (the live test stays skipped).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/mcp/client.py packages/tri-core/tests/test_mcp_client.py
git commit -m "fix(core): close the MCP exit stack when initialize fails or times out"
```

---

### Task 13: C2 `Decimal` returned as a string

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/sql_tool.py:8-11, 91-96`
- Test: `packages/tri-core/tests/test_sql_tool.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `_json_safe` returns `float` for `decimal.Decimal`.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_sql_tool.py`:

```python
@pytest.mark.db
def test_run_query_returns_numeric_as_float(url):
    out = run_readonly_query(url, "select 1.5::numeric as x, 2::numeric as n, 40.0::numeric as ctl")
    assert out["rows"][0] == [1.5, 2.0, 40.0]
    assert all(isinstance(v, float) for v in out["rows"][0])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_sql_tool.py::test_run_query_returns_numeric_as_float -v`
Expected: fails at the first assert with `['1.5', '2', '40.0'] == [1.5, 2.0, 40.0]` (skips if Postgres is not reachable; then start the test database first).

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/db/sql_tool.py`, replace:

```python
from __future__ import annotations

import json
from typing import Any
```

with:

```python
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
```

and replace:

```python
def _json_safe(v: Any) -> Any:
    if isinstance(v, int | float | str | bool) or v is None:
        return v
    if isinstance(v, list | dict):
        return json.loads(json.dumps(v, default=str))
    return str(v)
```

with:

```python
def _json_safe(v: Any) -> Any:
    if isinstance(v, int | float | str | bool) or v is None:
        return v
    if isinstance(v, Decimal):
        return float(v)  # numeric columns (ctl, atl, tsb) are numbers to the model, not text
    if isinstance(v, list | dict):
        return json.loads(json.dumps(v, default=str))
    return str(v)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/db/sql_tool.py packages/tri-core/tests/test_sql_tool.py
git commit -m "fix(core): return numeric columns as floats from the SQL tool"
```

---

### Task 14: C3 the SQL tool caps rows, not bytes

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/sql_tool.py:99-128, 136-143` (line numbers before Task 13; after Task 13 every line below 11 shifts by +1 and below 96 by +3)
- Test: `packages/tri-core/tests/test_sql_tool.py` (append)

**Interfaces:**
- Consumes: Task 13's `_json_safe` (unchanged signature)
- Produces: `tri_core.db.sql_tool.MAX_CHARS = 8000`; `run_readonly_query` output gains `"note": str` when `truncated` is true; `truncated` is true when either the row cap or the character cap cut the result; `row_count` counts the rows returned.

**Note for the assembler:** `select *` on `workouts` stays allowed (nothing rejects a statement by shape); a single row wider than `MAX_CHARS` (a `raw jsonb` column) returns zero rows with `truncated: true` and the note, which is the signal to pick columns.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_sql_tool.py`:

```python
@pytest.mark.db
def test_run_query_cuts_a_wide_result_at_a_row_boundary(url):
    # five 3,000-character rows: two fit under MAX_CHARS, the third would not
    out = run_readonly_query(url, "select repeat('x', 3000) as s from generate_series(1, 5)")
    assert out["columns"] == ["s"]
    assert out["row_count"] == 2 and len(out["rows"]) == 2
    assert all(row == ["x" * 3000] for row in out["rows"])  # whole rows, never a cut string
    assert out["truncated"] is True
    assert "narrow" in out["note"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_sql_tool.py::test_run_query_cuts_a_wide_result_at_a_row_boundary -v`
Expected: fails at `assert out["row_count"] == 2` with `5 == 2`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/db/sql_tool.py`, replace:

```python
_ALLOWED_HEADS = ("select", "with")
```

with:

```python
_ALLOWED_HEADS = ("select", "with")
MAX_CHARS = 8000  # of the rows' JSON; whole rows only, so a wide result is cut early
```

and replace:

```python
    rows = [[_json_safe(v) for v in r] for r in fetched[:max_rows]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(fetched) > max_rows,
    }
```

with:

```python
    rows = [[_json_safe(v) for v in r] for r in fetched[:max_rows]]
    kept: list[list[Any]] = []
    size = 2  # the enclosing brackets
    for row in rows:
        size += len(json.dumps(row, default=str)) + 1
        if size > MAX_CHARS:
            break
        kept.append(row)
    truncated = len(fetched) > max_rows or len(kept) < len(rows)
    out: dict[str, Any] = {
        "columns": columns,
        "rows": kept,
        "row_count": len(kept),
        "truncated": truncated,
    }
    if truncated:
        out["note"] = (
            f"result cut at {len(kept)} rows (caps: {max_rows} rows, {MAX_CHARS} characters); "
            "narrow the query: fewer columns, a shorter window, or aggregate"
        )
    return out
```

and replace:

```python
        Do arithmetic in SQL (sums, averages, group by week), not in your head.
        Rows are capped at 200; aggregate rather than listing raw rows for long windows.
        """
```

with:

```python
        Do arithmetic in SQL (sums, averages, group by week), not in your head.
        Rows are capped at 200 and the result at 8,000 characters, cut at whole rows; a cut
        result has "truncated": true and a note. Pick columns, aggregate, or shorten the window
        rather than listing raw rows for long windows.
        """
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass (`test_run_query_caps_rows` still holds: ten small rows are far under the character cap).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/db/sql_tool.py packages/tri-core/tests/test_sql_tool.py
git commit -m "fix(core): cap the SQL tool result at 8,000 characters on a row boundary"
```

---

### Task 15: C4 Garmin readiness keeps the day's highest score

**Files:**
- Modify: `packages/tri-core/src/tri_core/sync/garmin.py:84-97`
- Test: `packages/tri-core/tests/test_sync_garmin.py:66-71` (edit the existing test)

**Interfaces:**
- Consumes: nothing new
- Produces: `parse_readiness` picks the entry with the greatest `timestamp` (ISO string; entries without one sort first).

- [ ] **Step 1: Write the failing test**

In `packages/tri-core/tests/test_sync_garmin.py`, replace:

```python
def test_parse_readiness_picks_highest_score():
    assert parse_readiness(
        [{"date": "2026-09-01", "score": 55}, {"date": "2026-09-01", "score": 68}]
    ) == (date(2026, 9, 1), 68)
    assert parse_readiness([]) is None
    assert parse_readiness({"date": "2026-09-01", "score": 70}) == (date(2026, 9, 1), 70)
```

with:

```python
def test_parse_readiness_keeps_the_latest_entry_by_timestamp():
    # Garmin recomputes readiness through the day; the last word wins, not the best one
    assert parse_readiness(
        [
            {"date": "2026-09-01", "timestamp": "2026-09-01T09:40:00.0", "score": 55},
            {"date": "2026-09-01", "timestamp": "2026-09-01T04:18:29.0", "score": 68},
        ]
    ) == (date(2026, 9, 1), 55)
    assert parse_readiness([]) is None
    assert parse_readiness({"date": "2026-09-01", "score": 70}) == (date(2026, 9, 1), 70)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_sync_garmin.py::test_parse_readiness_keeps_the_latest_entry_by_timestamp -v`
Expected: fails with `(date(2026, 9, 1), 68) == (date(2026, 9, 1), 55)`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/sync/garmin.py`, replace:

```python
    if not scored:
        return None
    best = max(scored, key=lambda e: float(e["score"]))
    return _date(best["date"]), int(round(float(best["score"])))
```

with:

```python
    if not scored:
        return None
    latest = max(scored, key=lambda e: str(e.get("timestamp") or ""))
    return _date(latest["date"]), int(round(float(latest["score"])))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/sync/garmin.py packages/tri-core/tests/test_sync_garmin.py
git commit -m "fix(core): keep the latest Garmin readiness entry, not the highest"
```

---

### Task 16: C5 the sync runner's `except` path can raise on a dead connection

**Files:**
- Modify: `packages/tri-core/src/tri_core/sync/runner.py:128-135`
- Test: `packages/tri-core/tests/test_sync_runner.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: on a source error, the rollback, `set_sync_state` and commit run under their own `try`; a failure there is logged as `== <source>: could not record the error state: <err>` and `SourceResult.error` becomes `"<source error>; sync_state not updated: <state error>"`.

**Note for the assembler:** the spec names `set_sync_state`; `conn.rollback()` is inside the same `try` because a dead connection raises there first, and that is the same escape the row is closing.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-core/tests/test_sync_runner.py`:

```python
class _DeadConn:
    """A connection whose writes fail after the source did; connect() returns it."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass


async def test_a_failing_state_write_is_reported_with_the_source_error(monkeypatch):
    settings = Settings(_env_file=None)
    monkeypatch.setattr("tri_core.sync.runner.connect", lambda url: _DeadConn())
    monkeypatch.setattr(repo, "get_sync_state", lambda conn, source: None)

    def dead_write(conn, source, last, status, error):
        raise RuntimeError("the connection is closed")

    monkeypatch.setattr(repo, "set_sync_state", dead_write)
    lines: list[str] = []
    report = await run_sync(
        settings,
        since=date(2026, 8, 30),
        sources=("garmin",),
        log=lines.append,
        open_garmin=_factory(_Fake({}, fail=True)),
    )
    assert not report.ok
    (result,) = report.results
    assert result.source == "garmin" and result.status == "error"
    assert "server down" in (result.error or "") and "the connection is closed" in (result.error or "")
    assert any("could not record the error state" in line for line in lines)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_sync_runner.py::test_a_failing_state_write_is_reported_with_the_source_error -v`
Expected: fails with `RuntimeError: the connection is closed` raised out of `run_sync` (the `except` block re-raises through `set_sync_state`).

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/sync/runner.py`, replace:

```python
            except Exception as exc:  # per-source isolation is the point
                conn.rollback()
                err = f"{type(exc).__name__}: {exc}"
                log(f"== {source}: ERROR {err}\n{traceback.format_exc()}")
                last = state.last_synced_date if state else start
                repo.set_sync_state(conn, source, last, "error", err[:2000])
                conn.commit()
                report.results.append(SourceResult(source, "error", 0, err))
```

with:

```python
            except Exception as exc:  # per-source isolation is the point
                err = f"{type(exc).__name__}: {exc}"
                log(f"== {source}: ERROR {err}\n{traceback.format_exc()}")
                last = state.last_synced_date if state else start
                try:
                    conn.rollback()
                    repo.set_sync_state(conn, source, last, "error", err[:2000])
                    conn.commit()
                except Exception as state_exc:  # a dead connection must not hide the source error
                    state_err = f"{type(state_exc).__name__}: {state_exc}"
                    log(f"== {source}: could not record the error state: {state_err}")
                    err = f"{err}; sync_state not updated: {state_err}"
                report.results.append(SourceResult(source, "error", 0, err))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests -q`
Expected: all pass (`test_run_sync_isolates_source_failure` still sees `server down` in `last_error`; the state write succeeds there).

- [ ] **Step 5: Commit**

```bash
git add packages/tri-core/src/tri_core/sync/runner.py packages/tri-core/tests/test_sync_runner.py
git commit -m "fix(core): report a failed sync_state write instead of raising out of run_sync"
```

---

### Task 17: A1 a bare `/` raises `IndexError`

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/repl.py:62-71`
- Test: `packages/tri-analyze/tests/test_repl.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `chat_loop` prints `commands: /quit, /<name>, ...` (sorted) for a bare `/` and reads the next line.

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-analyze/tests/test_repl.py`:

```python
async def test_chat_loop_a_bare_slash_lists_the_commands():
    fake = FakeAgent()
    inputs = iter(["/", "/  ", "/quit"])

    async def read():
        return next(inputs, None)

    async def tools_cmd():
        return "tools: add"

    buf, out = _capture()
    await chat_loop(fake, read=read, out=out, context=lambda: CTX, commands={"tools": tools_cmd})
    assert buf.count("commands: /quit, /tools\n") == 2
    assert fake.calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-analyze/tests/test_repl.py::test_chat_loop_a_bare_slash_lists_the_commands -v`
Expected: `IndexError: list index out of range` from `repl.py:63`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-analyze/src/tri_analyze/repl.py`, replace:

```python
        if line.startswith("/"):
            name = line[1:].split()[0]
            if name == "quit":
                return
            handler = commands.get(name)
```

with:

```python
        if line.startswith("/"):
            name = (line[1:].split() or [""])[0]
            if name == "quit":
                return
            if not name:
                names = ", ".join(f"/{n}" for n in sorted(["quit", *commands]))
                out(f"commands: {names}\n")
                continue
            handler = commands.get(name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-analyze/src/tri_analyze/repl.py packages/tri-analyze/tests/test_repl.py
git commit -m "fix(analyze): a bare / lists the commands instead of raising"
```

---

### Task 18: A2 `states_window` matches "decoupling 5%"

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py:1-6, 23, 77-91`
- Test: `packages/tri-analyze/tests/test_evals.py:232-263` (edit the existing test)

**Interfaces:**
- Consumes: nothing new
- Produces: `states_window(inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]` (gains `inputs`, like `pulls_splits`; LangSmith passes evaluator arguments by name, and `run.py:76` needs no change); `_MONTH` matches only whole month names and their standard abbreviations; the question's own text is removed from the answer before the search.

- [ ] **Step 1: Write the failing test**

In `packages/tri-analyze/tests/test_evals.py`, replace:

```python
def test_states_window_accepts_iso_month_day_and_relative_windows():
    ref = case("weekly_tss_8w").outputs()

    def answer(text: str) -> dict:
        return {"calls": [], "answer": text}
```

with:

```python
def test_states_window_accepts_iso_month_day_and_relative_windows():
    inputs = case("weekly_tss_8w").inputs()
    ref = case("weekly_tss_8w").outputs()

    def answer(text: str) -> dict:
        return {"calls": [], "answer": text}
```

replace:

```python
        "Weight fell from 75.4 kg on 9/13/2026 to 74.0 kg.",
    ):
        assert states_window(answer(text), ref)["score"] == 1, text
    for text in (
        "TSS averaged 412 with one recovery week.",
        "Here is a weekly summary of your training.",
        "I don't have data for this session.",
        "May I suggest an easier week?",  # bare month name, no day/year/framing word
    ):
        r = states_window(answer(text), ref)
        assert r["score"] == 0 and r["key"] == "states_window", text
    assert states_window(answer("anything"), case("last_z2_ride").outputs())["score"] is None
```

with:

```python
        "Weight fell from 75.4 kg on 9/13/2026 to 74.0 kg.",
        "Sept. 3 was the hardest day.",  # abbreviation with a period
        # the question is ignored, the answer's own window counts
        "Show my weekly TSS for the last 8 weeks. Over the past 8 weeks it rose from 388 to 470.",
    ):
        assert states_window(inputs, answer(text), ref)["score"] == 1, text
    for text in (
        "TSS averaged 412 with one recovery week.",
        "Here is a weekly summary of your training.",
        "I don't have data for this session.",
        "May I suggest an easier week?",  # bare month name, no day/year/framing word
        "Aerobic decoupling 5% on the long ride.",  # a month prefix inside a word
        "Marathon 4 hours; augmented 2 reps; a decent 3 watts up.",
        "Show my weekly TSS for the last 8 weeks. Here they are: 388, 402, 470.",  # echoes the question
    ):
        r = states_window(inputs, answer(text), ref)
        assert r["score"] == 0 and r["key"] == "states_window", text
    plain = case("last_z2_ride")
    assert states_window(plain.inputs(), answer("anything"), plain.outputs())["score"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-analyze/tests/test_evals.py::test_states_window_accepts_iso_month_day_and_relative_windows -v`
Expected: `TypeError: states_window() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-analyze/src/tri_analyze/evals/evaluators.py`, replace:

```python
case scores None, which the pass rate leaves out. A bare month name only counts as a stated
window when it carries a day, a year, or an adjacent from/to/since/between/until word, so "in
May" does not count but "June 2026" and "from June to August" do."""
```

with:

```python
case scores None, which the pass rate leaves out. A bare month name only counts as a stated
window when it carries a day, a year, or an adjacent from/to/since/between/until word, so "in
May" does not count but "June 2026" and "from June to August" do; a month is a whole word or
its standard abbreviation, so "decoupling 5%" is not "Dec 5". Text that repeats the question
is not the answer's window and is ignored."""
```

replace:

```python
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
```

with:

```python
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
```

and replace:

```python
def states_window(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs.get("expects_window"):
        return {"key": "states_window", "score": None, "comment": "no window expected"}
    answer = str(outputs.get("answer") or "")
    hit: str | None = None
```

with:

```python
def states_window(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not reference_outputs.get("expects_window"):
        return {"key": "states_window", "score": None, "comment": "no window expected"}
    answer = str(outputs.get("answer") or "")
    question = str(inputs.get("question") or "").strip()
    if question:
        answer = re.sub(re.escape(question), " ", answer, flags=re.IGNORECASE)
    hit: str | None = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-analyze/tests -q`
Expected: all pass. (The month patterns keep every existing positive: `Jul 20`, `Sep 13`, `20 July`, `June 2026`, `September 13th`, `from June`; the tightened `_MONTH` and the question strip were checked against all of them while drafting.)

- [ ] **Step 5: Commit**

```bash
git add packages/tri-analyze/src/tri_analyze/evals/evaluators.py packages/tri-analyze/tests/test_evals.py
git commit -m "fix(analyze): states_window matches whole month names and ignores the echoed question"
```

---

### Task 19: B1 a turn during a paused review drops the review

**Files:**
- Modify: `packages/tri-web/src/tri_web/schemas.py:91-93`
- Modify: `packages/tri-web/src/tri_web/app.py:17, 52-54`
- Modify: `packages/tri-web/src/tri_web/routes/coach.py:17, 42-46`
- Modify: `web/src/components/chat/Chat.tsx:8-10, 22-30, 70-76`
- Modify: `web/src/components/chat/useTurnStream.ts:94-98`
- Modify: `web/src/pages/Today.tsx:25`
- Test: `packages/tri-web/tests/test_routes_coach.py` (append)
- Test: `web/tests/chat.test.tsx:7-16` (edit the harness) and append
- Test: `web/tests/turnStream.test.tsx` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: `tri_web.schemas.Paused(Exception)`; `POST /api/coach/turns` is 409 `{"reason": "paused"}` while a review is waiting (busy still wins with `{"running": ...}`); `Chat` gains a required prop `paused: boolean`, disables the composer with the hint `answer the review first`; `useTurnStream` shows `answer the review first` for a 409 `{"reason": "paused"}`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-web/tests/test_routes_coach.py`:

```python
async def test_a_turn_during_a_paused_review_is_409_and_keeps_the_review(
    nocommit, runtime, client, parse_sse
):
    tp, kw = proposing(nocommit)
    rt = runtime(**kw)
    async with client(rt) as c:
        await c.post("/api/coach/turns", json={"text": "my knee hurts"})
        r = await c.post("/api/coach/turns", json={"text": "never mind"})
        assert r.status_code == 409 and r.json() == {"reason": "paused"}
        thread = (await c.get("/api/coach/thread")).json()
        assert thread["paused"]["proposals"][0]["id"] == "p1"
        assert [m["role"] for m in thread["messages"]].count("user") == 1
        r = await c.post("/api/coach/review", json={"action": "reject"})
        assert r.status_code == 200 and parse_sse(r.text)[-1][0] == "done"
        assert (await c.get("/api/coach/thread")).json()["paused"] is None
    assert tp.calls == []
    assert not rt.lock.locked() and rt.running is None
```

In `web/tests/chat.test.tsx`, replace:

```tsx
function Harness() {
  const stream = useTurnStream();
  const thread = useThread();
  return (
    <>
      <output data-testid="probe" data-status={stream.state.status} data-running={thread.data?.running ?? "none"} />
      <Chat thread={thread.data} stream={stream} gate={null} />
    </>
  );
}
```

with:

```tsx
function Harness({ paused = false }: { paused?: boolean }) {
  const stream = useTurnStream();
  const thread = useThread();
  return (
    <>
      <output data-testid="probe" data-status={stream.state.status} data-running={thread.data?.running ?? "none"} />
      <Chat thread={thread.data} stream={stream} gate={null} paused={paused} />
    </>
  );
}
```

and append:

```tsx
test("a paused review disables the composer with the hint to answer it first", async () => {
  stubServer(() => threadEmpty(), () => openStream());
  renderWith(<Harness paused />);
  const probe = screen.getByTestId("probe");
  await waitFor(() => expect(probe).toHaveAttribute("data-running", "none"));
  expect(probe).toHaveAttribute("data-status", "idle");
  expect(screen.getByLabelText("Message")).toBeDisabled();
  expect(screen.getByText("answer the review first")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
});
```

Append to `web/tests/turnStream.test.tsx`:

```tsx
test("a 409 with reason paused says to answer the review first", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ reason: "paused" }), { status: 409 }));
  const { result } = renderHook(() => useTurnStream(), { wrapper: wrapper(client) });
  await act(() => result.current.send("never mind"));
  expect(result.current.state.status).toBe("idle");
  expect(result.current.state.error).toBe("answer the review first");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["thread"] });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_routes_coach.py::test_a_turn_during_a_paused_review_is_409_and_keeps_the_review -v`
Expected: fails at `assert r.status_code == 409` with `200 == 409` (the second turn streams and drops the review).

Run: `npm --prefix web test`
Expected: vitest strips types, so the new `chat.test.tsx` test renders with the unknown prop and fails at `expect(screen.getByLabelText("Message")).toBeDisabled()`; the new `turnStream.test.tsx` test fails with `expected 'nothing is waiting for review' to be 'answer the review first'`. (`npm --prefix web run build` would refuse the harness with `Property 'paused' does not exist on type 'Props'` until Step 3.)

- [ ] **Step 3: Write the implementation**

In `packages/tri-web/src/tri_web/schemas.py`, replace:

```python
class NoReview(Exception):
    """Nothing is paused at the gate."""
```

with:

```python
class NoReview(Exception):
    """Nothing is paused at the gate."""


class Paused(Exception):
    """A review is waiting at the gate; a new turn would drop it."""
```

In `packages/tri-web/src/tri_web/app.py`, replace:

```python
from tri_web.schemas import EditRejected, NoReview
```

with:

```python
from tri_web.schemas import EditRejected, NoReview, Paused
```

and replace:

```python
    @app.exception_handler(NoReview)
    async def no_review(request: Request, exc: NoReview) -> JSONResponse:
        return JSONResponse({"reason": "no_review"}, status_code=409)
```

with:

```python
    @app.exception_handler(NoReview)
    async def no_review(request: Request, exc: NoReview) -> JSONResponse:
        return JSONResponse({"reason": "no_review"}, status_code=409)

    @app.exception_handler(Paused)
    async def paused(request: Request, exc: Paused) -> JSONResponse:
        return JSONResponse({"reason": "paused"}, status_code=409)
```

In `packages/tri-web/src/tri_web/routes/coach.py`, replace:

```python
from tri_web.schemas import EditRejected, NoReview, ReviewIn, SchemaOut, TurnIn, ValidateIn, YamlOut
```

with:

```python
from tri_web.schemas import (
    EditRejected,
    NoReview,
    Paused,
    ReviewIn,
    SchemaOut,
    TurnIn,
    ValidateIn,
    YamlOut,
)
```

(ruff format may fold this back onto one line if it fits in 100 columns; accept its layout) and replace:

```python
@router.post("/turns")
async def post_turn(body: TurnIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    run = await start_turn(rt, {"messages": [HumanMessage(body.text)]}, kind="turn")
    return sse_response(run)
```

with:

```python
@router.post("/turns")
async def post_turn(body: TurnIn, request: Request) -> StreamingResponse:
    rt = _runtime(request)
    if rt.lock.locked():
        raise Busy(rt.running or "turn")
    if paused_review(await rt.graph.aget_state(cfg(rt))) is not None:
        raise Paused()  # a new input would restart the graph and drop the waiting review
    run = await start_turn(rt, {"messages": [HumanMessage(body.text)]}, kind="turn")
    return sse_response(run)
```

In `web/src/components/chat/Chat.tsx`, replace:

```tsx
type Props = { thread: ThreadView | undefined; stream: ReturnType<typeof useTurnStream>; gate: ReactNode };

export default function Chat({ thread, stream, gate }: Props) {
```

with:

```tsx
type Props = { thread: ThreadView | undefined; stream: ReturnType<typeof useTurnStream>; gate: ReactNode; paused: boolean };

export default function Chat({ thread, stream, gate, paused }: Props) {
```

replace:

```tsx
  const busy = state.status === "busy";
  // A lost stream stays busy while the thread catches up; the lost sentence wins over the busy one.
  const hint = state.lost
    ? "connection lost, reloading the conversation"
    : busy
      ? `a ${state.busyWith} is running`
      : thread?.stuck
        ? "the last run stopped early, send any message to continue"
        : undefined;
```

with:

```tsx
  const busy = state.status === "busy";
  // A lost stream stays busy while the thread catches up; the lost sentence wins over the busy one.
  // While a review waits at the gate the server refuses a turn (409 paused), so the composer says so.
  const hint = state.lost
    ? "connection lost, reloading the conversation"
    : busy
      ? `a ${state.busyWith} is running`
      : paused
        ? "answer the review first"
        : thread?.stuck
          ? "the last run stopped early, send any message to continue"
          : undefined;
```

and replace:

```tsx
        disabled={busy || state.status === "streaming"}
```

with:

```tsx
        disabled={busy || state.status === "streaming" || paused}
```

In `web/src/components/chat/useTurnStream.ts`, replace:

```ts
            // A 409 without `running` (e.g. { reason: "no_review" }) means nothing is waiting
            // for review, not that something else is running: stay idle, surface the message.
            setState((s) => ({ ...s, status: "idle", error: "nothing is waiting for review" }));
```

with:

```ts
            // A 409 without `running` is about the gate, not another run: { reason: "paused" }
            // refused a turn because a review is waiting; { reason: "no_review" } refused a
            // decision because nothing is. Stay idle, surface the message.
            const reason = (e.body as { reason?: string } | null)?.reason;
            setState((s) => ({ ...s, status: "idle", error: reason === "paused" ? "answer the review first" : "nothing is waiting for review" }));
```

In `web/src/pages/Today.tsx`, replace:

```tsx
      <Chat thread={thread.data} stream={stream} gate={gate} />
```

with:

```tsx
      <Chat thread={thread.data} stream={stream} gate={gate} paused={paused != null} />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests -q`
Expected: all pass (`test_busy_is_409_with_the_running_kind` still gets `{"running": "checkin"}`: the busy check comes first).

Run: `npm --prefix web test && npm --prefix web run lint && npm --prefix web run build`
Expected: all pass, lint clean, `tsc -b` clean.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-web/src/tri_web/schemas.py packages/tri-web/src/tri_web/app.py packages/tri-web/src/tri_web/routes/coach.py packages/tri-web/tests/test_routes_coach.py web/src/components/chat/Chat.tsx web/src/components/chat/useTurnStream.ts web/src/pages/Today.tsx web/tests/chat.test.tsx web/tests/turnStream.test.tsx
git commit -m "fix(web): refuse a turn while a review is paused; composer says to answer it first"
```

---

### Task 20: B2 500 bodies carry the exception text

**Files:**
- Modify: `packages/tri-web/src/tri_web/app.py:63-66`
- Test: `packages/tri-web/tests/test_app.py` (create)
- Test: `packages/tri-web/tests/test_routes_coach.py:177-186` (edit the existing assertion)

**Interfaces:**
- Consumes: nothing new
- Produces: the unexpected-exception handler returns `{"detail": "internal error"}` and calls `create_app`'s `log` with `internal error on <METHOD> <path>: <Type>: <text>`.

**Note for the assembler:** the spec names `test_app.py`, which does not exist; this task creates it. The existing `test_route_errors_return_detail_only` in `test_routes_coach.py` asserts the old body and is edited here.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-web/tests/test_app.py`:

```python
"""create_app: an unexpected exception is a 500 with a fixed body; the text goes to the log."""

import httpx
import pytest

from tri_web.app import create_app

pytestmark = pytest.mark.db


async def test_an_unexpected_error_logs_the_text_and_returns_a_fixed_body(runtime, monkeypatch):
    rt = runtime()

    async def boom(config):
        raise RuntimeError("psycopg went away")

    monkeypatch.setattr(rt.graph, "aget_state", boom)
    lines: list[str] = []
    transport = httpx.ASGITransport(app=create_app(rt, log=lines.append), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}
    assert lines == ["internal error on GET /api/coach/thread: RuntimeError: psycopg went away"]
```

In `packages/tri-web/tests/test_routes_coach.py`, replace:

```python
    rt.graph.aget_state = boom  # type: ignore[method-assign]
    async with client(rt) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "RuntimeError: psycopg went away"}
```

with:

```python
    rt.graph.aget_state = boom  # type: ignore[method-assign]
    async with client(rt) as c:
        r = await c.get("/api/coach/thread")
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-web/tests/test_app.py packages/tri-web/tests/test_routes_coach.py::test_route_errors_return_detail_only -v`
Expected: both fail with `{'detail': 'RuntimeError: psycopg went away'} == {'detail': 'internal error'}`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-web/src/tri_web/app.py`, replace:

```python
    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # uvicorn's error log keeps the traceback; the body never does
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)
```

with:

```python
    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # the text goes to the log (uvicorn's error log keeps the traceback); the body is fixed
        log(f"internal error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
        return JSONResponse({"detail": "internal error"}, status_code=500)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-web/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-web/src/tri_web/app.py packages/tri-web/tests/test_app.py packages/tri-web/tests/test_routes_coach.py
git commit -m "fix(web): 500 bodies say internal error; the exception text goes to the log"
```


---

### Task 21: Final checks

**Files:**
- Modify: nothing new; this task verifies the branch.

**Interfaces:**
- Consumes: every task above.
- Produces: nothing.

- [ ] **Step 1: The suite, with 006 applied**

If Brian has applied 006 to the test database, run `uv run pytest -q -rs` and confirm no test in this plan's files is skipped for a missing column or index: `uv run pytest -q -rs 2>&1 | grep -i "006\|bound\|source_sha\|title_idx\|tp_plan_applied"` prints nothing. If 006 is not applied yet, report the skipped names and continue.

- [ ] **Step 2: Nothing this plan touched still reads the old shapes**

Run: `rg -n "line\[1:\]\.split\(\)\[0\]|weekly = float\(tss_row\[\"total\"\]\) / 4|first = week_monday\(today\)$" packages`
Expected: no output.

- [ ] **Step 3: Vault copies**

For every `*.md` file changed on this branch (`git diff --name-only main...HEAD -- '*.md'`), copy it to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, READMEs as `readme.md`.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints (plus the web command for the two web tasks).
Expected: all pass; `git status` clean.

- [ ] **Step 5: Report**

List for Brian: the final test count against B, the tests that skip until 006 is applied, and the evals to rerun after merge (`tri-analyze eval` (A2 changes an evaluator), `tri-coach eval` (K3 changes the apply report)).
