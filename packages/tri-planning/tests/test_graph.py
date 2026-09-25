from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning import repo
from tri_planning.graph.graph import after_review, build_graph, route_start
from tri_planning.planning.models import ReviewDecision, TrainingGoal, WeekTarget
from tri_planning.testing import GOAL_ARGS, MONDAY, FakeTp, week_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "planning"}}
APPROVE = Command(resume={"action": "approve"})


def intake_script():
    return [
        tool_call("set_training_goal", GOAL_ARGS),
        AIMessage(content="Goal saved. Building the week targets."),
    ]


def week_call(target_tss, week_start=MONDAY, **k):
    return tool_call("PlannedWeek", week_json(week_start, target_tss, **k))


async def first_target(nocommit):
    goal = repo.get_active_goal(nocommit)
    return repo.get_active_plan(nocommit, goal.id).targets[0].target_tss


async def test_intake_to_review_pauses_before_any_write(nocommit, make_deps, fake_tp):
    # The design call needs the week-1 target, which only exists after the targets node runs.
    # The validator allows +-10 %, so 300 (the olympic floor with no fitness rows) is scripted.
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["changes"] and all(c["op"] == "create" for c in payload["changes"])
    assert fake_tp.calls == []
    snap = await graph.aget_state(CFG)
    assert snap.next == ("review",)
    assert snap.values["phase"] == "planning" and snap.values["changes_from"] == "design"


async def test_approve_applies_and_activates(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(
        script=[*intake_script(), week_call(300), AIMessage(content="All on track.")]
    )
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["phase"] == "active" and out["pending_changes"] == []
    assert [c[0] for c in fake_tp.calls] == ["tp_create_workout"] * 3
    assert isinstance(out["messages"][-1], AIMessage)
    assert "applied 3" in out["messages"][-1].content
    # a later turn goes to the adjust sub-agent
    out = await graph.ainvoke({"messages": [HumanMessage("how's it going")]}, CFG)
    assert "All on track." in out["messages"][-1].content


async def test_reject_routes_back_to_design_with_note(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "too much bike"}), CFG)
    assert "__interrupt__" in out and model.calls == 4
    msgs = (await graph.aget_state(CFG)).values["messages"]
    assert any(isinstance(m, HumanMessage) and "too much bike" in m.content for m in msgs)
    assert fake_tp.calls == []


async def test_edit_replaces_change_set(nocommit, make_deps, fake_tp):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    edited = out["__interrupt__"][0].value["changes"][:1]
    out = await graph.ainvoke(Command(resume={"action": "edit", "changes": edited}), CFG)
    assert len(fake_tp.calls) == 1 and out["phase"] == "active"


