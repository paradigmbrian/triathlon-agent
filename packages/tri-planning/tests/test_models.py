from datetime import date

import pytest
from pydantic import ValidationError

from tri_planning.planning.models import (
    CalendarChange,
    PlannedSession,
    PlannedWeek,
    ReviewDecision,
    TrainingGoal,
)


def goal(**over):
    base = dict(
        goal_type="olympic",
        event_name="City Tri",
        event_date=date(2026, 12, 13),
        priority="A",
        weekly_hours_min=6,
        weekly_hours_max=10,
        available_days={"mon": [], "tue": ["swim", "run"], "sat": "any"},
    )
    base.update(over)
    return TrainingGoal(**base)


def test_missing_weekdays_become_unavailable():
    g = goal()
    assert g.available_days["wed"] == []
    assert g.available_days["sat"] == "any"
    assert set(g.available_days) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_race_goal_requires_event_date():
    with pytest.raises(ValidationError, match="event_date"):
        goal(event_date=None)


def test_non_race_goal_requires_duration():
    with pytest.raises(ValidationError, match="duration_weeks"):
        goal(goal_type="build", event_date=None)
    g = goal(goal_type="build", event_date=None, duration_weeks=6)
    assert g.duration_weeks == 6


def test_hours_range_ordered():
    with pytest.raises(ValidationError, match="weekly_hours_min"):
        goal(weekly_hours_min=12, weekly_hours_max=10)


def test_week_totals():
    s1 = PlannedSession(
        date=date(2026, 9, 14),
        sport="bike",
        title="Endurance",
        description="z2",
        duration_minutes=90,
        tss_planned=70,
        intensity="endurance",
        structure=None,
    )
    s2 = PlannedSession(
        date=date(2026, 9, 15),
        sport="run",
        title="Tempo",
        description="",
        duration_minutes=60,
        tss_planned=65,
        intensity="tempo",
        structure=None,
    )
    w = PlannedWeek(week_start=date(2026, 9, 14), sessions=[s1, s2], coach_note="steady")
    assert w.total_tss == 135
    assert w.total_hours == 2.5


def test_calendar_change_roundtrip_json():
    c = CalendarChange(
        op="delete", tp_workout_id="123", reason="athlete asked", athlete_requested=True
    )
    again = CalendarChange.model_validate(c.model_dump(mode="json"))
    assert again == c


def test_review_decision_defaults():
    d = ReviewDecision(action="approve")
    assert d.note is None and d.changes is None
