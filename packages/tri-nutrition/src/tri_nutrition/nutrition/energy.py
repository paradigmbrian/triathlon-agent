"""RMR, session energy and day type. Pure: no I/O, no model calls. Spec §7.1 and §7.2."""

from __future__ import annotations

from datetime import date, timedelta

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import (
    HARD_INTENSITIES,
    DayType,
    NutritionProfile,
    PlanContext,
    Session,
)


def ffm(profile: NutritionProfile) -> float:
    """Fat-free mass in kg. Uses the profile's body fat or the assumed value for the sex."""
    pct = profile.body_fat_pct
    if pct is None:
        pct = C.ASSUMED_BODY_FAT_PCT[profile.sex]
    return profile.weight_kg * (1 - pct / 100)


def rmr(profile: NutritionProfile) -> float:
    """Cunningham when body fat is known, else Mifflin-St Jeor."""
    if profile.body_fat_pct is not None:
        return C.CUNNINGHAM_BASE + C.CUNNINGHAM_PER_KG_FFM * ffm(profile)
    return (
        10 * profile.weight_kg
        + 6.25 * profile.height_cm
        - 5 * profile.age
        + C.MIFFLIN_SEX_TERM[profile.sex]
    )


def non_exercise_kcal(profile: NutritionProfile) -> float:
    return rmr(profile) * profile.activity_factor


def _fallback(session: Session, weight_kg: float) -> float:
    return session.hours * weight_kg * C.SPORT_KCAL_PER_KG_H[session.sport][session.intensity]


def session_kcal(session: Session, profile: NutritionProfile, ftp_watts: int | None) -> float:
    w = profile.weight_kg
    if session.sport == "brick":
        legs = session.legs
        if legs is None:
            # The bike leg gets its share of the brick's TSS; the run leg is priced by duration
            # and intensity. Neither leg inherits the whole brick's distance.
            bike_min = round(session.duration_min * C.BRICK_BIKE_FRACTION)
            tss = session.planned_tss
            legs = [
                session.model_copy(
                    update={
                        "sport": "bike",
                        "duration_min": bike_min,
                        "planned_tss": tss * C.BRICK_BIKE_FRACTION if tss is not None else None,
                        "distance_km": None,
                        "legs": None,
                    }
                ),
                session.model_copy(
                    update={
                        "sport": "run",
                        "duration_min": session.duration_min - bike_min,
                        "planned_tss": None,
                        "distance_km": None,
                        "legs": None,
                    }
                ),
            ]
        return sum(session_kcal(leg, profile, ftp_watts) for leg in legs)
    if session.sport == "bike":
        if session.planned_tss is not None and ftp_watts:
            return session.planned_tss * ftp_watts * C.BIKE_KCAL_PER_TSS_FTP
        return _fallback(session, w)
    if session.sport == "run":
        if session.distance_km is not None:
            return w * session.distance_km
        return _fallback(session, w)
    if session.sport == "strength":
        return session.hours * C.STRENGTH_KCAL_PER_KG_H * w
    return _fallback(session, w)  # swim


def day_type(sessions: list[Session], day: date, ctx: PlanContext) -> DayType:
    """Spec §7.2. `sessions` are only that day's sessions. `long` is checked before `hard`
    (they share a macro row); two sessions totalling over 120 minutes with nothing above tempo
    are `moderate`."""
    if ctx.event_date is not None:
        if day == ctx.event_date:
            return "race"
        gap = (ctx.event_date - day).days
        if ctx.event_priority == "A" and 0 < gap <= C.CARB_LOAD_DAYS_BEFORE_RACE:
            return "carb_load"
    if not sessions:
        return "rest"
    if any(s.duration_min >= C.LONG_SESSION_MIN for s in sessions):
        return "long"
    if any(s.intensity in HARD_INTENSITIES for s in sessions):
        return "hard"
    total = sum(s.duration_min for s in sessions)
    tempo = sum(1 for s in sessions if s.intensity == "tempo")
    if total < C.EASY_MAX_MIN and tempo == 0:
        return "easy"
    return "moderate"


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())
