import logging
from datetime import date
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_coach import memory as M
from tri_coach.graph import nodes
from tri_coach.graph.graph import after_review, build_graph
from tri_coach.graph.state import STATE_TYPES
from tri_coach.models import ReviewDecision
from tri_coach.testing import CFG, consult, move_call, propose, seed_active_plan
from tri_core.harness.agents import one_tool_call_at_a_time
from tri_core.harness.persistence import make_serde
from tri_core.testing import ScriptedChatModel, tool_call
from tri_planning.testing import FakeTp
from tri_wellness.testing import seed_panel

pytestmark = pytest.mark.db


def scripted(**scripts):
    return {k: ScriptedChatModel(script=v) for k, v in scripts.items()}


def graph_for(make_deps, mem_store, *, tp=None, **scripts):
    models = scripted(
        **{k: scripts.get(k, []) for k in ("coach", "planning", "nutrition", "analyst")}
    )
    deps = make_deps(tp=tp, **models)
    return build_graph(deps, InMemorySaver(serde=make_serde(STATE_TYPES)), mem_store), models


async def test_pure_question_uses_the_analyst_and_ends_without_a_handoff(
    nocommit, make_deps, mem_store
):
    graph, models = graph_for(
        make_deps,
        mem_store,
        coach=[
            tool_call("ask_analyst", {"question": "CTL?"}),
            AIMessage(content="Your CTL is 45."),
        ],
        analyst=[AIMessage(content="CTL 45.")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("how fit am I?")]}, CFG)
    assert out["messages"][-1].content == "Your CTL is 45."
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_msgs] == ["ask_analyst"] and tool_msgs[0].content == "CTL 45."
    assert models["planning"].calls == 0 and models["nutrition"].calls == 0
    assert out.get("proposals", []) == [] and out.get("brief") is None
    assert (await graph.aget_state(CFG)).next == ()


async def test_handoff_runs_planning_and_lands_a_proposal(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, models = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Knee pain. Move w1 off Wednesday; hold weekly TSS."),
            AIMessage(content="Planning suggests moving Wednesday's tempo to Friday."),
        ],
        planning=[move_call(), AIMessage(content="Proposed a move.")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("my knee hurts")]}, CFG)
    assert (await graph.aget_state(CFG)).next == ()
    props = out["proposals"]
    assert len(props) == 1 and props[0].id == "p1" and props[0].domain == "planning"
    assert [c.op for c in props[0].changes] == ["move"] and props[0].summary == "move it"
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    tm = out["messages"][2]
    assert tm.name == "consult_planning" and tm.content.startswith("p1 (planning): move it")
    assert out["brief"] is None and out["messages"][-1].content.startswith("Planning suggests")
    assert models["coach"].calls == 2


async def test_no_checkpoint_deserializes_an_unregistered_type(
    nocommit, make_deps, mem_store, caplog
):
    """langgraph's default serde only warns today and refuses under LANGGRAPH_STRICT_MSGPACK."""
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Move w1 off Wednesday."),
            propose("Move it.", ["p1"]),
        ],
        planning=[move_call(), AIMessage(content="ok")],
    )
    with caplog.at_level(logging.WARNING):
        await graph.ainvoke({"messages": [HumanMessage("my knee hurts")]}, CFG)
        await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    unregistered = [r.getMessage() for r in caplog.records if "unregistered type" in r.getMessage()]
    assert unregistered == []


async def test_sub_agent_question_comes_back_as_a_proposal_question(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Lighten the week."),
            AIMessage(content="Which day is worst?"),
        ],
        planning=[AIMessage(content="Which session hurt: the run or the ride?")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]}, CFG)
    p = out["proposals"][0]
    assert p.changes == [] and p.question == "Which session hurt: the run or the ride?"
    assert "asked instead of proposing" in out["messages"][2].content


