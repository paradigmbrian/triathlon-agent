"""Safety bounds over targets and fuel plans. Pure; returns violations, never edits. Spec §7.6."""

from __future__ import annotations

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition import energy
from tri_nutrition.nutrition.models import (
    DEFICIT_FORBIDDEN_PHASES,
    DayTarget,
    FuelLogEntry,
    NutritionProfile,
    Product,
    RaceFuelPlan,
    SessionFuel,
)


def validate_targets(targets: list[DayTarget], profile: NutritionProfile) -> list[str]:
    out: list[str] = []
    ffm = energy.ffm(profile)
    rmr = energy.rmr(profile)
    w = profile.weight_kg
    for t in targets:
        ea = (t.total_kcal - t.session_kcal) / ffm
        if ea < C.MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM:
            out.append(
                f"{t.day}: energy availability {ea:.0f} kcal/kg FFM is below "
                f"{C.MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM:.0f}"
            )
        if t.total_kcal < rmr:
            out.append(f"{t.day}: total {t.total_kcal} kcal is below RMR {rmr:.0f}")
        if t.protein_g < C.MIN_PROTEIN_G_PER_KG * w:
            out.append(f"{t.day}: protein {t.protein_g} g is below {C.MIN_PROTEIN_G_PER_KG} g/kg")
        if t.day_type in ("hard", "long") and t.carbs_g < C.MIN_HARD_DAY_CARBS_G_PER_KG * w:
            out.append(
                f"{t.day}: carbs {t.carbs_g} g on a {t.day_type} day is below "
                f"{C.MIN_HARD_DAY_CARBS_G_PER_KG} g/kg"
            )
        if t.goal_adjust_kcal < 0 and t.plan_phase in DEFICIT_FORBIDDEN_PHASES:
            out.append(f"{t.day}: deficit of {-t.goal_adjust_kcal} kcal in a {t.plan_phase} week")
    weekly_budget = profile.max_weekly_change_pct / 100 * w * C.KCAL_PER_KG_BODY_MASS
    ordered = sorted(targets, key=lambda t: t.day)
    for i in range(len(ordered)):
        window = [t for t in ordered[i:] if (t.day - ordered[i].day).days < 7]
        deficit = -sum(min(t.goal_adjust_kcal, 0) for t in window)
        if deficit > weekly_budget + 0.5:
            out.append(
                f"{ordered[i].day}: seven-day deficit {deficit:.0f} kcal exceeds the "
                f"{profile.max_weekly_change_pct:g} %/week bound ({weekly_budget:.0f} kcal)"
            )
            break
    return out


def carbs_evidence(fuel_log: list[FuelLogEntry]) -> int:
    """Highest carbs/h the athlete has taken with outcome ok; 0 without evidence."""
    return max((e.carbs_g_per_h for e in fuel_log if e.outcome == "ok"), default=0)


def _carbs_per_h_violations(label: str, carbs: int, evidence: int) -> list[str]:
    if carbs > C.FUEL_CARBS_MAX:
        return [f"{label}: {carbs} g/h carbs exceeds the {C.FUEL_CARBS_MAX} g/h ceiling"]
    if carbs > C.FUEL_CARBS_TIER_2 and evidence < C.FUEL_CARBS_TIER_2:
        return [
            f"{label}: {carbs} g/h carbs needs a logged ok session at or above "
            f"{C.FUEL_CARBS_TIER_2} g/h (best so far: {evidence})"
        ]
    if carbs > C.FUEL_CARBS_TIER_1 and evidence < C.FUEL_CARBS_TIER_1:
        return [
            f"{label}: {carbs} g/h carbs needs a logged ok session at or above "
            f"{C.FUEL_CARBS_TIER_1} g/h (best so far: {evidence})"
        ]
    return []


def _fluid_sodium_violations(label: str, fluid: int | None, sodium: int | None) -> list[str]:
    """0 means none planned and is valid; the bounds apply to a positive value."""
    out: list[str] = []
    if fluid and fluid > C.FUEL_FLUID_MAX_ML_PER_H:
        out.append(f"{label}: fluid {fluid} ml/h exceeds {C.FUEL_FLUID_MAX_ML_PER_H}")
    if sodium and not (C.FUEL_SODIUM_MIN_MG_PER_H <= sodium <= C.FUEL_SODIUM_MAX_MG_PER_H):
        out.append(
            f"{label}: sodium {sodium} mg/h is outside {C.FUEL_SODIUM_MIN_MG_PER_H} to "
            f"{C.FUEL_SODIUM_MAX_MG_PER_H}"
        )
    return out


def _product_violations(label: str, names: list[str], library: list[Product]) -> list[str]:
    known = {p.name for p in library}
    return [
        f"{label}: product {n!r} is not in the product library" for n in names if n not in known
    ]


def _caffeine_violations(label: str, total_mg: float, profile: NutritionProfile) -> list[str]:
    if total_mg <= 0:
        return []
    if profile.caffeine_mg_per_day == 0:
        return [f"{label}: caffeine planned but the athlete takes none"]
    cap = C.CAFFEINE_MAX_MG_PER_KG_DAY * profile.weight_kg
    if total_mg > cap:
        return [
            f"{label}: caffeine {total_mg:.0f} mg exceeds {C.CAFFEINE_MAX_MG_PER_KG_DAY:g} mg/kg "
            f"({cap:.0f} mg)"
        ]
    return []


def validate_fuel(
    fuel: SessionFuel,
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
    other_caffeine_mg_today: int = 0,
) -> list[str]:
    label = f"{fuel.day} {fuel.tp_workout_id}"
    out = _carbs_per_h_violations(label, fuel.carbs_g_per_h, carbs_evidence(fuel_log))
    out += _fluid_sodium_violations(label, fuel.fluid_ml_per_h, fuel.sodium_mg_per_h)
    caffeine = fuel.caffeine_mg or 0
    if caffeine:
        out += _caffeine_violations(label, caffeine + other_caffeine_mg_today, profile)
    out += _product_violations(label, fuel.products, library)
    return out


def validate_race(
    plan: RaceFuelPlan,
    profile: NutritionProfile,
    library: list[Product],
    fuel_log: list[FuelLogEntry],
) -> list[str]:
    out: list[str] = []
    evidence = carbs_evidence(fuel_log)
    for leg in ("bike", "run"):
        label = f"{plan.event_date} {leg}"
        carbs = plan.totals_per_h.get(f"{leg}_carbs")
        if carbs is not None:
            out += _carbs_per_h_violations(label, carbs, evidence)
        out += _fluid_sodium_violations(
            label, plan.totals_per_h.get(f"{leg}_fluid"), plan.totals_per_h.get(f"{leg}_sodium")
        )
    lo, hi = C.PRE_RACE_WINDOW_MIN
    pre = [s for s in plan.timeline if s.leg == "pre"]
    if not pre:
        out.append(f"{plan.event_date}: no pre-race step")
    elif not any(lo <= s.offset_min <= hi for s in pre):
        out.append(
            f"{plan.event_date}: pre-race meal must fall {-hi // 60} to {-lo // 60} hours before "
            f"the start (offsets: {[s.offset_min for s in pre]})"
        )
    total_caffeine = sum(s.caffeine_mg for s in plan.timeline)
    out += _caffeine_violations(f"{plan.event_date} race", total_caffeine, profile)
    for s in plan.timeline:
        out += _product_violations(
            f"{plan.event_date} {s.leg} +{s.offset_min}", s.products, library
        )
    return out
