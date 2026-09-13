# tri-coach Plan 3 of 4: Wellness Consult Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the head coach read access to everything `tri-wellness` knows: an `ask_wellness` agent-as-tool that runs wellness's chat agent on a throwaway thread, and a lab summary line in the coach's per-turn context block, so lab findings inform the coach's planning and nutrition briefs. This is spec milestone 3 (§6.6). Nothing the coach does writes a wellness row.

**Architecture:** `tools/wellness.py` mirrors `tools/analyst.py`: wellness's `build_agent` over `query_training_db` (with `WELLNESS_SCHEMA_DOC`) and its three findings tools, wellness's own `render_chat_prompt`, a private `InMemorySaver`, thread `wellness-<uuid>`, final text returned. `context.py` gains `LabSummary` (latest panel, its report, markers outside optimal, the report's Priorities) rendered as one line after the nutrition line. `CoachSettings` reads `TRI_ATHLETE_SEX` as optional; `CoachDeps` gains `wellness_model` and `wellness_registry`; when the registry is `None` the tool is not bound and the line says labs are not configured, so a coach without labs behaves exactly as milestone 2. The coach prompt's routing guide and memory policy gain lab lines; `PROMPT_VERSION` becomes `"2"`.

**Tech Stack:** langgraph 1.2.11, langchain 1.4.0 `create_agent`, pydantic 2, pydantic-settings, psycopg 3, pytest with `tri_core.testing.ScriptedChatModel` and the rolled-back `db` fixture; `tri_wellness` (registry, repo, findings tools, chat prompt, `build_agent`, `testing.seed_panel`, `testing.REPORT_OK`).

**Spec:** `docs/superpowers/specs/2026-09-11-tri-coach-design.md`, revised 2026-09-13 (§4 layout, §6.3 coach tools, §6.4 prompt, §6.6 the wellness consult, §9 errors, §10 configuration, §11 testing, §13 milestone 3, §14). Companion: `docs/superpowers/specs/2026-09-10-tri-wellness-design.md` (§5 data model, §11 chat, §18 out of scope). Plans 1 and 2 are merged; `main` is at a0b1859 (spec amendment on top of 00ed820).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed; every command runs from the worktree root as `uv run ...`.
- `tri-coach` gains the workspace dependency `tri-wellness` (spec §10). No other package gains a dependency; no new third-party dependencies. `tri-wellness` is already a workspace member, so the root `pyproject.toml` is untouched; `uv.lock` changes and is committed.
- Settings: `TRI_ATHLETE_SEX` is read by the coach as optional (`male` | `female` | unset). `.env.example` already carries `TRI_ATHLETE_SEX=male`; do not change it.
- Invariants (spec §6.3, §6.6), preserved by construction: no write tool is ever bound to a model; the coach imports no wellness write function (`insert_panel`, `insert_report`, `run_report`, the ingest graph); `tri_wellness.repo` readers and `tri_wellness.tools.findings` are the only wellness entry points; wellness binds no MCP session, so `servers.py` is untouched; the sub-agents (planning, nutrition) never read lab tables.
- Standalone CLIs (`tri-wellness`, `tri-planning`, `tri-nutrition`, `tri-analyze`) are untouched; no edits under `packages/tri-wellness`, `packages/tri-planning`, `packages/tri-nutrition`, `packages/tri-analyze`, `packages/tri-core`.
- No migration: `migrations/005_wellness.sql` is applied to both databases. Tests write only through the rolled-back `db` fixture. A coach test that needs the lab tables uses the `ldb` fixture (Task 1), which skips when the tables are missing; for this plan's definition of done those tests must run, not skip.
- `LANGSMITH_TRACING=false` in `.env`; tests must not depend on tracing.
- Git commits are permitted (Brian's standing permission). Commit per task on the feature branch; end every commit message with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP
  ```
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-coach-03 -b feat/tri-coach-03 main`, copy `.env`, `uv sync` there. Other Claude sessions share the main checkout.
- Definition of done per task, in order: `uv run ruff format packages/tri-coach`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`. The only acceptable pytest warning is the pre-existing langsmith `ast.Str` DeprecationWarning. Baseline before Task 1: `716 passed, 5 skipped`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case file name (`readme.md` for the READMEs).

### Facts verified while writing this plan (against `main` a0b1859)

1. `tri_wellness.agent.build_agent(model, tools, system_prompt, checkpointer=None)` wraps `create_agent` with `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`; `checkpointer or InMemorySaver()`. Same shape as `tri_analyze.agent.agent.build_agent`.
2. `tri_wellness.prompts.chat.render_chat_prompt(profile, sex, panels, latest_report, today, tool_names) -> str`; `tri_wellness.report.athlete_profile(conn) -> dict | None`; `tri_wellness.report.extract_section(md, title) -> str | None` (level-2 `## Title` body; `REPORT_OK` has `## Priorities`).
3. `tri_wellness.tools.findings.make_findings_tools(connect, registry) -> list[BaseTool]` (sync `@tool`s named `get_panel_findings`, `get_marker_spec`, `get_marker_history`; all read-only) and `WELLNESS_SCHEMA_DOC` (second argument to `tri_core.db.sql_tool.make_query_tool(url, extra_doc)`).
4. `tri_wellness.ranges.registry.load_registry(sex) -> MarkerRegistry` with `.sex` and `.version`; `tri_wellness.config.Sex = Literal["male", "female"]`; `WellnessSettings.tri_athlete_sex` is required there, optional here.
5. `tri_wellness.repo`: `latest_panel_id(conn) -> int | None`, `get_panel(conn, id) -> StoredPanel | None` (`drawn_on`, `lab_name`), `list_panels(conn) -> list[PanelSummary]`, `latest_report_for_panel(conn, id) -> StoredReport | None` (`findings: list[Finding]`, `report_md`, `created_at: datetime`), `insert_report(conn, panel_id, ranges_version, findings, report_md) -> int` (tests only).
6. `tri_wellness.labs.models.Finding(marker, display, system, value, unit, conventional_status, functional_status, functional_range, previous=None, delta_pct=None, active_confounders=[], athlete_note="")`; `FunctionalStatus = Literal["low", "suboptimal_low", "optimal", "suboptimal_high", "high"]`.
7. `tri_wellness.testing.seed_panel(conn, drawn_on, rows: list[tuple[str, float, str]], lab="Quest", context=None) -> int` and `REPORT_OK` (a full report markdown). `ferritin` and `hs_crp` are registry markers used by wellness's own tests.
8. Coach side: `CoachDeps(model, analyst_model, connect, db_url, planning_deps, nutrition_deps, analyst_tools, max_consults=2, today=date.today)`; `make_deps(settings, model, servers, *, today)`; `make_coach_node` binds `[analyst, *make_handoff_tools(), *make_memory_tools(deps.today)]`; `load_context(conn, store, today, pending)`; `render_context` order: today, thresholds, plan lines, nutrition line, last-7-days lines, pending line; `tri_coach.testing.make_test_deps(nocommit, *, coach, planning, nutrition, analyst, tp=None, garmin=None, today=MONDAY, max_consults=2)`; `tests/conftest.py` has `nocommit`, `mem_store`, `ndb`, `make_deps`; `test_graph.py` has `scripted(**scripts)` and `graph_for(make_deps, mem_store, *, tp=None, **scripts)` and monkeypatches `nodes.coach.make_subagent` to capture the rendered prompt.
9. `graph/nodes/planning.py` defines `last_ai_text(messages)`; `graph/nodes/nutrition.py` imports it from there; `tools/analyst.py` has its own private `_text` loop. Task 2 moves the helper to `tri_coach/text.py` and uses it in all three places.

---

## File Structure

```
packages/tri-coach/
  pyproject.toml                       + tri-wellness dependency and workspace source
  src/tri_coach/
    config.py                          + tri_athlete_sex: Sex | None = None
    text.py                            NEW: last_ai_text(messages) shared by analyst, wellness, planning
    context.py                         + LabSummary, load_lab_summary, labs_enabled/labs on CoachContext,
                                         _labs_line after the nutrition line, load_context(..., labs_enabled=)
    testing.py                         make_test_deps(..., wellness=None, registry=None)
    graph/deps.py                      CoachDeps + wellness_model, wellness_registry; make_deps loads the registry
    graph/nodes/coach.py               binds ask_wellness when the registry is present; passes labs_enabled
    graph/nodes/planning.py            imports last_ai_text from tri_coach.text (definition removed)
    graph/nodes/nutrition.py           imports last_ai_text from tri_coach.text
    tools/analyst.py                   uses last_ai_text
    tools/wellness.py                  NEW: wellness_tools, make_wellness_tool (ask_wellness)
    prompts/coach.py                   PROMPT_VERSION "2"; wellness routing and memory lines
    cli.py                             /status and /prompt snapshot pass labs_enabled
  tests/
    conftest.py                        + ldb, registry fixtures
    test_config.py                     + optional sex
    test_servers.py                    + make_deps loads the registry only when sex is set
    test_tools.py                      + ask_wellness tests
    test_context.py                    + lab line in every state
    test_prompt.py                     + wellness phrases, PROMPT_VERSION "2"
    test_graph.py                      + lab question through ask_wellness; tool absent when unconfigured
  README.md                            wellness consult section, node table, status
README.md (root)                       dependency sentence, coach row, run line, status entry
docs/superpowers/specs/2026-09-11-tri-coach-design.md   status line only
```

---

### Task 1: Dependency, settings, deps and test doubles

**Files:**
- Modify: `packages/tri-coach/pyproject.toml`, `packages/tri-coach/src/tri_coach/config.py`, `packages/tri-coach/src/tri_coach/graph/deps.py`, `packages/tri-coach/src/tri_coach/testing.py`, `packages/tri-coach/tests/conftest.py`
- Test: `packages/tri-coach/tests/test_config.py`, `packages/tri-coach/tests/test_servers.py`

**Interfaces:**
- Consumes: `tri_wellness.config.Sex`; `tri_wellness.ranges.registry.load_registry(sex) -> MarkerRegistry`, `MarkerRegistry`.
- Produces: `CoachSettings.tri_athlete_sex: Sex | None = None`; `CoachDeps.wellness_model: BaseChatModel` and `CoachDeps.wellness_registry: MarkerRegistry | None = None`; `make_deps` sets both; `make_test_deps(..., wellness: BaseChatModel | None = None, registry: MarkerRegistry | None = None)`; fixtures `ldb` (rolled-back connection with the lab tables present) and `registry` (`load_registry("male")`).

- [ ] **Step 1: Worktree**

```bash
cd /Users/brian/Development/paradigm/fitness_agents/triathlon_agent
git worktree add ../triathlon_agent-coach-03 -b feat/tri-coach-03 main
cp .env ../triathlon_agent-coach-03/.env
cd ../triathlon_agent-coach-03 && uv sync && uv run pytest -q 2>&1 | tail -1
```
Expected: `716 passed, 5 skipped, 1 warning`. Every later step runs in `../triathlon_agent-coach-03`.

- [ ] **Step 2: Write the failing tests**

Append to `packages/tri-coach/tests/test_config.py`:
```python
def test_athlete_sex_is_optional_for_the_coach(monkeypatch):
    monkeypatch.delenv("TRI_ATHLETE_SEX", raising=False)
    assert CoachSettings(_env_file=None).tri_athlete_sex is None
    monkeypatch.setenv("TRI_ATHLETE_SEX", "female")
    assert CoachSettings(_env_file=None).tri_athlete_sex == "female"
```

Append to `packages/tri-coach/tests/test_servers.py`:
```python
def test_make_deps_loads_the_wellness_registry_only_when_sex_is_set(monkeypatch):
    servers = Servers()
    model = ScriptedChatModel(script=[])
    monkeypatch.delenv("TRI_ATHLETE_SEX", raising=False)
    deps = make_deps(CoachSettings(_env_file=None), model, servers)
    assert deps.wellness_registry is None and deps.wellness_model is model
    monkeypatch.setenv("TRI_ATHLETE_SEX", "male")
    deps = make_deps(CoachSettings(_env_file=None), model, servers)
    assert deps.wellness_registry is not None and deps.wellness_registry.sex == "male"
```

Append to `packages/tri-coach/tests/conftest.py`:
```python
@pytest.fixture
def ldb(nocommit):
    if nocommit.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied")
    return nocommit


@pytest.fixture
def registry():
    from tri_wellness.ranges.registry import load_registry

    return load_registry("male")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_config.py packages/tri-coach/tests/test_servers.py -q`
Expected: the two new tests fail (`ValidationError: extra` or `AttributeError: 'CoachDeps' object has no attribute 'wellness_registry'`); the rest pass.

- [ ] **Step 4: Dependency and settings**

`packages/tri-coach/pyproject.toml`: add `"tri-wellness",` after `"tri-nutrition",` in `dependencies`, and `tri-wellness = { workspace = true }` under `[tool.uv.sources]`. Then `uv sync`.

`packages/tri-coach/src/tri_coach/config.py`:
```python
"""Coach settings: the shared tri_core Settings plus the coach's own knobs."""

from functools import lru_cache

from tri_core.config import Settings
from tri_wellness.config import Sex


class CoachSettings(Settings):
    tri_coach_langsmith_project: str = "tri_coach"
    tri_coach_max_consults_per_domain: int = 2
    # Optional here (required by tri-wellness itself): unset means no wellness consult.
    tri_athlete_sex: Sex | None = None


@lru_cache(maxsize=1)
def get_coach_settings() -> CoachSettings:
    return CoachSettings()
```

- [ ] **Step 5: Deps and test doubles**

`packages/tri-coach/src/tri_coach/graph/deps.py`: add the import `from tri_wellness.ranges.registry import MarkerRegistry, load_registry`; extend the dataclass and `make_deps`:
```python
@dataclass
class CoachDeps:
    model: BaseChatModel  # the coach
    analyst_model: (
        BaseChatModel  # the analyst run inside ask_analyst (scripted separately in tests)
    )
    connect: ConnectFactory
    db_url: str
    planning_deps: PlanningDeps
    nutrition_deps: NutritionDeps
    analyst_tools: list[BaseTool]
    wellness_model: BaseChatModel  # the lab interpreter run inside ask_wellness
    wellness_registry: MarkerRegistry | None = None  # None: labs not configured, no tool bound
    max_consults: int = 2
    today: Callable[[], date] = date.today
```
In `make_deps`, before the `return`:
```python
    registry = load_registry(settings.tri_athlete_sex) if settings.tri_athlete_sex else None
```
and in the `CoachDeps(...)` call add `wellness_model=model,` and `wellness_registry=registry,` after `analyst_tools=...`.

`packages/tri-coach/src/tri_coach/testing.py`: add `from tri_core.testing import ScriptedChatModel, tool_call` (replacing the `tool_call` import) and `from tri_wellness.ranges.registry import MarkerRegistry`; extend `make_test_deps`:
```python
def make_test_deps(
    nocommit: Any,
    *,
    coach: BaseChatModel,
    planning: BaseChatModel,
    nutrition: BaseChatModel,
    analyst: BaseChatModel,
    wellness: BaseChatModel | None = None,
    registry: MarkerRegistry | None = None,
    tp: Any = None,
    garmin: Any = None,
    today: date = MONDAY,
    max_consults: int = 2,
) -> CoachDeps:
```
and in the `CoachDeps(...)` call add, after `analyst_tools=[],`:
```python
        wellness_model=wellness or ScriptedChatModel(script=[]),
        wellness_registry=registry,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass (53 passed, 1 skipped for the live test).

- [ ] **Step 7: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach uv.lock
git commit -m "feat(coach): tri-wellness dependency; optional TRI_ATHLETE_SEX; wellness model and registry in CoachDeps

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP"
```

---

### Task 2: `ask_wellness`, the lab interpreter as a tool

**Files:**
- Create: `packages/tri-coach/src/tri_coach/text.py`, `packages/tri-coach/src/tri_coach/tools/wellness.py`
- Modify: `packages/tri-coach/src/tri_coach/tools/analyst.py`, `packages/tri-coach/src/tri_coach/graph/nodes/planning.py`, `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py`
- Test: `packages/tri-coach/tests/test_tools.py`

**Interfaces:**
- Consumes: `tri_wellness.agent.build_agent`; `tri_wellness.prompts.chat.render_chat_prompt`; `tri_wellness.report.athlete_profile`; `tri_wellness.repo.list_panels`, `latest_panel_id`, `latest_report_for_panel`; `tri_wellness.tools.findings.make_findings_tools`, `WELLNESS_SCHEMA_DOC`; `tri_core.db.sql_tool.make_query_tool(url, extra_doc)`; `MarkerRegistry`.
- Produces: `tri_coach.text.last_ai_text(messages: Sequence[Any]) -> str` (text of the last `AIMessage` without tool calls, `""` if none); `wellness_tools(connect, db_url, registry) -> list[BaseTool]` (`query_training_db`, `get_panel_findings`, `get_marker_spec`, `get_marker_history`); `make_wellness_tool(model, connect, db_url, registry, today) -> BaseTool` named `ask_wellness` with `ask_wellness(question: str) -> str`; `WELLNESS_RECURSION_LIMIT = 40`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_tools.py` (add `from tri_coach.text import last_ai_text`, `from tri_coach.tools.wellness import make_wellness_tool, wellness_tools`, `from tri_core.config import Settings`, `from tri_wellness.testing import seed_panel` to the imports):
```python
def test_last_ai_text_takes_the_last_answer_without_tool_calls():
    calls = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}])
    assert last_ai_text([AIMessage(content="first"), calls]) == "first"
    assert last_ai_text([AIMessage(content=[{"type": "text", "text": "blocks"}])]) == "blocks"
    assert last_ai_text([HumanMessage("only human")]) == ""


