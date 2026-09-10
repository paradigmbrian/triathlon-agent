# tri-nutrition Plan 2 of 4: Profile and Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first end-to-end nutrition conversation: the intake sub-agent interviews the athlete and saves a `NutritionProfile` to the LangGraph Store; the targets node derives the 14-day horizon from the training plan and proposes Garmin day targets; the athlete approves at a durable `interrupt()`; the apply node writes them to Garmin Connect and records every call. `tri-nutrition chat` and `tri-nutrition reset` work. This is spec milestone 2. Fueling (Plan 3) and the check-in analysis (Plan 4) come later.

**Architecture:** A hand-built LangGraph `StateGraph` over `NutritionState`, compiled with both an `AsyncPostgresSaver` (per-thread state) and an `AsyncPostgresStore` (the athlete's profile, which outlives threads). Nodes are closures over `GraphDeps`; route functions are pure over state, except the one `route` node that reads the Store. The two conversational nodes (`intake`, `checkin`) host `create_agent` sub-agents whose tools reach the Store through `langgraph.config.get_store()`. Only `apply` calls Garmin's write tool, by name, through `ToolCaller.call_json`. Garmin reads inside the intake sub-agent go through the same single server process, wrapped as LangChain tools with hand-written schemas (no second MCP session).

**Tech Stack:** langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2 (`AsyncPostgresSaver`, `AsyncPostgresStore`), langchain 1.4.0 `create_agent`, langchain-anthropic 1.7.1, psycopg 3, typer, rich, pyyaml. Depends on Plan 1 (`tri_nutrition.nutrition.*`, `tri_nutrition.repo`, `garmin_spec(enabled_tools=...)`).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md` (§2 feasibility, §5.1 the Store, §6 the graph, §8 commands, §9 error handling, §11 testing, §13 milestone 2, §15 items 2 and 5). Read Plan 1's execution notes first: `docs/superpowers/plans/2026-09-10-tri-nutrition-01-math-and-schema.md`.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root `/Users/brian/Development/paradigm/fitness_agents/triathlon_agent` as `uv run ...`.
- `tri_nutrition` imports `tri_core` only. Planning's tables (`training_goals`, `training_plans`, `plan_weeks`) are read with SQL in `plan_loader.py`; nothing imports `tri_planning`, tests included. Test seeds insert into planning tables with plain SQL.
- Pins unchanged: `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langgraph-checkpoint-postgres>=3.1,<4`, `psycopg[binary]==3.3.5`. No new dependencies.
- Store namespace is exactly `("athlete", "nutrition")` with keys `profile`, `fuel_log`, `product_library` (spec §5.1). Store access inside tools and nodes is always async (`aget`, `aput`, `adelete`): `AsyncPostgresStore` refuses synchronous calls from the event loop thread.
- Thread id is `nutrition`. LangSmith project is `tri_nutrition`, exported as `LANGSMITH_PROJECT` before LangChain loads (same trick as planning's CLI).
- Write tools are never bound to a sub-agent. `apply` is the only caller of `set_nutrition_daily_settings`. The Garmin server for the nutrition agent is started with `garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS)` from `allowlist.py`.
- Garmin facts verified 2026-09-10 (Plan 1 Task 8 and the server source at the pinned ref): `set_nutrition_daily_settings(date, calorie_goal?, carbs_grams?, fat_grams?, protein_grams?)` is a read-modify-write and returns `{"status": "updated", "date", "calorie_goal", "carbs_grams", "fat_grams", "protein_grams"}`; `get_nutrition_daily_settings(date)` returns the raw settings with `calorieGoal` and `macroGoals: {carbs, fat, protein}` (both absent or empty on an account with no goals); any nutrition date more than 90 days out is rejected with HTTP 400. `get_body_composition(start_date, end_date)` returns `dateWeightList[]` with `calendarDate`, `weight` (grams), `bodyFat` (%), `muscleMass` (grams). `get_user_profile()` returns `userData.{gender, weight (g), height (cm), birthDate}`.
- Nodes receive the Store by declaring a keyword-only parameter named `store: BaseStore`; LangGraph injects it (verified on langgraph 1.2.11). Tools call `langgraph.config.get_store()`; the store compiled into the parent graph is visible inside a `create_agent` sub-agent invoked with the node's `config` (verified).
- **Brian runs every database command.** `scripts/setup_checkpointer.py` (extended here to create the Store tables) is run by Brian against both databases. Tests write only through the rolled-back `db` fixture, except the Postgres Store test, which creates and deletes its own keys under a unique namespace.
- Definition of done per task: `uv run ruff format packages/tri-nutrition`, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case file name.

### Spec deviations decided in this plan

- **Garmin live tools for the intake sub-agent are hand-written `StructuredTool`s over the one `ToolCaller` session** (`tools/garmin.py`), not `langchain-mcp-adapters` bindings. One server process serves both the sub-agent's reads and `apply`'s writes; the allow-list is enforced by construction (only the three read tools exist as LangChain tools); the fakes are trivial. Planning's Plan 4 Task 1 (moving the adapter-based binding into tri-core) is left for planning; nothing here depends on it.
- **The `fuel` node is a pass-through in this plan.** The graph has the edge `targets -> fuel -> review` from the start so Plan 3 replaces one node without rewiring; until then `fuel` returns `{}`.
- **The `checkin` node in this plan is a sub-agent with the profile tools only** (`query_training_db`, `read_training_plan`, `read_nutrition_profile`, `save_nutrition_profile`) and a short "profile edits and questions" prompt. Plan 4 swaps in the check-in prompt and adds the Garmin food-log tools and `propose_target_changes`. Spec §6.2 already requires that profile edits after intake go through checkin's `save_nutrition_profile`, so this is the minimum that makes chat useful after intake.
- **`pending_summary` carries the rendered horizon table.** The REPL prints `summary` then the change count; the targets node renders the table in Python (`repl.render_targets`) so no extra state key is needed.
- **`NutritionState` gains `profile_saved: bool`** (set by intake or checkin when `save_nutrition_profile` succeeded this run, cleared by targets) so `after_intake` and `after_checkin` stay pure over state. `has_profile` is set by the `route` node as the spec says.
- **`get_user_profile` is exposed to intake as `read_garmin_profile`**, a trimmed tool that returns only sex, weight, height and age, so the model does not see the full 4 KB payload.
- **`/status` in this plan shows profile weight and body fat, days of targets remaining, and the last write.** The weight and body-fat *trend* needs the check-in reader (Plan 4).

---

## File Structure

```
packages/tri-nutrition/src/tri_nutrition/
  allowlist.py               GARMIN_SERVER_TOOLS, GARMIN_INTAKE_TOOLS, GARMIN_CHECKIN_TOOLS, GARMIN_WRITE_TOOLS
  store.py                   NAMESPACE, KEYS, open_store, store_ready, get_profile, put_profile,
                             get_fuel_log, get_product_library, put_product_library, forget_all
  plan_loader.py             load_horizon(conn, today, horizon_days) -> (list[Session], PlanContext)
  testing.py                 PROFILE_ARGS, MONDAY, FakeGarmin, NoCommit, seed_goal_and_plan, seed_workouts, seed_ftp
  nutrition/garmin_calls.py  consistent_calorie_goal(), day_target_change(), to_garmin_call()
  tools/garmin.py            make_garmin_read_tools(garmin, today) -> [read_garmin_profile, read_body_composition,
                             read_garmin_nutrition_settings]
  tools/profile.py           save_nutrition_profile, read_nutrition_profile (Store via get_store())
  tools/plan.py              read_training_plan (SQL through plan_loader)
  prompts/intake.py          render_intake_prompt(today)
  prompts/checkin.py         render_checkin_prompt(today)   (Plan 2 version: profile edits only)
  graph/state.py             NutritionState
  graph/deps.py              GraphDeps, make_deps
  graph/llm.py               make_model, make_subagent (copied from planning)
  graph/checkpointer.py      STATE_TYPES, make_serde, open_checkpointer, checkpointer_ready, SETUP_HINT
  graph/nodes/route.py       route_node (reads the Store, sets has_profile)
  graph/nodes/intake.py      make_intake_node
  graph/nodes/checkin.py     make_checkin_node (Plan 2 version)
  graph/nodes/targets.py     make_targets_node
  graph/nodes/fuel.py        fuel_node (pass-through)
  graph/nodes/review.py      review_node
  graph/nodes/apply.py       make_apply_node
  graph/graph.py             route functions + build_graph(deps, checkpointer, store)
  repl.py                    TurnPrinter, run_turn, render_targets, render_review, parse_decision,
                             changes_to_yaml, changes_from_yaml, chat_loop
  cli.py                     chat, reset [--yes] [--forget-profile]
packages/tri-nutrition/tests/
  conftest.py                fake_garmin, nocommit, mem_store, make_deps fixtures
  test_store.py              typed helpers on InMemoryStore; Postgres round trip (skips without tables)
  test_plan_loader.py        db: plan_weeks path, workouts path, profile_hours path
  test_garmin_calls.py       pure: consistency fix, change diffing, call translation
  test_garmin_tools.py       FakeGarmin-backed read tools
  test_profile_tools.py      save/read through get_store() inside a compiled graph
  test_plan_tool.py          db
  test_intake_node.py        db
  test_targets_node.py       db
  test_apply_node.py         db
  test_graph.py              db: end-to-end with InMemorySaver + InMemoryStore
  test_checkpointer.py       serde; second process resumes and reads the profile from Postgres
  test_repl.py               pure
scripts/setup_checkpointer.py   also runs AsyncPostgresStore.setup()
```

Responsibilities: `store.py` is the only module that knows the namespace and key names. `plan_loader.py` is the only SQL over planning's tables. `garmin_calls.py` is pure translation and diffing. `tools/` are what the sub-agents can call. `graph/nodes/` are closures over deps; `graph/graph.py` wires them. `repl.py` renders and drives; `cli.py` opens resources.

---

### Task 1: Store helpers and setup script

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/store.py`
- Modify: `scripts/setup_checkpointer.py`
- Test: `packages/tri-nutrition/tests/test_store.py`

**Interfaces:**
- Consumes: `NutritionProfile`, `Product`, `FuelLogEntry` (Plan 1).
- Produces:
  - `NAMESPACE: tuple[str, str] = ("athlete", "nutrition")`; `KEY_PROFILE = "profile"`, `KEY_FUEL_LOG = "fuel_log"`, `KEY_PRODUCTS = "product_library"`.
  - `open_store(url) -> AsyncIterator[AsyncPostgresStore]` (async context manager); `store_ready(url) -> bool`.
  - `async get_profile(store, ns=NAMESPACE) -> NutritionProfile | None`; `async put_profile(store, profile, ns=NAMESPACE) -> None`.
  - `async get_fuel_log(store, ns=NAMESPACE) -> list[FuelLogEntry]`; `async get_product_library(store, ns=NAMESPACE) -> list[Product]`; `async put_product_library(store, products, ns=NAMESPACE) -> None`.
  - `async forget_all(store, ns=NAMESPACE) -> int` deletes the three keys, returns how many existed.
  - `STORE_SETUP_HINT: str`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_store.py`:
```python
import uuid

import pytest
from langgraph.store.memory import InMemoryStore

from tri_core.config import Settings
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile, Product
from tri_nutrition.testing import PROFILE_ARGS


def profile(**over) -> NutritionProfile:
    return NutritionProfile(**{**PROFILE_ARGS, **over})


async def test_profile_round_trip_and_missing():
    mem = InMemoryStore()
    assert await S.get_profile(mem) is None
    await S.put_profile(mem, profile())
    back = await S.get_profile(mem)
    assert back == profile()
    item = await mem.aget(S.NAMESPACE, S.KEY_PROFILE)
    assert item is not None and item.value["weight_kg"] == PROFILE_ARGS["weight_kg"]


async def test_put_profile_seeds_product_library_from_tested_products():
    mem = InMemoryStore()
    gel = Product(name="Gel", form="gel", carbs_g=25)
    await S.put_profile(mem, profile(tested_products=[gel]))
    assert await S.get_product_library(mem) == [gel]
    # a second save adds new products and keeps existing ones
    mix = Product(name="Mix", form="drink", carbs_g=40)
    await S.put_profile(mem, profile(tested_products=[mix]))
    assert [p.name for p in await S.get_product_library(mem)] == ["Gel", "Mix"]


async def test_fuel_log_empty_and_forget_all():
    mem = InMemoryStore()
    assert await S.get_fuel_log(mem) == []
    await S.put_profile(mem, profile())
    assert await S.forget_all(mem) == 2  # profile + product_library
    assert await S.get_profile(mem) is None
    assert await S.forget_all(mem) == 0


async def test_postgres_store_round_trip():
    url = Settings().test_database_url
    if not S.store_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    ns = ("test", f"nutrition-{uuid.uuid4()}")
    async with S.open_store(url) as pg:
        try:
            await S.put_profile(pg, profile(), ns=ns)
            assert await S.get_profile(pg, ns=ns) == profile()
        finally:
            await S.forget_all(pg, ns=ns)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_store.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.store'` (or `tri_nutrition.testing`; Task 2 creates it, so write `testing.py` from Task 2 Step 3 first if you run tasks in order).

- [ ] **Step 3: Write the store module**

`packages/tri-nutrition/src/tri_nutrition/store.py`:
```python
"""The athlete's long-term nutrition memory: LangGraph Store namespace, keys and typed access.

Everything here is async because AsyncPostgresStore refuses synchronous calls from the event
loop thread. The same helpers work on InMemoryStore in tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.store.base import BaseStore
from langgraph.store.postgres.aio import AsyncPostgresStore

from tri_nutrition.nutrition.models import FuelLogEntry, NutritionProfile, Product

NAMESPACE: tuple[str, str] = ("athlete", "nutrition")
KEY_PROFILE = "profile"
KEY_FUEL_LOG = "fuel_log"
KEY_PRODUCTS = "product_library"
KEYS = (KEY_PROFILE, KEY_FUEL_LOG, KEY_PRODUCTS)

STORE_SETUP_HINT = (
    "LangGraph store tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


@asynccontextmanager
async def open_store(url: str) -> AsyncIterator[AsyncPostgresStore]:
    async with AsyncPostgresStore.from_conn_string(url) as store:
        yield store


def store_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.store') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])


async def get_profile(
    store: BaseStore, ns: tuple[str, ...] = NAMESPACE
) -> NutritionProfile | None:
    item = await store.aget(ns, KEY_PROFILE)
    return NutritionProfile.model_validate(item.value) if item else None


async def get_product_library(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> list[Product]:
    item = await store.aget(ns, KEY_PRODUCTS)
    return [Product.model_validate(p) for p in item.value.get("products", [])] if item else []


async def put_product_library(
    store: BaseStore, products: list[Product], ns: tuple[str, ...] = NAMESPACE
) -> None:
    await store.aput(ns, KEY_PRODUCTS, {"products": [p.model_dump(mode="json") for p in products]})


async def put_profile(
    store: BaseStore, profile: NutritionProfile, ns: tuple[str, ...] = NAMESPACE
) -> None:
    """Overwrite the profile and merge its tested products into the product library by name."""
    await store.aput(ns, KEY_PROFILE, profile.model_dump(mode="json"))
    library = await get_product_library(store, ns)
    known = {p.name for p in library}
    added = [p for p in profile.tested_products if p.name not in known]
    if added or not library:
        await put_product_library(store, library + added, ns)


async def get_fuel_log(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> list[FuelLogEntry]:
    item = await store.aget(ns, KEY_FUEL_LOG)
    return [FuelLogEntry.model_validate(e) for e in item.value.get("entries", [])] if item else []


async def forget_all(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> int:
    n = 0
    for key in KEYS:
        if await store.aget(ns, key) is not None:
            await store.adelete(ns, key)
            n += 1
    return n
```

