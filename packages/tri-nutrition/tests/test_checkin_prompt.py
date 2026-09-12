from datetime import date

from tri_nutrition.prompts.checkin import BRIEF_PREFIX, CHECKIN_REQUEST, render_checkin_prompt


def test_directed_paragraph_names_the_prefix_and_bounds_the_run():
    text = render_checkin_prompt(date(2026, 9, 14))
    assert BRIEF_PREFIX == "Head coach brief:" and BRIEF_PREFIX in text
    assert "nothing else" in text and "at most one call" in text
    assert "Today is 2026-09-14" in text and CHECKIN_REQUEST in text
    # the check-in steps come first; the directed paragraph is a later carve-out
    assert text.index("run these") < text.index(BRIEF_PREFIX) < text.index("Never diagnose")
