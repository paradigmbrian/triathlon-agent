"""Fuel node: one structured-output call per qualifying session and one for the race, each
validated with one retry, stored in fuel_plans, proposed as TrainingPeaks note changes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, TypeVar

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.store.base import BaseStore
from pydantic import BaseModel

from tri_nutrition import plan_loader, repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.bounds import validate_fuel, validate_race
from tri_nutrition.nutrition.models import (
    HARD_INTENSITIES,
    DayTarget,
    FuelLogEntry,
    NutritionChange,
    NutritionProfile,
    PlanContext,
    Product,
    RaceFuelPlan,
    Session,
    SessionFuel,
    StoredFuelPlan,
)
from tri_nutrition.nutrition.tp_calls import race_note_change, race_note_title, session_note_change
from tri_nutrition.prompts.fuel import FUEL_SYSTEM, render_session_prompt
from tri_nutrition.prompts.race import RACE_SYSTEM, render_race_prompt
from tri_nutrition.repl import render_fuel, render_race

LONG_SESSION_MIN = 75
RACE_WINDOW_DAYS = 21


def qualifies(session: Session) -> bool:
    return session.duration_min > LONG_SESSION_MIN or session.intensity in HARD_INTENSITIES


def race_due(ctx: PlanContext, today: date) -> bool:
    return ctx.event_date is not None and 0 <= (ctx.event_date - today).days <= RACE_WINDOW_DAYS


def _needs_write(stored: StoredFuelPlan | None, note_text: str) -> bool:
    return stored is None or not stored.written or stored.payload.get("note_text") != note_text


T = TypeVar("T", bound=BaseModel)


class FuelPlanner:
    """The two structured-output calls with their validate-and-retry loop. Shared by the fuel
    node and the LangSmith evaluation target, which has no database."""

    def __init__(self, model: BaseChatModel) -> None:
        self._session: Runnable[LanguageModelInput, Any] = model.with_structured_output(SessionFuel)
        self._race: Runnable[LanguageModelInput, Any] = model.with_structured_output(RaceFuelPlan)

    @staticmethod
    async def _ask(
        runnable: Runnable[LanguageModelInput, Any],
        system: str,
        prompt: str,
        cls: type[T],
        config: RunnableConfig | None,
    ) -> T:
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(prompt)], config=config)
        assert isinstance(out, cls)
        return out

    async def session(
        self,
        profile: NutritionProfile,
        library: list[Product],
        fuel_log: list[FuelLogEntry],
        session: Session,
        target: DayTarget | None,
        other_caffeine_mg: int = 0,
        config: RunnableConfig | None = None,
    ) -> tuple[SessionFuel, list[str]]:
        ids = {"tp_workout_id": session.tp_workout_id or "", "day": session.day}
        prompt = render_session_prompt(profile, library, fuel_log, session, target, None, None)
        first = await self._ask(self._session, FUEL_SYSTEM, prompt, SessionFuel, config)
        plan = first.model_copy(update=ids)
        violations = validate_fuel(plan, profile, library, fuel_log, other_caffeine_mg)
        if violations:
            retry = render_session_prompt(
                profile, library, fuel_log, session, target, violations, plan
            )
            second = await self._ask(self._session, FUEL_SYSTEM, retry, SessionFuel, config)
            plan = second.model_copy(update=ids)
            violations = validate_fuel(plan, profile, library, fuel_log, other_caffeine_mg)
        return plan, violations

    async def race(
        self,
        profile: NutritionProfile,
        library: list[Product],
        fuel_log: list[FuelLogEntry],
        ctx: PlanContext,
        target: DayTarget | None,
        config: RunnableConfig | None = None,
    ) -> tuple[RaceFuelPlan, list[str]]:
        prompt = render_race_prompt(profile, library, fuel_log, ctx, target, None, None)
        plan = await self._ask(self._race, RACE_SYSTEM, prompt, RaceFuelPlan, config)
        violations = validate_race(plan, profile, library, fuel_log)
        if violations:
            retry = render_race_prompt(profile, library, fuel_log, ctx, target, violations, plan)
            plan = await self._ask(self._race, RACE_SYSTEM, retry, RaceFuelPlan, config)
            violations = validate_race(plan, profile, library, fuel_log)
        return plan, violations


def make_fuel_node(deps: GraphDeps) -> Any:
    planner = FuelPlanner(deps.model)

    async def fuel(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        profile = await S.get_profile(store)
        if profile is None or state.get("last_error"):
            return {}
        library = list(profile.tested_products)
        known = {p.name for p in library}
        library += [p for p in await S.get_product_library(store) if p.name not in known]
        fuel_log = await S.get_fuel_log(store)
        today = deps.today()
        end = today + timedelta(days=deps.horizon_days - 1)
        with deps.connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today, deps.horizon_days)
            targets = {s.target.day: s.target for s in repo.list_targets(conn, today, end)}
            stored = repo.list_fuel_plans(conn, today, max(end, ctx.event_date or end))
        by_workout = {p.tp_workout_id: p for p in stored if p.kind == "session" and p.tp_workout_id}
        stored_race = next((p for p in stored if p.kind == "race"), None)

        changes: list[NutritionChange] = list(state.get("pending_changes") or [])
        fuels: list[SessionFuel] = []
        violations_by_id: dict[str, list[str]] = {}
        unmatched: list[str] = []
        caffeine_today: dict[date, int] = {}

        for s in [x for x in sessions if qualifies(x)]:
            target = targets.get(s.day)
            cfg = merge_configs(config, {"tags": [f"day:{s.day}", "kind:session"]})
            other = caffeine_today.get(s.day, 0)
            plan, violations = await planner.session(
                profile, library, fuel_log, s, target, other, cfg
            )
            caffeine_today[s.day] = other + (plan.caffeine_mg or 0)
            with deps.connect() as conn:
                repo.upsert_fuel_plan(
                    conn,
                    "session",
                    s.day,
                    s.tp_workout_id,
                    plan.model_dump(mode="json"),
                    violations,
                )
                conn.commit()
            if s.tp_workout_id is None:
                unmatched.append(f"{s.day} {s.sport} '{s.title}'")
                continue
            fuels.append(plan)
            if violations:
                violations_by_id[s.tp_workout_id] = violations
            if _needs_write(by_workout.get(s.tp_workout_id), plan.note_text):
                changes.append(session_note_change(plan))

        race_text = ""
        if race_due(ctx, today) and ctx.event_date is not None:
            cfg = merge_configs(config, {"tags": [f"day:{ctx.event_date}", "kind:race"]})
            target = targets.get(ctx.event_date)
            plan_r, rv = await planner.race(profile, library, fuel_log, ctx, target, cfg)
            with deps.connect() as conn:
                repo.upsert_fuel_plan(
                    conn, "race", ctx.event_date, None, plan_r.model_dump(mode="json"), rv
                )
                conn.commit()
            race_text = render_race(plan_r, rv)
            if _needs_write(stored_race, plan_r.note_text):
                title = race_note_title(ctx.event_name, ctx.goal_type, ctx.event_date)
                note_id = stored_race.tp_note_id if stored_race is not None else None
                changes.append(race_note_change(plan_r, title, note_id))

        block = [render_fuel(fuels, violations_by_id)]
        if unmatched:
            block.append(
                "Planned but not on the TrainingPeaks calendar yet (no note will be written): "
                + "; ".join(unmatched)
            )
        if race_text:
            block.append(race_text)
        summary = (state.get("pending_summary") or "") + "\n\n" + "\n".join(block)
        return {"pending_changes": changes, "pending_summary": summary.strip()}

    return fuel