- [ ] **Step 4: Extend the setup script**

Replace `scripts/setup_checkpointer.py` with:
```python
"""Create LangGraph's checkpoint and store tables. Brian runs this once per database; the app
never does DDL.

uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
"""

import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore


async def main(url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
    async with AsyncPostgresStore.from_conn_string(url) as store:
        await store.setup()
    print(f"checkpoint and store tables ready in {url.rsplit('/', 1)[-1]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 5: Run the tests; Brian runs the setup script**

Run: `uv run pytest packages/tri-nutrition/tests/test_store.py -q`
Expected: 3 passed, 1 skipped (the Postgres test) until Brian runs:
```bash
uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test
```
Both are idempotent (`setup()` uses migrations tables). Then 4 passed.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition scripts && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition scripts/setup_checkpointer.py
git commit -m "feat(nutrition): LangGraph Store helpers for the athlete profile; setup script creates store tables"
```

---

### Task 2: Test doubles, allow-lists, Garmin read tools

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/allowlist.py`, `packages/tri-nutrition/src/tri_nutrition/testing.py`, `packages/tri-nutrition/src/tri_nutrition/tools/__init__.py`, `packages/tri-nutrition/src/tri_nutrition/tools/garmin.py`
- Test: `packages/tri-nutrition/tests/test_garmin_tools.py`

**Interfaces:**
- Consumes: `tri_core.sync.ToolCaller`, `tri_core.mcp.client.McpToolError`.
- Produces:
  - `allowlist.GARMIN_SERVER_TOOLS` (every Garmin tool the nutrition server process registers), `GARMIN_INTAKE_TOOLS = ["get_user_profile", "get_body_composition", "get_nutrition_daily_settings"]`, `GARMIN_CHECKIN_TOOLS` (Plan 4 list, declared now), `GARMIN_WRITE_TOOLS = ["set_nutrition_daily_settings"]`.
  - `testing.PROFILE_ARGS: dict` (a complete `save_nutrition_profile` argument set), `testing.MONDAY = date(2026, 9, 14)`, `testing.FakeGarmin(responses=None, fail_on_call=None)` with `.calls` and `call_json`, `testing.NoCommit`, `testing.seed_goal_and_plan(conn, monday, weeks: list[tuple[str, list[dict]]], *, event_date=None, priority="A") -> int`, `testing.seed_workouts(conn, rows: list[dict]) -> None`, `testing.seed_ftp(conn, ftp_watts) -> None`.
  - `tools.garmin.make_garmin_read_tools(garmin: ToolCaller | None, today: Callable[[], date]) -> list[BaseTool]` returning `read_garmin_profile`, `read_body_composition`, `read_garmin_nutrition_settings`. Each returns JSON text; when `garmin` is `None` each returns `{"error": "Garmin server unavailable this session"}`.
  - `tools.garmin.parse_body_composition(payload) -> list[dict]` pure: `[{"date", "weight_kg", "body_fat_pct", "muscle_mass_kg"}]` newest last.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_garmin_tools.py`:
```python
import json

from tri_nutrition.allowlist import (
    GARMIN_CHECKIN_TOOLS,
    GARMIN_INTAKE_TOOLS,
    GARMIN_SERVER_TOOLS,
    GARMIN_WRITE_TOOLS,
)
from tri_nutrition.testing import MONDAY, FakeGarmin
from tri_nutrition.tools.garmin import make_garmin_read_tools, parse_body_composition

BODY = {
    "startDate": "2026-08-27",
    "endDate": "2026-09-09",
    "dateWeightList": [
        {"calendarDate": "2026-09-01", "weight": 81510.0, "bodyFat": 21.7, "muscleMass": 33409},
        {"calendarDate": "2026-08-29", "weight": 81900.0, "bodyFat": 22.0, "muscleMass": 33200},
    ],
    "totalAverage": {"weight": 81705.0},
}


def test_allowlists():
    for name in GARMIN_INTAKE_TOOLS + GARMIN_CHECKIN_TOOLS:
        assert name.startswith("get_") and name in GARMIN_SERVER_TOOLS
    assert GARMIN_WRITE_TOOLS == ["set_nutrition_daily_settings"]
    assert "set_nutrition_daily_settings" in GARMIN_SERVER_TOOLS


def test_parse_body_composition_orders_and_converts():
    rows = parse_body_composition(BODY)
    assert [r["date"] for r in rows] == ["2026-08-29", "2026-09-01"]
    assert rows[-1] == {
        "date": "2026-09-01",
        "weight_kg": 81.5,
        "body_fat_pct": 21.7,
        "muscle_mass_kg": 33.4,
    }
    assert parse_body_composition(None) == []


async def test_read_tools_call_server_and_trim():
    profile = {
        "id": 1,
        "userData": {
            "gender": "MALE",
            "weight": 81510.0,
            "height": 180.34,
            "birthDate": "1986-06-11",
        },
    }
    settings = {"calorieGoal": 2500, "macroGoals": {"carbs": 300, "protein": 150, "fat": 70}}
    g = FakeGarmin(
        responses={
            "get_user_profile": profile,
            "get_body_composition": BODY,
            "get_nutrition_daily_settings": settings,
        }
    )
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    assert set(tools) == {
        "read_garmin_profile",
        "read_body_composition",
        "read_garmin_nutrition_settings",
    }
    p = json.loads(await tools["read_garmin_profile"].ainvoke({}))
    assert p == {"sex": "m", "weight_kg": 81.5, "height_cm": 180.3, "age": 40}
    b = json.loads(await tools["read_body_composition"].ainvoke({"days": 14}))
    assert b[-1]["weight_kg"] == 81.5
    assert g.calls[-1] == (
        "get_body_composition",
        {"start_date": "2026-08-31", "end_date": "2026-09-14"},
    )
    s = json.loads(await tools["read_garmin_nutrition_settings"].ainvoke({}))
    assert s == {"calorie_goal": 2500, "carbs_g": 300, "protein_g": 150, "fat_g": 70}
    assert g.calls[-1] == ("get_nutrition_daily_settings", {"date": "2026-09-14"})


async def test_read_tools_without_server_and_on_error():
    tools = {t.name: t for t in make_garmin_read_tools(None, lambda: MONDAY)}
    assert "unavailable" in json.loads(await tools["read_garmin_profile"].ainvoke({}))["error"]
    g = FakeGarmin(fail_on_call=1)
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    out = json.loads(await tools["read_body_composition"].ainvoke({"days": 7}))
    assert "boom" in out["error"]
    empty = FakeGarmin(responses={"get_nutrition_daily_settings": {"macroGoals": {}}})
    tools = {t.name: t for t in make_garmin_read_tools(empty, lambda: MONDAY)}
    s = json.loads(await tools["read_garmin_nutrition_settings"].ainvoke({}))
    assert s == {"calorie_goal": None, "carbs_g": None, "protein_g": None, "fat_g": None}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_garmin_tools.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.allowlist'`.

- [ ] **Step 3: Write the allow-lists and test doubles**

`packages/tri-nutrition/src/tri_nutrition/allowlist.py`:
```python
"""Which Garmin tools the nutrition agent's server process registers and which each node may use.

Write tools are never bound to a sub-agent; only the apply node calls them, by name, through
ToolCaller.call_json.
"""

GARMIN_INTAKE_TOOLS = ["get_user_profile", "get_body_composition", "get_nutrition_daily_settings"]
GARMIN_CHECKIN_TOOLS = [
    "get_body_composition",
    "get_nutrition_daily_food_log",
    "get_nutrition_daily_meals",
    "get_hydration_data",
]
GARMIN_WRITE_TOOLS = ["set_nutrition_daily_settings"]
GARMIN_SERVER_TOOLS = sorted(set(GARMIN_INTAKE_TOOLS + GARMIN_CHECKIN_TOOLS + GARMIN_WRITE_TOOLS))
```

`packages/tri-nutrition/src/tri_nutrition/tools/__init__.py`: empty.

`packages/tri-nutrition/src/tri_nutrition/testing.py`:
```python
"""Test doubles for the nutrition graph: a fake Garmin caller, a no-commit connection wrapper,
a canned profile, and SQL seeds for planning's tables. Imported by tests only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.models import AthleteProfileRow, WorkoutRow
from tri_core.db.repo import Conn, upsert_athlete_profile, upsert_workouts
from tri_core.mcp.client import McpToolError

MONDAY = date(2026, 9, 14)

PROFILE_ARGS: dict[str, Any] = {
    "height_cm": 180,
    "weight_kg": 80,
    "body_fat_pct": 18,
    "sex": "m",
    "age": 40,
    "activity_factor": 1.35,
    "goal": "maintain",
    "target_weight_kg": None,
    "target_date": None,
    "max_weekly_change_pct": 0.5,
    "pattern": "omnivore",
    "restrictions": [],
    "dislikes": ["liver"],
    "gi_issues": [],
    "meals_per_day": 3,
    "cooks": True,
    "caffeine_mg_per_day": 200,
    "alcohol_drinks_per_week": 2,
    "tracks_food": True,
    "scale_days_per_week": 3,
    "known_sweat_rate_l_per_h": None,
    "tested_products": [{"name": "Gel", "form": "gel", "carbs_g": 25, "sodium_mg": 50}],
    "fuel_notes": [],
    "unit_preference": "metric",
    "constraints": [],
    "medical_flags": [],
}


class FakeGarmin:
    """Records every call; answers like the real server. `fail_on_call` raises on the nth call."""

    def __init__(
        self, *, responses: dict[str, Any] | None = None, fail_on_call: int | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}
        self.fail_on_call = fail_on_call

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        self.calls.append((tool, dict(args or {})))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "Error updating nutrition settings: boom")
        if tool in self.responses:
            return self.responses[tool]
        if tool == "set_nutrition_daily_settings":
            a = args or {}
            return {
                "status": "updated",
                "date": a.get("date"),
                "calorie_goal": a.get("calorie_goal"),
                "carbs_grams": a.get("carbs_grams"),
                "fat_grams": a.get("fat_grams"),
                "protein_grams": a.get("protein_grams"),
            }
        if tool == "get_nutrition_daily_settings":
            return {"weightChangeType": "NO_GOAL", "macroGoals": {}}
        return None


class NoCommit:
    """The rolled-back test connection; commit/close are no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def session_json(
    day: date, sport: str = "bike", minutes: int = 60, intensity: str = "endurance", tss: float = 50
) -> dict[str, Any]:
    """One PlannedSession as planning stores it inside plan_weeks.designed."""
    return {
        "date": day.isoformat(),
        "sport": sport,
        "title": f"{sport} {minutes}",
        "description": "",
        "duration_minutes": minutes,
        "tss_planned": tss,
        "intensity": intensity,
    }


def seed_goal_and_plan(
    conn: Conn,
    monday: date,
    weeks: list[tuple[str, list[dict[str, Any]]]],
    *,
    event_date: date | None = None,
    priority: str = "A",
    weekly_hours: float = 8,
) -> int:
    """Insert an active goal, plan and one plan_weeks row per (phase, sessions) tuple.
    A week with sessions=None has designed = null."""
    goal = conn.execute(
        "insert into training_goals (goal_type, event_name, event_date, priority, "
        "weekly_hours_min, weekly_hours_max, available_days) "
        "values ('olympic', 'City Tri', %s, %s, %s, %s, '{}') returning id",
        (event_date, priority, weekly_hours - 2, weekly_hours),
    ).fetchone()
    assert goal is not None
    plan = conn.execute(
        "insert into training_plans (goal_id, source, start_date, end_date, targets) "
        "values (%s, 'generated', %s, %s, '[]') returning id",
        (goal["id"], monday, monday + timedelta(weeks=len(weeks), days=-1)),
    ).fetchone()
    assert plan is not None
    for i, (phase, sessions) in enumerate(weeks):
        week_start = monday + timedelta(weeks=i)
        designed = (
            Jsonb({"week_start": week_start.isoformat(), "sessions": sessions, "coach_note": ""})
            if sessions is not None
            else None
        )
        conn.execute(
            "insert into plan_weeks (plan_id, week_start, phase, designed) values (%s, %s, %s, %s)",
            (plan["id"], week_start, phase, designed),
        )
    return int(plan["id"])


def seed_workouts(conn: Conn, rows: list[dict[str, Any]]) -> None:
    """rows: dicts with tp_workout_id, workout_date, sport, planned_duration_sec, and optional
    planned_distance_m, planned_tss, planned_if, completed."""
    out: list[WorkoutRow] = []
    for r in rows:
        out.append(
            WorkoutRow(
                tp_workout_id=r["tp_workout_id"],
                workout_date=r["workout_date"],
                sport=r["sport"],
                sport_raw=None,
                title=r.get("title", ""),
                description=None,
                completed=bool(r.get("completed", False)),
                planned_duration_sec=r.get("planned_duration_sec"),
                planned_distance_m=r.get("planned_distance_m"),
                planned_tss=r.get("planned_tss"),
                planned_if=r.get("planned_if"),
                actual_duration_sec=None,
                actual_distance_m=None,
                actual_tss=None,
                actual_if=None,
                normalized_power=None,
                avg_power=None,
                avg_hr=None,
                avg_cadence=None,
                elevation_gain_m=None,
                calories=r.get("calories"),
                feeling=None,
                rpe=None,
                comments=None,
                structure=None,
                raw={},
            )
        )
    upsert_workouts(conn, out)


def seed_ftp(conn: Conn, ftp_watts: int) -> None:
    upsert_athlete_profile(
        conn,
        AthleteProfileRow(
            tp_athlete_id=None,
            ftp_watts=ftp_watts,
            run_threshold_pace_sec_per_km=None,
            swim_css_sec_per_100m=None,
            lthr_bpm=None,
            max_hr_bpm=None,
            hr_zones=None,
            power_zones=None,
            pace_zones=None,
            weight_kg=None,
            raw={},
        ),
    )
```

Check `WorkoutRow` and `AthleteProfileRow` field lists against `packages/tri-core/src/tri_core/db/models.py` when writing this; the dataclasses have no defaults, so every field must be passed.

- [ ] **Step 4: Write the Garmin read tools**

