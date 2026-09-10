from datetime import date

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_nutrition.nutrition.models import DayTarget, NutritionChange
from tri_nutrition.repl import (
    TurnPrinter,
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    parse_decision,
    render_review,
    render_targets,
)

MONDAY = date(2026, 9, 14)


def change(day=MONDAY, kcal=2800) -> NutritionChange:
    return NutritionChange(
        op="set_day_targets",
        target_key=day.isoformat(),
        day=day,
        payload={"calorie_goal": kcal, "carbs_grams": 280, "protein_grams": 150, "fat_grams": 120},
        reason="easy day",
    )


def interrupt_event(changes, summary="s"):
    value = {"summary": summary, "changes": [c.model_dump(mode="json") for c in changes]}
    value["last_error"] = None
    return ((), "updates", {"__interrupt__": (Interrupt(value=value),)})


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject too few carbs")
    assert d.action == "reject" and d.note == "too few carbs"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip():
    changes = [change(), change(date(2026, 9, 15), 3000)]
    text = changes_to_yaml(changes)
    assert "calorie_goal: 3000" in text and "set_day_targets" in text
    assert changes_from_yaml(text) == changes


def test_render_targets_and_review():
    t = DayTarget(
        day=MONDAY,
        day_type="hard",
        session_kcal=900,
        total_kcal=3600,
        carbs_g=600,
        protein_g=160,
        fat_g=64,
        fluid_baseline_ml=3500,
        source="plan",
        notes=["fat_floor"],
    )
    table = render_targets([t])
    assert "2026-09-14" in table and "hard" in table
    assert "600/160/64" in table and "fat_floor" in table
    payload = {
        "summary": "Daily targets\n" + table,
        "changes": [change().model_dump(mode="json")],
        "last_error": "boom",
    }
    text = render_review(payload)
    assert "Daily targets" in text and "previous apply stopped: boom" in text
    assert "1 change" in text and "approve / reject" in text


def test_turn_printer_handles_subgraph_events_and_interrupt():
    buf = []
    p = TurnPrinter(buf.append)
    meta = {"langgraph_node": "model"}
    p.on_event(("checkin:abc",), "messages", (AIMessageChunk(content="Hel"), meta))
    p.on_event(("checkin:abc",), "messages", (AIMessageChunk(content="lo"), meta))
    tool_msg = ToolMessage(content="{}", name="save_nutrition_profile", tool_call_id="1")
    p.on_event(("checkin:abc",), "updates", {"tools": {"messages": [tool_msg]}})
    p.on_event((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 7")]}})
    stop = Interrupt(value={"summary": "s", "changes": []})
    p.on_event((), "updates", {"__interrupt__": (stop,)})
    p.on_event((), "updates", {"checkin": {"messages": [AIMessage(content="Hello")]}})
    text = "".join(buf)
    assert "Hello" in text and "← save_nutrition_profile" in text and "Garmin: applied 7" in text
    assert text.count("Hello") == 1 and "[checkin]" not in text
    assert p.interrupt == {"summary": "s", "changes": []}


class StubGraph:
    def __init__(self, turns):
        self.turns = list(turns)
        self.inputs = []

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"pending_changes": [], "has_profile": True}
            next = ()

        return S()


async def test_chat_loop_review_dialogue_resumes_with_decision():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 1 of 1")]}})
    graph = StubGraph([[interrupt_event([change()])], [done]])
    inputs = iter(["set me up", "huh", "approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    text = "".join(buf)
    assert "approve / reject" in text and "applied 1" in text
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
