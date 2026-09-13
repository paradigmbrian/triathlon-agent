# tri-coach Plan 4 of 4: Check-in, Follow-on Gate and Routing Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the coach (spec milestone 4). After an approved plan change moves sessions, nutrition is regenerated from the stored plan and comes back as a second gate in the same command. `tri-coach check-in` runs the weekly checklist unattended, writes a `checkin` memory entry, and exits with the planning check-in's codes. `tri-coach eval` runs a LangSmith routing dataset (lab questions included) with three evaluators. The approval/pending defects parked by plan 2 and `ask_analyst`'s spec §9 gap are fixed on the way.

**Architecture:** The graph gains `apply -> nutrition` when `regenerate_after_apply` is set. The apply node sets it (and a regenerate `Brief`) when planning changed sessions without error and `nutrition_targets` has rows in the horizon. The nutrition node then runs the embedded graph's regenerate entry and appends a `[follow-on]` `HumanMessage`, so the coach narrates and calls `propose_changes` again. Review and apply get a `carried` state key, so held proposals a change set does not name survive an approve or a reject. Review refuses proposals without changes. Apply catches an exception per domain and holds that domain's changes. `tri_coach/checkin.py` mirrors `tri_planning.checkin` over the coach REPL's `run_turn`. `tri_coach/evals/` runs the coach model over stub tools with the real rules and names, and scores the route taken, pure questions and brief quality. The prompt becomes `PROMPT_VERSION = "3"`: follow-on rule, analyst-failure rule, check-in checklist, and a routing line that consults planning alone for load changes.

**Tech Stack:** langgraph 1.2.11, langchain 1.4.0 `create_agent`, langsmith 0.12.2 (`aevaluate`, evaluators taking `inputs`, `outputs`, `reference_outputs`), pydantic 2, typer, psycopg 3, pytest with `tri_core.testing.ScriptedChatModel` and the rolled-back `db` fixture.

**Spec:** `docs/superpowers/specs/2026-09-11-tri-coach-design.md` (§5.1 checkin entry, §6.1 state, §6.3 edges, §6.4 prompt, §6.5 follow-on gate, §8 check-in, §9 errors, §11 testing, §12 evaluation, §13 milestone 4). Plans 1 to 3 are merged; `main` is at 354ef39.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-coach-04 -b feat/tri-coach-04 main`, copy `.env`, `uv sync`. Other Claude sessions share the main checkout. Baseline before Task 1: `729 passed, 5 skipped` (all five are `--live`).
- No new dependencies anywhere; `tri-coach` already depends on `langsmith`. No edits under `packages/tri-core`, `packages/tri-analyze`, `packages/tri-planning`, `packages/tri-nutrition`, `packages/tri-wellness`. The root `pyproject.toml` is untouched.
- Invariants (spec §6.3, §6.6), preserved by construction: no write tool is ever bound to a model. The analyst gains only `read_intake_vs_targets`, selected with `filter_tools`. The only path into either package's `apply_changes` is the coach's `apply` node, reached only from `review`. The eval target binds stub tools and never reaches a sub-graph, the database or a device.
- No migration. Tests write only through the rolled-back fixtures (`nocommit`, `ndb`, `ldb`). Eval and check-in tests need no database, no LangSmith and no Anthropic key.
- `LANGSMITH_TRACING=false` in `.env`; tests must not depend on tracing.
- `PROMPT_VERSION` becomes `"3"`; the eval experiment is `coach-v3`.
- The fixed check-in request is exactly `Run the coach check-in.` (constant `CHECKIN_REQUEST` in `tri_coach/prompts/coach.py`).
- Git commits are permitted (Brian's standing permission). Commit per task on the feature branch. End every commit message with the `Co-Authored-By:` and `Claude-Session:` trailer lines of the session executing the plan.
- Definition of done per task, in order: `uv run ruff format packages/tri-coach`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. The only acceptable pytest warning is the pre-existing langsmith `ast.Str` DeprecationWarning.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`, with kebab-case names (`readme.md` for READMEs). SDD scratch (`.superpowers/`) goes to that vault's `.superpowers/sdd/<plan>/` at the end, as for earlier plans.

### Facts verified while writing this plan (against `main` 354ef39)

1. `CoachState` keys: `messages`, `brief`, `proposals`, `proposal_request`, `pending`, `review_decision`, `reports`, `last_error`. `start_node` clears all but `messages` and re-emits `pending`. `apply -> END` is a static edge today.
2. `Brief(domain, instruction, tool_call_id: str, message_id: str, regenerate=False)`. `result_message(brief, proposal)` in `graph/nodes/planning.py` builds the `ToolMessage` from the two ids.
3. The nutrition graph's regenerate entry: `build_graph(..., embedded=True).ainvoke({"targets_requested": True, "regenerate_from": "checkin"}, config)` routes `route -> targets -> fuel -> END`. The output has `pending_changes` (today's `set_day_targets` when today's row needs a Garmin write, plus fuel notes), `pending_summary` and `last_error`, and no messages. With a profile, no designed weeks and no workouts in the horizon, it makes no model call (plan 1's `test_regenerate_entry_routes_to_targets_and_ends_with_pending_changes`).
4. `nrepo.upsert_targets(conn, [DayTarget(...)])` inserts rows with `written_to_garmin` false, so `targets_needing_write` returns today and the regenerate proposes one `set_day_targets` change. `DayType` includes `"easy"`.
5. `review_node` resolves ids against `state["proposals"]` plus `state["pending"].proposals`. On reject it sets `pending = None`. On approve it sets `pending` to the requested set only. It never checks that a proposal has changes.
6. `apply` calls `repo.derive_phase`, `apply_planning` and `apply_nutrition` with no exception handling. `ApplyResult.error` covers MCP failures inside `apply_changes`; anything else raises out of the node.
7. `create_agent` built with `make_subagent` stops the loop after a tool created with `StructuredTool.from_function(..., return_direct=True)`. Probe: a scripted `consult_planning` then `propose_changes` made 2 model calls and ended on the `ToolMessage`.
8. `graph.aupdate_state(cfg, {"pending": ...}, as_node="start")` on a fresh `InMemorySaver` thread leaves `next == ("coach",)`. A following `ainvoke({"messages": [...]})` starts from `START`, and `start` re-emits the seeded `pending` (probe).
9. `tri_nutrition.tools.checkin.make_checkin_tools(garmin, connect, today)` returns `read_intake_vs_targets` (read-only), `record_fuel_feedback` (writes the Store) and `propose_target_changes`. `tri_core.mcp.live_tools.filter_tools(tools, allow)` keeps only the allowed names, in allow order.
10. `tri_planning.checkin.run_checkin` is the exit-code pattern: 0 ok, 1 error or incomplete apply, 2 no plan, 3 paused or refused. The coach REPL has `run_turn(graph, payload, thread_id, out) -> TurnPrinter` (`.error`, `.interrupt`), `render_review(payload)` and `_paused_review(snap)`. `_review_dialogue` handles only `/quit` and `/pending`.
11. `tri_nutrition.evals.run.pass_rates(rows)` is generic (skips `score is None`). langsmith 0.12.2 passes `reference_outputs` (the example's outputs) to function evaluators that name it. `langchain_core.messages.convert_to_messages` maps `{"role": "user" | "assistant", "content": ...}`.
12. `ScriptedChatModel.with_structured_output(Model)` works when the script holds `tool_call("<Model name>", {...})` (nutrition's judge test).
13. `analyst_tools_for(servers, db_url, today)` returns `query_training_db`, the allow-listed live tools and `read_body_composition`; `test_servers.py` pins the order.

### Decisions this plan makes where the spec is silent or its literal reading fails

- **The regenerate `Brief` has no tool call.** `tool_call_id` and `message_id` become optional (`None`). `result_message` asserts both are set, since only consultations use it.
- **The follow-on result is a `HumanMessage` starting `[follow-on]`**, not a `ToolMessage`: no tool call is waiting for it. This matches the `[review]` convention, and the history stays valid for Anthropic (an `AIMessage` apply report, then a human-role message).
- **Apply clears `proposals`.** Applied proposals are consumed, so the follow-on proposal is `p1` and an applied id can never be re-proposed in the same run.
- **Held proposals survive a change set that does not name them** (parked: reject cleared them; re-proposing `held-planning` alone dropped `held-nutrition`). Review computes `carried`: held proposals not in the request. A reject leaves them in `pending`; an approve hands them to apply, which holds them again next to any new remainder, merging a shared stable id.
- **Review refuses a proposal without changes** (parked: a question-only id reached apply) with a `[review]` message back to the coach.
- **An exception inside one domain's apply is reported and held** (parked: a psycopg error left `pending` stale). The domain's changes stay in `pending` under the stable id with an "unverified" summary, the other domain still runs, and regeneration is skipped (spec §9).
- **Slash commands work at the review gate** (parked).
- **The check-in memory entry is written before `propose_changes`**, because `propose_changes` ends the turn; spec §8 says "finally". `remember(kind="checkin")` without `until` defaults to fourteen days out (spec §5.1).
- **`--yes` approves the follow-on gate too**, at most two gates. The second gate only aligns nutrition with the plan change the athlete opted to approve.
- **The analyst reads intake:** `read_intake_vs_targets` joins the analyst's tools, so the checklist's intake item has a read path.
- **Routing classes add `wellness`** (spec §13 lab-question cases). A case lists every acceptable route. `no_unrequested_adjustment` and the brief judge score `None` (excluded from the pass rate) when a case is not a pure question or the turn made no brief.
- **Handoff runs carry the tag `domain:planning` or `domain:nutrition`; check-in runs carry `checkin`** (spec §12).
- **Out of scope, still parked:** the `← ask_analyst` line glued to the analyst's streamed text; the nutrition half of the review listing one line per change.

---

## File Structure

```
packages/tri-coach/src/tri_coach/
  models.py                  Brief.tool_call_id / message_id optional
  graph/state.py             + carried, regenerate_after_apply
  graph/graph.py             start clears both; after_apply; apply -> nutrition | END
  graph/nodes/review.py      carried; refuses proposals without changes
  graph/nodes/apply.py       per-domain exception handling; merge_held; regenerate decision;
                             clears proposals
  graph/nodes/nutrition.py   regenerate path, proposal_from_regenerate, follow_on_message, domain tag
  graph/nodes/planning.py    domain tag; result_message asserts the ids
  graph/deps.py              analyst_tools_for(..., connect) adds read_intake_vs_targets
  tools/analyst.py           a failure returns as the tool result
  tools/memory.py            checkin kind documented; default until 14 days
  prompts/coach.py           PROMPT_VERSION "3"; CHECKIN_REQUEST; follow-on, failure, routing,
                             check-in checklist
  repl.py                    run_turn(tags=); paused_review public; slash commands at review;
                             prints the follow-on message
  checkin.py                 NEW: run_checkin and exit codes
  cli.py                     check-in and eval commands
  evals/__init__.py          NEW
  evals/cases.py             NEW: EvalCase, CASES, ROUTES
  evals/target.py            NEW: stub_tools, classify, run_case, make_target
  evals/evaluators.py        NEW: routing_accuracy, no_unrequested_adjustment, make_brief_judge
  evals/run.py               NEW: dataset, run_eval, render_pass_rates
packages/tri-coach/tests/
  test_graph_apply.py        held/reject/refusal/exception tests; the follow-on second gate
  test_nodes.py              NEW: node tags, regenerate mapping, after_apply (no database)
  test_tools.py              analyst failure
  test_servers.py            analyst tool list
  test_memory.py             checkin default until
  test_prompt.py             v3 phrases
  test_repl.py               follow-on printing; slash commands at review
  test_checkin.py            NEW: refusal and exit codes over a stub graph
  test_evals.py              NEW
  test_cli.py                check-in, eval
packages/tri-coach/README.md, README.md, docs/superpowers/specs/2026-09-11-tri-coach-design.md (status line)
```

---
### Task 1: Review and apply keep held changes, refuse empty proposals, survive a raising apply

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/state.py`, `packages/tri-coach/src/tri_coach/graph/graph.py` (`start_node` only), `packages/tri-coach/src/tri_coach/graph/nodes/review.py`, `packages/tri-coach/src/tri_coach/graph/nodes/apply.py`
- Test: `packages/tri-coach/tests/test_graph_apply.py`

**Interfaces:**
- Consumes: fact 5, fact 6, fact 8; `tri_coach.testing` (`CFG`, `consult`, `move_call`, `propose`, `seed_active_plan`).
- Produces: `CoachState.carried: list[Proposal]` (held proposals the request did not name; set by `review`, consumed by `apply`, cleared by `start`); `review_node` refusal `"[review] <ids> carry no changes ..."`; `tri_coach.graph.nodes.apply.merge_held(carried: list[Proposal], new: list[Proposal]) -> list[Proposal]`, `raised_report(domain: Domain, n: int, exc: Exception) -> ApplyReport`, `HELD_IDS`.

- [ ] **Step 1: Worktree**

```bash
cd /Users/brian/Development/paradigm/fitness_agents/triathlon_agent
git worktree add ../triathlon_agent-coach-04 -b feat/tri-coach-04 main
cp .env ../triathlon_agent-coach-04/.env
cd ../triathlon_agent-coach-04 && uv sync && uv run pytest -q 2>&1 | tail -1
```
Expected: `729 passed, 5 skipped, 1 warning`. Every later step runs in `../triathlon_agent-coach-04`.

- [ ] **Step 2: Write the failing tests**

Append to `packages/tri-coach/tests/test_graph_apply.py` (add `from tri_coach.graph.nodes.apply import merge_held` and `from tri_coach.models import ChangeSet, Proposal` to the imports):
```python
def held_set() -> ChangeSet:
    return ChangeSet(
        narration="Held from the last apply.",
        proposals=[
            Proposal.model_validate(
                {
                    "id": "held-planning",
                    "domain": "planning",
                    "summary": "1 planning changes held from the last apply",
                    "changes": [
                        {
                            "op": "move",
                            "tp_workout_id": "w1",
                            "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                            "reason": "rest day",
                        }
                    ],
                }
            ),
            Proposal.model_validate(
                {
                    "id": "held-nutrition",
                    "domain": "nutrition",
                    "summary": "1 nutrition changes held from the last apply",
                    "changes": [
                        {
                            "op": "set_day_targets",
                            "target_key": MONDAY.isoformat(),
                            "day": MONDAY.isoformat(),
                            "payload": {"calorie_goal": 2800},
                            "reason": "extend horizon",
                        }
                    ],
                }
            ),
        ],
    )


async def test_re_proposing_one_held_proposal_keeps_the_other_held(ndb, make_deps, mem_store):
    seed_active_plan(ndb)
    tp = FakeTp()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[propose("Retry the plan part.", ["held-planning"])],
    )
    await graph.aupdate_state(CFG, {"pending": held_set()}, as_node="start")
    out = await graph.ainvoke({"messages": [HumanMessage("retry the plan part")]}, CFG)
    assert [p["id"] for p in out["__interrupt__"][0].value["proposals"]] == ["held-planning"]
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    assert [p.id for p in out["pending"].proposals] == ["held-nutrition"]
    assert out["carried"] == []


async def test_rejecting_a_held_proposal_keeps_the_ones_it_did_not_name(
    ndb, make_deps, mem_store
):
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            propose("Retry the plan part.", ["held-planning"]),
            AIMessage(content="Dropped the plan part."),
        ],
    )
    await graph.aupdate_state(CFG, {"pending": held_set()}, as_node="start")
    await graph.ainvoke({"messages": [HumanMessage("retry the plan part")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "not now"}), CFG)
    assert [p.id for p in out["pending"].proposals] == ["held-nutrition"]
    assert out["pending"].narration == "Held from the last apply."


