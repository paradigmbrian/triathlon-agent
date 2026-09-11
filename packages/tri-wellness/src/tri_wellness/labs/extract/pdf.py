"""PDF extraction: the file goes to the model as a document block; no PDF library."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from tri_wellness.labs.extract import count_pdf_pages
from tri_wellness.labs.extract.structured import extract_structured
from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import render_extract_prompt


async def extract_pdf(
    model: BaseChatModel, path: Path, drawn_on_hint: date | None, config: RunnableConfig | None
) -> tuple[ExtractedPanel, int]:
    data = path.read_bytes()
    pages = count_pdf_pages(data)
    attachment = {
        "type": "file",
        "source_type": "base64",
        "mime_type": "application/pdf",
        "data": base64.b64encode(data).decode("ascii"),
    }
    panel = await extract_structured(
        model,
        render_extract_prompt("pdf", drawn_on_hint, None),
        attachment,
        ["source_kind:pdf", f"page_count:{pages}"],
        config,
    )
    return panel, pages
