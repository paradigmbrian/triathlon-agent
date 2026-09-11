# tri-nutrition Plan 4 of 4: Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The check-in: a `checkin` sub-agent that reads logged intake against the stored targets, body composition, recovery and workout comments, records fueling feedback into the Store's fuel log, and proposes profile changes (or a horizon regeneration) that the graph turns into a reviewed change set; the `tri-nutrition check-in [--yes]` command that runs it unattended; and a LangSmith dataset with code evaluators and an LLM judge over the fueling prompts. This is spec milestone 4.

**Architecture:** `checkin` keeps its Plan 2 shape (a `create_agent` sub-agent whose tool results decide the route) and gains the check-in prompt, two Garmin read tools, and three check-in tools in `tools/checkin.py`. `read_intake_vs_targets` joins the Garmin food log to `nutrition_targets` in Python so the model reads a comparison, not two lists. `propose_target_changes` validates only; the node copies the proposal into `profile_overrides` and sets `targets_requested`, and the existing `targets -> fuel -> review -> apply` chain regenerates, reviews, and persists the overrides into the Store on approve (Plan 2 already built that half). The fuel node's per-session and race calls move into a `FuelPlanner` class so the evaluation target can run the same prompts without a database.

**Tech Stack:** langchain 1.4.0 `create_agent` and `with_structured_output`, langgraph 1.2.11 Store, langsmith 0.12.2 `aevaluate` (already installed as a langchain-core dependency; declared explicitly now that it is imported), psycopg 3. Depends on Plans 1 to 3 as merged on main.

**Spec:** `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md` (§2 Garmin tools, §5.1 fuel log and product library, §6.1 state, §6.2 checkin and targets, §8 `check-in` and `/status`, §9, §11 graph tests, §12 evaluation, §13 milestone 4). Read Plan 3's execution notes first.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- `tri_nutrition` imports `tri_core` only. No new packages are installed; `langsmith>=0.12,<1` is added to `pyproject.toml` because `evals/` imports it directly (it is already in the lock through langchain-core).
- Garmin facts (fixtures recorded 2026-09-10 in `packages/tri-nutrition/tests/fixtures/mcp/`): `get_nutrition_daily_food_log(date)` returns `{"mealDate", "dailyNutritionContent": {calories, carbs, protein, fat}, "mealDetails": [{"meal": {"mealName"}, "mealNutritionContent": {calories, carbs, protein, fat}?, "loggedFoods": [{"foodMetaData": {"foodName"}, "servingQty", "nutritionContent": {...}}]}]}` (grams); `get_hydration_data(date)` returns `{"calendarDate", "valueInML", "goalInML", "sweatLossInML", ...}` with nulls when nothing was logged; `get_nutrition_daily_meals(date)` returns only the meal windows (no totals), so it is not used.
- Write tools are never bound to a sub-agent. `record_fuel_feedback` writes the Store only; `propose_target_changes` writes nothing.
- Every model call in tests goes through `ScriptedChatModel` and `tool_call(...)` from `tri_core.testing`.
- **Brian runs every database command and every git write.** Tests use the rolled-back `db` fixture, `InMemoryStore`, `FakeGarmin` and `FakeTp`.
- Definition of done per task: `uv run ruff format packages/tri-nutrition`, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` (kebab-case file names).

### Spec deviations decided in this plan

- **`get_nutrition_daily_meals` is dropped from `GARMIN_CHECKIN_TOOLS`.** The recorded fixture shows it carries meal windows only; per-meal totals are inside the food log payload. The check-in reads intake from `get_nutrition_daily_food_log` alone.
- **The intake comparison is a Python tool, not two model reads.** `read_intake_vs_targets(days)` calls Garmin per day, parses totals, joins them to `nutrition_targets`, and returns per-day deltas plus per-day-type averages and the days of targets remaining. Spec §6.2 lists the raw Garmin tools; the join keeps the arithmetic out of the model, which is the spec's own rule ("Python owns the math").
- **A `targets_requested: bool` state key** carries "propose_target_changes was called" so an empty override set (the horizon extension) still routes `checkin -> targets`. `profile_overrides` alone cannot: `{}` is falsy. `targets` clears both flags and clears `profile_overrides` when a bound is violated (the proposal is discarded with the violations shown, spec §9).
- **`/status` stays offline.** The spec's "weight and body fat trend" in `/status` would need a Garmin call; the check-in reports the trend instead. `/status` gains the horizon end date and the fuel-log size.
- **The check-in command does not need the chat to approve.** `tri-nutrition check-in` without `--yes` exits with code 3 when a change set is paused at review; running it again (or `tri-nutrition chat`) resumes that review instead of starting a second one.
- **Evaluation target is the fueling half only.** Targets are deterministic Python, so the dataset exercises `FuelPlanner` (session and race prompts) over five (profile, training week) cases; `targets_within_bounds` is still an evaluator because the target function builds the week's `DayTarget`s as prompt input.

---

## File Structure

```
packages/tri-nutrition/pyproject.toml          + langsmith
packages/tri-nutrition/src/tri_nutrition/
  allowlist.py               GARMIN_CHECKIN_TOOLS trimmed; INTAKE_READ_TOOLS, CHECKIN_READ_TOOLS
  store.py                   + append_fuel_entry(), add_product()
  repo.py                    + last_target_day()
  testing.py                 FakeGarmin callable responses and food-log / hydration defaults; call_tool_in_graph()
  graph/state.py             + targets_requested
  graph/graph.py             after_checkin honours targets_requested
  graph/nodes/targets.py     clears targets_requested; clears profile_overrides on violation
  graph/nodes/checkin.py     full tool set; proposal_from_messages(); sets overrides and flags
  graph/nodes/fuel.py        FuelPlanner (session, race) used by the node and by evals
  graph/nodes/intake.py      make_garmin_read_tools(..., only=INTAKE_READ_TOOLS)
  tools/garmin.py            parse_food_log(), parse_hydration(), read_hydration; `only` filter
  tools/checkin.py           read_intake_vs_targets, record_fuel_feedback, propose_target_changes
  prompts/checkin.py         the check-in prompt; CHECKIN_REQUEST
  prompts/fuel.py            + PROMPT_VERSION
  repl.py                    + checkin_run()
  cli.py                     check-in, eval; _open_servers(); /status lines
  evals/__init__.py
  evals/cases.py             EvalCase, CASES
  evals/target.py            parse_inputs(), run_case(), make_target()
  evals/evaluators.py        targets_within_bounds, fuel_within_bounds, make_fuel_judge
  evals/run.py               DATASET_NAME, ensure_dataset(), pass_rates(), run_eval()
packages/tri-nutrition/tests/
  test_store.py              + fuel log and product cases
  test_garmin_tools.py       + parse_food_log (fixture), parse_hydration, read_hydration, `only`
  test_checkin_tools.py      new
  test_checkin_node.py       new
  test_graph.py              + proposal approve / reject / extend, checkin_run
  test_evals.py              new
  test_repo.py               + last_target_day
```

Responsibilities: `tools/garmin.py` parses Garmin payloads; `tools/checkin.py` joins and commits to the Store; `nodes/checkin.py` turns tool results into state; `evals/` never touches the database.

---

### Task 1: Store helpers, Garmin parsing, hydration tool, fakes, state key

**Files:**
- Modify: `store.py`, `repo.py`, `allowlist.py`, `testing.py`, `tools/garmin.py`, `graph/nodes/intake.py`, `graph/state.py`
- Test: `tests/test_store.py`, `tests/test_garmin_tools.py`, `tests/test_repo.py`

**Interfaces:**
- `store.append_fuel_entry(store, entry: FuelLogEntry, ns=NAMESPACE) -> int` returns the new length; `store.add_product(store, product: Product, ns=NAMESPACE) -> bool` returns `True` when added (names are unique).
- `repo.last_target_day(conn) -> date | None`.
- `allowlist.GARMIN_CHECKIN_TOOLS = ["get_body_composition", "get_nutrition_daily_food_log", "get_hydration_data"]`; `INTAKE_READ_TOOLS = ("read_garmin_profile", "read_body_composition", "read_garmin_nutrition_settings")`; `CHECKIN_READ_TOOLS = ("read_body_composition", "read_hydration")`.
- `tools.garmin.parse_food_log(payload) -> dict` with keys `logged: bool, kcal, carbs_g, protein_g, fat_g: int, meals: dict[str, int], items: list[str]`; `parse_hydration(payload) -> dict` with `date, intake_ml, goal_ml, sweat_loss_ml`; `RecentDaysArgs(days: int = 7, 1..28)`; `make_garmin_read_tools(garmin, today, only: Collection[str] | None = None)` now also builds `read_hydration(days=7)`.
- `testing.FakeGarmin`: a `responses[tool]` value may be a callable taking the args dict; defaults for `get_hydration_data` and `get_nutrition_daily_food_log`. `testing.call_tool_in_graph(store, tool, args) -> str` runs a tool inside a compiled graph so `get_store()` resolves.
- `NutritionState.targets_requested: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-nutrition/tests/test_store.py`:
```python
async def test_fuel_log_append_and_product_add():
    from tri_nutrition.nutrition.models import FuelLogEntry

    mem = InMemoryStore()
    assert await S.get_fuel_log(mem) == []
    e1 = FuelLogEntry(day=date(2026, 9, 7), sport="bike", duration_min=150, carbs_g_per_h=70, outcome="ok")
    e2 = FuelLogEntry(day=date(2026, 9, 9), sport="run", duration_min=60, carbs_g_per_h=40, outcome="gi_upset", note="side stitch")
    assert await S.append_fuel_entry(mem, e1) == 1
    assert await S.append_fuel_entry(mem, e2) == 2
    assert [e.outcome for e in await S.get_fuel_log(mem)] == ["ok", "gi_upset"]
    gel = Product(name="Gel", form="gel", carbs_g=25)
    assert await S.add_product(mem, gel) is True
    assert await S.add_product(mem, Product(name="Gel", form="gel", carbs_g=30)) is False
    assert await S.add_product(mem, Product(name="Chews", form="chew", carbs_g=24)) is True
    assert [p.name for p in await S.get_product_library(mem)] == ["Gel", "Chews"]
```
(add `from datetime import date` at the top of the file).

Append to `packages/tri-nutrition/tests/test_garmin_tools.py`:
```python
def test_parse_food_log_from_fixture():
    import json as _json
    from pathlib import Path

    from tri_nutrition.tools.garmin import parse_food_log, parse_hydration

    fixture = Path(__file__).parent / "fixtures" / "mcp" / "get_nutrition_daily_food_log.json"
    payload = _json.loads(fixture.read_text())["result"]
    out = parse_food_log(payload)
    assert out["logged"] is True
    assert (out["kcal"], out["carbs_g"], out["protein_g"], out["fat_g"]) == (213, 2, 18, 15)
    assert out["meals"]["breakfast"] == 213 and out["items"] == ["Eggs (3 large)"]
    assert parse_food_log("No food logged") == {
        "logged": False, "kcal": 0, "carbs_g": 0, "protein_g": 0, "fat_g": 0, "meals": {}, "items": []
    }
    hyd = parse_hydration({"calendarDate": "2026-09-10", "valueInML": 1500.4, "goalInML": 2839.056, "sweatLossInML": None})
    assert hyd == {"date": "2026-09-10", "intake_ml": 1500, "goal_ml": 2839, "sweat_loss_ml": None}
    assert parse_hydration(None) == {"date": None, "intake_ml": None, "goal_ml": None, "sweat_loss_ml": None}


async def test_read_hydration_walks_back_from_yesterday_and_only_filters():
    from tri_nutrition.allowlist import CHECKIN_READ_TOOLS, INTAKE_READ_TOOLS

    g = FakeGarmin(responses={"get_hydration_data": lambda a: {"calendarDate": a["date"], "valueInML": 1000.0, "goalInML": 2500.0, "sweatLossInML": None}})
    tools = {t.name: t for t in make_garmin_read_tools(g, lambda: MONDAY)}
    rows = json.loads(await tools["read_hydration"].ainvoke({"days": 3}))
    assert [r["date"] for r in rows] == ["2026-09-11", "2026-09-12", "2026-09-13"]
    assert rows[0]["intake_ml"] == 1000 and [c[1]["date"] for c in g.calls] == ["2026-09-11", "2026-09-12", "2026-09-13"]
    assert sorted(t.name for t in make_garmin_read_tools(g, lambda: MONDAY, only=INTAKE_READ_TOOLS)) == sorted(INTAKE_READ_TOOLS)
    assert sorted(t.name for t in make_garmin_read_tools(g, lambda: MONDAY, only=CHECKIN_READ_TOOLS)) == sorted(CHECKIN_READ_TOOLS)
    assert json.loads(await {t.name: t for t in make_garmin_read_tools(None, lambda: MONDAY)}["read_hydration"].ainvoke({}))["error"]
