import contextlib
from datetime import date
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from tri_coach.graph.llm import make_subagent
from tri_coach.models import Brief, ProposalRequest
from tri_coach.text import last_ai_text
from tri_coach.tools.analyst import make_analyst_tool
from tri_coach.tools.handoff import make_handoff_tools, turn_messages
from tri_coach.tools.wellness import make_wellness_tool, wellness_tools
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.testing import seed_panel


def test_turn_messages_is_everything_after_the_last_human_message():
    h1, a1, h2 = HumanMessage("a", id="1"), AIMessage("b", id="2"), HumanMessage("c", id="3")
    a2 = AIMessage(
        "", id="4", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    t2 = ToolMessage("r", tool_call_id="c1", id="5")
    assert turn_messages([h1, a1, h2, a2, t2]) == [a2, t2]
    assert turn_messages([h1, a1]) == [a1]
    assert turn_messages([]) == []


class Outer(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    brief: Brief | None
    proposal_request: ProposalRequest | None
    reached: str


def outer_graph(model, tools):
    """The shape the coach graph uses: a node function wraps the agent; planning, nutrition and
    review are reachable only through the tools' Commands."""
    agent = make_subagent(model, tools, "sys")

    async def coach(state: Outer) -> dict[str, Any]:
        before = state.get("messages", [])
        out = await agent.ainvoke({"messages": before})
        return {"messages": out["messages"][len(before) :]}

    def mark(name):
        def node(state: Outer) -> dict[str, Any]:
            return {"reached": name}

        return node

    g: StateGraph[Outer] = StateGraph(Outer)
    g.add_node("coach", coach, destinations=("planning", "nutrition", "review", END))
    for n in ("planning", "nutrition", "review"):
        g.add_node(n, mark(n))
        g.add_edge(n, END)
    g.add_edge(START, "coach")
    g.add_edge("coach", END)
    return g.compile()


async def test_consult_planning_hands_off_with_a_valid_history():
    model = ScriptedChatModel(
        script=[tool_call("consult_planning", {"instruction": "Drop w1; hold TSS."})]
    )
    graph = outer_graph(model, make_handoff_tools())
    out = await graph.ainvoke({"messages": [HumanMessage("my knee hurts")]})
    assert out["reached"] == "planning"
    brief = out["brief"]
    assert isinstance(brief, Brief) and brief.domain == "planning"
    assert brief.instruction == "Drop w1; hold TSS." and brief.tool_call_id == "c1"
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage"]
    ai, tm = out["messages"][1], out["messages"][2]
    assert ai.tool_calls[0]["name"] == "consult_planning"
    assert tm.tool_call_id == "c1" and tm.id == brief.message_id and tm.name == "consult_planning"
    assert "planning" in tm.content


async def test_consult_nutrition_and_propose_changes_route_and_carry_state():
    model = ScriptedChatModel(
        script=[tool_call("consult_nutrition", {"instruction": "Extend targets."})]
    )
    graph = outer_graph(model, make_handoff_tools())
    out = await graph.ainvoke({"messages": [HumanMessage("targets?")]})
    assert out["reached"] == "nutrition" and out["brief"].domain == "nutrition"

    model = ScriptedChatModel(
        script=[
            tool_call(
                "propose_changes",
                {"narration": "Knee pain: drop Wednesday.", "proposal_ids": ["p1"]},
            )
        ]
    )
    graph = outer_graph(model, make_handoff_tools())
    out = await graph.ainvoke({"messages": [HumanMessage("go ahead")]})
    assert out["reached"] == "review"
    assert out["proposal_request"] == ProposalRequest(
        narration="Knee pain: drop Wednesday.", ids=["p1"]
    )
    assert [type(m).__name__ for m in out["messages"]] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
    ]
    assert "p1" in out["messages"][-1].content


async def test_handoff_after_an_earlier_tool_call_keeps_that_call_too():
    @tool
    def ask_analyst(question: str) -> str:
        """fake analyst"""
        return "CTL 45, TSB -12."

    model = ScriptedChatModel(
        script=[
            tool_call("ask_analyst", {"question": "tsb?"}, call_id="a1"),
            tool_call("consult_planning", {"instruction": "Lighten the week."}, call_id="c2"),
        ]
    )
    graph = outer_graph(model, [ask_analyst, *make_handoff_tools()])
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]})
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage", "ToolMessage"]
    assert out["messages"][2].content == "CTL 45, TSB -12." and out["reached"] == "planning"
    assert len({m.id for m in out["messages"]}) == 5  # nothing duplicated