`packages/tri-nutrition/src/tri_nutrition/tools/garmin.py`:
```python
"""Garmin reads for the sub-agents, as LangChain tools over the one live server session.

Hand-written schemas keep the model's view small and make the allow-list structural: only these
three read tools exist. Payloads are trimmed to what the nutrition conversation needs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller

UNAVAILABLE = json.dumps({"error": "Garmin server unavailable this session"})


class BodyCompositionArgs(BaseModel):
    days: int = Field(default=28, ge=1, le=365, description="how many days back to read")


class NoArgs(BaseModel):
    pass


def parse_body_composition(payload: Any) -> list[dict[str, Any]]:
    """Index-scale readings, oldest first, masses in kg."""
    if not isinstance(payload, dict):
        return []
    rows = []
    for e in payload.get("dateWeightList", []):
        rows.append(
            {
                "date": e.get("calendarDate"),
                "weight_kg": round(float(e["weight"]) / 1000, 1) if e.get("weight") else None,
                "body_fat_pct": e.get("bodyFat"),
                "muscle_mass_kg": (
                    round(float(e["muscleMass"]) / 1000, 1) if e.get("muscleMass") else None
                ),
            }
        )
    return sorted(rows, key=lambda r: r["date"] or "")


def _age(birth: str | None, today: date) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth[:10])
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def trim_profile(payload: Any, today: date) -> dict[str, Any]:
    data = (payload or {}).get("userData", {}) if isinstance(payload, dict) else {}
    gender = str(data.get("gender") or "").upper()
    return {
        "sex": "f" if gender == "FEMALE" else "m" if gender == "MALE" else None,
        "weight_kg": round(float(data["weight"]) / 1000, 1) if data.get("weight") else None,
        "height_cm": round(float(data["height"]), 1) if data.get("height") else None,
        "age": _age(data.get("birthDate"), today),
    }


def trim_settings(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    macros = data.get("macroGoals") or {}
    goal = data.get("calorieGoal")
    return {
        "calorie_goal": goal,
        "carbs_g": macros.get("carbs"),
        "protein_g": macros.get("protein"),
        "fat_g": macros.get("fat"),
    }


def make_garmin_read_tools(garmin: ToolCaller | None, today: Callable[[], date]) -> list[BaseTool]:
    async def _call(tool: str, args: dict[str, Any]) -> Any:
        return await garmin.call_json(tool, args) if garmin is not None else None

    async def read_garmin_profile() -> str:
        """The athlete's Garmin profile: sex, weight_kg, height_cm, age. Read this first."""
        if garmin is None:
            return UNAVAILABLE
        try:
            return json.dumps(trim_profile(await _call("get_user_profile", {}), today()))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    async def read_body_composition(days: int = 28) -> str:
        """Index-scale readings for the last `days` days: date, weight_kg, body_fat_pct,
        muscle_mass_kg, oldest first. Empty list when the athlete has not weighed in."""
        if garmin is None:
            return UNAVAILABLE
        end = today()
        args = {
            "start_date": (end - timedelta(days=days)).isoformat(),
            "end_date": end.isoformat(),
        }
        try:
            return json.dumps(parse_body_composition(await _call("get_body_composition", args)))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    async def read_garmin_nutrition_settings() -> str:
        """The calorie and macro goals Garmin currently shows for today (null when none are set)."""
        if garmin is None:
            return UNAVAILABLE
        try:
            payload = await _call("get_nutrition_daily_settings", {"date": today().isoformat()})
            return json.dumps(trim_settings(payload))
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})

    return [
        StructuredTool.from_function(
            coroutine=read_garmin_profile,
            name="read_garmin_profile",
            description=read_garmin_profile.__doc__ or "",
            args_schema=NoArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_body_composition,
            name="read_body_composition",
            description=read_body_composition.__doc__ or "",
            args_schema=BodyCompositionArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_garmin_nutrition_settings,
            name="read_garmin_nutrition_settings",
            description=read_garmin_nutrition_settings.__doc__ or "",
            args_schema=NoArgs,
        ),
    ]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_garmin_tools.py packages/tri-nutrition/tests/test_store.py -q`
Expected: 8 passed (or 7 passed, 1 skipped without the store tables).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): allow-lists, test doubles, Garmin read tools over the live session"
```

---

### Task 3: Plan loader

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/plan_loader.py`
- Test: `packages/tri-nutrition/tests/test_plan_loader.py`, `packages/tri-nutrition/tests/conftest.py`

**Interfaces:**
- Consumes: `Session`, `PlanContext`, `Phase` (Plan 1); `tri_core.db.repo.Conn`.
- Produces:
  - `plan_loader.load_horizon(conn, today, horizon_days) -> tuple[list[Session], PlanContext]`.
  - `plan_loader.sessions_from_designed(designed: dict, start, end) -> list[Session]` pure.
  - `plan_loader.session_from_workout(row: dict) -> Session | None` pure (`None` for sports outside the model, e.g. `rest`, `other`).
  - `plan_loader.intensity_from_if(planned_if: float | None) -> Intensity` pure: `None` or `< 0.75` endurance, `< 0.85` tempo, `< 0.95` threshold, else vo2.
  - `plan_loader.describe(sessions, ctx) -> dict` JSON-safe summary for the `read_training_plan` tool.

Source rules (spec §6.2 and §9): if an active plan has `plan_weeks.designed` rows, sessions come from those weeks (`source = "plan"`), phases from every `plan_weeks` row of the plan, FTP from `athlete_profile`, event date and priority from the goal. If no designed week overlaps the horizon, planned uncompleted `workouts` in the horizon are used (`source = "tp_calendar"`); phases still come from the plan if one exists. If neither yields a session, `source = "profile_hours"` with `weekly_hours = training_goals.weekly_hours_max` of the active goal (or `None`).

- [ ] **Step 1: Write the conftest and the failing tests**

`packages/tri-nutrition/tests/conftest.py`:
```python
from __future__ import annotations

import contextlib

import pytest
from langgraph.store.memory import InMemoryStore

from tri_nutrition.testing import MONDAY, FakeGarmin, NoCommit


@pytest.fixture
def fake_garmin() -> FakeGarmin:
    return FakeGarmin()


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def mem_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def make_deps(nocommit):
    from tri_core.config import Settings
    from tri_nutrition.graph.deps import GraphDeps

    def _make(model, *, garmin=None, horizon=14, today=MONDAY) -> GraphDeps:
        return GraphDeps(
            model=model,
            connect=lambda: contextlib.nullcontext(nocommit),
            db_url=Settings().test_database_url,
            garmin=garmin,
            horizon_days=horizon,
            today=lambda: today,
        )

    return _make
```

`packages/tri-nutrition/tests/test_plan_loader.py`:
```python
from datetime import timedelta

import pytest

from tri_nutrition import plan_loader as L
from tri_nutrition.testing import MONDAY, seed_ftp, seed_goal_and_plan, seed_workouts, session_json

pytestmark = pytest.mark.db


@pytest.fixture
def pdb(db):
    if db.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied to the test database")
    return db


def test_intensity_from_if():
    assert L.intensity_from_if(None) == "endurance"
    assert L.intensity_from_if(0.7) == "endurance"
    assert L.intensity_from_if(0.8) == "tempo"
    assert L.intensity_from_if(0.9) == "threshold"
    assert L.intensity_from_if(1.0) == "vo2"


def test_session_from_workout_maps_fields_and_skips_unknown_sports():
    row = {
        "tp_workout_id": "w1",
        "workout_date": MONDAY,
        "sport": "run",
        "title": "Tempo run",
        "planned_duration_sec": 3600,
        "planned_distance_m": 12000,
        "planned_tss": 70,
        "planned_if": 0.82,
    }
    s = L.session_from_workout(row)
    assert s is not None
    assert (s.sport, s.duration_min, s.distance_km, s.intensity, s.tp_workout_id) == (
        "run", 60, 12.0, "tempo", "w1",
    )
    assert L.session_from_workout({**row, "sport": "rest"}) is None
    assert L.session_from_workout({**row, "planned_duration_sec": None}) is None


def test_sessions_from_designed_filters_to_window():
    designed = {
        "week_start": MONDAY.isoformat(),
        "coach_note": "",
        "sessions": [
            session_json(MONDAY, "bike", 90, "endurance", 80),
            session_json(MONDAY + timedelta(days=3), "run", 50, "threshold", 60),
            session_json(MONDAY + timedelta(days=6), "brick", 150, "endurance", 120),
        ],
    }
    out = L.sessions_from_designed(designed, MONDAY, MONDAY + timedelta(days=4))
    assert [(s.sport, s.duration_min, s.planned_tss) for s in out] == [("bike", 90, 80), ("run", 50, 60)]
    assert out[1].intensity == "threshold" and out[1].tp_workout_id is None


def test_load_horizon_from_plan(pdb):
    seed_ftp(pdb, 250)
    weeks = [
        ("build", [session_json(MONDAY, "bike", 90), session_json(MONDAY + timedelta(days=2), "run", 40)]),
        ("peak", [session_json(MONDAY + timedelta(days=7), "swim", 45)]),
        ("taper", None),
    ]
    seed_goal_and_plan(pdb, MONDAY, weeks, event_date=MONDAY + timedelta(days=20))
    sessions, ctx = L.load_horizon(pdb, MONDAY + timedelta(days=1), 14)
    assert ctx.source == "plan" and ctx.ftp_watts == 250
    assert ctx.event_date == MONDAY + timedelta(days=20) and ctx.event_priority == "A"
    assert ctx.phases == {
        MONDAY: "build",
        MONDAY + timedelta(days=7): "peak",
        MONDAY + timedelta(days=14): "taper",
    }
    assert [(s.day, s.sport) for s in sessions] == [
        (MONDAY + timedelta(days=2), "run"),
        (MONDAY + timedelta(days=7), "swim"),
    ]


def test_load_horizon_from_tp_calendar_when_no_designed_weeks(pdb):
    seed_goal_and_plan(pdb, MONDAY, [("base", None), ("base", None)])
    seed_workouts(
        pdb,
        [
            {"tp_workout_id": "w1", "workout_date": MONDAY, "sport": "bike", "planned_duration_sec": 5400, "planned_tss": 80},
            {"tp_workout_id": "w2", "workout_date": MONDAY + timedelta(days=1), "sport": "run", "planned_duration_sec": 2400, "completed": True},
            {"tp_workout_id": "w3", "workout_date": MONDAY + timedelta(days=30), "sport": "run", "planned_duration_sec": 2400},
        ],
    )
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert ctx.source == "tp_calendar" and ctx.phases[MONDAY] == "base"
    assert [s.tp_workout_id for s in sessions] == ["w1"]  # completed and out-of-window rows dropped


def test_load_horizon_profile_hours_fallback(pdb):
    seed_goal_and_plan(pdb, MONDAY, [("base", None)], weekly_hours=9)
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert sessions == [] and ctx.source == "profile_hours" and ctx.weekly_hours == 9


def test_load_horizon_nothing_at_all(pdb):
    sessions, ctx = L.load_horizon(pdb, MONDAY, 14)
    assert sessions == [] and ctx.source == "profile_hours" and ctx.weekly_hours is None
    assert ctx.phases == {} and ctx.event_date is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_plan_loader.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.plan_loader'`. (The conftest imports `tri_nutrition.graph.deps` lazily inside the fixture, so collection works before Task 4.)

- [ ] **Step 3: Write the loader**

`packages/tri-nutrition/src/tri_nutrition/plan_loader.py`:
```python
"""The horizon's planned sessions and their context, read from planning's tables and workouts.

The only SQL over training_goals, training_plans and plan_weeks in this package. Planning owns
those tables; this module only reads them.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_nutrition.nutrition.models import Intensity, PlanContext, Session, Source

SPORTS = {"swim", "bike", "run", "brick", "strength"}


def intensity_from_if(planned_if: float | None) -> Intensity:
    if planned_if is None or planned_if < 0.75:
        return "endurance"
    if planned_if < 0.85:
        return "tempo"
    if planned_if < 0.95:
        return "threshold"
    return "vo2"


def session_from_workout(row: dict[str, Any]) -> Session | None:
    sport = row.get("sport")
    secs = row.get("planned_duration_sec")
    if sport not in SPORTS or not secs:
        return None
    dist = row.get("planned_distance_m")
    return Session(
        day=row["workout_date"],
        sport=sport,
        duration_min=int(secs) // 60,
        intensity=intensity_from_if(float(row["planned_if"]) if row.get("planned_if") else None),
        tp_workout_id=str(row["tp_workout_id"]),
        title=row.get("title") or "",
        planned_tss=float(row["planned_tss"]) if row.get("planned_tss") is not None else None,
        distance_km=float(dist) / 1000 if dist else None,
    )


def sessions_from_designed(designed: dict[str, Any], start: date, end: date) -> list[Session]:
    """Sessions of one designed week (planning's PlannedWeek JSON) that fall in [start, end]."""
    out: list[Session] = []
    for s in designed.get("sessions", []):
        day = date.fromisoformat(str(s["date"])[:10])
        if not start <= day <= end or s.get("sport") not in SPORTS:
            continue
        out.append(
            Session(
                day=day,
                sport=s["sport"],
                duration_min=int(s.get("duration_minutes") or 0),
                intensity=s.get("intensity") or "endurance",
                title=s.get("title") or "",
                planned_tss=float(s["tss_planned"]) if s.get("tss_planned") is not None else None,
            )
        )
    return out


def _active_goal(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        "select id, event_date, priority, weekly_hours_max from training_goals "
        "where status = 'active' order by created_at desc, id desc limit 1"
    ).fetchone()


def _active_plan_weeks(conn: Conn, goal_id: int) -> list[dict[str, Any]]:
    return conn.execute(
        "select w.week_start, w.phase, w.designed from plan_weeks w "
        "join training_plans p on p.id = w.plan_id "
        "where p.goal_id = %s and p.status = 'active' order by w.week_start",
        (goal_id,),
    ).fetchall()


def _planned_workouts(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title, planned_duration_sec, "
        "planned_distance_m, planned_tss, planned_if from workouts "
        "where not completed and workout_date between %s and %s order by workout_date",
        (start, end),
    ).fetchall()


def _ftp(conn: Conn) -> int | None:
    row = conn.execute("select ftp_watts from athlete_profile where id = 1").fetchone()
    return int(row["ftp_watts"]) if row and row["ftp_watts"] is not None else None


def load_horizon(conn: Conn, today: date, horizon_days: int) -> tuple[list[Session], PlanContext]:
    end = today + timedelta(days=horizon_days - 1)
    goal = _active_goal(conn)
    phases: dict[date, Any] = {}
    sessions: list[Session] = []
    source: Source = "profile_hours"
    if goal is not None:
        weeks = _active_plan_weeks(conn, int(goal["id"]))
        phases = {w["week_start"]: w["phase"] for w in weeks}
        for w in weeks:
            if w["designed"]:
                sessions += sessions_from_designed(w["designed"], today, end)
        if sessions:
            source = "plan"
    if not sessions:
        for row in _planned_workouts(conn, today, end):
            s = session_from_workout(row)
            if s is not None:
                sessions.append(s)
        if sessions:
            source = "tp_calendar"
    weekly_hours = (
        float(goal["weekly_hours_max"])
        if goal is not None and goal.get("weekly_hours_max") is not None
        else None
    )
    ctx = PlanContext(
        source=source,
        ftp_watts=_ftp(conn),
        event_date=goal["event_date"] if goal is not None else None,
        event_priority=goal["priority"] if goal is not None else None,
        phases=phases,
        weekly_hours=weekly_hours if source == "profile_hours" else None,
    )
    return sorted(sessions, key=lambda s: (s.day, s.sport)), ctx


def describe(sessions: list[Session], ctx: PlanContext) -> dict[str, Any]:
    """JSON-safe summary for the read_training_plan tool."""
    return {
        "source": ctx.source,
        "event_date": ctx.event_date.isoformat() if ctx.event_date else None,
        "event_priority": ctx.event_priority,
        "ftp_watts": ctx.ftp_watts,
        "weekly_hours": ctx.weekly_hours,
        "phases": {d.isoformat(): p for d, p in sorted(ctx.phases.items())},
        "sessions": [
            {
                "day": s.day.isoformat(),
                "sport": s.sport,
                "minutes": s.duration_min,
                "intensity": s.intensity,
                "tss": s.planned_tss,
                "title": s.title,
            }
            for s in sessions
        ],
    }
```

