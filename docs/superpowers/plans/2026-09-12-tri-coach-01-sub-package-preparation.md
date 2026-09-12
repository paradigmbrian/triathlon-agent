# tri-coach Plan 1 of 3: Sub-Package Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tri-core, tri-planning and tri-nutrition composable by the coach without building the coach: planning derives its phase and ids from the tables at the start of every run; both graphs gain an `embedded` mode that ends with `pending_changes` instead of pausing at review; both apply nodes become thin wrappers over a callable `apply_changes`; nutrition gains a regenerate entry that goes straight to `targets`; both sub-agent prompts gain a directed section for briefs from the head coach; tri-core gains `open_live_servers` (tools grouped per server) and `ToolsCaller` (a `ToolCaller` over adapter-bound tools). Every existing CLI behaves as before. This is spec milestone 1.

**Architecture:** Each change is additive or a lift. Planning gets a `route` node (`START -> route`) that reads `training_goals` and `training_plans` and writes `phase`, `goal_id`, `plan_id` into state before the existing pure `route_start` picks the first node. `build_graph(..., embedded=True)` in both packages skips the `review` and `apply` nodes and points every edge that would reach `review` at `END`. `apply_changes` in both packages is the body of today's apply node with the state reads and the message assembly peeled off into a thin node; it returns an `ApplyResult` the coach will map to its `ApplyReport` in Plan 2. tri-core's `open_live_tools` becomes the flattened view of a new `open_live_servers`, and `ToolsCaller` lets one adapter session serve both the model's tools and the `call_json` path the graph deps expect.

**Tech Stack:** langgraph 1.2.11, langchain 1.4.0, langchain-mcp-adapters 0.3.2, pydantic 2, psycopg 3, pytest with `tri_core.testing.ScriptedChatModel` and the rolled-back `db` fixture.

**Spec:** `docs/superpowers/specs/2026-09-11-tri-coach-design.md` (§2 feasibility, §7 changes to existing packages, §11 testing, §13 milestone 1, §15 open items).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- No new dependencies and no new packages in this plan (spec §10, §13). The root `pyproject.toml` is not touched.
- Dependency direction is unchanged: tri-planning and tri-nutrition depend on tri-core only and never import each other.
- Invariants preserved by construction (spec §6.3): no write tool is ever bound to a model; the only edge into either `apply` node is from `review`; an embedded graph contains no `review` or `apply` node.
- Standalone behaviour is unchanged: `tri-planning chat`, `tri-planning check-in`, `tri-nutrition chat`, `tri-nutrition check-in`, `tri-nutrition today` produce the same turns, messages and exit codes as on `main` at `b223e1f`.
- **Brian runs any SQL with `psql`; this plan has no migration.** Tests write only through the rolled-back `db` fixture (`nocommit`).
- Git commits are permitted in this repo (Brian's standing permission). Commit per task on the feature branch. End every commit message with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2
  ```
- **Execute in a sibling worktree.** Other Claude sessions share the main checkout. Task 1 creates `../triathlon_agent-coach-01` on branch `feat/tri-coach-01`.
- Definition of done per task, in this order, in the worktree: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. Run `uv run ruff format packages/<pkg>` first; the test code in this plan is written for readability and the formatter wraps it.
- No "LangChain lesson:" framing in docstrings (Brian's standing feedback).
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case file name (Task 10).

### Spec deviations decided in this plan

- **The brief marker is a string prefix.** Spec §7.1 and §7.2 say the prompts recognise "a brief from the head coach" but do not say how. Each prompt module defines `BRIEF_PREFIX = "Head coach brief:"` (`tri_planning.prompts.adjust`, `tri_nutrition.prompts.checkin`, identical strings because neither package may import the other). The coach (Plan 2) sends `HumanMessage(f"{BRIEF_PREFIX} {brief.instruction}")`, and the directed section of each prompt names the prefix. Plan 2 adds one test asserting the two constants are equal.
- **Adapter tools return content blocks, not text.** Spec §15 asked whether `tool.ainvoke(args)` returns the server's text verbatim. Read from `langchain_mcp_adapters/tools.py` (0.3.2): `_convert_call_tool_result` returns `list[ToolMessageContentBlock]` (`[{"type": "text", "text": ...}]`), and `langchain_core`'s `_format_output` hands that list back unchanged when there is no tool call id. `tri_core.mcp.caller.tool_text` joins the text blocks; a plain string passes through. The live confirmation in §15 stays with Plan 2's live test.
- **MCP-level `isError` is not visible to `ToolsCaller`.** With the adapter's default `handle_tool_errors=True`, an `isError` result is returned as ordinary content blocks (the `status="error"` lands only on a `ToolMessage`). `ToolsCaller` therefore relies on the servers' text conventions exactly as `parse_tool_text` already does (TrainingPeaks `{"isError": true, ...}` JSON, Garmin `"Error ..."` text), and also converts a raised `ToolException` into `McpToolError`. The bound tools keep the default handler so the models' behaviour in every existing CLI is unchanged.
- **A dead server is absent from the `open_live_servers` result** rather than mapped to `[]`, so `servers.get("trainingpeaks")` being `None` is the same signal the CLIs use today (`tp = None` means "held pending").
- **`run_checkin` takes `phase` from its caller.** Spec §7.1 says the thread no longer carries the phase. `tri_planning.checkin.run_checkin(graph, *, phase, yes, out, thread_id)` receives the phase the CLI derives from the tables with `repo.derive_phase`, and the `StubGraph` tests pass it directly. The `/status` command derives it the same way.
- **The route node still writes `phase`, `goal_id`, `plan_id` into state** every run. The spec's "the thread no longer carries them" is satisfied in effect: whatever the checkpoint holds is overwritten before any routing reads it, so a stale value never matters and a fresh thread starts where the tables say.
- **Planning `apply_changes` has `tp_plan_applied: bool = False`** as a keyword; the node passes the state flag, the coach passes nothing.
- **Nutrition `ApplyResult` carries `held` and `profile_updated`** in addition to the spec's applied, skipped, remaining and error, because the node's report needs both and the coach's report (Plan 2) names held domains.
- **The regenerate rule "carries no new `HumanMessage`"** is implemented as "the messages list is empty or its last message is not a `HumanMessage`". In a stateless consultation the list is empty; in the standalone graph `targets_requested` is always false at the start of a run (the `targets` node resets it), so the guard is a safety net, not a routing path.
- **`GraphPhase = Literal["intake", "planning", "active"]`** is added to `tri_planning.planning.models` so `repo.derive_phase` and `PlanningState` share the type. `Phase` there remains the periodization phase.

---

## File Structure

```
packages/tri-core/src/tri_core/mcp/
  live_tools.py           open_live_servers(specs, log) -> dict[server, tools]; open_live_tools is
                          its flattened view (modified)
  caller.py               tool_text(out); ToolsCaller(tools): ToolCaller over bound tools (new)
  README.md               modules table, a ToolsCaller paragraph (modified)
packages/tri-core/tests/
  test_live_tools.py      grouping test with faked client and loader (modified)
  test_caller.py          ToolsCaller over fake @tools (new)

packages/tri-planning/src/tri_planning/
  planning/models.py      GraphPhase (modified)
  repo.py                 derive_phase(conn) (modified)
  graph/state.py          phase: GraphPhase (modified)
  graph/nodes/route.py    make_route_node(deps) (new)
  graph/nodes/apply.py    ApplyResult, SESSION_OPS, apply_changes(...); thin node (modified)
  graph/graph.py          START -> route; build_graph(..., embedded=False) (modified)
  checkin.py              run_checkin(graph, *, phase, yes, out, thread_id) (modified)
  cli.py                  /status and check-in derive the phase from the tables (modified)
  prompts/adjust.py       BRIEF_PREFIX, DIRECTED_RULES rendered in the stable part (modified)
  README.md               route node, embedded mode (modified)
packages/tri-planning/tests/
  test_graph.py           derive_phase, fresh-thread routing, embedded mode (modified)
  test_graph_adjust.py    no aupdate_state; embedded adjust (modified)
  test_apply_node.py      apply_changes direct (modified)
  test_checkin.py         phase passed to run_checkin (modified)
  test_adjust_prompt.py   directed section (modified)
  test_adjust_node.py     directed brief ends on the proposal and merges design_next_week (modified)

packages/tri-nutrition/src/tri_nutrition/
  graph/nodes/apply.py    ApplyResult, apply_changes(...); thin node (modified)
  graph/graph.py          route_start regenerate rule; build_graph(..., embedded=False) (modified)
  prompts/checkin.py      BRIEF_PREFIX, directed paragraph (modified)
  README.md               regenerate entry, embedded mode (modified)
packages/tri-nutrition/tests/
  test_apply_node.py      apply_changes direct (modified)
  test_graph.py           regenerate entry, embedded mode, route_start (modified)
  test_checkin_prompt.py  directed paragraph (new)
  test_checkin_node.py    brief turn (modified)

README.md                 status line (modified)
```

Responsibilities: `caller.py` is the only place adapter output is turned into `call_json` data. `route.py` is the only database read that routing depends on in planning. `apply.py` in each package remains the only writer of its server; `apply_changes` is that writer as a function, the node is state plumbing.

---

### Task 1: Worktree and `open_live_servers` in tri-core

**Files:**
- Modify: `packages/tri-core/src/tri_core/mcp/live_tools.py`
- Test: `packages/tri-core/tests/test_live_tools.py`

**Interfaces:**
- Consumes: `tri_core.mcp.servers.ServerSpec`, `langchain_mcp_adapters.client.MultiServerMCPClient`, `langchain_mcp_adapters.tools.load_mcp_tools` (both imported by name into `live_tools`, so tests can monkeypatch `tri_core.mcp.live_tools.<name>`).
- Produces: `open_live_servers(specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]) -> AsyncIterator[dict[str, list[BaseTool]]]` (async context manager; a dead server is logged and absent from the dict). `open_live_tools(specs, log) -> AsyncIterator[list[BaseTool]]` keeps its signature and yields every bound tool in spec order.

- [ ] **Step 1: Create the worktree**

```bash
cd /Users/brian/Development/paradigm/fitness_agents/triathlon_agent
git worktree add ../triathlon_agent-coach-01 -b feat/tri-coach-01 main
cp .env ../triathlon_agent-coach-01/.env
cd ../triathlon_agent-coach-01
uv sync
uv run pytest -q 2>&1 | tail -3
```
Expected: the suite passes (db tests skip if Postgres is unreachable; they must run for this plan, so `tri_analyze_test` should be up). Every later step runs in `../triathlon_agent-coach-01`.

- [ ] **Step 2: Write the failing test**

Add to `packages/tri-core/tests/test_live_tools.py` (keep the two existing tests):

```python
from contextlib import asynccontextmanager

