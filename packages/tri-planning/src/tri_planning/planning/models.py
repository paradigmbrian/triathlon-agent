"""Planning vocabulary shared by the skeleton builder, validator, repository and graph."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

GoalType = Literal[
    "sprint", "olympic", "half_ironman", "ironman", "maintenance", "build", "recovery"
]
Phase = Literal["base", "build", "peak", "taper", "race", "recovery"]
Sport = Literal["swim", "bike", "run", "brick", "strength", "rest"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Intensity = Literal["recovery", "endurance", "tempo", "threshold", "vo2", "race"]
Priority = Literal["A", "B", "C"]
Availability = dict[Weekday, list[Sport] | Literal["any"]]

WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RACE_GOALS: frozenset[str] = frozenset({"sprint", "olympic", "half_ironman", "ironman"})
HARD_INTENSITIES: frozenset[str] = frozenset({"threshold", "vo2", "race"})


class TrainingGoal(BaseModel):
    goal_type: GoalType
    event_name: str | None = None
    event_date: date | None = None
    priority: Priority | None = None
    weekly_hours_min: float = Field(ge=0)
    weekly_hours_max: float = Field(gt=0)
    available_days: Availability
    constraints: list[str] = Field(default_factory=list)
    tp_plan_id: str | None = None
    create_tp_event: bool = False
    duration_weeks: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> TrainingGoal:
        if self.weekly_hours_min > self.weekly_hours_max:
            raise ValueError("weekly_hours_min must be <= weekly_hours_max")
        if self.goal_type in RACE_GOALS and self.event_date is None:
            raise ValueError(f"{self.goal_type} goals need an event_date")
        if self.goal_type not in RACE_GOALS and self.duration_weeks is None:
            raise ValueError(f"{self.goal_type} goals need duration_weeks")
        for day in WEEKDAYS:
            self.available_days.setdefault(day, [])
        return self


class WeekTarget(BaseModel):
    week_start: date
    phase: Phase
    target_tss: float
    target_hours: float
    is_recovery: bool = False
    flags: list[str] = Field(default_factory=list)
    sport_hint: str = ""


class PlannedSession(BaseModel):
    date: date
    sport: Sport
    title: str
    description: str
    duration_minutes: int = Field(ge=0)
    tss_planned: float = Field(ge=0)
    intensity: Intensity
    structure: dict[str, Any] | None = None

    @property
    def hours(self) -> float:
        return self.duration_minutes / 60


class PlannedWeek(BaseModel):
    week_start: date
    sessions: list[PlannedSession]
    coach_note: str

    @property
    def total_tss(self) -> float:
        return sum(s.tss_planned for s in self.sessions)

    @property
    def total_hours(self) -> float:
        return sum(s.hours for s in self.sessions)


class CalendarChange(BaseModel):
    op: Literal["create", "update", "delete", "move", "apply_plan", "create_event"]
    workout_date: date | None = None
    tp_workout_id: str | None = None
    workout: PlannedSession | None = None
    new_date: date | None = None
    payload: dict[str, Any] | None = None
    reason: str
    athlete_requested: bool = False


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    changes: list[CalendarChange] | None = None


class FitnessSnapshot(BaseModel):
    ctl: float | None = None
    recent_weekly_tss: float | None = None


class StoredGoal(BaseModel):
    id: int
    goal: TrainingGoal
    status: str
    tp_event_id: str | None = None


class StoredPlan(BaseModel):
    id: int
    goal_id: int
    source: Literal["generated", "tp_plan"]
    tp_plan_id: str | None
    start_date: date
    end_date: date
    skeleton: list[WeekTarget]
    status: str


class PlanWeekRow(BaseModel):
    plan_id: int
    week_start: date
    phase: Phase
    target_tss: float | None
    target_hours: float | None
    designed: PlannedWeek | None
    written_to_tp: bool
