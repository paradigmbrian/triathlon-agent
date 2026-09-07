from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from tests.fakes import ScriptedChatModel, tool_call
from tri_analyze.agent.agent import build_agent, make_model
from tri_analyze.config import Settings


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def test_make_model_uses_settings():
    m = make_model(Settings(_env_file=None, tri_model="claude-sonnet-5", anthropic_api_key="k"))
    assert m.model == "claude-sonnet-5"
    assert m.max_tokens == 16000


def test_agent_runs_tool_loop_and_stops():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = build_agent(model, [add], "sys")
    cfg = {"configurable": {"thread_id": "t1"}}
    out = agent.invoke({"messages": [HumanMessage("add 2 and 3")]}, config=cfg)
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
    agent = build_agent(model, [add], "sys", checkpointer=saver)
    cfg = {"configurable": {"thread_id": "t2"}}
    agent.invoke({"messages": [HumanMessage("one")]}, config=cfg)
    agent.invoke({"messages": [HumanMessage("two")]}, config=cfg)
    state = agent.get_state(cfg).values["messages"]
    assert [m.content for m in state] == ["one", "hi", "two", "again"]


def test_agent_threads_are_isolated():
    model = ScriptedChatModel(script=[AIMessage(content="a"), AIMessage(content="b")])
    agent = build_agent(model, [add], "sys")
    agent.invoke({"messages": [HumanMessage("x")]}, config={"configurable": {"thread_id": "A"}})
    agent.invoke({"messages": [HumanMessage("y")]}, config={"configurable": {"thread_id": "B"}})
    assert len(agent.get_state({"configurable": {"thread_id": "B"}}).values["messages"]) == 2