async def test_two_consultations_in_one_turn_number_proposals(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "First brief.", "c1"),
            consult("planning", "Second brief.", "c2"),
            AIMessage(content="Two options."),
        ],
        planning=[
            move_call("m1"),
            AIMessage(content="ok"),
            move_call("m2"),
            AIMessage(content="ok"),
        ],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("options?")]}, CFG)
    assert [p.id for p in out["proposals"]] == ["p1", "p2"]
    names = [m.name for m in out["messages"] if isinstance(m, ToolMessage)]
    assert names == ["consult_planning", "consult_planning"]


async def test_a_parallel_call_beside_a_handoff_leaves_no_dangling_tool_use(
    nocommit, make_deps, mem_store
):
    seed_active_plan(nocommit)
    both = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "remember",
                "args": {"kind": "injury", "text": "Left knee sore."},
                "id": "r1",
                "type": "tool_call",
            },
            {
                "name": "consult_planning",
                "args": {"instruction": "Move w1 off Wednesday."},
                "id": "c1",
                "type": "tool_call",
            },
        ],
    )
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[both, AIMessage(content="Moved it to Friday.")],
        planning=[move_call("m1"), AIMessage(content="ok")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("my knee hurts")]}, CFG)
    asked = {tc["id"] for m in out["messages"] if isinstance(m, AIMessage) for tc in m.tool_calls}
    answered = {m.tool_call_id for m in out["messages"] if isinstance(m, ToolMessage)}
    assert asked == answered == {"r1", "c1"}
    results = {m.tool_call_id: m for m in out["messages"] if isinstance(m, ToolMessage)}
    assert results["c1"].content.startswith("p1 (planning): move it")
    assert results["r1"].content.startswith("not delivered")
    assert (await graph.aget_state(CFG)).next == ()


def _recording(monkeypatch):
    """Capture the tool names and the system prompt each coach turn binds."""
    bound: list[list[str]] = []
    prompts: list[str] = []
    real = nodes.coach.make_subagent

    def record(model, tools, system_prompt, **kwargs):
        bound.append([t.name for t in tools])
        prompts.append(system_prompt)
        return real(model, tools, system_prompt, **kwargs)

    monkeypatch.setattr(nodes.coach, "make_subagent", record)
    return bound, prompts


async def test_remember_writes_the_store_and_the_next_prompt_shows_it(
    nocommit, make_deps, mem_store, monkeypatch
):
    _, prompts = _recording(monkeypatch)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        coach=[
            tool_call(
                "remember",
                {"kind": "injury", "text": "Left knee sore on runs.", "until": "2026-09-28"},
            ),
            AIMessage(content="Noted."),
            AIMessage(content="Hello again."),
        ],
    )
    await graph.ainvoke({"messages": [HumanMessage("my left knee is sore when I run")]}, CFG)
    entries = await M.get_entries(mem_store)
    assert [e.kind for e in entries] == ["injury"] and entries[0].until.isoformat() == "2026-09-28"
    await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert "Left knee sore on runs." not in prompts[0]
    assert "Left knee sore on runs." in prompts[1]
    assert prompts[1].index("You are the athlete's head coach") < prompts[1].index("Today is")


async def test_propose_changes_pauses_at_review_with_the_narration(nocommit, make_deps, mem_store):
    seed_active_plan(nocommit)
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=FakeTp(),
        coach=[
            consult("planning", "Move w1."),
            propose("Knee pain: Wednesday's tempo moves to Friday.", ["p1"]),
        ],
        planning=[move_call(), AIMessage(content="ok")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["narration"].startswith("Knee pain") and payload["proposals"][0]["id"] == "p1"
    assert payload["proposals"][0]["changes"][0]["op"] == "move"
    snap = await graph.aget_state(CFG)
    assert snap.next == ("review",) and snap.values["pending"] is None  # built on resume
    assert snap.values["proposal_request"].ids == ["p1"]


async def test_unknown_proposal_id_returns_to_the_coach(nocommit, make_deps, mem_store):
    graph, models = graph_for(
        make_deps,
        mem_store,
        coach=[propose("n", ["p7"]), AIMessage(content="I have nothing to propose yet.")],
    )
    out = await graph.ainvoke({"messages": [HumanMessage("apply it")]}, CFG)
    assert "__interrupt__" not in out and models["coach"].calls == 2
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("[review] unknown proposal ids")
        for m in out["messages"]
    )
    assert out["proposal_request"] is None