def test_wellness_tools_are_read_only(registry):
    tools = wellness_tools(
        lambda: contextlib.nullcontext(None), Settings().test_database_url, registry
    )
    assert [t.name for t in tools] == [
        "query_training_db", "get_panel_findings", "get_marker_spec", "get_marker_history",
    ]


@pytest.mark.db
async def test_ask_wellness_runs_the_lab_interpreter_on_a_throwaway_thread(ldb, registry):
    seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    wellness = ScriptedChatModel(
        script=[
            tool_call("get_panel_findings", {"panel": "latest"}),
            AIMessage(content="Ferritin 18 ng/mL is functionally low."),
        ]
    )
    ask = make_wellness_tool(
        wellness,
        lambda: contextlib.nullcontext(ldb),
        Settings().test_database_url,
        registry,
        lambda: date(2026, 9, 14),
    )
    assert ask.name == "ask_wellness"
    assert "\n " not in ask.description
    assert await ask.ainvoke({"question": "how is my ferritin?"}) == (
        "Ferritin 18 ng/mL is functionally low."
    )
    assert wellness.calls == 2
    # a second question starts fresh: the interpreter does not remember the first
    wellness.script.extend([AIMessage(content="Fresh answer.")])
    assert await ask.ainvoke({"question": "again?"}) == "Fresh answer."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_coach.text'`.