```
Update `test_allowlists` in the same file so it also asserts `"get_nutrition_daily_meals" not in GARMIN_SERVER_TOOLS`.

Append to `packages/tri-nutrition/tests/test_repo.py` (it already has an `ndb` fixture and `MON`):
```python
def test_last_target_day(ndb):
    assert repo.last_target_day(ndb) is None
    repo.upsert_targets(ndb, [target(MON), target(MON + timedelta(days=3))])
    assert repo.last_target_day(ndb) == MON + timedelta(days=3)
```
(`target(day)` is the `DayTarget` helper already defined in `test_repo.py`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_store.py packages/tri-nutrition/tests/test_garmin_tools.py packages/tri-nutrition/tests/test_repo.py -q`
Expected: `AttributeError: module 'tri_nutrition.store' has no attribute 'append_fuel_entry'`, `ImportError: cannot import name 'parse_food_log'`, `AttributeError ... 'last_target_day'`.

- [ ] **Step 3: Store, repo, allow-list, state**

Append to `store.py`:
```python
async def append_fuel_entry(
    store: BaseStore, entry: FuelLogEntry, ns: tuple[str, ...] = NAMESPACE
) -> int:
    """Add one entry to the fuel log; returns the log's new length."""
    entries = await get_fuel_log(store, ns)
    entries.append(entry)
    await store.aput(ns, KEY_FUEL_LOG, {"entries": [e.model_dump(mode="json") for e in entries]})
    return len(entries)


async def add_product(store: BaseStore, product: Product, ns: tuple[str, ...] = NAMESPACE) -> bool:
    """Add a product to the library unless one with that name exists; True when added."""
    library = await get_product_library(store, ns)
    if any(p.name == product.name for p in library):
        return False
    await put_product_library(store, [*library, product], ns)
    return True
```

Append to `repo.py`:
```python
def last_target_day(conn: Conn) -> date | None:
    row = conn.execute("select max(day) as d from nutrition_targets").fetchone()
    return row["d"] if row else None
```

Replace the two Garmin lists in `allowlist.py` and add the LangChain-tool-name tuples:
```python
GARMIN_INTAKE_TOOLS = ["get_user_profile", "get_body_composition", "get_nutrition_daily_settings"]
GARMIN_CHECKIN_TOOLS = ["get_body_composition", "get_nutrition_daily_food_log", "get_hydration_data"]
GARMIN_WRITE_TOOLS = ["set_nutrition_daily_settings"]
GARMIN_SERVER_TOOLS = sorted(set(GARMIN_INTAKE_TOOLS + GARMIN_CHECKIN_TOOLS + GARMIN_WRITE_TOOLS))

# LangChain tool names (tools/garmin.py builds every read tool; each node picks its set).
INTAKE_READ_TOOLS = ("read_garmin_profile", "read_body_composition", "read_garmin_nutrition_settings")
CHECKIN_READ_TOOLS = ("read_body_composition", "read_hydration")
```

`graph/state.py`: add after `profile_saved`:
```python
    targets_requested: bool  # set by checkin when propose_target_changes succeeded this run
```

- [ ] **Step 4: Garmin parsing and the hydration tool**

In `tools/garmin.py` add `Collection` to the `collections.abc` import, then add after `BodyCompositionArgs`:
```python
class RecentDaysArgs(BaseModel):
    days: int = Field(default=7, ge=1, le=28, description="how many days back, ending yesterday")
```
Add after `trim_settings`:
```python
_EMPTY_LOG: dict[str, Any] = {
    "logged": False, "kcal": 0, "carbs_g": 0, "protein_g": 0, "fat_g": 0, "meals": {}, "items": []
}


def _int(value: Any) -> int:
    return int(round(float(value))) if value is not None else 0


def parse_food_log(payload: Any) -> dict[str, Any]:
    """One day's logged intake: totals (kcal and grams), kcal per meal, item names."""
    if not isinstance(payload, dict):
        return dict(_EMPTY_LOG)
    total = payload.get("dailyNutritionContent") or {}
    meals: dict[str, int] = {}
    items: list[str] = []
    for detail in payload.get("mealDetails") or []:
        name = str((detail.get("meal") or {}).get("mealName") or "meal").lower()
        content = detail.get("mealNutritionContent") or {}
        if content.get("calories") is not None:
            meals[name] = _int(content["calories"])
        for food in detail.get("loggedFoods") or []:
            fname = (food.get("foodMetaData") or {}).get("foodName")
            if not fname:
                continue
            qty = food.get("servingQty")
            label = str(fname)
            if isinstance(qty, int | float) and float(qty) != 1.0:
                label += f" x{float(qty):g}"
            items.append(label)
    return {
        "logged": bool(items),
        "kcal": _int(total.get("calories")),
        "carbs_g": _int(total.get("carbs")),
        "protein_g": _int(total.get("protein")),
        "fat_g": _int(total.get("fat")),
        "meals": meals,
        "items": items,
    }


def parse_hydration(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}

    def ml(key: str) -> int | None:
        value = data.get(key)
        return int(round(float(value))) if value is not None else None

    return {
        "date": data.get("calendarDate"),
        "intake_ml": ml("valueInML"),
        "goal_ml": ml("goalInML"),
        "sweat_loss_ml": ml("sweatLossInML"),
    }
```
Change the signature to `def make_garmin_read_tools(garmin: ToolCaller | None, today: Callable[[], date], only: Collection[str] | None = None) -> list[BaseTool]:`, add inside it after `read_garmin_nutrition_settings`:
```python
    async def read_hydration(days: int = 7) -> str:
        """Garmin hydration for the last `days` days ending yesterday: date, intake_ml, goal_ml,
        sweat_loss_ml per day (null when nothing was logged that day)."""
        if garmin is None:
            return UNAVAILABLE
        end = today() - timedelta(days=1)
        rows = []
        try:
            for i in range(days):
                day = end - timedelta(days=days - 1 - i)
                payload = await _call("get_hydration_data", {"date": day.isoformat()})
                rows.append({**parse_hydration(payload), "date": day.isoformat()})
        except McpToolError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(rows)
```
and replace the `return [...]` with:
```python
    tools = [
        StructuredTool.from_function(coroutine=read_garmin_profile, name="read_garmin_profile", description=read_garmin_profile.__doc__ or "", args_schema=NoArgs),
        StructuredTool.from_function(coroutine=read_body_composition, name="read_body_composition", description=read_body_composition.__doc__ or "", args_schema=BodyCompositionArgs),
        StructuredTool.from_function(coroutine=read_garmin_nutrition_settings, name="read_garmin_nutrition_settings", description=read_garmin_nutrition_settings.__doc__ or "", args_schema=NoArgs),
        StructuredTool.from_function(coroutine=read_hydration, name="read_hydration", description=read_hydration.__doc__ or "", args_schema=RecentDaysArgs),
    ]
    return [t for t in tools if only is None or t.name in only]
```
Update the module docstring's "only these three read tools exist" to "four".

`graph/nodes/intake.py`: import `INTAKE_READ_TOOLS` from `tri_nutrition.allowlist` and call `make_garmin_read_tools(deps.garmin, deps.today, only=INTAKE_READ_TOOLS)`.

- [ ] **Step 5: Fakes**

In `testing.py`, change `FakeGarmin.call_json` so a callable response is invoked, and add the two defaults:
```python
    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        a = dict(args or {})
        self.calls.append((tool, a))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise McpToolError(tool, "Error updating nutrition settings: boom")
        if tool in self.responses:
            r = self.responses[tool]
            return r(a) if callable(r) else r
        if tool == "set_nutrition_daily_settings":
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
        if tool == "get_hydration_data":
            return {"calendarDate": a.get("date"), "valueInML": 1500.0, "goalInML": 2800.0, "sweatLossInML": None}
        if tool == "get_nutrition_daily_food_log":
            return {
                "mealDate": a.get("date"),
                "dailyNutritionContent": {"calories": 2400, "carbs": 300.0, "protein": 150.0, "fat": 70.0},
                "mealDetails": [
                    {
                        "meal": {"mealName": "BREAKFAST"},
                        "mealNutritionContent": {"calories": 600, "carbs": 80.0, "protein": 30.0, "fat": 15.0},
                        "loggedFoods": [{"foodMetaData": {"foodName": "Oats"}, "servingQty": 1.0}],
                    }
                ],
            }
        return None
```
Append to `testing.py` (imports: `TypedDict` from `typing`, `BaseTool` from `langchain_core.tools`, `BaseStore` from `langgraph.store.base`, `END, START, StateGraph` from `langgraph.graph`):
```python
class _ToolState(TypedDict, total=False):
    out: str


async def call_tool_in_graph(store: BaseStore, tool: BaseTool, args: dict[str, Any]) -> str:
    """Run one tool inside a compiled graph so langgraph.config.get_store() resolves to `store`."""

    async def node(state: _ToolState) -> dict[str, Any]:
        return {"out": await tool.ainvoke(args)}

    g: StateGraph[_ToolState] = StateGraph(_ToolState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    result = await g.compile(store=store).ainvoke({})
    return str(result["out"])
```

- [ ] **Step 6: Run, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition -q` — expected: all pass (`test_intake_saves_profile_and_flags_state` still sees `read_garmin_profile`).
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): fuel log and product store helpers, Garmin food-log and hydration parsing, targets_requested state"
```

---

### Task 2: Check-in tools

**Files:**
- Create: `tools/checkin.py`
- Test: `tests/test_checkin_tools.py`

**Interfaces:**
- `tools.checkin.make_checkin_tools(garmin: ToolCaller | None, connect: ConnectFactory, today: Callable[[], date]) -> list[BaseTool]` returning `read_intake_vs_targets`, `record_fuel_feedback`, `propose_target_changes`.
- `read_intake_vs_targets(days=7) -> JSON {"days": [row...], "by_day_type": {...}, "targets_through": "YYYY-MM-DD" | null, "days_of_targets_remaining": int}`; a row has `day, day_type, logged, logged_kcal, logged_carbs_g, logged_protein_g, logged_fat_g, target_kcal, target_carbs_g, target_protein_g, target_fat_g, delta_kcal, items`. Days run from `today - days` to yesterday.
- `record_fuel_feedback(day, sport, duration_min, carbs_g_per_h, outcome, products=[], note="", tp_workout_id=None, new_product=None) -> JSON {"recorded": true, "entries": n, "product_added": bool | null, "carbs_evidence_g_per_h": int}`; `new_product` joins the library (as `tested: true`) only when `outcome == "ok"`.
- `propose_target_changes(overrides={}, reason) -> JSON {"proposed": true, "overrides": {...}, "reason": "..."}` or `{"error": ...}` for unknown fields, an invalid merged profile, or no profile.
- `tools.checkin.summarize_by_day_type(rows) -> dict[str, dict]` pure.
- `tools.checkin.FuelFeedbackArgs`, `ProposeArgs` (Pydantic arg schemas).

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_checkin_tools.py`:
```python
import contextlib
import json
from datetime import timedelta

import pytest

from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import DayTarget, NutritionProfile
from tri_nutrition.testing import MONDAY, PROFILE_ARGS, FakeGarmin, call_tool_in_graph
from tri_nutrition.tools.checkin import make_checkin_tools, summarize_by_day_type

pytestmark = pytest.mark.db


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


def target(day, day_type="easy", kcal=2500):
    return DayTarget(day=day, day_type=day_type, session_kcal=300, total_kcal=kcal, carbs_g=300, protein_g=150, fat_g=70, fluid_baseline_ml=3000, source="plan")


def tools(ndb, garmin):
    made = make_checkin_tools(garmin, lambda: contextlib.nullcontext(ndb), lambda: MONDAY)
    return {t.name: t for t in made}


