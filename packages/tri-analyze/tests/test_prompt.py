import json
from datetime import date
from pathlib import Path

import pytest

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.prompts.analyst import (
    FEEDBACK_RULES,
    NO_LIVE_TOOLS,
    PROMPT_VERSION,
    TOOL_GUIDE,
    WEEKDAYS,
    _zones_block,
    calendar_line,
    dated,
    render_system_prompt,
)
from tri_analyze.testing import athlete_context

STANDALONE = ["query_training_db", *GARMIN_LIVE_TOOLS, *TP_LIVE_TOOLS]
COACH_EXTRAS = ["read_body_composition", "read_intake_vs_targets"]


def test_render_includes_profile_load_and_tools():
    text = render_system_prompt(athlete_context(), ["query_training_db", "get_activity_splits"])
    assert (
        "Today is 2026-09-06 (Sun). Weeks start Monday: 2026-08-03, 2026-08-10, 2026-08-17, "
        "2026-08-24, 2026-08-31, 2026-09-07."
    ) in text
    assert "- 2026-09-05 (Sat): TSS 55, CTL 15.2" in text
    assert "FTP 230 W" in text and "4:30/km" in text and "1:44/100m" in text
    assert "LTHR 180 bpm, max HR 182 bpm" in text
    assert "CTL 15.2" in text and "TSB -7.3" in text and "readiness 51" in text
    assert "2026-09-05 (Sat) bike: Z2 ride [done] 60 -> 55" in text
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
    assert "2026-09-04 (Fri) swim: Drills [missed] 30 -> -" in text
    assert "2026-09-05 (Sat) bike: Z2 ride [done] 60 -> 55" in text
    assert "2026-09-06 (Sun) run: (untitled) [planned] 40 -> -" in text  # today counts as planned
    assert "2026-09-08 (Tue) run: Tempo [planned] 70 -> -" in text


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
    assert PROMPT_VERSION == "2"


def test_render_is_deterministic_and_pure():
    ctx = athlete_context()
    first = render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(ctx, STANDALONE)
    assert first == render_system_prompt(athlete_context(), list(STANDALONE))


def test_the_rules_ask_for_shown_arithmetic_and_a_literal_today():
    assert "show the arithmetic" in FEEDBACK_RULES
    assert "never use current_date" in FEEDBACK_RULES


def test_dated_names_the_weekday_in_fixed_english():
    assert dated(date(2026, 9, 12)) == "2026-09-12 (Sat)"
    assert dated(date(2026, 9, 16)) == "2026-09-16 (Wed)"
    assert WEEKDAYS[date(2026, 9, 16).weekday()] == "Wednesday"


def test_calendar_line_lists_six_mondays_from_four_weeks_back_to_next_week():
    expected = (
        "Weeks start Monday: 2026-08-17, 2026-08-24, 2026-08-31, 2026-09-07, 2026-09-14, "
        "2026-09-21."
    )
    assert calendar_line(date(2026, 9, 16)) == expected
    assert calendar_line(date(2026, 9, 14)) == expected  # today is a Monday
    assert calendar_line(date(2026, 9, 20)) == expected  # today is a Sunday


TP_SETTINGS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "tri-core/tests/fixtures/mcp/tp_get_athlete_settings.json"
    ).read_text()
)["result"]["settings"]


def _tp_zones(**over):
    return {
        "hr_zones": TP_SETTINGS["heartRateZones"],
        "power_zones": TP_SETTINGS["powerZones"],
        "pace_zones": TP_SETTINGS["speedZones"],
        **over,
    }


