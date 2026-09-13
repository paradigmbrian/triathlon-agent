"""The coach graph. Nodes are closures over CoachDeps; the only edges out of `coach` are its
tools' Commands (handoffs, propose) and a static edge to END for a conversational turn.

START  -> start   (clears the per-turn keys)
start  -> coach
coach  -> END                           (turn ended in conversation)
coach  => planning | nutrition          (Command from consult_*); each -> coach
coach  => review                        (Command from propose_changes)
review -> apply                         (approve or edit)
review -> coach                         (reject, or unknown proposal ids)
apply  -> nutrition                     (regenerate_after_apply: planning moved sessions and
                                         nutrition targets exist in the horizon)
apply  -> END                           (otherwise)
nutrition -> coach                      (a consultation, or the "[follow-on]" regeneration)
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from tri_coach.graph.deps import CoachDeps
from tri_coach.graph.nodes.apply import make_apply_node
from tri_coach.graph.nodes.coach import make_coach_node
from tri_coach.graph.nodes.nutrition import make_nutrition_node
from tri_coach.graph.nodes.planning import make_planning_node
from tri_coach.graph.nodes.review import review_node
from tri_coach.graph.state import CoachState
from tri_nutrition.graph.checkpointer import make_serde as nutrition_serde
from tri_nutrition.graph.graph import build_graph as build_nutrition_graph
from tri_planning.graph.checkpointer import make_serde as planning_serde
from tri_planning.graph.graph import build_graph as build_planning_graph


def start_node(state: CoachState) -> dict[str, Any]:
    """A new athlete turn: forget last turn's brief, proposals and decision. `pending` survives
    (a partial apply's remainder) and is shown in the context block; it is re-emitted unchanged so
    the channel exists in the snapshot from the first turn on."""
    return {
        "pending": state.get("pending"),
        "brief": None,
        "proposals": [],
        "proposal_request": None,
        "carried": [],
        "regenerate_after_apply": False,
        "review_decision": None,
        "reports": [],
        "last_error": None,
    }


def after_review(state: CoachState) -> str:
    decision = state.get("review_decision")
    if decision is not None and decision.action in ("approve", "edit"):
        return "apply"
    return "coach"


def after_apply(state: CoachState) -> str:
    return "nutrition" if state.get("regenerate_after_apply") else END


def build_graph(deps: CoachDeps, checkpointer: BaseCheckpointSaver[Any], store: BaseStore) -> Any:
    # Private in-memory savers: every consultation runs in a fresh checkpoint namespace and
    # nothing a sub-graph did is persisted or seen by the next consultation. Each carries its own
    # package's serde, so its state models round trip without the default's warning.
    planning_graph = build_planning_graph(
        deps.planning_deps, InMemorySaver(serde=planning_serde()), embedded=True
    )
    nutrition_graph = build_nutrition_graph(
        deps.nutrition_deps, InMemorySaver(serde=nutrition_serde()), store, embedded=True
    )

    g: StateGraph[CoachState] = StateGraph(CoachState)
    g.add_node("start", start_node)
    g.add_node(
        "coach", make_coach_node(deps), destinations=("planning", "nutrition", "review", END)
    )
    g.add_node("planning", make_planning_node(planning_graph))
    g.add_node("nutrition", make_nutrition_node(nutrition_graph))
    g.add_node("review", review_node)
    g.add_node("apply", make_apply_node(deps, planning_graph))

    g.add_edge(START, "start")
    g.add_edge("start", "coach")
    g.add_edge("coach", END)
    g.add_edge("planning", "coach")
    g.add_edge("nutrition", "coach")
    g.add_conditional_edges("review", after_review, ["apply", "coach"])
    g.add_conditional_edges("apply", after_apply, ["nutrition", END])
    return g.compile(checkpointer=checkpointer, store=store, name="tri-coach")
