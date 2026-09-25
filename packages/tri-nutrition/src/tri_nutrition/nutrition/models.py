"""Nutrition vocabulary shared by the energy math, targets builder, bounds, repository and graph."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Sex = Literal["m", "f"]
Goal = Literal["lose", "maintain", "gain_lean"]
Pattern = Literal["omnivore", "pescatarian", "vegetarian", "vegan", "other"]
DayType = Literal["rest", "easy", "moderate", "hard", "long", "race", "carb_load"]
Sport = Literal["swim", "bike", "run", "brick", "strength"]
Intensity = Literal["recovery", "endurance", "tempo", "threshold", "vo2", "race"]
Phase = Literal["base", "build", "peak", "taper", "race", "recovery"]
Source = Literal["plan", "tp_calendar", "profile_hours"]
ProductForm = Literal["gel", "chew", "drink", "bar", "real_food", "other"]
Leg = Literal["pre", "swim", "t1", "bike", "t2", "run", "post"]
Outcome = Literal["ok", "gi_upset", "bonk", "cramps", "other"]
Operation = Literal["set_day_targets", "set_session_note", "set_race_note"]

HARD_INTENSITIES: frozenset[str] = frozenset({"threshold", "vo2", "race"})
DEFICIT_PAUSE_PHASES: frozenset[str] = frozenset({"peak", "taper", "race", "recovery"})
DEFICIT_FORBIDDEN_PHASES: frozenset[str] = frozenset({"peak", "taper", "race"})


class Product(BaseModel):
    name: str
    form: ProductForm
    carbs_g: float = Field(ge=0)
    sodium_mg: float = Field(default=0, ge=0)
    caffeine_mg: float = Field(default=0, ge=0)
    tested: bool = True


class NutritionProfile(BaseModel):
    height_cm: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    body_fat_pct: float | None = Field(default=None, ge=3, le=60)
    sex: Sex
    age: int = Field(ge=14, le=100)
    activity_factor: float = Field(default=1.35, ge=1.2, le=1.5)
    goal: Goal
    target_weight_kg: float | None = None
    target_date: date | None = None
    max_weekly_change_pct: float = Field(default=0.5, gt=0, le=1.0)
    pattern: Pattern
    restrictions: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    gi_issues: list[str] = Field(default_factory=list)
    meals_per_day: int = Field(ge=1, le=8)
    cooks: bool
    caffeine_mg_per_day: int | None = None
    alcohol_drinks_per_week: int | None = None
    tracks_food: bool
    scale_days_per_week: int = Field(ge=0, le=7)
    known_sweat_rate_l_per_h: float | None = None
    tested_products: list[Product] = Field(default_factory=list)
    fuel_notes: list[str] = Field(default_factory=list)
    unit_preference: Literal["metric", "imperial"]
    constraints: list[str] = Field(default_factory=list)
    medical_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _goal_consistent(self) -> NutritionProfile:
        if self.goal == "lose":
            if self.target_weight_kg is None:
                raise ValueError("a lose goal needs target_weight_kg")
            if self.target_weight_kg >= self.weight_kg:
                raise ValueError("target_weight_kg must be below weight_kg for a lose goal")
        if (
            self.goal == "gain_lean"
            and self.target_weight_kg is not None
            and self.target_weight_kg <= self.weight_kg
        ):
            raise ValueError("target_weight_kg must be above weight_kg for a gain_lean goal")
        return self


class FuelLogEntry(BaseModel):
    day: date
    tp_workout_id: str | None = None
    sport: Sport
    duration_min: int = Field(ge=0)
    carbs_g_per_h: int = Field(ge=0)
    products: list[str] = Field(default_factory=list)
    outcome: Outcome
    note: str = ""


class Session(BaseModel):
    """One planned session in the horizon, as read from plan_weeks.designed or workouts."""

    day: date
    sport: Sport
    duration_min: int = Field(ge=0)
    intensity: Intensity
    tp_workout_id: str | None = None
    title: str = ""
    planned_tss: float | None = None
    distance_km: float | None = None
    legs: list[Session] | None = None  # bricks only; None means split by BRICK_BIKE_FRACTION
    completed: bool = False  # only set from `workouts`; designed-plan sessions default False

    @property
    def hours(self) -> float:
        return self.duration_min / 60

    @model_validator(mode="after")
    def _legs_only_on_bricks(self) -> Session:
        if self.legs is not None and self.sport != "brick":
            raise ValueError("legs are only valid on a brick session")
        return self


class PlanContext(BaseModel):
    """What the targets builder needs beyond the profile and the sessions."""

    source: Source
    ftp_watts: int | None = None
    event_date: date | None = None
    event_priority: Literal["A", "B", "C"] | None = None
    event_name: str | None = None
    goal_type: str | None = None
    phases: dict[date, Phase] = Field(default_factory=dict)  # keyed by week Monday
    weekly_hours: float | None = None  # from the active goal; the profile_hours fallback


class DayTarget(BaseModel):
    day: date
    day_type: DayType
    session_kcal: int
    total_kcal: int
    carbs_g: int
    protein_g: int
    fat_g: int
    fluid_baseline_ml: int
    goal_adjust_kcal: int = 0
    plan_phase: Phase | None = None
    source: Source
    notes: list[str] = Field(default_factory=list)


class SessionFuel(BaseModel):
    tp_workout_id: str
    day: date
    pre: str
    carbs_g_per_h: int = Field(ge=0)
    fluid_ml_per_h: int = Field(ge=0)
    sodium_mg_per_h: int = Field(ge=0)
    caffeine_mg: int | None = None
    products: list[str]
    post: str
    gut_training: bool
    note_text: str


class RaceFuelStep(BaseModel):
    offset_min: int  # from race start; negative is before
    leg: Leg
    what: str
    carbs_g: int = Field(ge=0)
    fluid_ml: int = Field(ge=0)
    sodium_mg: int = Field(ge=0)
    caffeine_mg: int = Field(default=0, ge=0)
    products: list[str] = Field(default_factory=list)


class RaceFuelPlan(BaseModel):
    event_date: date
    timeline: list[RaceFuelStep]
    # bike_carbs, run_carbs, bike_fluid, run_fluid, bike_sodium, run_sodium
    totals_per_h: dict[str, int]
    contingencies: list[str]
    note_text: str


class NutritionChange(BaseModel):
    op: Operation
    target_key: str  # date, tp_workout_id, or tp_note_id (empty when creating)
    day: date
    payload: dict[str, Any]
    reason: str


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    changes: list[NutritionChange] | None = None


class StoredDayTarget(BaseModel):
    target: DayTarget
    written_to_garmin: bool


class StoredFuelPlan(BaseModel):
    id: int
    kind: Literal["session", "race"]
    day: date
    tp_workout_id: str | None
    tp_note_id: str | None
    payload: dict[str, Any]
    violations: list[str]
    written: bool