async def test_a_proposal_without_changes_is_refused_at_review(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Lighten the week."),
            propose("Lighter week.", ["p1"]),
            AIMessage(content="Planning asked which session hurt; I will ask you."),
        ],
        planning=[AIMessage(content="Which session hurt: the run or the ride?")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]}, CFG)
    assert "__interrupt__" not in out and models["coach"].calls == 3
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("[review] p1 carry no changes")
        for m in out["messages"]
    )
    assert out["proposal_request"] is None and out["pending"] is None


async def test_an_exception_inside_apply_is_reported_and_the_changes_held(
    nocommit, make_deps, mem_store, monkeypatch
):
    from tri_coach.graph import nodes

    async def boom(*args, **kwargs):
        raise RuntimeError("psycopg went away")

    monkeypatch.setattr(nodes.apply, "apply_planning", boom)
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    report = out["reports"][0]
    assert report.domain == "planning" and report.applied == 0 and report.remaining == 1
    assert "RuntimeError: psycopg went away" in out["last_error"]
    held = out["pending"].proposals[0]
    assert held.id == "held-planning" and len(held.changes) == 1 and "unverified" in held.summary
    assert (await graph.aget_state(CFG)).next == ()


def test_merge_held_joins_a_shared_stable_id():
    plan = held_set().proposals[0]
    nut = held_set().proposals[1]
    merged = merge_held([plan, nut], [plan.model_copy(update={"summary": "new"})])
    assert [p.id for p in merged] == ["held-planning", "held-nutrition"]
    assert len(merged[0].changes) == 2 and merged[0].summary.startswith("2 planning changes")
    assert merge_held([], [nut]) == [nut] and merge_held([nut], []) == [nut]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_graph_apply.py -q`
Expected: collection fails with `ImportError: cannot import name 'merge_held'`. After Step 5 alone, the held tests fail because `pending` is `None` or holds `held-planning`, the refusal test fails with an interrupt, and the exception test fails with `RuntimeError`.

- [ ] **Step 4: State and start**

`packages/tri-coach/src/tri_coach/graph/state.py`: add after `pending`:
```python
    carried: list[Proposal]  # held proposals the change set did not name; review -> apply
```
`packages/tri-coach/src/tri_coach/graph/graph.py`, in `start_node`'s returned dict, add `"carried": [],` after `"proposal_request": None,`.

- [ ] **Step 5: Review node**

Replace `packages/tri-coach/src/tri_coach/graph/nodes/review.py` with:
```python
"""Review node: build the change set from the coach's proposal request, pause until the athlete
decides. On resume the node runs again from the top, so everything before interrupt() is a pure
function of state.

Held proposals (a partial apply's remainder in `pending`) that the request does not name are
`carried`: apply holds them again after an approve, and a reject leaves them pending."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from tri_coach.graph.state import CoachState
from tri_coach.models import ChangeSet, ReviewDecision


def _refusal(text: str) -> dict[str, Any]:
    return {"proposal_request": None, "messages": [HumanMessage(f"[review] {text}")]}


def review_node(state: CoachState) -> dict[str, Any]:
    request = state.get("proposal_request")
    held = state.get("pending")
    held_proposals = list(held.proposals) if held else []
    proposals = {p.id: p for p in held_proposals}
    proposals.update({p.id: p for p in state.get("proposals") or []})
    if request is None:
        return {
            "messages": [
                HumanMessage("[review] nothing to review; call propose_changes with proposal ids")
            ]
        }
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
    raw = interrupt(
        {
            "narration": pending.narration,
            "proposals": [p.model_dump(mode="json") for p in pending.proposals],
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {
        "pending": pending,
        "carried": carried,
        "proposal_request": None,
        "review_decision": decision,
    }
    if decision.action == "reject":
        note = decision.note or "no note given"
        # What was rejected is dropped; held proposals the request did not name stay pending.
        update["pending"] = (
            ChangeSet(narration=held.narration, proposals=carried) if held and carried else None
        )
        update["carried"] = []
        update["messages"] = [HumanMessage(f"Review rejected: {note}")]
    elif decision.action == "edit" and decision.proposals is not None:
        update["pending"] = ChangeSet(narration=pending.narration, proposals=decision.proposals)
    return update
```

- [ ] **Step 6: Apply node**

Replace `packages/tri-coach/src/tri_coach/graph/nodes/apply.py` with:
```python
"""Apply node: the only caller of the packages' apply_changes, planning first then nutrition,
with thread_id "coach". A bought plan that was just applied is adopted by one more embedded
planning run. Remaining changes stay in `pending` under a stable id (`held-planning`,
`held-nutrition`) so a later turn can re-propose them by that id, together with the held
proposals the approved set did not name (`carried`). An exception inside one domain's apply is
reported and that domain's changes are held unverified; the other domain still runs."""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.store.base import BaseStore

from tri_coach.graph.deps import CoachDeps
from tri_coach.graph.state import CoachState
from tri_coach.models import ApplyReport, ChangeSet, Domain, Proposal
from tri_nutrition.graph.nodes.apply import ApplyResult as NutritionResult
from tri_nutrition.graph.nodes.apply import apply_changes as apply_nutrition
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning import repo
from tri_planning.graph.nodes.apply import ApplyResult as PlanningResult
from tri_planning.graph.nodes.apply import apply_changes as apply_planning
from tri_planning.planning.models import CalendarChange


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


def raised_report(domain: Domain, n: int, exc: Exception) -> ApplyReport:
    return ApplyReport(
        domain=domain,
        applied=0,
        skipped=[],
        remaining=n,
        error=(
            f"apply raised {type(exc).__name__}: {exc}; some changes may already be written, "
            "check before re-proposing"
        ),
        sessions_changed=False,
    )


HELD_IDS: dict[str, str] = {"planning": "held-planning", "nutrition": "held-nutrition"}


def merge_held(carried: list[Proposal], new: list[Proposal]) -> list[Proposal]:
    """Carried held proposals first, then this apply's remainder; a shared stable id merges."""
    by_id = {p.id: p for p in carried}
    for p in new:
        prev = by_id.get(p.id)
        if prev is None:
            by_id[p.id] = p
            continue
        changes = [*prev.changes, *p.changes]
        by_id[p.id] = prev.model_copy(
            update={
                "changes": changes,
                "summary": f"{len(changes)} {p.domain} changes held from earlier applies",
                "overrides": {**(prev.overrides or {}), **(p.overrides or {})} or None,
            }
        )
    return list(by_id.values())