mypy note: `phases` is built as `dict[date, Any]` because psycopg returns `str`; `PlanContext.phases` validates the literals. If mypy complains about the `Source` reassignment, annotate `source: Source = "profile_hours"` as written.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_plan_loader.py -q`
Expected: 7 passed.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): plan loader reads the horizon's sessions from plan_weeks, workouts or goal hours"
```

---

### Task 4: State, deps, sub-agent factory, checkpointer

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/graph/__init__.py`, `graph/nodes/__init__.py`, `graph/state.py`, `graph/deps.py`, `graph/llm.py`, `graph/checkpointer.py`
- Test: `packages/tri-nutrition/tests/test_checkpointer.py` (the serde test only; the Postgres test is added in Task 9)

**Interfaces:**
- Produces:
  - `NutritionState` (spec §6.1 plus `profile_saved: bool`).
  - `GraphDeps(model, connect, db_url, garmin: ToolCaller | None = None, horizon_days: int = 14, today: Callable[[], date] = date.today)`; `ConnectFactory`; `make_deps(settings, model, garmin) -> GraphDeps`.
  - `make_model(settings)`, `make_subagent(model, tools, system_prompt)` (identical to planning's).
  - `STATE_TYPES = (NutritionChange, ReviewDecision)`, `make_serde()`, `open_checkpointer(url)`, `checkpointer_ready(url)`, `SETUP_HINT`.

- [ ] **Step 1: Write the failing test**

`packages/tri-nutrition/tests/test_checkpointer.py`:
```python
import logging
from datetime import date

from tri_nutrition.graph.checkpointer import make_serde
from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    change = NutritionChange(
        op="set_day_targets",
        target_key="2026-09-14",
        day=date(2026, 9, 14),
        payload={"calorie_goal": 2500, "carbs_grams": 300, "protein_grams": 150, "fat_grams": 60},
        reason="r",
    )
    decision = ReviewDecision(action="edit", changes=[change])
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(
            serde.dumps_typed({"pending_changes": [change], "review_decision": decision})
        )
    assert back == {"pending_changes": [change], "review_decision": decision}
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkpointer.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.graph'`.

- [ ] **Step 3: Write the four modules**

`graph/__init__.py` and `graph/nodes/__init__.py`: empty.

`packages/tri-nutrition/src/tri_nutrition/graph/state.py`:
```python
"""Graph state. One reducer: messages accumulate; every other key is last-write-wins."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision


class NutritionState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    has_profile: bool  # set by the route node from the Store each run
    profile_saved: bool  # set by intake/checkin when save_nutrition_profile succeeded this run
    profile_overrides: dict[str, Any] | None  # from propose_target_changes; persisted on approve
    regenerate_from: Literal["intake", "checkin"] | None
    pending_changes: list[NutritionChange]
    pending_summary: str | None
    review_decision: ReviewDecision | None
    last_error: str | None
```

`packages/tri-nutrition/src/tri_nutrition/graph/deps.py`:
```python
"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date

from langchain_core.language_models import BaseChatModel

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_core.sync import ToolCaller
from tri_nutrition.config import NutritionSettings

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    db_url: str  # for the read-only SQL tool, which opens its own connections
    garmin: ToolCaller | None = None  # live Garmin session; None when the server is down
    horizon_days: int = 14
    today: Callable[[], date] = date.today


def make_deps(
    settings: NutritionSettings, model: BaseChatModel, garmin: ToolCaller | None
) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        garmin=garmin,
        horizon_days=settings.tri_nutrition_horizon_days,
    )
```

`packages/tri-nutrition/src/tri_nutrition/graph/llm.py`: copy `packages/tri-planning/src/tri_planning/graph/llm.py` verbatim (module docstring, `MAX_TOKENS = 16000`, `make_model`, `make_subagent`). It has no planning imports.

`packages/tri-nutrition/src/tri_nutrition/graph/checkpointer.py`:
```python
"""Postgres-backed checkpointing so a paused review survives process exit.

The checkpointer makes `interrupt()` durable: every super-step writes a checkpoint keyed by
thread_id, and `Command(resume=...)` in a fresh process picks up from it. The Store (store.py)
is separate: it holds the profile, which must outlive any thread.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from tri_nutrition.nutrition.models import NutritionChange, ReviewDecision

STATE_TYPES: tuple[type, ...] = (NutritionChange, ReviewDecision)

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


@asynccontextmanager
async def open_checkpointer(url: str) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url, serde=make_serde()) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])
```

- [ ] **Step 4: Run the test, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkpointer.py -q`
Expected: 1 passed.

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): graph state, deps, sub-agent factory, checkpointer"
```

---

### Task 5: Profile and plan tools, intake prompt, intake node

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/tools/profile.py`, `tools/plan.py`, `prompts/__init__.py`, `prompts/intake.py`, `graph/nodes/intake.py`
- Test: `packages/tri-nutrition/tests/test_profile_tools.py`, `tests/test_plan_tool.py`, `tests/test_intake_node.py`

**Interfaces:**
- Consumes: `store.get_profile/put_profile`, `plan_loader.load_horizon/describe`, `make_subagent`, `make_garmin_read_tools`, `tri_core.db.sql_tool.make_query_tool(db_url)`.
- Produces:
  - `tools.profile.make_profile_tools() -> list[BaseTool]`: `save_nutrition_profile` (args `NutritionProfile`; returns `{"saved": true, "weight_kg": ..., "goal": ...}` or `{"error": ...}`; refuses `goal = "lose"` when `medical_flags` contains `"disordered_eating"` with a fixed message) and `read_nutrition_profile` (returns the Store profile JSON or `{"profile": null}`).
  - `tools.profile.DISORDERED_EATING_FLAG = "disordered_eating"`, `tools.profile.REFERRAL_MESSAGE`.
  - `tools.plan.make_plan_tool(connect, today, horizon_days) -> BaseTool` named `read_training_plan`.
  - `prompts.intake.render_intake_prompt(today) -> str`, `prompts.intake.SAVED_REPLY = "Profile saved. Building your targets."`.
  - `graph.nodes.intake.profile_saved_from_messages(messages) -> bool`, `make_intake_node(deps)`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_profile_tools.py`:
```python
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
```

`packages/tri-nutrition/tests/test_plan_tool.py`:
```python
import contextlib
import json
from datetime import timedelta

import pytest

from tri_nutrition.testing import MONDAY, seed_goal_and_plan, session_json
from tri_nutrition.tools.plan import make_plan_tool

pytestmark = pytest.mark.db


async def test_read_training_plan_describes_horizon(nocommit):
    if nocommit.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    seed_goal_and_plan(
        nocommit,
        MONDAY,
        [("build", [session_json(MONDAY + timedelta(days=1), "run", 50, "threshold", 60)])],
        event_date=MONDAY + timedelta(days=40),
    )
    tool = make_plan_tool(lambda: contextlib.nullcontext(nocommit), lambda: MONDAY, 14)
    out = json.loads(await tool.ainvoke({}))
    assert out["source"] == "plan" and out["phases"][MONDAY.isoformat()] == "build"
    assert out["sessions"][0]["intensity"] == "threshold" and out["event_priority"] == "A"


async def test_read_training_plan_without_plan(nocommit):
    tool = make_plan_tool(lambda: contextlib.nullcontext(nocommit), lambda: MONDAY, 14)
    out = json.loads(await tool.ainvoke({}))
    assert out["source"] == "profile_hours" and out["sessions"] == []
```

`packages/tri-nutrition/tests/test_intake_node.py`:
```python
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.intake import make_intake_node, profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.testing import PROFILE_ARGS

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def test_profile_saved_from_messages():
    ok = ToolMessage(
        content=json.dumps({"saved": True}), name="save_nutrition_profile", tool_call_id="c1"
    )
    err = ToolMessage(
        content=json.dumps({"error": "x"}), name="save_nutrition_profile", tool_call_id="c2"
    )
    assert profile_saved_from_messages([ok]) is True
    assert profile_saved_from_messages([err]) is False
    assert profile_saved_from_messages([AIMessage(content="hi")]) is False


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("intake", node)
    g.add_edge(START, "intake")
    g.add_edge("intake", END)
    return g.compile(store=store)


async def test_intake_turn_without_save_returns_only_messages(make_deps, mem_store):
    model = ScriptedChatModel(script=[AIMessage(content="What is your goal?")])
    graph = one_node_graph(make_intake_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("help me eat for my race")]}, CFG)
    assert [type(m).__name__ for m in out["messages"]] == ["HumanMessage", "AIMessage"]
    assert "profile_saved" not in out or out["profile_saved"] is False


async def test_intake_saves_profile_and_flags_state(make_deps, mem_store, fake_garmin):
    model = ScriptedChatModel(
        script=[
            tool_call("read_garmin_profile", {}),
            tool_call("save_nutrition_profile", PROFILE_ARGS, "c2"),
            AIMessage(content="Profile saved. Building your targets."),
        ]
    )
    graph = one_node_graph(make_intake_node(make_deps(model, garmin=fake_garmin)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("let's set up my nutrition")]}, CFG)
    assert out["profile_saved"] is True and out["regenerate_from"] == "intake"
    assert (await S.get_profile(mem_store)) is not None
    assert fake_garmin.calls[0][0] == "get_user_profile"
    names = [m.name for m in out["messages"] if isinstance(m, ToolMessage)]
    assert names == ["read_garmin_profile", "save_nutrition_profile"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_profile_tools.py packages/tri-nutrition/tests/test_plan_tool.py packages/tri-nutrition/tests/test_intake_node.py -q`
Expected: `ModuleNotFoundError` for `tri_nutrition.tools.profile`.

- [ ] **Step 3: Write the tools**

`packages/tri-nutrition/src/tri_nutrition/tools/profile.py`:
```python
"""Profile tools: save and read the athlete's NutritionProfile in the LangGraph Store.

The tools find the Store through langgraph.config.get_store(), which resolves to the store the
parent graph was compiled with, so the same tool objects work in chat and in tests.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, ValidationError

from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile

DISORDERED_EATING_FLAG = "disordered_eating"
REFERRAL_MESSAGE = (
    "A weight-loss goal is not set when disordered eating is flagged. Please talk to a doctor "
    "or a registered sports dietitian before changing intake; the profile can be saved with "
    "goal = maintain and revisited later."
)

SAVE_DESCRIPTION = """\
Commit the athlete's nutrition profile once every field is established and confirmed. Fields:
height_cm, weight_kg, body_fat_pct (null if unknown), sex (m | f), age; activity_factor for
non-exercise daily activity (1.2 desk-bound .. 1.5 on your feet all day, default 1.35);
goal (lose | maintain | gain_lean) with target_weight_kg and target_date (YYYY-MM-DD) for lose or
gain_lean; max_weekly_change_pct (default 0.5, at most 1.0); pattern (omnivore | pescatarian |
vegetarian | vegan | other); restrictions, dislikes, gi_issues, constraints, medical_flags as
lists of short strings (use the flag "disordered_eating" when the athlete's language suggests
it); meals_per_day; cooks; caffeine_mg_per_day and alcohol_drinks_per_week (null if unknown);
tracks_food; scale_days_per_week; known_sweat_rate_l_per_h (null if unknown); tested_products,
a list of {name, form (gel | chew | drink | bar | real_food | other), carbs_g, sodium_mg,
caffeine_mg} per serving; fuel_notes; unit_preference (metric | imperial). Returns JSON with
saved: true, or an error explaining what to fix. Do not call it more than once per confirmation."""


class NoArgs(BaseModel):
    pass


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def make_profile_tools() -> list[BaseTool]:
    async def save_nutrition_profile(**kwargs: Any) -> str:
        try:
            profile = NutritionProfile(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        if profile.goal == "lose" and DISORDERED_EATING_FLAG in profile.medical_flags:
            return json.dumps({"error": REFERRAL_MESSAGE})
        await S.put_profile(get_store(), profile)
        return json.dumps(
            {"saved": True, "weight_kg": profile.weight_kg, "goal": profile.goal}
        )

    async def read_nutrition_profile() -> str:
        """The athlete's saved nutrition profile as JSON, or {"profile": null} before intake."""
        profile = await S.get_profile(get_store())
        return json.dumps({"profile": profile.model_dump(mode="json") if profile else None})

    return [
        StructuredTool.from_function(
            coroutine=save_nutrition_profile,
            name="save_nutrition_profile",
            description=SAVE_DESCRIPTION,
            args_schema=NutritionProfile,
            handle_validation_error=_error_json,
        ),
        StructuredTool.from_function(
            coroutine=read_nutrition_profile,
            name="read_nutrition_profile",
            description=read_nutrition_profile.__doc__ or "",
            args_schema=NoArgs,
        ),
    ]
```

`packages/tri-nutrition/src/tri_nutrition/tools/plan.py`:
```python
"""read_training_plan: the horizon's sessions, phases and event, as the sub-agents see them."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from tri_nutrition import plan_loader
from tri_nutrition.graph.deps import ConnectFactory


class NoArgs(BaseModel):
    pass


def make_plan_tool(connect: ConnectFactory, today: Callable[[], date], horizon_days: int) -> BaseTool:
    async def read_training_plan() -> str:
        """The planned sessions for the coming days (day, sport, minutes, intensity, TSS), the
        plan phase per week, the goal event date and priority, FTP, and where the sessions came
        from: plan (the planning agent's designed weeks), tp_calendar (TrainingPeaks workouts),
        or profile_hours (nothing planned; the goal's weekly hours)."""
        with connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today(), horizon_days)
        return json.dumps(plan_loader.describe(sessions, ctx))

    return StructuredTool.from_function(
        coroutine=read_training_plan,
        name="read_training_plan",
        description=read_training_plan.__doc__ or "",
        args_schema=NoArgs,
    )
```

- [ ] **Step 4: Write the prompt and the node**

`packages/tri-nutrition/src/tri_nutrition/prompts/__init__.py`: empty.