from tri_core.mcp.live_tools import open_live_servers


@tool
def tp_get_workout(workout_id: str) -> str:
    """one workout"""
    return ""


class _FakeClient:
    """Stands in for MultiServerMCPClient: session(name) yields the name as the session."""

    def __init__(self, connections):
        self.connections = connections

    @asynccontextmanager
    async def session(self, name):
        yield name


async def _fake_load(session):
    return {
        "garmin": [delete_activity, get_activity_splits, get_activity],
        "trainingpeaks": [tp_get_workout],
    }[session]


async def test_open_live_servers_groups_tools_by_server(monkeypatch):
    monkeypatch.setattr("tri_core.mcp.live_tools.MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr("tri_core.mcp.live_tools.load_mcp_tools", _fake_load)
    s = Settings(_env_file=None)
    specs = {
        "garmin": (garmin_spec(s), ["get_activity_splits", "get_activity"]),
        "trainingpeaks": (trainingpeaks_spec(s), ["tp_get_workout"]),
    }
    logs: list[str] = []
    async with open_live_servers(specs, logs.append) as servers:
        assert {k: [t.name for t in v] for k, v in servers.items()} == {
            "garmin": ["get_activity_splits", "get_activity"],
            "trainingpeaks": ["tp_get_workout"],
        }
    async with open_live_tools(specs, logs.append) as tools:
        assert [t.name for t in tools] == ["get_activity_splits", "get_activity", "tp_get_workout"]
    assert any("garmin: bound" in m for m in logs)


async def test_open_live_servers_omits_a_dead_server(monkeypatch):
    s = Settings(_env_file=None, garmin_mcp_ref="0000000", tp_mcp_ref="0000000")
    monkeypatch.setattr("tri_core.mcp.live_tools.SESSION_TIMEOUT_S", 5)
    specs = {"garmin": (garmin_spec(s), ["get_activity"])}
    logs: list[str] = []
    async with open_live_servers(specs, logs.append) as servers:
        assert servers == {}
    assert any("garmin" in m and "unavailable" in m for m in logs)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_live_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'open_live_servers'`.

- [ ] **Step 4: Implement `open_live_servers` and re-express `open_live_tools` over it**

Replace the body of `packages/tri-core/src/tri_core/mcp/live_tools.py` from `@asynccontextmanager` down with:

```python
@asynccontextmanager
async def open_live_servers(
    specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]
) -> AsyncIterator[dict[str, list[BaseTool]]]:
    """Start each server, load its tools, keep the allow-listed ones, and keep every session open
    for as long as the context is. Yields server name -> bound tools, in spec order.

    A server that fails to start is logged and left out, so `name not in servers` means it is
    down; the others still bind.
    """
    client = MultiServerMCPClient({name: _connection(spec) for name, (spec, _) in specs.items()})
    servers: dict[str, list[BaseTool]] = {}
    async with AsyncExitStack() as stack:
        for name, (_, allow) in specs.items():
            try:
                session = await asyncio.wait_for(
                    stack.enter_async_context(client.session(name)), timeout=SESSION_TIMEOUT_S
                )
                loaded = await load_mcp_tools(session)
                picked = filter_tools(loaded, allow)
                servers[name] = picked
                log(f"{name}: bound {[t.name for t in picked]}")
            except Exception as exc:  # a dead server must not kill the chat
                log(
                    f"warning: {name} MCP server unavailable ({type(exc).__name__}: {exc}); "
                    "its tools are not bound"
                )
        yield servers


@asynccontextmanager
async def open_live_tools(
    specs: dict[str, tuple[ServerSpec, Sequence[str]]], log: Callable[[str], None]
) -> AsyncIterator[list[BaseTool]]:
    """The flattened view of `open_live_servers`: every bound tool, servers in spec order."""
    async with open_live_servers(specs, log) as servers:
        yield [t for tools in servers.values() for t in tools]
```

The module docstring, imports, `SESSION_TIMEOUT_S`, `filter_tools` and `_connection` stay as they are.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_live_tools.py -v`
Expected: 4 passed (the dead-server tests take a few seconds each while `uvx` fails on the bogus ref).

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-core && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-core
git commit -m "feat(core): open_live_servers groups bound tools per server; open_live_tools is its flattened view

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 2: `ToolsCaller` in tri-core

**Files:**
- Create: `packages/tri-core/src/tri_core/mcp/caller.py`
- Test: `packages/tri-core/tests/test_caller.py`

**Interfaces:**
- Consumes: `tri_core.mcp.client.parse_tool_text(tool, text)`, `tri_core.mcp.client.McpToolError(tool, message)`, `langchain_core.tools.ToolException`.
- Produces: `tool_text(out: Any) -> str`; `class ToolsCaller` with `__init__(self, tools: Sequence[BaseTool])`, `names -> list[str]`, `async call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None`. Satisfies `tri_core.sync.ToolCaller` structurally.

- [ ] **Step 1: Write the failing test**

`packages/tri-core/tests/test_caller.py`:

```python
import json

import pytest
from langchain_core.tools import ToolException, tool

from tri_core.mcp.caller import ToolsCaller, tool_text
from tri_core.mcp.client import McpToolError


@tool
def tp_get_workouts(start_date: str, end_date: str) -> str:
    """Planned workouts; JSON text as the TrainingPeaks server returns it."""
    return json.dumps({"workouts": [{"id": "w1", "date": start_date}], "count": 1})


@tool
def get_stats(date: str) -> list:
    """Daily stats; the adapter's content-block shape, with Garmin's empty convention."""
    return [{"type": "text", "text": "No stats found for " + date}]


@tool
def get_hrv_data(date: str) -> str:
    """HRV; Garmin's error convention."""
    return "Error retrieving HRV data: boom"


@tool
def tp_get_workout(workout_id: str) -> str:
    """One workout; the adapter raises ToolException when the server sets isError."""
    raise ToolException("server said no")


@tool
def tp_get_fitness(days: int) -> list:
    """Two text blocks, joined in order."""
    return [{"type": "text", "text": '{"ctl": 45,'}, {"type": "text", "text": ' "atl": 50}'}]


CALLER = ToolsCaller([tp_get_workouts, get_stats, get_hrv_data, tp_get_workout, tp_get_fitness])


def test_names_are_the_bound_tools():
    assert CALLER.names == [
        "tp_get_workouts",
        "get_stats",
        "get_hrv_data",
        "tp_get_workout",
        "tp_get_fitness",
    ]


async def test_call_json_parses_json_text():
    out = await CALLER.call_json("tp_get_workouts", {"start_date": "2026-09-14", "end_date": "x"})
    assert out == {"workouts": [{"id": "w1", "date": "2026-09-14"}], "count": 1}


async def test_content_blocks_are_joined_and_empty_convention_returns_none():
    assert await CALLER.call_json("get_stats", {"date": "2026-09-14"}) is None
    assert await CALLER.call_json("tp_get_fitness", {"days": 7}) == {"ctl": 45, "atl": 50}


async def test_error_text_raises_mcp_tool_error():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("get_hrv_data", {"date": "2026-09-14"})
    assert ei.value.tool == "get_hrv_data" and "boom" in ei.value.message


async def test_tool_exception_becomes_mcp_tool_error():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("tp_get_workout", {"workout_id": "w1"})
    assert ei.value.tool == "tp_get_workout" and "server said no" in ei.value.message


async def test_unbound_tool_raises():
    with pytest.raises(McpToolError) as ei:
        await CALLER.call_json("tp_create_workout", {})
    assert "not bound" in ei.value.message


async def test_missing_args_default_to_empty():
    caller = ToolsCaller([tp_get_fitness])
    # tp_get_fitness needs `days`; calling with no args surfaces pydantic's error as McpToolError
    with pytest.raises(McpToolError):
        await caller.call_json("tp_get_fitness")


def test_tool_text_shapes():
    assert tool_text("plain") == "plain"
    assert tool_text([{"type": "text", "text": "a"}, {"type": "image", "base64": "zz"}]) == "a"
    assert tool_text(["x", {"type": "text", "text": "y"}]) == "x\ny"
    assert tool_text([]) == ""
    assert tool_text({"k": 1}) == "{'k': 1}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_caller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_core.mcp.caller'`.

