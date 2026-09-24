import base64
import hashlib
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import tri_wellness.labs.extract.structured as structured_module
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.labs.extract import count_pdf_pages, file_sha256, sniff
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.extract.structured import extract_structured
from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import EXTRACT_SYSTEM, render_extract_prompt
from tri_wellness.testing import RecordingScriptedModel, load_extracted


def test_sniff_by_extension_and_override(tmp_path):
    assert sniff(Path("a.PDF")) == "pdf"
    assert sniff(Path("a.csv")) == "export"
    assert sniff(Path("a.json")) == "export"
    assert sniff(Path("a.txt"), "export") == "export"
    with pytest.raises(ValueError, match="--kind"):
        sniff(Path("a.txt"))


def test_sha_and_page_count(tiny_pdf):
    assert file_sha256(tiny_pdf) == hashlib.sha256(tiny_pdf.read_bytes()).hexdigest()
    assert count_pdf_pages(tiny_pdf.read_bytes()) == 2
    assert count_pdf_pages(b"not a pdf") == 0


def test_render_extract_prompt_mentions_hint_and_rules():
    p = render_extract_prompt("pdf", None, None)
    assert "verbatim" in p and "draw date" in p.lower()
    assert "2026-08-20" in render_extract_prompt("pdf", date(2026, 8, 20), None)
    body = render_extract_prompt("export", None, "name,value\nFerritin,42")
    assert "Ferritin,42" in body
    assert "ExtractedPanel" in EXTRACT_SYSTEM


async def test_extract_pdf_sends_document_block_and_parses(tiny_pdf):
    fixture = load_extracted("pdf_panel")
    model = RecordingScriptedModel(script=[tool_call("ExtractedPanel", fixture)])
    panel, pages = await extract_pdf(model, tiny_pdf, None, None)
    assert isinstance(panel, ExtractedPanel)
    assert panel.model_dump(mode="json") == fixture
    assert pages == 2 and model.calls == 1
    messages = model.received[0]
    assert isinstance(messages[0], SystemMessage) and messages[0].content == EXTRACT_SYSTEM
    human = messages[1]
    assert isinstance(human, HumanMessage) and isinstance(human.content, list)
    text_block, file_block = human.content
    assert text_block["type"] == "text" and "verbatim" in text_block["text"]
    # langchain-core normalizes the v0 {source_type, data} block we send into its v1
    # {base64} shape before the model sees it (langchain_core.language_models._utils
    # ._normalize_messages, unconditional as of langchain-core 1.x).
    assert file_block == {
        "type": "file",
        "mime_type": "application/pdf",
        "base64": base64.b64encode(tiny_pdf.read_bytes()).decode(),
    }


async def test_extraction_goes_through_the_structured_helper(monkeypatch):
    class _Stop(Exception):
        pass

    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        raise _Stop

    monkeypatch.setattr(structured_module, "structured", spy)
    model = ScriptedChatModel(script=[])
    with pytest.raises(_Stop):
        await extract_structured(model, "prompt", None, [], None)
    assert seen == [(model, ExtractedPanel)]
