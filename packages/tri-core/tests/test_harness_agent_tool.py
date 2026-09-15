from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphInterrupt

from tri_core.harness.agent_tool import Invocation, agent_tool


class FakeAgent:
    """Records each ainvoke and answers with the given messages appended, or raises."""

    def __init__(self, messages: list[Any] | None = None, error: Exception | None = None):
        self.messages = messages if messages is not None else [AIMessage(content="answer")]
        self.error = error
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []

    async def ainvoke(self, payload, config, **kwargs):
        self.calls.append((payload, config, kwargs))
        if self.error is not None:
            raise self.error
        return {"messages": [*payload["messages"], *self.messages]}


def make(prepare, **overrides):
    opts: dict[str, Any] = {
        "name": "ask_fake",
        "description": "Ask the fake.",
        "prepare": prepare,
        "thread_prefix": "fake",
        "recursion_limit": 7,
        "failure": "The fake failed ({error}); carry on.",
        "empty": "The fake returned no answer.",
    }
    opts.update(overrides)
    return agent_tool(**opts)


async def test_agent_tool_runs_on_a_fresh_throwaway_thread_and_returns_the_final_text():
    agent = FakeAgent()
    t = make(lambda: Invocation(agent))
    assert t.name == "ask_fake" and t.description == "Ask the fake."
    assert await t.ainvoke({"question": "how?"}) == "answer"
    assert await t.ainvoke({"question": "again?"}) == "answer"
    (p1, c1, k1), (_, c2, _) = agent.calls
    assert isinstance(p1["messages"][0], HumanMessage) and p1["messages"][0].content == "how?"
    assert c1["recursion_limit"] == 7 and k1 == {}
    t1, t2 = c1["configurable"]["thread_id"], c2["configurable"]["thread_id"]
    assert t1.startswith("fake-") and t2.startswith("fake-") and t1 != t2


async def test_agent_tool_passes_context_only_when_set():
    agent = FakeAgent()
    ctx = object()
    await make(lambda: Invocation(agent, context=ctx)).ainvoke({"question": "q"})
    assert agent.calls[0][2] == {"context": ctx}


async def test_agent_tool_returns_the_failure_text_when_prepare_or_the_run_fails():
    def broken_prepare():
        raise RuntimeError("db down")

    assert (
        await make(broken_prepare).ainvoke({"question": "q"})
        == "The fake failed (RuntimeError: db down); carry on."
    )
    agent = FakeAgent(error=ValueError("bad"))
    assert (
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})
        == "The fake failed (ValueError: bad); carry on."
    )


async def test_agent_tool_lets_graph_control_flow_propagate():
    agent = FakeAgent(error=GraphInterrupt())
    with pytest.raises(GraphInterrupt):
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})


async def test_agent_tool_returns_the_empty_text_when_there_is_no_final_answer():
    call = AIMessage(
        content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    agent = FakeAgent(messages=[call])
    assert (
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})
        == "The fake returned no answer."
    )


def test_agent_tool_schema_is_one_question_string_titled_by_name():
    schema = make(lambda: Invocation(FakeAgent())).tool_call_schema.model_json_schema()
    assert schema["title"] == "ask_fake" and schema["required"] == ["question"]
    assert schema["properties"] == {"question": {"title": "Question", "type": "string"}}