- [ ] **Step 3: Implement `caller.py`**

`packages/tri-core/src/tri_core/mcp/caller.py`:

```python
"""A ToolCaller over adapter-bound tools, so one open MCP session serves both the model (as
LangChain tools) and the programmatic `call_json` path the graph deps hold."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool, ToolException
from pydantic import ValidationError

from tri_core.mcp.client import McpToolError, parse_tool_text


def tool_text(out: Any) -> str:
    """The text of a tool result. Adapter tools return a list of content blocks
    (`[{"type": "text", "text": ...}, ...]`); plain tools return a string. Non-text blocks are
    dropped; text blocks are joined with newlines, as `McpToolClient.call_json` joins texts."""
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        parts: list[str] = []
        for block in out:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(out)


class ToolsCaller:
    """`call_json(tool, args)` finds the bound tool by name, awaits it, and parses the text with
    the same conventions as `McpToolClient.call_json`, raising `McpToolError` the same way."""

    def __init__(self, tools: Sequence[BaseTool]) -> None:
        self._tools: dict[str, BaseTool] = {t.name: t for t in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None:
        bound = self._tools.get(tool)
        if bound is None:
            raise McpToolError(tool, f"not bound (bound tools: {sorted(self._tools)})")
        try:
            out = await bound.ainvoke(args or {})
        except ToolException as exc:
            raise McpToolError(tool, str(exc)) from exc
        except ValidationError as exc:
            raise McpToolError(tool, f"invalid arguments: {exc}") from exc
        text = tool_text(out)
        if not text.strip():
            raise McpToolError(tool, "no text content in result")
        return parse_tool_text(tool, text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_caller.py -v`
Expected: 9 passed. If `test_missing_args_default_to_empty` fails because langchain raises something other than `pydantic.ValidationError` for missing arguments, read the traceback, add that exception type to the `except` tuple in `call_json` (it must stay narrow: never `except Exception`), and re-run.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-core && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-core
git commit -m "feat(core): ToolsCaller, a ToolCaller over adapter-bound tools

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 3: Planning `route` node with database-derived phase and ids

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/planning/models.py` (add `GraphPhase` after `Phase`)
- Modify: `packages/tri-planning/src/tri_planning/graph/state.py:15`
- Modify: `packages/tri-planning/src/tri_planning/repo.py` (add `derive_phase` after `get_active_plan`)
- Create: `packages/tri-planning/src/tri_planning/graph/nodes/route.py`
- Modify: `packages/tri-planning/src/tri_planning/graph/graph.py`
- Modify: `packages/tri-planning/src/tri_planning/checkin.py`
- Modify: `packages/tri-planning/src/tri_planning/cli.py:110-147` (`cmd_status`) and `cli.py:188-197` (`_check_in`)
- Test: `packages/tri-planning/tests/test_graph.py`, `test_graph_adjust.py`, `test_checkin.py`

**Interfaces:**
- Consumes: `repo.get_active_goal(conn)`, `repo.get_active_plan(conn, goal_id)`, `GraphDeps.connect`.
- Produces: `GraphPhase = Literal["intake", "planning", "active"]`; `repo.derive_phase(conn) -> tuple[GraphPhase, int | None, int | None]`; `make_route_node(deps) -> node` returning `{"phase", "goal_id", "plan_id"}`; `run_checkin(graph, *, phase: str, yes: bool, out: Out, thread_id: str = "planning") -> int`. `route_start`, `after_*` are unchanged.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-planning/tests/test_graph.py`, extend the imports and add three tests:

```python
from tri_planning.planning.models import ReviewDecision, TrainingGoal, WeekTarget
```

```python
def test_derive_phase_from_tables(nocommit):
    assert repo.derive_phase(nocommit) == ("intake", None, None)
    gid = repo.insert_goal(nocommit, TrainingGoal(**GOAL_ARGS))
    assert repo.derive_phase(nocommit) == ("planning", gid, None)
    targets = [WeekTarget(week_start=MONDAY, phase="base", target_tss=300, target_hours=6)]
    pid = repo.insert_plan(nocommit, gid, "generated", None, targets)
    assert repo.derive_phase(nocommit) == ("active", gid, pid)
    repo.abandon_active(nocommit)
    assert repo.derive_phase(nocommit) == ("intake", None, None)


async def test_fresh_thread_starts_where_the_tables_say(nocommit, make_deps, fake_tp):
    # An active goal with no plan: route -> targets -> design -> review. No intake call.
    gid = repo.insert_goal(nocommit, TrainingGoal(**GOAL_ARGS))
    model = ScriptedChatModel(script=[week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    out = await graph.ainvoke({"messages": [HumanMessage("continue")]}, CFG)
    assert "__interrupt__" in out and model.calls == 1
    values = (await graph.aget_state(CFG)).values
    assert values["goal_id"] == gid and values["plan_id"] is not None
    assert values["phase"] == "planning"


async def test_stale_thread_phase_is_overwritten_by_the_tables(nocommit, make_deps, fake_tp):
    # The checkpoint says active with ids that no longer exist; the tables say intake, so the
    # run goes intake -> targets -> design -> review instead of asserting in adjust.
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver())
    await graph.aupdate_state(CFG, {"phase": "active", "goal_id": 999, "plan_id": 999})
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" in out and model.calls == 3
    values = (await graph.aget_state(CFG)).values
    assert values["phase"] == "planning" and values["goal_id"] != 999
```

In `packages/tri-planning/tests/test_graph_adjust.py`, delete both `await graph.aupdate_state(CFG, {"goal_id": gid, "plan_id": pid, "phase": "active"})` lines (the route node derives them from the seeded rows) and change `gid, pid = seed_active(nocommit)` to `seed_active(nocommit)` in both tests.

In `packages/tri-planning/tests/test_checkin.py`, remove the `phase="active"` parameter and `self.phase` from `StubGraph` (its `aget_state` returns `values = {"pending_changes": list(self.pending_changes)}`), and pass the phase to every `run_checkin` call:

```python
async def test_checkin_pauses_without_yes():
    g = StubGraph([[INTERRUPT]])
    buf = []
    assert await run_checkin(g, phase="active", yes=False, out=buf.append) == 3
    ...

async def test_checkin_requires_active_plan():
    g = StubGraph([])
    buf = []
    assert await run_checkin(g, phase="intake", yes=True, out=buf.append) == 2
    assert "no active plan" in "".join(buf)
```
Every other call becomes `run_checkin(g, phase="active", ...)` with its existing `yes` and `out`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_graph.py packages/tri-planning/tests/test_graph_adjust.py packages/tri-planning/tests/test_checkin.py -v`
Expected: `test_derive_phase_from_tables` fails with `AttributeError: module 'tri_planning.repo' has no attribute 'derive_phase'`; the adjust tests fail with `AssertionError: adjust needs an active plan`; the checkin tests fail with `TypeError: ... unexpected keyword argument 'phase'`.

- [ ] **Step 3: Add `GraphPhase` and `derive_phase`**

`packages/tri-planning/src/tri_planning/planning/models.py`, after `Phase = ...`:

```python
GraphPhase = Literal["intake", "planning", "active"]  # where a planning run starts
```

`packages/tri-planning/src/tri_planning/graph/state.py`: import `GraphPhase` from `tri_planning.planning.models` and change the field to `phase: GraphPhase`; drop the now-unused `Literal` import of that line only if nothing else uses it (`changes_from` still does, so keep `Literal`).

`packages/tri-planning/src/tri_planning/repo.py`: add `GraphPhase` to the models import and, after `get_active_plan`:

```python
def derive_phase(conn: Conn) -> tuple[GraphPhase, int | None, int | None]:
    """Where a run starts, from the tables: no active goal is intake; an active goal without an
    active plan is planning; an active plan is active. Returns (phase, goal_id, plan_id)."""
    goal = get_active_goal(conn)
    if goal is None:
        return "intake", None, None
    plan = get_active_plan(conn, goal.id)
    if plan is None:
        return "planning", goal.id, None
    return "active", goal.id, plan.id
```

- [ ] **Step 4: Add the route node and wire `START -> route`**

`packages/tri-planning/src/tri_planning/graph/nodes/route.py`:

```python
"""Route node: derive the phase and the active ids from the tables at the start of every run,
so a fresh thread and a stateless consultation both start where the database says. The edge
functions in graph.py stay pure over state."""

from __future__ import annotations

from typing import Any

from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState


def make_route_node(deps: GraphDeps) -> Any:
    def route(state: PlanningState) -> dict[str, Any]:
        with deps.connect() as conn:
            phase, goal_id, plan_id = repo.derive_phase(conn)
        return {"phase": phase, "goal_id": goal_id, "plan_id": plan_id}

    return route
```

`packages/tri-planning/src/tri_planning/graph/graph.py`: update the module docstring's first line to `START -> route -> route_start: pending changes -> review; intake | targets | adjust by the phase derived from the tables`, import `make_route_node`, and in `build_graph` replace the `START` conditional edge with:

```python
    g.add_node("route", make_route_node(deps))
    ...
    g.add_edge(START, "route")
    g.add_conditional_edges("route", route_start, ["review", "intake", "targets", "adjust"])
