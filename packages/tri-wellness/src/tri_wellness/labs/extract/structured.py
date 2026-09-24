"""The one structured-output call every extraction path uses."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_core.llm import structured
from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import EXTRACT_SYSTEM


async def extract_structured(
    model: BaseChatModel,
    prompt: str,
    attachment: dict[str, Any] | None,
    tags: list[str],
    config: RunnableConfig | None,
) -> ExtractedPanel:
    """`attachment` is a standard content block (a base64 `file` block for PDFs) sent after the
    prompt text; langchain-anthropic turns it into an Anthropic `document` block."""
    content: list[str | dict[Any, Any]] = [{"type": "text", "text": prompt}]
    if attachment is not None:
        content.append(attachment)
    extractor = structured(model, ExtractedPanel)
    cfg = merge_configs(config, {"tags": tags})
    out = await extractor.ainvoke(
        [SystemMessage(EXTRACT_SYSTEM), HumanMessage(content=content)], config=cfg
    )
    assert isinstance(out, ExtractedPanel)
    return out
