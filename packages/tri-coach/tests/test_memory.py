import json
from datetime import date

from langgraph.store.memory import InMemoryStore

from tri_coach import memory as M
from tri_coach.tools.memory import make_memory_tools
from tri_nutrition.testing import call_tool_in_graph

TODAY = date(2026, 9, 14)


async def test_add_forget_and_expiry():
    store = InMemoryStore()
    assert await M.get_entries(store) == []
    a = await M.add_entry(
        store, "injury", "Left knee sore on runs.", TODAY, until=date(2026, 9, 21)
    )
    b = await M.add_entry(store, "preference", "Prefers long rides on Saturday.", TODAY)
    assert len(a.id) == 6 and a.id != b.id
    entries = await M.get_entries(store)
    assert [e.text for e in entries] == [a.text, b.text]
    assert [e.id for e in M.active(entries, date(2026, 9, 22))] == [b.id]  # the injury expired
    assert await M.forget_entry(store, a.id) is True
    assert await M.forget_entry(store, "nope") is False
    assert [e.id for e in await M.get_entries(store)] == [b.id]
    await M.clear(store)
    assert await M.get_entries(store) == []


def test_render_lists_active_entries_with_kind_and_end():
    entries = [
        M.MemoryEntry(
            id="ab12cd",
            kind="injury",
            text="Left knee sore.",
            created=TODAY,
            until=date(2026, 9, 21),
        ),
        M.MemoryEntry(
            id="ef34gh",
            kind="coaching_style",
            text="Wants blunt feedback.",
            created=date(2026, 9, 1),
        ),
        M.MemoryEntry(
            id="ij56kl",
            kind="event",
            text="Travel Oct 2-5.",
            created=TODAY,
            until=date(2026, 9, 10),
        ),
    ]
    text = M.render(entries, TODAY)
    assert text.startswith("Athlete memory (id, kind, since, until):")
    assert "ab12cd injury 2026-09-14 until 2026-09-21: Left knee sore." in text
    assert "ef34gh coaching_style 2026-09-01: Wants blunt feedback." in text
    assert "ij56kl" not in text
    assert M.render([], TODAY) == "Athlete memory: nothing remembered yet."


async def test_remember_and_forget_tools_write_the_store():
    store = InMemoryStore()
    remember, forget = make_memory_tools(lambda: TODAY)
    out = json.loads(
        await call_tool_in_graph(
            store,
            remember,
            {
                "kind": "constraint",
                "text": "No pool access on Fridays.",
                "until": None,
            },
        )
    )
    assert out["remembered"] is True and len(out["id"]) == 6
    out2 = json.loads(
        await call_tool_in_graph(
            store,
            remember,
            {
                "kind": "injury",
                "text": "Knee.",
                "until": "2026-09-30",
            },
        )
    )
    entries = await M.get_entries(store)
    assert [e.kind for e in entries] == ["constraint", "injury"]
    assert entries[1].until == date(2026, 9, 30)
    bad = json.loads(
        await call_tool_in_graph(
            store,
            remember,
            {
                "kind": "injury",
                "text": "x",
                "until": "next week",
            },
        )
    )
    assert "until" in bad["error"]
    gone = json.loads(await call_tool_in_graph(store, forget, {"entry_id": out2["id"]}))
    assert gone == {"forgotten": True, "id": out2["id"]}
    assert (
        json.loads(await call_tool_in_graph(store, forget, {"entry_id": "zzzzzz"}))["forgotten"]
        is False
    )
    assert [e.kind for e in await M.get_entries(store)] == ["constraint"]
