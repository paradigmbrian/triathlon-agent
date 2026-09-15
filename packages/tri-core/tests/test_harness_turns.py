import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Interrupt

from tri_core.harness.agents import build_chat_agent
from tri_core.harness.turns import (
    AgentTurnPrinter,
    GraphTurnPrinter,
    TurnFailure,
    api_error_message,
    format_failure,
    run_agent_turn,
    run_graph_turn,
    stream_turn,
    turn_config,
)
from tri_core.testing import ScriptedChatModel, tool_call

REQ = httpx.Request("POST", "https://api.anthropic.com")
INGEST_HINT = "Wait a moment and rerun; the thread resumes."


def rate_limited() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(
        message="slow down", response=httpx.Response(429, request=REQ), body=None
    )


def server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError(
        message="boom", response=httpx.Response(500, request=REQ), body=None
    )


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=REQ)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_event(self, namespace, mode, data) -> None:
        self.events.append((namespace, mode, data))


class ScriptedRunnable:
    """astream yields the given items, then raises `error` if one is set; records its kwargs."""

    def __init__(self, items, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.kwargs: dict | None = None

    async def astream(self, payload, **kwargs):
        self.kwargs = kwargs
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def test_api_error_message_matches_todays_sentences():
    assert api_error_message(rate_limited()) == (
        "rate limited: slow down. Wait a moment and try again."
    )
    assert api_error_message(rate_limited(), rate_limit_hint=INGEST_HINT) == (
        "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    )
    assert api_error_message(server_error()) == "Anthropic API error 500: boom"
    assert api_error_message(connection_error()) == (
        "connection error talking to Anthropic: Connection error."
    )
    assert api_error_message(RuntimeError("x")) is None


def test_turn_config_adds_the_limit_and_tags_only_when_given():
    assert turn_config("t") == {"configurable": {"thread_id": "t"}}
    assert turn_config("t", tags=[]) == {"configurable": {"thread_id": "t"}}
    assert turn_config("coach", tags=("checkin",), recursion_limit=60) == {
        "configurable": {"thread_id": "coach"},
        "recursion_limit": 60,
        "tags": ["checkin"],
    }


async def test_stream_turn_normalises_subgraph_items():
    runnable = ScriptedRunnable([(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})])
    sink = Recorder()
    cfg = turn_config("t")
    assert await stream_turn(runnable, {"messages": []}, cfg, sink, subgraphs=True) is None
    assert sink.events == [(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})]
    assert runnable.kwargs == {
        "config": cfg,
        "stream_mode": ["messages", "updates"],
        "subgraphs": True,
    }


async def test_stream_turn_normalises_list_mode_items_and_passes_context_when_set():
    runnable = ScriptedRunnable([("messages", "m"), ("updates", {"b": 2})])
    sink = Recorder()
    ctx = object()
    await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False, context=ctx)
    assert sink.events == [((), "messages", "m"), ((), "updates", {"b": 2})]
    assert runnable.kwargs["context"] is ctx and "subgraphs" not in runnable.kwargs


async def test_stream_turn_normalises_single_mode_items():
    runnable = ScriptedRunnable([{"extract": {}}, {"store": {"panel_id": 3}}])
    sink = Recorder()
    await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False, stream_mode="updates")
    assert sink.events == [
        ((), "updates", {"extract": {}}),
        ((), "updates", {"store": {"panel_id": 3}}),
    ]
    assert runnable.kwargs["stream_mode"] == "updates" and "context" not in runnable.kwargs


async def test_stream_turn_returns_a_failure_for_anthropic_errors_after_earlier_events():
    runnable = ScriptedRunnable([("updates", {"a": 1})], error=connection_error())
    sink = Recorder()
    failure = await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False)
    assert isinstance(failure, TurnFailure)
    assert isinstance(failure.exc, anthropic.APIConnectionError)
    assert failure.message == "connection error talking to Anthropic: Connection error."
    assert len(sink.events) == 1
    assert format_failure(failure) == (
        "\n[connection error talking to Anthropic: Connection error.]\n"
    )


async def test_stream_turn_propagates_other_errors_unless_catch_all_is_set():
    with pytest.raises(RuntimeError, match="kaboom"):
        await stream_turn(
            ScriptedRunnable([], error=RuntimeError("kaboom")),
            {},
            turn_config("t"),
            Recorder(),
            subgraphs=True,
        )
    failure = await stream_turn(
        ScriptedRunnable([], error=RuntimeError("kaboom")),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=True,
        catch_all="ingest failed",
    )
    assert failure is not None and failure.message == "ingest failed: RuntimeError: kaboom"


