from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from tri_core.harness.handoff import NOT_DELIVERED, handoff, turn_messages, undelivered


def calls(*id_names: tuple[str, str]) -> AIMessage:
    return AIMessage(
        content="",
        id="ai",
        tool_calls=[{"name": n, "args": {}, "id": i, "type": "tool_call"} for i, n in id_names],
    )


def test_not_delivered_keeps_todays_text():
    assert NOT_DELIVERED == (
        "not delivered: this step ended with a handoff; call again if still needed"
    )


def test_turn_messages_is_everything_after_the_last_human_message():
    h1, a1, h2 = HumanMessage("a", id="1"), AIMessage("b", id="2"), HumanMessage("c", id="3")
    a2 = AIMessage(
        "", id="4", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    t2 = ToolMessage("r", tool_call_id="c1", id="5")
    assert turn_messages([h1, a1, h2, a2, t2]) == [a2, t2]
    assert turn_messages([h1, a1]) == [a1]
    assert turn_messages([]) == []


def test_undelivered_answers_every_sibling_call_the_handoff_cut_off():
    ai = calls(("r1", "remember"), ("c1", "consult_planning"), ("r2", "remember"))
    answered = ToolMessage("ok", tool_call_id="r2", name="remember", id="t2")
    out = undelivered([ai, answered], "c1")
    assert [(m.tool_call_id, m.name, m.content) for m in out] == [("r1", "remember", NOT_DELIVERED)]
    assert out[0].id


def test_undelivered_is_empty_without_an_ai_message():
    assert undelivered([HumanMessage("hi")], "c1") == []


def test_handoff_jumps_in_the_parent_graph_with_the_turn_re_emitted():
    human = HumanMessage("tired", id="h")
    ai = calls(("r1", "remember"), ("c1", "consult_planning"))
    ack = ToolMessage("consulted", tool_call_id="c1", name="consult_planning", id="ack")
    cmd = handoff(
        "planning", tool_call_id="c1", messages=[human, ai], ack=ack, update={"brief": "b"}
    )
    assert isinstance(cmd, Command)
    assert cmd.goto == "planning" and cmd.graph == Command.PARENT
    assert cmd.update["brief"] == "b"
    emitted = cmd.update["messages"]
    assert [m.id for m in emitted][0] == "ai" and emitted[-1] is ack and len(emitted) == 3
    assert emitted[1].tool_call_id == "r1" and emitted[1].content == NOT_DELIVERED


def test_handoff_without_update_carries_only_the_messages():
    ai = calls(("c1", "propose_changes"))
    ack = ToolMessage("sent", tool_call_id="c1", name="propose_changes", id="ack")
    cmd = handoff("review", tool_call_id="c1", messages=[ai], ack=ack)
    assert set(cmd.update) == {"messages"} and cmd.update["messages"] == [ai, ack]