- [ ] **Step 3: `text.py` and the three call sites**

`packages/tri-coach/src/tri_coach/text.py`:
```python
"""The final text of an agent run: the last AIMessage that made no tool call."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage


def last_ai_text(messages: Sequence[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content
            if isinstance(content, str):
                return content
            return "".join(
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
    return ""
```

`graph/nodes/planning.py`: delete its `last_ai_text` definition and add `from tri_coach.text import last_ai_text` (the module still uses it in `proposal_from_planning`). `graph/nodes/nutrition.py`: change `from tri_coach.graph.nodes.planning import last_ai_text, result_message` to `from tri_coach.graph.nodes.planning import result_message` plus `from tri_coach.text import last_ai_text`. `tools/analyst.py`: delete `_text`, add `from tri_coach.text import last_ai_text`, and replace the `for msg in reversed(...)` loop with
```python
        return last_ai_text(out["messages"]) or (
            "The analyst returned no answer; ask a narrower question."
        )
```

- [ ] **Step 4: `tools/wellness.py`**

```python
"""ask_wellness: the tri-wellness chat agent as a tool. Each call runs the lab interpreter on a
throwaway in-memory thread with wellness's own prompt and read-only tools and returns its final
text. The coach never writes a wellness row: ingest and report stay athlete-driven commands."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from tri_coach.text import last_ai_text
from tri_core.db.repo import Conn
from tri_core.db.sql_tool import make_query_tool
from tri_wellness import repo
from tri_wellness.agent import build_agent
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import athlete_profile
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

ConnectFactory = Callable[[], AbstractContextManager[Conn]]

WELLNESS_RECURSION_LIMIT = 40


def wellness_tools(connect: ConnectFactory, db_url: str, registry: MarkerRegistry) -> list[BaseTool]:
    """What tri-wellness chat binds: the SQL read tool with the lab schema doc and the three
    findings tools. None of them writes."""
    return [make_query_tool(db_url, WELLNESS_SCHEMA_DOC), *make_findings_tools(connect, registry)]


def make_wellness_tool(
    model: BaseChatModel,
    connect: ConnectFactory,
    db_url: str,
    registry: MarkerRegistry,
    today: Callable[[], date],
) -> BaseTool:
    tools = wellness_tools(connect, db_url, registry)
    names = [t.name for t in tools]

    async def ask_wellness(question: str) -> str:
        """Ask the lab interpreter about the athlete's lab panels: a marker's value against its
        functional range, what is outside optimal and why, the retest plan, supplements, or
        whether a symptom could be lab-related. It reads stored panels and reports; it changes
        nothing. Ask one specific question at a time."""
        with connect() as conn:
            profile = athlete_profile(conn)
            panels = repo.list_panels(conn)
            latest = repo.latest_panel_id(conn)
            latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
        prompt = render_chat_prompt(profile, registry.sex, panels, latest_report, today(), names)
        agent = build_agent(model, tools, prompt, InMemorySaver())
        out = await agent.ainvoke(
            {"messages": [HumanMessage(question)]},
            {
                "configurable": {"thread_id": f"wellness-{uuid4()}"},
                "recursion_limit": WELLNESS_RECURSION_LIMIT,
            },
        )
        return last_ai_text(out["messages"]) or (
            "The lab interpreter returned no answer; ask a narrower question."
        )

    return StructuredTool.from_function(
        coroutine=ask_wellness,
        name="ask_wellness",
        description=inspect.cleandoc(ask_wellness.__doc__ or ""),
    )
```
Trap: the findings tools are sync, so `create_agent` runs them in a worker thread while the test's `connect` hands out the rolled-back psycopg connection. psycopg 3 connections serialise their use with an internal lock, and the tools run one at a time, so this is fine; if the test ever reports `psycopg.errors.InFailedSqlTransaction`, the seeded panel raised inside the tool (read the traceback), not the threading.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_graph.py -q`
Expected: all pass; `test_graph.py` still passes with `last_ai_text` moved.

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): ask_wellness agent-as-tool over tri-wellness's chat agent; shared last_ai_text

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP"
```

---

### Task 3: The lab summary in the context block

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/context.py`
- Test: `packages/tri-coach/tests/test_context.py`

