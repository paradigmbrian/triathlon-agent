"""Normalize node: raw rows -> canonical results and the rows that need review. Pure."""

from __future__ import annotations

from typing import Any

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.normalize import normalize


def make_normalize_node(deps: GraphDeps) -> Any:
    def normalize_node(state: IngestState) -> dict[str, Any]:
        out = normalize(list(state.get("raw_results") or []), deps.registry)
        return {"results": out.results, "unmapped": out.unmapped}

    return normalize_node