```
(Task 5 rewrites `build_graph` again for embedded mode; this step only adds the node and the edge.)

- [ ] **Step 5: Pass the phase into `run_checkin` and derive it in the CLI**

`packages/tri-planning/src/tri_planning/checkin.py`:

```python
async def run_checkin(
    graph: Any, *, phase: str, yes: bool, out: Out, thread_id: str = "planning"
) -> int:
    """Run one check-in turn. `phase` is derived from the tables by the caller
    (`repo.derive_phase`), not read from the thread. See module docstring for exit codes."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    values = snap.values or {}
    pending = values.get("pending_changes") or []
    if snap.next or pending:
        ...  # unchanged
        return EXIT_PAUSED
    if phase != "active":
        out("check-in: no active plan; run `tri-planning chat` to set a goal first\n")
        return EXIT_NO_PLAN
    ...  # unchanged
```

`packages/tri-planning/src/tri_planning/cli.py`, in `cmd_status` replace the `values.get("phase")` reads:

```python
            with connect(settings.database_url) as conn:
                phase, _, _ = repo.derive_phase(conn)
                goal = repo.get_active_goal(conn)
                if goal is None:
                    return f"no active goal; phase {phase}"
                ...
                lines = [
                    f"goal: {g.goal_type} {g.event_name or ''} {g.event_date or ''}".rstrip(),
                    f"phase: {phase}; next node: {snap.next or '-'}",
                ]
```

and in `_check_in`:

```python
async def _check_in(*, yes: bool, no_sync: bool, no_live: bool) -> int:
    from tri_core.db.connection import connect
    from tri_core.sync.runner import run_sync
    from tri_planning import repo
    from tri_planning.checkin import run_checkin

    settings = get_planning_settings()
    if not no_sync:
        report = await run_sync(settings, log=lambda m: _out(m + "\n"))
        if not report.ok:
            _out("check-in: sync had errors; continuing with existing data\n")
    with connect(settings.database_url) as conn:
        phase, _, _ = repo.derive_phase(conn)
    async with _open_graph(no_live=no_live) as graph:
        return await run_checkin(graph, phase=phase, yes=yes, out=_out, thread_id=THREAD_ID)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning -v`
Expected: all pass, including the unchanged `test_route_functions` (the pure `route_start` is untouched) and `test_intake_to_review_pauses_before_any_write` (intake still sets `phase: planning`).

- [ ] **Step 7: Definition of done and commit**

```bash
uv run ruff format packages/tri-planning && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-planning
git commit -m "feat(planning): route node derives phase and ids from the tables each run

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 4: Planning `apply_changes` and the thin apply node

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/nodes/apply.py`
- Test: `packages/tri-planning/tests/test_apply_node.py`

**Interfaces:**
- Consumes: `repo.owned_workout_ids`, `repo.insert_change`, `repo.set_goal_event`, `repo.mark_weeks_written`, `to_tp_call`, `result_workout_id`, `week_monday` (all already imported).
- Produces: `SESSION_OPS = ("create", "update", "delete", "move")`; `@dataclass ApplyResult(applied: list[CalendarChange], skipped: list[str], remaining: list[CalendarChange], error: str | None, tp_plan_applied: bool, sessions_changed: bool)` with `report(total: int) -> str`; `async apply_changes(deps, changes: Sequence[CalendarChange], thread_id: str, *, plan_id: int | None, goal_id: int | None, tp_plan_applied: bool = False) -> ApplyResult`; `make_apply_node(deps)` unchanged in signature and state contract.

- [ ] **Step 1: Write the failing tests**

Add to `packages/tri-planning/tests/test_apply_node.py`:

```python
from tri_planning.graph.nodes.apply import ApplyResult, apply_changes, make_apply_node
```

```python
async def test_apply_changes_direct_reports_sessions_changed_and_thread(nocommit, make_deps):
    gid, pid = seed(nocommit, create_tp_event=True)
    tp = FakeTp()
    deps = make_deps(ScriptedChatModel(script=[]), tp=tp)
    r = await apply_changes(deps, [create(0)], "coach", plan_id=pid, goal_id=gid)
    assert isinstance(r, ApplyResult)
    assert r.sessions_changed is True and r.remaining == [] and r.error is None
    assert len(r.applied) == 1 and r.skipped == [] and r.tp_plan_applied is False
    rows = nocommit.execute(
        "select thread_id from plan_changes where plan_id = %s", (pid,)
    ).fetchall()
    assert [row["thread_id"] for row in rows] == ["coach"]
    assert r.report(1).startswith("TrainingPeaks: applied 1 of 1 changes.")

    goal = repo.get_goal(nocommit, gid).goal
    r2 = await apply_changes(deps, [event_change(goal)], "coach", plan_id=pid, goal_id=gid)
    assert r2.sessions_changed is False and len(r2.applied) == 1


async def test_apply_changes_direct_holds_everything_without_tp(nocommit, make_deps):
    gid, pid = seed(nocommit)
    deps = make_deps(ScriptedChatModel(script=[]), tp=None)
    r = await apply_changes(deps, [create(0), create(1, "B")], "coach", plan_id=pid, goal_id=gid)
    assert r.applied == [] and len(r.remaining) == 2 and r.sessions_changed is False
    assert r.error is not None and "unavailable" in r.error
    assert "applied 0 of 2" in r.report(2) and "2 changes still pending" in r.report(2)


async def test_apply_changes_direct_stops_at_failure(nocommit, make_deps):
    gid, pid = seed(nocommit)
    deps = make_deps(ScriptedChatModel(script=[]), tp=FakeTp(fail_on_call=2))
    r = await apply_changes(
        deps, [create(0), create(1, "B"), create(2, "C")], "coach", plan_id=pid, goal_id=gid
    )
    assert [c.workout.title for c in r.applied] == ["Ride"]
    assert [c.workout.title for c in r.remaining] == ["B", "C"]
    assert r.sessions_changed is True and "boom" in r.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py -v`
Expected: FAIL with `ImportError: cannot import name 'ApplyResult'`.

- [ ] **Step 3: Lift the body into `apply_changes`**

Rewrite `packages/tri-planning/src/tri_planning/graph/nodes/apply.py`:

```python
"""Apply: the only place TrainingPeaks is written. `apply_changes` sends one call per change,
recording each as it goes, and stops at the first failure; the node is state plumbing around it.
The coach calls `apply_changes` directly with `thread_id="coach"`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from tri_core.mcp.client import McpToolError
from tri_planning import repo
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.state import PlanningState
from tri_planning.planning.models import CalendarChange
from tri_planning.planning.targets import week_monday
from tri_planning.planning.tp_calls import result_workout_id, to_tp_call

OWNED_OPS = ("update", "move", "delete")
SESSION_OPS = ("create", "update", "delete", "move")  # ops that change what the athlete trains
TP_UNAVAILABLE = "TrainingPeaks server unavailable; nothing applied, change set left pending."


def _label(c: CalendarChange) -> str:
    if c.workout is not None:
        return f"{c.op} {c.workout.date} {c.workout.sport} '{c.workout.title}'"
    return f"{c.op} {c.tp_workout_id or c.workout_date or ''}".strip()


@dataclass
class ApplyResult:
    applied: list[CalendarChange]
    skipped: list[str]
    remaining: list[CalendarChange]
    error: str | None
    tp_plan_applied: bool
    sessions_changed: bool  # any create/update/delete/move went through

    def report(self, total: int) -> str:
        lines = [f"TrainingPeaks: applied {len(self.applied)} of {total} changes."]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} changes still pending; "
                "they will be re-proposed next turn."
            )
        return "\n".join(lines)


async def apply_changes(
    deps: GraphDeps,
    changes: Sequence[CalendarChange],
    thread_id: str,
    *,
    plan_id: int | None,
    goal_id: int | None,
    tp_plan_applied: bool = False,
) -> ApplyResult:
    """Send each change to TrainingPeaks in order, recording every success in `plan_changes`
    under `thread_id`. Ownership: update/move/delete only agent-authored workouts unless
    `athlete_requested`. Stops at the first server error; the rest stay in `remaining`."""
    todo = list(changes)
    if deps.tp is None:
        return ApplyResult(
            applied=[],
            skipped=[],
            remaining=todo,
            error=TP_UNAVAILABLE,
            tp_plan_applied=tp_plan_applied,
            sessions_changed=False,
        )

    owned: set[str] = set()
    if plan_id is not None:
        with deps.connect() as conn:
            owned = repo.owned_workout_ids(conn, plan_id)

    applied: list[CalendarChange] = []
    skipped: list[str] = []
    remaining = list(todo)
    error: str | None = None
    written: set[Any] = set()

    for change in todo:
        if (
            change.op in OWNED_OPS
            and change.tp_workout_id not in owned
            and not change.athlete_requested
        ):
            skipped.append(
                f"{_label(change)}: not agent-authored (id {change.tp_workout_id}); dropped"
            )
            remaining.remove(change)
            continue
        try:
            name, args = to_tp_call(change)
            result = await deps.tp.call_json(name, args)
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        wid = result_workout_id(change, result)
        with deps.connect() as conn:
            repo.insert_change(
                conn,
                plan_id,
                thread_id,
                change,
                tp_workout_id=wid,
                result=result if isinstance(result, dict) else {"result": result},
            )
            if (
                change.op == "create_event"
                and goal_id is not None
                and isinstance(result, dict)
                and result.get("event_id") is not None
            ):
                repo.set_goal_event(conn, goal_id, str(result["event_id"]))
            conn.commit()
        applied.append(change)
        remaining.remove(change)
        if change.op == "create" and change.workout_date is not None:
            written.add(week_monday(change.workout_date))
        if change.op == "apply_plan":
            tp_plan_applied = True

    if plan_id is not None and written:
        with deps.connect() as conn:
            repo.mark_weeks_written(conn, plan_id, sorted(written))
            conn.commit()

    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        error=error,
        tp_plan_applied=tp_plan_applied,
        sessions_changed=any(c.op in SESSION_OPS for c in applied),
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(state: PlanningState, config: RunnableConfig) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        r = await apply_changes(
            deps,
            changes,
            str(config["configurable"]["thread_id"]),
            plan_id=state.get("plan_id"),
            goal_id=state.get("goal_id"),
            tp_plan_applied=bool(state.get("tp_plan_applied")),
        )
        update: dict[str, Any] = {
            "pending_changes": r.remaining,
            "pending_summary": state.get("pending_summary") if r.remaining else None,
            "last_error": r.error,
            "review_decision": None,
            "messages": [AIMessage(r.report(len(changes)))],
            "tp_plan_applied": r.tp_plan_applied,
        }
        if r.error is None and not r.remaining and not r.tp_plan_applied:
            update["phase"] = "active"
        return update

    return apply
