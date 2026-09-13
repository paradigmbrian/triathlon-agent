from datetime import date

import yaml
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from tri_coach.models import Proposal
from tri_coach.repl import (
    TurnPrinter,
    label,
    parse_decision,
    proposals_from_yaml,
    proposals_to_yaml,
    render_review,
)


def proposals():
    return [
        Proposal.model_validate(
            {
                "id": "p1",
                "domain": "planning",
                "summary": "move it",
                "changes": [
                    {
                        "op": "move",
                        "tp_workout_id": "w1",
                        "new_date": "2026-09-18",
                        "reason": "rest",
                    }
                ],
            }
        ),
        Proposal.model_validate(
            {
                "id": "p2",
                "domain": "nutrition",
                "summary": "targets",
                "changes": [
                    {
                        "op": "set_day_targets",
                        "target_key": "2026-09-14",
                        "day": "2026-09-14",
                        "payload": {"calorie_goal": 2800},
                        "reason": "extend",
                    }
                ],
                "overrides": {"activity_factor": 1.45},
            }
        ),
    ]


def test_label_by_first_namespace_segment():
    assert label(()) == ""
    assert label(("coach:abc",)) == "coach"
    assert label(("planning:abc",)) == "planning"
    assert label(("planning:abc", "adjust:def")) == "planning"
    assert label(("nutrition:abc", "checkin:def")) == "nutrition"


def test_printer_streams_coach_tokens_and_labels_sub_graph_activity():
    out: list[str] = []
    p = TurnPrinter(out.append)
    p.on_event(
        ("coach:1",), "messages", (AIMessageChunk(content="Hel"), {"langgraph_node": "model"})
    )
    p.on_event(
        ("coach:1",), "messages", (AIMessageChunk(content="lo"), {"langgraph_node": "model"})
    )
    p.on_event(
        ("coach:1",),
        "updates",
        {
            "model": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "consult_planning",
                                "args": {"instruction": "x"},
                                "id": "c1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        },
    )
    p.on_event(
        ("planning:2", "adjust:3"),
        "messages",
        (AIMessageChunk(content="Looking at the week."), {"langgraph_node": "model"}),
    )
    p.on_event(
        ("planning:2", "adjust:3"),
        "updates",
        {
            "tools": {
                "messages": [
                    ToolMessage(content="{}", name="propose_calendar_changes", tool_call_id="x")
                ]
            }
        },
    )
    p.on_event(
        (),
        "updates",
        {
            "planning": {
                "messages": [
                    ToolMessage(
                        content="p1 (planning): move it", name="consult_planning", tool_call_id="c1"
                    )
                ]
            }
        },
    )
    p.on_event((), "updates", {"apply": {"messages": [AIMessage(content="planning: applied 1")]}})
    text = "".join(out)
    assert text.startswith("Hello")
    assert "→ consult_planning({'instruction': 'x'})" in text
    assert "[planning] Looking at the week." in text
    assert "[planning] ← propose_calendar_changes" in text
    assert "← consult_planning: p1 (planning): move it" in text
    assert "planning: applied 1" in text and p.final_text == "planning: applied 1"


def test_printer_captures_the_interrupt():
    from langgraph.types import Interrupt

    p = TurnPrinter(lambda s: None)
    p.on_event(
        (), "updates", {"__interrupt__": (Interrupt(value={"narration": "n", "proposals": []}),)}
    )
    assert p.interrupt == {"narration": "n", "proposals": []}


def test_render_review_groups_by_domain_and_ends_with_the_prompt():
    payload = {
        "narration": "Knee pain: move Wednesday.",
        "proposals": [p.model_dump(mode="json") for p in proposals()],
    }
    text = render_review(payload)
    assert text.startswith("Knee pain: move Wednesday.")
    assert "-- planning (p1): move it" in text and "-- nutrition (p2): targets" in text
    assert "w1" in text and "2026-09-14" in text
    assert "profile overrides: {'activity_factor': 1.45}" in text
    assert text.rstrip().endswith("approve / reject <note> / edit")


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject  keep Wednesday")
    assert d.action == "reject" and d.note == "keep Wednesday"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip_keeps_both_domains_and_overrides():
    text = proposals_to_yaml(proposals())
    doc = yaml.safe_load(text)
    assert list(doc) == ["p1", "p2"] and doc["p1"]["domain"] == "planning"
    doc["p1"]["changes"][0]["new_date"] = "2026-09-19"
    doc["p2"]["changes"] = []
    back = proposals_from_yaml(yaml.safe_dump(doc, sort_keys=False), proposals())
    assert [p.id for p in back] == ["p1", "p2"]
    assert back[0].changes[0].new_date == date(2026, 9, 19)
    assert back[1].changes == [] and back[1].overrides == {"activity_factor": 1.45}
