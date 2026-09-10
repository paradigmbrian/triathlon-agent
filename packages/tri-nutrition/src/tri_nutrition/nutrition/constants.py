"""Every tunable number in the nutrition math. Spec §7. Change a value here, rerun the tests."""

from __future__ import annotations

from tri_nutrition.nutrition.models import DayType, Intensity, Sex, Sport

# --- energy (§7.1) ---
CUNNINGHAM_BASE = 500.0
CUNNINGHAM_PER_KG_FFM = 22.0
# Mifflin-St Jeor: 10*kg + 6.25*cm - 5*age + sex term
MIFFLIN_SEX_TERM: dict[Sex, float] = {"m": 5.0, "f": -161.0}
ASSUMED_BODY_FAT_PCT: dict[Sex, float] = {"m": 18.0, "f": 26.0}  # when the profile has none
BIKE_KCAL_PER_TSS_FTP = 36 / 1000  # kJ per TSS per watt of FTP, taken as kcal
STRENGTH_KCAL_PER_KG_H = 5.0
BRICK_BIKE_FRACTION = 2 / 3  # of a brick's duration when legs are not given
# kcal per kg per hour by sport and intensity: the fallback when TSS/FTP or distance is missing.
# Run values equal km/h at that effort (kcal ~ kg x km); swim and bike are MET-derived.
_S = STRENGTH_KCAL_PER_KG_H
SPORT_KCAL_PER_KG_H: dict[Sport, dict[Intensity, float]] = {
    "run": {
        "recovery": 8.5,
        "endurance": 10.0,
        "tempo": 11.5,
        "threshold": 12.5,
        "vo2": 13.5,
        "race": 12.5,
    },
    "bike": {
        "recovery": 5.0,
        "endurance": 7.0,
        "tempo": 8.5,
        "threshold": 10.0,
        "vo2": 11.0,
        "race": 10.0,
    },
    "swim": {
        "recovery": 6.0,
        "endurance": 7.0,
        "tempo": 8.0,
        "threshold": 9.0,
        "vo2": 10.0,
        "race": 9.0,
    },
    "strength": {
        "recovery": _S,
        "endurance": _S,
        "tempo": _S,
        "threshold": _S,
        "vo2": _S,
        "race": _S,
    },
    "brick": {},  # bricks are the sum of their legs
}

# --- day type (§7.2) ---
EASY_MAX_MIN = 60  # strictly under
MODERATE_MAX_MIN = 120  # up to and including
LONG_SESSION_MIN = 150  # any single session at or over
CARB_LOAD_DAYS_BEFORE_RACE = 2  # only for an A-priority event

# --- macros, g per kg body mass (§7.3) ---
# (carbs_lo, carbs_hi, protein, fat_min)
MACRO_TABLE: dict[DayType, tuple[float, float, float, float]] = {
    "rest": (3.0, 4.0, 1.8, 0.8),
    "easy": (3.0, 4.0, 1.8, 0.8),
    "moderate": (5.0, 6.0, 1.8, 0.8),
    "hard": (7.0, 8.0, 2.0, 0.8),
    "long": (7.0, 8.0, 2.0, 0.8),
    "carb_load": (10.0, 10.0, 1.6, 0.6),
    "race": (8.0, 8.0, 1.6, 0.6),
}
SESSION_KCAL_FULL_RANGE = 1500.0  # session kcal at which carbs sit at the top of their range
KCAL_PER_G_CARB = 4
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_FAT = 9

# --- goal adjustment (§7.4) ---
KCAL_PER_KG_BODY_MASS = 7700.0
MAX_DEFICIT_KCAL_PER_DAY = 500
DEFICIT_DAY_TYPES: frozenset[str] = frozenset({"rest", "easy", "moderate"})
SURPLUS_DAY_TYPES: frozenset[str] = frozenset({"hard", "long"})
SURPLUS_KCAL_MIN = 200
SURPLUS_KCAL_MAX = 300

# --- fluids (§7.5) ---
FLUID_ML_PER_KG_DAY = 35
FLUID_ML_PER_TRAINING_H = 500  # when no sweat rate is known

# --- bounds (§7.6) ---
MIN_ENERGY_AVAILABILITY_KCAL_PER_KG_FFM = 30.0
MIN_PROTEIN_G_PER_KG = 1.6
MIN_HARD_DAY_CARBS_G_PER_KG = 6.0
FUEL_CARBS_TIER_1 = 60  # g/h allowed without evidence
FUEL_CARBS_TIER_2 = 90  # g/h allowed with an ok log entry >= 60
FUEL_CARBS_MAX = 120  # g/h never exceeded
FUEL_FLUID_MAX_ML_PER_H = 1000
FUEL_SODIUM_MIN_MG_PER_H = 300
FUEL_SODIUM_MAX_MG_PER_H = 1500
CAFFEINE_MAX_MG_PER_KG_DAY = 6.0
PRE_RACE_WINDOW_MIN = (-240, -120)  # offset_min of the pre-race step, inclusive

# --- notes (strings the builder attaches to DayTarget.notes) ---
NOTE_FAT_FLOOR = "fat_floor"
NOTE_DEFICIT = "deficit"
NOTE_DEFICIT_PAUSED_DAY = "deficit paused: hard, long, carb-load or race day"
NOTE_DEFICIT_PAUSED_PHASE = "deficit paused: peak, taper, race or recovery week"
NOTE_SURPLUS = "surplus"
NOTE_PROFILE_HOURS = "no planned sessions; typed from the goal's weekly hours"
NOTE_NO_SESSIONS = "no planned sessions and no active goal; treated as rest"
