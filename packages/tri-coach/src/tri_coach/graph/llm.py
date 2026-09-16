"""Model construction. The agent builders live in tri_core.harness.agents."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 16000


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
