"""Extract node: file -> ExtractedPanel. Ends the run (last_error) when there is nothing to
review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.extract import file_sha256
from tri_wellness.labs.extract.exports import (
    ExportError,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.models import ExtractedPanel


def make_extract_node(deps: GraphDeps) -> Any:
    async def extract(state: IngestState, config: RunnableConfig) -> dict[str, Any]:
        path = Path(state["source_path"])
        hint = state.get("drawn_on_hint")
        pages: int | None = None
        panel = ExtractedPanel()
        error: str | None = None
        if state["source_kind"] == "pdf":
            panel, pages = await extract_pdf(deps.model, path, hint, config)
        else:
            try:
                parsed = parse_export(path)
            except ExportError as exc:
                error = f"{path.name}: {exc}"
            else:
                panel = parsed or await extract_export_with_model(deps.model, path, hint, config)
        drawn_on = panel.drawn_on or hint
        if error is None and not panel.results:
            error = f"extraction returned no rows for {path.name}"
        elif error is None and drawn_on is None:
            error = f"extraction found no draw date in {path.name}; rerun with --drawn-on"
        return {
            "source_sha": file_sha256(path),
            "raw_results": panel.results,
            "drawn_on": drawn_on,
            "lab_name": panel.lab_name,
            "page_count": pages,
            "results": [],
            "unmapped": [],
            "context": None,
            "decision": None,
            "panel_id": None,
            "last_error": error,
        }

    return extract
