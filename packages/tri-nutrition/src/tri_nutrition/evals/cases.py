"""The (profile, training week) cases behind the LangSmith dataset. Plain JSON so the dataset can
be re-created from code; `today` is fixed so runs are comparable across prompt versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tri_nutrition.testing import PROFILE_ARGS

TODAY = "2026-09-14"  # a Monday
D = [f"2026-09-{14 + i:02d}" for i in range(7)]  # D[0] .. D[6], Monday to Sunday

GEL = {"name": "Gel", "form": "gel", "carbs_g": 25, "sodium_mg": 50}
DRINK = {"name": "Drink mix", "form": "drink", "carbs_g": 40, "sodium_mg": 400}
OAT_BAR = {"name": "Oat bar", "form": "bar", "carbs_g": 30, "sodium_mg": 100}
CHEWS = {"name": "Chews", "form": "chew", "carbs_g": 24, "sodium_mg": 40, "caffeine_mg": 25}


def session(
    day: str, sport: str, minutes: int, intensity: str, wid: str, tss: float | None = None
) -> dict[str, Any]:
    return {
        "day": day,
        "sport": sport,
        "duration_min": minutes,
        "intensity": intensity,
        "tp_workout_id": wid,
        "title": f"{sport} {minutes}",
        "planned_tss": tss,
    }


def profile(**over: Any) -> dict[str, Any]:
    return {**PROFILE_ARGS, **over}


@dataclass(frozen=True)
class EvalCase:
    name: str
    profile: dict[str, Any]
    sessions: list[dict[str, Any]]
    ctx: dict[str, Any]
    fuel_log: list[dict[str, Any]] = field(default_factory=list)
    today: str = TODAY

    def inputs(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "sessions": self.sessions,
            "ctx": self.ctx,
            "fuel_log": self.fuel_log,
            "today": self.today,
        }


PLAN: dict[str, Any] = {"source": "plan", "ftp_watts": 250, "phases": {TODAY: "build"}}

CASES: list[EvalCase] = [
    EvalCase(
        name="maintain_build_week",
        profile=profile(),
        sessions=[
            session(D[0], "bike", 120, "endurance", "w1", 100),
            session(D[2], "run", 45, "threshold", "w2", 60),
            session(D[4], "swim", 45, "endurance", "w3", 40),
            session(D[5], "bike", 180, "endurance", "w4", 170),
            session(D[6], "run", 90, "endurance", "w5", 80),
        ],
        ctx=PLAN,
    ),
    EvalCase(
        name="vegan_lose_gluten_free",
        profile=profile(
            weight_kg=70,
            body_fat_pct=20,
            sex="f",
            goal="lose",
            target_weight_kg=66,
            target_date="2026-12-01",
            pattern="vegan",
            restrictions=["gluten"],
            dislikes=["bananas"],
            tested_products=[OAT_BAR, DRINK],
        ),
        sessions=[
            session(D[0], "bike", 100, "endurance", "w1", 70),
            session(D[2], "run", 40, "threshold", "w2", 55),
            session(D[5], "run", 80, "endurance", "w3", 70),
        ],
        ctx={**PLAN, "ftp_watts": 190},
    ),
    EvalCase(
        name="race_week_olympic",
        profile=profile(),
        sessions=[
            session(D[0], "bike", 60, "endurance", "w1", 40),
            session(D[2], "run", 30, "race", "w2", 35),
            session(D[6], "brick", 150, "race", "w3", 180),
        ],
        ctx={
            "source": "plan",
            "ftp_watts": 250,
            "event_date": D[6],
            "event_priority": "A",
            "event_name": "City Tri",
            "goal_type": "olympic",
            "phases": {TODAY: "race"},
        },
        fuel_log=[
            {
                "day": "2026-09-05",
                "sport": "bike",
                "duration_min": 150,
                "carbs_g_per_h": 75,
                "products": ["Gel"],
                "outcome": "ok",
            },
        ],
    ),
    EvalCase(
        name="no_caffeine_reflux",
        profile=profile(caffeine_mg_per_day=0, gi_issues=["reflux"], tested_products=[GEL, DRINK]),
        sessions=[
            session(D[1], "run", 50, "vo2", "w1", 65),
            session(D[3], "bike", 150, "endurance", "w2", 130),
            session(D[5], "brick", 120, "tempo", "w3", 120),
        ],
        ctx=PLAN,
    ),
    EvalCase(
        name="gut_trained_ironman_base",
        profile=profile(
            weight_kg=85, tested_products=[GEL, DRINK, CHEWS], known_sweat_rate_l_per_h=1.2
        ),
        sessions=[
            session(D[1], "swim", 90, "endurance", "w1", 60),
            session(D[3], "run", 120, "endurance", "w2", 110),
            session(D[5], "bike", 240, "endurance", "w3", 200),
            session(D[6], "run", 100, "endurance", "w4", 90),
        ],
        ctx={**PLAN, "goal_type": "ironman", "phases": {TODAY: "base"}},
        fuel_log=[
            {
                "day": "2026-08-29",
                "sport": "bike",
                "duration_min": 240,
                "carbs_g_per_h": 90,
                "products": ["Gel", "Drink mix"],
                "outcome": "ok",
            },
            {
                "day": "2026-09-05",
                "sport": "bike",
                "duration_min": 240,
                "carbs_g_per_h": 100,
                "products": ["Gel", "Drink mix", "Chews"],
                "outcome": "ok",
            },
        ],
    ),
]