def food_log(kcal_by_date):
    def respond(args):
        kcal = kcal_by_date.get(args["date"])
        if kcal is None:
            return "No food logged"
        return {
            "mealDate": args["date"],
            "dailyNutritionContent": {"calories": kcal, "carbs": 250.0, "protein": 120.0, "fat": 60.0},
            "mealDetails": [{"meal": {"mealName": "DINNER"}, "mealNutritionContent": {"calories": kcal}, "loggedFoods": [{"foodMetaData": {"foodName": "Rice bowl"}, "servingQty": 2.0}]}],
        }
    return respond


async def test_read_intake_vs_targets_joins_and_summarizes(ndb, mem_store):
    days = [MONDAY - timedelta(days=n) for n in range(7, 0, -1)]  # 7 days ending yesterday
    repo.upsert_targets(ndb, [target(d, "hard" if i % 2 else "easy") for i, d in enumerate(days)] + [target(MONDAY + timedelta(days=n)) for n in range(4)])
    logged = {days[0].isoformat(): 2000, days[1].isoformat(): 2600, days[6].isoformat(): 2400}
    g = FakeGarmin(responses={"get_nutrition_daily_food_log": food_log(logged)})
    out = json.loads(await call_tool_in_graph(mem_store, tools(ndb, g)["read_intake_vs_targets"], {"days": 7}))
    assert [r["day"] for r in out["days"]] == [d.isoformat() for d in days]
    first = out["days"][0]
    assert first["logged"] and first["logged_kcal"] == 2000 and first["target_kcal"] == 2500
    assert first["delta_kcal"] == -500 and first["items"] == ["Rice bowl x2"]
    assert out["days"][2]["logged"] is False and out["days"][2]["delta_kcal"] is None
    assert out["by_day_type"]["easy"]["days"] == 2 and out["by_day_type"]["easy"]["avg_delta_kcal"] == -300
    assert out["by_day_type"]["hard"] == {"days": 1, "avg_logged_kcal": 2600, "avg_target_kcal": 2500, "avg_delta_kcal": 100, "avg_logged_protein_g": 120, "avg_target_protein_g": 150}
    assert out["targets_through"] == (MONDAY + timedelta(days=3)).isoformat()
    assert out["days_of_targets_remaining"] == 4
    assert [c[1]["date"] for c in g.calls] == [d.isoformat() for d in days]


async def test_read_intake_without_garmin_or_targets(ndb, mem_store):
    out = json.loads(await call_tool_in_graph(mem_store, tools(ndb, None)["read_intake_vs_targets"], {}))
    assert "error" in out
    out = json.loads(await call_tool_in_graph(mem_store, tools(ndb, FakeGarmin())["read_intake_vs_targets"], {"days": 2}))
    assert len(out["days"]) == 2 and out["days"][0]["target_kcal"] is None and out["days"][0]["delta_kcal"] is None
    assert out["targets_through"] is None and out["days_of_targets_remaining"] == 0


def test_summarize_by_day_type_skips_unlogged_and_untyped():
    rows = [
        {"day_type": "easy", "logged": True, "logged_kcal": 2000, "target_kcal": 2500, "delta_kcal": -500, "logged_protein_g": 100, "target_protein_g": 150},
        {"day_type": "easy", "logged": False, "logged_kcal": 0, "target_kcal": 2500, "delta_kcal": None, "logged_protein_g": 0, "target_protein_g": 150},
        {"day_type": None, "logged": True, "logged_kcal": 2000, "target_kcal": None, "delta_kcal": None, "logged_protein_g": 100, "target_protein_g": None},
    ]
    assert summarize_by_day_type(rows) == {"easy": {"days": 1, "avg_logged_kcal": 2000, "avg_target_kcal": 2500, "avg_delta_kcal": -500, "avg_logged_protein_g": 100, "avg_target_protein_g": 150}}


