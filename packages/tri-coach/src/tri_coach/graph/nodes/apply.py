"""Apply node: the only caller of the packages' apply_changes, planning first then nutrition,
with thread_id "coach". A bought plan that was just applied is adopted by one more embedded
planning run. Remaining changes stay in `pending` under a stable id (`held-planning`,
`held-nutrition`) so a later turn can re-propose them by that id."""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_coach.graph.deps import CoachDeps
from tri_coach.graph.state import CoachState
from tri_coach.models import ApplyReport, ChangeSet, Proposal
from tri_nutrition.graph.nodes.apply import ApplyResult as NutritionResult
from tri_nutrition.graph.nodes.apply import apply_changes as apply_nutrition
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning import repo
from tri_planning.graph.nodes.apply import ApplyResult as PlanningResult
from tri_planning.graph.nodes.apply import apply_changes as apply_planning
from tri_planning.planning.models import CalendarChange


def report_from_planning(r: PlanningResult) -> ApplyReport:
    return ApplyReport(
        domain="planning",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=r.sessions_changed,
    )


def report_from_nutrition(r: NutritionResult) -> ApplyReport:
    return ApplyReport(
        domain="nutrition",
        applied=len(r.applied),
        skipped=r.skipped,
        remaining=len(r.remaining),
        error=r.error,
        sessions_changed=False,
    )


HELD_IDS: dict[str, str] = {"planning": "held-planning", "nutrition": "held-nutrition"}


def make_apply_node(deps: CoachDeps, planning_graph: Any) -> Any:
    async def apply(
        state: CoachState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        pending = state.get("pending")
        assert pending is not None, "apply needs a pending change set"
        thread_id = str(config["configurable"]["thread_id"])
        reports: list[ApplyReport] = []
        held: list[Proposal] = []

        planning = [p for p in pending.proposals if p.domain == "planning"]
        if planning:
            # The domain decides the change type; the Proposal validator already typed them.
            changes = cast(list[CalendarChange], [c for p in planning for c in p.changes])
            with deps.planning_deps.connect() as conn:
                _, goal_id, plan_id = repo.derive_phase(conn)
            r = await apply_planning(
                deps.planning_deps, changes, thread_id, plan_id=plan_id, goal_id=goal_id
            )
            report = report_from_planning(r)
            if r.tp_plan_applied and r.error is None:
                # The adopt re-invoke reads TrainingPeaks again; TrainingPeaks was already
                # written, so a failure here is reported, not raised.
                try:
                    await planning_graph.ainvoke({"tp_plan_applied": True}, config)
                except Exception as exc:  # noqa: BLE001 - any failure is reported to the athlete
                    detail = f"the plan was applied but adopting it failed: {exc}"
                    joined = "; ".join(x for x in (report.error, detail) if x)
                    report = report.model_copy(update={"error": joined})
            reports.append(report)
            if r.remaining:
                held.append(
                    Proposal(
                        id=HELD_IDS["planning"],
                        domain="planning",
                        summary=f"{len(r.remaining)} planning changes held from the last apply",
                        changes=r.remaining,
                    )
                )

        nutrition = [p for p in pending.proposals if p.domain == "nutrition"]
        if nutrition:
            nchanges = cast(list[NutritionChange], [c for p in nutrition for c in p.changes])
            overrides: dict[str, Any] = {}
            for p in nutrition:
                overrides.update(p.overrides or {})
            rn = await apply_nutrition(
                deps.nutrition_deps, store, nchanges, thread_id, overrides=overrides or None
            )
            reports.append(report_from_nutrition(rn))
            if rn.remaining:
                held.append(
                    Proposal(
                        id=HELD_IDS["nutrition"],
                        domain="nutrition",
                        summary=f"{len(rn.remaining)} nutrition changes held from the last apply",
                        changes=rn.remaining,
                        overrides=overrides or None,
                    )
                )

        errors = [rep.error for rep in reports if rep.error]
        return {
            "reports": reports,
            "pending": ChangeSet(narration=pending.narration, proposals=held) if held else None,
            "review_decision": None,
            "last_error": "; ".join(errors) or None,
            "messages": [AIMessage("\n".join(rep.line() for rep in reports))],
        }

    return apply
