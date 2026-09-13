"""Apply node: the only caller of the packages' apply_changes, planning first then nutrition,
with thread_id "coach". A bought plan that was just applied is adopted by one more embedded
planning run. Remaining changes stay in `pending` under a stable id (`held-planning`,
`held-nutrition`) so a later turn can re-propose them by that id, together with the held
proposals the approved set did not name (`carried`). An exception inside one domain's apply is
reported and that domain's changes are held unverified; the other domain still runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.store.base import BaseStore

from tri_coach.graph.deps import CoachDeps
from tri_coach.graph.state import CoachState
from tri_coach.models import ApplyReport, Brief, ChangeSet, Domain, Proposal
from tri_nutrition import repo as nrepo
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


def raised_report(domain: Domain, n: int, exc: Exception) -> ApplyReport:
    return ApplyReport(
        domain=domain,
        applied=0,
        skipped=[],
        remaining=n,
        error=(
            f"apply raised {type(exc).__name__}: {exc}; some changes may already be written, "
            "check before re-proposing"
        ),
        sessions_changed=False,
    )


HELD_IDS: dict[str, str] = {"planning": "held-planning", "nutrition": "held-nutrition"}

REGENERATE_INSTRUCTION = "Regenerate targets and fueling from the stored plan after the apply."


def _regeneration_due(deps: CoachDeps, reports: list[ApplyReport]) -> bool:
    """Spec 6.3: planning moved sessions without error and nutrition targets exist in the
    horizon. A failed or partial planning apply skips it (spec 9)."""
    plan = next((r for r in reports if r.domain == "planning"), None)
    if plan is None or not plan.sessions_changed or plan.error is not None:
        return False
    today = deps.today()
    end = today + timedelta(days=deps.nutrition_deps.horizon_days - 1)
    with deps.connect() as conn:
        return bool(nrepo.list_targets(conn, today, end))


def merge_held(carried: list[Proposal], new: list[Proposal]) -> list[Proposal]:
    """Carried held proposals first, then this apply's remainder; a shared stable id merges."""
    by_id = {p.id: p for p in carried}
    for p in new:
        prev = by_id.get(p.id)
        if prev is None:
            by_id[p.id] = p
            continue
        changes = [*prev.changes, *p.changes]
        summary = f"{len(changes)} {p.domain} changes held from earlier applies"
        if "unverified" in prev.summary or "unverified" in p.summary:
            summary += ", some unverified: apply raised"
        by_id[p.id] = prev.model_copy(
            update={
                "changes": changes,
                "summary": summary,
                "overrides": {**(prev.overrides or {}), **(p.overrides or {})} or None,
            }
        )
    return list(by_id.values())


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
            try:
                with deps.planning_deps.connect() as conn:
                    _, goal_id, plan_id = repo.derive_phase(conn)
                r = await apply_planning(
                    deps.planning_deps, changes, thread_id, plan_id=plan_id, goal_id=goal_id
                )
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001 - reported and held; nutrition still runs
                reports.append(raised_report("planning", len(changes), exc))
                held.append(
                    Proposal(
                        id=HELD_IDS["planning"],
                        domain="planning",
                        summary=f"{len(changes)} planning changes held unverified: apply raised",
                        changes=changes,
                    )
                )
            else:
                report = report_from_planning(r)
                if r.tp_plan_applied and r.error is None:
                    # The adopt re-invoke reads TrainingPeaks again; TrainingPeaks was already
                    # written, so a failure here is reported, not raised.
                    try:
                        await planning_graph.ainvoke({"tp_plan_applied": True}, config)
                    except Exception as exc:  # noqa: BLE001 - any failure is reported
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
            try:
                rn = await apply_nutrition(
                    deps.nutrition_deps, store, nchanges, thread_id, overrides=overrides or None
                )
            except GraphBubbleUp:
                raise
            except Exception as exc:  # noqa: BLE001 - reported and held
                reports.append(raised_report("nutrition", len(nchanges), exc))
                held.append(
                    Proposal(
                        id=HELD_IDS["nutrition"],
                        domain="nutrition",
                        summary=f"{len(nchanges)} nutrition changes held unverified: apply raised",
                        changes=nchanges,
                        overrides=overrides or None,
                    )
                )
            else:
                reports.append(report_from_nutrition(rn))
                if rn.remaining:
                    held.append(
                        Proposal(
                            id=HELD_IDS["nutrition"],
                            domain="nutrition",
                            summary=(
                                f"{len(rn.remaining)} nutrition changes held from the last apply"
                            ),
                            changes=rn.remaining,
                            overrides=overrides or None,
                        )
                    )

        kept = merge_held(list(state.get("carried") or []), held)
        errors = [rep.error for rep in reports if rep.error]
        lines = [rep.line() for rep in reports]
        try:
            regenerate = _regeneration_due(deps, reports)
        except GraphBubbleUp:
            raise
        except Exception as exc:  # noqa: BLE001 - the writes above are done; report, never raise
            regenerate = False
            skipped = f"regeneration skipped: {type(exc).__name__}: {exc}"
            errors.append(skipped)
            lines.append(skipped)
        return {
            "reports": reports,
            "pending": ChangeSet(narration=pending.narration, proposals=kept) if kept else None,
            "carried": [],
            "proposals": [],  # consumed: the follow-on proposal is p1, an applied id is gone
            "review_decision": None,
            "regenerate_after_apply": regenerate,
            "brief": (
                Brief(domain="nutrition", instruction=REGENERATE_INSTRUCTION, regenerate=True)
                if regenerate
                else None
            ),
            "last_error": "; ".join(errors) or None,
            "messages": [AIMessage("\n".join(lines))],
        }

    return apply
