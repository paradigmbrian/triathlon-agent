"""The nutrition review node with nothing to review: no database, no model."""

from tri_nutrition.graph.nodes.review import review_node

SUMMARY = "\n".join(
    [
        "Targets: 2026-09-14 2800 kcal.",
        "2026-09-15 run 45: not proposed: product Mystery is not in the library",
        "2026-09-27 race: not proposed: no pre-race step",
    ]
)


async def test_an_all_refused_turn_names_what_was_not_proposed(mem_store):
    state = {
        "pending_changes": [],
        "pending_summary": SUMMARY,
        "pending_violations": {
            "w2": ["product Mystery is not in the library"],
            "race": ["no pre-race step"],
        },
    }
    out = await review_node(state, store=mem_store)  # type: ignore[arg-type]
    text = out["messages"][-1].content
    assert text.startswith("No nutrition changes to review.")
    assert "2026-09-15 run 45: not proposed: product Mystery is not in the library" in text
    assert "2026-09-27 race: not proposed: no pre-race step" in text
    assert "2800 kcal" not in text


async def test_a_truly_empty_turn_says_only_that(mem_store):
    out = await review_node({"pending_changes": []}, store=mem_store)  # type: ignore[arg-type]
    assert out["messages"][-1].content == "No nutrition changes to review."