def make_apply_node(deps: CoachDeps, planning_graph: Any) -> Any:
    async def apply(
        state: CoachState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        pending = state.get("pending")
        assert pending is not None, "apply needs a pending change set"
        thread_id = str(config["configurable"]["thread_id"])
        reports: list[ApplyReport] = []
        held: list[Proposal] = []

        planning = [p for p in pending.proposals if p.domain == "planning"]
        if planning:
            # The domain decides the change type; the Proposal validator already typed them.
            changes = cast(list[CalendarChange], [c for p in planning for c in p.changes])
            try:
                with deps.planning_deps.connect() as conn:
                    _, goal_id, plan_id = repo.derive_phase(conn)
                r = await apply_planning(
                    deps.planning_deps, changes, thread_id, plan_id=plan_id, goal_id=goal_id
                )
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001 - reported and held; nutrition still runs
                reports.append(raised_report("planning", len(changes), exc))
                held.append(
                    Proposal(
                        id=HELD_IDS["planning"],
                        domain="planning",
                        summary=f"{len(changes)} planning changes held unverified: apply raised",
                        changes=changes,
                    )
                )
            else:
                report = report_from_planning(r)
                if r.tp_plan_applied and r.error is None:
                    # The adopt re-invoke reads TrainingPeaks again; TrainingPeaks was already
                    # written, so a failure here is reported, not raised.
                    try:
                        await planning_graph.ainvoke({"tp_plan_applied": True}, config)
                    except Exception as exc:  # noqa: BLE001 - any failure is reported
                        detail = f"the plan was applied but adopting it failed: {exc}"
                        joined = "; ".join(x for x in (report.error, detail) if x)
                        report = report.model_copy(update={"error": joined})
                reports.append(report)
                if r.remaining:
                    held.append(
                        Proposal(
                            id=HELD_IDS["planning"],
                            domain="planning",
                            summary=f"{len(r.remaining)} planning changes held from the last apply",
                            changes=r.remaining,
                        )
                    )

        nutrition = [p for p in pending.proposals if p.domain == "nutrition"]
        if nutrition:
            nchanges = cast(list[NutritionChange], [c for p in nutrition for c in p.changes])
            overrides: dict[str, Any] = {}
            for p in nutrition:
                overrides.update(p.overrides or {})
            try:
                rn = await apply_nutrition(
                    deps.nutrition_deps, store, nchanges, thread_id, overrides=overrides or None
                )
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001 - reported and held
                reports.append(raised_report("nutrition", len(nchanges), exc))
                held.append(
                    Proposal(
                        id=HELD_IDS["nutrition"],
                        domain="nutrition",
                        summary=f"{len(nchanges)} nutrition changes held unverified: apply raised",
                        changes=nchanges,
                        overrides=overrides or None,
                    )
                )
            else:
                reports.append(report_from_nutrition(rn))
                if rn.remaining:
                    held.append(
                        Proposal(
                            id=HELD_IDS["nutrition"],
                            domain="nutrition",
                            summary=(
                                f"{len(rn.remaining)} nutrition changes held from the last apply"
                            ),
                            changes=rn.remaining,
                            overrides=overrides or None,
                        )
                    )

        kept = merge_held(list(state.get("carried") or []), held)
        errors = [rep.error for rep in reports if rep.error]
        return {
            "reports": reports,
            "pending": ChangeSet(narration=pending.narration, proposals=kept) if kept else None,
            "carried": [],
            "review_decision": None,
            "last_error": "; ".join(errors) or None,
            "messages": [AIMessage("\n".join(rep.line() for rep in reports))],
        }

    return apply
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_graph_apply.py packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_resume.py -q`
Expected: all pass. The existing reject test still ends with `pending is None`, because nothing was held.

- [ ] **Step 8: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "fix(coach): held changes survive a change set that does not name them; review refuses empty proposals; a raising apply is reported and held"
```
(append the executing session's trailer lines to the message)

---
### Task 2: The follow-on gate: apply -> nutrition regenerate -> coach -> second review

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/models.py`, `packages/tri-coach/src/tri_coach/graph/state.py`, `packages/tri-coach/src/tri_coach/graph/graph.py`, `packages/tri-coach/src/tri_coach/graph/nodes/apply.py`, `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py`, `packages/tri-coach/src/tri_coach/graph/nodes/planning.py`, `packages/tri-coach/src/tri_coach/repl.py`
- Create: `packages/tri-coach/tests/test_nodes.py`
- Test: `packages/tri-coach/tests/test_graph_apply.py`, `packages/tri-coach/tests/test_repl.py`

**Interfaces:**
- Consumes: Task 1's `apply.py` (return dict, `HELD_IDS`), fact 3, fact 4.
- Produces: `Brief.tool_call_id: str | None = None`, `Brief.message_id: str | None = None`; `CoachState.regenerate_after_apply: bool`; `tri_coach.graph.graph.after_apply(state) -> str` (`"nutrition"` or `END`); `tri_coach.graph.nodes.apply.REGENERATE_INSTRUCTION: str`; `tri_coach.graph.nodes.nutrition.FOLLOW_ON = "[follow-on]"`, `proposal_from_regenerate(out: dict[str, Any], pid: str) -> Proposal`, `follow_on_message(proposal: Proposal) -> HumanMessage`; planning and nutrition nodes invoke their graphs with tags `domain:planning` / `domain:nutrition`; the apply node returns `proposals: []`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-coach/tests/test_nodes.py`:
```python
"""Coach graph nodes over stub sub-graphs: no database, no model."""

from langchain_core.messages import AIMessage
from langgraph.graph import END

from tri_coach.graph.graph import after_apply
from tri_coach.graph.nodes.nutrition import (
    FOLLOW_ON,
    follow_on_message,
    make_nutrition_node,
    proposal_from_regenerate,
)
from tri_coach.graph.nodes.planning import make_planning_node
from tri_coach.models import Brief

CONFIG = {"configurable": {"thread_id": "coach"}}


class Recorder:
    """A compiled sub-graph stand-in: records what it was invoked with, returns a fixed output."""

    def __init__(self, out):
        self.out = out
        self.inputs = []
        self.configs = []

    async def ainvoke(self, payload, config):
        self.inputs.append(payload)
        self.configs.append(config)
        return self.out


def test_after_apply_routes_to_nutrition_only_when_regeneration_is_due():
    assert after_apply({"regenerate_after_apply": True}) == "nutrition"
    assert after_apply({"regenerate_after_apply": False}) == END
    assert after_apply({}) == END


def test_a_regenerate_brief_needs_no_tool_call():
    b = Brief(domain="nutrition", instruction="regenerate", regenerate=True)
    assert b.tool_call_id is None and b.message_id is None


async def test_the_regenerate_brief_runs_the_targets_entry_and_appends_the_follow_on():
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
    out = await node({"brief": brief, "proposals": []}, CONFIG)
    assert graph.inputs == [{"targets_requested": True, "regenerate_from": "checkin"}]
    assert "domain:nutrition" in graph.configs[0]["tags"]
    assert out["brief"] is None and out["regenerate_after_apply"] is False
    p = out["proposals"][0]
    assert p.id == "p1" and p.question is None and p.changes[0].op == "set_day_targets"
    msg = out["messages"][0]
    assert msg.content.startswith(FOLLOW_ON) and "call propose_changes with p1" in msg.content


def test_a_regeneration_that_changes_nothing_or_breaks_a_bound_says_so():
    same = proposal_from_regenerate(
        {"pending_changes": [], "pending_summary": "already on Garmin", "last_error": None}, "p1"
    )
    assert same.changes == [] and same.question is None
    assert "no changes" in follow_on_message(same).content
    bad = proposal_from_regenerate(
        {"pending_changes": [], "pending_summary": None, "last_error": "kcal below floor"}, "p1"
    )
    assert bad.violations == ["kcal below floor"] and bad.summary == "kcal below floor"
    assert "state the violations" in follow_on_message(bad).content


async def test_consultations_carry_a_domain_tag():
    graph = Recorder({"pending_changes": [], "messages": [AIMessage(content="Which day?")]})
    node = make_planning_node(graph)
    brief = Brief(domain="planning", instruction="x", tool_call_id="c1", message_id="m1")
    out = await node({"brief": brief, "proposals": []}, CONFIG)
    assert "domain:planning" in graph.configs[0]["tags"]
    assert out["messages"][0].id == "m1" and out["proposals"][0].question == "Which day?"
```

Append to `packages/tri-coach/tests/test_graph_apply.py` (add `from tri_nutrition import repo as nrepo` and `from tri_nutrition.nutrition.models import DayTarget` to the imports):
```python
async def test_a_plan_change_that_moves_sessions_regenerates_nutrition_and_opens_a_second_gate(
    ndb, make_deps, mem_store
):
    seed_active_plan(ndb)
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    nrepo.upsert_targets(
        ndb,
        [
            DayTarget(
                day=MONDAY + timedelta(days=i),
                day_type="easy",
                session_kcal=0,
                total_kcal=2000,
                carbs_g=200,
                protein_g=150,
                fat_g=70,
                fluid_baseline_ml=2500,
                source="plan",
            )
            for i in range(3)
        ],
    )
    tp, garmin = FakeTp(), FakeGarmin()
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        garmin=garmin,
        coach=[
            consult("planning", "Move w1."),
            propose("Move it.", ["p1"]),
            propose("Today's targets follow the moved session.", ["p1"], "c10"),
        ],
        planning=[move_call(), AIMessage(content="ok")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("move it")]}, CFG)
    assert out["__interrupt__"][0].value["proposals"][0]["domain"] == "planning"

    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    second = out["__interrupt__"][0].value
    assert second["narration"].startswith("Today's targets")
    assert [(p["id"], p["domain"]) for p in second["proposals"]] == [("p1", "nutrition")]
    assert second["proposals"][0]["changes"][0]["op"] == "set_day_targets"
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("[follow-on]")
        for m in out["messages"]
    )
    assert garmin.calls == [] and models["nutrition"].calls == 0 and models["coach"].calls == 3

    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in garmin.calls] == ["set_nutrition_daily_settings"]
    assert [r.domain for r in out["reports"]] == ["nutrition"]
    assert out["regenerate_after_apply"] is False and out["pending"] is None
    assert (await graph.aget_state(CFG)).next == ()


async def test_no_regeneration_without_targets_in_the_horizon(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("move it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert out["reports"][0].sessions_changed is True and out["regenerate_after_apply"] is False
    assert out["proposals"] == [] and models["coach"].calls == 2
    assert (await graph.aget_state(CFG)).next == ()
```

Append to `packages/tri-coach/tests/test_repl.py` (add `HumanMessage` to the `langchain_core.messages` import):
```python
def test_printer_prints_the_follow_on_message_once():
    out: list[str] = []
    p = TurnPrinter(out.append)
    msg = HumanMessage("[follow-on] The approved plan change moved sessions.")
    p.on_event((), "updates", {"nutrition": {"messages": [msg]}})
    text = "".join(out)
    assert text.count("[follow-on] The approved plan change moved sessions.") == 1
    assert p.final_text == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_nodes.py packages/tri-coach/tests/test_graph_apply.py packages/tri-coach/tests/test_repl.py -q`
Expected: `test_nodes.py` fails to import `after_apply`; the two new graph tests fail on `KeyError: 'regenerate_after_apply'` or a missing second interrupt; the printer test fails on an empty output.

- [ ] **Step 3: Models and state**

`packages/tri-coach/src/tri_coach/models.py`, in `Brief`, replace the two id lines and the `regenerate` comment:
```python
    tool_call_id: str | None = None  # the consult_* call; None for the post-apply regenerate brief
    message_id: str | None = None  # the handoff ToolMessage the result replaces; None likewise
    regenerate: bool = False  # nutrition only: skip the sub-agent, go straight to targets
```
`packages/tri-coach/src/tri_coach/graph/state.py`: add after `carried`:
```python
    regenerate_after_apply: bool  # set by apply when planning moved sessions; routes to nutrition
```

- [ ] **Step 4: Graph edges**

`packages/tri-coach/src/tri_coach/graph/graph.py`:
- In the module docstring, replace the line `apply  -> END` with:
```
apply  -> nutrition                     (regenerate_after_apply: planning moved sessions and
                                         nutrition targets exist in the horizon)
apply  -> END                           (otherwise)
nutrition -> coach                      (a consultation, or the "[follow-on]" regeneration)
```
- In `start_node`'s returned dict add `"regenerate_after_apply": False,`.
- Add after `after_review`:
```python
def after_apply(state: CoachState) -> str:
    return "nutrition" if state.get("regenerate_after_apply") else END
```
- Replace `g.add_edge("apply", END)` with `g.add_conditional_edges("apply", after_apply, ["nutrition", END])`.

- [ ] **Step 5: Apply decides regeneration**

`packages/tri-coach/src/tri_coach/graph/nodes/apply.py`:
- Imports: add `from datetime import timedelta`, `from tri_nutrition import repo as nrepo`, and `Brief` to the `tri_coach.models` import.
- After `HELD_IDS`, add:
```python
REGENERATE_INSTRUCTION = "Regenerate targets and fueling from the stored plan after the apply."


def _regeneration_due(deps: CoachDeps, reports: list[ApplyReport]) -> bool:
    """Spec 6.3: planning moved sessions without error and nutrition targets exist in the
    horizon. A failed or partial planning apply skips it (spec 9)."""
    plan = next((r for r in reports if r.domain == "planning"), None)
    if plan is None or not plan.sessions_changed or plan.error is not None:
        return False
    today = deps.today()
    end = today + timedelta(days=deps.nutrition_deps.horizon_days - 1)
    with deps.connect() as conn:
        return bool(nrepo.list_targets(conn, today, end))
```
- In the node, replace the `return {...}` block with:
```python
        kept = merge_held(list(state.get("carried") or []), held)
        errors = [rep.error for rep in reports if rep.error]
        regenerate = _regeneration_due(deps, reports)
        return {
            "reports": reports,
            "pending": ChangeSet(narration=pending.narration, proposals=kept) if kept else None,
            "carried": [],
            "proposals": [],  # consumed: the follow-on proposal is p1, an applied id is gone
            "review_decision": None,
            "regenerate_after_apply": regenerate,
            "brief": (
                Brief(domain="nutrition", instruction=REGENERATE_INSTRUCTION, regenerate=True)
                if regenerate
                else None
            ),
            "last_error": "; ".join(errors) or None,
            "messages": [AIMessage("\n".join(rep.line() for rep in reports))],
        }
```

- [ ] **Step 6: Planning and nutrition nodes**

`packages/tri-coach/src/tri_coach/graph/nodes/planning.py`:
- Add `from langchain_core.runnables.config import merge_configs`.
- At the top of `result_message`, add:
```python
    assert brief.tool_call_id is not None and brief.message_id is not None, (
        "only a consultation brief has a tool call to answer"
    )
```
- In the node, replace `graph.ainvoke({...}, config)` with `graph.ainvoke({...}, merge_configs(config, {"tags": ["domain:planning"]}))`.

Replace `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py` with:
```python
"""Nutrition node: run the embedded nutrition graph on the brief and map its output to a Proposal
(with the sub-agent's profile overrides, persisted only if the athlete approves).

A regenerate brief (set by apply after planning moved sessions) skips the sub-agent: the graph's
targets entry rebuilds the horizon from the stored plan, and the result comes back to the coach
as a "[follow-on]" message, since no tool call is waiting for it."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_coach.graph.nodes.planning import result_message
from tri_coach.graph.state import CoachState
from tri_coach.models import Proposal
from tri_coach.text import last_ai_text
from tri_nutrition.prompts.checkin import BRIEF_PREFIX

FOLLOW_ON = "[follow-on]"


def proposal_from_nutrition(out: dict[str, Any], pid: str) -> Proposal:
    changes = list(out.get("pending_changes") or [])
    violations = [out["last_error"]] if out.get("last_error") else []
    overrides = out.get("profile_overrides") or None
    if not changes:
        return Proposal(
            id=pid,
            domain="nutrition",
            summary=out.get("pending_summary") or "",
            violations=violations,
            question=last_ai_text(out.get("messages", [])) or "no answer",
        )
    return Proposal(
        id=pid,
        domain="nutrition",
        summary=out.get("pending_summary") or "",
        changes=changes,
        violations=violations,
        overrides=overrides,
    )


def proposal_from_regenerate(out: dict[str, Any], pid: str) -> Proposal:
    """No sub-agent ran, so there is never a question: changes, or nothing, or violations."""
    error = out.get("last_error")
    return Proposal(
        id=pid,
        domain="nutrition",
        summary=out.get("pending_summary") or error or "",
        changes=list(out.get("pending_changes") or []),
        violations=[error] if error else [],
    )


def follow_on_message(proposal: Proposal) -> HumanMessage:
    if proposal.changes:
        ask = f"Narrate the consequence and call propose_changes with {proposal.id}."
    elif proposal.violations:
        ask = "Nothing can be written: state the violations and stop."
    else:
        ask = "It made no changes: say the nutrition targets stand and stop."
    return HumanMessage(
        f"{FOLLOW_ON} The approved plan change moved sessions, so nutrition was regenerated "
        f"from the stored plan.\n{proposal.render()}\n{ask}"
    )


def make_nutrition_node(graph: Any) -> Any:
    async def nutrition(state: CoachState, config: RunnableConfig) -> dict[str, Any]:
        brief = state.get("brief")
        assert brief is not None and brief.domain == "nutrition", (
            "nutrition node needs a nutrition brief"
        )
        cfg = merge_configs(config, {"tags": ["domain:nutrition"]})
        proposals = list(state.get("proposals") or [])
        pid = f"p{len(proposals) + 1}"
        if brief.regenerate:
            out = await graph.ainvoke({"targets_requested": True, "regenerate_from": "checkin"}, cfg)
            proposal = proposal_from_regenerate(out, pid)
            return {
                "brief": None,
                "regenerate_after_apply": False,
                "proposals": [*proposals, proposal],
                "messages": [follow_on_message(proposal)],
            }
        out = await graph.ainvoke(
            {"messages": [HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")]}, cfg
        )
        proposal = proposal_from_nutrition(out, pid)
        return {
            "brief": None,
            "proposals": [*proposals, proposal],
            "messages": [result_message(brief, proposal)],
        }

    return nutrition
```

- [ ] **Step 7: The REPL prints the follow-on**

`packages/tri-coach/src/tri_coach/repl.py`, in `TurnPrinter.on_event`, replace the branch condition
```python
                    and node in ("apply", "review")
```
with
```python
                    and node in ("apply", "review", "nutrition")
```
A consultation's nutrition update carries only its `ToolMessage` (handled by the branch above), so only the follow-on `HumanMessage` reaches this branch for `nutrition`. `chat_loop` already opens a second review when the resumed run ends in another interrupt.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass, 1 skipped (live).

- [ ] **Step 9: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): follow-on gate: a plan change that moves sessions regenerates nutrition and opens a second review; domain tags on handoff runs"
```
(append the executing session's trailer lines to the message)

---
### Task 3: The analyst: failures return as the tool result, and it reads logged intake

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/tools/analyst.py`, `packages/tri-coach/src/tri_coach/graph/deps.py`
- Test: `packages/tri-coach/tests/test_tools.py`, `packages/tri-coach/tests/test_servers.py`

**Interfaces:**
- Consumes: fact 9; `tri_coach.tools.wellness`'s failure pattern (`except GraphBubbleUp: raise`, then `except Exception`).
- Produces: `ask_analyst` returns `"The analyst failed (<Type>: <msg>); do not guess at the data it could not read."` instead of raising; `analyst_tools_for(servers, db_url, today, connect) -> list[BaseTool]`, ending with `read_body_composition, read_intake_vs_targets`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_tools.py`:
```python
async def test_ask_analyst_reports_a_failure_as_its_tool_result_instead_of_raising():
    @contextlib.contextmanager
    def broken_connect():
        raise RuntimeError("db is down")
        yield  # pragma: no cover - never reached; makes this a generator function

    analyst = ScriptedChatModel(script=[AIMessage(content="should never be called")])
    ask = make_analyst_tool(analyst, [], broken_connect, lambda: date(2026, 9, 14))
    result = await ask.ainvoke({"question": "what is my CTL?"})
    assert "RuntimeError" in result and "db is down" in result
    assert "do not guess" in result and analyst.calls == 0
```

In `packages/tri-coach/tests/test_servers.py`, add `import contextlib` at the top and change the `analyst_tools_for` test's call and expected list to:
```python
    tools = analyst_tools_for(
        servers,
        CoachSettings(_env_file=None).test_database_url,
        lambda: date(2026, 9, 14),
        lambda: contextlib.nullcontext(None),
    )
    names = [t.name for t in tools]
    assert names == [
        "query_training_db",
        "get_activity",
        "get_hrv_data",
        "tp_get_workout",
        "read_body_composition",
        "read_intake_vs_targets",
    ]
    assert not {"record_fuel_feedback", "propose_target_changes"} & set(names)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_servers.py -q`
Expected: the analyst test fails with `RuntimeError: db is down`; the servers test fails with `TypeError: analyst_tools_for() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: `tools/analyst.py`**

Add `from langgraph.errors import GraphBubbleUp` and replace the inner `ask_analyst` with:
```python
    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
        logged intake against nutrition targets, or how training compares to plan. It reads the
        database and the devices; it changes nothing. Ask one specific question at a time."""
        try:
            with connect() as conn:
                ctx = load_athlete_context(conn, today())
            agent = build_agent(model, tools, render_system_prompt(ctx, live), InMemorySaver())
            out = await agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"analyst-{uuid4()}"},
                    "recursion_limit": ANALYST_RECURSION_LIMIT,
                },
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
```
Update the module docstring's first sentence to end: `...and returns its final text, or the failure as text (spec 9).`

- [ ] **Step 4: `graph/deps.py`**

Add `from tri_nutrition.tools.checkin import make_checkin_tools`. Replace `analyst_tools_for` with:
```python
def analyst_tools_for(
    servers: Servers, db_url: str, today: Callable[[], date], connect: ConnectFactory
) -> list[BaseTool]:
    """query_training_db, the analyst's own live reads, and the two nutrition reads the coach's
    context lacks: body composition and logged intake against targets. Only the read is taken
    from nutrition's check-in tools; its writers are never bound."""
    return [
        make_query_tool(db_url),
        *filter_tools(servers.garmin_tools, ANALYST_GARMIN_TOOLS),
        *filter_tools(servers.tp_tools, ANALYST_TP_TOOLS),
        *make_garmin_read_tools(servers.garmin, today, only=("read_body_composition",)),
        *filter_tools(
            make_checkin_tools(servers.garmin, connect, today), ("read_intake_vs_targets",)
        ),
    ]
```
In `make_deps`, after `url = settings.database_url` add `connect = lambda: core_connect(url)  # noqa: E731`, use `connect=connect` in the `CoachDeps(...)` call, and `analyst_tools=analyst_tools_for(servers, url, today, connect)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_servers.py -q`
Expected: all pass.

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "fix(coach): an analyst failure returns as the tool result; the analyst reads logged intake against targets"
```
(append the executing session's trailer lines to the message)

---

### Task 4: Prompt v3 and the check-in memory entry

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/prompts/coach.py`, `packages/tri-coach/src/tri_coach/tools/memory.py`
- Test: `packages/tri-coach/tests/test_prompt.py`, `packages/tri-coach/tests/test_memory.py`

**Interfaces:**
- Consumes: Task 2's `[follow-on]` message; Task 3's analyst failure text and intake read.
- Produces: `PROMPT_VERSION = "3"`; `CHECKIN_REQUEST = "Run the coach check-in."`; `COACH_RULES` with the follow-on rule, the failure rule, the load-change routing line and the `Check-in:` section; `tri_coach.tools.memory.CHECKIN_DAYS = 14`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-coach/tests/test_prompt.py`: import `CHECKIN_REQUEST` alongside `COACH_RULES`; change `assert PROMPT_VERSION == "2"` to `assert PROMPT_VERSION == "3"`; extend the phrase tuple in `test_rules_cover_policy_routing_and_memory` with:
```python
        "[follow-on]",
        "Consult no one in a follow-on",
        "say what could not be read",
        "needs consult_planning only",
        "logged intake against targets",
        "fewer than 2 means brief planning",
        "fewer than 7 days of targets left",
        "call remember with kind checkin",
        "Write it before propose_changes",
```
and append:
```python
def test_the_checklist_names_the_exact_check_in_request():
    assert CHECKIN_REQUEST == "Run the coach check-in."
    assert f'When the message is exactly "{CHECKIN_REQUEST}"' in COACH_RULES
    COACH_RULES.format(max_consults=2)  # still only the one placeholder
```

Append to `packages/tri-coach/tests/test_memory.py`:
```python
async def test_a_checkin_entry_is_kept_for_fourteen_days_by_default():
    store = InMemoryStore()
    remember, _ = make_memory_tools(lambda: TODAY)
    out = json.loads(
        await call_tool_in_graph(
            store,
            remember,
            {"kind": "checkin", "text": "Week on plan; watch the left knee.", "until": None},
        )
    )
    assert out["remembered"] is True
    entry = (await M.get_entries(store))[0]
    assert entry.kind == "checkin" and entry.until == date(2026, 9, 28)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_prompt.py packages/tri-coach/tests/test_memory.py -q`
Expected: `ImportError: cannot import name 'CHECKIN_REQUEST'`, and after that the version, phrase and `until` assertions fail.

- [ ] **Step 3: `prompts/coach.py`**

Replace the `PROMPT_VERSION` line and `COACH_RULES` with (keep `render_system_prompt` as is; every line of the rules stays within 100 characters, and each tested phrase sits on one line):
```python
PROMPT_VERSION = "3"  # bump whenever COACH_RULES changes; names the LangSmith experiment coach-v<N>

CHECKIN_REQUEST = "Run the coach check-in."  # the fixed message `tri-coach check-in` sends

COACH_RULES = """\
You are the athlete's head coach. You are direct and specific: numbers, dates and sessions, never
generic encouragement. You coach one athlete whose training, nutrition and lab data you can read
through your tools (labs only while the context says they are configured). You are the only one
who decides when something changes; the athlete approves every change before it is written.

Decision policy:
- Sub-agents never initiate a change. You decide, then you brief them.
- A change is warranted only when you can name the signal, the lever and the constraint: the
  signal (from the context below, the analyst, or what the athlete said), the lever (what to
  change) and the constraint (what must hold). Every brief names all three, for example: "Knee
  pain reported today. No running for 7 days; hold weekly TSS within 10 percent of target; keep
  Saturday's ride."
- Pure questions never trigger a consultation. Answer them, through ask_analyst when the answer
  needs data you do not have in the context.
- When ask_analyst or ask_wellness reports a failure, say what could not be read and do not
  guess at that data.
- Make at most {max_consults} consultations per domain per turn; then explain what you found and
  stop. If a sub-agent asks a question instead of proposing, answer it from the conversation and
  memory and consult again with a fuller brief, or ask the athlete.
- A consultation's result arrives as the tool result of your consult_* call, named p1, p2, ... .
  When it carries violations, state them in your narration or consult again with a revised brief.
  Never edit a proposal yourself; the athlete can edit at review.
- When you are ready, call propose_changes once with a narration (why, in two or three sentences)
  and the proposal ids you keep. The athlete then sees the change set and approves, rejects with a
  note, or edits. A message beginning "[review]" is the review system, not the athlete.
- A message beginning "[follow-on]" is the system after an apply, not the athlete: the approved
  plan change moved sessions and nutrition was regenerated from the stored plan. When its proposal
  has changes, narrate the consequence in one or two sentences and call propose_changes with its
  id; when it has none, say the nutrition targets stand; when it carries violations, state them.
  Consult no one in a follow-on.

Routing guide:
- ask_analyst: anything about past sessions, trends, readiness, sleep, HRV, body composition,
  logged intake against targets, comparisons to plan. It reads the database and the live devices;
  it never changes anything.
- ask_wellness: anything about lab markers, functional ranges, what is outside optimal and why,
  the retest plan, supplements, or whether a symptom could be lab-related. It reads stored panels
  and reports; it never changes anything. When the context says labs are not configured or no
  panel is stored, say so instead of guessing.
- A lab finding that bears on training load or fueling is a signal: name it in the brief, for
  example "Ferritin 18 ng/mL, functional low, on the 2026-08-30 panel".
  Never brief a sub-agent to change a lab value; the sub-agents do not read lab tables.
- consult_planning: anything that changes the calendar, the goal or the horizon: sessions moved,
  shortened, dropped or added, a new goal, a bought plan, the next week's design.
- consult_nutrition: anything that changes daily targets, fueling notes, the profile or the race
  plan.
- A plan change that alters training load needs consult_planning only: once the athlete approves
  it and sessions move, nutrition is regenerated from the stored plan and comes back to you as a
  "[follow-on]". Consult both in one turn only when the athlete asks for a plan change and a
  separate nutrition change; planning first.

Memory policy:
- remember anything the athlete says that should shape a future decision: injuries, travel, life
  constraints, preferences, how they like to be coached. Give an until date when one exists.
- Do not remember what planning, nutrition or wellness already store (goal, availability, plan
  constraints, the nutrition profile, lab values); brief planning or nutrition to change theirs,
  and use ask_wellness for the labs.
- Read the memory below before deciding, and say when a memory entry influenced a decision.
- forget an entry when the athlete says it no longer applies.

Check-in:
When the message is exactly "Run the coach check-in." nobody is there to answer: ask the athlete
nothing. Read through ask_analyst, decide, and brief. Report each step in one or two lines:
1. The last seven days planned versus actual: sessions done, TSS and hours against the week.
2. Sessions with RPE at or above 8 or feeling at or below 3, with the athlete's comments.
3. Readiness and HRV over the last 3 days against the 30-day baseline.
4. TSB entering this week.
5. Designed weeks remaining (context): fewer than 2 means brief planning to design the next week.
6. Logged intake against targets by day type over the last 7 days; nothing logged, no judgement.
7. Weight and body fat trend against the rate the nutrition goal allows.
8. Targets through (context): fewer than 7 days of targets left means brief nutrition to extend.
Then call remember with kind checkin and one paragraph: what you found, what you decided, what to
watch. Write it before propose_changes, which ends your turn. A clean week ends with a short
report headed load, recovery, nutrition, decision, the memory entry, and no change set."""
```

- [ ] **Step 4: `tools/memory.py`**

Add `from datetime import date, timedelta` (replacing `from datetime import date`) and, after the imports:
```python
CHECKIN_DAYS = 14  # spec 5.1: a check-in summary stays in the prompt for two weeks
```
Replace `remember`'s docstring and add the default after the `until` parse:
```python
    async def remember(kind: M.MemoryKind, text: str, until: str | None = None) -> str:
        """Remember something the athlete said that should shape a later decision and that
        planning (goal, availability, constraints) and nutrition (profile) do not already store,
        or the one-paragraph summary at the end of a check-in.
        kind: injury | constraint | preference | event | coaching_style | note | checkin.
        until: ISO date when an injury or event ends, else omit; a checkin entry defaults to
        two weeks out."""
        end: date | None = None
        if until:
            try:
                end = date.fromisoformat(until)
            except ValueError:
                return json.dumps(
                    {"error": f"until must be an ISO date (YYYY-MM-DD), got {until!r}"}
                )
        if kind == "checkin" and end is None:
            end = today() + timedelta(days=CHECKIN_DAYS)
        entry = await M.add_entry(get_store(), kind, text, today(), end)
        return json.dumps({"remembered": True, "id": entry.id})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_prompt.py packages/tri-coach/tests/test_memory.py packages/tri-coach/tests/test_graph.py -q`
Expected: all pass (`test_graph.py`'s prompt assertions use phrases v3 keeps).

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): prompt v3: follow-on rule, analyst failure rule, check-in checklist; checkin memory kept two weeks"
```
(append the executing session's trailer lines to the message)

---
### Task 5: `tri-coach check-in`, and slash commands at the review gate

**Files:**
- Create: `packages/tri-coach/src/tri_coach/checkin.py`, `packages/tri-coach/tests/test_checkin.py`
- Modify: `packages/tri-coach/src/tri_coach/repl.py`, `packages/tri-coach/src/tri_coach/cli.py`
- Test: `packages/tri-coach/tests/test_repl.py`, `packages/tri-coach/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4's `CHECKIN_REQUEST`; fact 10; Task 2's second gate.
- Produces: `tri_coach.repl.run_turn(graph, payload, thread_id, out, *, tags: list[str] | None = None) -> TurnPrinter`; `tri_coach.repl.paused_review(snap) -> dict[str, Any] | None` (renamed from `_paused_review`); `_review_dialogue(payload, read, out, edit, commands)`; `tri_coach.checkin.run_checkin(graph, *, has_plan: bool, has_profile: bool, yes: bool, out: Out, thread_id: str = "coach") -> int` with `EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3`, `CHECKIN_TAGS = ["checkin"]`, `MAX_GATES = 2`; the CLI command `tri-coach check-in [--yes] [--no-sync] [--no-live]`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-coach/tests/test_checkin.py`:
```python
"""The check-in's refusals and exit codes over a stub graph: no database, no model."""

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from tri_coach.checkin import (
    EXIT_ERROR,
    EXIT_NO_PLAN,
    EXIT_OK,
    EXIT_PAUSED,
    run_checkin,
)
from tri_coach.models import ChangeSet, Proposal
from tri_coach.prompts.coach import CHECKIN_REQUEST


def proposal() -> Proposal:
    return Proposal.model_validate(
        {
            "id": "p1",
            "domain": "planning",
            "summary": "move it",
            "changes": [
                {"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "knee"}
            ],
        }
    )


def payload(narration: str = "Knee: move Wednesday.") -> dict[str, Any]:
    return {"narration": narration, "proposals": [proposal().model_dump(mode="json")]}


def interrupt_event(narration: str = "Knee: move Wednesday.") -> tuple:
    return ((), "updates", {"__interrupt__": (Interrupt(value=payload(narration)),)})


DONE = ((), "updates", {"coach": {"messages": [AIMessage(content="Clean week.")]}})
IDLE = SimpleNamespace(next=(), values={}, tasks=())


class Graph:
    """Scripted astream turns ("boom" raises); aget_state returns the scripted snapshots in order,
    repeating the last one."""

    def __init__(self, turns: list[Any], states: list[Any]) -> None:
        self.turns = list(turns)
        self.states = list(states)
        self.inputs: list[Any] = []
        self.configs: list[Any] = []

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        self.configs.append(config)
        turn = self.turns.pop(0)
        if turn == "boom":
            raise RuntimeError("model down")
        for ev in turn:
            yield ev

    async def aget_state(self, config: Any) -> Any:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


async def run(graph: Graph, *, has_plan: bool = True, has_profile: bool = True, yes: bool = False):
    buf: list[str] = []
    code = await run_checkin(
        graph, has_plan=has_plan, has_profile=has_profile, yes=yes, out=buf.append
    )
    return code, "".join(buf)


async def test_refuses_while_a_review_is_paused():
    paused = SimpleNamespace(
        next=("review",), values={}, tasks=(SimpleNamespace(interrupts=(Interrupt(value=payload()),)),)
    )
    graph = Graph([], [paused])
    code, text = await run(graph, yes=True)
    assert code == EXIT_PAUSED and graph.inputs == []
    assert "-- planning (p1): move it" in text and "/pending" in text


async def test_refuses_while_a_held_change_set_is_pending():
    held = ChangeSet(narration="Held from the last apply.", proposals=[proposal()])
    graph = Graph([], [SimpleNamespace(next=(), values={"pending": held}, tasks=())])
    code, text = await run(graph)
    assert code == EXIT_PAUSED and graph.inputs == [] and "Held from the last apply." in text


async def test_exits_2_with_neither_a_plan_nor_a_profile():
    graph = Graph([], [IDLE])
    code, text = await run(graph, has_plan=False, has_profile=False)
    assert code == EXIT_NO_PLAN and graph.inputs == [] and "tri-coach chat" in text
    code, _ = await run(Graph([[DONE]], [IDLE]), has_plan=False, has_profile=True)
    assert code == EXIT_OK


async def test_a_clean_week_sends_the_fixed_request_with_the_checkin_tag():
    graph = Graph([[DONE]], [IDLE])
    code, text = await run(graph)
    assert code == EXIT_OK and "Clean week." in text
    assert graph.inputs[0]["messages"][0].content == CHECKIN_REQUEST
    assert graph.configs[0]["tags"] == ["checkin"]
    assert graph.configs[0]["configurable"]["thread_id"] == "coach"


async def test_a_proposed_change_set_pauses_without_yes():
    graph = Graph([[interrupt_event()]], [IDLE])
    code, text = await run(graph)
    assert code == EXIT_PAUSED and len(graph.inputs) == 1
    assert "Knee: move Wednesday." in text and "/pending" in text


async def test_yes_approves_the_change_set_and_its_follow_on():
    graph = Graph([[interrupt_event()], [interrupt_event("Targets follow.")], [DONE]], [IDLE])
    code, text = await run(graph, yes=True)
    assert code == EXIT_OK and "Targets follow." in text
    assert [type(i) for i in graph.inputs[1:]] == [Command, Command]
    assert graph.inputs[1].resume == {"action": "approve"} and graph.configs[2]["tags"] == ["checkin"]


async def test_yes_stops_after_two_gates():
    turns = [[interrupt_event()], [interrupt_event("two")], [interrupt_event("three")]]
    graph = Graph(turns, [IDLE])
    code, _ = await run(graph, yes=True)
    assert code == EXIT_PAUSED and len(graph.inputs) == 3


async def test_yes_with_an_incomplete_apply_exits_1():
    after = SimpleNamespace(next=(), values={"last_error": "planning: boom", "pending": None}, tasks=())
    graph = Graph([[interrupt_event()], [DONE]], [IDLE, after])
    code, text = await run(graph, yes=True)
    assert code == EXIT_ERROR and "apply did not complete: planning: boom" in text


async def test_a_model_error_exits_1():
    code, text = await run(Graph(["boom"], [IDLE]))
    assert code == EXIT_ERROR and "model down" in text
```

Append to `packages/tri-coach/tests/test_repl.py`:
```python
async def test_slash_commands_work_at_the_review_gate():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}})
    graph = StubGraph([[interrupt_event()], [done]])
    buf: list[str] = []

    async def status() -> str:
        return "STATUS LINE"

    await chat_loop(
        graph,
        read=scripted(["move it", "/status", "/nope", "approve", "/quit"]),
        out=buf.append,
        commands={"status": status},
    )
    text = "".join(buf)
    assert "STATUS LINE" in text and "unknown command: /nope" in text
    assert isinstance(graph.inputs[1], Command) and graph.inputs[1].resume == {"action": "approve"}


async def test_run_turn_passes_tags_to_the_run():
    graph = StubGraph([[]])
    seen: list[Any] = []

    async def astream(payload, config=None, stream_mode=None, subgraphs=False):
        seen.append(config)
        return
        yield  # pragma: no cover - makes this an async generator

    graph.astream = astream  # type: ignore[method-assign]
    await run_turn(graph, {"messages": []}, "coach", lambda s: None, tags=["checkin"])
    assert seen[0]["tags"] == ["checkin"] and seen[0]["recursion_limit"] == 60
```

In `packages/tri-coach/tests/test_cli.py`, rename the test to `test_help_lists_the_commands` and make the loop `for name in ("chat", "check-in", "memory", "reset"):`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_checkin.py packages/tri-coach/tests/test_repl.py packages/tri-coach/tests/test_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_coach.checkin'`; the REPL tests fail on `unexpected keyword argument 'tags'` and on the gate reprinting the review prompt for `/status`; the CLI test fails on `check-in`.

- [ ] **Step 3: `repl.py`**

- `run_turn`: change the signature to `async def run_turn(graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out, *, tags: list[str] | None = None) -> TurnPrinter:` and replace the `cfg = ...` line with:
```python
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    if tags:
        cfg["tags"] = list(tags)
```
- Rename `_paused_review` to `paused_review` (definition and both uses in `chat_loop`).
- Replace `_review_dialogue` with:
```python
async def _review_dialogue(
    payload: dict[str, Any],
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    edit: EditFn | None,
    commands: dict[str, CommandFn],
) -> ReviewDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None or line.strip() == "/quit":
            return None
        text = line.strip()
        if text == "/pending":
            out(render_review(payload) + "\n")
            continue
        if text.startswith("/"):
            parts = text[1:].split()
            name = parts[0] if parts else ""
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}; {REVIEW_PROMPT}\n")
            else:
                out(await handler() + "\n")
            continue
        decision = parse_decision(text)
        if decision is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        if decision.action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            edited = await edit([Proposal.model_validate(p) for p in payload.get("proposals", [])])
            if edited is None:
                out("edit cancelled\n")
                continue
            decision = ReviewDecision(action="edit", proposals=edited)
        return decision
```
- In `chat_loop`, change the call to `await _review_dialogue(pending, read, out, edit, commands)`.

- [ ] **Step 4: `checkin.py`**

```python
"""tri-coach check-in: one unattended coach turn with the fixed check-in request on thread coach.

Exit codes, as `tri-planning check-in`: 0 a clean week, or every gate approved and applied;
1 a model or API error, or an apply that did not complete; 2 neither an active plan nor a
nutrition profile; 3 paused at review, or refused because a review or a held change set is
already pending (its owner decides it in chat, and --yes must not approve it)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_coach.repl import Out, paused_review, render_review, run_turn

EXIT_OK, EXIT_ERROR, EXIT_NO_PLAN, EXIT_PAUSED = 0, 1, 2, 3
CHECKIN_TAGS = ["checkin"]
MAX_GATES = 2  # the change set and its nutrition follow-on (spec 6.5)
PAUSED_HINT = "check-in: paused at review; run `tri-coach chat` and type /pending to decide"


async def run_checkin(
    graph: Any,
    *,
    has_plan: bool,
    has_profile: bool,
    yes: bool,
    out: Out,
    thread_id: str = "coach",
) -> int:
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    paused = paused_review(snap)
    held = ((snap.values or {}).get("pending") if snap is not None else None)
    if paused is not None or held is not None or (snap is not None and snap.next):
        if paused is not None:
            out(render_review(paused) + "\n")
        elif held is not None:
            proposals = [p.model_dump(mode="json") for p in held.proposals]
            out(render_review({"narration": held.narration, "proposals": proposals}) + "\n")
        out("check-in: a change set is already pending; decide it in `tri-coach chat` (/pending)\n")
        return EXIT_PAUSED
    if not has_plan and not has_profile:
        out("check-in: no active plan and no nutrition profile; start in `tri-coach chat`\n")
        return EXIT_NO_PLAN
    request = {"messages": [HumanMessage(CHECKIN_REQUEST)]}
    printer = await run_turn(graph, request, thread_id, out, tags=CHECKIN_TAGS)
    gates = 0
    while True:
        if printer.error is not None:
            return EXIT_ERROR
        if printer.interrupt is None:
            break
        out("\n" + render_review(printer.interrupt) + "\n")
        if not yes or gates >= MAX_GATES:
            out(PAUSED_HINT + "\n")
            return EXIT_PAUSED
        gates += 1
        out("check-in: --yes given, approving\n")
        approve = Command(resume={"action": "approve"})
        printer = await run_turn(graph, approve, thread_id, out, tags=CHECKIN_TAGS)
    if gates:
        # apply reports a failed or partial write through state, not an interrupt
        after = (await graph.aget_state(cfg)).values or {}
        if after.get("last_error") or after.get("pending") is not None:
            reason = after.get("last_error") or "changes still pending"
            out(f"check-in: apply did not complete: {reason}\n")
            return EXIT_ERROR
    return EXIT_OK
```

- [ ] **Step 5: `cli.py`**

Change the module docstring to `"""Command-line entry points for the head coach: chat, check-in, memory, reset."""` and add after `chat`:
```python
@app.command("check-in")
def check_in(
    yes: bool = typer.Option(
        False, "--yes", help="Approve the change set and its nutrition follow-on without asking"
    ),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip `tri sync` first"),
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Sync, run the coach's weekly check-in, and pause at review (exit 3) unless --yes."""
    raise typer.Exit(code=asyncio.run(_check_in(yes=yes, no_sync=no_sync, no_live=no_live)))


async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from tri_coach.checkin import run_checkin
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
    from tri_planning import repo

    settings = get_coach_settings()
    code = _ready(settings)
    if code is not None:
        return code
    if not no_sync:
        report = await run_sync(settings, log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("check-in: sync had errors; continuing with existing data\n")
    with connect(settings.database_url) as conn:
        phase, _, _ = repo.derive_phase(conn)
    async with _open_graph(no_live=no_live) as (graph, store, _servers):
        profile = await S.get_profile(store)
        return await run_checkin(
            graph,
            has_plan=phase == "active",
            has_profile=profile is not None,
            yes=yes,
            out=_out,
            thread_id=THREAD_ID,
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q && uv run tri-coach check-in --help`
Expected: all pass, 1 skipped; the help lists `--yes`, `--no-sync`, `--no-live`.

- [ ] **Step 7: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): tri-coach check-in with planning's exit codes and a checkin run tag; slash commands at the review gate"
```
(append the executing session's trailer lines to the message)

---
### Task 6: Routing eval: cases, target and evaluators

**Files:**
- Create: `packages/tri-coach/src/tri_coach/evals/__init__.py` (empty), `packages/tri-coach/src/tri_coach/evals/cases.py`, `packages/tri-coach/src/tri_coach/evals/target.py`, `packages/tri-coach/src/tri_coach/evals/evaluators.py`, `packages/tri-coach/tests/test_evals.py`

**Interfaces:**
- Consumes: Task 4's `COACH_RULES`, `CHECKIN_REQUEST`; `tri_coach.context.CoachContext`, `LabSummary`, `render_context`; `tri_coach.memory` (`MemoryEntry`, `render`); `make_subagent`; `make_handoff_tools`, `make_memory_tools` (for the real tool descriptions); facts 7, 11, 12.
- Produces: `Route = Literal["none", "analyst", "wellness", "planning", "nutrition", "both"]`, `ROUTES`; `EvalCase(name, message, expected, pure_question=False, labs_enabled=False, context=..., memory=..., history=(), analyst_answer=..., wellness_answer=...)` with `.inputs()` and `.outputs()`; `CASES: list[EvalCase]`; `stub_tools(inputs) -> list[BaseTool]`; `classify(calls) -> Route`; `run_case(model, inputs) -> dict` with keys `calls`, `route`, `briefs`, `answer`; `make_target(model)`; evaluators `routing_accuracy(outputs, reference_outputs)`, `no_unrequested_adjustment(outputs, reference_outputs)`, `make_brief_judge(model)` (key `brief_quality`), `BriefJudgement`.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-coach/tests/test_evals.py`:
```python
"""The routing eval without LangSmith, a database or a real model."""

from langchain_core.messages import AIMessage

from tri_coach.evals.cases import CASES, ROUTES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    routing_accuracy,
)
from tri_coach.evals.target import classify, make_target, stub_tools
from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_core.testing import ScriptedChatModel, tool_call


def case(name):
    return next(c for c in CASES if c.name == name)


def test_cases_are_valid_and_cover_every_route():
    assert len({c.name for c in CASES}) == len(CASES) >= 12
    for c in CASES:
        assert c.expected and set(c.expected) <= set(ROUTES), c.name
        i = c.inputs()
        assert i["context"].startswith("Today is 2026-09-16."), c.name
        assert i["messages"][-1] == {"role": "user", "content": c.message}
        assert ("Labs: panel 2026-08-30" in i["context"]) == c.labs_enabled, c.name
        assert i["memory"].startswith("Athlete memory")
        assert c.outputs() == {"expected_routes": list(c.expected), "pure_question": c.pure_question}
    assert {r for c in CASES for r in c.expected} == set(ROUTES)
    assert any(c.message == CHECKIN_REQUEST for c in CASES)
    assert any(c.pure_question for c in CASES) and any(not c.pure_question for c in CASES)


def test_stub_tools_use_the_real_names_and_bind_wellness_only_with_labs():
    names = {t.name for t in stub_tools({"labs_enabled": True})}
    assert names == {
        "ask_analyst",
        "ask_wellness",
        "consult_planning",
        "consult_nutrition",
        "propose_changes",
        "remember",
        "forget",
    }
    assert "ask_wellness" not in {t.name for t in stub_tools({"labs_enabled": False})}


def test_classify_routes():
    def call(name):
        return {"name": name, "args": {}}

    assert classify([]) == "none"
    assert classify([call("remember")]) == "none"
    assert classify([call("ask_analyst")]) == "analyst"
    assert classify([call("ask_analyst"), call("ask_wellness")]) == "wellness"
    assert classify([call("ask_wellness"), call("consult_nutrition")]) == "nutrition"
    assert classify([call("ask_analyst"), call("consult_planning")]) == "planning"
    assert classify([call("consult_planning"), call("consult_nutrition")]) == "both"


async def test_target_records_the_calls_briefs_and_route():
    c = case("knee_pain_planning")
    brief = "Knee pain on runs since Sunday. No running for 7 days; hold weekly TSS; keep Saturday."
    model = ScriptedChatModel(
        script=[
            tool_call("ask_analyst", {"question": "Runs since Sunday?"}, "a1"),
            tool_call("consult_planning", {"instruction": brief}, "c1"),
            tool_call("propose_changes", {"narration": "Knee.", "proposal_ids": ["p1"]}, "c2"),
            AIMessage(content="never reached: propose_changes ends the turn"),
        ]
    )
    out = await make_target(model)(c.inputs())
    assert model.calls == 3
    assert [x["name"] for x in out["calls"]] == ["ask_analyst", "consult_planning", "propose_changes"]
    assert out["route"] == "planning" and out["briefs"] == [brief]
    assert routing_accuracy(out, c.outputs()) == {
        "key": "routing_accuracy",
        "score": 1,
        "comment": "route planning; expected one of planning",
    }
    assert no_unrequested_adjustment(out, c.outputs())["score"] is None


async def test_a_pure_question_answered_from_context_consults_nothing():
    c = case("tsb_from_context")
    model = ScriptedChatModel(script=[AIMessage(content="TSB is -8.")])
    out = await make_target(model)(c.inputs())
    assert out["route"] == "none" and out["answer"] == "TSB is -8." and out["briefs"] == []
    assert routing_accuracy(out, c.outputs())["score"] == 1
    assert no_unrequested_adjustment(out, c.outputs())["score"] == 1
    bad = {"calls": [{"name": "consult_planning", "args": {}}], "route": "planning"}
    res = no_unrequested_adjustment(bad, c.outputs())
    assert res["score"] == 0 and "consult_planning" in res["comment"]


async def test_brief_judge_scores_every_brief_and_skips_a_turn_without_one():
    verdict = {
        "bounded": True,
        "names_signal": True,
        "names_lever": True,
        "names_constraint": False,
        "problems": ["no constraint named"],
    }
    c = case("knee_pain_planning")
    judge = make_brief_judge(ScriptedChatModel(script=[tool_call("BriefJudgement", verdict)]))
    res = await judge(c.inputs(), {"briefs": ["Knee pain. No running for 7 days."]})
    assert res["key"] == "brief_quality" and res["score"] == 0
    assert "no constraint named" in res["comment"]
    res = await make_brief_judge(ScriptedChatModel(script=[]))(c.inputs(), {"briefs": []})
    assert res["score"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_evals.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_coach.evals'`.

- [ ] **Step 3: `evals/cases.py`**

```python
"""The single-turn routing cases behind the LangSmith dataset. Each input holds a rendered context
block, the memory block and the conversation; each output lists the routes the coach may take.
Today is fixed (Wednesday 2026-09-16) so runs are comparable across prompt versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from tri_coach import memory as M
from tri_coach.context import CoachContext, LabSummary, render_context
from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS
from tri_planning.planning.models import (
    PlanWeekRow,
    StoredGoal,
    StoredPlan,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.testing import GOAL_ARGS, MONDAY

Route = Literal["none", "analyst", "wellness", "planning", "nutrition", "both"]
ROUTES: tuple[Route, ...] = ("none", "analyst", "wellness", "planning", "nutrition", "both")

TODAY = MONDAY + timedelta(days=2)

FERRITIN_LOW = LabSummary(
    panel_id=1,
    drawn_on=date(2026, 8, 30),
    lab_name="Quest",
    report_on=date(2026, 9, 1),
    outside_optimal=2,
    markers=24,
    priorities=(
        "Ferritin 18 ng/mL is functionally low: iron-rich meals with vitamin C, retest in 8 "
        "weeks. Vitamin D 28 ng/mL is suboptimal: 2000 IU daily through winter."
    ),
)

CLEAN_WEEK = (
    "Last 7 days: 6 of 6 planned sessions done, 410 of 420 TSS, no RPE above 7, no low feeling "
    "scores. Readiness and HRV at the 30-day baseline. Intake within 5 percent of targets on "
    "logged days. Weight steady."
)
FERRITIN_ANSWER = (
    "Ferritin 18 ng/mL on the 2026-08-30 panel, functional low (optimal 50 to 150); retest due "
    "late October."
)


def case_context(
    *,
    labs: LabSummary | None = None,
    designed_remaining: int = 3,
    targets_days: int = 10,
) -> str:
    goal = StoredGoal(id=1, goal=TrainingGoal(**GOAL_ARGS), status="active")
    weeks = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=420, target_hours=8
        )
        for i in range(12)
    ]
    plan = StoredPlan(
        id=1,
        goal_id=1,
        source="generated",
        tp_plan_id=None,
        start_date=MONDAY,
        end_date=MONDAY + timedelta(weeks=12, days=-1),
        targets=weeks,
        status="active",
    )
    this_week = PlanWeekRow(
        plan_id=1,
        week_start=MONDAY,
        phase="build",
        target_tss=420,
        target_hours=8,
        designed=None,
        written_to_tp=True,
    )
    days = [
        {
            "metric_date": (TODAY - timedelta(days=7 - i)).isoformat(),
            "tss_day": 50 + 5 * i,
            "ctl": 52 + 0.3 * i,
            "atl": 57 + 0.5 * i,
            "tsb": -8.0,
            "sleep_score": 78,
            "hrv_overnight_avg": 62,
            "training_readiness": 70,
        }
        for i in range(7)
    ]
    ctx = CoachContext(
        today=TODAY,
        thresholds={
            "ftp_watts": 250,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 100,
            "lthr_bpm": 165,
            "max_hr_bpm": 190,
        },
        phase="active",
        goal=goal,
        plan=plan,
        this_week=this_week,
        actual_tss=130.0,
        actual_hours=2.5,
        designed_remaining=designed_remaining,
        profile=NutritionProfile(**PROFILE_ARGS),
        targets_through=TODAY + timedelta(days=targets_days),
        recent_days=days,
        labs_enabled=labs is not None,
        labs=labs,
    )
    return render_context(ctx)


def case_memory(*entries: tuple[M.MemoryKind, str]) -> str:
    return M.render(
        [
            M.MemoryEntry(id=f"m{i:05d}", kind=kind, text=text, created=TODAY - timedelta(days=3))
            for i, (kind, text) in enumerate(entries)
        ],
        TODAY,
    )


@dataclass(frozen=True)
class EvalCase:
    name: str
    message: str
    expected: tuple[Route, ...]
    pure_question: bool = False
    labs_enabled: bool = False
    context: str = field(default_factory=case_context)
    memory: str = field(default_factory=case_memory)
    history: tuple[tuple[str, str], ...] = ()  # ("user" | "assistant", content), oldest first
    analyst_answer: str = CLEAN_WEEK
    wellness_answer: str = FERRITIN_ANSWER

    def inputs(self) -> dict[str, Any]:
        turns = [*self.history, ("user", self.message)]
        return {
            "context": self.context,
            "memory": self.memory,
            "messages": [{"role": role, "content": text} for role, text in turns],
            "labs_enabled": self.labs_enabled,
            "analyst_answer": self.analyst_answer,
            "wellness_answer": self.wellness_answer,
        }

    def outputs(self) -> dict[str, Any]:
        return {"expected_routes": list(self.expected), "pure_question": self.pure_question}


CASES: list[EvalCase] = [
    EvalCase(
        name="sleep_question",
        message="How has my sleep been this week?",
        expected=("none", "analyst"),
        pure_question=True,
    ),
    EvalCase(
        name="tsb_from_context",
        message="What's my TSB today?",
        expected=("none", "analyst"),
        pure_question=True,
    ),
    EvalCase(
        name="weight_trend_question",
        message="Am I losing weight at the rate my goal allows?",
        expected=("analyst",),
        pure_question=True,
        analyst_answer="Weight 80.4 kg to 79.6 kg over 28 days; body fat 16.1 to 15.8 percent.",
    ),
    EvalCase(
        name="ferritin_question",
        message="Is my ferritin still low?",
        expected=("wellness",),
        pure_question=True,
        labs_enabled=True,
        context=case_context(labs=FERRITIN_LOW),
    ),
    EvalCase(
        name="labs_not_configured",
        message="What did my last blood test say?",
        expected=("none",),
        pure_question=True,
    ),
    EvalCase(
        name="encouragement",
        message="Nailed the tempo run this morning, felt great.",
        expected=("none",),
        pure_question=True,
    ),
    EvalCase(
        name="knee_pain_planning",
        message=(
            "My left knee has hurt on every run since Sunday: sharp on the outside after about "
            "20 minutes."
        ),
        expected=("planning",),
    ),
    EvalCase(
        name="travel_planning",
        message="I'm travelling Thursday to Sunday next week with no bike, only a hotel gym.",
        expected=("planning",),
    ),
    EvalCase(
        name="protein_nutrition",
        message=(
            "The scale says I've lost 1.5 kg of muscle in a month. Can we raise my protein?"
        ),
        expected=("nutrition",),
        analyst_answer="Muscle mass 38.1 kg on 2026-08-16 and 36.6 kg on 2026-09-15.",
    ),
    EvalCase(
        name="move_ride_and_gluten_free",
        message=(
            "Move Saturday's long ride to Sunday, and note that I've gone gluten free this week."
        ),
        expected=("both",),
    ),
    EvalCase(
        name="flat_long_rides_with_low_ferritin",
        message=(
            "I've felt flat on every long ride this month. Should we change how I eat around them?"
        ),
        expected=("nutrition",),
        labs_enabled=True,
        context=case_context(labs=FERRITIN_LOW),
        analyst_answer=(
            "Long rides: power down 6 percent at the same heart rate over 4 weeks; intake logged "
            "on 3 of 4 long-ride days, 400 to 600 kcal under target."
        ),
    ),
    EvalCase(
        name="checkin_clean_week",
        message=CHECKIN_REQUEST,
        expected=("analyst",),
        pure_question=True,
        memory=case_memory(("checkin", "Last week on plan; watch the left knee on long runs.")),
    ),
    EvalCase(
        name="checkin_needs_the_next_week_designed",
        message=CHECKIN_REQUEST,
        expected=("planning",),
        context=case_context(designed_remaining=1),
    ),
]
```

- [ ] **Step 4: `evals/target.py`**

```python
"""The function under evaluation: one coach turn over stub tools. The coach model sees the real
rules, the case's context and memory, and tools with the real names, arguments and descriptions;
the stubs answer from the case and never reach a sub-graph, the database or a device.
propose_changes ends the turn, as in the graph."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_core.tools import BaseTool, StructuredTool

from tri_coach import memory as M
from tri_coach.evals.cases import Route
from tri_coach.graph.llm import make_subagent
from tri_coach.prompts.coach import COACH_RULES
from tri_coach.text import last_ai_text
from tri_coach.tools.handoff import make_handoff_tools
from tri_coach.tools.memory import make_memory_tools

MAX_CONSULTS = 2
TARGET_RECURSION_LIMIT = 30
HANDOFFS: dict[str, Route] = {"consult_planning": "planning", "consult_nutrition": "nutrition"}
REAL_DESCRIPTIONS = {
    t.name: t.description for t in [*make_handoff_tools(), *make_memory_tools(date.today)]
}


def stub_tools(inputs: dict[str, Any]) -> list[BaseTool]:
    n = 0

    async def ask_analyst(question: str) -> str:
        """Ask the analyst about past sessions, trends, readiness, sleep, HRV, body composition,
        logged intake against nutrition targets, or how training compares to plan. It reads the
        database and the devices; it changes nothing. Ask one specific question at a time."""
        return str(inputs.get("analyst_answer") or "No data found for that question.")

    async def ask_wellness(question: str) -> str:
        """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
        functional range, what is outside optimal and why, the retest plan, supplements, or
        whether a symptom could be lab-related. It reads stored panels and reports; it changes
        nothing. Ask one specific question at a time."""
        return str(inputs.get("wellness_answer") or "No panel stored.")

    def proposal(domain: str) -> str:
        nonlocal n
        n += 1
        return f"p{n} ({domain}): a proposal that satisfies the brief\n1 change"

    async def consult_planning(instruction: str) -> str:
        return proposal("planning")

    async def consult_nutrition(instruction: str) -> str:
        return proposal("nutrition")

    async def propose_changes(narration: str, proposal_ids: list[str]) -> str:
        return f"change set {proposal_ids} sent to the athlete for review"

    async def remember(kind: M.MemoryKind, text: str, until: str | None = None) -> str:
        return json.dumps({"remembered": True, "id": "e0e0e0"})

    async def forget(entry_id: str) -> str:
        return json.dumps({"forgotten": True, "id": entry_id})

    def make(
        fn: Callable[..., Awaitable[str]], name: str, *, return_direct: bool = False
    ) -> BaseTool:
        description = REAL_DESCRIPTIONS.get(name) or inspect.cleandoc(fn.__doc__ or "")
        return StructuredTool.from_function(
            coroutine=fn, name=name, description=description, return_direct=return_direct
        )

    tools = [make(ask_analyst, "ask_analyst")]
    if inputs.get("labs_enabled"):
        tools.append(make(ask_wellness, "ask_wellness"))
    return [
        *tools,
        make(consult_planning, "consult_planning"),
        make(consult_nutrition, "consult_nutrition"),
        make(propose_changes, "propose_changes", return_direct=True),
        make(remember, "remember"),
        make(forget, "forget"),
    ]


def classify(calls: list[dict[str, Any]]) -> Route:
    names = {c["name"] for c in calls}
    handoffs = {HANDOFFS[name] for name in names if name in HANDOFFS}
    if handoffs == {"planning", "nutrition"}:
        return "both"
    if "planning" in handoffs:
        return "planning"
    if "nutrition" in handoffs:
        return "nutrition"
    if "ask_wellness" in names:
        return "wellness"
    if "ask_analyst" in names:
        return "analyst"
    return "none"


async def run_case(model: BaseChatModel, inputs: dict[str, Any]) -> dict[str, Any]:
    prompt = "\n\n".join(
        [COACH_RULES.format(max_consults=MAX_CONSULTS), inputs["context"], inputs["memory"]]
    )
    history = convert_to_messages(inputs["messages"])
    agent = make_subagent(model, stub_tools(inputs), prompt)
    out = await agent.ainvoke({"messages": history}, {"recursion_limit": TARGET_RECURSION_LIMIT})
    new = out["messages"][len(history) :]
    calls = [
        {"name": tc["name"], "args": tc["args"]}
        for m in new
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    ]
    return {
        "calls": calls,
        "route": classify(calls),
        "briefs": [str(c["args"].get("instruction", "")) for c in calls if c["name"] in HANDOFFS],
        "answer": last_ai_text(new),
    }


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(model, inputs)

    return target
```

- [ ] **Step 5: `evals/evaluators.py`**

```python
"""Evaluators over one coach turn: two code checks over the tool calls (the route taken, and no
handoff for a pure question) and an LLM judge over each brief. A check that does not apply to a
case scores None, which the pass rate leaves out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from tri_coach.evals.target import HANDOFFS

AsyncEvaluator = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


def routing_accuracy(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected = [str(r) for r in reference_outputs.get("expected_routes") or []]
    route = str(outputs.get("route"))
    return {
        "key": "routing_accuracy",
        "score": int(route in expected),
        "comment": f"route {route}; expected one of {', '.join(expected)}",
    }


def no_unrequested_adjustment(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not reference_outputs.get("pure_question"):
        return {"key": "no_unrequested_adjustment", "score": None, "comment": "not a pure question"}
    made = [
        c["name"]
        for c in outputs.get("calls") or []
        if c["name"] in HANDOFFS or c["name"] == "propose_changes"
    ]
    return {
        "key": "no_unrequested_adjustment",
        "score": int(not made),
        "comment": ", ".join(made) or "ok",
    }


class BriefJudgement(BaseModel):
    bounded: bool = Field(
        description="asks for one specific change, not a review, a re-plan or an open question"
    )
    names_signal: bool = Field(description="states what was observed or reported that warrants it")
    names_lever: bool = Field(description="states what to change")
    names_constraint: bool = Field(description="states what must hold while changing it")
    problems: list[str] = Field(description="one line per missing element or overreach")


JUDGE_SYSTEM = """\
You audit one brief a head coach wrote to a planning or nutrition sub-agent. A good brief is
bounded (one specific change the sub-agent can carry out without deciding anything else) and
names three things: the signal (what was observed or reported, with numbers or dates when the
conversation has them), the lever (what to change) and the constraint (what must hold, such as
a weekly TSS band, a session to keep, or the nutrition goal). You are given the athlete's last
message and the brief. Judge the brief's text literally; return a BriefJudgement."""


def render_judge_prompt(inputs: dict[str, Any], brief: str) -> str:
    messages = inputs.get("messages") or []
    last = str(messages[-1]["content"]) if messages else ""
    return f"Athlete's last message:\n{last}\n\nBrief:\n{brief}"


def make_brief_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = model.with_structured_output(BriefJudgement)

    async def brief_quality(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        briefs = [b for b in outputs.get("briefs") or [] if b]
        if not briefs:
            return {"key": "brief_quality", "score": None, "comment": "no brief"}
        ok = True
        problems: list[str] = []
        for brief in briefs:
            out = await judge.ainvoke(
                [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, brief))]
            )
            assert isinstance(out, BriefJudgement)
            ok = ok and out.bounded and out.names_signal and out.names_lever and out.names_constraint
            problems += out.problems
        return {"key": "brief_quality", "score": int(ok), "comment": "; ".join(problems) or "ok"}

    return brief_quality
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_evals.py -q`
Expected: all pass. If `test_cases_are_valid_and_cover_every_route` fails on the `Labs: panel` check, confirm that only the two `labs_enabled=True` cases pass `context=case_context(labs=FERRITIN_LOW)`.

- [ ] **Step 7: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): routing eval cases, a stub-tool target and three evaluators"
```
(append the executing session's trailer lines to the message)

---
### Task 7: `tri-coach eval`: the LangSmith dataset and experiment

**Files:**
- Create: `packages/tri-coach/src/tri_coach/evals/run.py`
- Modify: `packages/tri-coach/src/tri_coach/cli.py`
- Test: `packages/tri-coach/tests/test_evals.py`, `packages/tri-coach/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 6's `CASES`, `make_target`, the three evaluators; `PROMPT_VERSION`; `tri_nutrition.evals.run.pass_rates` (fact 11).
- Produces: `DATASET_NAME = "tri_coach_routing"`; `case_examples() -> list[dict]`; `ensure_dataset(client, *, recreate=False) -> None`; `render_pass_rates(rates, n) -> str`; `run_eval(settings, model, *, judge=True, prefix=None, recreate=False, log=print) -> dict[str, float]` (experiment prefix `coach-v<PROMPT_VERSION>`); the CLI command `tri-coach eval [--judge/--no-judge] [--prefix] [--recreate-dataset]` (exit 2 without keys, 1 when any evaluator is below 100%).

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_evals.py` (add `from tri_coach.evals.run import DATASET_NAME, case_examples, ensure_dataset, render_pass_rates` to the imports):
```python
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
    assert DATASET_NAME == "tri_coach_routing" and len(examples) == len(CASES)
    assert examples[0]["outputs"] == CASES[0].outputs()
    assert examples[0]["metadata"] == {"case": CASES[0].name}
    client = FakeClient()
    ensure_dataset(client)
    ensure_dataset(client)
    assert client.created == [DATASET_NAME] and len(client.examples) == len(CASES)
    ensure_dataset(client, recreate=True)
    assert client.deleted == 1 and client.created == [DATASET_NAME, DATASET_NAME]


