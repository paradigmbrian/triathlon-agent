"""Route node: derive the phase and the active ids from the tables at the start of every run,
so a fresh thread and a stateless consultation both start where the database says. The edge
functions in graph.py stay pure over state."""

from __future__ import annotations

from typing import Any

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState


def make_route_node(deps: GraphDeps) -> Any:
    def route(state: PlanningState) -> dict[str, Any]:
        with deps.connect() as conn:
            phase, goal_id, plan_id = repo.derive_phase(conn)
        return {"phase": phase, "goal_id": goal_id, "plan_id": plan_id}

    return route