async def test_record_fuel_feedback_appends_and_adds_tested_product(ndb, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    t = tools(ndb, None)["record_fuel_feedback"]
    out = json.loads(await call_tool_in_graph(mem_store, t, {"day": "2026-09-12", "sport": "bike", "duration_min": 150, "carbs_g_per_h": 75, "outcome": "ok", "products": ["Gel", "Chews"], "new_product": {"name": "Chews", "form": "chew", "carbs_g": 24, "sodium_mg": 40}}))
    assert out == {"recorded": True, "entries": 1, "product_added": True, "carbs_evidence_g_per_h": 75}
    library = {p.name: p for p in await S.get_product_library(mem_store)}
    assert library["Chews"].tested is True and library["Chews"].carbs_g == 24
    out = json.loads(await call_tool_in_graph(mem_store, t, {"day": "2026-09-13", "sport": "run", "duration_min": 60, "carbs_g_per_h": 90, "outcome": "gi_upset", "note": "cramps at 40 min", "new_product": {"name": "Mystery", "form": "gel", "carbs_g": 30}}))
    assert out["entries"] == 2 and out["product_added"] is False and out["carbs_evidence_g_per_h"] == 75
    assert "Mystery" not in {p.name for p in await S.get_product_library(mem_store)}
    log = await S.get_fuel_log(mem_store)
    assert [e.outcome for e in log] == ["ok", "gi_upset"] and log[1].note == "cramps at 40 min"
    bad = json.loads(await call_tool_in_graph(mem_store, t, {"day": "2026-09-13", "sport": "run", "duration_min": -5, "carbs_g_per_h": 40, "outcome": "ok"}))
    assert "error" in bad and len(await S.get_fuel_log(mem_store)) == 2


async def test_propose_target_changes_validates_against_profile(ndb, mem_store):
    t = tools(ndb, None)["propose_target_changes"]
    out = json.loads(await call_tool_in_graph(mem_store, t, {"overrides": {"activity_factor": 1.4}, "reason": "x"}))
    assert "error" in out and "no profile" in out["error"]
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    out = json.loads(await call_tool_in_graph(mem_store, t, {"overrides": {"activity_factor": 1.4}, "reason": "on my feet more"}))
    assert out == {"proposed": True, "overrides": {"activity_factor": 1.4}, "reason": "on my feet more"}
    out = json.loads(await call_tool_in_graph(mem_store, t, {"overrides": {}, "reason": "extend horizon"}))
    assert out["proposed"] is True and out["overrides"] == {}
    out = json.loads(await call_tool_in_graph(mem_store, t, {"overrides": {"activity_factor": 1.9}, "reason": "x"}))
    assert "error" in out and "activity_factor" in out["error"]
    out = json.loads(await call_tool_in_graph(mem_store, t, {"overrides": {"shoe_size": 44}, "reason": "x"}))
    assert "error" in out and "shoe_size" in out["error"]
    assert (await S.get_profile(mem_store)).activity_factor == 1.35  # nothing was written
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkin_tools.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.tools.checkin'`.

- [ ] **Step 3: Write the module**

`packages/tri-nutrition/src/tri_nutrition/tools/checkin.py`:
```python
"""Check-in tools: logged intake against targets, the fuel log, and target-change proposals.

record_fuel_feedback writes the Store only (fuel log, and a tested product after an ok outcome).
propose_target_changes writes nothing: it validates the overrides against the saved profile and
returns them; the checkin node carries them into state and the graph regenerates targets for
review, where approve persists them into the profile.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_store
from pydantic import BaseModel, Field, ValidationError

from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import ConnectFactory
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.nutrition.bounds import carbs_evidence
from tri_nutrition.nutrition.models import (
    FuelLogEntry,
    NutritionProfile,
    Outcome,
    Product,
    Sport,
)
from tri_nutrition.tools.garmin import UNAVAILABLE, RecentDaysArgs, parse_food_log

PROFILE_FIELDS = frozenset(NutritionProfile.model_fields)
MAX_ITEMS = 15


class FuelFeedbackArgs(BaseModel):
    day: date
    sport: Sport
    duration_min: int = Field(ge=0)
    carbs_g_per_h: int = Field(ge=0, description="what the athlete actually took per hour")
    outcome: Outcome
    products: list[str] = Field(default_factory=list, description="library product names used")
    note: str = ""
    tp_workout_id: str | None = None
    new_product: Product | None = Field(
        default=None,
        description="a product not yet in the library; added as tested only when outcome is ok",
    )


class ProposeArgs(BaseModel):
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description='profile fields to change, e.g. {"activity_factor": 1.4}; empty to regenerate '
        "the horizon unchanged (extend it)",
    )
    reason: str = Field(description="one sentence the athlete sees at review")


INTAKE_DESCRIPTION = """\
Logged intake (Garmin food log) against the stored daily target for each of the last `days` days
ending yesterday. Per day: day_type, logged (false when nothing was logged), logged_kcal and
logged_carbs_g / protein_g / fat_g, target_kcal and target macros (null when no target was
stored), delta_kcal (logged minus target), and the logged item names. Then by_day_type: averages
over logged days per day type; targets_through: the last day with a stored target;
days_of_targets_remaining: stored target days from today onward. Read this before judging intake."""

FEEDBACK_DESCRIPTION = """\
Record how one session's fueling went: day, sport, duration_min, carbs_g_per_h actually taken,
outcome (ok | gi_upset | bonk | cramps | other), products used, a short note, tp_workout_id when
known. Pass new_product ({name, form, carbs_g, sodium_mg, caffeine_mg} per serving) for a product
not yet in the library; it joins the library only after an ok outcome. Returns the log length and
carbs_evidence_g_per_h, the highest per-hour intake with an ok outcome so far."""

PROPOSE_DESCRIPTION = """\
Propose changes to the profile fields the daily targets are built from (activity_factor 1.2 to
1.5, max_weekly_change_pct up to 1.0, goal, target_weight_kg, target_date, weight_kg, ...) with a
one-sentence reason, or pass empty overrides to regenerate the horizon unchanged. Nothing is
written: the graph rebuilds the targets with the overrides and shows them for approval. Call it
at most once per check-in, after confirming with the athlete when they are present."""


def _error_json(exc: ValidationError) -> str:
    return json.dumps({"error": str(exc)})


def summarize_by_day_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("logged") and r.get("day_type") and r.get("delta_kcal") is not None:
            groups.setdefault(str(r["day_type"]), []).append(r)

    def avg(rs: list[dict[str, Any]], key: str) -> int:
        return round(sum(float(r[key]) for r in rs) / len(rs))

    return {
        day_type: {
            "days": len(rs),
            "avg_logged_kcal": avg(rs, "logged_kcal"),
            "avg_target_kcal": avg(rs, "target_kcal"),
            "avg_delta_kcal": avg(rs, "delta_kcal"),
            "avg_logged_protein_g": avg(rs, "logged_protein_g"),
            "avg_target_protein_g": avg(rs, "target_protein_g"),
        }
        for day_type, rs in groups.items()
    }


def make_checkin_tools(
    garmin: ToolCaller | None, connect: ConnectFactory, today: Callable[[], date]
) -> list[BaseTool]:
    async def read_intake_vs_targets(days: int = 7) -> str:
        if garmin is None:
            return UNAVAILABLE
        now = today()
        end = now - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        with connect() as conn:
            targets = {t.target.day: t.target for t in repo.list_targets(conn, start, end)}
            last = repo.last_target_day(conn)
        rows: list[dict[str, Any]] = []
        for i in range(days):
            day = start + timedelta(days=i)
            try:
                payload = await garmin.call_json(
                    "get_nutrition_daily_food_log", {"date": day.isoformat()}
                )
            except McpToolError as exc:
                return json.dumps({"error": str(exc)})
            logged = parse_food_log(payload)
            t = targets.get(day)
            has_both = t is not None and logged["logged"]
            rows.append(
                {
                    "day": day.isoformat(),
                    "day_type": t.day_type if t else None,
                    "logged": logged["logged"],
                    "logged_kcal": logged["kcal"],
                    "logged_carbs_g": logged["carbs_g"],
                    "logged_protein_g": logged["protein_g"],
                    "logged_fat_g": logged["fat_g"],
                    "target_kcal": t.total_kcal if t else None,
                    "target_carbs_g": t.carbs_g if t else None,
                    "target_protein_g": t.protein_g if t else None,
                    "target_fat_g": t.fat_g if t else None,
                    "delta_kcal": logged["kcal"] - t.total_kcal if has_both and t else None,
                    "items": logged["items"][:MAX_ITEMS],
                }
            )
        remaining = (last - now).days + 1 if last is not None and last >= now else 0
        return json.dumps(
            {
                "days": rows,
                "by_day_type": summarize_by_day_type(rows),
                "targets_through": last.isoformat() if last else None,
                "days_of_targets_remaining": remaining,
            }
        )

    async def record_fuel_feedback(**kwargs: Any) -> str:
        try:
            args = FuelFeedbackArgs(**kwargs)
        except ValidationError as exc:
            return _error_json(exc)
        store = get_store()
        entry = FuelLogEntry(**args.model_dump(exclude={"new_product"}))
        n = await S.append_fuel_entry(store, entry)
        added: bool | None = None
        if args.new_product is not None:
            added = args.outcome == "ok" and await S.add_product(
                store, args.new_product.model_copy(update={"tested": True})
            )
        evidence = carbs_evidence(await S.get_fuel_log(store))
        return json.dumps(
            {
                "recorded": True,
                "entries": n,
                "product_added": added,
                "carbs_evidence_g_per_h": evidence,
            }
        )

    async def propose_target_changes(overrides: dict[str, Any] | None = None, reason: str = "") -> str:
        overrides = dict(overrides or {})
        unknown = sorted(set(overrides) - PROFILE_FIELDS)
        if unknown:
            return json.dumps({"error": f"unknown profile fields: {', '.join(unknown)}"})
        profile = await S.get_profile(get_store())
        if profile is None:
            return json.dumps({"error": "no profile saved; run intake first"})
        try:
            apply_overrides(profile, overrides)
        except ValidationError as exc:
            return _error_json(exc)
        return json.dumps({"proposed": True, "overrides": overrides, "reason": reason})

    return [
        StructuredTool.from_function(
            coroutine=read_intake_vs_targets,
            name="read_intake_vs_targets",
            description=INTAKE_DESCRIPTION,
            args_schema=RecentDaysArgs,
        ),
        StructuredTool.from_function(
            coroutine=record_fuel_feedback,
            name="record_fuel_feedback",
            description=FEEDBACK_DESCRIPTION,
            args_schema=FuelFeedbackArgs,
            handle_validation_error=_error_json,
        ),
        StructuredTool.from_function(
            coroutine=propose_target_changes,
            name="propose_target_changes",
            description=PROPOSE_DESCRIPTION,
            args_schema=ProposeArgs,
            handle_validation_error=_error_json,
        ),
    ]
```

- [ ] **Step 4: Run, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkin_tools.py -q` — expected: 5 passed. If `handle_validation_error` complains about the callable type, mirror exactly what `tools/profile.py` passes (it is the same `_error_json` shape).
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): check-in tools: intake vs targets, fuel feedback, target-change proposals"
```

---

### Task 3: The check-in prompt, the checkin node, and the graph edges

**Files:**
- Modify: `prompts/checkin.py` (replace), `graph/nodes/checkin.py` (replace), `graph/graph.py` (`after_checkin`, docstring), `graph/nodes/targets.py` (clear flags)
- Test: `tests/test_checkin_node.py` (new), `tests/test_graph.py` (add cases)

**Interfaces:**
- `prompts.checkin.CHECKIN_REQUEST = "Run the check-in."`; `render_checkin_prompt(today) -> str`.
- `nodes.checkin.proposal_from_messages(messages) -> dict[str, Any] | None`: the overrides of the last successful `propose_target_changes` tool result (possibly `{}`), else `None`.
- `nodes.checkin.make_checkin_node(deps)`: returns `messages`, plus `profile_saved=True, regenerate_from="checkin"` after a save, plus `targets_requested=True, profile_overrides=<dict or None>, regenerate_from="checkin"` after a proposal.
- `graph.after_checkin(state)`: `"targets"` when `profile_saved` or `targets_requested`, else `END`.
- `nodes.targets`: every return sets `targets_requested: False`; the error/violation return also sets `profile_overrides: None`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_checkin_node.py`:
```python
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition import store as S
from tri_nutrition.graph.nodes.checkin import make_checkin_node, proposal_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.models import NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS

pytestmark = pytest.mark.db
CFG = {"configurable": {"thread_id": "t"}}


def tm(content, name="propose_target_changes"):
    return ToolMessage(content=json.dumps(content), name=name, tool_call_id="c1")


def test_proposal_from_messages():
    assert proposal_from_messages([tm({"proposed": True, "overrides": {"activity_factor": 1.4}, "reason": "r"})]) == {"activity_factor": 1.4}
    assert proposal_from_messages([tm({"proposed": True, "overrides": {}, "reason": "extend"})]) == {}
    assert proposal_from_messages([tm({"error": "unknown profile fields: x"})]) is None
    assert proposal_from_messages([tm({"recorded": True}, name="record_fuel_feedback")]) is None
    assert proposal_from_messages([AIMessage(content="hi")]) is None
    # the last proposal wins
    both = [tm({"proposed": True, "overrides": {"activity_factor": 1.4}}), tm({"error": "x"})]
    assert proposal_from_messages(both) is None


def one_node_graph(node, store):
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("checkin", node)
    g.add_edge(START, "checkin")
    g.add_edge("checkin", END)
    return g.compile(store=store)


async def test_proposal_sets_overrides_and_flags(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[
            tool_call("propose_target_changes", {"overrides": {"activity_factor": 1.5}, "reason": "on my feet all day"}),
            AIMessage(content="Proposed a higher activity factor."),
        ]
    )
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert out["targets_requested"] is True and out["regenerate_from"] == "checkin"
    assert out["profile_overrides"] == {"activity_factor": 1.5}
    assert "profile_saved" not in out or out["profile_saved"] is False
    assert (await S.get_profile(mem_store)).activity_factor == 1.35


async def test_extend_horizon_requests_targets_without_overrides(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[tool_call("propose_target_changes", {"overrides": {}, "reason": "extend horizon"}), AIMessage(content="Extending.")]
    )
    out = await one_node_graph(make_checkin_node(make_deps(model)), mem_store).ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert out["targets_requested"] is True and out["profile_overrides"] is None


async def test_question_turn_sets_nothing(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[AIMessage(content="Rest days are 2400 kcal.")])
    out = await one_node_graph(make_checkin_node(make_deps(model)), mem_store).ainvoke({"messages": [HumanMessage("what do I eat on rest days?")]}, CFG)
    assert "targets_requested" not in out and "profile_overrides" not in out
    assert [type(m).__name__ for m in out["messages"]] == ["HumanMessage", "AIMessage"]


async def test_fuel_feedback_turn_writes_log_and_sets_nothing(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[
            tool_call("record_fuel_feedback", {"day": "2026-09-12", "sport": "bike", "duration_min": 150, "carbs_g_per_h": 70, "outcome": "ok", "products": ["Gel"]}),
            AIMessage(content="Logged."),
        ]
    )
    out = await one_node_graph(make_checkin_node(make_deps(model)), mem_store).ainvoke({"messages": [HumanMessage("the long ride went fine at 70 g/h")]}, CFG)
    assert "targets_requested" not in out
    assert [e.carbs_g_per_h for e in await S.get_fuel_log(mem_store)] == [70]
```

Append to `packages/tri-nutrition/tests/test_graph.py` (imports: `after_checkin` from `tri_nutrition.graph.graph`, `plan_loader`, `build` from `tri_nutrition.nutrition.targets`, `END` from `langgraph.graph`):
```python
def proposal_script(overrides, reason="evidence"):
    return [tool_call("propose_target_changes", {"overrides": overrides, "reason": reason}), AIMessage(content="Proposed.")]


def baseline_kcal(ndb, horizon=3):
    sessions, ctx = plan_loader.load_horizon(ndb, MONDAY, horizon)
    return build(NutritionProfile(**PROFILE_ARGS), sessions, ctx, MONDAY, horizon)[0].total_kcal


async def test_checkin_proposal_regenerates_and_approve_persists_overrides(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=proposal_script({"activity_factor": 1.5}, "on my feet all day")), g, horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    payload = out["__interrupt__"][0].value
    assert payload["changes"][0]["payload"]["calorie_goal"] > baseline_kcal(ndb)
    snap = await graph.aget_state(CFG)
    assert snap.values["profile_overrides"] == {"activity_factor": 1.5}
    assert snap.values["regenerate_from"] == "checkin" and snap.values["targets_requested"] is False
    out = await graph.ainvoke(APPROVE, CFG)
    assert len(g.calls) == 1 and out["pending_changes"] == [] and out["profile_overrides"] is None
    assert (await S.get_profile(mem_store)).activity_factor == 1.5
    assert "profile updated" in out["messages"][-1].content


async def test_checkin_proposal_reject_discards_overrides(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(script=[*proposal_script({"activity_factor": 1.5}), AIMessage(content="Understood, the targets stand.")])
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, model, g, horizon=3)
    await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "I sit most of the day"}), CFG)
    assert "__interrupt__" not in out and g.calls == [] and model.calls == 3
    assert out["profile_overrides"] is None and out["pending_changes"] == []
    assert (await S.get_profile(mem_store)).activity_factor == 1.35
    assert any(isinstance(m, HumanMessage) and "I sit most" in m.content for m in out["messages"])
    assert out["messages"][-1].content.startswith("Understood")


async def test_checkin_extend_horizon_reproposes_today_only_when_changed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=[*proposal_script({}, "extend horizon"), *proposal_script({}, "extend horizon")]), g, horizon=3)
    out = await graph.ainvoke({"messages": [HumanMessage("check in")]}, CFG)
    assert len(out["__interrupt__"][0].value["changes"]) == 1
    await graph.ainvoke(APPROVE, CFG)
    assert repo.list_targets(ndb, MONDAY, MONDAY)[0].written_to_garmin is True
    out = await graph.ainvoke({"messages": [HumanMessage("check in again")]}, CFG)
    assert "__interrupt__" not in out and len(g.calls) == 1  # today already on Garmin with these values
    assert "No nutrition changes to review" in out["messages"][-1].content


def test_after_checkin_routes_on_either_flag():
    assert after_checkin({"profile_saved": True}) == "targets"
    assert after_checkin({"targets_requested": True}) == "targets"
    assert after_checkin({"profile_saved": False, "targets_requested": False}) == END
    assert after_checkin({}) == END
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkin_node.py packages/tri-nutrition/tests/test_graph.py -q`
Expected: `ImportError: cannot import name 'proposal_from_messages'` and, for the graph cases, `KeyError: '__interrupt__'` (the node does not route to targets yet).

- [ ] **Step 3: The prompt**

Replace `packages/tri-nutrition/src/tri_nutrition/prompts/checkin.py`:
```python
"""System prompt for the checkin sub-agent: the periodic check-in, questions, profile edits."""

from datetime import date

CHECKIN_REQUEST = "Run the check-in."  # the fixed message `tri-nutrition check-in` sends


