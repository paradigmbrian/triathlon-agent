"""Every periodization constant. Change numbers here; the tests in test_skeleton.py pin them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tri_planning.planning.models import GoalType, Phase


@dataclass(frozen=True)
class PhaseSpec:
    race: int
    taper: int
    peak: int
    build: int
    minimum_weeks: int
    shape: Literal["remaining", "all_build", "all_base", "all_recovery"]


# Spec §7.1. "remaining" means: base takes whatever is left after the fixed phases.
PHASE_TABLE: dict[GoalType, PhaseSpec] = {
    "sprint": PhaseSpec(race=1, taper=1, peak=2, build=4, minimum_weeks=8, shape="remaining"),
    "olympic": PhaseSpec(race=1, taper=1, peak=3, build=5, minimum_weeks=12, shape="remaining"),
    "half_ironman": PhaseSpec(
        race=1, taper=2, peak=3, build=6, minimum_weeks=16, shape="remaining"
    ),
    "ironman": PhaseSpec(race=1, taper=3, peak=4, build=8, minimum_weeks=20, shape="remaining"),
    "build": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=4, shape="all_build"),
    "maintenance": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=2, shape="all_base"),
    "recovery": PhaseSpec(race=0, taper=0, peak=0, build=0, minimum_weeks=1, shape="all_recovery"),
}

# Spec §7.2 load progression.
MAX_WEEKLY_RAMP = 0.08
MAX_CTL_RISE_PER_WEEK = 5.0
CTL_TIME_CONSTANT_DAYS = 42
RECOVERY_EVERY_N_WEEKS = 4
IRONMAN_BUILD_RECOVERY_EVERY_N_WEEKS = 3
RECOVERY_WEEK_FACTOR = 0.60
TAPER_FACTORS: tuple[float, ...] = (0.80, 0.60, 0.45)
RACE_WEEK_FACTOR = 0.30
RECOVERY_GOAL_FACTOR = 0.50

# Week-1 floor when there is no recent load and no CTL.
GOAL_FLOOR_TSS: dict[GoalType, float] = {
    "sprint": 250,
    "olympic": 300,
    "half_ironman": 350,
    "ironman": 400,
    "build": 300,
    "maintenance": 250,
    "recovery": 200,
}

# Assumed intensity factor per phase: TSS = hours * IF^2 * 100.
PHASE_IF: dict[Phase, float] = {
    "base": 0.70,
    "build": 0.75,
    "peak": 0.80,
    "taper": 0.75,
    "race": 0.75,
    "recovery": 0.65,
}

SPORT_HINTS: dict[Phase, str] = {
    "base": "Swim and run frequency first; bike is aerobic and steady. Mostly endurance intensity, "
    "one tempo session at most.",
    "build": "Bike volume grows and one brick (bike into run) appears each week. One threshold "
    "session per sport at most, never on consecutive days.",
    "peak": "Race-specific: bricks at race pace, race-pace intervals in each sport. Hold volume, "
    "raise intensity.",
    "taper": "Keep session frequency, cut duration sharply. Short race-pace touches only.",
    "race": "Openers early in the week, rest the two days before, the race itself is not planned "
    "here.",
    "recovery": "Easy, short, optional. No intensity above endurance.",
}

FLAG_COMPRESSED = "compressed"
FLAG_HOURS_CAPPED = "hours_capped"

# Bought-plan phase inference: weeks at or above this fraction of the max are "peak".
PEAK_PLATEAU_FRACTION = 0.9
