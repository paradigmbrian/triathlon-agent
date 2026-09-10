from datetime import date

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_planning.planning.models import CalendarChange, PlannedSession
from tri_planning.repl import (
    TurnPrinter,
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    parse_decision,
    render_changes,
)


def change(day=14, title="Ride", op="create"):
    s = PlannedSession(
        date=date(2026, 9, day),
        sport="bike",
        title=title,
        description="z2",
        duration_minutes=60,
        tss_planned=50,
        intensity="endurance",
    )
    return CalendarChange(op=op, workout_date=s.date, workout=s, reason="base week")


def interrupt_event(changes):
    value = {"summary": "s", "changes": [c.model_dump(mode="json") for c in changes]}
    value["last_error"] = None
    return ((), "updates", {"__interrupt__": (Interrupt(value=value),)})


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject too much bike")
    assert d.action == "reject" and d.note == "too much bike"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip():
    changes = [
        change(),
        change(15, "Run"),
        CalendarChange(op="delete", tp_workout_id="9", reason="drop"),
    ]
    text = changes_to_yaml(changes)
    assert "Ride" in text and "tp_workout_id: '9'" in text
    assert changes_from_yaml(text) == changes


def test_render_changes_groups_by_week():
    payload = {
        "summary": "week one",
        "changes": [change().model_dump(mode="json"), change(21, "Next").model_dump(mode="json")],
        "last_error": None,
    }
    text = render_changes(payload)
    assert "week one" in text and "2026-09-14" in text and "2026-09-21" in text
    assert "Ride" in text
    assert text.index("2026-09-14") < text.index("2026-09-21")


def test_turn_printer_handles_subgraph_events_and_interrupt():
    buf = []
    p = TurnPrinter(buf.append)
    meta = {"langgraph_node": "model"}
    p.on_event(("intake:abc",), "messages", (AIMessageChunk(content="Hel"), meta))
    p.on_event(("intake:abc",), "messages", (AIMessageChunk(content="lo"), meta))
    tool_msg = ToolMessage(content="{}", name="set_training_goal", tool_call_id="1")
    p.on_event(("intake:abc",), "updates", {"tools": {"messages": [tool_msg]}})
    p.on_event((), "updates", {"targets": {"messages": [AIMessage(content="Targets: 14 weeks")]}})
    stop = Interrupt(value={"summary": "s", "changes": []})
    p.on_event((), "updates", {"__interrupt__": (stop,)})
    p.on_event((), "updates", {"intake": {"messages": [AIMessage(content="Hello")]}})
    text = "".join(buf)
    assert "Hello" in text and "← set_training_goal" in text and "Targets: 14 weeks" in text
    assert text.count("Hello") == 1 and "[intake]" not in text
    assert p.interrupt == {"summary": "s", "changes": []}


class StubGraph:
    """Yields scripted event lists per astream call; records the inputs it was given."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.inputs = []

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"pending_changes": [], "phase": "intake"}
            next = ()

        return S()


async def test_chat_loop_review_dialogue_resumes_with_decision():
    done_msg = AIMessage(content="TrainingPeaks: applied 1 of 1 changes.")
    done_ev = ((), "updates", {"apply": {"messages": [done_msg]}})
    graph = StubGraph([[interrupt_event([change()])], [done_ev]])
    inputs = iter(["plan my season", "huh", "approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    text = "".join(buf)
    assert "Ride" in text and "approve / reject" in text and "applied 1" in text
    assert isinstance(graph.inputs[1], Command)
    assert graph.inputs[1].resume == {"action": "approve"}


async def test_chat_loop_edit_uses_editor_callback():
    graph = StubGraph([[interrupt_event([change()])], []])
    inputs = iter(["go", "edit", "/quit"])

    async def read():
        return next(inputs, None)

    async def edit(changes):
        return [changes[0].model_copy(update={"reason": "edited"})]

    await chat_loop(graph, read=read, out=lambda s: None, edit=edit)
    resume = graph.inputs[1].resume
    assert resume["action"] == "edit" and resume["changes"][0]["reason"] == "edited"