```

Behaviour note: when the server is down the node used to return a bare message and no `tp_plan_applied` key; it now returns the standard report ("applied 0 of N ... stopped: TrainingPeaks server unavailable ...") and echoes the flag. `last_error` still starts with "TrainingPeaks server unavailable", which `run_checkin` and `test_refuses_without_tp_server` rely on.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning/tests/test_apply_node.py packages/tri-planning/tests/test_graph.py packages/tri-planning/tests/test_checkin.py -v`
Expected: all pass; the six pre-existing apply-node tests pass unchanged through the thin node.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-planning && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-planning
git commit -m "refactor(planning): lift apply into apply_changes returning ApplyResult; thin node

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 5: Planning embedded mode

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/graph.py`
- Test: `packages/tri-planning/tests/test_graph.py`, `packages/tri-planning/tests/test_graph_adjust.py`

**Interfaces:**
- Consumes: Task 3's `make_route_node`.
- Produces: `build_graph(deps, checkpointer, *, embedded: bool = False)`. When `embedded` is true, `review` and `apply` are not added and every path that names `"review"` resolves to `END`; the output state carries `pending_changes`, `pending_summary`, `changes_from` and `last_error`.

- [ ] **Step 1: Write the failing tests**

Add to `packages/tri-planning/tests/test_graph.py`:

```python
async def test_embedded_graph_has_no_review_and_ends_with_pending_changes(
    nocommit, make_deps, fake_tp
):
    model = ScriptedChatModel(script=[*intake_script(), week_call(300)])
    graph = build_graph(make_deps(model, tp=fake_tp), InMemorySaver(), embedded=True)
    assert "review" not in graph.nodes and "apply" not in graph.nodes
    out = await graph.ainvoke({"messages": [HumanMessage("Olympic Dec 13")]}, CFG)
    assert "__interrupt__" not in out
    assert (await graph.aget_state(CFG)).next == ()
    assert out["pending_changes"] and all(c.op == "create" for c in out["pending_changes"])
    assert out["changes_from"] == "design" and out["pending_summary"]
    assert fake_tp.calls == []
```

Add to `packages/tri-planning/tests/test_graph_adjust.py` (factor the move proposal used by both existing tests into `move_call()` at module level first, then use it here):

```python
def move_call():
    return tool_call(
        "propose_calendar_changes",
        {
            "summary": "move it",
            "changes": [
                {
                    "op": "move",
                    "tp_workout_id": "w1",
                    "new_date": (MONDAY + timedelta(days=4)).isoformat(),
                    "reason": "rest day",
                }
            ],
        },
    )