def test_render_pass_rates_names_the_prompt_version():
    text = render_pass_rates({"routing_accuracy": 0.75, "brief_quality": 1.0}, 13)
    assert text.startswith("pass rate over 13 examples (prompt version 3):")
    assert "routing_accuracy" in text and "75%" in text and "100%" in text
```
In `packages/tri-coach/tests/test_cli.py`, make the loop `for name in ("chat", "check-in", "memory", "reset", "eval"):`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_evals.py packages/tri-coach/tests/test_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_coach.evals.run'`; the CLI test fails on `eval`.

- [ ] **Step 3: `evals/run.py`**

```python
"""Create the LangSmith routing dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

from tri_coach.evals.cases import CASES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    routing_accuracy,
)
from tri_coach.evals.target import make_target
from tri_coach.prompts.coach import PROMPT_VERSION
from tri_core.config import Settings
from tri_nutrition.evals.run import pass_rates

DATASET_NAME = "tri_coach_routing"
DATASET_DESCRIPTION = (
    "Single coach turns (context block, memory, conversation) with the routes the coach may take. "
    "Evaluators: routing_accuracy, no_unrequested_adjustment, and an LLM judge over each brief."
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


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


async def run_eval(
    settings: Settings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [routing_accuracy, no_unrequested_adjustment]
    if judge:
        evaluators.append(make_brief_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"coach-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model},
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
```

