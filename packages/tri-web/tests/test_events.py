"""Each spec §5.3 event from a recorded (namespace, mode, data); start_turn over a stub graph."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Interrupt

from tri_web.events import Busy, TurnEmitter, TurnEvent, error_message, format_sse, start_turn


def emitted(events: list[tuple[tuple[str, ...], str, Any]]) -> list[TurnEvent]:
    q: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
    em = TurnEmitter(q)
    for ns, mode, data in events:
        em.on_event(ns, mode, data)
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_token_and_tool_activity_by_where():
    call = AIMessage(
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
    evs = emitted(
        [
            (("coach:1",), "messages", (AIMessageChunk(content="Hi"), {"langgraph_node": "model"})),
            ((), "messages", (AIMessageChunk(content="CTL 45"), {"langgraph_node": "model"})),
            ((), "updates", {"model": {"messages": [call]}}),
            (
                (),
                "updates",
                {
                    "tools": {
                        "messages": [
                            ToolMessage(content="[]", name="query_training_db", tool_call_id="q1")
                        ]
                    }
                },
            ),
            (
                ("coach:1",),
                "updates",
                {"model": {"messages": [AIMessage(content="Your CTL is 45.")]}},
            ),
        ]
    )
    assert [(e.name, e.data) for e in evs] == [
        ("token", {"where": "coach", "text": "Hi"}),
        ("token", {"where": "analyst", "text": "CTL 45"}),
        (
            "tool_call",
            {"where": "analyst", "name": "query_training_db", "args": {"sql": "select 1"}},
        ),
        ("tool_result", {"where": "analyst", "name": "query_training_db", "chars": 2}),
    ]  # the tool-call-free AIMessage ("assistant") is not an SSE event


def test_consult_report_and_interrupt():
    consult = ToolMessage(
        content="p1 (planning): move it", name="consult_planning", tool_call_id="c1"
    )
    evs = emitted(
        [
            ((), "updates", {"planning": {"messages": [consult]}}),
            ((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}}),
            ((), "updates", {"nutrition": {"messages": [HumanMessage("[follow-on] moved.")]}}),
            (
                (),
                "updates",
                {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)},
            ),
        ]
    )
    assert [(e.name, e.data) for e in evs] == [
        ("consult", {"domain": "planning", "text": "p1 (planning): move it"}),
        ("report", {"text": "planning: applied 1"}),
        ("report", {"text": "[follow-on] moved."}),
        ("interrupt", {"narration": "n", "proposals": []}),
    ]


def test_format_sse_frames_one_event_with_json_data():
    assert format_sse("token", {"where": "coach", "text": "a\nb"}) == (
        'event: token\ndata: {"where": "coach", "text": "a\\nb"}\n\n'
    )
    assert json.loads(format_sse("done", {"paused": False}).split("data: ")[1]) == {"paused": False}


def test_error_message_strips_the_terminal_dressing():
    assert (
        error_message("\n[the turn failed: RuntimeError: boom]\n")
        == "the turn failed: RuntimeError: boom"
    )


class StubGraph:
    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.inputs: list[Any] = []
        self.release = asyncio.Event()

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        turn = self.turns.pop(0)
        if turn == "boom":
            raise RuntimeError("model down")
        for ev in turn:
            yield ev
        await self.release.wait()  # hold the run open until the test lets go

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(next=(), values={}, tasks=())


def runtime_over(graph: Any) -> Any:
    return SimpleNamespace(
        graph=graph, thread_id="coach", lock=asyncio.Lock(), running=None, turn_task=None
    )


async def drain(run) -> list[TurnEvent]:
    out = []
    while (ev := await run.queue.get()) is not None:
        out.append(ev)
    return out


async def test_start_turn_holds_the_lock_until_the_run_ends_and_ends_with_done():
    graph = StubGraph(
        [[(("coach:1",), "messages", (AIMessageChunk(content="Hi"), {"langgraph_node": "model"}))]]
    )
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": [HumanMessage("hi")]}, kind="turn")
    assert rt.lock.locked() and rt.running == "turn"
    first = await run.queue.get()
    assert first is not None and first.name == "token"
    try:
        await start_turn(rt, {"messages": []}, kind="turn")
    except Busy as exc:
        assert exc.running == "turn"
    else:
        raise AssertionError("second start_turn should be refused")
    graph.release.set()
    rest = await drain(run)
    await run.task
    assert rest[-1].name == "done" and rest[-1].data == {"final_text": "Hi", "paused": False}
    assert not rt.lock.locked() and rt.running is None


async def test_a_failing_run_emits_error_then_done_and_releases_the_lock():
    graph = StubGraph(["boom"])
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": []}, kind="turn")
    evs = await drain(run)
    await run.task
    assert [e.name for e in evs] == ["error", "done"]
    assert "model down" in evs[0].data["message"]
    assert not rt.lock.locked()


async def test_done_paused_is_true_after_an_interrupt():
    graph = StubGraph(
        [
            [
                (
                    (),
                    "updates",
                    {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)},
                )
            ]
        ]
    )
    graph.release.set()
    rt = runtime_over(graph)
    run = await start_turn(rt, {"messages": []}, kind="review")
    evs = await drain(run)
    assert [e.name for e in evs] == ["interrupt", "done"] and evs[-1].data["paused"] is True