`packages/tri-nutrition/src/tri_nutrition/prompts/intake.py`:
```python
"""System prompt for the intake sub-agent."""

from datetime import date

SAVED_REPLY = "Profile saved. Building your targets."


def render_intake_prompt(today: date) -> str:
    return f"""\
You are an endurance sports nutritionist setting up one athlete's nutrition profile.
Today is {today.isoformat()}.

Open by reading, not asking: call read_garmin_profile, read_body_composition and
read_garmin_nutrition_settings, and read_training_plan. Confirm weight, body fat, age and any
current Garmin targets with the athlete instead of asking cold. If Garmin is unavailable, ask for
weight, body fat (if known) and age.

Then establish, in this order, one or two questions per turn:
1. Goal and timeline: lose, maintain or gain_lean; target weight and date if not maintain.
   Warn when a lose goal overlaps the peak, taper or race weeks shown by read_training_plan (the
   deficit is paused in those weeks) and when the requested rate exceeds 0.5 % of body mass per
   week (the cap is 1 %).
2. Dietary pattern, allergies, intolerances and medical restrictions.
3. GI history by sport (what has gone wrong while training or racing).
4. Meals per day, whether they cook, caffeine and alcohol habits, whether they log food in
   Garmin, how many days a week they weigh in.
5. Tested fuel products (name, form, carbs, sodium, caffeine per serving) and sweat rate if known.
6. Constraints in the athlete's words (travel, budget, family meals, work schedule).

If the athlete's language suggests disordered eating (restriction, purging, fear of food, body
checking), stop the interview, reply with exactly this and nothing else:
"I'm not the right tool for this. Please talk to a doctor or a registered sports dietitian; I can
help with fueling for training once they're involved." Then, if the athlete still wants a
profile, save it with goal = maintain and the medical flag "disordered_eating".

Use query_training_db when you need history (weekly hours, long sessions, recent race dates).

When everything is established, summarize it in one short block, ask for confirmation, and only
after the athlete confirms call save_nutrition_profile exactly once. If it returns an error, fix
the inputs and call again. After it succeeds reply with exactly: {SAVED_REPLY}
Be brief. Use the athlete's unit preference when you talk about weight and height."""
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/intake.py`:
```python
"""Intake node: a create_agent sub-agent that ends the phase by calling save_nutrition_profile."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.intake import render_intake_prompt
from tri_nutrition.tools.garmin import make_garmin_read_tools
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def profile_saved_from_messages(messages: Sequence[AnyMessage]) -> bool:
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "save_nutrition_profile":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return False
            return bool(isinstance(data, dict) and data.get("saved"))
    return False


def make_intake_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_garmin_read_tools(deps.garmin, deps.today),
        *make_profile_tools(),
    ]
    agent = make_subagent(deps.model, tools, render_intake_prompt(deps.today()))

    async def intake(state: NutritionState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        update: dict[str, Any] = {"messages": new}
        if profile_saved_from_messages(new):
            update["profile_saved"] = True
            update["regenerate_from"] = "intake"
        return update

    return intake
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_profile_tools.py packages/tri-nutrition/tests/test_plan_tool.py packages/tri-nutrition/tests/test_intake_node.py -q`
Expected: 9 passed. `save_nutrition_profile` is registered with `coroutine=` only, so it has no sync path; the sub-agent and the tests always call `ainvoke`. Planning's `set_training_goal` is the sync twin of the same `**kwargs` + `args_schema` shape.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): profile and plan tools, intake prompt and node"
```

---

### Task 6: Garmin call translation and the targets node

**Files:**
- Create: `packages/tri-nutrition/src/tri_nutrition/nutrition/garmin_calls.py`, `graph/nodes/targets.py`, `graph/nodes/fuel.py`, plus `render_targets` in `repl.py` (started here; the rest of `repl.py` is Task 8)
- Test: `packages/tri-nutrition/tests/test_garmin_calls.py`, `tests/test_targets_node.py`

**Interfaces:**
- Consumes: `targets.build`, `bounds.validate_targets`, `repo.*`, `plan_loader.load_horizon`, `store.get_profile`.
- Produces (pure, `garmin_calls`):
  - `consistent_calorie_goal(carbs_g, protein_g, fat_g, calorie_goal) -> int` returns `calorie_goal` unless it differs from `4c + 4p + 9f` by more than `CALORIE_TOLERANCE = 20`, then the recomputed value.
  - `day_target_change(target: DayTarget) -> NutritionChange` with `op = "set_day_targets"`, `target_key = day.isoformat()`, payload `{calorie_goal, carbs_grams, protein_grams, fat_grams}`.
  - `targets_needing_write(new: list[DayTarget], existing: list[StoredDayTarget]) -> list[DayTarget]`: every day whose stored row is missing, unwritten, or differs in kcal or any macro.
  - `to_garmin_call(change) -> tuple[str, dict]`: `("set_nutrition_daily_settings", {"date", "calorie_goal", "carbs_grams", "protein_grams", "fat_grams"})` with the consistency fix applied; raises `ValueError` for other ops (Plan 3 adds the TP ops).
- Produces (`repl.render_targets(targets: list[DayTarget]) -> str`): a fixed-width table `day  type  kcal  C/P/F  session  notes`.
- Produces (`make_targets_node(deps)`): reads the profile (with `profile_overrides` applied), loads the horizon, builds, validates, upserts, emits changes, sets `pending_changes`, `pending_summary`, `profile_saved = False`; on violations writes nothing and sets `last_error` plus an `AIMessage`.
- Produces (`fuel_node(state) -> {}`), the Plan 3 placeholder.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_garmin_calls.py`:
```python
from datetime import date, timedelta

import pytest

from tri_nutrition.nutrition.garmin_calls import (
    consistent_calorie_goal,
    day_target_change,
    targets_needing_write,
    to_garmin_call,
)
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, StoredDayTarget

MONDAY = date(2026, 9, 14)


def target(day=MONDAY, **over) -> DayTarget:
    base = dict(
        day=day, day_type="easy", session_kcal=0, total_kcal=2800, carbs_g=280, protein_g=150,
        fat_g=120, fluid_baseline_ml=2800, source="plan",
    )
    base.update(over)
    return DayTarget(**base)


def test_consistent_calorie_goal():
    assert consistent_calorie_goal(280, 150, 120, 2800) == 2800  # exact
    assert consistent_calorie_goal(280, 150, 120, 2815) == 2815  # within 20
    assert consistent_calorie_goal(280, 150, 120, 2900) == 2800  # off by 100: recomputed


def test_day_target_change_and_call():
    c = day_target_change(target())
    assert c.op == "set_day_targets" and c.target_key == "2026-09-14" and c.day == MONDAY
    assert c.payload == {"calorie_goal": 2800, "carbs_grams": 280, "protein_grams": 150, "fat_grams": 120}
    name, args = to_garmin_call(c)
    assert name == "set_nutrition_daily_settings"
    assert args == {"date": "2026-09-14", **c.payload}


def test_to_garmin_call_fixes_inconsistent_goal_and_rejects_other_ops():
    c = day_target_change(target())
    c = c.model_copy(update={"payload": {**c.payload, "calorie_goal": 3000}})
    assert to_garmin_call(c)[1]["calorie_goal"] == 2800
    other = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="")
    with pytest.raises(ValueError):
        to_garmin_call(other)


def test_targets_needing_write():
    d2 = MONDAY + timedelta(days=1)
    d3 = MONDAY + timedelta(days=2)
    new = [target(), target(d2, total_kcal=3000, fat_g=142), target(d3)]
    existing = [
        StoredDayTarget(target=target(), written_to_garmin=True),  # unchanged, written: skip
        StoredDayTarget(target=target(d2), written_to_garmin=True),  # changed: write
        StoredDayTarget(target=target(d3), written_to_garmin=False),  # never written: write
    ]
    assert [t.day for t in targets_needing_write(new, existing)] == [d2, d3]
    assert [t.day for t in targets_needing_write(new, [])] == [MONDAY, d2, d3]
```

`packages/tri-nutrition/tests/test_targets_node.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.targets import make_targets_node
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, seed_ftp, seed_goal_and_plan, session_json

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    if nocommit.execute("select to_regclass('plan_weeks') as t").fetchone()["t"] is None:
        pytest.skip("planning migrations not applied")
    return nocommit


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("targets", node)
    g.add_edge(START, "targets")
    g.add_edge("targets", END)
    return g.compile(store=store)


async def test_builds_upserts_and_proposes_every_day(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    seed_ftp(ndb, 250)
    seed_goal_and_plan(ndb, MONDAY, [("build", [session_json(MONDAY + timedelta(days=2), "run", 50, "threshold", 60)]), ("build", None)])
    graph = one_node_graph(make_targets_node(make_deps(ScriptedChatModel(script=[]), horizon=7)), mem_store)
    out = await graph.ainvoke({"profile_saved": True, "regenerate_from": "intake"}, CFG)
    assert len(out["pending_changes"]) == 7 and out["profile_saved"] is False
    assert all(c.op == "set_day_targets" for c in out["pending_changes"])
    stored = repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6))
    assert len(stored) == 7 and stored[2].target.day_type == "hard"
    assert stored[0].target.plan_phase == "build" and stored[0].target.source == "plan"
    assert "hard" in out["pending_summary"] and "2026-09-16" in out["pending_summary"]
    assert out["last_error"] is None


async def test_unchanged_written_days_are_not_reproposed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    node = make_targets_node(make_deps(ScriptedChatModel(script=[]), horizon=3))
    graph = one_node_graph(node, mem_store)
    await graph.ainvoke({"profile_saved": True}, CFG)
    repo.mark_targets_written(ndb, [MONDAY, MONDAY + timedelta(days=1)])
    out = await graph.ainvoke({"profile_saved": True}, CFG)
    assert [c.day for c in out["pending_changes"]] == [MONDAY + timedelta(days=2)]


async def test_overrides_apply_on_top_of_store_profile(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    graph = one_node_graph(make_targets_node(make_deps(ScriptedChatModel(script=[]), horizon=1)), mem_store)
    base = await graph.ainvoke({"profile_saved": True}, CFG)
    more = await graph.ainvoke({"profile_saved": True, "profile_overrides": {"activity_factor": 1.5}}, CFG)
    assert more["pending_changes"][0].payload["calorie_goal"] > base["pending_changes"][0].payload["calorie_goal"]


async def test_bounds_violation_writes_nothing(ndb, make_deps, mem_store):
    # a 45 kg athlete with the max deficit lands below 30 kcal/kg FFM
    await S.put_profile(
        mem_store,
        NutritionProfile(**{**PROFILE_ARGS, "weight_kg": 45, "height_cm": 150, "body_fat_pct": 10, "goal": "lose", "target_weight_kg": 40, "max_weekly_change_pct": 1.0, "activity_factor": 1.2}),
    )
    graph = one_node_graph(make_targets_node(make_deps(ScriptedChatModel(script=[]), horizon=7)), mem_store)
    out = await graph.ainvoke({"profile_saved": True}, CFG)
    assert out["pending_changes"] == [] and "energy availability" in out["last_error"]
    assert isinstance(out["messages"][-1], AIMessage) and "energy availability" in out["messages"][-1].content
    assert repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6)) == []


async def test_without_profile_sets_error(ndb, make_deps, mem_store):
    graph = one_node_graph(make_targets_node(make_deps(ScriptedChatModel(script=[]))), mem_store)
    out = await graph.ainvoke({}, CFG)
    assert out["pending_changes"] == [] and "no nutrition profile" in out["last_error"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_garmin_calls.py packages/tri-nutrition/tests/test_targets_node.py -q`
Expected: `ModuleNotFoundError` for `tri_nutrition.nutrition.garmin_calls`.

- [ ] **Step 3: Write the translation module**

`packages/tri-nutrition/src/tri_nutrition/nutrition/garmin_calls.py`:
```python
"""DayTarget -> NutritionChange -> (Garmin MCP tool name, arguments). Pure."""

from __future__ import annotations

from typing import Any

from tri_nutrition.nutrition import constants as C
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, StoredDayTarget

CALORIE_TOLERANCE = 20  # kcal; Garmin silently corrects a goal that disagrees with the macros


def consistent_calorie_goal(carbs_g: int, protein_g: int, fat_g: int, calorie_goal: int) -> int:
    from_macros = (
        C.KCAL_PER_G_CARB * carbs_g + C.KCAL_PER_G_PROTEIN * protein_g + C.KCAL_PER_G_FAT * fat_g
    )
    return calorie_goal if abs(calorie_goal - from_macros) <= CALORIE_TOLERANCE else from_macros


def day_target_change(target: DayTarget) -> NutritionChange:
    notes = f" ({', '.join(target.notes)})" if target.notes else ""
    return NutritionChange(
        op="set_day_targets",
        target_key=target.day.isoformat(),
        day=target.day,
        payload={
            "calorie_goal": target.total_kcal,
            "carbs_grams": target.carbs_g,
            "protein_grams": target.protein_g,
            "fat_grams": target.fat_g,
        },
        reason=f"{target.day_type} day, {target.session_kcal} kcal of training{notes}",
    )


def _macros(t: DayTarget) -> tuple[int, int, int, int]:
    return t.total_kcal, t.carbs_g, t.protein_g, t.fat_g


def targets_needing_write(
    new: list[DayTarget], existing: list[StoredDayTarget]
) -> list[DayTarget]:
    by_day = {s.target.day: s for s in existing}
    out: list[DayTarget] = []
    for t in new:
        prev = by_day.get(t.day)
        if prev is not None and prev.written_to_garmin and _macros(prev.target) == _macros(t):
            continue
        out.append(t)
    return out


def to_garmin_call(change: NutritionChange) -> tuple[str, dict[str, Any]]:
    if change.op != "set_day_targets":
        raise ValueError(f"{change.op} is not a Garmin operation")
    p = change.payload
    try:
        carbs, protein, fat = int(p["carbs_grams"]), int(p["protein_grams"]), int(p["fat_grams"])
        goal = int(p["calorie_goal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"set_day_targets payload is incomplete: {exc}") from exc
    return "set_nutrition_daily_settings", {
        "date": change.day.isoformat(),
        "calorie_goal": consistent_calorie_goal(carbs, protein, fat, goal),
        "carbs_grams": carbs,
        "protein_grams": protein,
        "fat_grams": fat,
    }
```

- [ ] **Step 4: Write the table renderer (the first piece of `repl.py`)**

Create `packages/tri-nutrition/src/tri_nutrition/repl.py` with, for now, only:
```python
"""Terminal REPL for the nutrition graph: stream a turn, show node activity, run the review
dialogue, render the horizon table. (Task 8 fills in the rest.)"""

from __future__ import annotations

from tri_nutrition.nutrition.models import DayTarget


def render_targets(targets: list[DayTarget]) -> str:
    lines = [f"{'day':10}  {'type':9}  {'kcal':>5}  {'C/P/F g':>13}  {'train':>5}  notes"]
    for t in targets:
        macros = f"{t.carbs_g}/{t.protein_g}/{t.fat_g}"
        lines.append(
            f"{t.day.isoformat():10}  {t.day_type:9}  {t.total_kcal:>5}  {macros:>13}  "
            f"{t.session_kcal:>5}  {', '.join(t.notes)}"
        )
    return "\n".join(lines)
```

