from datetime import date

from tri_coach import memory as M
from tri_coach.context import CoachContext
from tri_coach.prompts.coach import COACH_RULES, PROMPT_VERSION, render_system_prompt


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
    assert PROMPT_VERSION == "1"


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
        "Do not remember what planning or nutrition already store",
        "say when a memory entry influenced a decision",
        "[review]",
    ):
        assert phrase in COACH_RULES, phrase