async def test_approve_dispatches_planning_apply_with_thread_coach(nocommit, make_deps, mem_store):
    gid, pid = seed_active_plan(nocommit)
    tp = FakeTp()
    graph, _ = graph_for(
        make_deps,
        mem_store,
        tp=tp,
        coach=[consult("planning", "Move w1."), propose("Move it.", ["p1"])],
        planning=[move_call(), AIMessage(content="ok")],
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), CFG)
    assert [c[0] for c in tp.calls] == ["tp_update_workout"]
    assert out["pending"] is None and out["reports"][0].applied == 1
    assert out["reports"][0].sessions_changed is True and out["last_error"] is None
    rows = nocommit.execute(
        "select thread_id from plan_changes where plan_id = %s and operation = 'move'", (pid,)
    ).fetchall()
    assert [r["thread_id"] for r in rows] == ["coach"]
    assert out["messages"][-1].content.startswith("planning: applied 1\n  applied: move w1 -> ")
    assert (await graph.aget_state(CFG)).next == ()


def test_after_review():
    assert after_review({"review_decision": ReviewDecision(action="approve")}) == "apply"
    assert after_review({"review_decision": ReviewDecision(action="edit")}) == "apply"
    assert after_review({"review_decision": ReviewDecision(action="reject")}) == "coach"
    assert after_review({"review_decision": None}) == "coach"


async def test_lab_question_uses_the_wellness_consult_and_ends_without_a_handoff(
    ldb, make_deps, mem_store, registry, monkeypatch
):
    bound, prompts = _recording(monkeypatch)
    seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL")])
    models = scripted(
        coach=[
            tool_call("ask_wellness", {"question": "ferritin?"}),
            AIMessage(content="Ferritin is functionally low; I will fuel for iron."),
        ],
        planning=[],
        nutrition=[],
        analyst=[],
        wellness=[
            tool_call("get_panel_findings", {"panel": "latest"}),
            AIMessage(content="Ferritin 18 ng/mL, functional low."),
        ],
    )
    deps = make_deps(registry=registry, **models)
    graph = build_graph(deps, InMemorySaver(serde=make_serde(STATE_TYPES)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("how is my ferritin?")]}, CFG)
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_msgs] == ["ask_wellness"]
    assert tool_msgs[0].content == "Ferritin 18 ng/mL, functional low."
    assert out["messages"][-1].content.startswith("Ferritin is functionally low")
    assert models["planning"].calls == 0 and models["nutrition"].calls == 0
    assert models["analyst"].calls == 0 and models["wellness"].calls == 2
    assert "ask_wellness" in bound[0]
    assert not any(
        n.startswith(("set_", "tp_create", "tp_update", "tp_delete", "tp_apply")) for n in bound[0]
    )
    assert "Labs: latest panel 2026-08-30 (Quest) has no report yet" in prompts[0]
    assert (await graph.aget_state(CFG)).next == ()


async def test_wellness_tool_is_absent_when_labs_are_not_configured(
    nocommit, make_deps, mem_store, monkeypatch
):
    bound, prompts = _recording(monkeypatch)
    graph, _ = graph_for(make_deps, mem_store, coach=[AIMessage(content="Hello.")])
    await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert "ask_wellness" not in bound[0] and "ask_analyst" in bound[0]
    assert "Labs: not configured" in prompts[0]


async def test_the_coach_node_disables_parallel_tool_calls(
    nocommit, make_deps, mem_store, monkeypatch
):
    """Spec S6.4: the real coach node builds its sub-agent with
    middleware=[one_tool_call_at_a_time]."""
    captured: list[Any] = []
    real = nodes.coach.make_subagent

    def record(model, tools, system_prompt, **kwargs):
        captured.append(kwargs.get("middleware"))
        return real(model, tools, system_prompt, **kwargs)

    monkeypatch.setattr(nodes.coach, "make_subagent", record)
    graph, _ = graph_for(make_deps, mem_store, coach=[AIMessage(content="Hello.")])
    await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert captured == [[one_tool_call_at_a_time]]
