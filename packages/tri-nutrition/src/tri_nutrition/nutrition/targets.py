"""Profile + horizon of sessions -> one DayTarget per day. Pure: no I/O, no model calls.
Spec §7.3 to §7.5."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import (
    DEFICIT_PAUSE_PHASES,
    DayTarget,
    DayType,
    NutritionProfile,
    Phase,
    PlanContext,
    Session,
)


def sessions_by_day(sessions: list[Session]) -> dict[date, list[Session]]:
    out: dict[date, list[Session]] = defaultdict(list)
    for s in sessions:
        out[s.day].append(s)
    return dict(out)


def macro_grams(
    day_type: DayType, session_kcal: float, maintenance_kcal: float, weight_kg: float
) -> tuple[int, int, int, int, bool]:
    """(carbs_g, protein_g, fat_g, total_kcal, fat_floor_hit). total is 4c + 4p + 9f exactly."""
    carbs_lo, carbs_hi, protein_per_kg, fat_min_per_kg = C.MACRO_TABLE[day_type]
    position = min(max(session_kcal / C.SESSION_KCAL_FULL_RANGE, 0.0), 1.0)
    carbs = round((carbs_lo + (carbs_hi - carbs_lo) * position) * weight_kg)
    protein = round(protein_per_kg * weight_kg)
    fat_min = round(fat_min_per_kg * weight_kg)
    remainder = maintenance_kcal - C.KCAL_PER_G_CARB * carbs - C.KCAL_PER_G_PROTEIN * protein
    fat = round(remainder / C.KCAL_PER_G_FAT)
    floor_hit = fat < fat_min
    if floor_hit:
        fat = fat_min
    total = C.KCAL_PER_G_CARB * carbs + C.KCAL_PER_G_PROTEIN * protein + C.KCAL_PER_G_FAT * fat
    return carbs, protein, fat, total, floor_hit


def daily_deficit_kcal(profile: NutritionProfile) -> int:
    weekly_budget = (
        profile.max_weekly_change_pct / 100 * profile.weight_kg * C.KCAL_PER_KG_BODY_MASS
    )
    return min(C.MAX_DEFICIT_KCAL_PER_DAY, round(weekly_budget / 7))


def goal_adjust(
    profile: NutritionProfile, day_type: DayType, phase: Phase | None
) -> tuple[int, list[str]]:
    """Signed kcal adjustment for the day and the notes explaining it. Spec §7.4."""
    if profile.goal == "lose":
        if day_type not in C.DEFICIT_DAY_TYPES:
            return 0, [C.NOTE_DEFICIT_PAUSED_DAY]
        if phase in DEFICIT_PAUSE_PHASES:
            return 0, [C.NOTE_DEFICIT_PAUSED_PHASE]
        return -daily_deficit_kcal(profile), [C.NOTE_DEFICIT]
    if profile.goal == "gain_lean" and day_type in C.SURPLUS_DAY_TYPES:
        return round((C.SURPLUS_KCAL_MIN + C.SURPLUS_KCAL_MAX) / 2), [C.NOTE_SURPLUS]
    return 0, []


def fluid_baseline_ml(profile: NutritionProfile, sessions: list[Session]) -> int:
    hours = sum(s.hours for s in sessions)
    per_h = (
        profile.known_sweat_rate_l_per_h * 1000
        if profile.known_sweat_rate_l_per_h is not None
        else C.FLUID_ML_PER_TRAINING_H
    )
    return round(C.FLUID_ML_PER_KG_DAY * profile.weight_kg + hours * per_h)


def _profile_hours_session(day: date, weekly_hours: float) -> Session:
    return Session(
        day=day,
        sport="bike",
        duration_min=round(weekly_hours * 60 / 7),
        intensity="endurance",
        title="assumed from weekly hours",
    )


def build(
    profile: NutritionProfile,
    sessions: list[Session],
    ctx: PlanContext,
    today: date,
    horizon_days: int,
) -> list[DayTarget]:
    by_day = sessions_by_day(sessions)
    base_kcal = energy.non_exercise_kcal(profile)
    out: list[DayTarget] = []
    for i in range(horizon_days):
        day = today + timedelta(days=i)
        notes: list[str] = []
        day_sessions = by_day.get(day, [])
        if ctx.source == "profile_hours" and not day_sessions:
            if ctx.weekly_hours:
                day_sessions = [_profile_hours_session(day, ctx.weekly_hours)]
                notes.append(C.NOTE_PROFILE_HOURS)
            else:
                notes.append(C.NOTE_NO_SESSIONS)
        dt = energy.day_type(day_sessions, day, ctx)
        phase = ctx.phases.get(energy.week_monday(day))
        s_kcal = round(sum(energy.session_kcal(s, profile, ctx.ftp_watts) for s in day_sessions))
        adjust, adjust_notes = goal_adjust(profile, dt, phase)
        notes.extend(adjust_notes)
        carbs, protein, fat, total, floor_hit = macro_grams(
            dt, s_kcal, base_kcal + s_kcal + adjust, profile.weight_kg
        )
        if floor_hit:
            notes.append(C.NOTE_FAT_FLOOR)
        out.append(
            DayTarget(
                day=day,
                day_type=dt,
                session_kcal=s_kcal,
                total_kcal=total,
                carbs_g=carbs,
                protein_g=protein,
                fat_g=fat,
                fluid_baseline_ml=fluid_baseline_ml(profile, day_sessions),
                goal_adjust_kcal=adjust,
                plan_phase=phase,
                source=ctx.source,
                notes=notes,
            )
        )
    return out