- [ ] **Step 4: `cli.py`**

Change the module docstring to `"""Command-line entry points for the head coach: chat, check-in, memory, reset, eval."""` and add before `reset`:
```python
@app.command(name="eval")
def eval_cmd(
    judge: bool = typer.Option(True, "--judge/--no-judge", help="Also run the brief judge"),
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default coach-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate-dataset",
        help="Delete and re-create the LangSmith dataset from the cases in code",
    ),
) -> None:
    """Run the coach over the routing dataset in LangSmith and print the pass rate per evaluator
    (exit 1 when any evaluator is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(judge=judge, prefix=prefix, recreate=recreate)))


async def _eval(*, judge: bool, prefix: str | None, recreate: bool) -> int:
    from tri_coach.evals.run import run_eval
    from tri_coach.graph.llm import make_model

    settings = get_coach_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings,
        make_model(settings),
        judge=judge,
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1
```
Also change the Typer `help` to `"Head coach: one conversation over the analyst, wellness, planning and nutrition"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q && uv run tri-coach eval --help`
Expected: all pass, 1 skipped; the help lists `--judge / --no-judge`, `--prefix`, `--recreate-dataset`.

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): tri-coach eval runs the routing dataset as experiment coach-v<PROMPT_VERSION>"
```
(append the executing session's trailer lines to the message)

---

### Task 8: Docs, spec status, vault export, finish

**Files:**
- Modify: `packages/tri-coach/README.md`, root `README.md`, `docs/superpowers/specs/2026-09-11-tri-coach-design.md` (status line only)
- Copy: this plan and every edited markdown file into the Obsidian vault

- [ ] **Step 1: Package README**

In `packages/tri-coach/README.md`:
- Commands block: after the `chat` line add
```
uv run tri-coach check-in [--yes] [--no-sync] [--no-live]   # sync, the weekly checklist, one change set; exit 3 when paused
uv run tri-coach eval [--judge/--no-judge] [--prefix P] [--recreate-dataset]   # the LangSmith routing eval
```
- Mermaid: change the review edge label `reject, or unknown ids` to `reject, unknown ids, or no changes`, and replace `apply --> END2([END])` with
```
    apply -->|planning moved sessions and targets exist| nutrition
    apply -->|otherwise| END2([END])