async def test_embedded_adjust_ends_with_pending_changes_and_no_interrupt(nocommit, make_deps):
    seed_active(nocommit)
    tp = FakeTp()
    model = ScriptedChatModel(script=[move_call(), AIMessage(content="Proposed a move.")])
    graph = build_graph(
        make_deps(model, tp=tp, today=MONDAY + timedelta(days=1), horizon=3),
        InMemorySaver(),
        embedded=True,
    )
    out = await graph.ainvoke({"messages": [HumanMessage("Move Wednesday to Friday.")]}, CFG)
    assert "__interrupt__" not in out and (await graph.aget_state(CFG)).next == ()
    assert [c.op for c in out["pending_changes"]] == ["move"]
    assert out["pending_summary"] == "move it" and out["changes_from"] == "adjust"
    assert tp.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_graph.py packages/tri-planning/tests/test_graph_adjust.py -v -k embedded`
Expected: FAIL with `TypeError: build_graph() got an unexpected keyword argument 'embedded'`.

- [ ] **Step 3: Implement embedded mode**

Replace `build_graph` in `packages/tri-planning/src/tri_planning/graph/graph.py`:

```python
def build_graph(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any], *, embedded: bool = False
) -> Any:
    """Compile the planning graph. With `embedded=True` there is no `review` or `apply`: every
    path that would pause at review ends the run instead, leaving `pending_changes`,
    `pending_summary` and `changes_from` in the output for the caller (the coach) to review."""
    review = END if embedded else "review"
    g: StateGraph[PlanningState] = StateGraph(PlanningState)
    g.add_node("route", make_route_node(deps))
    g.add_node("intake", make_intake_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("design", make_design_node(deps))
    g.add_node("adjust", make_adjust_node(deps))
    if not embedded:
        g.add_node("review", review_node)
        g.add_node("apply", make_apply_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        route_start,
        {"review": review, "intake": "intake", "targets": "targets", "adjust": "adjust"},
    )
    g.add_conditional_edges("intake", after_intake, {"targets": "targets", END: END})
    g.add_conditional_edges(
        "targets", after_targets, {"review": review, "design": "design", END: END}
    )
    g.add_edge("design", review)
    g.add_conditional_edges("adjust", after_adjust, {"review": review, END: END})
    if not embedded:
        g.add_conditional_edges("review", after_review, ["apply", "design", "adjust", END])
        g.add_conditional_edges("apply", after_apply, ["targets", END])
    return g.compile(checkpointer=checkpointer, name="tri-planning")
```

Add to the module docstring: `Embedded mode (build_graph(..., embedded=True)): no review or apply; every "review" target is END.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning -v`
Expected: all pass. The path maps are equivalent to the previous lists in standalone mode, so no standalone test changes.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-planning && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-planning
git commit -m "feat(planning): embedded mode ends with pending_changes and has no review or apply

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 6: Directed section in planning's adjust prompt

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/prompts/adjust.py`
- Test: `packages/tri-planning/tests/test_adjust_prompt.py`, `packages/tri-planning/tests/test_adjust_node.py`

**Interfaces:**
- Produces: `BRIEF_PREFIX = "Head coach brief:"`; `DIRECTED_RULES: str`; `render_adjust_prompt(ctx)` renders `ADJUST_RULES`, then `DIRECTED_RULES`, then the per-turn data (all stable text before `Today is`).

- [ ] **Step 1: Write the failing tests**

Add to `packages/tri-planning/tests/test_adjust_prompt.py` (extend the import to include `BRIEF_PREFIX`):

```python
from tri_planning.prompts.adjust import (
    BRIEF_PREFIX,
    AdjustContext,
    load_adjust_context,
    render_adjust_prompt,
)


def test_directed_section_is_stable_and_names_the_prefix():
    ctx = AdjustContext(
        today=date(2026, 9, 21),
        goal=TrainingGoal(**GOAL_ARGS),
        this_week=None,
        next_week=None,
        actual_tss_this_week=0,
        sessions=[],
        baseline={},
        owned=[],
        weeks_on_calendar=2,
        horizon=3,
        extension_needed=False,
    )
    text = render_adjust_prompt(ctx)
    assert BRIEF_PREFIX == "Head coach brief:" and BRIEF_PREFIX in text
    assert "smallest change set" in text and "ask one question" in text
    assert "athlete_requested" in text.split("Directed briefs")[1]
    assert text.index("Review checklist") < text.index("Directed briefs") < text.index("Today is")
```

Add to `packages/tri-planning/tests/test_adjust_node.py` (import `BRIEF_PREFIX` from `tri_planning.prompts.adjust`):

```python
async def test_directed_brief_ends_on_the_proposal_and_merges_the_designed_week(
    nocommit, make_deps
):
    gid, pid, targets = seed(nocommit)
    model = ScriptedChatModel(
        script=[
            tool_call("design_next_week", {}),
            tool_call("PlannedWeek", week_json(MONDAY + timedelta(weeks=1), targets[1].target_tss)),
            tool_call(
                "propose_calendar_changes",
                {
                    "summary": "drop tempo",
                    "changes": [
                        {"op": "delete", "tp_workout_id": "w1", "reason": "knee pain reported"}
                    ],
                },
                call_id="c2",
            ),
            AIMessage(content="Done."),
        ]
    )
    node = make_adjust_node(
        make_deps(model, tp=FakeTp(), today=MONDAY + timedelta(days=3), horizon=3)
    )
    brief = (
        f"{BRIEF_PREFIX} Knee pain reported today. Drop w1 (Wednesday tempo run) and design "
        "next week without running; hold weekly TSS within 10 percent of target."
    )
    out = await node(
        {"goal_id": gid, "plan_id": pid, "phase": "active", "messages": [HumanMessage(brief)]},
        CFG,
    )
    assert out["changes_from"] == "adjust" and out["pending_summary"] == "drop tempo"
    assert [c.op for c in out["pending_changes"]] == ["create", "create", "create", "delete"]
    assert repo.list_weeks(nocommit, pid)[1].designed is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_adjust_prompt.py packages/tri-planning/tests/test_adjust_node.py -v`
Expected: FAIL with `ImportError: cannot import name 'BRIEF_PREFIX'`.

- [ ] **Step 3: Add the directed rules**

In `packages/tri-planning/src/tri_planning/prompts/adjust.py`, after `ADJUST_RULES`:

```python
BRIEF_PREFIX = "Head coach brief:"  # the coach (tri-coach) starts every directed message with this

DIRECTED_RULES = f"""\
Directed briefs:
When the message begins with "{BRIEF_PREFIX}" it is an instruction from the athlete's head coach,
who has already reviewed the data and decided what must change. Satisfy that instruction with the
smallest change set that does it and nothing else: do not run the review checklist, do not propose
changes the brief did not ask for, and do not call design_next_week unless the brief asks for the
window to be extended. The brief names the signal, the lever and the constraint; hold the
constraint (for example "keep weekly TSS within 10 percent of target" or "keep Saturday's ride")
when choosing what to change. The lever order and the ownership rule still apply; set
athlete_requested only when the brief says the athlete asked for that change. When the brief is
ambiguous, ask one question in a short message and stop without calling propose_calendar_changes.
The review checklist is for the scheduled check-in and for the athlete's own messages."""
```

And in `render_adjust_prompt` change the first line to:

```python
    lines = [ADJUST_RULES, "", DIRECTED_RULES, "", f"Today is {ctx.today.isoformat()}."]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning -v`
Expected: all pass, including `test_render_flags_rpe_and_feeling_and_lists_owned_ids` (its `Lever order` before `Today is` ordering still holds).

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-planning && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-planning
git commit -m "feat(planning): adjust prompt gains a directed section for head-coach briefs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 7: Nutrition `apply_changes` and the thin apply node

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py`
- Test: `packages/tri-nutrition/tests/test_apply_node.py`

**Interfaces:**
- Consumes: the existing `write_change(deps, thread_id, change)`, `_server_down`, `S.get_profile`, `S.put_profile`, `apply_overrides`.
- Produces: `@dataclass ApplyResult(applied: list[NutritionChange], skipped: list[str], remaining: list[NutritionChange], held: list[NutritionChange], error: str | None, profile_updated: bool)` with `report(total: int, overrides: dict[str, Any] | None) -> str`; `async apply_changes(deps, store: BaseStore, changes: Sequence[NutritionChange], thread_id: str, *, overrides: dict[str, Any] | None) -> ApplyResult`; `make_apply_node(deps)` unchanged in signature and state contract.

- [ ] **Step 1: Write the failing tests**

Add to `packages/tri-nutrition/tests/test_apply_node.py`:

```python
from tri_nutrition.graph.nodes.apply import ApplyResult, apply_changes, make_apply_node
```

```python
async def test_apply_changes_direct_records_thread_and_persists_overrides(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    g = FakeGarmin()
    deps = make_deps(ScriptedChatModel(script=[]), garmin=g)
    r = await apply_changes(
        deps, mem_store, [day_target_change(target())], "coach", overrides={"activity_factor": 1.5}
    )
    assert isinstance(r, ApplyResult)
    assert [c.op for c in r.applied] == ["set_day_targets"]
    assert r.remaining == [] and r.held == [] and r.skipped == [] and r.error is None
    assert r.profile_updated is True
    assert (await S.get_profile(mem_store)).activity_factor == 1.5
    rows = ndb.execute("select thread_id from nutrition_changes").fetchall()
    assert [row["thread_id"] for row in rows] == ["coach"]
    text = r.report(1, {"activity_factor": 1.5})
    assert text.startswith("Applied 1 of 1 changes (Garmin 1, TrainingPeaks 0).")
    assert "profile updated" in text


async def test_apply_changes_direct_holds_when_the_server_is_down(ndb, make_deps, mem_store):
    deps = make_deps(ScriptedChatModel(script=[]), garmin=None)
    r = await apply_changes(deps, mem_store, [day_target_change(target())], "coach", overrides=None)
    assert r.applied == [] and len(r.remaining) == 1 and r.held == r.remaining
    assert r.error is not None and "Garmin server unavailable" in r.error
    assert r.profile_updated is False
    assert "1 change(s) still pending" in r.report(1, None)


async def test_apply_changes_direct_does_not_persist_overrides_on_partial(ndb, make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    repo.upsert_targets(ndb, [target()])
    deps = make_deps(ScriptedChatModel(script=[]), garmin=FakeGarmin(fail_on_call=1))
    r = await apply_changes(
        deps, mem_store, [day_target_change(target())], "coach", overrides={"activity_factor": 1.5}
    )
    assert r.error is not None and "boom" in r.error and r.profile_updated is False
    assert (await S.get_profile(mem_store)).activity_factor == 1.35
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_apply_node.py -v`
Expected: FAIL with `ImportError: cannot import name 'ApplyResult'`.

- [ ] **Step 3: Lift the body into `apply_changes`**

In `packages/tri-nutrition/src/tri_nutrition/graph/nodes/apply.py`, keep everything through `_server_down` unchanged (update the module docstring's second sentence to "`write_change` is shared with the `today` command; `apply_changes` is the batch the node and the coach both call."), add the imports `from collections.abc import Sequence` and `from dataclasses import dataclass`, and replace `make_apply_node` with:

```python
@dataclass
class ApplyResult:
    applied: list[NutritionChange]
    skipped: list[str]
    remaining: list[NutritionChange]
    held: list[NutritionChange]  # a subset of remaining: the server for these was down
    error: str | None
    profile_updated: bool

    def report(self, total: int, overrides: dict[str, Any] | None) -> str:
        n_garmin = sum(1 for c in self.applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in self.applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(self.applied)} of {total} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.profile_updated:
            lines.append(f"  profile updated: {overrides}")
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} change(s) still pending; they will be re-proposed next "
                "turn."
            )
        return "\n".join(lines)


async def apply_changes(
    deps: GraphDeps,
    store: BaseStore,
    changes: Sequence[NutritionChange],
    thread_id: str,
    *,
    overrides: dict[str, Any] | None,
) -> ApplyResult:
    """Send each change to its server in order, recording every success in `nutrition_changes`
    under `thread_id`. Changes whose server is down are held (kept in `remaining`); an ownership
    refusal drops the change; a server error stops the batch. `overrides` are written to the
    profile in the Store only when every change went through."""
    todo = list(changes)
    applied: list[NutritionChange] = []
    skipped: list[str] = []
    held: list[NutritionChange] = []
    remaining = list(todo)
    error: str | None = None
    for change in todo:
        if _server_down(deps, change):
            held.append(change)
            continue
        try:
            await write_change(deps, thread_id, change)
        except PermissionError as exc:
            skipped.append(f"{_label(change)}: {exc}; dropped")
            remaining.remove(change)
            continue
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        applied.append(change)
        remaining.remove(change)
    if error is None:
        remaining = [c for c in remaining if c in held]
    if held:
        servers = sorted({"Garmin" if c.op in GARMIN_OPS else "TrainingPeaks" for c in held})
        held_msg = (
            f"{' and '.join(servers)} server unavailable; {len(held)} change(s) held pending."
        )
        error = held_msg if error is None else f"{error}; {held_msg}"

    persisted = False
    if error is None and not remaining and overrides:
        base = await S.get_profile(store)
        if base is not None:
            await S.put_profile(store, apply_overrides(base, overrides))
            persisted = True
    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        held=held,
        error=error,
        profile_updated=persisted,
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        overrides = state.get("profile_overrides")
        r = await apply_changes(
            deps, store, changes, str(config["configurable"]["thread_id"]), overrides=overrides
        )
        clean = r.error is None and not r.remaining
        return {
            "pending_changes": r.remaining,
            "pending_summary": state.get("pending_summary") if r.remaining else None,
            "last_error": r.error,
            "review_decision": None,
            "profile_overrides": None if clean else overrides,
            "messages": [AIMessage(r.report(len(changes), overrides))],
        }

    return apply
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition/tests/test_apply_node.py packages/tri-nutrition/tests/test_graph.py -v`
Expected: all pass; the eleven pre-existing apply-node tests pass unchanged through the thin node.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-nutrition && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "refactor(nutrition): lift apply into apply_changes returning ApplyResult; thin node

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 8: Nutrition embedded mode and the regenerate entry

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/graph.py`
- Test: `packages/tri-nutrition/tests/test_graph.py`

**Interfaces:**
- Produces: `route_start(state)` returns `"targets"` when `targets_requested` is set and the messages list is empty or its last message is not a `HumanMessage` (after the `pending_changes` rule, before the profile rule); `build_graph(deps, checkpointer, store, *, embedded: bool = False)`. When `embedded` is true, `review` and `apply` are not added, `fuel -> END`, and `route`'s `"review"` path resolves to `END`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-nutrition/tests/test_graph.py`, extend `test_route_functions`:

```python
def test_route_functions():
    assert route_start({"pending_changes": [1]}) == "review"
    assert route_start({"has_profile": False}) == "intake"
    assert route_start({"has_profile": True}) == "checkin"
    # the coach's regenerate entry: the flag with no new athlete message goes straight to targets
    assert route_start({"targets_requested": True, "has_profile": True}) == "targets"
    assert route_start({"targets_requested": True, "has_profile": True, "messages": []}) == "targets"
    ended = [HumanMessage("hi"), AIMessage(content="ok")]
    assert route_start({"targets_requested": True, "has_profile": True, "messages": ended}) == "targets"
    fresh = [HumanMessage("hi")]
    assert route_start({"targets_requested": True, "has_profile": True, "messages": fresh}) == "checkin"
    assert route_start({"pending_changes": [1], "targets_requested": True}) == "review"
    ...  # the after_review assertions stay as they are
```

Add two tests:

```python
async def test_embedded_graph_has_no_review_and_ends_with_pending_changes(ndb, make_deps, mem_store):
    g = FakeGarmin()
    deps = make_deps(ScriptedChatModel(script=intake_script()), garmin=g, horizon=7)
    graph = build_graph(deps, InMemorySaver(), mem_store, embedded=True)
    assert "review" not in graph.nodes and "apply" not in graph.nodes
    out = await graph.ainvoke({"messages": [HumanMessage("set up my nutrition")]}, CFG)
    assert "__interrupt__" not in out and (await graph.aget_state(CFG)).next == ()
    assert len(out["pending_changes"]) == 1 and "kcal" in out["pending_summary"]
    assert out["regenerate_from"] == "intake" and g.calls == []


async def test_regenerate_entry_routes_to_targets_and_ends_with_pending_changes(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    g = FakeGarmin()
    deps = make_deps(ScriptedChatModel(script=[]), garmin=g, horizon=3)  # no model call at all
    graph = build_graph(deps, InMemorySaver(), mem_store, embedded=True)
    out = await graph.ainvoke({"targets_requested": True, "regenerate_from": "checkin"}, CFG)
    assert "__interrupt__" not in out and (await graph.aget_state(CFG)).next == ()
    assert [c.op for c in out["pending_changes"]] == ["set_day_targets"]
    assert out["pending_changes"][0].day == MONDAY and g.calls == []
    assert out["targets_requested"] is False and out["last_error"] is None
    assert len(repo.list_targets(ndb, MONDAY, MONDAY + timedelta(days=2))) == 3
    assert out.get("messages", []) == []  # nothing was said; the caller narrates
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_graph.py -v -k "route_functions or embedded or regenerate"`
Expected: `test_route_functions` fails on the first `targets_requested` assertion (`'checkin' == 'targets'`); the other two fail with `TypeError: build_graph() got an unexpected keyword argument 'embedded'`.

- [ ] **Step 3: Implement the regenerate rule and embedded mode**

In `packages/tri-nutrition/src/tri_nutrition/graph/graph.py`, add `from langchain_core.messages import HumanMessage`, and replace `route_start` and `build_graph`:

```python
def _new_athlete_message(state: NutritionState) -> bool:
    msgs = state.get("messages") or []
    return bool(msgs) and isinstance(msgs[-1], HumanMessage)


def route_start(state: NutritionState) -> str:
    if state.get("pending_changes"):
        return "review"
    if state.get("targets_requested") and not _new_athlete_message(state):
        # The regenerate entry: the coach invokes the graph with the flag and no message after a
        # plan change was applied. In a standalone run the flag is always clear here.
        return "targets"
    return "checkin" if state.get("has_profile") else "intake"
```

```python
def build_graph(
    deps: GraphDeps,
    checkpointer: BaseCheckpointSaver[Any],
    store: BaseStore,
    *,
    embedded: bool = False,
) -> Any:
    """Compile the nutrition graph. With `embedded=True` there is no `review` or `apply`: `fuel`
    ends the run and a targets violation ends it, leaving `pending_changes`, `pending_summary`,
    `regenerate_from` and `last_error` in the output for the caller (the coach) to review."""
    review = END if embedded else "review"
    g: StateGraph[NutritionState] = StateGraph(NutritionState)
    g.add_node("route", route_node)
    g.add_node("intake", make_intake_node(deps))
    g.add_node("checkin", make_checkin_node(deps))
    g.add_node("targets", make_targets_node(deps))
    g.add_node("fuel", make_fuel_node(deps))
    if not embedded:
        g.add_node("review", review_node)
        g.add_node("apply", make_apply_node(deps))

    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        route_start,
        {"review": review, "targets": "targets", "intake": "intake", "checkin": "checkin"},
    )
    g.add_conditional_edges("intake", after_intake, {"targets": "targets", END: END})
    g.add_conditional_edges("checkin", after_checkin, {"targets": "targets", END: END})
    g.add_conditional_edges("targets", after_targets, {"fuel": "fuel", END: END})
    g.add_edge("fuel", review)
    if not embedded:
        g.add_conditional_edges("review", after_review, ["apply", "intake", "checkin", END])
        g.add_edge("apply", END)
    return g.compile(checkpointer=checkpointer, store=store, name="tri-nutrition")
```

Update the module docstring: add `route   -> targets  (targets_requested with no new athlete message: the coach's regenerate entry)` after the existing `route` line, and `Embedded mode (build_graph(..., embedded=True)): no review or apply; fuel and a targets violation end the run.` at the end.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition -v`
Expected: all pass. If `test_regenerate_entry_...` fails inside the `fuel` node with `IndexError` from `ScriptedChatModel` (a model call happened), the horizon contains a qualifying session from a leftover plan; the `db` fixture rolls back, so this means another test leaked rows through a real commit. Find that test before changing this one.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-nutrition && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): embedded mode and the regenerate entry straight to targets

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 9: Directed section in nutrition's check-in prompt

**Files:**
- Modify: `packages/tri-nutrition/src/tri_nutrition/prompts/checkin.py`
- Create: `packages/tri-nutrition/tests/test_checkin_prompt.py`
- Test: `packages/tri-nutrition/tests/test_checkin_node.py`

**Interfaces:**
- Produces: `BRIEF_PREFIX = "Head coach brief:"` in `tri_nutrition.prompts.checkin`; `render_checkin_prompt(today)` includes the directed paragraph after the check-in steps.

- [ ] **Step 1: Write the failing tests**

`packages/tri-nutrition/tests/test_checkin_prompt.py`:

```python
from datetime import date

from tri_nutrition.prompts.checkin import BRIEF_PREFIX, CHECKIN_REQUEST, render_checkin_prompt


def test_directed_paragraph_names_the_prefix_and_bounds_the_run():
    text = render_checkin_prompt(date(2026, 9, 14))
    assert BRIEF_PREFIX == "Head coach brief:" and BRIEF_PREFIX in text
    assert "nothing else" in text and "at most one call" in text
    assert "Today is 2026-09-14" in text and CHECKIN_REQUEST in text
    # the check-in steps come first; the directed paragraph is a later carve-out
    assert text.index("run these") < text.index(BRIEF_PREFIX) < text.index("Never diagnose")
```

Add to `packages/tri-nutrition/tests/test_checkin_node.py` (import `BRIEF_PREFIX` from `tri_nutrition.prompts.checkin`):

```python
async def test_brief_turn_proposes_once_and_asks_nothing(make_deps, mem_store):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    model = ScriptedChatModel(
        script=[
            propose({"activity_factor": 1.45}, "race block starts; training load up"),
            AIMessage(content="Proposed activity factor 1.45 for the race block."),
        ]
    )
    graph = one_node_graph(make_checkin_node(make_deps(model)), mem_store)
    brief = (
        f"{BRIEF_PREFIX} Training load rises 20 percent from Monday for the race block. Raise "
        "activity_factor to 1.45; keep the goal and everything else."
    )
    out = await graph.ainvoke({"messages": [HumanMessage(brief)]}, CFG)
    assert out["targets_requested"] is True and out["regenerate_from"] == "checkin"
    assert out["profile_overrides"] == {"activity_factor": 1.45} and model.calls == 2
    assert (await S.get_profile(mem_store)).activity_factor == 1.35  # nothing written yet
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-nutrition/tests/test_checkin_prompt.py packages/tri-nutrition/tests/test_checkin_node.py -v`
Expected: FAIL with `ImportError: cannot import name 'BRIEF_PREFIX'`.

- [ ] **Step 3: Add the directed paragraph**

In `packages/tri-nutrition/src/tri_nutrition/prompts/checkin.py`, after `CHECKIN_REQUEST`:

```python
BRIEF_PREFIX = "Head coach brief:"  # the coach (tri-coach) starts every directed message with this
```

and in `render_checkin_prompt`, insert this paragraph between the "Outside a check-in, ..." paragraph and the "Never diagnose." paragraph:

```python
When the message begins with "{BRIEF_PREFIX}" it is an instruction from the athlete's head coach,
who has already reviewed the data and decided what must change. Execute that instruction and
nothing else: do not run the check-in steps, do not ask the athlete anything, and make at most one
call, to propose_target_changes or to save_nutrition_profile, whichever the brief needs. The brief
names the signal, the lever and the constraint; hold the constraint (for example "keep the goal")
when choosing overrides. When the brief is ambiguous, say what is unclear in one line and call
nothing. The check-in steps are for "{CHECKIN_REQUEST}" and for the athlete's own messages.
```

(The function body is one f-string; the paragraph goes inside it with a blank line on each side.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-nutrition -v`
Expected: all pass.

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-nutrition && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-nutrition
git commit -m "feat(nutrition): check-in prompt gains a directed paragraph for head-coach briefs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

---

### Task 10: Docs, Obsidian export, full verification

**Files:**
- Modify: `packages/tri-core/src/tri_core/mcp/README.md:11-17` (modules table) and `:45-47` (agent path)
- Modify: `packages/tri-planning/README.md:8-58`
- Modify: `packages/tri-nutrition/README.md:42-72`
- Modify: `README.md:146-` (Status)
- Copy: this plan and every edited markdown file into the Obsidian vault

- [ ] **Step 1: tri-core `mcp/README.md`**

In the modules block add, after the `live_tools.py` line:

```
  caller.py      ToolsCaller: a ToolCaller over adapter-bound tools, so one session serves both
                 the model (BaseTools) and call_json (the sync/apply path)
```

Change the `live_tools.py` line to `open_live_servers (tools per server) and open_live_tools (flattened); the generic opener used by tri-analyze, tri-planning and tri-coach`.

Replace the last sentence of the "Agent path" paragraph with:

```
Each agent package wraps `open_live_tools` with its own allow-lists. `open_live_servers` yields
the same tools grouped by server name (a dead server is absent), and `caller.ToolsCaller(tools)`
turns one server's list into a `ToolCaller`: `call_json` finds the tool by name, awaits it, joins
the adapter's text content blocks, and parses the text with `parse_tool_text`. That is how a
process that already holds a session for the model also serves the graph deps' `tp` and `garmin`
callers without a second subprocess (tri-coach).
```

- [ ] **Step 2: tri-planning `README.md`**

Change the first sentence of "The graph" to ``build_graph(deps, checkpointer, *, embedded=False)`` and, in the mermaid block, replace the four `START` edges with:

```
    START([START]) --> route
    route -->|pending_changes| review
    route -->|no active goal| intake
    route -->|active goal, no plan| targets
    route -->|active plan| adjust
```

Add to the node table, as its first row:

```
| `route` | none | nothing | `training_goals`, `training_plans` | `phase`, `goal_id`, `plan_id` derived from the tables every run (a fresh thread and a stateless consultation start where the database says) |
```

After the invariants paragraph add:

```
**Embedded mode.** `build_graph(..., embedded=True)` adds no `review` or `apply` node and sends
every edge that would reach `review` to `END`, so the run ends with `pending_changes`,
`pending_summary` and `changes_from` in the output state. The coach (`tri-coach`) runs the
graph this way, reviews the proposal itself, and writes through `apply_changes` in
`graph/nodes/apply.py` with `thread_id="coach"`. The adjust prompt treats a message starting
with `Head coach brief:` as a bounded instruction to satisfy and nothing else; the review
checklist is for `tri-planning check-in` and the athlete's own messages.
```

- [ ] **Step 3: tri-nutrition `README.md`**

Change the first sentence of "The graph (Plan 2)" to ``build_graph(deps, checkpointer, store, *, embedded=False)`` and add to the mermaid block, after the three `route -->` lines:

```
    route -->|targets_requested, no new message| targets
```

After the mermaid block add:

```
**Regenerate entry and embedded mode.** Invoking the graph with `{"targets_requested": true,
"regenerate_from": "checkin"}` and no message routes straight to `targets`, which rebuilds the
horizon from the stored plan; the coach uses it after a plan change has been applied.
`build_graph(..., embedded=True)` adds no `review` or `apply`: `fuel` ends the run and so does
a targets violation, leaving `pending_changes` and `pending_summary` for the coach to review;
writes then go through `apply_changes` in `graph/nodes/apply.py` with `thread_id="coach"`.
The check-in prompt treats a message starting with `Head coach brief:` as a bounded instruction
to execute and nothing else. `tri-nutrition today` is unchanged.
```

- [ ] **Step 4: Root `README.md` status**

Append to the Status list:

```
- tri-coach milestone 1 (2026-09-12): planning route node, embedded mode and `apply_changes` in
  planning and nutrition, nutrition regenerate entry, directed prompt sections, tri-core
  `open_live_servers` and `ToolsCaller`; tracked in
  `docs/superpowers/plans/2026-09-12-tri-coach-01-sub-package-preparation.md`. Coach v1 pending.
```

- [ ] **Step 5: Full definition of done**

```bash
uv run ruff format packages && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
```
Expected: every command exits 0. Then confirm the standalone CLIs still start and route as before:

```bash
uv run tri-planning --help && uv run tri-nutrition --help
uv run python -c "
from datetime import date
from tri_planning.prompts.adjust import BRIEF_PREFIX as P
from tri_nutrition.prompts.checkin import BRIEF_PREFIX as N
assert P == N == 'Head coach brief:'; print('prefixes agree')"
```

- [ ] **Step 6: Obsidian export**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p "$V/docs/superpowers/plans" "$V/packages/tri-core/src/tri_core/mcp" "$V/packages/tri-planning" "$V/packages/tri-nutrition"
cp docs/superpowers/plans/2026-09-12-tri-coach-01-sub-package-preparation.md "$V/docs/superpowers/plans/"
cp packages/tri-core/src/tri_core/mcp/README.md "$V/packages/tri-core/src/tri_core/mcp/readme.md"
cp packages/tri-planning/README.md "$V/packages/tri-planning/readme.md"
cp packages/tri-nutrition/README.md "$V/packages/tri-nutrition/readme.md"
cp README.md "$V/readme.md"
```
(If the vault already holds these READMEs under a different kebab-case name from an earlier export, overwrite that file instead of adding a second copy: `ls "$V"/packages/tri-planning` first.)

- [ ] **Step 7: Commit**

```bash
git add README.md packages/tri-core/src/tri_core/mcp/README.md packages/tri-planning/README.md packages/tri-nutrition/README.md docs/superpowers/plans/2026-09-12-tri-coach-01-sub-package-preparation.md
git commit -m "docs(coach): plan 1 READMEs; route node, embedded mode, ToolsCaller, directed prompts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QEeNWmAHTuWBXqvsmWi4q2"
```

- [ ] **Step 8: Finish the branch**

Use `superpowers:finishing-a-development-branch`. The expected outcome, as with the earlier plans, is a fast-forward merge of `feat/tri-coach-01` into `main` and removal of the worktree; the spec's milestone 2 plan starts from the merged `main`.

---

## Self-review against the spec

**Spec coverage (§7, §13 milestone 1):**
- §7.1 `route` node deriving phase, goal_id, plan_id; `route_start` keeps the pending rule; standalone chat unchanged: Task 3.
- §7.1 embedded mode with path maps sending `"review"` to `END`: Task 5.
- §7.1 `apply_changes(deps, changes, thread_id, *, plan_id, goal_id, tp_plan_applied) -> ApplyResult` with `sessions_changed`: Task 4.
- §7.1 directed adjust section (minimal change set, lever order, ownership, one question when ambiguous, checklist only for the check-in): Task 6.
- §7.2 embedded mode (fuel ends, targets violation ends, no review/apply): Task 8.
- §7.2 `apply_changes(deps, store, changes, thread_id, *, overrides) -> ApplyResult`: Task 7.
- §7.2 regenerate entry (`targets_requested` with no new `HumanMessage`); `tri-nutrition today` unchanged: Task 8.
- §7.2 directed check-in section: Task 9.
- §7.3 `open_live_servers` with `open_live_tools` as the flattened view; `ToolsCaller` with `parse_tool_text` and `McpToolError`: Tasks 1 and 2. The union allow-list and the coach's wiring are Plan 2.
- §11 tests named for milestone 1: `ToolsCaller` over fake tools including the empty and error conventions (Task 2); embedded mode ends with `pending_changes` and has no `review` node (Tasks 5, 8); regenerate routes to `targets` (Task 8); `route` derives all three phases (Task 3); existing apply tests pass unchanged through the thin node and again through `apply_changes` directly (Tasks 4, 7); the directed adjust sub-agent ends on `propose_calendar_changes` and merges `design_next_week` output (Task 6).
- §15 open item 4 (adapter result shape) is answered from the adapter source in "Spec deviations"; items 1 to 3 are Plan 2.
- §13 "every existing CLI behaves as before": standalone tests are untouched except where they passed state the route node now derives (Task 3) or the phase argument (Task 3). Plan 2 should note in the spec's status line that milestone 1 is done.

**Placeholder scan:** every code step carries its code; no "similar to", "TBD" or "add handling" phrases remain. Task 3 Step 5 shows `...  # unchanged` inside `run_checkin` for the two blocks that do not change; the full function is in `packages/tri-planning/src/tri_planning/checkin.py:20-65` on `main`.

**Type consistency:** `ApplyResult` is defined per package with the same field names where they overlap (`applied`, `skipped`, `remaining`, `error`) and the domain-specific extras the spec names (`tp_plan_applied`, `sessions_changed`; `held`, `profile_updated`). `apply_changes` signatures match spec §7.1 and §7.2 plus the documented `tp_plan_applied` default. `BRIEF_PREFIX` is the same literal in both prompt modules and Task 10 Step 5 asserts it. `derive_phase` returns `GraphPhase` and `PlanningState.phase` is typed with it. `run_checkin`'s `phase` is a `str` (it compares to `"active"` only).
