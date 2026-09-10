"""Terminal REPL for the nutrition graph: stream a turn, show node activity, run the review
dialogue, render the horizon table. (Task 8 fills in the rest.)"""

from __future__ import annotations

from tri_nutrition.nutrition.models import DayTarget


def render_targets(targets: list[DayTarget]) -> str:
    lines = [f"{'day':10}  {'type':9}  {'kcal':>5}  {'C/P/F g':>13}  {'train':>5}  notes"]
    for t in targets:
        macros = f"{t.carbs_g}/{t.protein_g}/{t.fat_g}"
        lines.append(
            f"{t.day.isoformat():10}  {t.day_type:9}  {t.total_kcal:>5}  {macros:>13}  "
            f"{t.session_kcal:>5}  {', '.join(t.notes)}"
        )
    return "\n".join(lines)