```
- Node table: append to the `nutrition` row's Returns cell `; on the regenerate brief, the targets entry and a "[follow-on]" message`, and to the `apply` row's Returns cell `; regenerate_after_apply and a regenerate brief when planning moved sessions and targets exist in the horizon`.
- After "## Wellness consult" (and its paragraphs) insert:
```markdown
## Follow-on gate

Nutrition targets are built from the stored plan, so a plan change and its nutrition consequence
are two gates in one command. When the apply node sees planning move sessions without error and
`nutrition_targets` has rows in the horizon, it sets `regenerate_after_apply` and routes to
`nutrition` with a regenerate brief. That brief skips the sub-agent and runs the graph's targets
entry. The result comes back to the coach as a `[follow-on]` message: the coach narrates it and
proposes again, or says the targets stand. Applied proposals are consumed, so the follow-on
proposal is `p1`. Held proposals a change set does not name stay pending through an approve or a
reject. Review refuses a proposal without changes. An exception inside one domain's apply is
reported and its changes are held unverified, while the other domain still runs.

## Check-in

`tri-coach check-in` runs `tri sync`, then sends `Run the coach check-in.` on thread `coach`
tagged `checkin`. The prompt's checklist reads through the analyst: planned versus actual, RPE
and feeling, readiness and HRV against baseline, TSB, designed weeks, logged intake against
targets, weight trend, and targets remaining. It writes a `checkin` memory entry that lasts two
weeks, then proposes or reports a clean week. Exit codes match `tri-planning check-in`: 0 done,
1 a model error or an incomplete apply, 2 neither an active plan nor a nutrition profile, and
3 paused, or refused while a review or a held change set is pending. `--yes` approves the change
set and its follow-on, at most two gates.

