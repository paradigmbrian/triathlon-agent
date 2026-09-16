from datetime import date
from types import SimpleNamespace
from typing import Any

import yaml
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt

from tri_coach.models import ChangeSet, Proposal
from tri_coach.repl import (
    TurnClassifier,
    TurnPrinter,
    chat_loop,
    label,
    parse_decision,
    proposals_from_yaml,
    proposals_to_yaml,
    render_review,
    run_turn,
    where_of,
)


def proposals():
    return [
        Proposal.model_validate(
            {
                "id": "p1",
                "domain": "planning",
                "summary": "move it",
                "changes": [
                    {
                        "op": "move",
                        "tp_workout_id": "w1",
                        "new_date": "2026-09-18",
                        "reason": "rest",
                    }
                ],
            }
        ),
        Proposal.model_validate(
            {
                "id": "p2",
                "domain": "nutrition",
                "summary": "targets",
                "changes": [
                    {
                        "op": "set_day_targets",
                        "target_key": "2026-09-14",
                        "day": "2026-09-14",
                        "payload": {"calorie_goal": 2800},
                        "reason": "extend",
                    }
                ],
                "overrides": {"activity_factor": 1.45},
            }
        ),
    ]


def test_label_by_first_namespace_segment():
    assert label(()) == ""
    assert label(("coach:abc",)) == "coach"
    assert label(("planning:abc",)) == "planning"
    assert label(("planning:abc", "adjust:def")) == "planning"
    assert label(("nutrition:abc", "checkin:def")) == "nutrition"


def test_printer_streams_coach_tokens_and_labels_sub_graph_activity():
    out: list[str] = []
    p = TurnPrinter(out.append)
    p.on_event(
        ("coach:1",), "messages", (AIMessageChunk(content="Hel"), {"langgraph_node": "model"})
    )
    p.on_event(
        ("coach:1",), "messages", (AIMessageChunk(content="lo"), {"langgraph_node": "model"})
    )
    p.on_event(
        ("coach:1",),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "consult_planning",
                                "args": {"instruction": "x"},
                                "id": "c1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        },
    )
    p.on_event(
        ("planning:2", "adjust:3"),
        "messages",
        (AIMessageChunk(content="Looking at the week."), {"langgraph_node": "model"}),
    )
    p.on_event(
        ("planning:2", "adjust:3"),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="{}", name="propose_calendar_changes", tool_call_id="x")
                ]
            }
        },
    )
    p.on_event(
        (),
        "updates",
        {
            "planning": {
                "messages": [
                    ToolMessage(
                        content="p1 (planning): move it", name="consult_planning", tool_call_id="c1"
                    )
                ]
            }
        },
    )
    p.on_event((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}})
    text = "".join(out)
    assert text.startswith("Hello")
    assert "→ consult_planning({'instruction': 'x'})" in text
    assert "[planning] Looking at the week." in text
    assert "[planning] ← propose_calendar_changes" in text
    assert "← consult_planning: p1 (planning): move it" in text
    assert "planning: applied 1" in text and p.final_text == "planning: applied 1"


def test_printer_labels_the_analyst_and_does_not_repeat_its_answer():
    out: list[str] = []
    p = TurnPrinter(out.append)
    # the coach asks the analyst
    p.on_event(
        ("coach:1",),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "ask_analyst",
                                "args": {"question": "CTL?"},
                                "id": "a1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        },
    )
    # the analyst's own agent streams at the root namespace: label it, do not read it as coach text
    p.on_event((), "messages", (AIMessageChunk(content="CTL is 45."), {"langgraph_node": "model"}))
    p.on_event(
        (),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "query_training_db",
                                "args": {"sql": "select 1"},
                                "id": "q1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        },
    )
    p.on_event(
        (),
        "updates",
        {
            "tools": {
                "messages": [ToolMessage(content="[]", name="query_training_db", tool_call_id="q1")]
            }
        },
    )
    # the coach's tools node reports the analyst's answer once, as a length
    p.on_event(
        ("coach:1",),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="a1")
                ]
            }
        },
    )
    # the coach node's own update replays the same messages; they must not print again
    p.on_event(
        (),
        "updates",
        {
            "coach": {
                "messages": [
                    ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="a1"),
                    AIMessage(content="Your CTL is 45."),
                ]
            }
        },
    )
    text = "".join(out)
    assert "[analyst] CTL is 45." in text
    assert "[analyst] → query_training_db" in text
    assert "[analyst] ← query_training_db" in text
    assert text.count("← ask_analyst") == 1
    assert "← ask_analyst: 10 chars" in text
    assert p.final_text == ""  # the analyst never speaks for the coach


def test_printer_captures_the_interrupt():
    from langgraph.types import Interrupt

    p = TurnPrinter(lambda s: None)
    p.on_event(
        (), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)}
    )
    assert p.interrupt == {"narration": "n", "proposals": []}