**Interfaces:**
- Consumes: `tri_wellness.repo.latest_panel_id`, `get_panel`, `latest_report_for_panel`; `tri_wellness.report.extract_section`; `tri_wellness.repo.insert_report` and `tri_wellness.testing.seed_panel`, `REPORT_OK` (tests).
- Produces: `LabSummary(panel_id, drawn_on, lab_name, report_on, outside_optimal, markers, priorities)`; `load_lab_summary(conn) -> LabSummary | None`; `CoachContext.labs_enabled: bool = False`, `CoachContext.labs: LabSummary | None = None`; `load_context(conn, store, today, pending, *, labs_enabled: bool = False)`; `render_context` emits one `Labs:` line after the nutrition line.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-coach/tests/test_context.py` (add `from tri_wellness import repo as wrepo`, `from tri_wellness.labs.models import Finding`, `from tri_wellness.testing import REPORT_OK, seed_panel` to the imports):
```python
async def test_labs_line_when_not_configured(nocommit, mem_store):
    ctx = await load_context(nocommit, mem_store, MONDAY, None)
    assert ctx.labs_enabled is False and ctx.labs is None
    assert "Labs: not configured (set TRI_ATHLETE_SEX" in render_context(ctx)


async def test_labs_line_in_each_stored_state(ldb, mem_store, registry):
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    assert ctx.labs is None
    assert "Labs: no panels stored (tri-wellness ingest)." in render_context(ctx)

    pid = seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    assert ctx.labs is not None and ctx.labs.panel_id == pid and ctx.labs.report_on is None
    assert "Labs: latest panel 2026-08-30 (Quest) has no report yet (run tri-wellness report)." in (
        render_context(ctx)
    )

    findings = [
        Finding(marker="ferritin", display="Ferritin", system="iron", value=18.0, unit="ng/mL",
                conventional_status="in_range", functional_status="low",
                functional_range=(50.0, 150.0)),
        Finding(marker="hs_crp", display="hs-CRP", system="inflammation", value=0.4, unit="mg/L",
                conventional_status="in_range", functional_status="optimal",
                functional_range=(None, 1.0)),
    ]
    wrepo.insert_report(ldb, pid, registry.version, findings, REPORT_OK)
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    text = render_context(ctx)
    assert ctx.labs is not None and ctx.labs.outside_optimal == 1 and ctx.labs.markers == 2
    assert "Labs: panel 2026-08-30 (Quest), report " in text
    assert "1 of 2 markers outside optimal. Priorities: " in text
    assert text.index("Nutrition:") < text.index("Labs:")
    assert render_context(ctx) == text  # byte-stable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_context.py -q`
