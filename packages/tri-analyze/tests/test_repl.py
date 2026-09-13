from datetime import date

import anthropic
import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from tri_analyze.agent import build_agent
from tri_analyze.repl import TurnPrinter, chat_loop, run_turn, text_of
from tri_analyze.testing import athlete_context
from tri_core.testing import ScriptedChatModel, tool_call

CTX = athlete_context()


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def _capture():
    buf: list[str] = []
    return buf, buf.append


class FakeAgent:
    """Records what run_turn hands to astream and answers with one final message."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def astream(self, payload, config=None, stream_mode=None, context=None):
        self.calls.append((payload, config, stream_mode, context))
        yield ("updates", {"model": {"messages": [AIMessage(content="ok")]}})


async def test_run_turn_streams_text_and_shows_tool_calls():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add])
    buf, out = _capture()
    final = await run_turn(agent, "add 2 and 3", "t", out, context=CTX)
    text = "".join(buf)
    assert final == "It is 5."
    assert "→ add({'a': 2, 'b': 3})" in text
    assert "← add: 1 chars" in text
    assert text.rstrip().endswith("It is 5.")


async def test_run_turn_passes_context_tags_thread_and_stream_modes():
    fake = FakeAgent()
    buf, out = _capture()
    final = await run_turn(fake, "hi", "t9", out, context=CTX, tags=["chat"])
    assert final == "ok"
    payload, config, mode, context = fake.calls[0]
    assert payload["messages"][0].content == "hi"
    assert config["configurable"]["thread_id"] == "t9" and config["tags"] == ["chat"]
    assert mode == ["messages", "updates"] and context is CTX
    await run_turn(fake, "again", "t9", out, context=CTX)
    assert "tags" not in fake.calls[1][1]


async def test_run_turn_reports_api_errors_without_raising():
    class Boom(ScriptedChatModel):
        def _stream(self, *a, **k):
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.com")
            )

    agent = build_agent(Boom(script=[]), [add])
    buf, out = _capture()
    final = await run_turn(agent, "hi", "t", out, context=CTX)
    assert final == ""
    assert any("connection" in s.lower() for s in buf)


async def test_run_turn_reports_any_other_exception_and_returns():
    class Boom(ScriptedChatModel):
        def _stream(self, *a, **k):
            raise RuntimeError("kaboom")

    agent = build_agent(Boom(script=[]), [add])
    buf, out = _capture()
    final = await run_turn(agent, "hi", "t", out, context=CTX)
    assert final == ""
    assert "[the turn failed: RuntimeError: kaboom]" in "".join(buf)


async def test_chat_loop_reads_the_context_holder_before_each_turn():
    fake = FakeAgent()
    holder = [athlete_context()]
    lines = iter(["one", "/sync", "two"])

    async def read():
        return next(lines, None)

    async def sync():
        holder[0] = athlete_context(today=date(2026, 9, 7))
        return "context swapped"

    buf, out = _capture()
    await chat_loop(fake, read=read, out=out, context=lambda: holder[0], commands={"sync": sync})
    assert [c[3].today for c in fake.calls] == [date(2026, 9, 6), date(2026, 9, 7)]
    assert all(c[1]["tags"] == ["chat"] for c in fake.calls)
    assert all(c[1]["configurable"]["thread_id"] == "analyze" for c in fake.calls)
    assert "context swapped" in "".join(buf)


async def test_chat_loop_runs_commands_and_quits():
    model = ScriptedChatModel(script=[AIMessage(content="hello")])
    agent = build_agent(model, [add])
    inputs = iter(["/tools", "hi there", "/quit", "never read"])

    async def read():
        return next(inputs, None)

    buf, out = _capture()

    async def tools_cmd():
        return "tools: add"

    await chat_loop(agent, read=read, out=out, context=lambda: CTX, commands={"tools": tools_cmd})
    text = "".join(buf)
    assert "tri-analyze chat" in text and "/quit" in text and "tools" in text
    assert "tools: add" in text
    assert "hello" in text
    assert model.calls == 1


async def test_chat_loop_handles_eof_and_unknown_command():
    agent = build_agent(ScriptedChatModel(script=[]), [add])
    inputs = iter(["/nope", "   "])

    async def read():
        return next(inputs, None)

    buf, out = _capture()
    await chat_loop(agent, read=read, out=out, context=lambda: CTX)
    assert any("unknown command: /nope" in s for s in buf)


def test_turn_printer_ignores_non_text_chunks_and_text_of_reads_blocks():
    p = TurnPrinter(lambda s: None)
    p.on_event(
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert p.final_text == "x"
    assert text_of(AIMessage(content=[{"type": "text", "text": "a"}, "b"])) == "ab"
    assert text_of(AIMessage(content="plain")) == "plain"
