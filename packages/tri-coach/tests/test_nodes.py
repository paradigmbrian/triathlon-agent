"""Coach graph nodes over stub sub-graphs: no database, no model."""

from datetime import date
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langgraph.graph import END

from tri_coach.graph.graph import after_apply
from tri_coach.graph.nodes.apply import _regeneration_due
from tri_coach.graph.nodes.nutrition import (
    FOLLOW_ON,
    follow_on_message,
    make_nutrition_node,
    proposal_from_regenerate,
)
from tri_coach.graph.nodes.planning import make_planning_node
from tri_coach.models import ApplyReport, Brief

CONFIG = {"configurable": {"thread_id": "coach"}}


class ExplodingConnect:
    """Raises if called: proves a guard short-circuited before touching the database."""

    def __call__(self):
        raise AssertionError("connect must not be reached when regeneration is not due")


class StubDeps:
    nutrition_deps = SimpleNamespace(horizon_days=3)

    def __init__(self) -> None:
        self.connect = ExplodingConnect()

    def today(self) -> date:
        return date(2026, 9, 14)


class Recorder:
    """A compiled sub-graph stand-in: records what it was invoked with, returns a fixed output."""

    def __init__(self, out):
        self.out = out
        self.inputs = []
        self.configs = []

    async def ainvoke(self, payload, config):
        self.inputs.append(payload)
        self.configs.append(config)
        return self.out


def test_after_apply_routes_to_nutrition_only_when_regeneration_is_due():
    assert after_apply({"regenerate_after_apply": True}) == "nutrition"
    assert after_apply({"regenerate_after_apply": False}) == END
    assert after_apply({}) == END


def test_regeneration_is_not_due_without_a_planning_report():
    nutrition_only = ApplyReport(
        domain="nutrition", applied=1, skipped=[], remaining=0, error=None, sessions_changed=False
    )
    assert _regeneration_due(StubDeps(), [nutrition_only]) is False


def test_regeneration_is_skipped_after_a_planning_apply_that_errored_mid_batch():
    """Spec 9: a planning ApplyResult can have sessions_changed=True from an applied op and
    error set from a later failed call in the same batch; that must not trigger regeneration.
    StubDeps.connect blows up if called, so this also proves the guard alone decides here,
    without ever checking whether nutrition targets exist in the horizon."""
    partial_batch = ApplyReport(
        domain="planning", applied=1, skipped=[], remaining=1, error="boom", sessions_changed=True
    )
    assert _regeneration_due(StubDeps(), [partial_batch]) is False


def test_a_regenerate_brief_needs_no_tool_call():
    b = Brief(domain="nutrition", instruction="regenerate", regenerate=True)
    assert b.tool_call_id is None and b.message_id is None


async def test_the_regenerate_brief_runs_the_targets_entry_and_appends_the_follow_on():
    change = {
        "op": "set_day_targets",
        "target_key": "2026-09-14",
        "day": "2026-09-14",
        "payload": {"calorie_goal": 2800},
        "reason": "easy day",
    }
    graph = Recorder(
        {"pending_changes": [change], "pending_summary": "Daily targets", "last_error": None}
    )
    node = make_nutrition_node(graph)
    brief = Brief(domain="nutrition", instruction="regenerate", regenerate=True)
    out = await node({"brief": brief, "proposals": []}, CONFIG)
    assert graph.inputs == [{"targets_requested": True, "regenerate_from": "checkin"}]
    assert "domain:nutrition" in graph.configs[0]["tags"]
    assert out["brief"] is None and out["regenerate_after_apply"] is False
    p = out["proposals"][0]
    assert p.id == "p1" and p.question is None and p.changes[0].op == "set_day_targets"
    msg = out["messages"][0]
    assert msg.content.startswith(FOLLOW_ON) and "call propose_changes with p1" in msg.content


def test_a_regeneration_that_changes_nothing_or_breaks_a_bound_says_so():
    same = proposal_from_regenerate(
        {"pending_changes": [], "pending_summary": "already on Garmin", "last_error": None}, "p1"
    )
    assert same.changes == [] and same.question is None
    assert "no changes" in follow_on_message(same).content
    bad = proposal_from_regenerate(
        {"pending_changes": [], "pending_summary": None, "last_error": "kcal below floor"}, "p1"
    )
    assert bad.violations == ["kcal below floor"] and bad.summary == "kcal below floor"
    assert "state the violations" in follow_on_message(bad).content


async def test_consultations_carry_a_domain_tag():
    graph = Recorder({"pending_changes": [], "messages": [AIMessage(content="Which day?")]})
    node = make_planning_node(graph)
    brief = Brief(domain="planning", instruction="x", tool_call_id="c1", message_id="m1")
    out = await node({"brief": brief, "proposals": []}, CONFIG)
    assert "domain:planning" in graph.configs[0]["tags"]
    assert out["messages"][0].id == "m1" and out["proposals"][0].question == "Which day?"