## Evaluation

`tri-coach eval` creates the LangSmith dataset `tri_coach_routing` from `evals/cases.py`: single
turns with a rendered context block, memory and conversation, plus the routes the coach may
take (none, analyst, wellness, planning, nutrition, both). The target runs the coach model
over stub tools with the real names and descriptions. It scores `routing_accuracy`,
`no_unrequested_adjustment` (pure questions only) and `brief_quality`, an LLM judge checking
that each brief is bounded and names the signal, the lever and the constraint. The experiment
is `coach-v<PROMPT_VERSION>`.
```
- "## Status": replace the `Milestone 4 (...): pending.` line with
```
- Check-in and follow-on (2026-09): check-in, the follow-on gate, prompt v3, routing eval.
  Eval pass rates (`tri-coach eval`): not yet measured. First `tri-coach check-in --no-live`: not yet run.
```

- [ ] **Step 2: Root README**

- Package table, tri-coach row: change the command cell `` `tri-coach chat \| memory \| reset` `` to `` `tri-coach chat \| check-in \| memory \| reset \| eval` ``.
- Run lines: after the `tri-coach chat` line add
```
uv run tri-coach check-in [--yes] [--no-sync] [--no-live]   # sync, weekly checklist over plan and nutrition; exit 3 when paused
uv run tri-coach eval [--recreate-dataset]                   # LangSmith routing eval
```
- Status: change the milestone 3 entry's closing sentence `Check-in and eval pending.` to `Merged 2026-09-13.` and append
```
- tri-coach milestone 4 (2026-09): check-in, the follow-on nutrition gate, prompt v3 and the routing eval;
  tracked in `docs/superpowers/plans/2026-09-13-tri-coach-04-checkin-and-follow-on.md`.