def test_zones_block_renders_the_synced_groups():
    block = _zones_block(_tp_zones())
    assert block.splitlines() == [
        "Athlete zones (from TrainingPeaks):",
        "- Bike power: Z1 0-135 W, Z2 136-184 W, Z3 185-220 W, Z4 221-257 W, Z5 258+ W",
        "- Run HR: Z1 117-152 bpm, Z2 153-161 bpm, Z3 162-170 bpm, Z4 171-179 bpm, Z5 180+ bpm",
        "- Bike HR: Z1 89-110 bpm, Z2 111-135 bpm, Z3 136-152 bpm, Z4 153-170 bpm, Z5 171+ bpm",
        "- Run pace: Z1 6:00-5:38/km, Z2 5:38-5:00/km, Z3 5:00-4:45/km, Z4 4:45-4:30/km, "
        "Z5 faster than 4:30/km",
        "- Swim pace: Z1 2:15-1:59/100m, Z2 1:59-1:49/100m, Z3 1:49-1:46/100m, "
        "Z4 1:46-1:40/100m, Z5 faster than 1:40/100m",
    ]


def test_zones_block_falls_back_to_the_default_groups_and_keeps_names():
    hr0 = [g for g in TP_SETTINGS["heartRateZones"] if g["workoutTypeId"] == 0]
    power0 = [g for g in TP_SETTINGS["powerZones"] if g["workoutTypeId"] == 0]
    block = _zones_block({"hr_zones": hr0, "power_zones": power0, "pace_zones": None})
    assert "- Bike power: Z1 0-102 W, Z2 103-139 W," in block
    assert "- Run HR: Z1 Recovery 0-126 bpm, Z2 Aerobic 127-141 bpm," in block
    assert "Z5A SuperThreshold 158-161 bpm" in block and "Z5C Anaerobic Capacity 169+ bpm" in block
    assert "Bike HR" not in block and "pace" not in block


def test_bike_hr_is_left_out_when_it_equals_run_hr():
    run = next(g for g in TP_SETTINGS["heartRateZones"] if g["workoutTypeId"] == 3)
    block = _zones_block(_tp_zones(hr_zones=[run, {**run, "workoutTypeId": 2}]))
    assert "- Run HR:" in block and "Bike HR" not in block


NOT_SYNCED = "Zones: not synced; prescribe only as a stated % of a threshold."


def test_zones_block_says_not_synced_without_zones():
    assert _zones_block(None) == NOT_SYNCED
    assert _zones_block({"ftp_watts": 250}) == NOT_SYNCED
    assert _zones_block({"hr_zones": None, "power_zones": [], "pace_zones": "x"}) == NOT_SYNCED
    assert NOT_SYNCED in render_system_prompt(athlete_context(), [])


@pytest.mark.parametrize(
    "garbled",
    [
        {"workoutTypeId": 2, "zones": None},
        {"workoutTypeId": 2, "zones": "Zone 1"},
        {"workoutTypeId": 2, "zones": []},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": 0}]},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": "0", "maximum": 9}]},
        {"workoutTypeId": 2, "zones": [{"label": "Zone 1", "minimum": True, "maximum": 9}]},
        {"workoutTypeId": 2, "zones": ["Zone 1"]},
        "not a group",
    ],
)
def test_a_garbled_group_is_skipped(garbled):
    assert _zones_block({"power_zones": [garbled]}) == NOT_SYNCED
    power0 = next(g for g in TP_SETTINGS["powerZones"] if g["workoutTypeId"] == 0)
    assert "- Bike power: Z1 0-102 W" in _zones_block({"power_zones": [garbled, power0]})


def test_a_zero_speed_bound_skips_the_pace_group():
    run = next(g for g in TP_SETTINGS["speedZones"] if g["workoutTypeId"] == 3)
    broken = {**run, "zones": [{"label": "Zone 1", "minimum": 0, "maximum": 0}]}
    assert _zones_block({"pace_zones": [broken]}) == NOT_SYNCED


def test_render_puts_the_zones_after_the_thresholds():
    profile = {**athlete_context().profile, **_tp_zones()}
    text = render_system_prompt(athlete_context(profile=profile), [])
    assert (
        text.index("Athlete thresholds") < text.index("Athlete zones") < text.index("Recent load")
    )
