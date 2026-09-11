"""The ingest graph.

START -> extract -> normalize -> review -> store -> END
                 └─(no rows / no date)─> END          review -> review (edit, refused approve)
                                                      review -> END (reject)
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.nodes.extract import make_extract_node
from tri_wellness.graph.nodes.normalize import make_normalize_node
from tri_wellness.graph.nodes.review import make_review_node
from tri_wellness.graph.nodes.store import make_store_node
from tri_wellness.graph.state import IngestState


def after_extract(state: IngestState) -> str:
    return END if state.get("last_error") else "normalize"


def after_review(state: IngestState) -> str:
    decision = state.get("decision")
    if decision == "approve":
        return "store"
    if decision == "reject":
        return END
    return "review"


def build_ingest_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    g: StateGraph[IngestState] = StateGraph(IngestState)
    g.add_node("extract", make_extract_node(deps))
    g.add_node("normalize", make_normalize_node(deps))
    g.add_node("review", make_review_node(deps))
    g.add_node("store", make_store_node(deps))
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", after_extract, ["normalize", END])
    g.add_edge("normalize", "review")
    g.add_conditional_edges("review", after_review, ["store", "review", END])
    g.add_edge("store", END)
    return g.compile(checkpointer=checkpointer, name="tri-wellness-ingest")
