"""Checkpoint messages map to UiMessages; a paused review and a held set are recovered."""

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Interrupt

from tri_coach.models import ChangeSet, Proposal
from tri_web.thread import ThreadView, thread_snapshot, ui_messages


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


def payload() -> dict[str, Any]:
    return {"narration": "Knee: move Wednesday.", "proposals": [proposal().model_dump(mode="json")]}


def test_ui_messages_classify_each_root_message():
    ask = AIMessage(
        content="",
        id="a1",
        tool_calls=[
            {"name": "ask_analyst", "args": {"question": "CTL?"}, "id": "t1", "type": "tool_call"}
        ],
    )
    consult = AIMessage(
        content="Let me ask planning.",
        id="a2",
        tool_calls=[
            {
                "name": "consult_planning",
                "args": {"instruction": "move w1"},
                "id": "t2",
                "type": "tool_call",
            }
        ],
    )
    msgs = [
        SystemMessage("never shown"),
        HumanMessage("how fit am I?", id="h1"),
        ask,
        ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="t1", id="tm1"),
        AIMessage(content="Your CTL is 45.", id="a3"),
        consult,
        ToolMessage(
            content="p1 (planning): move it", name="consult_planning", tool_call_id="t2", id="tm2"
        ),
        AIMessage(content="planning: applied 1", name="apply", id="a4"),
        HumanMessage("[review] nothing to review; call propose_changes with proposal ids", id="h2"),
        HumanMessage("[follow-on] The approved plan change moved sessions.", id="h3"),
        HumanMessage("Review rejected: keep Wednesday", id="h4"),
    ]
    out = ui_messages(msgs)
    assert [(m.id, m.role) for m in out] == [
        ("h1", "user"),
        ("a1.0", "activity"),
        ("tm1", "activity"),
        ("a3", "assistant"),
        ("a2.0", "activity"),
        ("a2", "assistant"),
        ("tm2", "consult"),
        ("a4", "report"),
        ("h2", "report"),
        ("h3", "report"),
        ("h4", "report"),
    ]
    assert (
        out[1].name == "ask_analyst"
        and out[1].args == {"question": "CTL?"}
        and out[1].where == "coach"
    )
    assert (
        out[2].name == "ask_analyst"
        and out[2].chars == 10
        and out[2].text == "← ask_analyst: 10 chars"
    )
    assert out[3].where == "coach" and out[3].text == "Your CTL is 45."
    assert out[6].where == "planning" and out[6].text == "p1 (planning): move it"
    assert out[7].text == "planning: applied 1"


def test_messages_without_ids_get_positional_ids():
    out = ui_messages([HumanMessage("a"), AIMessage(content="b")])
    assert [m.id for m in out] == ["m0", "m1"]


class Graph:
    def __init__(self, snap: Any) -> None:
        self.snap = snap

    async def aget_state(self, config: Any) -> Any:
        assert config == {"configurable": {"thread_id": "coach"}}
        return self.snap


async def test_snapshot_recovers_a_paused_review():
    snap = SimpleNamespace(
        next=("review",),
        values={"messages": [HumanMessage("move it", id="h1")], "pending": None},
        tasks=(SimpleNamespace(interrupts=(Interrupt(value=payload()),)),),
    )
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert isinstance(view, ThreadView)
    assert [m.role for m in view.messages] == ["user"]
    assert view.paused is not None and view.paused.narration == "Knee: move Wednesday."
    assert view.paused.proposals[0]["id"] == "p1"
    assert view.held is None and view.stuck is False and view.running is None


async def test_snapshot_recovers_a_held_change_set():
    held = ChangeSet(narration="Held from the last apply.", proposals=[proposal()])
    snap = SimpleNamespace(next=(), values={"messages": [], "pending": held}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running="turn")
    assert view.paused is None
    assert view.held is not None and view.held.narration == "Held from the last apply."
    assert view.held.proposals[0]["changes"][0]["new_date"] == "2026-09-18"
    assert view.running == "turn"


async def test_snapshot_marks_a_thread_stopped_mid_run_as_stuck():
    snap = SimpleNamespace(next=("nutrition",), values={"messages": []}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert view.stuck is True and view.paused is None and view.held is None


async def test_snapshot_of_an_empty_thread():
    snap = SimpleNamespace(next=(), values={}, tasks=())
    view = await thread_snapshot(Graph(snap), "coach", running=None)
    assert view.messages == [] and view.stuck is False