Expected: the two new tests fail (`AttributeError: labs_enabled` / `TypeError: unexpected keyword argument 'labs_enabled'`).

- [ ] **Step 3: Implement**

In `packages/tri-coach/src/tri_coach/context.py` add the imports `from tri_wellness import repo as wrepo` and `from tri_wellness.report import extract_section`, then:

```python
PRIORITIES_CHARS = 300


@dataclass
class LabSummary:
    panel_id: int
    drawn_on: date
    lab_name: str | None
    report_on: date | None  # the latest report's creation date; None when no report yet
    outside_optimal: int | None  # findings whose functional_status is not "optimal"
    markers: int | None
    priorities: str | None  # the report's Priorities section, whitespace collapsed, clipped


def load_lab_summary(conn: Conn) -> LabSummary | None:
    """The latest stored panel and its latest report, or None when no panel is stored (or the
    lab tables are not there: the coach must not fail a turn because wellness is not set up)."""
    if conn.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        return None
    pid = wrepo.latest_panel_id(conn)
    if pid is None:
        return None
    panel = wrepo.get_panel(conn, pid)
    if panel is None:
        return None
    report = wrepo.latest_report_for_panel(conn, pid)
    if report is None:
        return LabSummary(pid, panel.drawn_on, panel.lab_name, None, None, None, None)
    priorities = extract_section(report.report_md, "Priorities")
    if priorities:
        priorities = " ".join(priorities.split())
        if len(priorities) > PRIORITIES_CHARS:
            priorities = priorities[: PRIORITIES_CHARS - 1].rstrip() + "…"
    return LabSummary(
        panel_id=pid,
        drawn_on=panel.drawn_on,
        lab_name=panel.lab_name,
        report_on=report.created_at.date(),
        outside_optimal=sum(1 for f in report.findings if f.functional_status != "optimal"),
        markers=len(report.findings),
        priorities=priorities or None,
    )
```
`CoachContext` gains two defaulted fields after `pending`:
```python
    labs_enabled: bool = False  # TRI_ATHLETE_SEX set: the wellness consult is bound
    labs: LabSummary | None = None
```
`load_context` gains the keyword `*, labs_enabled: bool = False` and passes `labs_enabled=labs_enabled, labs=load_lab_summary(conn) if labs_enabled else None` to `CoachContext(...)`.

