"""The check-in's refusals and exit codes over a stub graph: no database, no model."""

from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
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


def nutrition_proposal() -> Proposal:
    return Proposal.model_validate(
        {
            "id": "p1",
            "domain": "nutrition",
            "summary": "targets follow the moved session",
            "changes": [
                {
                    "op": "set_day_targets",
                    "target_key": "2026-09-14",
                    "day": "2026-09-14",
                    "payload": {"calorie_goal": 2800},
                    "reason": "easy day",
                }
            ],
        }
    )


def payload(narration: str = "Knee: move Wednesday.", domain: str = "planning") -> dict[str, Any]:
    p = proposal() if domain == "planning" else nutrition_proposal()
    return {"narration": narration, "proposals": [p.model_dump(mode="json")]}


def interrupt_event(narration: str = "Knee: move Wednesday.", domain: str = "planning") -> tuple:
    return ((), "updates", {"__interrupt__": (Interrupt(value=payload(narration, domain)),)})


# TurnPrinter prints the coach's own text as it streams (namespace ("coach:<id>",), node "model");
# the top-level "coach" node's own "updates" event only replays the same messages and, by design
# (see test_repl.py's test_printer_labels_the_analyst_and_does_not_repeat_its_answer), does not
# print again. So a turn that ends in plain conversation is simulated as the stream chunk plus
# that replay, matching what a real run over the compiled graph emits.
STREAM_CLEAN_WEEK = (
    ("coach:1",),
    "messages",
    (AIMessageChunk(content="Clean week."), {"langgraph_node": "model"}),
)
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
        next=("review",),
        values={},
        tasks=(SimpleNamespace(interrupts=(Interrupt(value=payload()),)),),
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
    graph = Graph([[STREAM_CLEAN_WEEK, DONE]], [IDLE])
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


async def test_refuses_while_the_thread_stopped_mid_run():
    stopped = SimpleNamespace(next=("nutrition",), values={}, tasks=())
    graph = Graph([], [stopped])
    code, text = await run(graph, yes=True)
    assert code == EXIT_PAUSED and graph.inputs == []
    assert "stopped mid-run at nutrition" in text and "tri-coach chat" in text
    assert "already pending" not in text


async def test_yes_approves_the_change_set_and_its_follow_on():
    follow_on = interrupt_event("Targets follow.", "nutrition")
    graph = Graph([[interrupt_event()], [follow_on], [DONE]], [IDLE])
    code, text = await run(graph, yes=True)
    assert code == EXIT_OK and "Targets follow." in text
    assert [type(i) for i in graph.inputs[1:]] == [Command, Command]
    assert graph.inputs[1].resume == {"action": "approve"} and graph.configs[2]["tags"] == [
        "checkin"
    ]


async def test_yes_stops_after_two_gates():
    turns = [
        [interrupt_event()],
        [interrupt_event("two", "nutrition")],
        [interrupt_event("three", "nutrition")],
    ]
    graph = Graph(turns, [IDLE])
    code, _ = await run(graph, yes=True)
    assert code == EXIT_PAUSED and len(graph.inputs) == 3


async def test_yes_does_not_approve_a_second_gate_that_is_not_the_nutrition_follow_on():
    turns = [[interrupt_event()], [interrupt_event("Also move Friday.")], [DONE]]
    graph = Graph(turns, [IDLE])
    code, text = await run(graph, yes=True)
    assert code == EXIT_PAUSED and len(graph.inputs) == 2
    assert "Also move Friday." in text and "/pending" in text


async def test_yes_with_an_incomplete_apply_exits_1():
    after = SimpleNamespace(
        next=(), values={"last_error": "planning: boom", "pending": None}, tasks=()
    )
    graph = Graph([[interrupt_event()], [DONE]], [IDLE, after])
    code, text = await run(graph, yes=True)
    assert code == EXIT_ERROR and "apply did not complete: planning: boom" in text


async def test_a_model_error_exits_1():
    code, text = await run(Graph(["boom"], [IDLE]))
    assert code == EXIT_ERROR and "model down" in text


def flagged(pid: str, domain: str, changes: list[dict[str, Any]], violations: dict) -> tuple:
    p = Proposal.model_validate(
        {
            "id": pid,
            "domain": domain,
            "summary": "s",
            "changes": changes,
            "pending_violations": violations,
        }
    )
    value = {"narration": f"{domain} gate", "proposals": [p.model_dump(mode="json")]}
    return ((), "updates", {"__interrupt__": (Interrupt(value=value),)})


FLAGGED_WEEK = flagged(
    "p1",
    "planning",
    [
        {"op": "create", "workout_date": "2026-09-22", "reason": "next week"},
        {"op": "move", "tp_workout_id": "w1", "new_date": "2026-09-18", "reason": "knee"},
    ],
    {"2026-09-21": ["hard sessions on consecutive days"]},
)
FLAGGED_NOTE = flagged(
    "p2",
    "nutrition",
    [
        {
            "op": "set_day_targets",
            "target_key": "2026-09-14",
            "day": "2026-09-14",
            "payload": {"calorie_goal": 2800},
            "reason": "easy day",
        },
        {
            "op": "set_session_note",
            "target_key": "w2",
            "day": "2026-09-15",
            "payload": {},
            "reason": "long ride",
        },
    ],
    {"w2": ["carbs 95 g/h above the 90 g/h ceiling"]},
)


async def test_yes_skips_flagged_changes_at_both_gates_and_exits_1():
    graph = Graph([[FLAGGED_WEEK], [FLAGGED_NOTE], [DONE]], [IDLE])
    code, text = await run(graph, yes=True)
    assert code == EXIT_ERROR
    plan, fuel = graph.inputs[1].resume, graph.inputs[2].resume
    assert plan["action"] == "edit" and fuel["action"] == "edit"
    assert [c["op"] for p in plan["proposals"] for c in p["changes"]] == ["move"]
    assert [c["op"] for p in fuel["proposals"] for c in p["changes"]] == ["set_day_targets"]
    assert "skipping p1 week of 2026-09-21: hard sessions on consecutive days" in text
    assert "skipping p2 set_session_note w2: carbs 95 g/h above the 90 g/h ceiling" in text