async def test_stream_turn_uses_the_rate_limit_hint():
    failure = await stream_turn(
        ScriptedRunnable([], error=rate_limited()),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=False,
        rate_limit_hint=INGEST_HINT,
    )
    assert failure is not None
    assert (
        failure.message == "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    )


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def _capture():
    buf: list[str] = []
    return buf, buf.append


class FakeAgent:
    """Records what run_agent_turn hands to astream and answers with one final message."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def astream(self, payload, config=None, stream_mode=None, context=None):
        self.calls.append((payload, config, stream_mode, context))
        yield ("updates", {"model": {"messages": [AIMessage(content="ok")]}})


class ConnectionBoom(ScriptedChatModel):
    def _stream(self, *a, **k):
        raise anthropic.APIConnectionError(request=REQ)


class RuntimeBoom(ScriptedChatModel):
    def _stream(self, *a, **k):
        raise RuntimeError("kaboom")


async def test_run_agent_turn_streams_text_and_shows_tool_calls():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    buf, out = _capture()
    final = await run_agent_turn(build_chat_agent(model, [add]), "add 2 and 3", "t", out)
    text = "".join(buf)
    assert final == "It is 5."
    assert "→ add({'a': 2, 'b': 3})" in text
    assert "← add: 1 chars" in text
    assert text.rstrip().endswith("It is 5.")


async def test_run_agent_turn_passes_context_tags_thread_and_stream_modes():
    fake = FakeAgent()
    ctx = object()
    buf, out = _capture()
    assert await run_agent_turn(fake, "hi", "t9", out, context=ctx, tags=["chat"]) == "ok"
    payload, config, mode, context = fake.calls[0]
    assert payload["messages"][0].content == "hi"
    assert config["configurable"]["thread_id"] == "t9" and config["tags"] == ["chat"]
    assert mode == ["messages", "updates"] and context is ctx
    await run_agent_turn(fake, "again", "t9", out)
    assert "tags" not in fake.calls[1][1] and fake.calls[1][3] is None


async def test_run_agent_turn_reports_api_errors_without_raising():
    agent = build_chat_agent(ConnectionBoom(script=[]), [add])
    buf, out = _capture()
    assert await run_agent_turn(agent, "hi", "t", out) == ""
    assert "\n[connection error talking to Anthropic: Connection error.]\n" in buf


async def test_run_agent_turn_with_catch_all_reports_any_other_exception():
    agent = build_chat_agent(RuntimeBoom(script=[]), [add])
    buf, out = _capture()
    assert await run_agent_turn(agent, "hi", "t", out, catch_all="the turn failed") == ""
    assert "[the turn failed: RuntimeError: kaboom]" in "".join(buf)


async def test_run_agent_turn_without_catch_all_propagates_other_exceptions():
    agent = build_chat_agent(RuntimeBoom(script=[]), [add])
    buf, out = _capture()
    with pytest.raises(RuntimeError, match="kaboom"):
        await run_agent_turn(agent, "hi", "t", out)


def test_agent_printer_ignores_namespace_and_reads_text_blocks():
    printer = AgentTurnPrinter(lambda s: None)
    printer.on_event(
        ("any:1",),
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert printer.final_text == "x"


def test_graph_printer_handles_subgraph_events_interrupt_and_streamed_nodes():
    buf: list[str] = []
    printer = GraphTurnPrinter(buf.append, frozenset({"intake", "adjust"}))
    meta = {"langgraph_node": "model"}
    printer.on_event(("intake:abc",), "messages", (AIMessageChunk(content="Hel"), meta))
    printer.on_event(("intake:abc",), "messages", (AIMessageChunk(content="lo"), meta))
    tool_msg = ToolMessage(content="{}", name="set_training_goal", tool_call_id="1")
    printer.on_event(("intake:abc",), "updates", {"tools": {"messages": [tool_msg]}})
    printer.on_event(
        (), "updates", {"targets": {"messages": [AIMessage(content="Targets: 14 weeks")]}}
    )
    stop = Interrupt(value={"summary": "s", "changes": []})
    printer.on_event((), "updates", {"__interrupt__": (stop,)})
    printer.on_event((), "updates", {"intake": {"messages": [AIMessage(content="Hello")]}})
    text = "".join(buf)
    assert "Hello" in text and "← set_training_goal" in text and "Targets: 14 weeks" in text
    assert text.count("Hello") == 1 and "[intake]" not in text
    assert "[targets] Targets: 14 weeks" in text
    assert printer.interrupt == {"summary": "s", "changes": []}
    assert printer.error is None


async def test_run_graph_turn_streams_subgraphs_on_the_thread():
    class StubGraph:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            self.calls.append((payload, config, stream_mode, subgraphs))
            chunk = AIMessageChunk(content="Hi")
            yield (("adjust:1",), "messages", (chunk, {"langgraph_node": "model"}))

    graph = StubGraph()
    buf: list[str] = []
    printer = await run_graph_turn(
        graph, {"messages": []}, "planning", buf.append, streamed_nodes=frozenset({"adjust"})
    )
    assert isinstance(printer, GraphTurnPrinter)
    assert printer.final_text == "Hi" and printer.error is None
    assert printer.streamed_nodes == frozenset({"adjust"})
    assert graph.calls == [
        (
            {"messages": []},
            {"configurable": {"thread_id": "planning"}},
            ["messages", "updates"],
            True,
        )
    ]


async def test_run_graph_turn_sets_error_on_api_connection_failure():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            raise anthropic.APIConnectionError(request=REQ)
            yield  # pragma: no cover - makes this an async generator

    buf: list[str] = []
    printer = await run_graph_turn(RaisingGraph(), {"messages": []}, "planning", buf.append)
    assert printer.error == "\n[connection error talking to Anthropic: Connection error.]\n"
    assert printer.error in buf
    assert printer.interrupt is None


async def test_run_graph_turn_propagates_non_anthropic_errors():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover - makes this an async generator

    with pytest.raises(RuntimeError, match="kaboom"):
        await run_graph_turn(RaisingGraph(), {"messages": []}, "planning", lambda s: None)
