"""The single-turn routing cases behind the LangSmith dataset. Each input holds a rendered context
block, the memory block and the conversation; each output lists the routes the coach may take.
Today is fixed (Wednesday 2026-09-16) so runs are comparable across prompt versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from tri_coach import memory as M
from tri_coach.context import CoachContext, LabSummary, render_context
from tri_coach.prompts.coach import CHECKIN_REQUEST
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS
from tri_planning.planning.models import (
    PlanWeekRow,
    StoredGoal,
    StoredPlan,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.testing import GOAL_ARGS, MONDAY

Route = Literal["none", "analyst", "wellness", "planning", "nutrition", "both"]
ROUTES: tuple[Route, ...] = ("none", "analyst", "wellness", "planning", "nutrition", "both")

TODAY = MONDAY + timedelta(days=2)

FERRITIN_LOW = LabSummary(
    panel_id=1,
    drawn_on=date(2026, 8, 30),
    lab_name="Quest",
    report_on=date(2026, 9, 1),
    outside_optimal=2,
    markers=24,
    priorities=(
        "Ferritin 18 ng/mL is functionally low: iron-rich meals with vitamin C, retest in 8 "
        "weeks. Vitamin D 28 ng/mL is suboptimal: 2000 IU daily through winter."
    ),
)

CLEAN_WEEK = (
    "Last 7 days: 6 of 6 planned sessions done, 410 of 420 TSS, no RPE above 7, no low feeling "
    "scores. Readiness and HRV at the 30-day baseline. Intake within 5 percent of targets on "
    "logged days. Weight steady."
)
FERRITIN_ANSWER = (
    "Ferritin 18 ng/mL on the 2026-08-30 panel, functional low (optimal 50 to 150); retest due "
    "late October."
)


def case_context(
    *,
    labs: LabSummary | None = None,
    designed_remaining: int = 3,
    targets_days: int = 10,
) -> str:
    goal = StoredGoal(id=1, goal=TrainingGoal(**GOAL_ARGS), status="active")
    weeks = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=420, target_hours=8
        )
        for i in range(12)
    ]
    plan = StoredPlan(
        id=1,
        goal_id=1,
        source="generated",
        tp_plan_id=None,
        start_date=MONDAY,
        end_date=MONDAY + timedelta(weeks=12, days=-1),
        targets=weeks,
        status="active",
    )
    this_week = PlanWeekRow(
        plan_id=1,
        week_start=MONDAY,
        phase="build",
        target_tss=420,
        target_hours=8,
        designed=None,
        written_to_tp=True,
    )
    days = [
        {
            "metric_date": (TODAY - timedelta(days=7 - i)).isoformat(),
            "tss_day": 50 + 5 * i,
            "ctl": 52 + 0.3 * i,
            "atl": 57 + 0.5 * i,
            "tsb": -8.0,
            "sleep_score": 78,
            "hrv_overnight_avg": 62,
            "training_readiness": 70,
        }
        for i in range(7)
    ]
    ctx = CoachContext(
        today=TODAY,
        thresholds={
            "ftp_watts": 250,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 100,
            "lthr_bpm": 165,
            "max_hr_bpm": 190,
        },
        phase="active",
        goal=goal,
        plan=plan,
        this_week=this_week,
        actual_tss=130.0,
        actual_hours=2.5,
        designed_remaining=designed_remaining,
        profile=NutritionProfile(**PROFILE_ARGS),
        targets_through=TODAY + timedelta(days=targets_days),
        recent_days=days,
        labs_enabled=labs is not None,
        labs=labs,
    )
    return render_context(ctx)


def case_memory(*entries: tuple[M.MemoryKind, str]) -> str:
    return M.render(
        [
            M.MemoryEntry(id=f"m{i:05d}", kind=kind, text=text, created=TODAY - timedelta(days=3))
            for i, (kind, text) in enumerate(entries)
        ],
        TODAY,
    )


@dataclass(frozen=True)
class EvalCase:
    name: str
    message: str
    expected: tuple[Route, ...]
    pure_question: bool = False
    labs_enabled: bool = False
    context: str = field(default_factory=case_context)
    memory: str = field(default_factory=case_memory)
    history: tuple[tuple[str, str], ...] = ()  # ("user" | "assistant", content), oldest first
    analyst_answer: str = CLEAN_WEEK
    wellness_answer: str = FERRITIN_ANSWER

    def inputs(self) -> dict[str, Any]:
        turns = [*self.history, ("user", self.message)]
        return {
            "context": self.context,
            "memory": self.memory,
            "messages": [{"role": role, "content": text} for role, text in turns],
            "labs_enabled": self.labs_enabled,
            "analyst_answer": self.analyst_answer,
            "wellness_answer": self.wellness_answer,
        }

    def outputs(self) -> dict[str, Any]:
        return {"expected_routes": list(self.expected), "pure_question": self.pure_question}


CASES: list[EvalCase] = [
    EvalCase(
        name="sleep_question",
        message="How has my sleep been this week?",
        expected=("none", "analyst"),
        pure_question=True,
    ),
    EvalCase(
        name="tsb_from_context",
        message="What's my TSB today?",
        expected=("none", "analyst"),
        pure_question=True,
    ),
    EvalCase(
        name="weight_trend_question",
        message="Am I losing weight at the rate my goal allows?",
        expected=("analyst",),
        pure_question=True,
        analyst_answer="Weight 80.4 kg to 79.6 kg over 28 days; body fat 16.1 to 15.8 percent.",
    ),
    EvalCase(
        name="ferritin_question",
        message="Is my ferritin still low?",
        expected=("wellness",),
        pure_question=True,
        labs_enabled=True,
        context=case_context(labs=FERRITIN_LOW),
    ),
    EvalCase(
        name="labs_not_configured",
        message="What did my last blood test say?",
        expected=("none",),
        pure_question=True,
    ),
    EvalCase(
        name="encouragement",
        message="Nailed the tempo run this morning, felt great.",
        expected=("none",),
        pure_question=True,
    ),
    EvalCase(
        name="knee_pain_planning",
        message=(
            "My left knee has hurt on every run since Sunday: sharp on the outside after about "
            "20 minutes."
        ),
        expected=("planning",),
    ),
    EvalCase(
        name="travel_planning",
        message="I'm travelling Thursday to Sunday next week with no bike, only a hotel gym.",
        expected=("planning",),
    ),
    EvalCase(
        name="protein_nutrition",
        message=("The scale says I've lost 1.5 kg of muscle in a month. Can we raise my protein?"),
        expected=("nutrition",),
        analyst_answer="Muscle mass 38.1 kg on 2026-08-16 and 36.6 kg on 2026-09-15.",
    ),
    EvalCase(
        name="move_ride_and_gluten_free",
        message=(
            "Move Saturday's long ride to Sunday, and note that I've gone gluten free this week."
        ),
        expected=("both",),
    ),
    EvalCase(
        name="flat_long_rides_with_low_ferritin",
        message=(
            "I've felt flat on every long ride this month. Should we change how I eat around them?"
        ),
        expected=("nutrition",),
        labs_enabled=True,
        context=case_context(labs=FERRITIN_LOW),
        analyst_answer=(
            "Long rides: power down 6 percent at the same heart rate over 4 weeks; intake logged "
            "on 3 of 4 long-ride days, 400 to 600 kcal under target."
        ),
    ),
    EvalCase(
        name="checkin_clean_week",
        message=CHECKIN_REQUEST,
        expected=("analyst",),
        pure_question=True,
        memory=case_memory(("checkin", "Last week on plan; watch the left knee on long runs.")),
    ),
    EvalCase(
        name="checkin_needs_the_next_week_designed",
        message=CHECKIN_REQUEST,
        expected=("planning",),
        context=case_context(designed_remaining=1),
    ),
]
