from datetime import date
from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_core.harness.turns import GraphTurnPrinter
from tri_nutrition.nutrition.models import DayTarget, NutritionChange
from tri_nutrition.repl import (
    STREAMED_NODES,
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    checkin_run,
    parse_decision,
    render_review,
    render_targets,
    split_violating,
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
    p = GraphTurnPrinter(buf.append, STREAMED_NODES)
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


def test_render_fuel_and_race():
    from tri_nutrition.nutrition.models import RaceFuelPlan, SessionFuel
    from tri_nutrition.repl import render_fuel, render_race
    from tri_nutrition.testing import race_plan_json, session_fuel_json

    fuel = SessionFuel.model_validate(session_fuel_json("w1", MONDAY))
    text = render_fuel([fuel], {"w1": ["too much"]})
    assert "2026-09-14" in text and "60 g/h" in text and "Gel" in text
    assert "VIOLATIONS: too much" in text
    plan = RaceFuelPlan.model_validate(race_plan_json(date(2026, 10, 4)))
    text = render_race(plan, [])
    assert "-180" in text and "pre" in text and "bike" in text and "60 g/h" in text
    assert "If the gut turns" in text


async def test_chat_loop_a_bare_slash_lists_the_commands():
    graph = StubGraph([])
    inputs = iter(["/", "/  ", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    text = "".join(buf)
    assert text.count("commands: /pending, /quit\n") == 2
    assert graph.inputs == []


def test_split_violating_keeps_order_and_matches_notes_by_key():
    note = NutritionChange(
        op="set_session_note", target_key="w2", day=MONDAY, payload={}, reason="r"
    )
    race = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="r")
    violations = {"w2": ["too much"], "race": ["no pre-race step"]}
    clean, skipped = split_violating([change(), note, race], violations)
    assert clean == [change()]
    assert skipped == [(note, ["too much"]), (race, ["no pre-race step"])]
    assert split_violating([note], {}) == ([note], [])


class _RefusedTurn:
    """A graph whose turn ends without an interrupt, leaving a refused note in state."""

    def __init__(self) -> None:
        self.turned = False

    async def astream(self, payload, config=None, **kwargs):
        self.turned = True
        return
        yield

    async def aget_state(self, config):
        values = {"pending_violations": {"w2": ["product Mystery"]}} if self.turned else {}
        return SimpleNamespace(values=values, next=())


async def test_checkin_run_exits_1_on_a_refusal_with_nothing_to_review():
    printed: list[str] = []
    code = await checkin_run(_RefusedTurn(), thread_id="n", out=printed.append, approve=True)
    assert code == 1 and "not proposed w2: product Mystery" in "".join(printed)


class PausedGraph(StubGraph):
    """A thread the athlete left at review: the first state read is the waiting review."""

    def __init__(self, turns, payload):
        super().__init__(turns)
        self.payload = payload
        self.reads = 0

    async def aget_state(self, config):
        self.reads += 1
        if self.reads == 1:
            waiting = SimpleNamespace(interrupts=(Interrupt(value=self.payload),))
            return SimpleNamespace(next=("review",), values={}, tasks=(waiting,))
        return await super().aget_state(config)


def waiting_payload():
    return interrupt_event([change()])[2]["__interrupt__"][0].value


async def test_chat_loop_opens_a_waiting_review_before_reading_a_message():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 1 of 1")]}})
    graph = PausedGraph([[done]], waiting_payload())
    inputs = iter(["approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    assert "approve / reject" in "".join(buf)
    assert len(graph.inputs) == 1 and isinstance(graph.inputs[0], Command)
    assert graph.inputs[0].resume == {"action": "approve"}


async def test_quitting_at_a_waiting_review_leaves_it_waiting():
    graph = PausedGraph([], waiting_payload())
    inputs = iter(["/quit"])

    async def read():
        return next(inputs, None)

    await chat_loop(graph, read=read, out=lambda s: None)
    assert graph.inputs == []


class _Busy:
    """A thread that is not idle: `state` is what aget_state returns; a turn must not start."""

    def __init__(self, state) -> None:
        self.state = state
        self.turned = False

    async def astream(self, payload, config=None, **kwargs):
        self.turned = True
        return
        yield

    async def aget_state(self, config):
        return self.state


async def test_checkin_run_never_starts_a_turn_on_a_thread_that_is_not_idle():
    # a partial apply's remainder: next is empty, the changes wait in state
    remainder = SimpleNamespace(next=(), values={"pending_changes": [change()]}, tasks=())
    graph = _Busy(remainder)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="n", out=printed.append, approve=True) == 3
    assert not graph.turned and "already waiting at review" in "".join(printed)
    # a run that stopped mid-graph
    graph = _Busy(SimpleNamespace(next=("fuel",), values={}, tasks=()))
    printed.clear()
    assert await checkin_run(graph, thread_id="n", out=printed.append, approve=True) == 3
    assert not graph.turned and "stopped mid-run at fuel" in "".join(printed)