The line, placed in `render_context` right after `lines.append(_nutrition_line(ctx))`:
```python
def _labs_line(ctx: CoachContext) -> str:
    if not ctx.labs_enabled:
        return "Labs: not configured (set TRI_ATHLETE_SEX to enable the wellness consult)."
    s = ctx.labs
    if s is None:
        return "Labs: no panels stored (tri-wellness ingest)."
    lab = f" ({s.lab_name})" if s.lab_name else ""
    if s.report_on is None:
        return (
            f"Labs: latest panel {s.drawn_on.isoformat()}{lab} has no report yet "
            "(run tri-wellness report)."
        )
    line = (
        f"Labs: panel {s.drawn_on.isoformat()}{lab}, report {s.report_on.isoformat()}: "
        f"{s.outside_optimal} of {s.markers} markers outside optimal."
    )
    if s.priorities:
        line += f" Priorities: {s.priorities}"
    return line
```
and `lines.append(_labs_line(ctx))` after the nutrition line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach/tests/test_context.py packages/tri-coach/tests/test_prompt.py -q`
Expected: all pass (the existing `test_render_is_byte_stable_and_shows_pending` constructs `CoachContext` positionally; the new fields default).

- [ ] **Step 5: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): lab summary line in the context block from the latest panel and report

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP"
```

---

### Task 4: Prompt v2, the coach node binding, the CLI snapshot

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/prompts/coach.py`, `packages/tri-coach/src/tri_coach/graph/nodes/coach.py`, `packages/tri-coach/src/tri_coach/cli.py`
- Test: `packages/tri-coach/tests/test_prompt.py`, `packages/tri-coach/tests/test_graph.py`

**Interfaces:**
- Consumes: Task 2's `make_wellness_tool`; Task 3's `load_context(..., labs_enabled=)`; Task 1's `CoachDeps.wellness_model`, `wellness_registry`.
- Produces: `PROMPT_VERSION = "2"`; `COACH_RULES` with an `ask_wellness` routing bullet, a lab-signal rule and a memory-policy mention of lab values; `make_coach_node` binds `ask_wellness` only when `deps.wellness_registry is not None` and renders the context with `labs_enabled` accordingly; `cli._chat`'s snapshot passes `labs_enabled=settings.tri_athlete_sex is not None`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-coach/tests/test_prompt.py`: change `assert PROMPT_VERSION == "1"` to `assert PROMPT_VERSION == "2"`, and extend the phrase list in `test_rules_cover_policy_routing_and_memory` with:
```python
        "ask_wellness",
        "Never brief a sub-agent to change a lab value",
        "lab values",
        "labs are not configured",
```

Append to `packages/tri-coach/tests/test_graph.py` (add `from datetime import date` and `from tri_wellness.testing import seed_panel` to the imports):
```python
def _recording(monkeypatch):
    """Capture the tool names and the system prompt each coach turn binds."""
    bound: list[list[str]] = []
    prompts: list[str] = []
    real = nodes.coach.make_subagent

    def record(model, tools, system_prompt):
        bound.append([t.name for t in tools])
        prompts.append(system_prompt)
        return real(model, tools, system_prompt)

    monkeypatch.setattr(nodes.coach, "make_subagent", record)
    return bound, prompts


async def test_lab_question_uses_the_wellness_consult_and_ends_without_a_handoff(
    ldb, make_deps, mem_store, registry, monkeypatch
):
    bound, prompts = _recording(monkeypatch)
    seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL")])
    models = scripted(
        coach=[
            tool_call("ask_wellness", {"question": "ferritin?"}),
            AIMessage(content="Ferritin is functionally low; I will fuel for iron."),
        ],
        planning=[],
        nutrition=[],
        analyst=[],
        wellness=[
            tool_call("get_panel_findings", {"panel": "latest"}),
            AIMessage(content="Ferritin 18 ng/mL, functional low."),
        ],
    )
    deps = make_deps(registry=registry, **models)
    graph = build_graph(deps, InMemorySaver(serde=make_serde()), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("how is my ferritin?")]}, CFG)
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_msgs] == ["ask_wellness"]
    assert tool_msgs[0].content == "Ferritin 18 ng/mL, functional low."
    assert out["messages"][-1].content.startswith("Ferritin is functionally low")
    assert models["planning"].calls == 0 and models["nutrition"].calls == 0
    assert models["analyst"].calls == 0 and models["wellness"].calls == 2
    assert "ask_wellness" in bound[0]
    assert not any(
        n.startswith(("set_", "tp_create", "tp_update", "tp_delete", "tp_apply")) for n in bound[0]
    )
    assert "Labs: latest panel 2026-08-30 (Quest) has no report yet" in prompts[0]
    assert (await graph.aget_state(CFG)).next == ()


async def test_wellness_tool_is_absent_when_labs_are_not_configured(
    nocommit, make_deps, mem_store, monkeypatch
):
    bound, prompts = _recording(monkeypatch)
    graph, _ = graph_for(make_deps, mem_store, coach=[AIMessage(content="Hello.")])
    await graph.ainvoke({"messages": [HumanMessage("hi")]}, CFG)
    assert "ask_wellness" not in bound[0] and "ask_analyst" in bound[0]
    assert "Labs: not configured" in prompts[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_prompt.py packages/tri-coach/tests/test_graph.py -q`