- [ ] **Step 5: Write the targets node and the fuel placeholder**

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/targets.py`:
```python
"""Targets node: profile + horizon -> DayTargets in the database and a Garmin change set.
No model call."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_nutrition import plan_loader, repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.bounds import validate_targets
from tri_nutrition.nutrition.garmin_calls import day_target_change, targets_needing_write
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.nutrition.targets import build
from tri_nutrition.repl import render_targets

NO_PROFILE = "no nutrition profile in the store; run intake first"


def apply_overrides(profile: NutritionProfile, overrides: dict[str, Any] | None) -> NutritionProfile:
    if not overrides:
        return profile
    return NutritionProfile.model_validate({**profile.model_dump(mode="json"), **overrides})


def make_targets_node(deps: GraphDeps) -> Any:
    async def targets_node(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        base = await S.get_profile(store)
        if base is None:
            return {
                "pending_changes": [],
                "pending_summary": None,
                "profile_saved": False,
                "last_error": NO_PROFILE,
                "messages": [AIMessage(NO_PROFILE)],
            }
        profile = apply_overrides(base, state.get("profile_overrides"))
        today = deps.today()
        with deps.connect() as conn:
            sessions, ctx = plan_loader.load_horizon(conn, today, deps.horizon_days)
        targets = build(profile, sessions, ctx, today, deps.horizon_days)
        violations = validate_targets(targets, profile)
        if violations:
            text = "Targets not written; bounds violated:\n  " + "\n  ".join(violations)
            return {
                "pending_changes": [],
                "pending_summary": None,
                "profile_saved": False,
                "last_error": "; ".join(violations),
                "messages": [AIMessage(text)],
            }
        end = today + timedelta(days=deps.horizon_days - 1)
        with deps.connect() as conn:
            existing = repo.list_targets(conn, today, end)
            repo.upsert_targets(conn, targets)
            conn.commit()
        changes = [day_target_change(t) for t in targets_needing_write(targets, existing)]
        summary = (
            f"Daily targets for {today} to {end} ({ctx.source}); {len(changes)} of "
            f"{len(targets)} days need a Garmin write.\n" + render_targets(targets)
        )
        return {
            "pending_changes": changes,
            "pending_summary": summary,
            "profile_saved": False,
            "last_error": None,
        }

    return targets_node
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`:
```python
"""Placeholder until Plan 3 replaces it with the fueling node."""

from typing import Any

from tri_nutrition.graph.state import NutritionState


def fuel_node(state: NutritionState) -> dict[str, Any]:
    return {}
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_garmin_calls.py packages/tri-nutrition/tests/test_targets_node.py -q`
Expected: 9 passed. If `test_bounds_violation_writes_nothing` does not trip the energy-availability bound, lower `weight_kg` further or raise `max_weekly_change_pct`; the assertion looks for the EA message only.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): Garmin call translation, targets node, fuel placeholder"
```

---

### Task 7: Review, apply, checkin (Plan 2 version), route, graph wiring

**Files:**
- Create: `graph/nodes/review.py`, `graph/nodes/apply.py`, `graph/nodes/checkin.py`, `graph/nodes/route.py`, `prompts/checkin.py`, `graph/graph.py`
- Test: `packages/tri-nutrition/tests/test_apply_node.py`, `tests/test_graph.py`

**Interfaces:**
- `review_node(state)`: identical in shape to planning's; reject appends `HumanMessage("Targets review rejected: <note>")`.
- `make_apply_node(deps)`: for each `set_day_targets` change, `to_garmin_call`, `deps.garmin.call_json`, `repo.insert_change` (thread id from config), `repo.mark_targets_written`; a failed call stops the batch; on success with no remainder and `profile_overrides` present, persists them with `S.put_profile` and clears `profile_overrides`. Garmin unavailable: everything stays pending with `last_error`. Non-Garmin ops (Plan 3) are skipped with a printed reason for now.
- `make_checkin_node(deps)`: sub-agent with `query_training_db`, `read_training_plan`, `read_nutrition_profile`, `save_nutrition_profile`; on save sets `profile_saved = True`, `regenerate_from = "checkin"`.
- `route_node(state, *, store)`: `{"has_profile": profile exists}`.
- `graph.build_graph(deps, checkpointer, store)`; route functions `route_start`, `after_intake`, `after_targets`, `after_review`, `after_checkin`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_apply_node.py`:
```python
from datetime import timedelta

import pytest
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.apply import make_apply_node
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import day_target_change
from tri_nutrition.nutrition.models import DayTarget, NutritionChange, NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def target(day=MONDAY, **over) -> DayTarget:
    base = dict(
        day=day, day_type="easy", session_kcal=0, total_kcal=2800, carbs_g=280, protein_g=150,
        fat_g=120, fluid_baseline_ml=2800, source="plan",
    )
    base.update(over)
    return DayTarget(**base)


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("apply", node)
    g.add_edge(START, "apply")
    g.add_edge("apply", END)
    return g.compile(store=store)


def state(changes, **over):
    return {"pending_changes": changes, "pending_summary": "s", **over}


async def test_applies_all_records_rows_and_marks_written(ndb, make_deps, mem_store):
    ts = [target(), target(MONDAY + timedelta(days=1))]
    repo.upsert_targets(ndb, ts)
    g = FakeGarmin()
    graph = one_node_graph(make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=g)), mem_store)
    out = await graph.ainvoke(state([day_target_change(t) for t in ts]), CFG)
    assert out["pending_changes"] == [] and out["last_error"] is None
    assert [c[0] for c in g.calls] == ["set_nutrition_daily_settings"] * 2
    assert g.calls[0][1]["date"] == "2026-09-14" and g.calls[0][1]["calorie_goal"] == 2800
    assert [s.written_to_garmin for s in repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=1))] == [True, True]
    rows = ndb.execute("select operation, target_key, result from nutrition_changes order by id").fetchall()
    assert [r["target_key"] for r in rows] == ["2026-09-14", "2026-09-15"]
    assert rows[0]["result"]["status"] == "updated"
    assert "applied 2 of 2" in out["messages"][-1].content


async def test_mid_batch_failure_keeps_remainder_pending(ndb, make_deps, mem_store):
    ts = [target(MONDAY + timedelta(days=i)) for i in range(3)]
    repo.upsert_targets(ndb, ts)
    g = FakeGarmin(fail_on_call=2)
    graph = one_node_graph(make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=g)), mem_store)
    out = await graph.ainvoke(state([day_target_change(t) for t in ts]), CFG)
    assert [c.day for c in out["pending_changes"]] == [MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)]
    assert "boom" in out["last_error"] and "2026-09-15" in out["last_error"]
    assert [s.written_to_garmin for s in repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=2))] == [True, False, False]
    assert ndb.execute("select count(*) as n from nutrition_changes").fetchone()["n"] == 1


async def test_refuses_without_garmin(ndb, make_deps, mem_store):
    graph = one_node_graph(make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=None)), mem_store)
    out = await graph.ainvoke(state([day_target_change(target())]), CFG)
    assert len(out["pending_changes"]) == 1 and "unavailable" in out["last_error"]


async def test_overrides_persist_to_store_on_full_success(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    graph = one_node_graph(make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=FakeGarmin())), mem_store)
    out = await graph.ainvoke(state([day_target_change(target())], profile_overrides={"activity_factor": 1.5}), CFG)
    assert out["profile_overrides"] is None
    assert (await S.get_profile(mem_store)).activity_factor == 1.5


async def test_non_garmin_ops_are_skipped_with_reason(ndb, make_deps, mem_store):
    note = NutritionChange(op="set_race_note", target_key="", day=MONDAY, payload={}, reason="r")
    g = FakeGarmin()
    graph = one_node_graph(make_apply_node(make_deps(ScriptedChatModel(script=[]), garmin=g)), mem_store)
    out = await graph.ainvoke(state([note]), CFG)
    assert g.calls == [] and out["pending_changes"] == []
    assert "skipped" in out["messages"][-1].content
```

`packages/tri-nutrition/tests/test_graph.py`:
```python
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.graph import after_review, build_graph, route_start
from tri_nutrition.nutrition.models import NutritionProfile, ReviewDecision
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "nutrition"}}
APPROVE = Command(resume={"action": "approve"})


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def intake_script():
    return [
        tool_call("save_nutrition_profile", PROFILE_ARGS),
        AIMessage(content="Profile saved. Building your targets."),
    ]


def make_graph(make_deps, mem_store, model, garmin, horizon=7):
    return build_graph(make_deps(model, garmin=garmin, horizon=horizon), InMemorySaver(), mem_store)


async def test_intake_to_review_pauses_before_any_write(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert len(payload["changes"]) == 7 and "kcal" in payload["summary"]
    assert g.calls == []
    snap = await graph.aget_state(CFG)
    assert snap.next == ("review",) and snap.values["regenerate_from"] == "intake"
    assert (await S.get_profile(mem_store)) is not None


async def test_approve_applies_and_writes_garmin(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and len(g.calls) == 7
    assert all(s.written_to_garmin for s in repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=6)))
    assert "applied 7 of 7" in out["messages"][-1].content


async def test_reject_routes_back_to_intake_with_note(ndb, make_deps, mem_store):
    model = ScriptedChatModel(
        script=[*intake_script(), AIMessage(content="What would you like to change?")]
    )
    graph = make_graph(make_deps, mem_store, model, FakeGarmin())
    await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "too few carbs"}), CFG)
    assert "__interrupt__" not in out and model.calls == 3
    msgs = out["messages"]
    assert any(isinstance(m, HumanMessage) and "too few carbs" in m.content for m in msgs)
    assert isinstance(msgs[-1], AIMessage) and "change" in msgs[-1].content


async def test_new_thread_with_profile_routes_to_checkin(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[AIMessage(content="Your profile is set; ask me anything.")])
    graph = make_graph(make_deps, mem_store, model, FakeGarmin())
    out = await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert out["has_profile"] is True and "__interrupt__" not in out
    assert out["messages"][-1].content.startswith("Your profile")


async def test_checkin_profile_edit_regenerates_targets(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    edited = {**PROFILE_ARGS, "activity_factor": 1.5}
    model = ScriptedChatModel(
        script=[tool_call("save_nutrition_profile", edited), AIMessage(content="Updated.")]
    )
    graph = make_graph(make_deps, mem_store, model, FakeGarmin(), horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("I'm on my feet all day now")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 3
    assert (await graph.aget_state(CFG)).values["regenerate_from"] == "checkin"


async def test_edit_replaces_change_set(ndb, make_deps, mem_store):
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=intake_script()), g)
    out = await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    edited = out["__interrupt__"][0].value["changes"][:2]
    out = await graph.ainvoke(Command(resume={"action": "edit", "changes": edited}), CFG)
    assert len(g.calls) == 2 and out["pending_changes"] == []


async def test_mid_batch_failure_then_reproposes_remainder(ndb, make_deps, mem_store):
    g = FakeGarmin(fail_on_call=3)
    model = ScriptedChatModel(script=[*intake_script(), AIMessage(content="Trying again.")])
    graph = make_graph(make_deps, mem_store, model, g, horizon=4)
    await graph.ainvoke({"messages": [HumanMessage("go")]}, CFG)
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(out["pending_changes"]) == 2 and "boom" in out["last_error"]
    g.fail_on_call = None
    out = await graph.ainvoke({"messages": [HumanMessage("try again")]}, CFG)
    assert "__interrupt__" in out and len(out["__interrupt__"][0].value["changes"]) == 2
    out = await graph.ainvoke(APPROVE, CFG)
    assert out["pending_changes"] == [] and len(g.calls) == 5  # 2 ok + 1 failed + 2 retried


def test_route_functions():
    assert route_start({"pending_changes": [1]}) == "review"
    assert route_start({"has_profile": False}) == "intake"
    assert route_start({"has_profile": True}) == "checkin"
    assert after_review({"review_decision": ReviewDecision(action="approve")}) == "apply"
    reject = ReviewDecision(action="reject")
    assert after_review({"review_decision": reject, "regenerate_from": "checkin"}) == "checkin"
    assert after_review({"review_decision": reject, "regenerate_from": "intake"}) == "intake"
    assert after_review({"review_decision": reject}) == "__end__"
    assert after_review({"review_decision": None}) == "__end__"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_apply_node.py packages/tri-nutrition/tests/test_graph.py -q`
Expected: `ModuleNotFoundError` for `tri_nutrition.graph.nodes.apply`.

- [ ] **Step 3: Write review and apply**

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/review.py`:
```python
"""Review node: pause the graph until the athlete decides.

`interrupt(value)` stops the run with the value exposed to the caller as `__interrupt__` and the
checkpoint records where we are. On `Command(resume=x)` the node runs again from the top and
`interrupt()` returns x. Nothing before the interrupt may have side effects.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import ReviewDecision


def review_node(state: NutritionState) -> dict[str, Any]:
    changes = state.get("pending_changes") or []
    if not changes:
        return {"review_decision": None, "messages": [AIMessage("No nutrition changes to review.")]}
    raw = interrupt(
        {
            "summary": state.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in changes],
            "last_error": state.get("last_error"),
        }
    )
    decision = ReviewDecision.model_validate(raw)
    update: dict[str, Any] = {"review_decision": decision}
    if decision.action == "reject":
        note = decision.note or "no note given"
        update["messages"] = [HumanMessage(f"Targets review rejected: {note}")]
        update["pending_changes"] = []
        update["pending_summary"] = None
        update["profile_overrides"] = None
    elif decision.action == "edit" and decision.changes is not None:
        update["pending_changes"] = decision.changes
    return update
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py`:
```python
"""Apply node: the only place Garmin (and, from Plan 3, TrainingPeaks) is written.
One call per change, recorded as it goes."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.mcp.client import McpToolError
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange

GARMIN_OPS = ("set_day_targets",)


def _label(c: NutritionChange) -> str:
    return f"{c.op} {c.target_key or c.day}"


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        thread_id = str(config["configurable"]["thread_id"])
        garmin_changes = [c for c in changes if c.op in GARMIN_OPS]
        skipped = [f"{_label(c)}: not applied in this version; dropped" for c in changes if c.op not in GARMIN_OPS]
        if garmin_changes and deps.garmin is None:
            msg = "Garmin server unavailable; nothing applied, change set left pending."
            return {
                "pending_changes": garmin_changes,
                "last_error": msg,
                "review_decision": None,
                "messages": [AIMessage(msg)],
            }

        applied: list[NutritionChange] = []
        remaining = list(garmin_changes)
        error: str | None = None
        for change in garmin_changes:
            try:
                name, args = to_garmin_call(change)
                assert deps.garmin is not None
                result = await deps.garmin.call_json(name, args)
            except (McpToolError, ValueError) as exc:
                error = f"{_label(change)} failed: {exc}"
                break
            with deps.connect() as conn:
                repo.insert_change(
                    conn,
                    thread_id,
                    change,
                    result if isinstance(result, dict) else {"result": result},
                )
                repo.mark_targets_written(conn, [change.day])
                conn.commit()
            applied.append(change)
            remaining.remove(change)

        overrides = state.get("profile_overrides")
        persisted = False
        if error is None and not remaining and overrides:
            base = await S.get_profile(store)
            if base is not None:
                await S.put_profile(store, apply_overrides(base, overrides))
                persisted = True

        lines = [f"Garmin: applied {len(applied)} of {len(garmin_changes)} day targets."]
        lines += [f"  skipped: {s}" for s in skipped]
        if persisted:
            lines.append(f"  profile updated: {overrides}")
        if error:
            lines.append(f"  stopped: {error}")
            lines.append(
                f"  {len(remaining)} days still pending; they will be re-proposed next turn."
            )
        return {
            "pending_changes": remaining,
            "pending_summary": state.get("pending_summary") if remaining else None,
            "last_error": error,
            "review_decision": None,
            "profile_overrides": None if (error is None and not remaining) else overrides,
            "messages": [AIMessage("\n".join(lines))],
        }

    return apply
```

- [ ] **Step 4: Write checkin (Plan 2 version), route, and the graph**

`packages/tri-nutrition/src/tri_nutrition/prompts/checkin.py`:
```python
"""System prompt for the checkin sub-agent. Plan 2 version: profile questions and edits only;
Plan 4 replaces this with the full check-in."""

from datetime import date


def render_checkin_prompt(today: date) -> str:
    return f"""\
You are an endurance sports nutritionist working with one athlete whose nutrition profile is
already saved. Today is {today.isoformat()}.

