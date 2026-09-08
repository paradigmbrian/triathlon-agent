"""Goal + fitness -> week targets. Pure: no I/O, no model calls."""

from __future__ import annotations

from datetime import date, timedelta

from tri_planning.planning import periodization as P
from tri_planning.planning.models import (
    FitnessSnapshot,
    GoalType,
    Phase,
    TrainingGoal,
    WeekTarget,
)

_DECAY = (1 - 1 / P.CTL_TIME_CONSTANT_DAYS) ** 7  # CTL carry-over across one week of constant load


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7)


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def count_weeks(goal: TrainingGoal, start: date) -> int:
    if goal.event_date is not None:
        n = (week_monday(goal.event_date) - start).days // 7 + 1
        if n < 1:
            raise ValueError("event_date is before the plan start")
        return n
    assert goal.duration_weeks is not None  # enforced by TrainingGoal
    return goal.duration_weeks


def allocate_phases(goal_type: GoalType, total_weeks: int) -> tuple[list[Phase], bool]:
    spec = P.PHASE_TABLE[goal_type]
    compressed = total_weeks < spec.minimum_weeks
    if spec.shape == "all_build":
        return ["build"] * total_weeks, compressed
    if spec.shape == "all_base":
        return ["base"] * total_weeks, compressed
    if spec.shape == "all_recovery":
        return ["recovery"] * total_weeks, compressed
    fixed_tail = spec.race + spec.taper + spec.peak
    build = min(spec.build, total_weeks - fixed_tail)
    if build < 0:
        raise ValueError(
            f"{goal_type} needs at least {fixed_tail} weeks for peak, taper and race; "
            f"got {total_weeks}"
        )
    base = total_weeks - fixed_tail - build
    layout: list[tuple[Phase, int]] = [
        ("base", base),
        ("build", build),
        ("peak", spec.peak),
        ("taper", spec.taper),
        ("race", spec.race),
    ]
    phases: list[Phase] = []
    for phase, count in layout:
        phases.extend([phase] * count)
    return phases, compressed


def recovery_flags(goal_type: GoalType, phases: list[Phase]) -> list[bool]:
    flags: list[bool] = []
    since = 0
    for phase in phases:
        if phase not in ("base", "build"):
            flags.append(False)
            since = 0
            continue
        since += 1
        cadence = (
            P.IRONMAN_BUILD_RECOVERY_EVERY_N_WEEKS
            if goal_type == "ironman" and phase == "build"
            else P.RECOVERY_EVERY_N_WEEKS
        )
        if since >= cadence:
            flags.append(True)
            since = 0
        else:
            flags.append(False)
    return flags


def week1_tss(goal_type: GoalType, fitness: FitnessSnapshot) -> float:
    if fitness.recent_weekly_tss:
        return float(fitness.recent_weekly_tss)
    if fitness.ctl:
        return 7 * float(fitness.ctl)
    return P.GOAL_FLOOR_TSS[goal_type]


def ctl_after_week(ctl: float, weekly_tss: float) -> float:
    daily = weekly_tss / 7
    return daily + (ctl - daily) * _DECAY


def max_tss_for_ctl_rise(ctl: float) -> float:
    """Largest weekly TSS whose modeled CTL rise over the week is <= MAX_CTL_RISE_PER_WEEK."""
    return 7 * (ctl + P.MAX_CTL_RISE_PER_WEEK / (1 - _DECAY))


def hours_for(tss: float, phase: Phase) -> float:
    return tss / (P.PHASE_IF[phase] ** 2 * 100)


def tss_for(hours: float, phase: Phase) -> float:
    return hours * P.PHASE_IF[phase] ** 2 * 100


def _clamp_hours(
    tss: float, phase: Phase, goal: TrainingGoal, apply_min: bool
) -> tuple[float, float, bool]:
    hours = hours_for(tss, phase)
    lo = goal.weekly_hours_min if apply_min else 0.0
    hi = goal.weekly_hours_max
    if hours > hi:
        return tss_for(hi, phase), hi, True
    if hours < lo:
        return tss_for(lo, phase), lo, True
    return tss, hours, False


def build(goal: TrainingGoal, fitness: FitnessSnapshot, start: date) -> list[WeekTarget]:
    if start.weekday() != 0:
        raise ValueError("start must be a Monday")
    total = count_weeks(goal, start)
    phases, compressed = allocate_phases(goal.goal_type, total)
    recovery = recovery_flags(goal.goal_type, phases)
    w1 = week1_tss(goal.goal_type, fitness)
    ctl = float(fitness.ctl) if fitness.ctl else w1 / 7
    last_load: float | None = None  # last non-recovery base/build week, after clamping
    peak_load: float | None = None
    taper_i = 0
    out: list[WeekTarget] = []
    for i, (phase, is_rec) in enumerate(zip(phases, recovery, strict=True)):
        if goal.goal_type == "maintenance":
            tss = w1
        elif goal.goal_type == "recovery":
            tss = w1 * P.RECOVERY_GOAL_FACTOR
        elif phase in ("base", "build"):
            if last_load is None:
                tss = w1
            elif is_rec:
                tss = last_load * P.RECOVERY_WEEK_FACTOR
            else:
                tss = min(last_load * (1 + P.MAX_WEEKLY_RAMP), max_tss_for_ctl_rise(ctl))
        else:
            if peak_load is None:
                peak_load = last_load if last_load is not None else w1
            if phase == "peak":
                tss = peak_load
            elif phase == "taper":
                tss = peak_load * P.TAPER_FACTORS[min(taper_i, len(P.TAPER_FACTORS) - 1)]
                taper_i += 1
            else:  # race
                tss = peak_load * P.RACE_WEEK_FACTOR
        apply_min = phase in ("base", "build", "peak") and not is_rec
        tss, hours, capped = _clamp_hours(tss, phase, goal, apply_min)
        if phase in ("base", "build") and not is_rec:
            last_load = tss
        flags: list[str] = []
        if compressed:
            flags.append(P.FLAG_COMPRESSED)
        if capped:
            flags.append(P.FLAG_HOURS_CAPPED)
        out.append(
            WeekTarget(
                week_start=start + timedelta(weeks=i),
                phase=phase,
                target_tss=round(tss),
                target_hours=round(hours, 1),
                is_recovery=is_rec,
                flags=flags,
                sport_hint=P.SPORT_HINTS[phase],
            )
        )
        ctl = ctl_after_week(ctl, tss)
    return out


def infer_phases(weekly_tss: list[float]) -> list[Phase]:
    """Phases for a bought plan from its weekly planned TSS: rising = build, plateau = peak,
    falling into the event = taper, last week = race."""
    n = len(weekly_tss)
    if n == 0:
        return []
    if n == 1:
        return ["race"]
    peak = max(weekly_tss[:-1])
    m = weekly_tss.index(peak)
    phases: list[Phase] = []
    for i, tss in enumerate(weekly_tss):
        if i == n - 1:
            phases.append("race")
        elif i > m:
            phases.append("taper")
        elif tss >= P.PEAK_PLATEAU_FRACTION * peak:
            phases.append("peak")
        else:
            phases.append("build")
    return phases
