from datetime import date

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from tri_analyze.agent import build_agent
from tri_analyze.prompts.analyst import PROMPT_VERSION, render_system_prompt
from tri_analyze.testing import RecordingScriptedModel, athlete_context
from tri_core.testing import ScriptedChatModel, tool_call


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def mul(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


CTX = athlete_context()


def cfg(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def test_agent_runs_tool_loop_and_stops():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add])
    out = agent.invoke({"messages": [HumanMessage("add 2 and 3")]}, cfg("t1"), context=CTX)
    msgs = out["messages"]
    assert [type(m).__name__ for m in msgs] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    assert isinstance(msgs[2], ToolMessage) and msgs[2].content == "5"
    assert msgs[-1].content == "It is 5."
    assert model.calls == 2


def test_agent_remembers_across_turns_on_same_thread():
    model = ScriptedChatModel(script=[AIMessage(content="hi"), AIMessage(content="again")])
    saver = InMemorySaver()
    agent = build_agent(model, [add], checkpointer=saver)
    agent.invoke({"messages": [HumanMessage("one")]}, cfg("t2"), context=CTX)
    agent.invoke({"messages": [HumanMessage("two")]}, cfg("t2"), context=CTX)
    state = agent.get_state(cfg("t2")).values["messages"]
    assert [m.content for m in state] == ["one", "hi", "two", "again"]


def test_agent_threads_are_isolated():
    model = ScriptedChatModel(script=[AIMessage(content="a"), AIMessage(content="b")])
    agent = build_agent(model, [add])
    agent.invoke({"messages": [HumanMessage("x")]}, cfg("A"), context=CTX)
    agent.invoke({"messages": [HumanMessage("y")]}, cfg("B"), context=CTX)
    assert len(agent.get_state(cfg("B")).values["messages"]) == 2


def test_model_sees_the_prompt_rendered_from_the_context_and_bound_tools():
    model = RecordingScriptedModel(script=[AIMessage(content="hi")])
    agent = build_agent(model, [add, mul])
    agent.invoke({"messages": [HumanMessage("x")]}, cfg("t"), context=CTX)
    system = model.received[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == render_system_prompt(CTX, ["add", "mul"])
    assert "Tools bound this session: add, mul." in system.content


def test_a_new_context_changes_the_prompt_and_keeps_the_history():
    model = RecordingScriptedModel(script=[AIMessage(content="a"), AIMessage(content="b")])
    agent = build_agent(model, [add])
    agent.invoke({"messages": [HumanMessage("one")]}, cfg("t"), context=CTX)
    later = athlete_context(today=date(2026, 9, 7))
    agent.invoke({"messages": [HumanMessage("two")]}, cfg("t"), context=later)
    assert "Today is 2026-09-06." in model.received[0][0].content
    assert "Today is 2026-09-07." in model.received[1][0].content
    assert [m.content for m in model.received[1][1:]] == ["one", "a", "two"]
    assert [m.content for m in agent.get_state(cfg("t")).values["messages"]] == [
        "one",
        "a",
        "two",
        "b",
    ]


def test_tool_order_is_preserved_in_the_prompt():
    model = RecordingScriptedModel(script=[AIMessage(content="x")])
    build_agent(model, [mul, add]).invoke({"messages": [HumanMessage("x")]}, cfg("t"), context=CTX)
    assert "Tools bound this session: mul, add." in model.received[0][0].content


async def test_analyst_tag_and_prompt_version_reach_the_model_run():
    class Spy(BaseCallbackHandler):
        def __init__(self) -> None:
            self.tags: list[list[str]] = []
            self.metadata: list[dict] = []

        def on_chat_model_start(self, serialized, messages, *, tags=None, metadata=None, **kw):
            self.tags.append(list(tags or []))
            self.metadata.append(dict(metadata or {}))

    spy = Spy()
    model = ScriptedChatModel(script=[AIMessage(content="x")])
    agent = build_agent(model, [add])
    await agent.ainvoke(
        {"messages": [HumanMessage("x")]},
        {**cfg("t"), "tags": ["chat"], "callbacks": [spy]},
        context=CTX,
    )
    assert spy.tags and "analyst" in spy.tags[0] and "chat" in spy.tags[0]
    assert spy.metadata[0]["analyst_prompt_version"] == PROMPT_VERSION