```

- [ ] **Step 3: Spec status line**

In `docs/superpowers/specs/2026-09-11-tri-coach-design.md` line 4, change `milestones 1 and 2 merged (plans 01, 02; `main` at 00ed820 on 2026-09-13); milestone 3, the wellness consult, in progress (plan 03)` to `milestones 1 to 3 merged (plans 01 to 03; `main` at 354ef39 on 2026-09-13); milestone 4, check-in and follow-on, in progress (plan 04)`. Do not change any other spec line.

- [ ] **Step 4: Definition of done and vault export**

```bash
uv run ruff format packages && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run tri-coach --help
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p "$V/docs/superpowers/plans" "$V/docs/superpowers/specs" "$V/packages/tri-coach"
cp docs/superpowers/plans/2026-09-13-tri-coach-04-checkin-and-follow-on.md "$V/docs/superpowers/plans/"
cp docs/superpowers/specs/2026-09-11-tri-coach-design.md "$V/docs/superpowers/specs/"
cp packages/tri-coach/README.md "$V/packages/tri-coach/readme.md"
cp README.md "$V/readme.md"
```

- [ ] **Step 5: Commit**

```bash
git add README.md packages/tri-coach/README.md docs/superpowers/specs/2026-09-11-tri-coach-design.md
git commit -m "docs(coach): check-in, follow-on gate and eval in the package and root READMEs; spec status"
```
(append the executing session's trailer lines to the message)

- [ ] **Step 6: Finish the branch**

Use `superpowers:finishing-a-development-branch`. The expected outcome is the same as for plans 1 to 3: a fast-forward merge into `main` after the suite passes on the merged tree, then removal of the worktree and branch. Brian's manual exits for the milestone:
- one `tri-coach check-in --no-live`, exit code recorded in the package README status;
- one `tri-coach eval --no-judge`, then with the judge, pass rates recorded there too;
- one chat turn where an approved plan change reaches the follow-on gate.

---

## Self-review against the spec

**Spec coverage (§13 milestone 4: "`tri-coach check-in` with its refusal and exit codes, the `checkin` memory entry, the post-apply nutrition regeneration and second gate, the routing dataset, evaluators and `eval`. The routing dataset gains lab-question cases"):**
- **§6.1:** `regenerate_after_apply` (Task 2), plus `carried` (Task 1).
- **§6.3 and §6.5:** `apply -> nutrition` when planning moved sessions and targets exist in the horizon; the regenerate brief; the second gate; "changes nothing" said by the coach (Task 2 node, Task 4 rule).
- **§6.4:** the check-in checklist as prompt item 5, and `PROMPT_VERSION` bumped (Task 4).
- **§5.1:** the `checkin` entry with `until` fourteen days out, written at the end of the check-in (Task 4). It is written before `propose_changes`; see the decisions.
- **§8 check-in:** sync, the fixed request on thread `coach`, the refusal while paused or pending (exit 3), exit 2 without a plan or profile, exit 1 on an error, `--yes` (Task 5).
- **§9:**
  - A planning apply failing mid-batch skips regeneration (Task 2 `_regeneration_due`).
  - Analyst errors return as the tool result (Task 3).
  - An exception inside apply holds instead of stalling (Task 1).
- **§11:**
  - Check-in refusal and exit codes against a scripted thread state (Task 5).
  - A planning apply that changed sessions triggers the regenerate brief and a second gate (Task 2).
  - The regenerate entry routes to targets (plan 1, and Task 2's node test).
- **§12:** domain tags on handoff runs and the `checkin` tag (Tasks 2, 5); the dataset `tri_coach_routing` with context, messages and expected routes; routing accuracy, no unrequested adjustment and the LLM brief judge; `eval [--judge/--no-judge] [--prefix] [--recreate-dataset]` as `coach-v<PROMPT_VERSION>`, printing pass rates (Tasks 6, 7). The lab-question cases are `ferritin_question`, `labs_not_configured` and `flat_long_rides_with_low_ferritin`.

**Parked items from plan 2 (plan 3's milestone):**
- Reject discards a held remainder: Task 1.
- Re-proposing one held id drops the other: Task 1.
- A psycopg error in apply leaves `pending` stale: Task 1.
- A question-only id reaches apply: Task 1.
- Slash commands at the review gate: Task 5.
- Still parked: the `← ask_analyst` line glued to streamed text, and the nutrition review showing one line per change.

**Placeholder scan:** no "TBD", "similar to" or "add handling" phrases. Every code step shows the code. The commit steps defer only the session trailer lines, which the executing session supplies.

**Type consistency:**
- `Brief.tool_call_id` and `message_id` are optional (Task 2); `result_message` asserts them.
- `merge_held` and `raised_report` (Task 1) are used by Task 2's return block unchanged.
- `REGENERATE_INSTRUCTION` and `_regeneration_due` live in `apply.py` (Task 2).
- `run_turn(..., tags=)` and `paused_review` (Task 5) are what `checkin.py` imports.
- `CHECKIN_REQUEST` (Task 4) is used by `checkin.py` (Task 5) and `cases.py` (Task 6).
- `analyst_tools_for(servers, db_url, today, connect)` (Task 3) matches `make_deps` and `test_servers.py`.
- `HANDOFFS` (Task 6 target) is imported by the evaluators.
- `case_examples` and `ensure_dataset` (Task 7) consume `EvalCase.inputs()` and `.outputs()` (Task 6).