async def test_mid_batch_failure_then_reproposes_remainder(nocommit, make_deps):
    tp = FakeTp(fail_on_call=2)
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=tp), InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(out["pending_changes"]) == 2 and "boom" in out["last_error"]
    assert out["phase"] == "planning"
    tp.fail_on_call = None
    out = await graph.ainvoke({"messages": [HumanMessage("try again")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 2
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["phase"] == "active" and len(tp.calls) == 4  # 1 ok + 1 failed + 2 retried


async def test_bought_plan_path(nocommit, make_deps):
    workouts = [
        {"id": "w1", "date": MONDAY.isoformat(), "tss_planned": 60, "duration_planned": 1.0},
        {
            "id": "w2",
            "date": (MONDAY + timedelta(weeks=1)).isoformat(),
            "tss_planned": 40,
            "duration_planned": 1.0,
        },
    ]
    tp = FakeTp(responses={"tp_get_workouts": {"workouts": workouts, "count": 2}})
    args = {**GOAL_ARGS, "tp_plan_id": "p1"}
    model = ScriptedChatModel(
        script=[tool_call("set_training_goal", args), AIMessage(content="Goal saved.")]
    )
    graph = build_graph(make_deps(model, tp=tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("use my bought plan p1")]}, CFG)
    assert out["__interrupt__"][0].value["changes"][0]["op"] == "apply_plan"
    out = await graph.ainvoke(APPROVE, CFG)
    assert [c[0] for c in tp.calls] == ["tp_apply_training_plan", "tp_get_workouts"]
    assert out["phase"] == "active" and out["plan_id"] is not None
    assert repo.owned_workout_ids(nocommit, out["plan_id"]) == {"w1", "w2"}


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


def test_derive_phase_from_tables(nocommit):
    assert repo.derive_phase(nocommit) == ("intake", None, None)
    gid = repo.insert_goal(nocommit, TrainingGoal(**GOAL_ARGS))
    assert repo.derive_phase(nocommit) == ("planning", gid, None)
    targets = [WeekTarget(week_start=MONDAY, phase="base", target_tss=300, target_hours=6)]
    pid = repo.insert_plan(nocommit, gid, "generated", None, targets)
    # a plan row with nothing on the calendar yet is still planning, with its id
    assert repo.derive_phase(nocommit) == ("planning", gid, pid)
    repo.mark_weeks_written(nocommit, pid, [MONDAY])
    assert repo.derive_phase(nocommit) == ("active", gid, pid)
    repo.abandon_active(nocommit)
    assert repo.derive_phase(nocommit) == ("intake", None, None)


async def test_second_run_after_a_failed_design_redesigns(nocommit, make_deps, fake_tp):
    # Run 1: intake and targets commit the goal and plan rows, then design has no scripted
    # reply and raises. Run 2 must re-design, not adjust an empty calendar.
    model = ScriptedChatModel(script=intake_script())
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    with pytest.raises(IndexError):
        await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    phase, _, pid = repo.derive_phase(nocommit)
    assert phase == "planning" and pid is not None
    model.script.append(week_call(300))
    out = await graph.ainvoke({"messages": [HumanMessage("try again")]}, CFG)
    assert "__interrupt__" in out and model.calls == 3
    assert (await graph.aget_state(CFG)).values["changes_from"] == "design"
    assert fake_tp.calls == []


async def test_fresh_thread_starts_where_the_tables_say(nocommit, make_deps, fake_tp):
    # An active goal with no plan: route -> targets -> design -> review. No intake call.
    gid = repo.insert_goal(nocommit, TrainingGoal(**GOAL_ARGS))
    model = ScriptedChatModel(script=[week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("continue")]}, CFG)
    assert "__interrupt__" in out and model.calls == 1
    values = (await graph.aget_state(CFG)).values
    assert values["goal_id"] == gid and values["plan_id"] is not None
    assert values["phase"] == "planning"


async def test_stale_thread_phase_is_overwritten_by_the_tables(nocommit, make_deps, fake_tp):
    # The checkpoint says active with ids that no longer exist; the tables say intake, so the
    # run goes intake -> targets -> design -> review instead of asserting in adjust.
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.aupdate_state(CFG, {"phase": "active", "goal_id": 999, "plan_id": 999})
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" in out and model.calls == 3
    values = (await graph.aget_state(CFG)).values
    assert values["phase"] == "planning" and values["goal_id"] != 999


def test_route_functions():
    assert route_start({"pending_changes": [1]}) == "review"
    assert route_start({}) == "intake"
    assert route_start({"phase": "planning"}) == "targets"
    assert route_start({"phase": "active"}) == "adjust"
    assert after_review({"review_decision": ReviewDecision(action="approve")}) == "apply"
    reject = ReviewDecision(action="reject")
    assert after_review({"review_decision": reject, "changes_from": "design"}) == "design"
    assert after_review({"review_decision": reject, "changes_from": "targets"}) == "__end__"
    assert after_review({"review_decision": None}) == "__end__"


async def test_embedded_graph_has_no_review_and_ends_with_pending_changes(
    nocommit, make_deps, fake_tp
):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver(), embedded=True)
    assert "review" not in graph.nodes and "apply" not in graph.nodes
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" not in out
    assert (await graph.aget_state(CFG)).next == ()
    assert out["pending_changes"] and all(c.op == "create" for c in out["pending_changes"])
    assert out["changes_from"] == "design" and out["pending_summary"]
    assert fake_tp.calls == []
