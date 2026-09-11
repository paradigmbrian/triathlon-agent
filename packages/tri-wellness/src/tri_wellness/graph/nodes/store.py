"""Store node: one transaction, one panel, its result rows and the raw extract."""

from __future__ import annotations

from typing import Any

from tri_wellness import repo
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState


def make_store_node(deps: GraphDeps) -> Any:
    def store(state: IngestState) -> dict[str, Any]:
        drawn_on, context = state.get("drawn_on"), state.get("context")
        assert drawn_on is not None and context is not None
        with deps.connect() as conn:
            panel_id = repo.insert_panel(
                conn,
                drawn_on=drawn_on,
                lab_name=state.get("lab_name"),
                source_file=state["source_path"],
                source_kind=state["source_kind"],
                context=context,
                raw_extract=list(state.get("raw_results") or []),
                results=list(state.get("results") or []),
            )
            conn.commit()
        return {"panel_id": panel_id, "last_error": None}

    return store
