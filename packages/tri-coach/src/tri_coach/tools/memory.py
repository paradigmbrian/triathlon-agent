"""remember / forget: the coach's only writers of its Store namespace. They find the Store through
langgraph.config.get_store(), so the same tool objects work in chat and in tests."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store

from tri_coach import memory as M

CHECKIN_DAYS = 14  # spec 5.1: a check-in summary stays in the prompt for two weeks


def make_memory_tools(today: Callable[[], date]) -> list[BaseTool]:
    async def remember(kind: M.MemoryKind, text: str, until: str | None = None) -> str:
        """Remember something the athlete said that should shape a later decision and that
        planning (goal, availability, constraints) and nutrition (profile) do not already store,
        or the one-paragraph summary at the end of a check-in.
        kind: injury | constraint | preference | event | coaching_style | note | checkin.
        until: ISO date when an injury or event ends, else omit; a checkin entry defaults to
        two weeks out."""
        end: date | None = None
        if until:
            try:
                end = date.fromisoformat(until)
            except ValueError:
                return json.dumps(
                    {"error": f"until must be an ISO date (YYYY-MM-DD), got {until!r}"}
                )
        if kind == "checkin" and end is None:
            end = today() + timedelta(days=CHECKIN_DAYS)
        entry = await M.add_entry(get_store(), kind, text, today(), end)
        return json.dumps({"remembered": True, "id": entry.id})

    async def forget(entry_id: str) -> str:
        """Remove one memory entry by the id shown in the athlete memory list."""
        ok = await M.forget_entry(get_store(), entry_id)
        return json.dumps({"forgotten": ok, "id": entry_id})

    def _tool(fn: Any, name: str) -> BaseTool:
        return StructuredTool.from_function(
            coroutine=fn, name=name, description=inspect.cleandoc(fn.__doc__ or "")
        )

    return [_tool(remember, "remember"), _tool(forget, "forget")]