Expected: the prompt tests fail on the version and the phrases; the lab-question test fails because `ask_wellness` is not bound (the scripted coach's tool call has no matching tool).

- [ ] **Step 3: Prompt v2**

In `packages/tri-coach/src/tri_coach/prompts/coach.py`: set `PROMPT_VERSION = "2"`. In `COACH_RULES`:

Replace
```
generic encouragement. You coach one athlete whose training, nutrition and lab data you can read
through your tools. You are the only one who decides when something changes; the athlete approves
every change before it is written.
```
with
```
generic encouragement. You coach one athlete whose training, nutrition and lab data you can read
through your tools (labs only while the context says they are configured). You are the only one
who decides when something changes; the athlete approves every change before it is written.
```

After the `ask_analyst` routing bullet insert
```
- ask_wellness: anything about lab markers, functional ranges, what is outside optimal and why,
  the retest plan, supplements, or whether a symptom could be lab-related. It reads stored panels
  and reports; it never changes anything. When the context says labs are not configured or no
  panel is stored, say so instead of guessing.
- A lab finding that bears on training load or fueling is a signal: name it in the brief, for
  example "Ferritin 18 ng/mL, functional low, on the 2026-08-30 panel". Never brief a sub-agent to
  change a lab value; the sub-agents do not read lab tables.
```

Replace the memory bullet
```
- Do not remember what planning or nutrition already store (goal, availability, plan constraints,
  the nutrition profile); brief the right sub-agent to change those instead.
```
with
```
- Do not remember what planning, nutrition or wellness already store (goal, availability, plan
  constraints, the nutrition profile, lab values); brief the right sub-agent to change the first
  three, and ask_wellness for the labs.
```
`COACH_RULES` still contains only the `{max_consults}` placeholder; `str.format` stays safe.

- [ ] **Step 4: Coach node and CLI**

`packages/tri-coach/src/tri_coach/graph/nodes/coach.py`: add `from tri_coach.tools.wellness import make_wellness_tool`, and replace the two tool lines plus the `load_context` call:
```python
def make_coach_node(deps: CoachDeps) -> Any:
    analyst = make_analyst_tool(deps.analyst_model, deps.analyst_tools, deps.connect, deps.today)
    labs_enabled = deps.wellness_registry is not None
    wellness = (
        [make_wellness_tool(deps.wellness_model, deps.connect, deps.db_url, deps.wellness_registry, deps.today)]
        if deps.wellness_registry is not None
        else []
    )
    tools = [analyst, *wellness, *make_handoff_tools(), *make_memory_tools(deps.today)]

    async def coach(
        state: CoachState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        with deps.connect() as conn:
            ctx = await load_context(
                conn, store, deps.today(), state.get("pending"), labs_enabled=labs_enabled
            )
```
(the rest of the node is unchanged).

`packages/tri-coach/src/tri_coach/cli.py`, in `_chat`'s `snapshot()`: pass `labs_enabled=settings.tri_athlete_sex is not None` to `load_context`, so `/status` and `/prompt` show the same lab line the coach sees.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass, 1 skipped (live).

- [ ] **Step 6: Definition of done and commit**

```bash
uv run ruff format packages/tri-coach && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add packages/tri-coach
git commit -m "feat(coach): prompt v2 routes lab questions to ask_wellness; bound only when labs are configured

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP"
```

---

### Task 5: Docs, spec status, vault export

**Files:**
- Modify: `packages/tri-coach/README.md`, root `README.md`, `docs/superpowers/specs/2026-09-11-tri-coach-design.md` (status line only)
- Copy: this plan and every edited markdown file into the Obsidian vault

- [ ] **Step 1: Package README**

In `packages/tri-coach/README.md`:
- Mermaid `coach` node label: change `ask_analyst, consult_planning, consult_nutrition,` to `ask_analyst, ask_wellness, consult_planning, consult_nutrition,`.
- Node table row for `coach`: change `tables and both Store namespaces (context), coach memory` to `tables, both Store namespaces and the lab tables (context), coach memory`.
- After the "## Memory" section insert:
```markdown
## Wellness consult

`ask_wellness` runs `tri-wellness`'s chat agent the way `ask_analyst` runs the analyst: on a
throwaway thread, with wellness's own prompt (profile, stored panels, the latest report's
priorities and retest plan) and its read-only tools (`query_training_db` with the lab schema
doc, `get_panel_findings`, `get_marker_spec`, `get_marker_history`). The context block carries
one `Labs:` line from the latest panel and report: draw date and lab, whether a report exists,
how many markers sit outside the optimal functional band, and the report's Priorities. A lab
finding that bears on load or fueling is named as the signal in a planning or nutrition brief;
the sub-agents never read lab tables. The coach never runs `ingest` or `report`.

`TRI_ATHLETE_SEX` is optional for the coach: unset, the tool is not bound and the line says labs
are not configured.
```
- "## Sessions": append the sentence `Wellness needs no session: it reads Postgres only.`
- "## Status": add `- Wellness consult (2026-09): ask_wellness, the lab line in the context block, prompt v2.` and change the milestone line to `- Milestone 4 (check-in, post-apply nutrition regeneration, routing dataset and eval): pending.`

- [ ] **Step 2: Root README**

- Line 15: change `depends on `tri-analyze`, `tri-planning` and `tri-nutrition`.` to `depends on `tri-analyze`, `tri-planning`, `tri-nutrition` and `tri-wellness`.`
- The tri-coach table row: change `Head coach: answers through the analyst, briefs planning and nutrition,` to `Head coach: answers through the analyst and the lab interpreter, briefs planning and nutrition,`.
- The run line comment for `tri-coach chat`: `# the front door: one conversation over the analyst, wellness, planning and nutrition`.
- Status: append
```
- tri-coach milestone 3 (2026-09): wellness consult (`ask_wellness`, lab line in the context, prompt v2);
  tracked in `docs/superpowers/plans/2026-09-13-tri-coach-03-wellness-consult.md`. Check-in and eval pending.
```

- [ ] **Step 3: Spec status line**

In `docs/superpowers/specs/2026-09-11-tri-coach-design.md` line 4, change `milestone 3, the wellness consult, planned 2026-09-13 (plan 03)` to `milestone 3, the wellness consult, in progress (plan 03)`. No other spec line changes.

- [ ] **Step 4: Definition of done and vault export**

```bash
uv run ruff format packages && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run tri-coach --help
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p "$V/docs/superpowers/plans" "$V/docs/superpowers/specs" "$V/packages/tri-coach"
cp docs/superpowers/plans/2026-09-13-tri-coach-03-wellness-consult.md "$V/docs/superpowers/plans/"
cp docs/superpowers/specs/2026-09-11-tri-coach-design.md "$V/docs/superpowers/specs/"
cp packages/tri-coach/README.md "$V/packages/tri-coach/readme.md"
cp README.md "$V/readme.md"
```

- [ ] **Step 5: Commit**

```bash
git add README.md packages/tri-coach/README.md docs/superpowers/specs/2026-09-11-tri-coach-design.md
git commit -m "docs(coach): wellness consult in the package and root READMEs; spec status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0158NPK2UVmhfeuJCy2QB1eP"
```

- [ ] **Step 6: Finish the branch**

Use `superpowers:finishing-a-development-branch`. Expected outcome, as for plans 1 and 2: a fast-forward merge into `main` after the suite passes on the merged tree, then removal of the worktree and branch. Plan 4 (check-in and follow-on) starts from the merged `main`. Brian's manual exit for the milestone: one `tri-coach chat --no-live` turn asking about a stored panel, recorded in the package README status.

---

## Self-review against the spec

**Spec coverage (§13 milestone 3: "`tri-wellness` as a coach dependency; `ask_wellness` agent-as-tool; the lab summary in the context block; the routing-guide and memory-policy lines for labs; `PROMPT_VERSION` 2"):** dependency, settings and deps in Task 1; `ask_wellness` in Task 2 (§6.3 tool bullet, §6.6 first bullet); the lab line with its three states plus the not-configured state in Task 3 (§6.6 second and third bullets, §9 row); routing guide, lab-signal rule, memory policy, `PROMPT_VERSION` and the conditional binding in Task 4 (§6.4, §6.6 fourth bullet); README and status in Task 5. §6.6 invariants: the coach imports only `tri_wellness.repo` readers, `report.athlete_profile`/`extract_section`, `prompts.chat`, `agent.build_agent`, `tools.findings`, `ranges.registry`, `config.Sex`; no write function anywhere (Task 4's graph test asserts no write-prefixed tool is bound). §11 wellness items: throwaway thread and fresh second question (Task 2), the three states byte-stable (Task 3), lab question calls `ask_wellness` and consults nothing (Task 4), tool absent when unset (Task 4), read-only tool names (Task 2). §10: optional `TRI_ATHLETE_SEX`, the `tri-wellness` dependency, no root `pyproject.toml` change.

**Placeholder scan:** no "TBD", "similar to", or "add handling" phrases; every code step shows the code.

**Type consistency:** `wellness_tools(connect, db_url, registry)` and `make_wellness_tool(model, connect, db_url, registry, today)` (Task 2) match the coach node's call (Task 4) and the tests; `CoachDeps.wellness_model`/`wellness_registry` (Task 1) are what Task 4 reads and `make_test_deps(..., wellness=, registry=)` sets; `load_context(..., labs_enabled=)` (Task 3) is called with the keyword in Task 4's node and CLI; `LabSummary.report_on`/`outside_optimal`/`markers`/`priorities` are what `_labs_line` renders and Task 3's test asserts; `last_ai_text` (Task 2) is imported by `analyst.py`, `wellness.py`, `planning.py` and `nutrition.py` from `tri_coach.text`.
