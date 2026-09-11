"""Race-day fueling prompt: the model writes the race timeline inside Python-set bounds."""

from __future__ import annotations

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    PlanContext,
    Product,
    RaceFuelPlan,
)
from tri_nutrition.prompts.fuel import _library_block, _log_block, _profile_block

RACE_SYSTEM = f"""\
You are an endurance sports nutritionist writing the race-day fueling plan for one athlete's
triathlon. You return a RaceFuelPlan: event_date; timeline, a list of steps with offset_min from
the race start (negative before), leg (pre | swim | t1 | bike | t2 | run | post), what (plain
words), carbs_g, fluid_ml, sodium_mg, caffeine_mg for that step, and products (library names
used in the step, empty for real food or water); totals_per_h with keys bike_carbs, run_carbs,
bike_fluid, run_fluid, bike_sodium, run_sodium (per hour of that leg); contingencies (two to four
short lines: GI trouble, heat, a dropped bottle); note_text, the calendar-note text (a compact
timeline the athlete can read on race morning, plain text, no markdown).

Hard rules (a validator rejects the plan otherwise):
- The pre-race meal step must fall between {-C.PRE_RACE_WINDOW_MIN[1] // 60} and
  {-C.PRE_RACE_WINDOW_MIN[0] // 60} hours before the start.
- Per-hour carbs on the bike and run follow the same evidence tiers as training: above
  {C.FUEL_CARBS_TIER_1} g/h needs a logged ok session at or above {C.FUEL_CARBS_TIER_1}; above
  {C.FUEL_CARBS_TIER_2} needs one at or above {C.FUEL_CARBS_TIER_2}; never above
  {C.FUEL_CARBS_MAX}.
- Fluid at most {C.FUEL_FLUID_MAX_ML_PER_H} ml/h; sodium between {C.FUEL_SODIUM_MIN_MG_PER_H}
  and {C.FUEL_SODIUM_MAX_MG_PER_H} mg/h per leg.
- Total race caffeine at most {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg per kg; none if the athlete
  takes none.
- Only products from the library, named exactly.
Nitrate (beetroot) may be mentioned as an optional pre-race item; no other supplements."""


def render_race_prompt(
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    ctx: PlanContext,
    target: DayTarget | None,
    violations: list[str] | None,
    previous: RaceFuelPlan | None,
) -> str:
    name = ctx.event_name or ctx.goal_type or "race"
    parts = [
        f"Event: {name} ({ctx.goal_type or 'unknown distance'}) on {ctx.event_date}, "
        f"priority {ctx.event_priority or 'A'}.",
        (
            f"Race-day target: {target.total_kcal} kcal, {target.carbs_g} g carbs for the day "
            "(in-race intake is on top)."
            if target
            else "Race-day target: not available."
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
