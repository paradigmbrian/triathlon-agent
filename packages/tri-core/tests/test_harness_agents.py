from typing import Any

from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

import tri_core.harness.agents as agents
from tri_core.harness.agents import build_chat_agent, make_subagent, one_tool_call_at_a_time
from tri_core.llm import claude_fallback
from tri_core.testing import ScriptedChatModel, tool_call


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


class RecordingModel(ScriptedChatModel):
    """A scripted model that records the kwargs create_agent binds its tools with."""

    bind_kwargs: list[dict[str, Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingModel":
        self.bind_kwargs.append(kwargs)
        return self


async def test_make_subagent_runs_a_tool_round_trip_when_invoked_directly():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = make_subagent(model, [add], "sys")
    out = await agent.ainvoke({"messages": [HumanMessage("add 2 and 3")]})
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][2].content == "5"
    assert out["messages"][3].content == "It is 5."


async def test_one_tool_call_at_a_time_binds_tools_with_parallel_calls_off():
    model = RecordingModel(script=[AIMessage(content="hi")])
    agent = make_subagent(model, [add], "sys", middleware=[one_tool_call_at_a_time])
    await agent.ainvoke({"messages": [HumanMessage("hello")]})
    assert model.bind_kwargs and model.bind_kwargs[0].get("parallel_tool_calls") is False


async def test_build_chat_agent_keeps_history_per_thread_in_memory_by_default():
    model = ScriptedChatModel(script=[AIMessage(content="one"), AIMessage(content="two")])
    agent = build_chat_agent(model, [add], system_prompt="sys")
    cfg = {"configurable": {"thread_id": "t"}}
    await agent.ainvoke({"messages": [HumanMessage("a")]}, cfg)
    out = await agent.ainvoke({"messages": [HumanMessage("b")]}, cfg)
    assert [m.content for m in out["messages"]] == ["a", "one", "b", "two"]


def test_builders_put_prompt_caching_last_and_pass_their_arguments(monkeypatch):
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_create_agent(*args: Any, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "agent"

    monkeypatch.setattr(agents, "create_agent", fake_create_agent)
    model = ScriptedChatModel(script=[])
    saver = InMemorySaver()

    assert make_subagent(model, (add,), "sys", middleware=[one_tool_call_at_a_time]) == "agent"
    assert (
        build_chat_agent(
            model,
            [add],
            middleware=[one_tool_call_at_a_time],
            context_schema=dict,
            checkpointer=saver,
        )
        == "agent"
    )
    assert build_chat_agent(model, []) == "agent"

    (sub_args, sub), (chat_args, chat), (_, bare) = calls
    assert sub_args == (model, [add]) and chat_args == (model, [add])
    assert sub["system_prompt"] == "sys" and sub["checkpointer"] is False
    assert len(sub["middleware"]) == 3 and sub["middleware"][0] is one_tool_call_at_a_time
    assert sub["middleware"][1] is claude_fallback
    assert isinstance(sub["middleware"][2], AnthropicPromptCachingMiddleware)
    assert chat["middleware"][0] is one_tool_call_at_a_time
    assert chat["middleware"][1] is claude_fallback
    assert isinstance(chat["middleware"][2], AnthropicPromptCachingMiddleware)
    assert chat["context_schema"] is dict and chat["checkpointer"] is saver
    assert chat["system_prompt"] is None
    assert isinstance(bare["checkpointer"], InMemorySaver) and len(bare["middleware"]) == 2
    assert bare["middleware"][0] is claude_fallback
