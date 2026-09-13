import anthropic
import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from tri_analyze._old_agent.agent import build_agent
from tri_analyze._old_agent.repl import TurnPrinter, chat_loop, run_turn
from tri_core.testing import ScriptedChatModel, tool_call


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def _capture():
    buf: list[str] = []
    return buf, buf.append


async def test_run_turn_streams_text_and_shows_tool_calls():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add], "sys")
    buf, out = _capture()
    final = await run_turn(agent, "add 2 and 3", "t", out)
    text = "".join(buf)
    assert final == "It is 5."
    assert "→ add({'a': 2, 'b': 3})" in text
    assert "← add: 1 chars" in text
    assert text.rstrip().endswith("It is 5.")


async def test_run_turn_reports_api_errors_without_raising():
    class Boom(ScriptedChatModel):
        def _stream(self, *a, **k):
            raise anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.com")
            )

    agent = build_agent(Boom(script=[]), [add], "sys")
    buf, out = _capture()
    final = await run_turn(agent, "hi", "t", out)
    assert final == ""
    assert any("connection" in s.lower() for s in buf)


async def test_chat_loop_runs_commands_and_quits():
    model = ScriptedChatModel(script=[AIMessage(content="hello")])
    agent = build_agent(model, [add], "sys")
    inputs = iter(["/tools", "hi there", "/quit"])

    async def read():
        return next(inputs, None)

    buf, out = _capture()

    async def tools_cmd():
        return "tools: add"

    await chat_loop(agent, read=read, out=out, commands={"tools": tools_cmd})
    text = "".join(buf)
    assert "tools: add" in text
    assert "hello" in text
    assert model.calls == 1


async def test_chat_loop_handles_eof_and_unknown_command():
    agent = build_agent(ScriptedChatModel(script=[]), [add], "sys")
    inputs = iter(["/nope"])

    async def read():
        return next(inputs, None)

    buf, out = _capture()
    await chat_loop(agent, read=read, out=out)
    assert any("unknown command" in s.lower() for s in buf)


def test_turn_printer_ignores_non_text_chunks():
    p = TurnPrinter(lambda s: None)
    p.on_event(
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert p.final_text == "x"
