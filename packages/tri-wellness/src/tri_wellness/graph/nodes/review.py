"""Review node: pause until the athlete decides. Edit and a refused approve return with
`decision` None, which routes back here for another look at the (edited) table.

`interrupt(value)` stops the run with the value exposed as `__interrupt__`; on
`Command(resume=x)` the node runs again from the top and `interrupt()` returns x. The duplicate
lookup before it is a read, so replaying it is harmless.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from tri_wellness import repo
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.models import BLOCKING_REASONS, IngestDecision, Unmapped


def blocking_rows(unmapped: list[Unmapped]) -> list[Unmapped]:
    return [u for u in unmapped if u.reason in BLOCKING_REASONS]


def make_review_node(deps: GraphDeps) -> Any:
    def review(state: IngestState) -> dict[str, Any]:
        drawn_on = state.get("drawn_on")
        context = state.get("context")
        unmapped = list(state.get("unmapped") or [])
        sha = state.get("source_sha")
        duplicates: list[int] = []
        already_ingested: int | None = None
        if drawn_on is not None or sha is not None:
            with deps.connect() as conn:
                if drawn_on is not None:
                    duplicates = repo.find_duplicate_panels(conn, drawn_on, state.get("lab_name"))
                if sha is not None:
                    already_ingested = repo.panel_id_for_sha(conn, sha)
        raw = interrupt(
            {
                "source_path": state["source_path"],
                "drawn_on": drawn_on.isoformat() if drawn_on else None,
                "lab_name": state.get("lab_name"),
                "results": [r.model_dump(mode="json") for r in state.get("results") or []],
                "unmapped": [u.model_dump(mode="json") for u in unmapped],
                "context": context.model_dump(mode="json") if context else None,
                "duplicates": duplicates,
                "already_ingested": already_ingested,
                "last_error": state.get("last_error"),
            }
        )
        decision = IngestDecision.model_validate(raw)
        if decision.action == "reject":
            return {"decision": "reject", "last_error": None}
        if decision.action == "edit":
            update: dict[str, Any] = {"decision": None, "last_error": None}
            for field in ("results", "unmapped", "drawn_on", "lab_name", "context"):
                value = getattr(decision, field)
                if value is not None:
                    update[field] = value
            return update
        if already_ingested is not None:
            return {
                "decision": None,
                "last_error": f"already ingested as panel {already_ingested}",
            }
        blocking = blocking_rows(unmapped)
        if blocking:
            names = ", ".join(u.raw.name for u in blocking)
            return {
                "decision": None,
                "last_error": f"{len(blocking)} row(s) need a unit or value fix before approve "
                f"(edit or remove): {names}",
            }
        if decision.context is None:
            return {"decision": None, "last_error": "approve needs the panel context"}
        if drawn_on is None:
            return {"decision": None, "last_error": "approve needs a draw date (edit drawn_on)"}
        return {"decision": "approve", "context": decision.context, "last_error": None}

    return review
