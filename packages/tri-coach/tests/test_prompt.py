from datetime import date

from tri_coach import memory as M
from tri_coach.context import CoachContext
from tri_coach.prompts.coach import (
    CHECKIN_REQUEST,
    COACH_RULES,
    PROMPT_VERSION,
    render_system_prompt,
)


def ctx():
    return CoachContext(
        today=date(2026, 9, 14),
        thresholds=None,
        phase="intake",
        goal=None,
        plan=None,
        this_week=None,
        actual_tss=0.0,
        actual_hours=0.0,
        designed_remaining=0,
        profile=None,
        targets_through=None,
        recent_days=[],
        pending=None,
    )


def test_prompt_order_is_rules_context_memory_and_names_the_limit():
    entries = [M.MemoryEntry(id="ab12cd", kind="injury", text="Knee.", created=date(2026, 9, 10))]
    text = render_system_prompt(ctx(), entries, max_consults=2)
    assert text.startswith(COACH_RULES.split("\n")[0])
    assert text.index("Today is") < text.index("Athlete memory")
    assert "at most 2 consultations per domain per turn" in text
    assert "ab12cd injury" in text
    assert PROMPT_VERSION == "3"


def test_rules_cover_policy_routing_and_memory():
    for phrase in (
        "You are the athlete's head coach",
        "Sub-agents never initiate a change",
        "name the signal, the lever and the constraint",
        "Pure questions never trigger a consultation",
        "ask_analyst",
        "consult_planning",
        "consult_nutrition",
        "propose_changes",
        "remember",
        "Do not remember what planning, nutrition or wellness already store",
        "say when a memory entry influenced a decision",
        "[review]",
        "ask_wellness",
        "Never brief a sub-agent to change a lab value",
        "lab values",
        "labs are not configured",
        "[follow-on]",
        "Consult no one in a follow-on",
        "say what could not be read",
        "needs consult_planning only",
        "logged intake against targets",
        "fewer than 2 means brief planning",
        "fewer than 7 days of targets left",
        "call remember with kind checkin",
        "Write it before propose_changes",
    ):
        assert phrase in COACH_RULES, phrase


def test_the_checklist_names_the_exact_check_in_request():
    assert CHECKIN_REQUEST == "Run the coach check-in."
    assert f'When the message is exactly "{CHECKIN_REQUEST}"' in COACH_RULES
    COACH_RULES.format(max_consults=2)  # still only the one placeholder