def render_checkin_prompt(today: date) -> str:
    return f"""\
You are an endurance sports nutritionist working with one athlete whose nutrition profile is
saved. Today is {today.isoformat()}. You have read tools (read_nutrition_profile,
read_training_plan, query_training_db, read_body_composition, read_hydration,
read_intake_vs_targets) and two commit tools: record_fuel_feedback (the fuel log) and
propose_target_changes (change the profile fields the targets are built from, or regenerate the
horizon unchanged). Every proposal is shown to the athlete for approval before anything is
written; you never write to Garmin or TrainingPeaks yourself.

When the athlete asks for a check-in, or the message is exactly "{CHECKIN_REQUEST}", run these
steps in order and report each in one or two lines:
1. read_nutrition_profile, then read_training_plan.
2. read_intake_vs_targets(7). Judge intake by day_type over logged days only. Flag under-eating on
   hard and long days (more than 300 kcal or 15% under target), over-eating on rest days, and
   protein below target on most days. Nothing logged means no judgement, say so.
3. read_body_composition(28). Judge the trend over the last 14 and 28 days, not two readings:
   for lose, a loss of at most max_weekly_change_pct per week and not zero; for maintain, drift
   under 1%; for gain_lean, a slow rise with body fat flat.
4. query_training_db: select metric_date, sleep_score, training_readiness, hrv_overnight_avg
   from daily_metrics where metric_date >= current_date - 8 order by metric_date. Flag a
   low-intake day followed by poor readiness or sleep the next day.
5. query_training_db: select workout_date, sport, title, feeling, rpe, comments from workouts
   where workout_date between current_date - 7 and current_date - 1 and (comments is not null or
   feeling is not null) order by workout_date. Comments about the gut, cramps, bonking or nausea
   are fueling feedback: ask what was taken (in a check-in run, use what the comment says) and
   call record_fuel_feedback once per session.
6. When the athlete is present, ask how fueling went on the long and hard sessions since the last
   check-in and record each answer with record_fuel_feedback; a product that worked (outcome ok)
   may be added as new_product.
7. If days_of_targets_remaining is below 7, call propose_target_changes with empty overrides and
   the reason "extend horizon".
8. Decide. Intake consistently under target with falling readiness, weight moving faster than
   the goal rate, or a stalled lose goal are reasons to change the profile: activity_factor (1.2
   to 1.5), max_weekly_change_pct, or goal maintain to pause a deficit. Call
   propose_target_changes once with the overrides and a one-sentence reason. When the evidence is
   thin, say the targets stand and do not call it. Step 7 and step 8 are one call: put the
   overrides and "extend horizon" together.

In chat, confirm a proposal in one line before calling propose_target_changes. In a check-in run
(the message "{CHECKIN_REQUEST}") nobody is there to answer: ask nothing, record what the data
shows, then either propose once or say the targets stand. End with a short report headed
intake, body, recovery, fueling, horizon, decision.

Outside a check-in, answer questions about targets and the plan with read_training_plan and
query_training_db (nutrition_targets: day, day_type, total_kcal, carbs_g, protein_g, fat_g,
notes, written_to_garmin; fuel_plans: kind, day, tp_workout_id, payload, written). When the
athlete changes something about themselves (weight, goal, activity level, restrictions,
products, habits), confirm in one line and call save_nutrition_profile once with the complete
updated profile; targets regenerate and go to review. Use propose_target_changes instead when
the change follows from the data and you can state the reason.

Never diagnose. Language suggesting disordered eating gets the referral: talk to a doctor or a
registered sports dietitian; the goal stays maintain. Be brief."""
```

- [ ] **Step 4: The node**

Replace `packages/tri-nutrition/src/tri_nutrition/graph/nodes/checkin.py`:
```python
"""Checkin node: a sub-agent that runs the check-in, answers questions, and edits the profile.
Its tool results decide the route: a profile save or a target-change proposal sends the run to
targets; anything else ends the turn."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from tri_core.db.sql_tool import make_query_tool
from tri_nutrition.allowlist import CHECKIN_READ_TOOLS
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.llm import make_subagent
from tri_nutrition.graph.nodes.intake import profile_saved_from_messages
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.prompts.checkin import render_checkin_prompt
from tri_nutrition.tools.checkin import make_checkin_tools
from tri_nutrition.tools.garmin import make_garmin_read_tools
from tri_nutrition.tools.plan import make_plan_tool
from tri_nutrition.tools.profile import make_profile_tools


def proposal_from_messages(messages: Sequence[AnyMessage]) -> dict[str, Any] | None:
    """The overrides of the last propose_target_changes result when it succeeded (may be {})."""
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and msg.name == "propose_target_changes":
            try:
                data = json.loads(str(msg.content))
            except json.JSONDecodeError:
                return None
            if isinstance(data, dict) and data.get("proposed"):
                overrides = data.get("overrides")
                return dict(overrides) if isinstance(overrides, dict) else {}
            return None
    return None


def make_checkin_node(deps: GraphDeps) -> Any:
    tools = [
        make_query_tool(deps.db_url),
        make_plan_tool(deps.connect, deps.today, deps.horizon_days),
        *make_garmin_read_tools(deps.garmin, deps.today, only=CHECKIN_READ_TOOLS),
        *make_profile_tools(),
        *make_checkin_tools(deps.garmin, deps.connect, deps.today),
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
        proposal = proposal_from_messages(new)
        if proposal is not None:
            update["targets_requested"] = True
            update["profile_overrides"] = proposal or None
            update["regenerate_from"] = "checkin"
        return update

    return checkin
```

- [ ] **Step 5: Graph and targets**

`graph/graph.py`: change `after_checkin` to
```python
def after_checkin(state: NutritionState) -> str:
    if state.get("profile_saved") or state.get("targets_requested"):
        return "targets"
    return END
```
and the docstring line to `checkin -> targets  (save_nutrition_profile or propose_target_changes was called) | END`.

`graph/nodes/targets.py`, in `targets_node`: add `"targets_requested": False` to both returned dicts, and `"profile_overrides": None` to the error/violation dict only. The docstring of that branch: the proposal is discarded with the violations shown; the athlete adjusts in chat.

- [ ] **Step 6: Run everything, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition -q` — expected: all pass. `test_checkin_profile_edit_regenerates_targets` (Plan 2) is unchanged.
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): check-in sub-agent with intake, body, recovery and fueling steps; proposals regenerate targets"
```

---

### Task 4: The `check-in` command and `/status`

**Files:**
- Modify: `repl.py` (add `checkin_run`), `cli.py` (extract `_ready`, `_open_servers`; add `check-in`; extend `/status`)
- Test: `tests/test_graph.py` (one case for `checkin_run`)

**Interfaces:**
- `repl.checkin_run(graph, *, thread_id, out, approve: bool) -> int`: sends `CHECKIN_REQUEST` (or, when the thread is already paused at `review`, re-prints that review instead), prints the review, returns `0` when nothing is pending or the approve went through, `3` when a change set is left paused. `repl.PAUSED_HINT` is the printed line.
- `cli._ready(settings) -> int | None`: the three readiness checks shared by `chat` and `check-in` (returns an exit code or `None`).
- `cli._open_servers(stack, settings, *, no_live) -> tuple[ToolCaller | None, ToolCaller | None]`.
- `tri-nutrition check-in [--yes] [--no-sync] [--no-live]`: exit codes `0`, `3` (paused), `2` (not configured).

- [ ] **Step 1: Write the failing test**

Append to `packages/tri-nutrition/tests/test_graph.py` (import `checkin_run` from `tri_nutrition.repl`):
```python
async def test_checkin_run_pauses_then_approves_on_second_run(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=proposal_script({}, "extend horizon")), g, horizon=3)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=False) == 3
    text = "".join(printed)
    assert "approve / reject" in text and "paused" in text and g.calls == []
    printed.clear()
    assert await checkin_run(graph, thread_id="nutrition", out=printed.append, approve=True) == 0
    assert "already waiting at review" in "".join(printed) and len(g.calls) == 1
    assert (await graph.aget_state(CFG)).next == ()


async def test_checkin_run_returns_zero_when_nothing_proposed(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    graph = make_graph(make_deps, mem_store, ScriptedChatModel(script=[AIMessage(content="Targets stand.")]), FakeGarmin(), horizon=3)
    assert await checkin_run(graph, thread_id="nutrition", out=lambda s: None, approve=True) == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-nutrition/tests/test_graph.py -q -k checkin_run`
Expected: `ImportError: cannot import name 'checkin_run'`.

- [ ] **Step 3: `checkin_run`**

Append to `repl.py` (import `CHECKIN_REQUEST` from `tri_nutrition.prompts.checkin`):
```python
PAUSED_HINT = (
    "paused at review; run `tri-nutrition check-in --yes` to approve, or `tri-nutrition chat` "
    "to answer approve / reject <note> / edit"
)


async def checkin_run(graph: Any, *, thread_id: str, out: Out, approve: bool) -> int:
    """One unattended check-in. 0: nothing pending or approved; 3: a change set waits at review."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    if snap.next == ("review",):
        values = snap.values or {}
        pending = {
            "summary": values.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in values.get("pending_changes") or []],
            "last_error": values.get("last_error"),
        }
        out("a change set is already waiting at review:\n" + render_review(pending) + "\n")
    else:
        printer = await run_turn(graph, {"messages": [HumanMessage(CHECKIN_REQUEST)]}, thread_id, out)
        if printer.interrupt is None:
            return 0
        out("\n" + render_review(printer.interrupt) + "\n")
    if not approve:
        out(PAUSED_HINT + "\n")
        return 3
    printer = await run_turn(graph, Command(resume={"action": "approve"}), thread_id, out)
    return 0 if printer.interrupt is None else 3
```

- [ ] **Step 4: CLI**

In `cli.py`:

1. Add module-level helpers after `_out`:
```python
def _ready(settings: Any) -> int | None:
    """Exit code when chat or check-in cannot start, else None."""
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import SETUP_HINT, checkpointer_ready

    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        return 2
    if not S.store_ready(settings.database_url):
        console.print(S.STORE_SETUP_HINT, style="red")
        return 2
    return None


async def _open_servers(stack: Any, settings: Any, *, no_live: bool) -> tuple[Any, Any]:
    """Start the Garmin and TrainingPeaks MCP servers; a dead server is None and its writes
    are held pending by apply."""
    from tri_core.mcp.client import McpToolClient
    from tri_core.mcp.servers import garmin_spec, trainingpeaks_spec
    from tri_nutrition.allowlist import GARMIN_SERVER_TOOLS

    if no_live:
        return None, None
    garmin = None
    try:
        garmin = await asyncio.wait_for(
            stack.enter_async_context(
                McpToolClient(garmin_spec(settings, enabled_tools=GARMIN_SERVER_TOOLS))
            ),
            timeout=SERVER_START_TIMEOUT_S,
        )
        _out("garmin: connected (writes happen only after you approve)\n")
    except Exception as exc:  # the run still works; apply holds Garmin changes pending
        _out(
            f"warning: garmin MCP server unavailable ({type(exc).__name__}: {exc}); "
            "Garmin reads are unavailable and Garmin writes will be held pending\n"
        )
    tp = None
    try:
        tp = await asyncio.wait_for(
            stack.enter_async_context(McpToolClient(trainingpeaks_spec(settings))),
            timeout=SERVER_START_TIMEOUT_S,
        )
        _out("trainingpeaks: connected (notes are written only after you approve)\n")
    except Exception as exc:  # note changes are held pending until the server is back
        _out(
            f"warning: trainingpeaks MCP server unavailable ({type(exc).__name__}: {exc}); "
            "note changes will be held pending\n"
        )
    return garmin, tp
```
2. In `_chat`: replace the three inline readiness checks with `code = _ready(settings)` / `if code is not None: raise typer.Exit(code=code)`, and replace the two server blocks with `garmin, tp = await _open_servers(stack, settings, no_live=no_live)`. Drop the now-unused imports.
3. In `cmd_status`, replace the `targets from today` line and add a Store line:
```python
            through = stored[-1].target.day.isoformat() if stored else "-"
            fuel_log = await S.get_fuel_log(store)
            library = await S.get_product_library(store)
            lines = [
                f"goal: {profile.goal}; weight {profile.weight_kg:g} kg; body fat {body_fat} %",
                f"targets from today: {len(stored)} days through {through} "
                f"({len(written)} written to Garmin)",
                f"fuel plans from today: {len(plans)} "
                f"({len(plans_written)} written to TrainingPeaks)",
                f"fuel log: {len(fuel_log)} entries; product library: {len(library)} products",
                f"last write: {last.isoformat(timespec='minutes') if last else 'never'}",
                f"next node: {snap.next or '-'}",
            ]