Call read_nutrition_profile at the start of the conversation so you know the profile. Answer
questions about the athlete's targets and plan using read_training_plan and query_training_db
(nutrition_targets holds the daily targets: day, day_type, total_kcal, carbs_g, protein_g, fat_g,
notes, written_to_garmin).

When the athlete wants to change something about themselves (weight, goal, activity level,
restrictions, products, habits), confirm the full change in one line and then call
save_nutrition_profile once with the complete updated profile (every field, not only the changed
ones). Targets are regenerated automatically after a save and shown for approval. Do not call
save_nutrition_profile for questions.

Be brief."""
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py`:
```python
"""Checkin node (Plan 2 version): a sub-agent that answers questions and edits the profile.
Plan 4 replaces the prompt and adds the food-log tools and propose_target_changes."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.nodes.intake import profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.checkin import render_checkin_prompt
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def make_checkin_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_profile_tools(),
    ]
    agent = make_subagent(deps.model, tools, render_checkin_prompt(deps.today()))

    async def checkin(state: NutritionState, config: RunnableConfig) -> dict[str, Any]:
        before = state.get("messages", [])
        result = await agent.ainvoke({"messages": before}, config)
        new = result["messages"][len(before) :]
        update: dict[str, Any] = {"messages": new}
        if profile_saved_from_messages(new):
            update["profile_saved"] = True
            update["regenerate_from"] = "checkin"
        return update

    return checkin
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/route.py`:
```python
"""Route node: the one Store read that routing needs. Edge functions stay pure over state."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from tri_nutrition import store as S
from tri_nutrition.graph.state import NutritionState


async def route_node(state: NutritionState, *, store: BaseStore) -> dict[str, Any]:
    return {"has_profile": await S.get_profile(store) is not None}
```

`packages/tri-nutrition/src/tri_nutrition/graph/graph.py`:
```python
"""The nutrition graph. Nodes are closures over GraphDeps; routing is pure functions over state.

START   -> route    (reads the Store, sets has_profile)
route   -> review   (pending_changes) | intake (no profile) | checkin
intake  -> targets  (save_nutrition_profile was called) | END
targets -> fuel     | END (bounds violated, or no profile)
fuel    -> review
review  -> apply    (approve or edit) | intake or checkin (reject) | END
apply   -> END
checkin -> targets  (save_nutrition_profile was called) | END
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore

from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.apply import make_apply_node
from tri_nutrition.graph.nodes.checkin import make_checkin_node
from tri_nutrition.graph.nodes.fuel import fuel_node
from tri_nutrition.graph.nodes.intake import make_intake_node
from tri_nutrition.graph.nodes.review import review_node
from tri_nutrition.graph.nodes.route import route_node
from tri_nutrition.graph.nodes.targets import make_targets_node
from tri_nutrition.graph.state import NutritionState


def route_start(state: NutritionState) -> str:
    if state.get("pending_changes"):
        return "review"
    return "checkin" if state.get("has_profile") else "intake"


def after_intake(state: NutritionState) -> str:
    return "targets" if state.get("profile_saved") else END


def after_checkin(state: NutritionState) -> str:
    return "targets" if state.get("profile_saved") else END


def after_targets(state: NutritionState) -> str:
    return "fuel" if state.get("pending_changes") or state.get("last_error") is None else END


def after_review(state: NutritionState) -> str:
    decision = state.get("review_decision")
    if decision is None:
        return END
    if decision.action in ("approve", "edit"):
        return "apply"
    origin = state.get("regenerate_from")
    return origin if origin in ("intake", "checkin") else END


def build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any], store: BaseStore) -> Any:
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("route", route_node)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("checkin", make_checkin_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("fuel", fuel_node)
    g.add_node("review", review_node)
    g.add_node("apply", make_apply_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_start, ["review", "intake", "checkin"])
    g.add_conditional_edges("intake", after_intake, ["targets", END])
    g.add_conditional_edges("checkin", after_checkin, ["targets", END])
    g.add_conditional_edges("targets", after_targets, ["fuel", END])
    g.add_edge("fuel", "review")
    g.add_conditional_edges("review", after_review, ["apply", "intake", "checkin", END])
    g.add_edge("apply", END)
    return g.compile(checkpointer=checkpointer, store=store, name="tri-nutrition")
```

Note on `after_targets`: when targets writes nothing because of violations, `last_error` is set and `pending_changes` is empty, so the run ends. When every day is already written and unchanged, `pending_changes` is empty and `last_error` is `None`; the run goes to `fuel` then `review`, which says "No nutrition changes to review." and ends. Both are the spec's behavior.

Note on reject: the review node clears `pending_changes` so the next `route_start` does not send a fresh turn back to review; the conversational node then continues with the rejection note in `messages`. `profile_overrides` is discarded (spec §6.2).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-nutrition/tests/test_apply_node.py packages/tri-nutrition/tests/test_graph.py -q`
Expected: 13 passed.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): review, apply, checkin and route nodes; graph wiring with end-to-end tests"
```

---

### Task 8: REPL

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/repl.py` (add everything but `render_targets`)
- Test: `packages/tri-nutrition/tests/test_repl.py`

**Interfaces:**
- Produces: `TurnPrinter`, `run_turn(graph, payload, thread_id, out)`, `render_review(payload) -> str`, `parse_decision(line) -> ReviewDecision | None`, `changes_to_yaml(changes) -> str`, `changes_from_yaml(text) -> list[NutritionChange]`, `chat_loop(graph, *, read, out, thread_id="nutrition", commands=None, edit=None)`. `STREAMED_NODES = frozenset({"intake", "checkin"})`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_repl.py`:
```python
from datetime import date

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from tri_nutrition.nutrition.models import DayTarget, NutritionChange
from tri_nutrition.repl import (
    TurnPrinter,
    changes_from_yaml,
    changes_to_yaml,
    chat_loop,
    parse_decision,
    render_review,
    render_targets,
)

MONDAY = date(2026, 9, 14)


def change(day=MONDAY, kcal=2800) -> NutritionChange:
    return NutritionChange(
        op="set_day_targets",
        target_key=day.isoformat(),
        day=day,
        payload={"calorie_goal": kcal, "carbs_grams": 280, "protein_grams": 150, "fat_grams": 120},
        reason="easy day",
    )


def interrupt_event(changes, summary="s"):
    value = {"summary": summary, "changes": [c.model_dump(mode="json") for c in changes]}
    value["last_error"] = None
    return ((), "updates", {"__interrupt__": (Interrupt(value=value),)})


def test_parse_decision():
    assert parse_decision("approve").action == "approve"
    d = parse_decision("reject too few carbs")
    assert d.action == "reject" and d.note == "too few carbs"
    assert parse_decision("edit").action == "edit"
    assert parse_decision("what?") is None


def test_yaml_round_trip():
    changes = [change(), change(date(2026, 9, 15), 3000)]
    text = changes_to_yaml(changes)
    assert "calorie_goal: 3000" in text and "set_day_targets" in text
    assert changes_from_yaml(text) == changes


def test_render_targets_and_review():
    t = DayTarget(
        day=MONDAY, day_type="hard", session_kcal=900, total_kcal=3600, carbs_g=600,
        protein_g=160, fat_g=64, fluid_baseline_ml=3500, source="plan", notes=["fat_floor"],
    )
    table = render_targets([t])
    assert "2026-09-14" in table and "hard" in table and "600/160/64" in table and "fat_floor" in table
    text = render_review({"summary": "Daily targets\n" + table, "changes": [change().model_dump(mode="json")], "last_error": "boom"})
    assert "Daily targets" in text and "previous apply stopped: boom" in text
    assert "1 change" in text and "approve / reject" in text


