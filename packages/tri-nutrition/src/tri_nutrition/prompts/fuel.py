"""Session fueling prompt: the model writes one session's fuel plan inside Python-set bounds."""

from __future__ import annotations

import json

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    Session,
    SessionFuel,
)

PROMPT_VERSION = "3"  # bump when FUEL_SYSTEM or RACE_SYSTEM changes; names the eval experiment

FUEL_SYSTEM = f"""\
You are an endurance sports nutritionist writing the fueling plan for one training session of
one athlete. You return a SessionFuel: tp_workout_id and day copied from the session; pre (what
to eat and when before the session, one or two sentences); carbs_g_per_h, fluid_ml_per_h,
sodium_mg_per_h during the session; caffeine_mg for the session or null; products, a list of
product names taken verbatim from the athlete's product library; post (recovery intake in one
sentence); gut_training (true when the plan deliberately pushes intake above what the athlete has
tolerated before, to train the gut); note_text, the text that goes on the TrainingPeaks workout
(4 to 8 short lines: pre, during per hour with product counts, sodium, caffeine, post). Plain
text, no markdown.

Hard rules (a validator rejects the plan otherwise):
- carbs_g_per_h above {C.FUEL_CARBS_TIER_1} needs a logged session with outcome ok at or above
  {C.FUEL_CARBS_TIER_1} g/h; above {C.FUEL_CARBS_TIER_2} needs one at or above
  {C.FUEL_CARBS_TIER_2}; never above {C.FUEL_CARBS_MAX}. The fuel log is given; when it is empty
  stay at or below {C.FUEL_CARBS_TIER_1}.
- fluid_ml_per_h at most {C.FUEL_FLUID_MAX_ML_PER_H}; sodium_mg_per_h between
  {C.FUEL_SODIUM_MIN_MG_PER_H} and {C.FUEL_SODIUM_MAX_MG_PER_H}.
- No caffeine when the athlete takes none; total caffeine for the day at most
  {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg per kg.
- Only products from the library. Name them exactly.
- Fuel on the bike must be realistic to carry on race day: no big meals, only small, calorically
  dense items that can be eaten quickly.
Respect restrictions, dislikes and GI history. Sessions under 90 minutes at endurance intensity
need little or nothing during; say so rather than inventing intake."""


def _library_block(library: list[Product]) -> str:
    if not library:
        return "Product library: empty (use real food and water only)."
    rows = [
        f"  {p.name}: {p.form}, {p.carbs_g:g} g carbs, {p.sodium_mg:g} mg sodium, "
        f"{p.caffeine_mg:g} mg caffeine per serving"
        for p in library
    ]
    return "Product library:\n" + "\n".join(rows)


def _log_block(fuel_log: list[FuelLogEntry]) -> str:
    if not fuel_log:
        return "Fuel log: empty (no evidence above 60 g/h)."
    rows = [
        f"  {e.day} {e.sport} {e.duration_min} min: {e.carbs_g_per_h} g/h, {e.outcome}"
        + (f" ({e.note})" if e.note else "")
        for e in fuel_log[-10:]
    ]
    return "Fuel log (most recent last):\n" + "\n".join(rows)


def _profile_block(profile: NutritionProfile) -> str:
    return json.dumps(
        {
            "weight_kg": profile.weight_kg,
            "pattern": profile.pattern,
            "restrictions": profile.restrictions,
            "dislikes": profile.dislikes,
            "gi_issues": profile.gi_issues,
            "caffeine_mg_per_day": profile.caffeine_mg_per_day,
            "known_sweat_rate_l_per_h": profile.known_sweat_rate_l_per_h,
            "fuel_notes": profile.fuel_notes,
            "constraints": profile.constraints,
        }
    )


def render_session_prompt(
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    session: Session,
    target: DayTarget | None,
    violations: list[str] | None,
    previous: SessionFuel | None,
) -> str:
    tss = f" Planned TSS {session.planned_tss:g}." if session.planned_tss else ""
    parts = [
        f"Session: {session.day} {session.sport} '{session.title}', {session.duration_min} min, "
        f"intensity {session.intensity}, tp_workout_id {session.tp_workout_id or 'none'}.{tss}",
        (
            f"Day target: {target.day_type} day, {target.total_kcal} kcal, "
            f"{target.carbs_g}/{target.protein_g}/{target.fat_g} g C/P/F, "
            f"fluid baseline {target.fluid_baseline_ml} ml."
            if target
            else "Day target: not available."
        ),
        "Athlete: " + _profile_block(profile),
        _library_block(library),
        _log_block(fuel_log),
    ]
    if violations and previous is not None:
        parts.append(
            "Your previous attempt was rejected by the validator:\n- "
            + "\n- ".join(violations)
            + "\nPrevious attempt: "
            + previous.model_dump_json()
            + "\nFix every violation and return the whole plan again."
        )
    return "\n\n".join(parts)
