"""The nutrition graph. Nodes are closures over GraphDeps; routing is pure functions over state.

START   -> route    (reads the Store, sets has_profile)
route   -> review   (pending_changes) | intake (no profile) | checkin
route   -> targets  (targets_requested with no new athlete message: the coach's regenerate entry)
intake  -> targets  (save_nutrition_profile was called) | END
targets -> fuel     | END (bounds violated, or no profile)
fuel    -> review
review  -> apply    (approve or edit) | intake or checkin (reject) | END
apply   -> END
checkin -> targets  (save_nutrition_profile or propose_target_changes was called) | END

Embedded mode (build_graph(..., embedded=True)): no review or apply; fuel and a targets
violation end the run.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.apply import make_apply_node
from tri_nutrition.graph.nodes.checkin import make_checkin_node
from tri_nutrition.graph.nodes.fuel import make_fuel_node
from tri_nutrition.graph.nodes.intake import make_intake_node
from tri_nutrition.graph.nodes.review import review_node
from tri_nutrition.graph.nodes.route import route_node
from tri_nutrition.graph.nodes.targets import make_targets_node
from tri_nutrition.graph.state import NutritionState


def _new_athlete_message(state: NutritionState) -> bool:
    msgs = state.get("messages") or []
    return bool(msgs) and isinstance(msgs[-1], HumanMessage)


def route_start(state: NutritionState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("targets_requested") and not _new_athlete_message(state):
        # The regenerate entry: the coach invokes the graph with the flag and no message after a
        # plan change was applied. In a standalone run the flag is always clear here.
        return "targets"
    return "checkin" if state.get("has_profile") else "intake"


def after_intake(state: NutritionState) -> str:
    return "targets" if state.get("profile_saved") else END


def after_checkin(state: NutritionState) -> str:
    if state.get("profile_saved") or state.get("targets_requested"):
        return "targets"
    return END


def after_targets(state: NutritionState) -> str:
    return "fuel" if state.get("pending_changes") or state.get("last_error") is None else END


def after_review(state: NutritionState) -> str:
    decision = state.get("review_decision")
    if decision is None:
        return END
    if decision.action in ("approve", "edit"):
        return "apply"
    origin = state.get("regenerate_from")
    return origin if origin in ("intake", "checkin") else END


def build_graph(
    deps: GraphDeps,
    checkpointer: BaseCheckpointSaver[Any],
    store: BaseStore,
    *,
    embedded: bool = False,
) -> Any:
    """Compile the nutrition graph. With `embedded=True` there is no `review` or `apply`: `fuel`
    ends the run and a targets violation ends it, leaving `pending_changes`, `pending_summary`,
    `regenerate_from` and `last_error` in the output for the caller (the coach) to review."""
    review = END if embedded else "review"
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("route", route_node)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("checkin", make_checkin_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("fuel", make_fuel_node(deps))
    if not embedded:
        g.add_node("review", review_node)
        g.add_node("apply", make_apply_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        route_start,
        {"review": review, "targets": "targets", "intake": "intake", "checkin": "checkin"},
    )
    g.add_conditional_edges("intake", after_intake, {"targets": "targets", END: END})
    g.add_conditional_edges("checkin", after_checkin, {"targets": "targets", END: END})
    g.add_conditional_edges("targets", after_targets, {"fuel": "fuel", END: END})
    g.add_edge("fuel", review)
    if not embedded:
        g.add_conditional_edges("review", after_review, ["apply", "intake", "checkin", END])
        g.add_edge("apply", END)
    return g.compile(checkpointer=checkpointer, store=store, name="tri-nutrition")