def test_render_review_groups_by_domain_and_ends_with_the_prompt():
    payload = {
        "narration": "Knee pain: move Wednesday.",
        "proposals": [p.model_dump(mode="json") for p in proposals()],
    }
    text = render_review(payload)
    assert text.startswith("Knee pain: move Wednesday.")
    assert "-- planning (p1): move it" in text and "-- nutrition (p2): targets" in text
    assert "w1" in text and "2026-09-14" in text
    assert "profile overrides: {'activity_factor': 1.45}" in text
    assert text.rstrip().endswith("approve / reject <note> / edit")


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject  keep Wednesday")
    assert d.action == "reject" and d.note == "keep Wednesday"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip_keeps_both_domains_and_overrides():
    text = proposals_to_yaml(proposals())
    doc = yaml.safe_load(text)
    assert list(doc) == ["p1", "p2"] and doc["p1"]["domain"] == "planning"
    doc["p1"]["changes"][0]["new_date"] = "2026-09-19"
    doc["p2"]["changes"] = []
    back = proposals_from_yaml(yaml.safe_dump(doc, sort_keys=False), proposals())
    assert [p.id for p in back] == ["p1", "p2"]
    assert back[0].changes[0].new_date == date(2026, 9, 19)
    assert back[1].changes == [] and back[1].overrides == {"activity_factor": 1.45}


def interrupt_payload() -> dict[str, Any]:
    return {
        "narration": "Knee pain: move Wednesday.",
        "proposals": [p.model_dump(mode="json") for p in proposals()],
    }


def interrupt_event() -> tuple[tuple[str, ...], str, dict[str, Any]]:
    return ((), "updates", {"__interrupt__": (Interrupt(value=interrupt_payload()),)})


class StubGraph:
    """Yields a scripted event list per astream call; records the payloads it was given."""

    def __init__(self, turns: list[list[Any]], state: Any = None) -> None:
        self.turns = list(turns)
        self.inputs: list[Any] = []
        self.state = state

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config: Any) -> Any:
        return self.state


def scripted(lines: list[str]) -> Any:
    it = iter(lines)

    async def read() -> str | None:
        return next(it, None)

    return read


async def test_chat_loop_reviews_then_resumes_the_graph_with_the_decision():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}})
    graph = StubGraph([[interrupt_event()], [done]])
    buf: list[str] = []

    await chat_loop(
        graph, read=scripted(["move my long ride", "huh", "approve", "/quit"]), out=buf.append
    )

    text = "".join(buf)
    assert "-- planning (p1): move it" in text and "2026-09-14" in text
    assert "approve / reject <note> / edit" in text  # reprinted after the unparsable "huh"
    assert "planning: applied 1" in text
    assert graph.inputs[0]["messages"][0].content == "move my long ride"
    assert isinstance(graph.inputs[1], Command)
    assert graph.inputs[1].resume == {"action": "approve"}


async def test_chat_loop_survives_a_bare_slash_and_shows_a_held_change_set():
    held = ChangeSet(narration="Held from the last apply.", proposals=proposals())
    snapshot = SimpleNamespace(next=(), values={"pending": held}, tasks=())
    graph = StubGraph([[]], state=snapshot)
    buf: list[str] = []

    await chat_loop(graph, read=scripted(["/", "/pending", "/quit"]), out=buf.append)

    text = "".join(buf)
    assert "unknown command" not in text
    assert "-- nutrition (p2): targets" in text
    assert "held from an earlier apply" in text
    assert graph.inputs == []


async def test_chat_loop_resumes_a_review_paused_before_the_restart():
    snapshot = SimpleNamespace(
        next=("review",),
        values={},
        tasks=(SimpleNamespace(interrupts=(Interrupt(value=interrupt_payload()),)),),
    )
    graph = StubGraph([[]], state=snapshot)
    buf: list[str] = []

    await chat_loop(graph, read=scripted(["approve", "/quit"]), out=buf.append)

    text = "".join(buf)
    assert "-- nutrition (p2): targets" in text  # shown before any new message is read
    assert isinstance(graph.inputs[0], Command)
    assert graph.inputs[0].resume == {"action": "approve"}


async def test_run_turn_reports_a_non_anthropic_failure_instead_of_raising():
    class Boom:
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            raise RuntimeError("psycopg went away")
            yield  # pragma: no cover - makes this an async generator

    buf: list[str] = []
    printer = await run_turn(Boom(), {"messages": []}, "coach", buf.append)
    assert printer.error is not None and "psycopg went away" in printer.error
    assert "psycopg went away" in "".join(buf)


async def test_run_turn_formats_the_failure_text_with_the_60_step_recursion_limit():
    class Boom:
        def __init__(self) -> None:
            self.configs: list[Any] = []

        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            self.configs.append(config)
            raise RuntimeError("boom")
            yield  # pragma: no cover - makes this an async generator

    graph = Boom()
    buf: list[str] = []
    printer = await run_turn(graph, {"messages": []}, "coach", buf.append)
    assert printer.error == "\n[the turn failed: RuntimeError: boom]\n"
    assert printer.error in "".join(buf)
    assert graph.configs[0]["recursion_limit"] == 60