class RecordingModel(ScriptedChatModel):
    """A scripted model that records the kwargs create_agent binds its tools with."""

    bind_kwargs: list[dict[str, Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingModel":
        self.bind_kwargs.append(kwargs)
        return self


async def test_the_coach_sub_agent_disables_parallel_tool_calls():
    model = RecordingModel(script=[AIMessage(content="hi")])
    graph = outer_graph(model, make_handoff_tools())
    await graph.ainvoke({"messages": [HumanMessage("hello")]})
    assert model.bind_kwargs and model.bind_kwargs[0].get("parallel_tool_calls") is False


async def test_a_sibling_call_in_a_handoff_step_gets_a_not_delivered_result():
    @tool
    def remember(text: str) -> str:
        """fake memory"""
        return "ok"

    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "remember", "args": {"text": "knee"}, "id": "r1", "type": "tool_call"},
                    {
                        "name": "consult_planning",
                        "args": {"instruction": "Lighten the week."},
                        "id": "c1",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    )
    graph = outer_graph(model, [remember, *make_handoff_tools()])
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]})
    assert out["reached"] == "planning"
    results = {m.tool_call_id: m for m in out["messages"] if isinstance(m, ToolMessage)}
    assert set(results) == {"r1", "c1"}  # no tool_use id is left without a result
    assert results["r1"].content.startswith("not delivered")
    assert results["r1"].name == "remember"


async def test_a_sibling_call_in_a_propose_step_gets_a_not_delivered_result():
    @tool
    def remember(text: str) -> str:
        """fake memory"""
        return "ok"

    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "remember", "args": {"text": "knee"}, "id": "r1", "type": "tool_call"},
                    {
                        "name": "propose_changes",
                        "args": {"narration": "Move it.", "proposal_ids": ["p1"]},
                        "id": "c9",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    )
    graph = outer_graph(model, [remember, *make_handoff_tools()])
    out = await graph.ainvoke({"messages": [HumanMessage("go")]})
    assert out["reached"] == "review"
    results = {m.tool_call_id: m for m in out["messages"] if isinstance(m, ToolMessage)}
    assert set(results) == {"r1", "c9"}
    assert results["r1"].content.startswith("not delivered")


@pytest.mark.db
async def test_ask_analyst_runs_the_analyst_on_a_throwaway_thread(nocommit):
    @tool
    def query_training_db(sql: str) -> str:
        """fake db tool"""
        return "[]"

    analyst = ScriptedChatModel(
        script=[
            tool_call("query_training_db", {"sql": "select 1"}),
            AIMessage(content="Your CTL is 45."),
        ]
    )
    ask = make_analyst_tool(
        analyst,
        [query_training_db],
        lambda: contextlib.nullcontext(nocommit),
        lambda: date(2026, 9, 14),
    )
    assert ask.name == "ask_analyst"
    assert "\n " not in ask.description  # the raw __doc__ would carry its source indent
    assert await ask.ainvoke({"question": "what is my CTL?"}) == "Your CTL is 45."
    assert analyst.calls == 2
    # a second question starts fresh: the analyst does not remember the first
    analyst.script.extend([AIMessage(content="Fresh answer.")])
    assert await ask.ainvoke({"question": "again?"}) == "Fresh answer."


def test_last_ai_text_takes_the_last_answer_without_tool_calls():
    calls = AIMessage(
        content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    assert last_ai_text([AIMessage(content="first"), calls]) == "first"
    assert last_ai_text([AIMessage(content=[{"type": "text", "text": "blocks"}])]) == "blocks"
    assert last_ai_text([HumanMessage("only human")]) == ""


def test_wellness_tools_are_read_only(registry):
    tools = wellness_tools(
        lambda: contextlib.nullcontext(None), Settings().test_database_url, registry
    )
    assert [t.name for t in tools] == [
        "query_training_db",
        "get_panel_findings",
        "get_marker_spec",
        "get_marker_history",
    ]


@pytest.mark.db
async def test_ask_wellness_runs_the_lab_interpreter_on_a_throwaway_thread(ldb, registry):
    seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    wellness = ScriptedChatModel(
        script=[
            tool_call("get_panel_findings", {"panel": "latest"}),
            AIMessage(content="Ferritin 18 ng/mL is functionally low."),
        ]
    )
    ask = make_wellness_tool(
        wellness,
        lambda: contextlib.nullcontext(ldb),
        Settings().test_database_url,
        registry,
        lambda: date(2026, 9, 14),
    )
    assert ask.name == "ask_wellness"
    assert "\n " not in ask.description
    assert await ask.ainvoke({"question": "how is my ferritin?"}) == (
        "Ferritin 18 ng/mL is functionally low."
    )
    assert wellness.calls == 2
    # a second question starts fresh: the interpreter does not remember the first
    wellness.script.extend([AIMessage(content="Fresh answer.")])
    assert await ask.ainvoke({"question": "again?"}) == "Fresh answer."
