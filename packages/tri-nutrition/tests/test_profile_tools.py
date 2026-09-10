import json
from typing import Any, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from tri_nutrition import store as S
from tri_nutrition.testing import PROFILE_ARGS
from tri_nutrition.tools.profile import (
    DISORDERED_EATING_FLAG,
    REFERRAL_MESSAGE,
    make_profile_tools,
)


class St(TypedDict, total=False):
    out: str


async def run_tool_in_graph(store: InMemoryStore, tool: BaseTool, args: dict[str, Any]) -> str:
    """Tools reach the Store through get_store(), so they must run inside a compiled graph."""

    async def node(state: St) -> dict[str, Any]:
        return {"out": await tool.ainvoke(args)}

    g: StateGraph[St] = StateGraph(St)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    result = await g.compile(store=store).ainvoke({})
    return str(result["out"])


def tools() -> dict[str, BaseTool]:
    return {t.name: t for t in make_profile_tools()}


async def test_save_then_read(mem_store):
    t = tools()
    out = json.loads(await run_tool_in_graph(mem_store, t["save_nutrition_profile"], PROFILE_ARGS))
    assert out["saved"] is True and out["goal"] == "maintain"
    stored = await S.get_profile(mem_store)
    assert stored is not None and stored.weight_kg == 80
    assert [p.name for p in await S.get_product_library(mem_store)] == ["Gel"]
    back = json.loads(await run_tool_in_graph(mem_store, t["read_nutrition_profile"], {}))
    assert back["profile"]["dislikes"] == ["liver"]


async def test_read_without_profile(mem_store):
    out = json.loads(await run_tool_in_graph(mem_store, tools()["read_nutrition_profile"], {}))
    assert out == {"profile": None}


async def test_validation_error_is_returned_as_text(mem_store):
    bad = {**PROFILE_ARGS, "goal": "lose", "target_weight_kg": 90}
    out = json.loads(await run_tool_in_graph(mem_store, tools()["save_nutrition_profile"], bad))
    assert "error" in out and "target_weight_kg" in out["error"]
    assert await S.get_profile(mem_store) is None


async def test_lose_refused_with_disordered_eating_flag(mem_store):
    args = {
        **PROFILE_ARGS,
        "goal": "lose",
        "target_weight_kg": 75,
        "medical_flags": [DISORDERED_EATING_FLAG],
    }
    out = json.loads(await run_tool_in_graph(mem_store, tools()["save_nutrition_profile"], args))
    assert out["error"] == REFERRAL_MESSAGE
    assert await S.get_profile(mem_store) is None