```
4. Add the command after `today`:
```python
@app.command(name="check-in")
def check_in(
    yes: bool = typer.Option(False, "--yes", help="Approve the proposed changes without asking"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Do not run `tri sync` first"),
    no_live: bool = typer.Option(False, "--no-live", help="Do not start the MCP servers"),
) -> None:
    """Sync, run the check-in on the nutrition thread, and pause at review (exit code 3) or
    approve with --yes."""
    raise typer.Exit(code=asyncio.run(_check_in(yes=yes, no_sync=no_sync, no_live=no_live)))


async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from contextlib import AsyncExitStack

    from tri_core.sync.runner import run_sync
    from tri_nutrition import store as S
    from tri_nutrition.graph.checkpointer import open_checkpointer
    from tri_nutrition.graph.deps import make_deps
    from tri_nutrition.graph.graph import build_graph
    from tri_nutrition.graph.llm import make_model
    from tri_nutrition.repl import checkin_run

    settings = get_nutrition_settings()
    code = _ready(settings)
    if code is not None:
        return code
    if not no_sync and not no_live:
        report = await run_sync(settings, log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("sync had errors; checking in against what is stored\n")
    async with AsyncExitStack() as stack:
        garmin, tp = await _open_servers(stack, settings, no_live=no_live)
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        store = await stack.enter_async_context(S.open_store(settings.database_url))
        graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)
        return await checkin_run(graph, thread_id=THREAD_ID, out=_out, approve=yes)
```
Update the module docstring: `chat, today, check-in, reset (eval arrives in Task 5)`.

- [ ] **Step 5: Run everything, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition -q` and `uv run tri-nutrition --help` (expect `check-in` listed).
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): check-in command; shared server start-up; /status shows horizon end and fuel log"
```

---

### Task 5: `FuelPlanner`, the LangSmith dataset, evaluators and the `eval` command

**Files:**
- Modify: `graph/nodes/fuel.py` (extract `FuelPlanner`), `prompts/fuel.py` (`PROMPT_VERSION`), `pyproject.toml`, `cli.py` (`eval`)
- Create: `evals/__init__.py`, `evals/cases.py`, `evals/target.py`, `evals/evaluators.py`, `evals/run.py`
- Test: `tests/test_evals.py`

**Interfaces:**
- `nodes.fuel.FuelPlanner(model)`: `async session(profile, library, fuel_log, session, target, other_caffeine_mg, config=None) -> tuple[SessionFuel, list[str]]` and `async race(profile, library, fuel_log, ctx, target, config=None) -> tuple[RaceFuelPlan, list[str]]`, each one call plus one validated retry, ids copied from the session.
- `prompts.fuel.PROMPT_VERSION = "1"` (bump when either fueling prompt changes; it names the experiment).
- `evals.cases.EvalCase(name, profile, sessions, ctx, fuel_log, today="2026-09-14")` with `.inputs() -> dict`; `evals.cases.CASES: list[EvalCase]` (five).
- `evals.target.parse_inputs(inputs) -> tuple[NutritionProfile, list[Session], PlanContext, list[FuelLogEntry], date]`; `run_case(planner, inputs, horizon_days=7) -> dict` with keys `targets, target_violations, fuels [{session, fuel, violations}], race ({plan, violations} | None)`; `make_target(model) -> Callable[[dict], Awaitable[dict]]`.
- `evals.evaluators.targets_within_bounds(inputs, outputs) -> dict`, `fuel_within_bounds(inputs, outputs) -> dict` (both `{"key", "score" 0|1, "comment"}`); `FuelJudgement`; `make_fuel_judge(model)` returns `async fuel_respects_profile(inputs, outputs) -> dict`.
- `evals.run.DATASET_NAME = "tri_nutrition_fueling"`; `case_examples() -> list[dict]`; `ensure_dataset(client, *, recreate=False) -> None`; `pass_rates(rows) -> dict[str, float]`; `render_pass_rates(rates, n) -> str`; `async run_eval(settings, model, *, judge, prefix, recreate, log) -> dict[str, float]`.
- `tri-nutrition eval [--judge/--no-judge] [--prefix NAME] [--recreate-dataset]`: exit 0 when every pass rate is 1.0, else 1; 2 when keys are missing.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_evals.py`:
```python
from datetime import date

from langsmith.evaluation import EvaluationResult

from tri_core.testing import ScriptedChatModel, tool_call
from tri_nutrition.evals.cases import CASES
from tri_nutrition.evals.evaluators import fuel_within_bounds, make_fuel_judge, targets_within_bounds
from tri_nutrition.evals.run import DATASET_NAME, case_examples, pass_rates, render_pass_rates
from tri_nutrition.evals.target import make_target, parse_inputs
from tri_nutrition.graph.nodes.fuel import qualifies, race_due
from tri_nutrition.testing import race_plan_json, session_fuel_json


def case(name):
    return next(c for c in CASES if c.name == name)


def fuel_calls(c, **over):
    _, sessions, _, _, _ = parse_inputs(c.inputs())
    return [
        tool_call("SessionFuel", session_fuel_json(s.tp_workout_id or "", s.day, **over))
        for s in sessions
        if qualifies(s)
    ]


def test_cases_are_valid_and_each_has_a_qualifying_session():
    assert len({c.name for c in CASES}) == len(CASES) >= 5
    for c in CASES:
        profile, sessions, ctx, fuel_log, today = parse_inputs(c.inputs())
        assert today == date(2026, 9, 14) and all(0 <= (s.day - today).days < 7 for s in sessions)
        assert any(qualifies(s) for s in sessions)
        assert profile.tested_products, c.name
    assert race_due(parse_inputs(case("race_week_olympic").inputs())[2], date(2026, 9, 14))
    examples = case_examples()
    assert len(examples) == len(CASES) and examples[0]["metadata"]["case"] == CASES[0].name
    assert DATASET_NAME == "tri_nutrition_fueling"


async def test_target_runs_a_week_and_code_evaluators_pass():
    c = case("maintain_build_week")
    calls = fuel_calls(c)
    model = ScriptedChatModel(script=calls)
    out = await make_target(model)(c.inputs())
    assert model.calls == len(calls) and len(out["fuels"]) == len(calls)
    assert len(out["targets"]) == 7 and out["target_violations"] == [] and out["race"] is None
    assert all(f["violations"] == [] for f in out["fuels"])
    assert targets_within_bounds(c.inputs(), out) == {"key": "targets_within_bounds", "score": 1, "comment": "ok"}
    assert fuel_within_bounds(c.inputs(), out)["score"] == 1


async def test_race_case_plans_the_race_and_retries_bad_fuel():
    c = case("race_week_olympic")
    _, _, ctx, _, _ = parse_inputs(c.inputs())
    bad = fuel_calls(c, products=["Mystery"])
    model = ScriptedChatModel(script=[*bad, *bad, tool_call("RaceFuelPlan", race_plan_json(ctx.event_date))])
    out = await make_target(model)(c.inputs())
    assert out["race"] is not None and out["race"]["violations"] == []
    assert all(any("Mystery" in v for v in f["violations"]) for f in out["fuels"])
    res = fuel_within_bounds(c.inputs(), out)
    assert res["score"] == 0 and "Mystery" in res["comment"]


async def test_judge_uses_the_model_only_when_there_are_notes():
    c = case("vegan_lose_gluten_free")
    out = await make_target(ScriptedChatModel(script=fuel_calls(c, products=["Oat bar"])))(c.inputs())
    judge_model = ScriptedChatModel(script=[tool_call("FuelJudgement", {"respects_restrictions": False, "only_library_products": True, "problems": ["2026-09-15 pre: banana, a listed dislike"]})])
    res = await make_fuel_judge(judge_model)(c.inputs(), out)
    assert res["key"] == "fuel_respects_profile" and res["score"] == 0 and "banana" in res["comment"]
    empty = await make_fuel_judge(ScriptedChatModel(script=[]))(c.inputs(), {"fuels": [], "race": None})
    assert empty["score"] == 1


def test_pass_rates_and_rendering():
    rows = [
        {"evaluation_results": {"results": [EvaluationResult(key="a", score=1), EvaluationResult(key="b", score=0)]}},
        {"evaluation_results": {"results": [EvaluationResult(key="a", score=1), EvaluationResult(key="b", score=1), EvaluationResult(key="c", score=None)]}},
    ]
    rates = pass_rates(rows)
    assert rates == {"a": 1.0, "b": 0.5}
    text = render_pass_rates(rates, 2)
    assert "a" in text and "100%" in text and "50%" in text and "2 examples" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_evals.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_nutrition.evals'`.

- [ ] **Step 3: Declare langsmith, add `PROMPT_VERSION`, extract `FuelPlanner`**

`pyproject.toml`: add `"langsmith>=0.12,<1",` after `"langgraph-checkpoint-postgres>=3.1,<4",`. Run `uv lock` (no new download is expected; `uv sync` if the lock changes).

`prompts/fuel.py`: add after the imports `PROMPT_VERSION = "1"  # bump when FUEL_SYSTEM or RACE_SYSTEM changes; names the eval experiment`.

`graph/nodes/fuel.py`: replace the two `fuel_one` / `race_one` closures with a class placed after `_needs_write` (imports: `TypeVar` from `typing`, `BaseChatModel, LanguageModelInput` from `langchain_core.language_models`, `Runnable` from `langchain_core.runnables`, `BaseModel` from `pydantic`, `DayTarget, FuelLogEntry, NutritionProfile, Product` from models):
```python
T = TypeVar("T", bound=BaseModel)


class FuelPlanner:
    """The two structured-output calls with their validate-and-retry loop. Shared by the fuel
    node and the LangSmith evaluation target, which has no database."""

    def __init__(self, model: BaseChatModel) -> None:
        self._session: Runnable[LanguageModelInput, Any] = model.with_structured_output(SessionFuel)
        self._race: Runnable[LanguageModelInput, Any] = model.with_structured_output(RaceFuelPlan)

    @staticmethod
    async def _ask(
        runnable: Runnable[LanguageModelInput, Any],
        system: str,
        prompt: str,
        cls: type[T],
        config: RunnableConfig | None,
    ) -> T:
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(prompt)], config=config)
        assert isinstance(out, cls)
        return out

    async def session(
        self,
        profile: NutritionProfile,
        library: list[Product],
        fuel_log: list[FuelLogEntry],
        session: Session,
        target: DayTarget | None,
        other_caffeine_mg: int = 0,
        config: RunnableConfig | None = None,
    ) -> tuple[SessionFuel, list[str]]:
        ids = {"tp_workout_id": session.tp_workout_id or "", "day": session.day}
        prompt = render_session_prompt(profile, library, fuel_log, session, target, None, None)
        plan = (await self._ask(self._session, FUEL_SYSTEM, prompt, SessionFuel, config)).model_copy(update=ids)
        violations = validate_fuel(plan, profile, library, fuel_log, other_caffeine_mg)
        if violations:
            retry = render_session_prompt(profile, library, fuel_log, session, target, violations, plan)
            plan = (await self._ask(self._session, FUEL_SYSTEM, retry, SessionFuel, config)).model_copy(update=ids)
            violations = validate_fuel(plan, profile, library, fuel_log, other_caffeine_mg)
        return plan, violations

    async def race(
        self,
        profile: NutritionProfile,
        library: list[Product],
        fuel_log: list[FuelLogEntry],
        ctx: PlanContext,
        target: DayTarget | None,
        config: RunnableConfig | None = None,
    ) -> tuple[RaceFuelPlan, list[str]]:
        prompt = render_race_prompt(profile, library, fuel_log, ctx, target, None, None)
        plan = await self._ask(self._race, RACE_SYSTEM, prompt, RaceFuelPlan, config)
        violations = validate_race(plan, profile, library, fuel_log)
        if violations:
            retry = render_race_prompt(profile, library, fuel_log, ctx, target, violations, plan)
            plan = await self._ask(self._race, RACE_SYSTEM, retry, RaceFuelPlan, config)
            violations = validate_race(plan, profile, library, fuel_log)
        return plan, violations
```
In `make_fuel_node`, replace the model setup with `planner = FuelPlanner(deps.model)`, the session loop body with
```python
            plan, violations = await planner.session(
                profile, library, fuel_log, s, target, other, cfg
            )
```
(delete the `ids`, `prompt`, `retry` lines there), and the race block with
```python
            plan_r, rv = await planner.race(profile, library, fuel_log, ctx, target, cfg)
```
Everything after each call (caffeine tally, upsert, changes) stays as it is. `test_fuel_node.py` must pass unchanged.

- [ ] **Step 4: The cases**

`packages/tri-nutrition/src/tri_nutrition/evals/__init__.py`: `"""LangSmith dataset, evaluators and runner for the fueling prompts (spec §12)."""`

