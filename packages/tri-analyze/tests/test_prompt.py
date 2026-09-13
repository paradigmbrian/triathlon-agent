from datetime import date

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.prompts.analyst import (
    FEEDBACK_RULES,
    NO_LIVE_TOOLS,
    PROMPT_VERSION,
    TOOL_GUIDE,
    render_system_prompt,
)
from tri_analyze.testing import athlete_context

STANDALONE = ["query_training_db", *GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
COACH_EXTRAS = ["read_body_composition", "read_intake_vs_targets"]


def test_render_includes_profile_load_and_tools():
    text = render_system_prompt(athlete_context(), ["query_training_db", "get_activity_splits"])
    assert "Today is 2026-09-06." in text
    assert "FTP 230 W" in text and "4:30/km" in text and "1:44/100m" in text
    assert "LTHR 180 bpm, max HR 182 bpm" in text
    assert "CTL 15.2" in text and "TSB -7.3" in text and "readiness 51" in text
    assert "2026-09-05 bike: Z2 ride [done] 60 -> 55" in text
    assert "Tools bound this session: query_training_db, get_activity_splits." in text


def test_render_marks_done_planned_and_missed():
    workouts = [
        {
            "workout_date": date(2026, 9, 4),
            "sport": "swim",
            "title": "Drills",
            "completed": False,
            "planned_tss": 30,
            "actual_tss": None,
        },
        {
            "workout_date": date(2026, 9, 5),
            "sport": "bike",
            "title": "Z2 ride",
            "completed": True,
            "planned_tss": 60,
            "actual_tss": 55,
        },
        {
            "workout_date": date(2026, 9, 6),
            "sport": "run",
            "title": None,
            "completed": False,
            "planned_tss": 40,
            "actual_tss": None,
        },
        {
            "workout_date": date(2026, 9, 8),
            "sport": "run",
            "title": "Tempo",
            "completed": False,
            "planned_tss": 70,
            "actual_tss": None,
        },
    ]
    text = render_system_prompt(athlete_context(recent_workouts=workouts), [])
    assert "2026-09-04 swim: Drills [missed] 30 -> -" in text
    assert "2026-09-05 bike: Z2 ride [done] 60 -> 55" in text
    assert "2026-09-06 run: (untitled) [planned] 40 -> -" in text  # today counts as planned
    assert "2026-09-08 run: Tempo [planned] 70 -> -" in text


def test_render_without_profile_or_data_hints_tri_sync():
    text = render_system_prompt(
        athlete_context(profile=None, recent_days=[], recent_workouts=[]), ["query_training_db"]
    )
    assert "Athlete thresholds: not available (run `tri sync`)." in text
    assert "tri-analyze sync" not in text
    assert "Recent load: not available." in text
    assert "Recent and upcoming workouts: not available." in text


def test_no_live_sentence_only_when_sql_alone_is_bound():
    assert NO_LIVE_TOOLS in render_system_prompt(athlete_context(), ["query_training_db"])
    assert NO_LIVE_TOOLS in render_system_prompt(athlete_context(), [])
    assert "Tools bound this session: none." in render_system_prompt(athlete_context(), [])
    with_live = render_system_prompt(athlete_context(), ["query_training_db", "get_hrv_data"])
    assert NO_LIVE_TOOLS not in with_live


def test_guide_lines_only_for_bound_tools_including_coach_extras():
    bound = ["query_training_db", "get_activity_splits", "read_body_composition"]
    text = render_system_prompt(athlete_context(), bound)
    assert (
        "Tools bound this session: query_training_db, get_activity_splits, read_body_composition."
        in text
    )
    for name in bound:
        assert f"- {name}: {TOOL_GUIDE[name]}" in text, name
    for name in (
        "get_training_readiness",
        "get_hrv_data",
        "tp_get_workout",
        "read_intake_vs_targets",
    ):
        assert name not in text, name
    assert "- get_activity:" not in text  # a prefix of a bound name, not bound itself


def test_guide_lines_follow_bound_order():
    text = render_system_prompt(athlete_context(), ["tp_get_workout", "query_training_db"])
    assert text.index("- tp_get_workout:") < text.index("- query_training_db:")


def test_unknown_bound_tool_is_listed_without_a_guide_line():
    text = render_system_prompt(athlete_context(), ["query_training_db", "mystery_tool"])
    assert "Tools bound this session: query_training_db, mystery_tool." in text
    assert "- mystery_tool:" not in text
    assert "- query_training_db:" in text


def test_every_allow_listed_and_coach_tool_has_a_guide_entry():
    for name in STANDALONE + COACH_EXTRAS:
        assert name in TOOL_GUIDE, name
    assert set(TOOL_GUIDE) == set(STANDALONE + COACH_EXTRAS)
    assert "workouts.garmin_activity_id" in TOOL_GUIDE["get_activity_splits"]
    assert "days" in TOOL_GUIDE["read_body_composition"]


def test_render_feedback_rules_present_and_version_is_1():
    text = render_system_prompt(athlete_context(), [])
    assert FEEDBACK_RULES in text
    for phrase in ("planned vs", "zones", "CTL/ATL/TSB", "takeaway", "SQL"):
        assert phrase.lower() in text.lower(), phrase
    assert PROMPT_VERSION == "1"


def test_render_is_deterministic_and_pure():
    ctx = athlete_context()
    first = render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(athlete_context(), list(STANDALONE))
