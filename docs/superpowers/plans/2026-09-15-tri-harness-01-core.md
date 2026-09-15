# tri-harness Plan 1 of 4: Harness Core (`tri_core.harness`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tri_core.harness` to tri-core. It provides the text helpers, agent builders, agent-as-tool runner, handoff plumbing, Postgres persistence helpers and the turn driver, each with its own tests. No existing module calls it yet.

**Architecture:** Six focused modules under `packages/tri-core/src/tri_core/harness/`, each a verbatim or near-verbatim move of code that five packages carry copies of today. A module appears once and is tested once in tri-core. Plans 2–4 then delete the package copies and point callers here. This plan changes no existing module, so the suite stays exactly as it was plus the new tests.

**Tech Stack:** Python 3.12, langchain 1.4.0 (`create_agent`, `wrap_model_call`), langchain-core 1.6.2, langchain-anthropic 1.7.1 (`AnthropicPromptCachingMiddleware`), langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2 (`AsyncPostgresSaver`, `AsyncPostgresStore`), anthropic 1.4.0, psycopg 3.3.5, pytest with `pytest-asyncio` 1.4.0 in auto mode, `tri_core.testing.ScriptedChatModel`.

**Spec:** `docs/superpowers/specs/2026-09-15-tri-harness-design.md`. This plan implements §4 (tri-core layout), §5.1–§5.6 (interfaces) and the plan 01 tests in §7. The spec and all four plans are merged to `main` before any plan runs, so the feature branch starts from `main` with them in place. Plans 2 (tri-analyze and tri-wellness), 3 (tri-planning and tri-nutrition) and 4 (tri-coach and tri-web) follow.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** run `git worktree add ../triathlon_agent-harness-01 -b feat/tri-harness-01 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout. First confirm the plans are on `main`: `ls docs/superpowers/plans/2026-09-15-tri-harness-0*.md` lists four files. Baseline recorded on `main` 3a5a82c; the docs merge adds only markdown: `903 passed, 6 skipped, 1 warning` (the six skips are `--live`). Record `uv run pytest -q` before Task 1 and stop if it differs.
- **Files this plan may touch:**
  - `packages/tri-core/pyproject.toml`
  - `uv.lock`
  - `packages/tri-core/src/tri_core/harness/*` (new)
  - `packages/tri-core/src/tri_core/testing/fakes.py` (one test model)
  - `packages/tri-core/tests/test_harness_*.py` (new)
  - `packages/tri-core/README.md`

  No edits under any other package, and no edits to any existing tri-core module beyond `fakes.py`.
- **New tri-core dependencies:** `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langgraph-checkpoint-postgres>=3.1,<4`, `anthropic>=1.4,<2`. All are already resolved in `uv.lock` through the other packages, so `uv lock` must not change any resolved version.
- **Code the spec says is "moved verbatim" keeps its logic and every user-visible string exactly.** This covers error sentences, `NOT_DELIVERED`, `SETUP_HINT`, `STORE_SETUP_HINT`, printer output and docstrings that act as tool descriptions.
- **Test data:** tests write nothing to Postgres. `@pytest.mark.db` tests only open connections and read, and skip when the tables are missing. No test needs an Anthropic key or an MCP server.
- **Commits:** Git commits are permitted (Brian's standing permission). Commit once per task on `feat/tri-harness-01`, and end every commit message with the `Co-Authored-By:` trailer of the session executing the plan.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages/tri-core`
  2. `uv run ruff check --fix packages/tri-core`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing one.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file created or edited in this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Facts verified while writing this plan (against `main` 3a5a82c, 2026-09-15)

1. `langchain.agents.create_agent` defaults: `system_prompt=None`, `middleware=()`, `context_schema=None`, `checkpointer=None`.
2. An agent built with `checkpointer=False` runs fine when invoked directly, outside a parent graph. A scripted tool round trip returns `[HumanMessage, AIMessage, ToolMessage, AIMessage]`, and a tool returning the int `5` produces a `ToolMessage` whose content is `"5"`.
3. With `one_tool_call_at_a_time` in the middleware, `ScriptedChatModel.bind_tools` receives `{"tool_choice": None, "parallel_tool_calls": False}`.
4. An agent on an `InMemorySaver` keeps history per thread. Two turns on one thread end with message contents `["a", "one", "b", "two"]`.
5. `astream` item shapes:
   - `stream_mode="updates"` without subgraphs yields plain `dict`s.
   - `stream_mode=["messages", "updates"]` without subgraphs yields `(mode, data)` 2-tuples.
   - With `subgraphs=True`, it yields `(namespace, mode, data)`.
6. `StructuredTool.from_function(coroutine=run, name="ask_analyst", description=...)` produces the same `tool_call_schema` whatever the inner function is called. The schema title is the tool `name`, and the properties are `{"question": {"title": "Question", "type": "string"}}`.
7. The error strings the tests assert against:
   - `str(anthropic.RateLimitError(message="slow down", response=httpx.Response(429, request=req), body=None))` is `"slow down"` (status 429).
   - `InternalServerError(message="boom", ...)` gives `status_code` 500 and `.message == "boom"`.
   - `str(anthropic.APIConnectionError(request=req))` is `"Connection error."`.
8. `tri_nutrition.store.STORE_SETUP_HINT` starts with `"LangGraph store tables are missing; run once per database:\n"`, while `SETUP_HINT` starts with `"checkpoint tables are missing; run once per database:\n"`. The next two lines are the same in both.
9. tri-core's `src` has no pydantic `BaseModel`. A model defined inside a test module is not reliably importable by module path under `--import-mode=importlib`, and the msgpack serializer needs that path to rebuild the object.
10. Existing fakes that plans 2–4 keep:
    - `tri_analyze/tests/test_repl.py::FakeAgent.astream(self, payload, config=None, stream_mode=None, context=None)` has no `subgraphs` parameter.
    - `tri_planning/tests/test_repl.py::RaisingGraph.astream(self, payload, config=None, stream_mode=None, subgraphs=False)` has no `context` parameter.

### Decisions this plan makes where the spec is silent

- **`stream_turn(stream_mode=None)`** means `["messages", "updates"]`, which avoids a mutable default argument.
- **`stream_turn` passes `subgraphs=True` and `context=` to `astream` only when they are set.** This matches what each caller passes today, so the fakes in fact 10 keep working in plans 2–4 without edits.
- **`tri_core.testing.fakes.StateSample`** is a two-field pydantic model the serializer test registers (fact 9).
- **`agents._caching()`** builds a fresh `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")` for every agent, as each package copy does today.

---

## File Structure

```
packages/tri-core/
  pyproject.toml                         Task 1: four dependencies, description
  README.md                              Task 8: harness paragraph
  src/tri_core/harness/
    __init__.py                          Task 1: empty
    messages.py                          Task 1: text_of, last_ai_text
    agents.py                            Task 2: one_tool_call_at_a_time, make_subagent, build_chat_agent
    agent_tool.py                        Task 3: Invocation, agent_tool
    handoff.py                           Task 4: NOT_DELIVERED, turn_messages, undelivered, handoff
    persistence.py                       Task 5: SETUP_HINT, STORE_SETUP_HINT, make_serde, open_checkpointer,
                                                 checkpointer_ready, open_store, store_ready
    turns.py                             Task 6: Out, TurnSink, TurnFailure, api_error_message, turn_config,
                                                 stream_turn, format_failure
                                         Task 7: AgentTurnPrinter, GraphTurnPrinter, run_agent_turn,
                                                 run_graph_turn
  src/tri_core/testing/fakes.py          Task 5: StateSample
  tests/test_harness_messages.py         Task 1
  tests/test_harness_agents.py           Task 2
  tests/test_harness_agent_tool.py       Task 3
  tests/test_harness_handoff.py          Task 4
  tests/test_harness_persistence.py      Task 5
  tests/test_harness_turns.py            Tasks 6, 7
uv.lock                                  Task 1
```

---

### Task 1: Dependencies, the `harness` package, and `messages.py`

**Files:**
- Modify: `packages/tri-core/pyproject.toml`
- Modify: `uv.lock` (regenerated)
- Create: `packages/tri-core/src/tri_core/harness/__init__.py`
- Create: `packages/tri-core/src/tri_core/harness/messages.py`
- Test: `packages/tri-core/tests/test_harness_messages.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `tri_core.harness.messages.text_of(msg: BaseMessage) -> str`
  - `tri_core.harness.messages.last_ai_text(messages: Sequence[Any]) -> str`

- [ ] **Step 1: Add the dependencies**

In `packages/tri-core/pyproject.toml`, replace the `description` line and the `dependencies` list with:

```toml
description = "Shared settings, MCP client, Postgres store, sync and agent harness for the triathlon agents"
```

```toml
dependencies = [
    "mcp>=1.29,<2",
    "langchain-mcp-adapters==0.3.2",  # only for tri_core.mcp.live_tools
    "psycopg[binary]==3.3.5",
    "pydantic-settings>=2.6",
    "python-dotenv>=1.0",
    "typer>=0.15",
    "rich>=13",
    "langchain-core>=1.0,<2",
    "langchain==1.4.0",                       # tri_core.harness.agents
    "langchain-anthropic==1.7.1",             # tri_core.harness.agents
    "langgraph-checkpoint-postgres>=3.1,<4",  # tri_core.harness.persistence
    "anthropic>=1.4,<2",                      # tri_core.harness.turns
    "pytest>=8.3",             # only for tri_core.testing.fixtures
]
```

Run: `uv lock && git diff --stat uv.lock && uv sync`
Expected: `uv.lock` changes only in the `tri-core` package entry (its dependency and requires-dist lists). No `version = ` line changes. `uv sync` completes.

Run: `git diff uv.lock | grep '^[-+]version'`
Expected: no output.

- [ ] **Step 2: Write the failing test**

Create `packages/tri-core/tests/test_harness_messages.py`:

```python
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.harness.messages import last_ai_text, text_of


def test_text_of_returns_string_content_unchanged():
    assert text_of(AIMessage(content="plain")) == "plain"


def test_text_of_joins_text_blocks_and_bare_strings_and_skips_other_blocks():
    msg = AIMessage(
        content=[
            {"type": "text", "text": "a"},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            "b",
            {"type": "text", "text": "c"},
        ]
    )
    assert text_of(msg) == "abc"


def test_last_ai_text_is_the_last_message_without_tool_calls():
    call = AIMessage(
        content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    messages = [
        HumanMessage("q"),
        AIMessage(content="first"),
        call,
        ToolMessage("r", tool_call_id="c1"),
        AIMessage(content=[{"type": "text", "text": "final"}]),
    ]
    assert last_ai_text(messages) == "final"


def test_last_ai_text_skips_tool_calling_messages_and_is_empty_when_none_match():
    call = AIMessage(
        content="thinking",
        tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}],
    )
    assert last_ai_text([HumanMessage("q"), call]) == ""
    assert last_ai_text([]) == ""
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_messages.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness'`.

- [ ] **Step 4: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/__init__.py` as an empty file.

Create `packages/tri-core/src/tri_core/harness/messages.py`:

```python
"""Text out of LangChain messages: one message's text, and the final answer of an agent run."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


def text_of(msg: BaseMessage) -> str:
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


def last_ai_text(messages: Sequence[Any]) -> str:
    """The final text of an agent run: the last AIMessage that made no tool call."""
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

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_messages.py -v`
Expected: 4 passed.

- [ ] **Step 6: Definition of done**

Run the six commands from Global Constraints.
Expected: `907 passed, 6 skipped`, ruff clean, `mypy` reports `Success`.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-core/pyproject.toml uv.lock packages/tri-core/src/tri_core/harness packages/tri-core/tests/test_harness_messages.py
git commit -m "feat(core): tri_core.harness package with text_of and last_ai_text"
```

---

### Task 2: `agents.py`: `make_subagent`, `build_chat_agent`, `one_tool_call_at_a_time`

**Files:**
- Create: `packages/tri-core/src/tri_core/harness/agents.py`
- Test: `packages/tri-core/tests/test_harness_agents.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Middleware = AgentMiddleware[Any, Any, Any]`
  - `one_tool_call_at_a_time: AgentMiddleware`
  - `make_subagent(model: BaseChatModel, tools: Sequence[BaseTool], system_prompt: str, *, middleware: Sequence[Middleware] = ()) -> Any`
  - `build_chat_agent(model: BaseChatModel, tools: Sequence[BaseTool], *, system_prompt: str | None = None, middleware: Sequence[Middleware] = (), context_schema: type[Any] | None = None, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any`

- [ ] **Step 1: Write the failing test**

Create `packages/tri-core/tests/test_harness_agents.py`:

```python
from typing import Any

from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

import tri_core.harness.agents as agents
from tri_core.harness.agents import build_chat_agent, make_subagent, one_tool_call_at_a_time
from tri_core.testing import ScriptedChatModel, tool_call


@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


class RecordingModel(ScriptedChatModel):
    """A scripted model that records the kwargs create_agent binds its tools with."""

    bind_kwargs: list[dict[str, Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingModel":
        self.bind_kwargs.append(kwargs)
        return self


async def test_make_subagent_runs_a_tool_round_trip_when_invoked_directly():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    agent = make_subagent(model, [add], "sys")
    out = await agent.ainvoke({"messages": [HumanMessage("add 2 and 3")]})
    kinds = [type(m).__name__ for m in out["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert out["messages"][2].content == "5"
    assert out["messages"][3].content == "It is 5."


async def test_one_tool_call_at_a_time_binds_tools_with_parallel_calls_off():
    model = RecordingModel(script=[AIMessage(content="hi")])
    agent = make_subagent(model, [add], "sys", middleware=[one_tool_call_at_a_time])
    await agent.ainvoke({"messages": [HumanMessage("hello")]})
    assert model.bind_kwargs and model.bind_kwargs[0].get("parallel_tool_calls") is False


async def test_build_chat_agent_keeps_history_per_thread_in_memory_by_default():
    model = ScriptedChatModel(script=[AIMessage(content="one"), AIMessage(content="two")])
    agent = build_chat_agent(model, [add], system_prompt="sys")
    cfg = {"configurable": {"thread_id": "t"}}
    await agent.ainvoke({"messages": [HumanMessage("a")]}, cfg)
    out = await agent.ainvoke({"messages": [HumanMessage("b")]}, cfg)
    assert [m.content for m in out["messages"]] == ["a", "one", "b", "two"]


def test_builders_put_prompt_caching_last_and_pass_their_arguments(monkeypatch):
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_create_agent(*args: Any, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return "agent"

    monkeypatch.setattr(agents, "create_agent", fake_create_agent)
    model = ScriptedChatModel(script=[])
    saver = InMemorySaver()

    assert make_subagent(model, (add,), "sys", middleware=[one_tool_call_at_a_time]) == "agent"
    assert (
        build_chat_agent(
            model,
            [add],
            middleware=[one_tool_call_at_a_time],
            context_schema=dict,
            checkpointer=saver,
        )
        == "agent"
    )
    assert build_chat_agent(model, []) == "agent"

    (sub_args, sub), (chat_args, chat), (_, bare) = calls
    assert sub_args == (model, [add]) and chat_args == (model, [add])
    assert sub["system_prompt"] == "sys" and sub["checkpointer"] is False
    assert len(sub["middleware"]) == 2 and sub["middleware"][0] is one_tool_call_at_a_time
    assert isinstance(sub["middleware"][1], AnthropicPromptCachingMiddleware)
    assert chat["middleware"][0] is one_tool_call_at_a_time
    assert isinstance(chat["middleware"][1], AnthropicPromptCachingMiddleware)
    assert chat["context_schema"] is dict and chat["checkpointer"] is saver
    assert chat["system_prompt"] is None
    assert isinstance(bare["checkpointer"], InMemorySaver) and len(bare["middleware"]) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_agents.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness.agents'`.

- [ ] **Step 3: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/agents.py`:

```python
"""The agent builders every package uses. Prompt caching is always the last middleware, so the
prompt an earlier dynamic-prompt middleware renders is what gets marked for the cache."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, wrap_model_call
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

Middleware = AgentMiddleware[Any, Any, Any]


@wrap_model_call
async def one_tool_call_at_a_time(request: Any, handler: Any) -> Any:
    """Bind every model call with parallel tool use off.

    A handoff tool unwinds the sub-agent through Command(graph=PARENT) as soon as it runs, so a
    sibling call made in the same step can never return its result. Asking for one call per step
    keeps the persisted history free of tool_use blocks with no tool_result. langchain-anthropic
    turns `parallel_tool_calls=False` into the API's `disable_parallel_tool_use`. The coach
    graph only ever runs the sub-agent asynchronously, so the async hook is the one needed.
    """
    settings = {**request.model_settings, "parallel_tool_calls": False}
    return await handler(request.override(model_settings=settings))


def _caching() -> Middleware:
    return AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")


def make_subagent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    *,
    middleware: Sequence[Middleware] = (),
) -> Any:
    """A tool-calling loop with no checkpointer of its own: the parent graph owns the messages.

    A compiled graph invoked inside a node is a subgraph. `checkpointer=False`
    stops it from writing its own checkpoints under the parent's namespace; the parent state
    already carries the conversation.
    """
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[*middleware, _caching()],
        checkpointer=False,
    )


def build_chat_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
    middleware: Sequence[Middleware] = (),
    context_schema: type[Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools, remembering each thread. Without a
    checkpointer the threads live in memory."""
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[*middleware, _caching()],
        context_schema=context_schema,
        checkpointer=checkpointer or InMemorySaver(),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_agents.py -v`
Expected: 4 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `911 passed, 6 skipped`, ruff clean, `mypy` `Success`.

If `mypy` rejects passing `list[Middleware]` as `create_agent(middleware=...)`, annotate the list as `middleware: list[Middleware] = [*middleware, _caching()]` on its own line before the call. Do not add `# type: ignore`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/agents.py packages/tri-core/tests/test_harness_agents.py
git commit -m "feat(core): harness agent builders with prompt caching last"
```

---

### Task 3: `agent_tool.py`: an agent run as a tool

**Files:**
- Create: `packages/tri-core/src/tri_core/harness/agent_tool.py`
- Test: `packages/tri-core/tests/test_harness_agent_tool.py`

**Interfaces:**
- Consumes: `tri_core.harness.messages.last_ai_text(messages: Sequence[Any]) -> str` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Invocation: agent: Any; context: Any = None`
  - `agent_tool(*, name: str, description: str, prepare: Callable[[], Invocation], thread_prefix: str, recursion_limit: int, failure: str, empty: str) -> BaseTool`

  The tool takes one string argument, `question`. `failure` contains `{error}`, which is filled with `"<ExcType>: <exc>"`.

- [ ] **Step 1: Write the failing test**

Create `packages/tri-core/tests/test_harness_agent_tool.py`:

```python
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphInterrupt

from tri_core.harness.agent_tool import Invocation, agent_tool


class FakeAgent:
    """Records each ainvoke and answers with the given messages appended, or raises."""

    def __init__(self, messages: list[Any] | None = None, error: Exception | None = None):
        self.messages = messages if messages is not None else [AIMessage(content="answer")]
        self.error = error
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []

    async def ainvoke(self, payload, config, **kwargs):
        self.calls.append((payload, config, kwargs))
        if self.error is not None:
            raise self.error
        return {"messages": [*payload["messages"], *self.messages]}


def make(prepare, **overrides):
    opts: dict[str, Any] = {
        "name": "ask_fake",
        "description": "Ask the fake.",
        "prepare": prepare,
        "thread_prefix": "fake",
        "recursion_limit": 7,
        "failure": "The fake failed ({error}); carry on.",
        "empty": "The fake returned no answer.",
    }
    opts.update(overrides)
    return agent_tool(**opts)


async def test_agent_tool_runs_on_a_fresh_throwaway_thread_and_returns_the_final_text():
    agent = FakeAgent()
    t = make(lambda: Invocation(agent))
    assert t.name == "ask_fake" and t.description == "Ask the fake."
    assert await t.ainvoke({"question": "how?"}) == "answer"
    assert await t.ainvoke({"question": "again?"}) == "answer"
    (p1, c1, k1), (_, c2, _) = agent.calls
    assert isinstance(p1["messages"][0], HumanMessage) and p1["messages"][0].content == "how?"
    assert c1["recursion_limit"] == 7 and k1 == {}
    t1, t2 = c1["configurable"]["thread_id"], c2["configurable"]["thread_id"]
    assert t1.startswith("fake-") and t2.startswith("fake-") and t1 != t2


async def test_agent_tool_passes_context_only_when_set():
    agent = FakeAgent()
    ctx = object()
    await make(lambda: Invocation(agent, context=ctx)).ainvoke({"question": "q"})
    assert agent.calls[0][2] == {"context": ctx}


async def test_agent_tool_returns_the_failure_text_when_prepare_or_the_run_fails():
    def broken_prepare():
        raise RuntimeError("db down")

    assert (
        await make(broken_prepare).ainvoke({"question": "q"})
        == "The fake failed (RuntimeError: db down); carry on."
    )
    agent = FakeAgent(error=ValueError("bad"))
    assert (
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})
        == "The fake failed (ValueError: bad); carry on."
    )


async def test_agent_tool_lets_graph_control_flow_propagate():
    agent = FakeAgent(error=GraphInterrupt())
    with pytest.raises(GraphInterrupt):
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})


async def test_agent_tool_returns_the_empty_text_when_there_is_no_final_answer():
    call = AIMessage(
        content="", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    agent = FakeAgent(messages=[call])
    assert (
        await make(lambda: Invocation(agent)).ainvoke({"question": "q"})
        == "The fake returned no answer."
    )


def test_agent_tool_schema_is_one_question_string_titled_by_name():
    schema = make(lambda: Invocation(FakeAgent())).tool_call_schema.model_json_schema()
    assert schema["title"] == "ask_fake" and schema["required"] == ["question"]
    assert schema["properties"] == {"question": {"title": "Question", "type": "string"}}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_agent_tool.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness.agent_tool'`.

- [ ] **Step 3: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/agent_tool.py`:

```python
"""An agent run as a tool: each call prepares the agent, runs it on a throwaway thread and returns
its final text, or the failure as text. Interrupts and other graph control flow propagate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp

from tri_core.harness.messages import last_ai_text


@dataclass(frozen=True)
class Invocation:
    agent: Any
    context: Any = None  # passed to ainvoke as context= only when set


def agent_tool(
    *,
    name: str,
    description: str,
    prepare: Callable[[], Invocation],
    thread_prefix: str,
    recursion_limit: int,
    failure: str,
    empty: str,
) -> BaseTool:
    async def run(question: str) -> str:
        try:
            invocation = prepare()
            kwargs: dict[str, Any] = {}
            if invocation.context is not None:
                kwargs["context"] = invocation.context
            out = await invocation.agent.ainvoke(
                {"messages": [HumanMessage(question)]},
                {
                    "configurable": {"thread_id": f"{thread_prefix}-{uuid4()}"},
                    "recursion_limit": recursion_limit,
                },
                **kwargs,
            )
        except GraphBubbleUp:
            raise  # interrupts and other langgraph control flow must keep propagating
        except Exception as exc:
            return failure.format(error=f"{type(exc).__name__}: {exc}")
        return last_ai_text(out["messages"]) or empty

    return StructuredTool.from_function(coroutine=run, name=name, description=description)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_agent_tool.py -v`
Expected: 6 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `917 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/agent_tool.py packages/tri-core/tests/test_harness_agent_tool.py
git commit -m "feat(core): harness agent_tool runs an agent on a throwaway thread"
```

---

### Task 4: `handoff.py`: leaving a sub-agent through `Command.PARENT`

**Files:**
- Create: `packages/tri-core/src/tri_core/harness/handoff.py`
- Test: `packages/tri-core/tests/test_harness_handoff.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `NOT_DELIVERED: str`
  - `turn_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]`
  - `undelivered(turn: Sequence[AnyMessage], handoff_call_id: str) -> list[ToolMessage]`
  - `handoff(goto: str, *, tool_call_id: str, messages: Sequence[AnyMessage], ack: ToolMessage, update: Mapping[str, Any] | None = None) -> Command[str]`

- [ ] **Step 1: Write the failing test**

Create `packages/tri-core/tests/test_harness_handoff.py`:

```python
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from tri_core.harness.handoff import NOT_DELIVERED, handoff, turn_messages, undelivered


def calls(*id_names: tuple[str, str]) -> AIMessage:
    return AIMessage(
        content="",
        id="ai",
        tool_calls=[{"name": n, "args": {}, "id": i, "type": "tool_call"} for i, n in id_names],
    )


def test_not_delivered_keeps_todays_text():
    assert NOT_DELIVERED == (
        "not delivered: this step ended with a handoff; call again if still needed"
    )


def test_turn_messages_is_everything_after_the_last_human_message():
    h1, a1, h2 = HumanMessage("a", id="1"), AIMessage("b", id="2"), HumanMessage("c", id="3")
    a2 = AIMessage(
        "", id="4", tool_calls=[{"name": "x", "args": {}, "id": "c1", "type": "tool_call"}]
    )
    t2 = ToolMessage("r", tool_call_id="c1", id="5")
    assert turn_messages([h1, a1, h2, a2, t2]) == [a2, t2]
    assert turn_messages([h1, a1]) == [a1]
    assert turn_messages([]) == []


def test_undelivered_answers_every_sibling_call_the_handoff_cut_off():
    ai = calls(("r1", "remember"), ("c1", "consult_planning"), ("r2", "remember"))
    answered = ToolMessage("ok", tool_call_id="r2", name="remember", id="t2")
    out = undelivered([ai, answered], "c1")
    assert [(m.tool_call_id, m.name, m.content) for m in out] == [
        ("r1", "remember", NOT_DELIVERED)
    ]
    assert out[0].id


def test_undelivered_is_empty_without_an_ai_message():
    assert undelivered([HumanMessage("hi")], "c1") == []


def test_handoff_jumps_in_the_parent_graph_with_the_turn_re_emitted():
    human = HumanMessage("tired", id="h")
    ai = calls(("r1", "remember"), ("c1", "consult_planning"))
    ack = ToolMessage("consulted", tool_call_id="c1", name="consult_planning", id="ack")
    cmd = handoff("planning", tool_call_id="c1", messages=[human, ai], ack=ack, update={"brief": "b"})
    assert isinstance(cmd, Command)
    assert cmd.goto == "planning" and cmd.graph == Command.PARENT
    assert cmd.update["brief"] == "b"
    emitted = cmd.update["messages"]
    assert [m.id for m in emitted][0] == "ai" and emitted[-1] is ack and len(emitted) == 3
    assert emitted[1].tool_call_id == "r1" and emitted[1].content == NOT_DELIVERED


def test_handoff_without_update_carries_only_the_messages():
    ai = calls(("c1", "propose_changes"))
    ack = ToolMessage("sent", tool_call_id="c1", name="propose_changes", id="ack")
    cmd = handoff("review", tool_call_id="c1", messages=[ai], ack=ack)
    assert set(cmd.update) == {"messages"} and cmd.update["messages"] == [ai, ack]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_handoff.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness.handoff'`.

- [ ] **Step 3: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/handoff.py`. `NOT_DELIVERED`, `turn_messages` and `undelivered` are copied from `packages/tri-coach/src/tri_coach/tools/handoff.py` without change; `handoff` is new.

```python
"""Handoffs: leaving a create_agent sub-agent for another node of the parent graph.

A tool inside create_agent that returns Command(graph=Command.PARENT) unwinds the agent before
its model step is committed, so the AIMessage that made the call would be lost and the parent's
history would hold a tool result with no tool use. A handoff therefore re-emits the turn's
messages (ids intact; add_messages upserts), a result for every sibling call the unwinding cut
off, and its own acknowledgement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import Command


def turn_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Everything after the last HumanMessage: the messages this turn produced so far."""
    last = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last = i
    return list(messages[last + 1 :])


NOT_DELIVERED = "not delivered: this step ended with a handoff; call again if still needed"


def undelivered(turn: Sequence[AnyMessage], handoff_call_id: str) -> list[ToolMessage]:
    """A result for every sibling call of the handoff that the tools node will never answer.

    The sub-agent unwinds the moment a handoff tool returns, so a call made alongside it in the
    same step loses its result. Anthropic rejects a persisted history that holds a tool_use with
    no tool_result, which would break every later turn on the thread."""
    last_ai = next((m for m in reversed(turn) if isinstance(m, AIMessage)), None)
    if last_ai is None:
        return []
    answered = {m.tool_call_id for m in turn if isinstance(m, ToolMessage)} | {handoff_call_id}
    return [
        ToolMessage(content=NOT_DELIVERED, tool_call_id=tc["id"], name=tc["name"], id=str(uuid4()))
        for tc in last_ai.tool_calls
        if tc["id"] and tc["id"] not in answered
    ]


def handoff(
    goto: str,
    *,
    tool_call_id: str,
    messages: Sequence[AnyMessage],
    ack: ToolMessage,
    update: Mapping[str, Any] | None = None,
) -> Command[str]:
    """Jump to `goto` in the parent graph, carrying `update` and the turn's messages."""
    turn = turn_messages(messages)
    return Command(
        goto=goto,
        graph=Command.PARENT,
        update={**(update or {}), "messages": [*turn, *undelivered(turn, tool_call_id), ack]},
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_handoff.py -v`
Expected: 6 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `923 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/handoff.py packages/tri-core/tests/test_harness_handoff.py
git commit -m "feat(core): harness handoff re-emits the turn through Command.PARENT"
```

---

### Task 5: `persistence.py`: checkpointer, store, readiness and hints

**Files:**
- Create: `packages/tri-core/src/tri_core/harness/persistence.py`
- Modify: `packages/tri-core/src/tri_core/testing/fakes.py` (append `StateSample`)
- Test: `packages/tri-core/tests/test_harness_persistence.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SETUP_HINT: str`
  - `STORE_SETUP_HINT: str`
  - `make_serde(state_types: Sequence[type]) -> JsonPlusSerializer`
  - `open_checkpointer(url: str, state_types: Sequence[type]) -> AbstractAsyncContextManager[AsyncPostgresSaver]`
  - `checkpointer_ready(url: str) -> bool`
  - `open_store(url: str) -> AbstractAsyncContextManager[AsyncPostgresStore]`
  - `store_ready(url: str) -> bool`
  - `tri_core.testing.fakes.StateSample(name: str, minutes: int)`

- [ ] **Step 1: Add the test model**

Append to `packages/tri-core/src/tri_core/testing/fakes.py`. Add `from pydantic import BaseModel` to its imports, in the third-party group after the `langchain_core` imports:

```python
class StateSample(BaseModel):
    """A pydantic model importable by module path, for serializer round-trip tests."""

    name: str
    minutes: int
```

- [ ] **Step 2: Write the failing test**

Create `packages/tri-core/tests/test_harness_persistence.py`:

```python
import logging
import uuid

import pytest
from langgraph.checkpoint.serde import jsonplus

from tri_core.config import Settings
from tri_core.harness.persistence import (
    SETUP_HINT,
    STORE_SETUP_HINT,
    checkpointer_ready,
    make_serde,
    open_checkpointer,
    open_store,
    store_ready,
)
from tri_core.testing.fakes import StateSample

UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/nope"
TAIL = (
    "run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def test_setup_hints_keep_todays_text():
    assert SETUP_HINT == "checkpoint tables are missing; " + TAIL
    assert STORE_SETUP_HINT == "LangGraph store tables are missing; " + TAIL


def test_make_serde_round_trips_registered_models_without_the_unregistered_warning(caplog):
    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    serde = make_serde([StateSample])
    value = {"pending": [StateSample(name="Ride", minutes=60)]}
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed(value))
    assert back == value
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]


def test_readiness_checks_are_false_when_the_database_is_unreachable():
    assert checkpointer_ready(UNREACHABLE) is False
    assert store_ready(UNREACHABLE) is False


@pytest.mark.db
async def test_checkpointer_and_store_open_against_the_test_database():
    url = Settings().test_database_url
    if not (checkpointer_ready(url) and store_ready(url)):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"harness-{uuid.uuid4()}"}}
    async with open_checkpointer(url, [StateSample]) as saver:
        assert await saver.aget_tuple(thread) is None
    async with open_store(url) as store:
        assert await store.aget(("harness-test", str(uuid.uuid4())), "missing") is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_persistence.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness.persistence'`.

- [ ] **Step 4: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/persistence.py`. The hint texts are copied from `tri_planning/graph/checkpointer.py` (`SETUP_HINT`) and `tri_nutrition/store.py` (`STORE_SETUP_HINT`):

```python
"""Postgres persistence for every graph. The checkpointer makes `interrupt()` durable: every
super-step writes a checkpoint keyed by thread_id, and `Command(resume=...)` in a fresh process
picks up from it. The Store holds what must outlive any thread. The app never creates tables;
scripts/setup_checkpointer.py does."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.postgres.aio import AsyncPostgresStore

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)

STORE_SETUP_HINT = (
    "LangGraph store tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def make_serde(state_types: Sequence[type]) -> JsonPlusSerializer:
    """A serializer that accepts the pydantic models a graph keeps in its state. Registering them
    keeps the checkpointer from warning (and, in strict mode, refusing) when it loads them."""
    return JsonPlusSerializer(allowed_msgpack_modules=tuple(state_types))


@asynccontextmanager
async def open_checkpointer(
    url: str, state_types: Sequence[type]
) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url, serde=make_serde(state_types)) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])


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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_persistence.py -v`
Expected: 4 passed. If the test database's LangGraph tables are missing, the `db` test shows as skipped; report that rather than treating it as a pass.

- [ ] **Step 6: Definition of done**

Run the six commands from Global Constraints.
Expected: `927 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/persistence.py packages/tri-core/src/tri_core/testing/fakes.py packages/tri-core/tests/test_harness_persistence.py
git commit -m "feat(core): harness persistence — checkpointer, store, readiness and hints"
```

---

### Task 6: `turns.py` part 1: error sentences, config, and the stream loop

**Files:**
- Create: `packages/tri-core/src/tri_core/harness/turns.py`
- Test: `packages/tri-core/tests/test_harness_turns.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Out = Callable[[str], None]`
  - `DEFAULT_RATE_LIMIT_HINT = "Wait a moment and try again."`
  - `class TurnSink(Protocol): def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None`
  - `@dataclass(frozen=True) class TurnFailure: exc: Exception; message: str`
  - `api_error_message(exc: BaseException, *, rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT) -> str | None`
  - `turn_config(thread_id: str, *, tags: Sequence[str] | None = None, recursion_limit: int | None = None) -> dict[str, Any]`
  - `async stream_turn(runnable: Any, payload: Any, config: dict[str, Any], sink: TurnSink, *, subgraphs: bool, stream_mode: str | Sequence[str] | None = None, context: Any = None, catch_all: str | None = None, rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT) -> TurnFailure | None`
  - `format_failure(failure: TurnFailure) -> str`

- [ ] **Step 1: Write the failing test**

Create `packages/tri-core/tests/test_harness_turns.py`:

```python
import anthropic
import httpx
import pytest

from tri_core.harness.turns import (
    TurnFailure,
    api_error_message,
    format_failure,
    stream_turn,
    turn_config,
)

REQ = httpx.Request("POST", "https://api.anthropic.com")
INGEST_HINT = "Wait a moment and rerun; the thread resumes."


def rate_limited() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(
        message="slow down", response=httpx.Response(429, request=REQ), body=None
    )


def server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError(
        message="boom", response=httpx.Response(500, request=REQ), body=None
    )


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=REQ)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_event(self, namespace, mode, data) -> None:
        self.events.append((namespace, mode, data))


class ScriptedRunnable:
    """astream yields the given items, then raises `error` if one is set; records its kwargs."""

    def __init__(self, items, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.kwargs: dict | None = None

    async def astream(self, payload, **kwargs):
        self.kwargs = kwargs
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def test_api_error_message_matches_todays_sentences():
    assert api_error_message(rate_limited()) == (
        "rate limited: slow down. Wait a moment and try again."
    )
    assert api_error_message(rate_limited(), rate_limit_hint=INGEST_HINT) == (
        "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    )
    assert api_error_message(server_error()) == "Anthropic API error 500: boom"
    assert api_error_message(connection_error()) == (
        "connection error talking to Anthropic: Connection error."
    )
    assert api_error_message(RuntimeError("x")) is None


def test_turn_config_adds_the_limit_and_tags_only_when_given():
    assert turn_config("t") == {"configurable": {"thread_id": "t"}}
    assert turn_config("t", tags=[]) == {"configurable": {"thread_id": "t"}}
    assert turn_config("coach", tags=("checkin",), recursion_limit=60) == {
        "configurable": {"thread_id": "coach"},
        "recursion_limit": 60,
        "tags": ["checkin"],
    }


async def test_stream_turn_normalises_subgraph_items():
    runnable = ScriptedRunnable([(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})])
    sink = Recorder()
    cfg = turn_config("t")
    assert await stream_turn(runnable, {"messages": []}, cfg, sink, subgraphs=True) is None
    assert sink.events == [(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})]
    assert runnable.kwargs == {
        "config": cfg,
        "stream_mode": ["messages", "updates"],
        "subgraphs": True,
    }


async def test_stream_turn_normalises_list_mode_items_and_passes_context_when_set():
    runnable = ScriptedRunnable([("messages", "m"), ("updates", {"b": 2})])
    sink = Recorder()
    ctx = object()
    await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False, context=ctx)
    assert sink.events == [((), "messages", "m"), ((), "updates", {"b": 2})]
    assert runnable.kwargs["context"] is ctx and "subgraphs" not in runnable.kwargs


async def test_stream_turn_normalises_single_mode_items():
    runnable = ScriptedRunnable([{"extract": {}}, {"store": {"panel_id": 3}}])
    sink = Recorder()
    await stream_turn(
        runnable, {}, turn_config("t"), sink, subgraphs=False, stream_mode="updates"
    )
    assert sink.events == [
        ((), "updates", {"extract": {}}),
        ((), "updates", {"store": {"panel_id": 3}}),
    ]
    assert runnable.kwargs["stream_mode"] == "updates" and "context" not in runnable.kwargs


async def test_stream_turn_returns_a_failure_for_anthropic_errors_after_earlier_events():
    runnable = ScriptedRunnable([("updates", {"a": 1})], error=connection_error())
    sink = Recorder()
    failure = await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False)
    assert isinstance(failure, TurnFailure)
    assert isinstance(failure.exc, anthropic.APIConnectionError)
    assert failure.message == "connection error talking to Anthropic: Connection error."
    assert len(sink.events) == 1
    assert format_failure(failure) == (
        "\n[connection error talking to Anthropic: Connection error.]\n"
    )


async def test_stream_turn_propagates_other_errors_unless_catch_all_is_set():
    with pytest.raises(RuntimeError, match="kaboom"):
        await stream_turn(
            ScriptedRunnable([], error=RuntimeError("kaboom")),
            {},
            turn_config("t"),
            Recorder(),
            subgraphs=True,
        )
    failure = await stream_turn(
        ScriptedRunnable([], error=RuntimeError("kaboom")),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=True,
        catch_all="ingest failed",
    )
    assert failure is not None and failure.message == "ingest failed: RuntimeError: kaboom"


async def test_stream_turn_uses_the_rate_limit_hint():
    failure = await stream_turn(
        ScriptedRunnable([], error=rate_limited()),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=False,
        rate_limit_hint=INGEST_HINT,
    )
    assert failure is not None
    assert failure.message == "rate limited: slow down. Wait a moment and rerun; the thread resumes."
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_turns.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.harness.turns'`.

- [ ] **Step 3: Write the implementation**

Create `packages/tri-core/src/tri_core/harness/turns.py`:

```python
"""The turn driver every REPL shares: one stream loop that feeds a sink, and the sentences an
Anthropic error becomes. The loop never prints; the drivers decide how a failure reads."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

Out = Callable[[str], None]

DEFAULT_RATE_LIMIT_HINT = "Wait a moment and try again."
DEFAULT_STREAM_MODES = ("messages", "updates")


class TurnSink(Protocol):
    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None: ...


@dataclass(frozen=True)
class TurnFailure:
    exc: Exception
    message: str  # no brackets or newlines


def api_error_message(
    exc: BaseException, *, rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT
) -> str | None:
    """The sentence for an Anthropic error, or None for anything else. RateLimitError is an
    APIStatusError, so it is checked first."""
    if isinstance(exc, anthropic.RateLimitError):
        return f"rate limited: {exc}. {rate_limit_hint}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return f"connection error talking to Anthropic: {exc}"
    return None


def turn_config(
    thread_id: str, *, tags: Sequence[str] | None = None, recursion_limit: int | None = None
) -> dict[str, Any]:
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if recursion_limit is not None:
        cfg["recursion_limit"] = recursion_limit
    if tags:
        cfg["tags"] = list(tags)
    return cfg


async def stream_turn(
    runnable: Any,
    payload: Any,
    config: dict[str, Any],
    sink: TurnSink,
    *,
    subgraphs: bool,
    stream_mode: str | Sequence[str] | None = None,
    context: Any = None,
    catch_all: str | None = None,
    rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT,
) -> TurnFailure | None:
    """Stream one run into `sink` as (namespace, mode, data). An Anthropic error, or any error
    when `catch_all` names the failure, ends the run as a TurnFailure; anything else propagates.
    `subgraphs` and `context` reach astream only when set."""
    mode: str | list[str]
    if stream_mode is None:
        mode = list(DEFAULT_STREAM_MODES)
    elif isinstance(stream_mode, str):
        mode = stream_mode
    else:
        mode = list(stream_mode)
    kwargs: dict[str, Any] = {"config": config, "stream_mode": mode}
    if subgraphs:
        kwargs["subgraphs"] = True
    if context is not None:
        kwargs["context"] = context
    try:
        async for item in runnable.astream(payload, **kwargs):
            if subgraphs:
                namespace, event_mode, data = item
                sink.on_event(tuple(namespace), event_mode, data)
            elif isinstance(mode, str):
                sink.on_event((), mode, item)
            else:
                event_mode, data = item
                sink.on_event((), event_mode, data)
    except Exception as exc:
        message = api_error_message(exc, rate_limit_hint=rate_limit_hint)
        if message is None:
            if catch_all is None:
                raise
            message = f"{catch_all}: {type(exc).__name__}: {exc}"
        return TurnFailure(exc, message)
    return None


def format_failure(failure: TurnFailure) -> str:
    """How a REPL prints a failed turn: on its own bracketed line."""
    return f"\n[{failure.message}]\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/tri-core/tests/test_harness_turns.py -v`
Expected: 8 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `935 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/turns.py packages/tri-core/tests/test_harness_turns.py
git commit -m "feat(core): harness stream_turn and the Anthropic error sentences"
```

---

### Task 7: `turns.py` part 2: printers and the two drivers

**Files:**
- Modify: `packages/tri-core/src/tri_core/harness/turns.py` (append)
- Test: `packages/tri-core/tests/test_harness_turns.py` (append)

**Interfaces:**
- Consumes (Task 6): `Out`, `TurnSink`, `turn_config`, `stream_turn`, `format_failure`. Consumes (Task 1): `text_of`. Consumes (Task 2, in tests only): `build_chat_agent`.
- Produces:
  - `class AgentTurnPrinter: __init__(self, out: Out) -> None; out: Out; final_text: str; on_event(namespace, mode, data) -> None`
  - `class GraphTurnPrinter: __init__(self, out: Out, streamed_nodes: frozenset[str] = frozenset()) -> None; out: Out; final_text: str; interrupt: dict[str, Any] | None; error: str | None; on_event(namespace, mode, data) -> None`
  - `async run_agent_turn(agent: Any, text: str, thread_id: str, out: Out, *, context: Any = None, tags: Sequence[str] | None = None, catch_all: str | None = None) -> str`
  - `async run_graph_turn(graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out, *, streamed_nodes: frozenset[str] = frozenset()) -> GraphTurnPrinter`

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_harness_turns.py`. Merge these imports into the file's import block and let `ruff check --fix` order them:

```python
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Interrupt

from tri_core.harness.agents import build_chat_agent
from tri_core.harness.turns import (
    AgentTurnPrinter,
    GraphTurnPrinter,
    run_agent_turn,
    run_graph_turn,
)
from tri_core.testing import ScriptedChatModel, tool_call
```

Then append:

```python
@tool
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def _capture():
    buf: list[str] = []
    return buf, buf.append


class FakeAgent:
    """Records what run_agent_turn hands to astream and answers with one final message."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def astream(self, payload, config=None, stream_mode=None, context=None):
        self.calls.append((payload, config, stream_mode, context))
        yield ("updates", {"model": {"messages": [AIMessage(content="ok")]}})


class ConnectionBoom(ScriptedChatModel):
    def _stream(self, *a, **k):
        raise anthropic.APIConnectionError(request=REQ)


class RuntimeBoom(ScriptedChatModel):
    def _stream(self, *a, **k):
        raise RuntimeError("kaboom")


async def test_run_agent_turn_streams_text_and_shows_tool_calls():
    model = ScriptedChatModel(
        script=[tool_call("add", {"a": 2, "b": 3}), AIMessage(content="It is 5.")]
    )
    buf, out = _capture()
    final = await run_agent_turn(build_chat_agent(model, [add]), "add 2 and 3", "t", out)
    text = "".join(buf)
    assert final == "It is 5."
    assert "→ add({'a': 2, 'b': 3})" in text
    assert "← add: 1 chars" in text
    assert text.rstrip().endswith("It is 5.")


async def test_run_agent_turn_passes_context_tags_thread_and_stream_modes():
    fake = FakeAgent()
    ctx = object()
    buf, out = _capture()
    assert await run_agent_turn(fake, "hi", "t9", out, context=ctx, tags=["chat"]) == "ok"
    payload, config, mode, context = fake.calls[0]
    assert payload["messages"][0].content == "hi"
    assert config["configurable"]["thread_id"] == "t9" and config["tags"] == ["chat"]
    assert mode == ["messages", "updates"] and context is ctx
    await run_agent_turn(fake, "again", "t9", out)
    assert "tags" not in fake.calls[1][1] and fake.calls[1][3] is None


async def test_run_agent_turn_reports_api_errors_without_raising():
    agent = build_chat_agent(ConnectionBoom(script=[]), [add])
    buf, out = _capture()
    assert await run_agent_turn(agent, "hi", "t", out) == ""
    assert "\n[connection error talking to Anthropic: Connection error.]\n" in buf


async def test_run_agent_turn_with_catch_all_reports_any_other_exception():
    agent = build_chat_agent(RuntimeBoom(script=[]), [add])
    buf, out = _capture()
    assert await run_agent_turn(agent, "hi", "t", out, catch_all="the turn failed") == ""
    assert "[the turn failed: RuntimeError: kaboom]" in "".join(buf)


async def test_run_agent_turn_without_catch_all_propagates_other_exceptions():
    agent = build_chat_agent(RuntimeBoom(script=[]), [add])
    buf, out = _capture()
    with pytest.raises(RuntimeError, match="kaboom"):
        await run_agent_turn(agent, "hi", "t", out)


def test_agent_printer_ignores_namespace_and_reads_text_blocks():
    printer = AgentTurnPrinter(lambda s: None)
    printer.on_event(
        ("any:1",),
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert printer.final_text == "x"


def test_graph_printer_handles_subgraph_events_interrupt_and_streamed_nodes():
    buf: list[str] = []
    printer = GraphTurnPrinter(buf.append, frozenset({"intake", "adjust"}))
    meta = {"langgraph_node": "model"}
    printer.on_event(("intake:abc",), "messages", (AIMessageChunk(content="Hel"), meta))
    printer.on_event(("intake:abc",), "messages", (AIMessageChunk(content="lo"), meta))
    tool_msg = ToolMessage(content="{}", name="set_training_goal", tool_call_id="1")
    printer.on_event(("intake:abc",), "updates", {"tools": {"messages": [tool_msg]}})
    printer.on_event(
        (), "updates", {"targets": {"messages": [AIMessage(content="Targets: 14 weeks")]}}
    )
    stop = Interrupt(value={"summary": "s", "changes": []})
    printer.on_event((), "updates", {"__interrupt__": (stop,)})
    printer.on_event((), "updates", {"intake": {"messages": [AIMessage(content="Hello")]}})
    text = "".join(buf)
    assert "Hello" in text and "← set_training_goal" in text and "Targets: 14 weeks" in text
    assert text.count("Hello") == 1 and "[intake]" not in text
    assert "[targets] Targets: 14 weeks" in text
    assert printer.interrupt == {"summary": "s", "changes": []}
    assert printer.error is None


async def test_run_graph_turn_streams_subgraphs_on_the_thread():
    class StubGraph:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            self.calls.append((payload, config, stream_mode, subgraphs))
            chunk = AIMessageChunk(content="Hi")
            yield (("adjust:1",), "messages", (chunk, {"langgraph_node": "model"}))

    graph = StubGraph()
    buf: list[str] = []
    printer = await run_graph_turn(graph, {"messages": []}, "planning", buf.append)
    assert isinstance(printer, GraphTurnPrinter)
    assert printer.final_text == "Hi" and printer.error is None
    assert graph.calls == [
        ({"messages": []}, {"configurable": {"thread_id": "planning"}}, ["messages", "updates"], True)
    ]


async def test_run_graph_turn_sets_error_on_api_connection_failure():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            raise anthropic.APIConnectionError(request=REQ)
            yield  # pragma: no cover - makes this an async generator

    buf: list[str] = []
    printer = await run_graph_turn(RaisingGraph(), {"messages": []}, "planning", buf.append)
    assert printer.error == "\n[connection error talking to Anthropic: Connection error.]\n"
    assert printer.error in buf
    assert printer.interrupt is None


async def test_run_graph_turn_propagates_non_anthropic_errors():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None, subgraphs=False):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover - makes this an async generator

    with pytest.raises(RuntimeError, match="kaboom"):
        await run_graph_turn(RaisingGraph(), {"messages": []}, "planning", lambda s: None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_harness_turns.py -v`
Expected: collection error, `ImportError: cannot import name 'AgentTurnPrinter' from 'tri_core.harness.turns'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/harness/turns.py`, extend the imports to:

```python
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command

from tri_core.harness.messages import text_of
```

Append to the module. `AgentTurnPrinter.on_event` is `tri_analyze.repl.TurnPrinter.on_event` with a `namespace` parameter it ignores. `GraphTurnPrinter` is `tri_planning.repl.TurnPrinter` with `STREAMED_NODES` replaced by `self.streamed_nodes`.

```python
class AgentTurnPrinter:
    """Renders agent stream events to `out`. Text streams inline; tool activity gets lines."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode == "updates" and isinstance(data, dict):
            for node, payload in data.items():
                for msg in (payload or {}).get("messages", []):
                    if node == "model" and isinstance(msg, AIMessage):
                        for tc in msg.tool_calls:
                            self.out(f"\n→ {tc['name']}({tc['args']})\n")
                        if not msg.tool_calls:
                            # the update carries the whole final message; prefer it to the
                            # accumulated chunks, which may include text from earlier tool turns
                            self.final_text = text_of(msg) or self.final_text
                            self.out("\n")
                    elif node == "tools" and isinstance(msg, ToolMessage):
                        self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")


class GraphTurnPrinter:
    """Renders a graph run with subgraphs. Conversational nodes stream their text from inside
    their subgraph, so their root updates (`streamed_nodes`) are skipped; other root nodes print
    their message as `[node] text`. The first interrupt's value is kept."""

    def __init__(self, out: Out, streamed_nodes: frozenset[str] = frozenset()) -> None:
        self.out = out
        self.streamed_nodes = streamed_nodes
        self.final_text = ""
        self.interrupt: dict[str, Any] | None = None
        self.error: str | None = None

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
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
            if not namespace and node in self.streamed_nodes:
                continue
            for msg in (payload or {}).get("messages", []):
                if node == "model" and isinstance(msg, AIMessage):
                    for tc in msg.tool_calls:
                        self.out(f"\n→ {tc['name']}({tc['args']})\n")
                    if not msg.tool_calls:
                        self.final_text = text_of(msg) or self.final_text
                        self.out("\n")
                elif node == "tools" and isinstance(msg, ToolMessage):
                    self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")
                elif not namespace and isinstance(msg, AIMessage):
                    text = text_of(msg)
                    self.out(f"[{node}] {text}\n")
                    self.final_text = text


async def run_agent_turn(
    agent: Any,
    text: str,
    thread_id: str,
    out: Out,
    *,
    context: Any = None,
    tags: Sequence[str] | None = None,
    catch_all: str | None = None,
) -> str:
    """One chat turn: stream the agent, print as it goes, return the final text. A failure is
    printed and the thread keeps its last checkpoint."""
    printer = AgentTurnPrinter(out)
    failure = await stream_turn(
        agent,
        {"messages": [HumanMessage(text)]},
        turn_config(thread_id, tags=tags),
        printer,
        subgraphs=False,
        context=context,
        catch_all=catch_all,
    )
    if failure is not None:
        out(format_failure(failure))
    return printer.final_text


async def run_graph_turn(
    graph: Any,
    payload: dict[str, Any] | Command[Any],
    thread_id: str,
    out: Out,
    *,
    streamed_nodes: frozenset[str] = frozenset(),
) -> GraphTurnPrinter:
    """One graph turn with subgraphs. An Anthropic failure is printed and kept in
    `printer.error`; any other error propagates."""
    printer = GraphTurnPrinter(out, streamed_nodes)
    failure = await stream_turn(graph, payload, turn_config(thread_id), printer, subgraphs=True)
    if failure is not None:
        printer.error = format_failure(failure)
        out(printer.error)
    return printer
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_harness_turns.py -v`
Expected: 18 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `945 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/harness/turns.py packages/tri-core/tests/test_harness_turns.py
git commit -m "feat(core): harness agent and graph turn printers and drivers"
```

---

### Task 8: README, scope check, and final verification

**Files:**
- Modify: `packages/tri-core/README.md`

**Interfaces:**
- Consumes: every module from Tasks 1–7.
- Produces: nothing new.

- [ ] **Step 1: Update the README**

In `packages/tri-core/README.md`, replace the paragraph under `# tri-core` with:

```markdown
Shared code for the triathlon agents: `tri_core.config` (settings), `tri_core.mcp` (server specs
and a stdio MCP client), `tri_core.db` (connection, row models, repository), `tri_core.sync` (the
ETL behind `tri sync`), `tri_core.harness` (the agent harness every package builds on), and
`tri_core.testing` (the `db` fixture, `ScriptedChatModel` and `StateSample`). See the READMEs
inside `src/tri_core/{mcp,db,sync}/`.

## Harness

| Module | What it holds |
|---|---|
| `harness.messages` | `text_of`, `last_ai_text` |
| `harness.agents` | `make_subagent` (no checkpointer; the parent graph owns the messages), `build_chat_agent` (a thread per conversation, in memory by default), `one_tool_call_at_a_time`. Prompt caching is always the last middleware. |
| `harness.agent_tool` | `agent_tool` and `Invocation`: an agent run on a throwaway thread, exposed as a one-question tool |
| `harness.handoff` | `handoff`, `turn_messages`, `undelivered`: leaving a sub-agent through `Command.PARENT` with a valid history |
| `harness.persistence` | `open_checkpointer(url, state_types)`, `open_store`, `checkpointer_ready`, `store_ready`, `make_serde`, `SETUP_HINT`, `STORE_SETUP_HINT` |
| `harness.turns` | `stream_turn`, `AgentTurnPrinter`, `GraphTurnPrinter`, `run_agent_turn`, `run_graph_turn`, `api_error_message`, `turn_config` |

Spec: `docs/superpowers/specs/2026-09-15-tri-harness-design.md`.
```

Copy the file to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-core/readme.md`, creating the directory if it does not exist.

- [ ] **Step 2: Check that nothing outside this plan's files changed**

Run: `git diff --name-only main...HEAD`
Expected: exactly these paths:

```
packages/tri-core/README.md
packages/tri-core/pyproject.toml
packages/tri-core/src/tri_core/harness/__init__.py
packages/tri-core/src/tri_core/harness/agent_tool.py
packages/tri-core/src/tri_core/harness/agents.py
packages/tri-core/src/tri_core/harness/handoff.py
packages/tri-core/src/tri_core/harness/messages.py
packages/tri-core/src/tri_core/harness/persistence.py
packages/tri-core/src/tri_core/harness/turns.py
packages/tri-core/src/tri_core/testing/fakes.py
packages/tri-core/tests/test_harness_agent_tool.py
packages/tri-core/tests/test_harness_agents.py
packages/tri-core/tests/test_harness_handoff.py
packages/tri-core/tests/test_harness_messages.py
packages/tri-core/tests/test_harness_persistence.py
packages/tri-core/tests/test_harness_turns.py
uv.lock
```

Run: `git diff main...HEAD -- uv.lock | grep '^[-+]version'`
Expected: no output.

- [ ] **Step 3: Definition of done**

Run the six commands from Global Constraints.
Expected: `945 passed, 6 skipped, 1 warning`, which is the baseline 903 plus 42 new tests. Ruff clean, `mypy` `Success`. This plan adds no build step: tri-core has no build command, and `web/` is untouched.

- [ ] **Step 4: Commit**

```bash
git add packages/tri-core/README.md
git commit -m "docs(core): tri-core README describes tri_core.harness"
```

---

## Self-review against the spec

- **§4 tri-core layout:** the pyproject dependencies are Task 1; `harness/{__init__,messages}` Task 1; `agents` Task 2; `agent_tool` Task 3; `handoff` Task 4; `persistence` Task 5; `turns` Tasks 6–7. All six `tests/test_harness_*.py` files are covered.
- **§5 interfaces:**
  - §5.1 `messages`: Task 1.
  - §5.2 `agents`: Task 2, including the middleware order and `checkpointer=False`.
  - §5.3 `agent_tool`: Task 3, including prepare failures inside `try`, the context-only-when-set rule, `GraphBubbleUp`, the `{error}` format and the schema.
  - §5.4 `handoff`: Task 4.
  - §5.5 `persistence`: Task 5, including both hints (the spec was corrected on 2026-09-15: `STORE_SETUP_HINT` keeps its own text).
  - §5.6 `turns`: Tasks 6–7. `stream_mode=None` stands in for the spec's list default; see "Decisions".
- **§5.7 (package wrappers), §6 (behaviour in callers) and the plans 02–04 rules in §7** are out of scope for this plan. Plan 01 changes no caller, and Task 8 Step 2 proves it.
- **§7 plan 01 tests:** messages (Task 1); agents (Task 2: round trip, no checkpointer, history, middleware order, parallel calls off); agent_tool (Task 3); handoff (Task 4); persistence (Task 5: serde, db open, unreachable readiness); turns (Tasks 6–7: error sentences, config, the three stream shapes, `catch_all`, context, both printers, both drivers).
- **Type consistency:** `Invocation(agent, context)` is the same in Task 3's code and tests. `stream_turn(..., subgraphs=, stream_mode=, context=, catch_all=, rate_limit_hint=)` is the same in Tasks 6–7. `GraphTurnPrinter(out, streamed_nodes)` is the same in Task 7's code, tests and `run_graph_turn`.