`packages/tri-nutrition/src/tri_nutrition/evals/cases.py`:
```python
"""The (profile, training week) cases behind the LangSmith dataset. Plain JSON so the dataset can
be re-created from code; `today` is fixed so runs are comparable across prompt versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tri_nutrition.testing import PROFILE_ARGS

TODAY = "2026-09-14"  # a Monday
D = [f"2026-09-{14 + i:02d}" for i in range(7)]  # D[0] .. D[6], Monday to Sunday

GEL = {"name": "Gel", "form": "gel", "carbs_g": 25, "sodium_mg": 50}
DRINK = {"name": "Drink mix", "form": "drink", "carbs_g": 40, "sodium_mg": 400}
OAT_BAR = {"name": "Oat bar", "form": "bar", "carbs_g": 30, "sodium_mg": 100}
CHEWS = {"name": "Chews", "form": "chew", "carbs_g": 24, "sodium_mg": 40, "caffeine_mg": 25}


def session(day: str, sport: str, minutes: int, intensity: str, wid: str, tss: float | None = None) -> dict[str, Any]:
    return {
        "day": day,
        "sport": sport,
        "duration_min": minutes,
        "intensity": intensity,
        "tp_workout_id": wid,
        "title": f"{sport} {minutes}",
        "planned_tss": tss,
    }


def profile(**over: Any) -> dict[str, Any]:
    return {**PROFILE_ARGS, **over}


@dataclass(frozen=True)
class EvalCase:
    name: str
    profile: dict[str, Any]
    sessions: list[dict[str, Any]]
    ctx: dict[str, Any]
    fuel_log: list[dict[str, Any]] = field(default_factory=list)
    today: str = TODAY

    def inputs(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "sessions": self.sessions,
            "ctx": self.ctx,
            "fuel_log": self.fuel_log,
            "today": self.today,
        }


PLAN = {"source": "plan", "ftp_watts": 250, "phases": {TODAY: "build"}}

CASES: list[EvalCase] = [
    EvalCase(
        name="maintain_build_week",
        profile=profile(),
        sessions=[
            session(D[0], "bike", 120, "endurance", "w1", 100),
            session(D[2], "run", 45, "threshold", "w2", 60),
            session(D[4], "swim", 45, "endurance", "w3", 40),
            session(D[5], "bike", 180, "endurance", "w4", 170),
            session(D[6], "run", 90, "endurance", "w5", 80),
        ],
        ctx=PLAN,
    ),
    EvalCase(
        name="vegan_lose_gluten_free",
        profile=profile(
            weight_kg=70, body_fat_pct=20, sex="f", goal="lose", target_weight_kg=66,
            target_date="2026-12-01", pattern="vegan", restrictions=["gluten"],
            dislikes=["bananas"], tested_products=[OAT_BAR, DRINK],
        ),
        sessions=[
            session(D[0], "bike", 100, "endurance", "w1", 70),
            session(D[2], "run", 40, "threshold", "w2", 55),
            session(D[5], "run", 80, "endurance", "w3", 70),
        ],
        ctx={**PLAN, "ftp_watts": 190},
    ),
    EvalCase(
        name="race_week_olympic",
        profile=profile(),
        sessions=[
            session(D[0], "bike", 60, "endurance", "w1", 40),
            session(D[2], "run", 30, "race", "w2", 35),
            session(D[6], "brick", 150, "race", "w3", 180),
        ],
        ctx={
            "source": "plan",
            "ftp_watts": 250,
            "event_date": D[6],
            "event_priority": "A",
            "event_name": "City Tri",
            "goal_type": "olympic",
            "phases": {TODAY: "race"},
        },
        fuel_log=[
            {"day": "2026-09-05", "sport": "bike", "duration_min": 150, "carbs_g_per_h": 75, "products": ["Gel"], "outcome": "ok"},
        ],
    ),
    EvalCase(
        name="no_caffeine_reflux",
        profile=profile(caffeine_mg_per_day=0, gi_issues=["reflux"], tested_products=[GEL, DRINK]),
        sessions=[
            session(D[1], "run", 50, "vo2", "w1", 65),
            session(D[3], "bike", 150, "endurance", "w2", 130),
            session(D[5], "brick", 120, "tempo", "w3", 120),
        ],
        ctx=PLAN,
    ),
    EvalCase(
        name="gut_trained_ironman_base",
        profile=profile(weight_kg=85, tested_products=[GEL, DRINK, CHEWS], known_sweat_rate_l_per_h=1.2),
        sessions=[
            session(D[1], "swim", 90, "endurance", "w1", 60),
            session(D[3], "run", 120, "endurance", "w2", 110),
            session(D[5], "bike", 240, "endurance", "w3", 200),
            session(D[6], "run", 100, "endurance", "w4", 90),
        ],
        ctx={**PLAN, "goal_type": "ironman", "phases": {TODAY: "base"}},
        fuel_log=[
            {"day": "2026-08-29", "sport": "bike", "duration_min": 240, "carbs_g_per_h": 90, "products": ["Gel", "Drink mix"], "outcome": "ok"},
            {"day": "2026-09-05", "sport": "bike", "duration_min": 240, "carbs_g_per_h": 100, "products": ["Gel", "Drink mix", "Chews"], "outcome": "ok"},
        ],
    ),
]
```

- [ ] **Step 5: The target**

`packages/tri-nutrition/src/tri_nutrition/evals/target.py`:
```python
"""The function under evaluation: one week of targets (Python) and the fueling plans (model)
for a (profile, training week) input. No database, no Store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel

from tri_nutrition.graph.nodes.fuel import FuelPlanner, qualifies, race_due
from tri_nutrition.nutrition.bounds import validate_targets
from tri_nutrition.nutrition.models import FuelLogEntry, NutritionProfile, PlanContext, Session
from tri_nutrition.nutrition.targets import build

HORIZON_DAYS = 7


def parse_inputs(
    inputs: dict[str, Any],
) -> tuple[NutritionProfile, list[Session], PlanContext, list[FuelLogEntry], date]:
    return (
        NutritionProfile.model_validate(inputs["profile"]),
        [Session.model_validate(s) for s in inputs["sessions"]],
        PlanContext.model_validate(inputs["ctx"]),
        [FuelLogEntry.model_validate(e) for e in inputs.get("fuel_log", [])],
        date.fromisoformat(inputs["today"]),
    )


async def run_case(
    planner: FuelPlanner, inputs: dict[str, Any], horizon_days: int = HORIZON_DAYS
) -> dict[str, Any]:
    profile, sessions, ctx, fuel_log, today = parse_inputs(inputs)
    targets = build(profile, sessions, ctx, today, horizon_days)
    by_day = {t.day: t for t in targets}
    library = list(profile.tested_products)
    fuels: list[dict[str, Any]] = []
    caffeine: dict[date, int] = {}
    for s in sessions:
        if not qualifies(s):
            continue
        other = caffeine.get(s.day, 0)
        plan, violations = await planner.session(
            profile, library, fuel_log, s, by_day.get(s.day), other
        )
        caffeine[s.day] = other + (plan.caffeine_mg or 0)
        fuels.append(
            {
                "session": s.model_dump(mode="json"),
                "fuel": plan.model_dump(mode="json"),
                "violations": violations,
            }
        )
    race: dict[str, Any] | None = None
    if race_due(ctx, today) and ctx.event_date is not None:
        plan_r, rv = await planner.race(profile, library, fuel_log, ctx, by_day.get(ctx.event_date))
        race = {"plan": plan_r.model_dump(mode="json"), "violations": rv}
    return {
        "targets": [t.model_dump(mode="json") for t in targets],
        "target_violations": validate_targets(targets, profile),
        "fuels": fuels,
        "race": race,
    }


def make_target(model: BaseChatModel) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    planner = FuelPlanner(model)

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(planner, inputs)

    return target
```

- [ ] **Step 6: The evaluators**

`packages/tri-nutrition/src/tri_nutrition/evals/evaluators.py`:
```python
"""Evaluators over the target's output: two code checks that re-run the bounds, and an LLM
judge for what the bounds cannot see (restrictions and dislikes in the prose)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from tri_nutrition.evals.target import parse_inputs
from tri_nutrition.nutrition.bounds import validate_fuel, validate_race, validate_targets
from tri_nutrition.nutrition.models import DayTarget, RaceFuelPlan, SessionFuel

Evaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
AsyncEvaluator = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


def _result(key: str, ok: bool, problems: list[str]) -> dict[str, Any]:
    return {"key": key, "score": int(ok), "comment": "; ".join(problems) or "ok"}


def targets_within_bounds(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    profile, *_ = parse_inputs(inputs)
    targets = [DayTarget.model_validate(t) for t in outputs.get("targets", [])]
    return _result("targets_within_bounds", not (v := validate_targets(targets, profile)), v)


def fuel_within_bounds(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    profile, _, _, fuel_log, _ = parse_inputs(inputs)
    library = list(profile.tested_products)
    problems: list[str] = []
    caffeine: dict[date, int] = {}
    for item in outputs.get("fuels", []):
        fuel = SessionFuel.model_validate(item["fuel"])
        other = caffeine.get(fuel.day, 0)
        problems += [f"{fuel.day} {fuel.tp_workout_id}: {v}" for v in validate_fuel(fuel, profile, library, fuel_log, other)]
        caffeine[fuel.day] = other + (fuel.caffeine_mg or 0)
    race = outputs.get("race")
    if race:
        plan = RaceFuelPlan.model_validate(race["plan"])
        problems += [f"race: {v}" for v in validate_race(plan, profile, library, fuel_log)]
    return _result("fuel_within_bounds", not problems, problems)


class FuelJudgement(BaseModel):
    respects_restrictions: bool = Field(
        description="every note honours the dietary pattern, restrictions, dislikes and GI history"
    )
    only_library_products: bool = Field(
        description="no named sports product outside the library appears anywhere in the notes; "
        "plain food and water are always fine"
    )
    problems: list[str] = Field(description="one line per problem: the day and the offending text")


JUDGE_SYSTEM = """\
You audit fueling notes written for one athlete. You are given the athlete's dietary pattern,
restrictions, dislikes, GI history and caffeine habit, the product library, and each note (pre,
products, post, note text) plus the race note when there is one. Return a FuelJudgement.
respects_restrictions is true only when every note honours the pattern (a vegan note names no
animal food), every restriction (gluten: no oats unless labelled gluten-free, no bread, no wheat
bars), every dislike, and the GI history (reflux: no large, fatty or acidic pre-session meal;
caffeine_mg_per_day 0: no caffeine anywhere). only_library_products is true only when every
named sports product (gel, chew, drink mix, bar, or brand) is in the library; plain foods and
water never count against it. Be literal: judge the text, not the intent."""


def render_judge_prompt(inputs: dict[str, Any], outputs: dict[str, Any]) -> str:
    profile = inputs["profile"]
    keys = ("pattern", "restrictions", "dislikes", "gi_issues", "caffeine_mg_per_day", "constraints")
    library = [p["name"] for p in profile.get("tested_products", [])]
    parts = [
        "Athlete: " + json.dumps({k: profile.get(k) for k in keys}),
        "Product library: " + (", ".join(library) or "empty"),
    ]
    for item in outputs.get("fuels", []):
        s, f = item["session"], item["fuel"]
        parts.append(
            f"Session {s['day']} {s['sport']} {s['duration_min']} min, {s['intensity']}:\n"
            f"  pre: {f['pre']}\n  products: {', '.join(f['products']) or '-'}\n"
            f"  post: {f['post']}\n  note: {f['note_text']}"
        )
    race = outputs.get("race")
    if race:
        parts.append("Race note:\n" + str(race["plan"]["note_text"]))
    return "\n\n".join(parts)


def make_fuel_judge(model: BaseChatModel) -> AsyncEvaluator:
    judge = model.with_structured_output(FuelJudgement)

    async def fuel_respects_profile(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        if not outputs.get("fuels") and not outputs.get("race"):
            return _result("fuel_respects_profile", True, [])
        out = await judge.ainvoke(
            [SystemMessage(JUDGE_SYSTEM), HumanMessage(render_judge_prompt(inputs, outputs))]
        )
        assert isinstance(out, FuelJudgement)
        ok = out.respects_restrictions and out.only_library_products
        return _result("fuel_respects_profile", ok, out.problems)

    return fuel_respects_profile
```

- [ ] **Step 7: The runner and the command**

