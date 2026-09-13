"""Coach-owned athlete memory in the LangGraph Store: what the athlete said that should shape a
later decision and that no sub-agent stores (injuries, constraints, preferences, events, how
they like to be coached, check-in summaries)."""

from __future__ import annotations

import secrets
from datetime import date
from typing import Literal

from langgraph.store.base import BaseStore
from pydantic import BaseModel

NAMESPACE: tuple[str, str] = ("athlete", "coach")
KEY = "memory"

MemoryKind = Literal[
    "injury", "constraint", "preference", "event", "coaching_style", "note", "checkin"
]


class MemoryEntry(BaseModel):
    id: str  # six hex characters, printed by /memory and taken by forget
    kind: MemoryKind
    text: str
    created: date
    until: date | None = None  # an injury or event with a known end


async def get_entries(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> list[MemoryEntry]:
    item = await store.aget(ns, KEY)
    if item is None:
        return []
    return [MemoryEntry.model_validate(e) for e in item.value.get("entries", [])]


async def put_entries(
    store: BaseStore, entries: list[MemoryEntry], ns: tuple[str, ...] = NAMESPACE
) -> None:
    await store.aput(ns, KEY, {"entries": [e.model_dump(mode="json") for e in entries]})


async def add_entry(
    store: BaseStore, kind: MemoryKind, text: str, today: date, until: date | None = None
) -> MemoryEntry:
    entries = await get_entries(store)
    taken = {e.id for e in entries}
    new_id = secrets.token_hex(3)
    while new_id in taken:
        new_id = secrets.token_hex(3)
    entry = MemoryEntry(id=new_id, kind=kind, text=text.strip(), created=today, until=until)
    await put_entries(store, [*entries, entry])
    return entry


async def forget_entry(store: BaseStore, entry_id: str) -> bool:
    entries = await get_entries(store)
    kept = [e for e in entries if e.id != entry_id]
    if len(kept) == len(entries):
        return False
    await put_entries(store, kept)
    return True


async def clear(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> None:
    await store.adelete(ns, KEY)


def active(entries: list[MemoryEntry], today: date) -> list[MemoryEntry]:
    return [e for e in entries if e.until is None or e.until >= today]


def render(entries: list[MemoryEntry], today: date) -> str:
    live = active(entries, today)
    if not live:
        return "Athlete memory: nothing remembered yet."
    lines = ["Athlete memory (id, kind, since, until):"]
    for e in live:
        until = f" until {e.until.isoformat()}" if e.until else ""
        lines.append(f"- {e.id} {e.kind} {e.created.isoformat()}{until}: {e.text}")
    return "\n".join(lines)
