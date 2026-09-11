"""Model construction. One constructor for extraction, the report and chat."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 32000  # a 200-row panel is roughly 12k output tokens as JSON; reports are long


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