`packages/tri-nutrition/src/tri_nutrition/evals/run.py`:
```python
"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; every model call goes through the normal fueling prompts, so an experiment
is named by PROMPT_VERSION and the pass rate per evaluator is what changes between versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

from tri_core.config import Settings
from tri_nutrition.evals.cases import CASES
from tri_nutrition.evals.evaluators import fuel_within_bounds, make_fuel_judge, targets_within_bounds
from tri_nutrition.evals.target import make_target
from tri_nutrition.prompts.fuel import PROMPT_VERSION

DATASET_NAME = "tri_nutrition_fueling"
DATASET_DESCRIPTION = (
    "(profile, training week) pairs for the tri-nutrition fueling prompts. Evaluators: "
    "validate_targets, validate_fuel / validate_race, and an LLM judge for restrictions."
)


def case_examples() -> list[dict[str, Any]]:
    return [{"inputs": c.inputs(), "outputs": {}, "metadata": {"case": c.name}} for c in CASES]


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples())


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:24} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


async def run_eval(
    settings: Settings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [targets_within_bounds, fuel_within_bounds]
    if judge:
        evaluators.append(make_fuel_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"fuel-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model},
        client=client,
        max_concurrency=2,
    )
    rows = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
```

`cli.py`: add after `check-in`:
```python
@app.command(name="eval")
def eval_cmd(
    judge: bool = typer.Option(True, "--judge/--no-judge", help="Also run the LLM judge"),
    prefix: str | None = typer.Option(None, "--prefix", help="Experiment name prefix (default fuel-v<PROMPT_VERSION>)"),
    recreate: bool = typer.Option(False, "--recreate-dataset", help="Delete and re-create the LangSmith dataset from the cases in code"),
) -> None:
    """Run the fueling prompts over the LangSmith dataset and print the pass rate per evaluator
    (exit 1 when any evaluator is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(judge=judge, prefix=prefix, recreate=recreate)))


async def _eval(*, judge: bool, prefix: str | None, recreate: bool) -> int:
    from tri_nutrition.evals.run import run_eval
    from tri_nutrition.graph.llm import make_model

    settings = get_nutrition_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings, make_model(settings), judge=judge, prefix=prefix, recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1
```
Update the `cli.py` module docstring to list `chat, today, check-in, eval, reset`.

- [ ] **Step 8: Run everything, lint, type-check, commit**

Run: `uv run pytest packages/tri-nutrition -q` — expected: all pass, including the unchanged `test_fuel_node.py`. If mypy objects to `rows` typing from `aevaluate`, keep the `[dict(r) for r in rows]` conversion and annotate `rows: list[Any]`.
```bash
uv run ruff format packages/tri-nutrition && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition uv.lock
git commit -m "feat(nutrition): FuelPlanner; LangSmith fueling dataset, bounds evaluators, LLM judge, eval command"
```

---

### Task 6: README, vault copies, and the live steps (Brian)

**Files:**
- Modify: `packages/tri-nutrition/README.md`, root `README.md`, this plan (execution notes)

- [ ] **Step 1: Package README**

In the mermaid graph replace the checkin node text with `checkin["checkin\ncreate_agent sub-agent\nthe check-in: intake vs targets, body, recovery, fuel log;\nsave_nutrition_profile or propose_target_changes"]` and the edge `checkin -->|profile saved| targets` with `checkin -->|profile saved or targets proposed| targets`. Under "The graph" add one paragraph:

> The check-in reads through tools only: `read_intake_vs_targets` joins the Garmin food log to `nutrition_targets` per day (so the model reads deltas, not two lists), `read_body_composition` and `read_hydration` come from the Index scale and the app, and the SQL tool covers `daily_metrics` and workout comments. Its commit tools write the Store only: `record_fuel_feedback` appends to the fuel log (and adds a product after an ok outcome), `propose_target_changes` validates overrides that the graph applies on top of the profile when it regenerates targets; approve persists them, reject discards them.

Under Commands add:
```
- `tri-nutrition check-in [--yes] [--no-sync] [--no-live]`: runs `tri sync`, sends the fixed
  check-in request on the nutrition thread, prints the report and any proposed change set, and
  exits 3 while it waits at review. `--yes` approves. Run it again (or `chat`) to resume a
  paused review rather than start a second one.
- `tri-nutrition eval [--judge/--no-judge] [--prefix NAME] [--recreate-dataset]`: creates the
  LangSmith dataset `tri_nutrition_fueling` from `evals/cases.py` when missing, runs the fueling
  prompts over it as experiment `fuel-v<PROMPT_VERSION>`, and prints the pass rate per
  evaluator (`targets_within_bounds`, `fuel_within_bounds`, `fuel_respects_profile`). Bump
  `PROMPT_VERSION` in `prompts/fuel.py` whenever a fueling prompt changes and compare runs in
  LangSmith.
```
Add `evals/` to the layout list: `evals/`: cases, target, evaluators, runner (no database).

- [ ] **Step 2: Root README**

Line 131's package listing: add `evals` to the `src/tri_nutrition/{...}` set. Add `check-in` and `eval` to the tri-nutrition command cell in the packages table (`tri-nutrition chat | today | check-in | eval`).

- [ ] **Step 3: Vault copies, commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/docs/superpowers/plans $V/packages/tri-nutrition
cp packages/tri-nutrition/README.md $V/packages/tri-nutrition/readme.md
cp README.md $V/readme.md
cp docs/superpowers/plans/2026-09-10-tri-nutrition-04-checkin.md $V/docs/superpowers/plans/
git add packages/tri-nutrition/README.md README.md docs/superpowers/plans/2026-09-10-tri-nutrition-04-checkin.md
git commit -m "docs(nutrition): plan 4 check-in and eval documentation"
```

- [ ] **Step 4: Brian's live run**

1. `uv run tri-nutrition check-in` after a week with some Garmin food logging. Read the report; if it proposes, `uv run tri-nutrition check-in --yes` or `chat` to approve. Confirm in Garmin that today's goal changed when the proposal changed the kcal.
2. In `chat`, say how a long ride went ("the 3 h ride was fine at 70 g/h with Gel") and check `/status` shows one fuel-log entry; then `/profile` is unchanged.
3. `uv run tri-nutrition eval` with `LANGSMITH_API_KEY` set. Open the experiment in LangSmith; note the pass rate per evaluator here. Then change one line of `FUEL_SYSTEM`, bump `PROMPT_VERSION` to `"2"`, run again, and compare.
4. Record here: what the check-in reported, whether `read_intake_vs_targets` matched the Connect app's daily totals, what the eval pass rates were, and anything the judge flagged that the bounds did not.

---

## Self-review notes

- Spec §6.2 checkin: tools `query_training_db`, `read_training_plan`, body composition, food log, hydration (Tasks 1 to 3; `get_nutrition_daily_meals` dropped, see deviations), commit tools `record_fuel_feedback` and `propose_target_changes` (Task 2); the prompt's five checks: intake vs target by day type over 7 days, weight and body fat over 14 and 28 days against the goal rate, low-intake days followed by poor readiness or sleep, TP comments mentioning GI trouble, fewer than 7 days of targets remaining (Task 3 prompt steps 2, 3, 4, 5, 7); overrides into `profile_overrides` with `regenerate_from = "checkin"` (Task 3 node); regenerate with overrides, approve persists, reject discards (Plan 2 apply and review, tested in Task 3's graph cases); extending the horizon is the same call with no overrides (Task 3 `test_checkin_extend_horizon...`).
- Spec §5.1 fuel log and product library written by `record_fuel_feedback` (Task 1 helpers, Task 2 tool). §6.1 state: `targets_requested` added (deviation noted).
- Spec §8 `check-in [--yes]`: runs `tri sync`, invokes the graph on thread `nutrition` with the fixed prompt, prints the change set, exits paused; `--yes` approves (Task 4). `/status`: horizon end and fuel log added; trend left to the check-in (deviation noted).
- Spec §9: Garmin unavailable makes the intake and hydration tools answer with an error and the check-in says so; a bounds violation after a proposal discards the overrides with the violations printed (Task 3 targets change).
- Spec §11 graph tests: "checkin ends on `propose_target_changes`, targets regenerate with the overrides, and approve persists them to the Store" (Task 3). Unit: parsing (Task 1), tools (Task 2), evaluators (Task 5).
- Spec §12: dataset of (profile, training week) pairs, code evaluator running `validate_targets` and `validate_fuel`, LLM judge for restrictions and library products, pass rate per prompt version (Task 5).
- Type consistency: `make_garmin_read_tools(garmin, today, only=None)` is used by intake (Task 1) and checkin (Task 3) with the tuples from `allowlist.py`; `make_checkin_tools(garmin, connect, today)` matches `GraphDeps` fields; `FuelPlanner.session(profile, library, fuel_log, session, target, other_caffeine_mg, config)` is called identically by the node and `run_case`; `checkin_run(graph, *, thread_id, out, approve)` is what `_check_in` calls; `proposal_from_messages` returns `{}` for an extension and the node stores `None` in `profile_overrides` while `targets_requested` carries the route.
- Placeholder scan: every step carries its code; `test_repo.py`'s existing `target(day=MON, **over)` helper is reused as named.

## Execution notes (2026-09-11)

- Executed inline on branch `feat/tri-nutrition-04`, one commit per task (six commits). Every module matched the plan; the only edits were an existing assertion in `test_garmin_tools.py` that listed the three old read-tool names (now four, with `read_hydration`) and one import-order fix for `PROMPT_VERSION`.
- **Suite:** 411 passed, 2 skipped (the two live tests), plus `ruff check`, `ruff format --check` and strict `mypy` clean. New tests: store helpers (1), Garmin parsing and hydration (2), repo (1), check-in tools (5), checkin node (5), graph proposal approve / reject / extend and `after_checkin` (4), `checkin_run` (2), evals (5).
- `uv lock` picked up the explicit `langsmith>=0.12,<1` pin without downloading anything new; langsmith 0.12.2 emits one `ast.Str` DeprecationWarning under Python 3.12 when imported in tests, harmless.
- **Brian's steps left (Task 6 step 4):** a real `tri-nutrition check-in` after a week of Garmin food logging; a fueling-feedback line in `chat` followed by `/status`; `tri-nutrition eval` with `LANGSMITH_API_KEY` set, then a prompt tweak with `PROMPT_VERSION = "2"` to compare experiments. Record here what the check-in reported, whether `read_intake_vs_targets` matched the Connect app's daily totals, the pass rates, and anything the judge flagged that the bounds did not.
- **Things to watch on the first live run:** `aevaluate` result rows are read as `row["evaluation_results"]["results"]` and `results.experiment_name`; both come from langsmith 0.12.2's `AsyncExperimentResults` and were not exercised against the service in tests. `client.create_examples(dataset_name=..., examples=[{inputs, outputs, metadata}])` likewise.

### Eval findings (2026-09-11, Brian's runs; results pulled with the SDK)

- Dataset `tri_nutrition_fueling` (5 examples) on the AWS-region endpoint (`LANGSMITH_ENDPOINT=https://aws.api.smith.langchain.com`). Both `aevaluate` result rows and `create_examples` worked as written; the "things to watch" above are settled.
- `fuel-v1-78dcdf24` (prompt version 1, claude-opus-5): `targets_within_bounds` 5/5, `fuel_within_bounds` 5/5, `fuel_respects_profile` 3/5. Judge failures: `vegan_lose_gluten_free` ("toast with jam" in the pre-session line for a gluten restriction); `race_week_olympic` (the race note names "sports drink" on bike and run, "electrolyte drink or salt caps", and the optional beetroot shot; the library holds only Gel).
- `fuel-v2-fbd6cae8` (prompt version 2: a line in `FUEL_SYSTEM` about bike-carriable fuel): 5/5, 5/5, 4/5. The gluten case passed; the race case failed on the same on-course drink and beetroot mentions. With `num_repetitions` 1 the gluten flip is within run-to-run variance, not evidence for the v2 line.
- What the judge catches that the bounds cannot: every violation lived in `note_text` or `pre` prose ("sports drink", "toast"), which `_product_violations` does not read because it checks the `products` list only.
- **Prompt version 3** (this commit, not yet run): `RACE_SYSTEM` says on-course drink, electrolyte drink or salt caps may be named only when the library holds them, else water plus library products; `JUDGE_SYSTEM` exempts the optional pre-race beetroot or nitrate shot that the race prompt permits; the v2 bike-carry line is kept, reworded. Run `uv run tri-nutrition eval` to record `fuel-v3`.
- Still open from Task 6 step 4: the live `tri-nutrition check-in` after a week of Garmin food logging (and whether `read_intake_vs_targets` matches the Connect app's daily totals), and the fueling-feedback line in `chat` followed by `/status`.
