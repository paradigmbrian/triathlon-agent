"""The planning graph. Nodes are closures over GraphDeps; routing is pure functions over state.

START -> route -> route_start: pending changes -> review; intake | targets | adjust by the phase
            derived from the tables
intake   -> targets (goal saved) | END
targets  -> review (bought plan) | design (generated) | END (bought plan adopted)
design   -> review
review   -> apply (approve/edit) | design or adjust (reject) | END (nothing to review, or
            rejected apply_plan)
apply    -> targets (after apply_plan) | END
adjust   -> review (changes proposed) | END
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.nodes.adjust import make_adjust_node
from tri_planning.graph.nodes.apply import make_apply_node
from tri_planning.graph.nodes.design import make_design_node
from tri_planning.graph.nodes.intake import make_intake_node
from tri_planning.graph.nodes.review import review_node
from tri_planning.graph.nodes.route import make_route_node
from tri_planning.graph.nodes.targets import make_targets_node
from tri_planning.graph.state import PlanningState


def route_start(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    phase = state.get("phase") or "intake"
    return {"intake": "intake", "planning": "targets", "active": "adjust"}[phase]


def after_intake(state: PlanningState) -> str:
    return "targets" if state.get("phase") == "planning" and state.get("goal_id") else END


def after_targets(state: PlanningState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("phase") == "active":
        return END
    return "design"


def after_review(state: PlanningState) -> str:
    decision = state.get("review_decision")
    if decision is None:
        return END
    if decision.action in ("approve", "edit"):
        return "apply"
    origin = state.get("changes_from")
    return origin if origin in ("design", "adjust") else END


def after_apply(state: PlanningState) -> str:
    return "targets" if state.get("tp_plan_applied") else END


def after_adjust(state: PlanningState) -> str:
    return "review" if state.get("pending_changes") else END


def build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    g: StateGraph[PlanningState] = StateGraph(PlanningState)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("design", make_design_node(deps))
    g.add_node("review", review_node)
    g.add_node("apply", make_apply_node(deps))
    g.add_node("adjust", make_adjust_node(deps))
    g.add_node("route", make_route_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_start, ["review", "intake", "targets", "adjust"])
    g.add_conditional_edges("intake", after_intake, ["targets", END])
    g.add_conditional_edges("targets", after_targets, ["review", "design", END])
    g.add_edge("design", "review")
    g.add_conditional_edges("review", after_review, ["apply", "design", "adjust", END])
    g.add_conditional_edges("apply", after_apply, ["targets", END])
    g.add_conditional_edges("adjust", after_adjust, ["review", END])
    return g.compile(checkpointer=checkpointer, name="tri-planning")