def test_turn_printer_handles_subgraph_events_and_interrupt():
    buf = []
    p = TurnPrinter(buf.append)
    meta = {"langgraph_node": "model"}
    p.on_event(("checkin:abc",), "messages", (AIMessageChunk(content="Hel"), meta))
    p.on_event(("checkin:abc",), "messages", (AIMessageChunk(content="lo"), meta))
    tool_msg = ToolMessage(content="{}", name="save_nutrition_profile", tool_call_id="1")
    p.on_event(("checkin:abc",), "updates", {"tools": {"messages": [tool_msg]}})
    p.on_event((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 7")]}})
    stop = Interrupt(value={"summary": "s", "changes": []})
    p.on_event((), "updates", {"__interrupt__": (stop,)})
    p.on_event((), "updates", {"checkin": {"messages": [AIMessage(content="Hello")]}})
    text = "".join(buf)
    assert "Hello" in text and "← save_nutrition_profile" in text and "Garmin: applied 7" in text
    assert text.count("Hello") == 1 and "[checkin]" not in text
    assert p.interrupt == {"summary": "s", "changes": []}


class StubGraph:
    def __init__(self, turns):
        self.turns = list(turns)
        self.inputs = []

    async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
        self.inputs.append(payload)
        for ev in self.turns.pop(0):
            yield ev

    async def aget_state(self, config):
        class S:
            values = {"pending_changes": [], "has_profile": True}
            next = ()

        return S()


async def test_chat_loop_review_dialogue_resumes_with_decision():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 1 of 1")]}})
    graph = StubGraph([[interrupt_event([change()])], [done]])
    inputs = iter(["set me up", "huh", "approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    text = "".join(buf)
    assert "approve / reject" in text and "applied 1" in text
    assert isinstance(graph.inputs[1], Command) and graph.inputs[1].resume == {"action": "approve"}


async def test_chat_loop_edit_uses_editor_callback():
    graph = StubGraph([[interrupt_event([change()])], []])
    inputs = iter(["go", "edit", "/quit"])

    async def read():
        return next(inputs, None)

    async def edit(changes):
        return [changes[0].model_copy(update={"reason": "edited"})]

    await chat_loop(graph, read=read, out=lambda s: None, edit=edit)
    resume = graph.inputs[1].resume
    assert resume["action"] == "edit" and resume["changes"][0]["reason"] == "edited"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_repl.py -q`
Expected: `ImportError: cannot import name 'TurnPrinter'`.

- [ ] **Step 3: Complete `repl.py`**

Replace `packages/tri-nutrition/src/tri_nutrition/repl.py` with:
```python
"""Terminal REPL for the nutrition graph: stream a turn, show node activity, run the review
dialogue, render the horizon table.

With `subgraphs=True` every stream event is (namespace, mode, data). The namespace is () for the
parent graph and ("intake:<id>",) or ("checkin:<id>",) inside a sub-agent. An interrupt shows up
as an "updates" event whose only key is "__interrupt__".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
import yaml
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from tri_nutrition.nutrition.models import DayTarget, NutritionChange, ReviewDecision

Out = Callable[[str], None]
CommandFn = Callable[[], Awaitable[str]]
EditFn = Callable[[list[NutritionChange]], Awaitable[list[NutritionChange] | None]]

REVIEW_PROMPT = "approve / reject <note> / edit"
# Nodes that host a sub-agent: their text was already streamed token by token, so the parent
# update that carries the same messages is not echoed again.
STREAMED_NODES = frozenset({"intake", "checkin"})


def render_targets(targets: list[DayTarget]) -> str:
    lines = [f"{'day':10}  {'type':9}  {'kcal':>5}  {'C/P/F g':>13}  {'train':>5}  notes"]
    for t in targets:
        macros = f"{t.carbs_g}/{t.protein_g}/{t.fat_g}"
        lines.append(
            f"{t.day.isoformat():10}  {t.day_type:9}  {t.total_kcal:>5}  {macros:>13}  "
            f"{t.session_kcal:>5}  {', '.join(t.notes)}"
        )
    return "\n".join(lines)


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


class TurnPrinter:
    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = _text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode != "updates" or not isinstance(data, dict):
            return
        if "__interrupt__" in data:
            first = data["__interrupt__"][0]
            self.interrupt = dict(first.value)
            return
        for node, payload in data.items():
            if not namespace and node in STREAMED_NODES:
                continue
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls:
                        self.final_text = _text_of(msg) or self.final_text
                        self.out("\n")
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self.out(f"← {msg.name}: {len(_text_of(msg))} chars\n")
                elif not namespace and isinstance(msg, AIMessage):
                    text = _text_of(msg)
                    self.out(f"[{node}] {text}\n")
                    self.final_text = text


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> TurnPrinter:
    printer = TurnPrinter(out)
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        async for namespace, mode, data in graph.astream(
            payload, config=cfg, stream_mode=["messages", "updates"], subgraphs=True
        ):
            printer.on_event(tuple(namespace), mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    return printer


def render_review(payload: dict[str, Any]) -> str:
    changes = [NutritionChange.model_validate(c) for c in payload.get("changes", [])]
    lines: list[str] = []
    if payload.get("summary"):
        lines += [str(payload["summary"]), ""]
    if payload.get("last_error"):
        lines += [f"previous apply stopped: {payload['last_error']}", ""]
    ops = sorted({c.op for c in changes})
    n = len(changes)
    lines.append(f"{n} change{'s' if n != 1 else ''} ({', '.join(ops)}). {REVIEW_PROMPT}")
    return "\n".join(lines)


def parse_decision(line: str) -> ReviewDecision | None:
    word, _, rest = line.strip().partition(" ")
    if word == "approve":
        return ReviewDecision(action="approve")
    if word == "reject":
        return ReviewDecision(action="reject", note=rest.strip() or None)
    if word == "edit":
        return ReviewDecision(action="edit")
    return None


def changes_to_yaml(changes: list[NutritionChange]) -> str:
    return yaml.safe_dump(
        [c.model_dump(mode="json", exclude_none=True) for c in changes], sort_keys=False
    )


def changes_from_yaml(text: str) -> list[NutritionChange]:
    return [NutritionChange.model_validate(d) for d in (yaml.safe_load(text) or [])]


async def _review_dialogue(
    payload: dict[str, Any],
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    edit: EditFn | None,
) -> ReviewDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None:
            return None
        if line.strip() == "/pending":
            out(render_review(payload) + "\n")
            continue
        if line.strip() == "/quit":
            return None
        decision = parse_decision(line)
        if decision is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        if decision.action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            changes = [NutritionChange.model_validate(c) for c in payload.get("changes", [])]
            edited = await edit(changes)
            if edited is None:
                out("edit cancelled\n")
                continue
            decision = ReviewDecision(action="edit", changes=edited)
        return decision


async def chat_loop(
    graph: Any,
    *,
    read: Callable[[], Awaitable[str | None]],
    out: Out,
    thread_id: str = "nutrition",
    commands: dict[str, CommandFn] | None = None,
    edit: EditFn | None = None,
) -> None:
    commands = dict(commands or {})
    names = ", ".join(sorted(["quit", "pending", *commands]))
    out(f"tri-nutrition chat. Type a message, /quit to exit, /<command> for: {names}\n")
    pending: dict[str, Any] | None = None
    while True:
        if pending is not None:
            decision = await _review_dialogue(pending, read, out, edit)
            if decision is None:
                out("\n")
                return
            resume: Command[Any] = Command(
                resume=decision.model_dump(mode="json", exclude_none=True)
            )
            printer = await run_turn(graph, resume, thread_id, out)
            pending = printer.interrupt
            continue
        line = await read()
        if line is None:
            out("\n")
            return
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            name = line[1:].split()[0]
            if name == "quit":
                return
            if name == "pending":
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                changes = snap.values.get("pending_changes") or []
                if not changes:
                    out("nothing pending\n")
                else:
                    pending = {
                        "summary": snap.values.get("pending_summary") or "",
                        "changes": [c.model_dump(mode="json") for c in changes],
                        "last_error": snap.values.get("last_error"),
                    }
                continue
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler() + "\n")
            continue
        printer = await run_turn(graph, {"messages": [HumanMessage(line)]}, thread_id, out)
        pending = printer.interrupt
```

- [ ] **Step 4: Run the tests, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition/tests/test_repl.py -q`
Expected: 6 passed.

```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): streaming REPL with review dialogue and YAML edit"
```

---

### Task 9: `chat` and `reset` commands, Postgres round-trip test, README, first conversation

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/cli.py`, `packages/tri-nutrition/tests/test_checkpointer.py` (add the Postgres test), `packages/tri-nutrition/README.md`, root `README.md`
- Test: the added Postgres test; a live conversation by Brian

**Interfaces:**
- `tri-nutrition chat [--no-live]`: opens Garmin (`McpToolClient(garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS))`, 120 s start timeout, tolerated failure), the checkpointer, the store; refuses to start when either table set is missing; commands `/status`, `/profile`, `/pending`, `/sync`, `/quit`; `edit` opens YAML in `$EDITOR`.
- `tri-nutrition reset [--yes] [--forget-profile]`: deletes unwritten `nutrition_targets` and `fuel_plans` rows, deletes thread `nutrition`; with `--forget-profile` also `store.forget_all`. Never touches Garmin.

- [ ] **Step 1: Add the Postgres round-trip test**

Add these imports to the top of `packages/tri-nutrition/tests/test_checkpointer.py` (merged with the existing ones, imports stay at module top for ruff E402):
```python
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.checkpointer import checkpointer_ready, open_checkpointer
from tri_nutrition.graph.graph import build_graph
from tri_nutrition.testing import PROFILE_ARGS, FakeGarmin
```
and append this test:
```python
@pytest.mark.db
async def test_second_process_resumes_and_reads_profile_from_postgres(nocommit, make_deps):
    url = Settings().test_database_url
    if not checkpointer_ready(url) or not S.store_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    thread = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
    script = [
        tool_call("save_nutrition_profile", PROFILE_ARGS),
        AIMessage(content="Profile saved. Building your targets."),
    ]
    garmin = FakeGarmin()
    try:
        async with open_checkpointer(url) as saver, S.open_store(url) as store:
            # the profile written by the first process must not survive the test: use the
            # real namespace but clean up in finally
            graph = build_graph(make_deps(ScriptedChatModel(script=script), garmin=garmin, horizon=2), saver, store)
            out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, thread)
            assert "__interrupt__" in out
        async with open_checkpointer(url) as saver2, S.open_store(url) as store2:
            graph2 = build_graph(make_deps(ScriptedChatModel(script=[]), garmin=garmin, horizon=2), saver2, store2)
            assert (await S.get_profile(store2)) is not None  # a second process sees the profile
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            out = await graph2.ainvoke(Command(resume={"action": "approve"}), thread)
            assert out["pending_changes"] == [] and len(garmin.calls) == 2
    finally:
        async with open_checkpointer(url) as saver3, S.open_store(url) as store3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
            await S.forget_all(store3)
```

This test writes the real `("athlete", "nutrition")` namespace in the **test** database and deletes it afterwards; `nutrition_targets` rows are written through the rolled-back `nocommit` connection so they vanish with the transaction.

- [ ] **Step 2: Write the CLI**

Replace `packages/tri-nutrition/src/tri_nutrition/cli.py` with:
```python
"""Command-line entry points for the nutrition agent: chat, reset (check-in arrives in Plan 4)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from datetime import date, timedelta
from typing import Any

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console

from tri_nutrition.config import get_nutrition_settings

load_dotenv()
# The agents share one .env; give this agent its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = get_nutrition_settings().tri_nutrition_langsmith_project

app = typer.Typer(help="Endurance nutrition agent", no_args_is_help=True)
console = Console()
THREAD_ID = "nutrition"
GARMIN_START_TIMEOUT_S = 120


@app.callback()
def main() -> None:
    """Endurance nutrition agent."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


@app.command()
def chat(
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the Garmin server"),
) -> None:
    """Set up the nutrition profile and daily targets in conversation; every Garmin write is
    approved first."""
    asyncio.run(_chat(no_live=no_live))


async def _chat(*, no_live: bool) -> None:
    from contextlib import AsyncExitStack

    from tri_core.db.connection import connect
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec
    from tri_core.sync.runner import run_sync
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS
    from tri_nutrition.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.nutrition.models import NutritionChange
    from tri_nutrition.repl import changes_from_yaml, changes_to_yaml, chat_loop

    settings = get_nutrition_settings()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        raise typer.Exit(code=2)
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        raise typer.Exit(code=2)

    async with AsyncExitStack() as stack:
        garmin = None
        if not no_live:
            try:
                garmin = await asyncio.wait_for(
                    stack.enter_async_context(
                        McpToolClient(garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS))
                    ),
                    timeout=GARMIN_START_TIMEOUT_S,
                )
                _out("garmin: connected (writes happen only after you approve)\n")
            except Exception as exc:  # the chat still works; apply holds changes pending
                _out(
                    f"warning: garmin MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "intake will ask for weight and age, and apply will hold Garmin writes\n"
                )
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin), saver, store)
        cfg = {"configurable": {"thread_id": THREAD_ID}}

        async def read() -> str | None:
            try:
                return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
            except EOFError:
                return None

        async def cmd_status() -> str:
            snap = await graph.aget_state(cfg)
            values: dict[str, Any] = snap.values or {}
            profile = await S.get_profile(store)
            if profile is None:
                return "no nutrition profile yet; say hello to start intake"
            today = date.today()
            with connect(settings.database_url) as conn:
                stored = repo.list_targets(conn, today, today + timedelta(days=365))
                last = repo.last_change_at(conn)
            written = [s for s in stored if s.written_to_garmin]
            lines = [
                f"goal: {profile.goal}; weight {profile.weight_kg:g} kg; body fat "
                f"{profile.body_fat_pct if profile.body_fat_pct is not None else '-'} %",
                f"targets from today: {len(stored)} days ({len(written)} written to Garmin)",
                f"last write: {last.isoformat(timespec='minutes') if last else 'never'}",
                f"next node: {snap.next or '-'}",
            ]
            if values.get("last_error"):
                lines.append(f"last error: {values['last_error']}")
            return "\n".join(lines)

        async def cmd_profile() -> str:
            profile = await S.get_profile(store)
            if profile is None:
                return "no nutrition profile yet"
            return yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False)

        async def cmd_sync() -> str:
            report = await run_sync(settings, log=lambda m: _out(m + "\n"))
            return "sync " + ("ok" if report.ok else "had errors")

        async def edit_in_editor(changes: list[NutritionChange]) -> list[NutritionChange] | None:
            editor = os.environ.get("EDITOR", "vi")
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                f.write(changes_to_yaml(changes))
                path = f.name
            await asyncio.to_thread(subprocess.call, [editor, path])
            try:
                with open(path) as f:
                    return changes_from_yaml(f.read())
            except Exception as exc:
                _out(f"could not parse edited YAML: {exc}\n")
                return None
            finally:
                os.unlink(path)

        await chat_loop(
            graph,
            read=read,
            out=_out,
            thread_id=THREAD_ID,
            commands={"status": cmd_status, "profile": cmd_profile, "sync": cmd_sync},
            edit=edit_in_editor,
        )


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
    forget_profile: bool = typer.Option(
        False, "--forget-profile", help="Also delete the profile, fuel log and product library"
    ),
) -> None:
    """Clear the conversation and unwritten targets. Never touches Garmin or TrainingPeaks."""
    what = "the conversation, unwritten targets" + (
        " and the saved profile" if forget_profile else ""
    )
    if not yes and not typer.confirm(f"Forget {what}?"):
        raise typer.Exit(code=1)
    asyncio.run(_reset(forget_profile))


async def _reset(forget_profile: bool) -> None:
    from tri_core.db.connection import connect
    from tri_nutrition import repo
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import checkpointer_ready, open_checkpointer

    settings = get_nutrition_settings()
    with connect(settings.database_url) as conn:
        targets = repo.delete_unwritten_targets(conn)
        plans = repo.delete_unwritten_fuel_plans(conn)
        conn.commit()
    if checkpointer_ready(settings.database_url):
        async with open_checkpointer(settings.database_url) as saver:
            await saver.adelete_thread(THREAD_ID)
    forgotten = 0
    if forget_profile and S.store_ready(settings.database_url):
        async with S.open_store(settings.database_url) as store:
            forgotten = await S.forget_all(store)
    console.print(
        f"reset: {targets} unwritten target(s) and {plans} fuel plan(s) deleted, thread cleared"
        + (f", {forgotten} store key(s) forgotten" if forget_profile else "")
    )


if __name__ == "__main__":
    app()
```

- [ ] **Step 3: Run everything**

```bash
uv run pytest -q
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run tri-nutrition --help
uv run tri-nutrition reset --help
```
Expected: all pass (the Postgres test skips until Brian has run the setup script on the test database); `--help` lists `chat` and `reset`.

- [ ] **Step 4: README updates**

Append to `packages/tri-nutrition/README.md`:
```markdown
## The graph (Plan 2)

`build_graph(deps, checkpointer, store)` compiles a LangGraph `StateGraph` over `NutritionState`
with two kinds of persistence: the checkpointer saves the thread's state after every node (so a
pause at `review` survives the process exiting), and the Store holds the athlete's profile, fuel
log and product library under `("athlete", "nutrition")`, which outlive any thread.

```mermaid
flowchart TD
    START([START]) --> route
    route -->|pending_changes| review
    route -->|no profile in the Store| intake
    route -->|profile exists| checkin
    intake["intake\ncreate_agent sub-agent\nreads Garmin, asks, calls save_nutrition_profile"]
    checkin["checkin\ncreate_agent sub-agent\nquestions and profile edits (Plan 4: the check-in)"]
    targets["targets\npure Python\nprofile + plan -> DayTargets, Garmin change set"]
    fuel["fuel\n(Plan 3)"]
    review["review\ninterrupt()\napprove / reject / edit"]
    apply["apply\nthe only Garmin writer\none call per day, each recorded"]
    intake -->|profile saved| targets
    intake -->|still asking| END1([END])
    checkin -->|profile saved| targets
    checkin --> END2([END])
    targets --> fuel
    targets -->|bounds violated| END3([END])
    fuel --> review
    review -->|approve / edit| apply
    review -->|reject| intake
    review -->|reject| checkin
    apply --> END4([END])
```

## Commands

- `tri-nutrition chat [--no-live]`: the REPL. `/status`, `/profile`, `/pending`, `/sync`, `/quit`.
  At review: `approve`, `reject <note>`, or `edit` (YAML in `$EDITOR`).
- `tri-nutrition reset [--yes] [--forget-profile]`: clears the thread and unwritten rows; only
  `--forget-profile` deletes the Store keys.

Setup once per database (creates the checkpoint and store tables):

```bash
uv run python scripts/setup_checkpointer.py $DATABASE_URL
uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL
```
```

Root `README.md`: under Layout change the tri-nutrition line to `packages/tri-nutrition/ src/tri_nutrition/{config,cli,repo,repl,store,plan_loader,testing,nutrition,graph,tools,prompts}`; under Setup, note that `scripts/setup_checkpointer.py` now also creates the LangGraph store tables.

- [ ] **Step 5: First conversation (Brian)**

```bash
uv run tri-nutrition chat
```
Expected: `garmin: connected`, then intake reads the Garmin profile and body composition and confirms them; after the interview and `save_nutrition_profile`, the horizon table prints and the review prompt appears. `approve` writes the days to Garmin and the watch shows per-day calorie and macro goals. Record in the execution notes: whether the Garmin app shows per-day targets or only the latest (spec §15 item 2), the `macroGoals` key names as returned by the first `set_nutrition_daily_settings` result, and anything the prompt got wrong.

- [ ] **Step 6: Docs to the vault, commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
cp packages/tri-nutrition/README.md $V/packages/tri-nutrition/readme.md
cp README.md $V/readme.md
cp docs/superpowers/plans/2026-09-10-tri-nutrition-02-profile-and-targets.md $V/docs/superpowers/plans/
git add -A packages/tri-nutrition README.md docs/superpowers/plans/2026-09-10-tri-nutrition-02-profile-and-targets.md
git commit -m "feat(nutrition): chat and reset commands, Postgres store round trip, README"
```

---

## Self-review notes

- Spec §5.1: namespace, three keys, `save_nutrition_profile` seeding the product library from `tested_products` (Task 1); `record_fuel_feedback` writing `fuel_log` is Plan 4. `reset` touches the Store only with `--forget-profile` (Task 9).
- Spec §6.1 state: every key, plus `profile_saved` (deviation). §6.2 edges: all present in `graph.py` (Task 7) with `fuel` as a placeholder. `route` is a node that reads the Store; every edge function is pure.
- Spec §6.2 intake: reads Garmin first, the ordered interview, the lose-in-peak warning, the rate warning, the disordered-eating referral with the tool refusing `goal = lose` (Task 5). Profile edits after intake go through `checkin` and regenerate targets (Task 7, `test_checkin_profile_edit_regenerates_targets`).
- Spec §6.2 targets: profile with overrides, sessions from `plan_weeks.designed` or `workouts`, phases from `plan_weeks`, bounds check before any write, upsert, one change per day that needs a write (Tasks 3 and 6).
- Spec §6.2 review and apply: interrupt payload, resume, reject to the originating node with a `HumanMessage`, calorie consistency, one audit row per call, `written_to_garmin`, overrides persisted on approve and discarded on reject, batch stops on failure with the remainder pending (Tasks 6 and 7). Note ownership arrives with TP notes in Plan 3.
- Spec §8: `chat` with the listed slash commands and the review dialogue; `reset` with both flags; `check-in` is Plan 4. §9: Garmin unavailable (intake asks; apply holds), bounds violation, mid-batch failure, auth-expired text surfaces through `McpToolError` in `last_error`, API errors caught per turn in `run_turn`, missing tables refuse to start.
- Spec §11 graph tests: intake ends on save and the profile is in the Store; a new thread routes to checkin; review pauses and approve reaches apply; reject routes back with the note; checkin save regenerates with the new profile; a second process reads the profile from `AsyncPostgresStore` (Task 9). `propose_target_changes` is Plan 4. Apply tests: mid-batch failure, one row per call, refusal without Garmin; ownership refusal is Plan 3.
- Spec §15 item 5 is answered in the constraints (`get_store()` works inside `create_agent` tools; nodes take `store` by keyword). Item 2 (per-day targets on the watch) is observed in Task 9 Step 5.
- Type consistency: `build_graph(deps, checkpointer, store)`; `GraphDeps.garmin`; `make_deps(model, *, garmin, horizon, today)` in the conftest; `S.get_profile(store)`/`S.put_profile(store, profile)`; `plan_loader.load_horizon(conn, today, horizon_days)`; `to_garmin_call(change)`; `day_target_change(target)`; `targets_needing_write(new, existing)`; `render_targets(targets)`; `render_review(payload)`; `apply_overrides(profile, overrides)` imported by `apply` from `targets`.

## Execution notes

(Filled in during execution; Plan 3 reads these first.)