def test_printer_prints_the_follow_on_message_once():
    out: list[str] = []
    p = TurnPrinter(out.append)
    msg = HumanMessage("[follow-on] The approved plan change moved sessions.")
    p.on_event((), "updates", {"nutrition": {"messages": [msg]}})
    text = "".join(out)
    assert text.count("[follow-on] The approved plan change moved sessions.") == 1
    assert p.final_text == ""


async def test_chat_loop_keeps_going_after_a_failed_turn():
    class Flaky(StubGraph):
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            self.inputs.append(payload)
            turn = self.turns.pop(0)
            if turn == "boom":
                raise RuntimeError("psycopg went away")
            for ev in turn:
                yield ev

    done = ((), "updates", {"coach": {"messages": [AIMessage(content="still here")]}})
    graph = Flaky(["boom", [done]], state=SimpleNamespace(next=(), values={}, tasks=()))
    buf: list[str] = []

    await chat_loop(graph, read=scripted(["hello", "again", "/quit"]), out=buf.append)

    assert "psycopg went away" in "".join(buf)
    assert len(graph.inputs) == 2


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


def test_where_of_maps_namespaces_and_root_nodes():
    assert where_of("coach", "model") == "coach"
    assert where_of("coach", "tools") == "coach"
    assert where_of("planning", "model") == "planning"
    assert where_of("nutrition", "tools") == "nutrition"
    assert where_of("", "model") == "analyst"
    assert where_of("", "tools") == "analyst"
    assert where_of("", "apply") == "coach"


def test_classifier_emits_one_event_per_visible_thing():
    c = TurnClassifier()
    assert c.classify(
        ("coach:1",), "messages", (AIMessageChunk(content="Hel"), {"langgraph_node": "model"})
    ) == [("token", {"where": "coach", "text": "Hel"})]
    assert (
        c.classify(
            ("coach:1",), "messages", (AIMessageChunk(content=""), {"langgraph_node": "model"})
        )
        == []
    )
    assert c.classify(
        (), "messages", (AIMessageChunk(content="CTL 45"), {"langgraph_node": "model"})
    ) == [("token", {"where": "analyst", "text": "CTL 45"})]
    assert c.final_text == "Hel"  # only the coach's own tokens count
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "ask_analyst", "args": {"question": "CTL?"}, "id": "a1", "type": "tool_call"}
        ],
    )
    assert c.classify(("coach:1",), "updates", {"model": {"messages": [call]}}) == [
        ("tool_call", {"where": "coach", "name": "ask_analyst", "args": {"question": "CTL?"}})
    ]
    assert c.classify(
        ("coach:1",),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="CTL is 45.", name="ask_analyst", tool_call_id="a1")
                ]
            }
        },
    ) == [("tool_result", {"where": "coach", "name": "ask_analyst", "chars": 10})]
    assert c.classify(
        ("coach:1",), "updates", {"model": {"messages": [AIMessage(content="Your CTL is 45.")]}}
    ) == [("assistant", {"where": "coach", "text": "Your CTL is 45."})]
    assert c.final_text == "Your CTL is 45."
    assert c.classify(
        (),
        "updates",
        {
            "planning": {
                "messages": [
                    ToolMessage(
                        content="p1 (planning): move it", name="consult_planning", tool_call_id="c1"
                    )
                ]
            }
        },
    ) == [
        (
            "consult",
            {"domain": "planning", "name": "consult_planning", "text": "p1 (planning): move it"},
        )
    ]
    assert c.classify(
        (), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}}
    ) == [("report", {"text": "planning: applied 1", "node": "apply", "role": "ai"})]
    assert c.final_text == "planning: applied 1"
    msg = HumanMessage("[follow-on] moved.")
    assert c.classify((), "updates", {"nutrition": {"messages": [msg]}}) == [
        ("report", {"text": "[follow-on] moved.", "node": "nutrition", "role": "human"})
    ]
    ev = c.classify(
        (), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)}
    )
    assert ev == [("interrupt", {"narration": "n", "proposals": []})]
    assert c.interrupt == {"narration": "n", "proposals": []}
    # the coach node's own replay of the sub-agent's messages is silent
    assert (
        c.classify((), "updates", {"coach": {"messages": [AIMessage(content="Your CTL is 45.")]}})
        == []
    )


async def test_run_turn_uses_the_given_printer():
    class Collect(TurnPrinter):
        def __init__(self) -> None:
            super().__init__(lambda s: None)
            self.kinds: list[str] = []

        def print_event(self, kind: str, payload: dict[str, Any]) -> None:
            self.kinds.append(kind)

    graph = StubGraph([[interrupt_event()]])
    collect = Collect()
    printer = await run_turn(graph, {"messages": []}, "coach", lambda s: None, printer=collect)
    assert printer is collect and collect.kinds == ["interrupt"]
    assert collect.interrupt == interrupt_payload()
