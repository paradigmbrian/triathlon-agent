from datetime import date

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from tri_coach.allowlist import ANALYST_GARMIN_TOOLS, ANALYST_TP_TOOLS, GARMIN_TOOLS, TP_TOOLS
from tri_coach.graph.checkpointer import make_serde
from tri_coach.models import ApplyReport, Brief, ChangeSet, Proposal, ReviewDecision
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange


def planning_change():
    return {"op": "delete", "tp_workout_id": "w1", "reason": "knee pain"}


def nutrition_change():
    return {
        "op": "set_day_targets",
        "target_key": "2026-09-14",
        "day": "2026-09-14",
        "payload": {"calorie_goal": 2800},
        "reason": "extend horizon",
    }


def test_proposal_types_changes_by_domain():
    p = Proposal.model_validate(
        {"id": "p1", "domain": "planning", "summary": "drop", "changes": [planning_change()]}
    )
    assert isinstance(p.changes[0], CalendarChange) and p.question is None
    n = Proposal.model_validate(
        {"id": "p2", "domain": "nutrition", "summary": "targets", "changes": [nutrition_change()]}
    )
    assert isinstance(n.changes[0], NutritionChange) and n.overrides is None
    with pytest.raises(ValueError):
        Proposal.model_validate(
            {"id": "p3", "domain": "planning", "summary": "x", "changes": [nutrition_change()]}
        )


def test_proposal_render_names_id_domain_and_outcome():
    p = Proposal.model_validate(
        {
            "id": "p1",
            "domain": "planning",
            "summary": "drop tempo",
            "changes": [planning_change()],
            "violations": ["week over target by 12%"],
        }
    )
    text = p.render()
    assert text.startswith("p1 (planning): drop tempo") and "1 change" in text
    assert "violations: week over target by 12%" in text
    q = Proposal(id="p2", domain="nutrition", summary="", question="Which race day?")
    assert q.render() == "p2 (nutrition) asked instead of proposing: Which race day?"


def test_change_set_and_decision_round_trip():
    p = Proposal.model_validate(
        {"id": "p1", "domain": "planning", "summary": "s", "changes": [planning_change()]}
    )
    cs = ChangeSet(narration="Knee pain: drop Wednesday.", proposals=[p])
    d = ReviewDecision(action="edit", proposals=cs.proposals)
    again = ReviewDecision.model_validate(d.model_dump(mode="json"))
    assert again.proposals is not None and again.proposals[0].changes[0].op == "delete"
    assert ReviewDecision.model_validate({"action": "approve"}).note is None


def test_apply_report_line():
    r = ApplyReport(
        domain="planning",
        applied=2,
        skipped=["w9: not agent-authored"],
        remaining=1,
        error="tp_update_workout failed: boom",
        sessions_changed=True,
    )
    assert r.line() == (
        "planning: applied 2, skipped 1, 1 still pending; stopped: tp_update_workout failed: boom"
    )
    clean = ApplyReport(
        domain="nutrition", applied=1, skipped=[], remaining=0, error=None, sessions_changed=False
    )
    assert clean.line() == "nutrition: applied 1"


def test_brief_defaults():
    b = Brief(domain="planning", instruction="Drop w1.", tool_call_id="c1", message_id="m1")
    assert b.regenerate is False


def test_allowlists_are_unions_without_duplicates():
    assert sorted(set(GARMIN_TOOLS)) == GARMIN_TOOLS
    assert {
        "get_training_readiness",
        "get_hrv_data",
        "get_body_composition",
        "set_nutrition_daily_settings",
        "get_activity_splits",
    } <= set(GARMIN_TOOLS)
    assert {
        "tp_get_workout",
        "tp_get_workouts",
        "tp_create_workout",
        "tp_set_workout_note",
        "tp_apply_training_plan",
    } <= set(TP_TOOLS)
    assert ANALYST_GARMIN_TOOLS == [
        "get_activity",
        "get_activity_splits",
        "get_training_readiness",
        "get_hrv_data",
    ]
    assert ANALYST_TP_TOOLS == ["tp_get_workout"]
    assert not any(
        n.startswith(("set_", "tp_create", "tp_update", "tp_delete", "tp_apply"))
        for n in ANALYST_GARMIN_TOOLS + ANALYST_TP_TOOLS
    )


def test_serde_round_trips_state_types():
    serde = make_serde()
    assert isinstance(serde, JsonPlusSerializer)
    p = Proposal.model_validate(
        {"id": "p1", "domain": "nutrition", "summary": "s", "changes": [nutrition_change()]}
    )
    cs = ChangeSet(narration="n", proposals=[p])
    kind, data = serde.dumps_typed(cs)
    back = serde.loads_typed((kind, data))
    assert isinstance(back, ChangeSet) and back.proposals[0].changes[0].day == date(2026, 9, 14)
