"""The nutrition graph. Nodes are closures over GraphDeps; routing is pure functions over state.

START   -> route    (reads the Store, sets has_profile)
route   -> review   (pending_changes) | intake (no profile) | checkin
intake  -> targets  (save_nutrition_profile was called) | END
targets -> fuel     | END (bounds violated, or no profile)
fuel    -> review
review  -> apply    (approve or edit) | intake or checkin (reject) | END
apply   -> END
checkin -> targets  (save_nutrition_profile was called) | END
"""

from __future__ import annotations

from typing import Any

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


def route_start(state: NutritionState) -> str:
    if state.get("pending_changes"):
        return "review"
    return "checkin" if state.get("has_profile") else "intake"


def after_intake(state: NutritionState) -> str:
    return "targets" if state.get("profile_saved") else END


def after_checkin(state: NutritionState) -> str:
    return "targets" if state.get("profile_saved") else END


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


def build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any], store: BaseStore) -> Any:
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("route", route_node)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("checkin", make_checkin_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("fuel", make_fuel_node(deps))
    g.add_node("review", review_node)
    g.add_node("apply", make_apply_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_start, ["review", "intake", "checkin"])
    g.add_conditional_edges("intake", after_intake, ["targets", END])
    g.add_conditional_edges("checkin", after_checkin, ["targets", END])
    g.add_conditional_edges("targets", after_targets, ["fuel", END])
    g.add_edge("fuel", "review")
    g.add_conditional_edges("review", after_review, ["apply", "intake", "checkin", END])
    g.add_edge("apply", END)
    return g.compile(checkpointer=checkpointer, store=store, name="tri-nutrition")
