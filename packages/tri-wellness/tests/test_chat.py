from datetime import date, datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.agent import build_agent
from tri_wellness.labs.models import PanelSummary, StoredReport
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.prompts.report import REPORT_RULES
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.repl import chat_loop, run_chat_turn
from tri_wellness.tools.findings import make_findings_tools


def summaries():
    return [
        PanelSummary(
            id=2,
            drawn_on=date(2026, 8, 20),
            lab_name="Quest",
            result_count=40,
            unmapped_count=1,
            has_report=True,
        ),
        PanelSummary(
            id=1,
            drawn_on=date(2026, 3, 1),
            lab_name="Quest",
            result_count=38,
            unmapped_count=0,
            has_report=True,
        ),
    ]


def report():
    return StoredReport(
        id=5,
        panel_id=2,
        ranges_version="2026-09-11.1",
        findings=[],
        report_md=(
            "disclaimer\n\n## Priorities\n1. Iron.\n\n## Retest plan\nFerritin in 8 weeks."
            "\n\n## Levers\nx"
        ),
        created_at=datetime(2026, 8, 21, 9, 0),
    )


def test_render_chat_prompt_contents():
    text = render_chat_prompt(
        {"ftp_watts": 260, "weight_kg": 74.5},
        "male",
        summaries(),
        report(),
        date(2026, 9, 11),
        ["query_training_db", "get_panel_findings", "get_marker_spec", "get_marker_history"],
    )
    assert "Today is 2026-09-11" in text and "Athlete: male" in text and "260 W" in text
    assert "panel 2: 2026-08-20 Quest, 40 results, report yes" in text
    assert "panel 1: 2026-03-01" in text
    assert "Latest report (panel 2, 2026-08-21)" in text
    assert "1. Iron." in text and "Ferritin in 8 weeks." in text and "## Levers" not in text
    assert "get_panel_findings" in text and "get_marker_history" in text
    assert REPORT_RULES in text
    bare = render_chat_prompt(None, "female", [], None, date(2026, 9, 11), ["query_training_db"])
    assert (
        "no panels stored" in bare
        and "no report yet" in bare
        and "thresholds: not available" in bare
    )


def no_db():
    def boom():
        raise AssertionError("this tool must not touch the database")

    return boom


async def test_agent_answers_with_a_findings_tool():
    reg = load_registry("male", MARKERS_PATH)
    tools = make_findings_tools(no_db(), reg)
    model = ScriptedChatModel(
        script=[
            tool_call("get_marker_spec", {"marker": "ferritin"}),
            AIMessage(content="Ferritin's functional range is 50-150 ng/mL."),
        ]
    )
    agent = build_agent(model, tools, "sys")
    out = []
    text = await run_chat_turn(agent, "what is the ferritin range?", "t1", out.append)
    assert text == "Ferritin's functional range is 50-150 ng/mL."
    printed = "".join(out)
    assert "→ get_marker_spec" in printed and "← get_marker_spec" in printed
    msgs = agent.get_state({"configurable": {"thread_id": "t1"}}).values["messages"]
    assert [type(m).__name__ for m in msgs] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "AIMessage",
    ]
    assert isinstance(msgs[2], ToolMessage) and '"key": "ferritin"' in msgs[2].content


async def test_chat_loop_dispatches_commands_with_arguments():
    model = ScriptedChatModel(script=[AIMessage(content="hi")])
    agent = build_agent(model, [], "sys")
    lines = iter(["/panels", "/report 2", "/nope", "hello", "/quit"])

    async def read():
        return next(lines, None)

    seen = []

    async def panels(arg: str) -> str:
        seen.append(("panels", arg))
        return "PANELS"

    async def show(arg: str) -> str:
        seen.append(("report", arg))
        return f"REPORT {arg}"

    out = []
    await chat_loop(
        agent,
        read=read,
        out=out.append,
        thread_id="t2",
        commands={"panels": panels, "report": show},
    )
    text = "".join(out)
    assert seen == [("panels", ""), ("report", "2")]
    assert (
        "PANELS" in text
        and "REPORT 2" in text
        and "unknown command: /nope" in text
        and "hi" in text
    )
    assert model.calls == 1
    msgs = agent.get_state({"configurable": {"thread_id": "t2"}}).values["messages"]
    assert isinstance(msgs[0], HumanMessage) and msgs[0].content == "hello"
