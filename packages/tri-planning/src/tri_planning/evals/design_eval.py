"""Dataset of target weeks and a code evaluator for the design prompt."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.design import design_week
from tri_planning.planning import validate
from tri_planning.planning.models import (
    FitnessSnapshot,
    PlannedWeek,
    TrainingGoal,
    WeekTarget,
)
from tri_planning.planning.targets import build, next_monday

ANY = {d: "any" for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
RESTRICTED: dict[str, Any] = {
    "mon": [],
    "tue": ["swim", "run"],
    "wed": ["bike"],
    "thu": ["run"],
    "fri": ["swim"],
    "sat": "any",
    "sun": ["bike", "run", "brick"],
}
THRESHOLDS = {
    "ftp_watts": 250,
    "run_threshold_pace_sec_per_km": 270,
    "swim_css_sec_per_100m": 105,
    "lthr_bpm": 165,
}
PHASES = ("base", "build", "recovery", "peak", "taper", "race")


def _presets(start: date) -> list[TrainingGoal]:
    def race(
        goal_type: str, weeks: int, hours: tuple[float, float], days: dict[str, Any]
    ) -> TrainingGoal:
        return TrainingGoal(
            goal_type=goal_type,
            event_name=f"{goal_type} race",
            priority="A",
            event_date=start + timedelta(weeks=weeks - 1, days=6),
            weekly_hours_min=hours[0],
            weekly_hours_max=hours[1],
            available_days=days,
            constraints=["no swimming Mondays" if days is RESTRICTED else "long ride Saturdays"],
        )

    return [
        race("sprint", 8, (4, 7), ANY),
        race("olympic", 14, (6, 10), ANY),
        race("half_ironman", 20, (8, 12), RESTRICTED),
        race("ironman", 24, (10, 16), ANY),
    ]


def build_examples(today: date) -> list[dict[str, Any]]:
    start = next_monday(today)
    fitness = FitnessSnapshot(ctl=45, recent_weekly_tss=320)
    examples: list[dict[str, Any]] = []
    for goal in _presets(start):
        targets = build(goal, fitness, start)
        for phase in PHASES:
            target = next(
                (
                    t
                    for t in targets
                    if (t.phase == phase and not t.is_recovery)
                    or (phase == "recovery" and t.is_recovery)
                ),
                None,
            )
            if target is None:
                continue
            examples.append(
                {
                    "inputs": {
                        "goal": goal.model_dump(mode="json"),
                        "target": target.model_dump(mode="json"),
                        "thresholds": THRESHOLDS,
                    },
                    "metadata": {"goal_type": goal.goal_type, "phase": phase},
                }
            )
    return examples


def validator_pass(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    goal = TrainingGoal.model_validate(inputs["goal"])
    target = WeekTarget.model_validate(inputs["target"])
    week = PlannedWeek.model_validate(outputs["week"])
    violations = validate.week(week, target, goal)
    return {
        "key": "validator_pass",
        "score": 0 if violations else 1,
        "comment": "; ".join(violations),
    }


def design_target(deps: GraphDeps) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def run(inputs: dict[str, Any]) -> dict[str, Any]:
        goal = TrainingGoal.model_validate(inputs["goal"])
        target = WeekTarget.model_validate(inputs["target"])
        week, violations = await design_week(
            deps, goal, target, inputs.get("thresholds"), None, None, {"configurable": {}}
        )
        return {"week": week.model_dump(mode="json"), "violations": violations}

    return run
