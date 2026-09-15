"""Test doubles."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import BaseModel


class ScriptedChatModel(BaseChatModel):
    """Replays scripted AIMessages in order; supports bind_tools and streaming."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _next(self) -> AIMessage:
        msg = self.script[self.calls]
        self.calls += 1
        return msg

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        msg = self._next()
        chunks = [
            {
                "name": tc["name"],
                "args": json.dumps(tc["args"]),
                "id": tc["id"],
                "index": i,
                "type": "tool_call_chunk",
            }
            for i, tc in enumerate(msg.tool_calls)
        ]
        yield ChatGenerationChunk(
            message=AIMessageChunk(content=msg.content, tool_call_chunks=chunks)
        )


def tool_call(name: str, args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )


class StateSample(BaseModel):
    """A pydantic model importable by module path, for serializer round-trip tests."""

    name: str
    minutes: int
