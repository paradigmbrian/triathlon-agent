# tri-harness Plan 2 of 4: tri-analyze and tri-wellness onto `tri_core.harness` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tri-analyze and tri-wellness stop carrying their own copies of the harness. Their agent builders, text helper, turn printers, stream loops and checkpointer module give way to `tri_core.harness`, with no change to anything a user or a test can observe.

**Architecture:** Package by package, unit by unit. Task 1 pins today's exact error lines with three characterization tests on the old code. The next tasks each migrate one coherent unit: the analyst builder, the analyze REPL, wellness persistence, the wellness chat agent, and the wellness REPL. For each unit the package's tests run green before the change and after it. Public entry points keep their names and signatures: `tri_analyze.agent.build_agent`, `tri_analyze.repl.run_turn`, `tri_wellness.repl.run_turn`, `tri_wellness.repl.run_chat_turn`. Only their bodies move onto the harness. `tri_wellness/agent.py` and `tri_wellness/graph/checkpointer.py` are deleted.

**Tech Stack:** Python 3.12, `tri_core.harness` from plan 1 (`agents.build_chat_agent`, `messages.text_of`, `persistence.{SETUP_HINT, checkpointer_ready, make_serde, open_checkpointer}`, `turns.{Out, run_agent_turn, stream_turn, turn_config}`), langchain 1.4.0, langgraph 1.2.11, anthropic 1.4.0, pytest with `pytest-asyncio` 1.4.0 in auto mode.

**Spec:** `docs/superpowers/specs/2026-09-15-tri-harness-design.md`. This plan implements §5.7 (tri-analyze and tri-wellness parts), §6 (behaviour kept), the plans 02–04 rules in §7, and §9 item 2. Plan 1 (`docs/superpowers/plans/2026-09-15-tri-harness-01-core.md`) defines every harness name used here.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Plan 1 must be on `main` first.** Check from the main checkout:
  - `git log main --oneline | grep "tri_core.harness package"` prints a commit.
  - `git show main:packages/tri-core/src/tri_core/harness/turns.py | grep -c "def run_graph_turn"` prints `1`.

  If either check fails, stop: this plan cannot start.
- **Execute in a sibling worktree:** run `git worktree add ../triathlon_agent-harness-02 -b feat/tri-harness-02 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout.
- **Baseline** after plan 1 on `main`: `945 passed, 6 skipped, 1 warning` (the six skips are `--live`). If the number differs, record the actual baseline and shift every expected count below by the same amount.
- **Existing tests:** assertions and expected values are not edited. Only these may change: imports, how a test constructs a moved object (`build_agent(...)` becomes `build_chat_agent(..., system_prompt=...)`, `make_serde()` becomes `make_serde(STATE_TYPES)`), and string `monkeypatch.setattr` targets. If any existing assertion fails after a migration step, stop and see "Stop conditions".
- **Behaviour stays byte-identical** (spec §6): every error line, printed progress line, thread id, tag, middleware order and tool description.
- **Files this plan may touch:**
  - `packages/tri-analyze/src/tri_analyze/{agent,repl}.py`, `evals/target.py`
  - `packages/tri-analyze/tests/test_repl.py`
  - `packages/tri-analyze/README.md`
  - `packages/tri-wellness/src/tri_wellness/{agent,repl,report,cli}.py`, `graph/{checkpointer,state}.py`
  - `packages/tri-wellness/tests/{test_chat,test_checkpointer,test_cli,test_repl}.py`
  - `packages/tri-coach/src/tri_coach/tools/wellness.py`

  Nothing under `tri-core`, `tri-planning`, `tri-nutrition`, `tri-web` or `web/`.
- **Commits:** Git commits are permitted (Brian's standing permission). Commit once per task on `feat/tri-harness-02`, and end every commit message with the `Co-Authored-By:` trailer of the session executing the plan.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages/tri-analyze packages/tri-wellness packages/tri-coach`
  2. `uv run ruff check --fix packages/tri-analyze packages/tri-wellness packages/tri-coach`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing one.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file created or edited in this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).

### Facts verified while writing this plan (against `main` 3a5a82c, 2026-09-15)

1. **tri-analyze and tri-wellness tests on `main`:** `240 passed, 3 skipped`. Test counts in the files this plan touches: `tri-analyze/tests/test_agent.py` 7, `test_repl.py` 8; `tri-wellness/tests/test_chat.py` 3, `test_checkpointer.py` 2, `test_cli.py` 11, `test_repl.py` 15.
2. **Every importer of what this plan moves or deletes** (source and tests, all packages and `scripts/`):
   - `tri_wellness.agent.build_agent`: `tri_wellness/cli.py:193` (`_chat`), `tri_coach/tools/wellness.py:23`, `tri-wellness/tests/test_chat.py:6`.
   - `tri_wellness.graph.checkpointer`: `tri_wellness/cli.py:94` (`_ingest`), `tri-wellness/tests/test_checkpointer.py:10`, and the string patch at `tri-wellness/tests/test_cli.py:115`.
   - `tri_wellness.repl.text_of`: `tri_wellness/report.py:21`, which also imports `Out` from there.
   - `tri_analyze.repl.text_of`: `tri_analyze/evals/target.py:20`, `tri-analyze/tests/test_repl.py:9`.
   - `tri_analyze.repl.TurnPrinter`: `tri-analyze/tests/test_repl.py:9` only.
   - `tri_analyze.agent.build_agent`: `tri_analyze/cli.py:59`, `evals/target.py:17`, `tri_coach/tools/analyst.py:19`, and tests. Its signature does not change, so none of these are edited.
   - `tri_wellness.testing`, `tri_analyze.testing` and `tri-coach/tests/test_evals.py` (which builds `make_wellness_tool`) import none of the moved names.
3. **Where the spec's §9 item 2 lists fall short:**
   - `packages/tri-analyze/README.md:115` lists `repl.py  text_of, TurnPrinter, run_turn, chat_loop` and must change.
   - `tri_wellness/report.py` imports `Out` from `tri_wellness.repl`. Under `mypy --strict` (`no_implicit_reexport`), a bare `from tri_core.harness.turns import Out` in `repl.py` would not re-export it, so `repl.py` uses `from tri_core.harness.turns import Out as Out`.
   - No other file is missing from the spec's lists. No wellness README line names `agent.py`, `checkpointer.py`, `text_of` or `TurnPrinter`.
4. **Output of today's code**, probed with raising fakes:
   - Wellness ingest `run_turn` on a `RateLimitError("slow down")` sets `result.error == "rate limited: slow down. Wait a moment and rerun; the thread resumes."` and prints exactly `["[rate limited: slow down. Wait a moment and rerun; the thread resumes.]\n"]`.
   - `run_chat_turn` on `APIConnectionError` returns `""` and prints `["\n[connection error talking to Anthropic: Connection error.]\n"]`. On `RuntimeError("kaboom")` it raises.
   - tri-analyze `run_turn` on `RateLimitError("slow down")` prints `["\n[rate limited: slow down. Wait a moment and try again.]\n"]`.
5. **Fake signatures in existing tests**, which plan 1's `stream_turn` must satisfy:
   - wellness `test_repl.py` `RaisingGraph.astream(self, payload, config=None, stream_mode=None)`. It has no `subgraphs` or `context` parameters; `stream_turn` sends neither when `subgraphs=False` and `context is None`.
   - analyze `test_repl.py` `FakeAgent.astream(self, payload, config=None, stream_mode=None, context=None)`.
6. `tri_wellness/graph/state.py` already imports `LabResult`, `PanelContext`, `RawResult` and `Unmapped`, the four `STATE_TYPES`.
7. **Pure-duplicate test deleted by this plan:** `tri-analyze/tests/test_repl.py::test_turn_printer_ignores_non_text_chunks_and_text_of_reads_blocks`. Plan 1 covers it with `tri-core/tests/test_harness_turns.py::test_agent_printer_ignores_namespace_and_reads_text_blocks`, plus `test_harness_messages.py::test_text_of_joins_text_blocks_and_bare_strings_and_skips_other_blocks` and `::test_text_of_returns_string_content_unchanged`. No wellness test only duplicates a harness test. The wellness `run_turn` tests exercise the ingest sink, and `test_checkpointer.py`'s serde test exercises wellness's own `STATE_TYPES`.

### Stop conditions

None found while writing. Stop and report to Brian, without editing the assertion, if any of these happens:
- Any existing assertion in the test files listed above fails after its migration step. That is a behaviour change.
- Any of the three Task 1 characterization tests fails after Task 3, 5 or 6.
- `mypy` reports that `Out` is not exported from `tri_wellness.repl` even with the `as Out` form.

---

## File Structure

```
packages/tri-analyze/
  src/tri_analyze/agent.py          Task 2: build_agent body → build_chat_agent (signature, tags, metadata kept)
  src/tri_analyze/repl.py           Task 3: text_of and TurnPrinter removed; run_turn → run_agent_turn
  src/tri_analyze/evals/target.py   Task 3: text_of from tri_core.harness.messages
  tests/test_repl.py                Task 1: +1 characterization test; Task 3: import line, one duplicate test deleted
  README.md                         Task 3: layout line for repl.py
packages/tri-wellness/
  src/tri_wellness/graph/checkpointer.py   Task 4: deleted
  src/tri_wellness/graph/state.py          Task 4: STATE_TYPES
  src/tri_wellness/cli.py                  Task 4: _ingest imports; Task 5: _chat builder
  src/tri_wellness/agent.py                Task 5: deleted
  src/tri_wellness/repl.py                 Task 6: text_of and TurnPrinter removed; run_turn on stream_turn;
                                                   run_chat_turn → run_agent_turn
  src/tri_wellness/report.py               Task 6: text_of from tri_core.harness.messages
  tests/test_repl.py                       Task 1: +1 characterization test
  tests/test_chat.py                       Task 1: +1 characterization test; Task 5: builder construction
  tests/test_checkpointer.py               Task 4: imports, make_serde(STATE_TYPES), open_checkpointer(url, STATE_TYPES)
  tests/test_cli.py                        Task 4: patch target string
packages/tri-coach/src/tri_coach/tools/wellness.py   Task 5: build_chat_agent
```

Expected full-suite counts after each task: T1 `948`, T2 `948`, T3 `947`, T4 `947`, T5 `947`, T6 `947`, T7 `947` passed, always with `6 skipped`.

---

### Task 1: Pin today's error lines with characterization tests

**Files:**
- Test: `packages/tri-analyze/tests/test_repl.py` (append)
- Test: `packages/tri-wellness/tests/test_repl.py` (append)
- Test: `packages/tri-wellness/tests/test_chat.py` (append, plus imports)

**Interfaces:**
- Consumes: today's `tri_analyze.repl.run_turn`, `tri_wellness.repl.run_turn`, `tri_wellness.repl.run_chat_turn`.
- Produces: three tests that must pass unchanged through Tasks 3, 5 and 6.

These tests describe the code as it is, so they pass immediately. Their job is to fail if a later task changes a single byte of output.

- [ ] **Step 1: Append the analyze test**

Append to `packages/tri-analyze/tests/test_repl.py`. The file already imports `anthropic`, `httpx`, `_capture`, `CTX` and `run_turn`.

```python
async def test_run_turn_prints_the_exact_rate_limit_line():
    class RaisingAgent:
        async def astream(self, payload, config=None, stream_mode=None, context=None):
            raise anthropic.RateLimitError(
                message="slow down",
                response=httpx.Response(
                    429, request=httpx.Request("POST", "https://api.anthropic.com")
                ),
                body=None,
            )
            yield  # pragma: no cover - makes this an async generator

    buf, out = _capture()
    assert await run_turn(RaisingAgent(), "hi", "t", out, context=CTX) == ""
    assert buf == ["\n[rate limited: slow down. Wait a moment and try again.]\n"]
```

- [ ] **Step 2: Append the wellness ingest test**

Append to `packages/tri-wellness/tests/test_repl.py`. The file already imports `anthropic`, `httpx` and `run_turn`.

```python
async def test_run_turn_rate_limit_line_keeps_the_resume_hint():
    class RaisingGraph:
        async def astream(self, payload, config=None, stream_mode=None):
            raise anthropic.RateLimitError(
                message="slow down",
                response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
                body=None,
            )
            yield  # pragma: no cover - makes this an async generator

    out = []
    result = await run_turn(RaisingGraph(), {"source_path": "x"}, "t1", out.append)
    assert result.error == "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    assert out == ["[rate limited: slow down. Wait a moment and rerun; the thread resumes.]\n"]
    assert result.interrupt is None
```

- [ ] **Step 3: Append the wellness chat test**

In `packages/tri-wellness/tests/test_chat.py`, replace the first import line:

```python
from datetime import date, datetime
```

with:

```python
from datetime import date, datetime

import anthropic
import httpx
import pytest
```

Then append:

```python
async def test_run_chat_turn_prints_api_errors_and_lets_other_errors_propagate():
    class RaisingAgent:
        def __init__(self, exc):
            self.exc = exc

        async def astream(self, payload, config=None, stream_mode=None):
            raise self.exc
            yield  # pragma: no cover - makes this an async generator

    out = []
    conn = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )
    assert await run_chat_turn(RaisingAgent(conn), "hi", "t", out.append) == ""
    assert out == ["\n[connection error talking to Anthropic: Connection error.]\n"]
    with pytest.raises(RuntimeError, match="kaboom"):
        await run_chat_turn(RaisingAgent(RuntimeError("kaboom")), "hi", "t", out.append)
```

- [ ] **Step 4: Run the three tests on the old code**

Run: `uv run pytest packages/tri-analyze/tests/test_repl.py::test_run_turn_prints_the_exact_rate_limit_line packages/tri-wellness/tests/test_repl.py::test_run_turn_rate_limit_line_keeps_the_resume_hint packages/tri-wellness/tests/test_chat.py::test_run_chat_turn_prints_api_errors_and_lets_other_errors_propagate -v`
Expected: 3 passed. If one fails, the test does not describe today's behaviour. Fix the test to match the output shown in the failure, never the code, and note the difference in the commit message.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `948 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-analyze/tests/test_repl.py packages/tri-wellness/tests/test_repl.py packages/tri-wellness/tests/test_chat.py
git commit -m "test(analyze,wellness): pin today's turn error lines before the harness move"
```

---

### Task 2: `tri_analyze.agent.build_agent` on `build_chat_agent`

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/agent.py`
- Test (unchanged, must stay green): `packages/tri-analyze/tests/test_agent.py`

**Interfaces:**
- Consumes (plan 1): `tri_core.harness.agents.build_chat_agent(model, tools, *, system_prompt=None, middleware=(), context_schema=None, checkpointer=None) -> Any`.
- Produces: `tri_analyze.agent.build_agent(model: BaseChatModel, tools: Sequence[BaseTool], checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any`, with the same signature as today. Middleware is still `[analyst_prompt, caching]`, the context schema is still `AthleteContext`, the checkpointer still defaults to an `InMemorySaver`, and the config still carries `tags=["analyst"]` and `metadata={"analyst_prompt_version": PROMPT_VERSION}`.

- [ ] **Step 1: Run the tests on the old code**

Run: `uv run pytest packages/tri-analyze/tests/test_agent.py packages/tri-analyze/tests/test_repl.py -q`
Expected: 16 passed (7 + 9, including Task 1's test).

- [ ] **Step 2: Replace the module**

Replace the whole of `packages/tri-analyze/src/tri_analyze/agent.py` with:

```python
"""The analyst agent: a model-and-tools loop whose system prompt is rendered before each model
call from the athlete context passed as runtime context and the names of the bound tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from tri_analyze.prompts.analyst import PROMPT_VERSION, render_system_prompt
from tri_analyze.repo import AthleteContext
from tri_core.harness.agents import build_chat_agent


@dynamic_prompt
def analyst_prompt(request: ModelRequest[AthleteContext]) -> str:
    """Render the system prompt from the run's context and the tools bound to this request."""
    names = [t.name if isinstance(t, BaseTool) else str(t["name"]) for t in request.tools]
    return render_system_prompt(request.runtime.context, names)


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools. Every run must pass
    `context=<AthleteContext>`. The prompt middleware runs first so the caching middleware marks
    the rendered system prompt; tool order is the order given, which keeps the cached prefix
    stable. Runs carry the `analyst` tag and the prompt version as metadata."""
    agent = build_chat_agent(
        model,
        tools,
        middleware=[analyst_prompt],
        context_schema=AthleteContext,
        checkpointer=checkpointer,
    )
    return agent.with_config(
        {"tags": ["analyst"], "metadata": {"analyst_prompt_version": PROMPT_VERSION}}
    )
```

What changed: the imports of `create_agent`, `AgentMiddleware`, `AnthropicPromptCachingMiddleware` and `InMemorySaver` are gone. `build_chat_agent` appends caching after `analyst_prompt` and supplies `InMemorySaver()` when `checkpointer` is `None`, so the agent is built exactly as before.

- [ ] **Step 3: Run the tests again**

Run: `uv run pytest packages/tri-analyze/tests/test_agent.py packages/tri-analyze/tests/test_repl.py -q`
Expected: 16 passed.

- [ ] **Step 4: Definition of done**

Run the six commands from Global Constraints.
Expected: `948 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 5: Commit**

```bash
git add packages/tri-analyze/src/tri_analyze/agent.py
git commit -m "refactor(analyze): build_agent builds through tri_core.harness.build_chat_agent"
```

---

### Task 3: tri-analyze REPL and eval target onto the harness

**Files:**
- Modify: `packages/tri-analyze/src/tri_analyze/repl.py`
- Modify: `packages/tri-analyze/src/tri_analyze/evals/target.py`
- Modify: `packages/tri-analyze/tests/test_repl.py`
- Modify: `packages/tri-analyze/README.md`

**Interfaces:**
- Consumes (plan 1):
  - `tri_core.harness.turns.Out`
  - `tri_core.harness.turns.run_agent_turn(agent, text, thread_id, out, *, context=None, tags=None, catch_all=None) -> str`
  - `tri_core.harness.messages.text_of(msg) -> str`
- Produces: `tri_analyze.repl.run_turn(agent: Any, text: str, thread_id: str, out: Out, *, context: AthleteContext, tags: list[str] | None = None) -> str` with the same signature and output as today; `tri_analyze.repl.chat_loop` unchanged; `tri_analyze.repl.Command` unchanged.

- [ ] **Step 1: Run the tests on the old code**

Run: `uv run pytest packages/tri-analyze -q`
Expected: every tri-analyze test passes (skips are the `db` ones when the database is down; note the numbers).

- [ ] **Step 2: Replace `repl.py` above `chat_loop`**

In `packages/tri-analyze/src/tri_analyze/repl.py`, replace everything from the first line down to the line before `async def chat_loop(` with:

```python
"""Terminal REPL: stream a turn, show tool calls, loop.

`stream_mode=["messages", "updates"]` yields ("messages", (chunk, meta)) for token-level output
and ("updates", {node: {...}}) when a node finishes. Tool calls are visible in the model node's
update; tool results arrive as ToolMessages from the tools node. The stream loop and the printer
are tri_core.harness.turns.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from tri_analyze.repo import AthleteContext
from tri_core.harness.turns import Out, run_agent_turn

Command = Callable[[], Awaitable[str]]


async def run_turn(
    agent: Any,
    text: str,
    thread_id: str,
    out: Out,
    *,
    context: AthleteContext,
    tags: list[str] | None = None,
) -> str:
    """One turn: stream the agent, print as it goes, return the final text. Anthropic errors and
    any other failure are printed; the loop continues and the thread keeps its last checkpoint."""
    return await run_agent_turn(
        agent, text, thread_id, out, context=context, tags=tags, catch_all="the turn failed"
    )


```

`chat_loop` and everything below it stay exactly as they are.

- [ ] **Step 3: Point the eval target at the harness `text_of`**

In `packages/tri-analyze/src/tri_analyze/evals/target.py`, replace:

```python
from tri_analyze.evals.cases import SQL_ENVELOPE_EMPTY
from tri_analyze.repl import text_of
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool
```

with:

```python
from tri_analyze.evals.cases import SQL_ENVELOPE_EMPTY
from tri_analyze.repo import AthleteContext
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.messages import text_of
```

- [ ] **Step 4: Update the REPL test's import and delete the duplicate test**

In `packages/tri-analyze/tests/test_repl.py`, replace:

```python
from tri_analyze.repl import TurnPrinter, chat_loop, run_turn, text_of
```

with:

```python
from tri_analyze.repl import chat_loop, run_turn
```

Delete this whole test. Plan 1 covers it with `tri-core/tests/test_harness_turns.py::test_agent_printer_ignores_namespace_and_reads_text_blocks`, plus `test_harness_messages.py::test_text_of_joins_text_blocks_and_bare_strings_and_skips_other_blocks` and `::test_text_of_returns_string_content_unchanged`:

```python
def test_turn_printer_ignores_non_text_chunks_and_text_of_reads_blocks():
    p = TurnPrinter(lambda s: None)
    p.on_event(
        "messages",
        (AIMessage(content=[{"type": "text", "text": "x"}]), {"langgraph_node": "model"}),
    )
    assert p.final_text == "x"
    assert text_of(AIMessage(content=[{"type": "text", "text": "a"}, "b"])) == "ab"
    assert text_of(AIMessage(content="plain")) == "plain"
```

No other line in the file changes.

- [ ] **Step 5: Update the README layout line**

In `packages/tri-analyze/README.md`, replace:

```
  repl.py             text_of, TurnPrinter, run_turn, chat_loop
```

with:

```
  repl.py             run_turn (over tri_core.harness.turns.run_agent_turn), chat_loop
```

Copy the file to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-analyze/readme.md`, creating the directory if it does not exist.

- [ ] **Step 6: Run the tests again**

Run: `uv run pytest packages/tri-analyze -q`
Expected: the Step 1 numbers minus one passed test, and the same skips. Every run_turn and chat_loop test passes with its assertions untouched, including `test_run_turn_reports_any_other_exception_and_returns` (`"[the turn failed: RuntimeError: kaboom]"`) and Task 1's exact rate-limit line.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `947 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-analyze/src/tri_analyze/repl.py packages/tri-analyze/src/tri_analyze/evals/target.py packages/tri-analyze/tests/test_repl.py packages/tri-analyze/README.md
git commit -m "refactor(analyze): REPL turns and eval text run on tri_core.harness"
```

---

### Task 4: tri-wellness persistence: `graph/checkpointer.py` deleted

**Files:**
- Delete: `packages/tri-wellness/src/tri_wellness/graph/checkpointer.py`
- Modify: `packages/tri-wellness/src/tri_wellness/graph/state.py`
- Modify: `packages/tri-wellness/src/tri_wellness/cli.py` (`_ingest` only)
- Modify: `packages/tri-wellness/tests/test_checkpointer.py`
- Modify: `packages/tri-wellness/tests/test_cli.py`

**Interfaces:**
- Consumes (plan 1):
  - `tri_core.harness.persistence.SETUP_HINT`
  - `checkpointer_ready(url) -> bool`
  - `make_serde(state_types) -> JsonPlusSerializer`
  - `open_checkpointer(url, state_types)`
- Produces: `tri_wellness.graph.state.STATE_TYPES: tuple[type, ...] = (RawResult, LabResult, Unmapped, PanelContext)`, the same tuple in the same order.

- [ ] **Step 1: Run the tests on the old code**

Run: `uv run pytest packages/tri-wellness/tests/test_checkpointer.py packages/tri-wellness/tests/test_cli.py -q`
Expected: 13 passed, or 12 passed and 1 skipped when the test database's LangGraph tables are missing.

- [ ] **Step 2: Add `STATE_TYPES` to the state module**

In `packages/tri-wellness/src/tri_wellness/graph/state.py`, replace:

```python
from tri_wellness.labs.models import IngestKind, LabResult, PanelContext, RawResult, Unmapped


class IngestState(TypedDict, total=False):
```

with:

```python
from tri_wellness.labs.models import IngestKind, LabResult, PanelContext, RawResult, Unmapped

# Pydantic models that live in IngestState. Registering them with the checkpointer's serializer
# keeps it from warning (and, in strict mode, refusing) when it loads them. Ingest threads are
# keyed `ingest:<sha256>`.
STATE_TYPES: tuple[type, ...] = (RawResult, LabResult, Unmapped, PanelContext)


class IngestState(TypedDict, total=False):
```

- [ ] **Step 3: Delete the checkpointer module**

Run: `git rm packages/tri-wellness/src/tri_wellness/graph/checkpointer.py`

- [ ] **Step 4: Point `_ingest` at the harness**

In `packages/tri-wellness/src/tri_wellness/cli.py`, inside `async def _ingest`, replace:

```python
    from tri_wellness.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_wellness.graph.deps import make_deps
    from tri_wellness.graph.graph import build_ingest_graph
    from tri_wellness.graph.llm import make_model
```

with:

```python
    from tri_core.harness.persistence import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_wellness.graph.deps import make_deps
    from tri_wellness.graph.graph import build_ingest_graph
    from tri_wellness.graph.llm import make_model
    from tri_wellness.graph.state import STATE_TYPES
```

and, further down the same function, replace:

```python
    async with open_checkpointer(settings.database_url) as saver:
```

with:

```python
    async with open_checkpointer(settings.database_url, STATE_TYPES) as saver:
```

The imports stay inside the function body, so a test's string patch of `tri_core.harness.persistence.checkpointer_ready` still takes effect.

- [ ] **Step 5: Update `test_checkpointer.py`**

In `packages/tri-wellness/tests/test_checkpointer.py`, replace:

```python
from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.checkpointer import checkpointer_ready, make_serde, open_checkpointer
from tri_wellness.graph.graph import build_ingest_graph
```

with:

```python
from tri_core.config import Settings
from tri_core.harness.persistence import checkpointer_ready, make_serde, open_checkpointer
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.graph import build_ingest_graph
from tri_wellness.graph.state import STATE_TYPES
```

Replace:

```python
    serde = make_serde()
```

with:

```python
    serde = make_serde(STATE_TYPES)
```

Replace each of the three lines:

```python
        async with open_checkpointer(url) as saver:
```
```python
        async with open_checkpointer(url) as saver2:
```
```python
        async with open_checkpointer(url) as saver3:
```

with, respectively:

```python
        async with open_checkpointer(url, STATE_TYPES) as saver:
```
```python
        async with open_checkpointer(url, STATE_TYPES) as saver2:
```
```python
        async with open_checkpointer(url, STATE_TYPES) as saver3:
```

- [ ] **Step 6: Retarget the CLI test's patch**

In `packages/tri-wellness/tests/test_cli.py`, replace:

```python
    monkeypatch.setattr("tri_wellness.graph.checkpointer.checkpointer_ready", lambda url: False)
```

with:

```python
    monkeypatch.setattr("tri_core.harness.persistence.checkpointer_ready", lambda url: False)
```

- [ ] **Step 7: Run the tests again**

Run: `uv run pytest packages/tri-wellness/tests/test_checkpointer.py packages/tri-wellness/tests/test_cli.py -q`
Expected: the same numbers as Step 1. `test_ingest_checkpointer_missing_exits_2` still finds `"checkpoint tables are missing"` in the output.

- [ ] **Step 8: Definition of done**

Run the six commands from Global Constraints.
Expected: `947 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 9: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/graph/state.py packages/tri-wellness/src/tri_wellness/cli.py packages/tri-wellness/tests/test_checkpointer.py packages/tri-wellness/tests/test_cli.py
git commit -m "refactor(wellness): ingest checkpointing through tri_core.harness.persistence"
```

(`git rm` already staged the deletion.)

---

### Task 5: tri-wellness chat agent: `agent.py` deleted

**Files:**
- Delete: `packages/tri-wellness/src/tri_wellness/agent.py`
- Modify: `packages/tri-wellness/src/tri_wellness/cli.py` (`_chat` only)
- Modify: `packages/tri-coach/src/tri_coach/tools/wellness.py`
- Modify: `packages/tri-wellness/tests/test_chat.py`

**Interfaces:**
- Consumes (plan 1): `tri_core.harness.agents.build_chat_agent(model, tools, *, system_prompt=None, middleware=(), context_schema=None, checkpointer=None) -> Any`.
- Produces: nothing new. Today's `tri_wellness.agent.build_agent(model, tools, system_prompt, checkpointer=None)` builds `create_agent(model, list(tools), system_prompt=..., middleware=[caching], checkpointer=checkpointer or InMemorySaver())`. `build_chat_agent(model, tools, system_prompt=..., checkpointer=...)` builds the same agent.

- [ ] **Step 1: Run the tests on the old code**

Run: `uv run pytest packages/tri-wellness/tests/test_chat.py packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_evals.py -q`
Expected: all pass. Note the numbers; `db` tests skip without the test database.

- [ ] **Step 2: Delete the module**

Run: `git rm packages/tri-wellness/src/tri_wellness/agent.py`

- [ ] **Step 3: Build the chat agent through the harness in `_chat`**

In `packages/tri-wellness/src/tri_wellness/cli.py`, inside `async def _chat`, replace:

```python
    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_wellness import repo
    from tri_wellness.agent import build_agent
    from tri_wellness.graph.llm import make_model
```

with:

```python
    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_core.harness.agents import build_chat_agent
    from tri_wellness import repo
    from tri_wellness.graph.llm import make_model
```

and replace:

```python
    agent = build_agent(make_model(settings), tools, prompt)
```

with:

```python
    agent = build_chat_agent(make_model(settings), tools, system_prompt=prompt)
```

- [ ] **Step 4: Build `ask_wellness`'s agent through the harness**

In `packages/tri-coach/src/tri_coach/tools/wellness.py`, replace:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_wellness import repo
from tri_wellness.agent import build_agent
from tri_wellness.prompts.chat import render_chat_prompt
```

with:

```python
from tri_core.db.sql_tool import make_query_tool
from tri_core.harness.agents import build_chat_agent
from tri_wellness import repo
from tri_wellness.prompts.chat import render_chat_prompt
```

and replace:

```python
            agent = build_agent(model, tools, prompt, InMemorySaver())
```

with:

```python
            agent = build_chat_agent(model, tools, system_prompt=prompt, checkpointer=InMemorySaver())
```

The tool's name, docstring (its description), thread prefix `wellness-`, recursion limit, failure and empty sentences are untouched. Plan 4 turns this function into `agent_tool(...)`.

- [ ] **Step 5: Update `test_chat.py`'s construction**

In `packages/tri-wellness/tests/test_chat.py`, replace:

```python
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.agent import build_agent
from tri_wellness.labs.models import PanelSummary, StoredReport
```

with:

```python
from tri_core.harness.agents import build_chat_agent
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.labs.models import PanelSummary, StoredReport
```

Replace:

```python
    agent = build_agent(model, tools, "sys")
```

with:

```python
    agent = build_chat_agent(model, tools, system_prompt="sys")
```

Replace:

```python
    agent = build_agent(model, [], "sys")
```

with:

```python
    agent = build_chat_agent(model, [], system_prompt="sys")
```

- [ ] **Step 6: Run the tests again**

Run: `uv run pytest packages/tri-wellness/tests/test_chat.py packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_evals.py -q`
Expected: the same numbers as Step 1.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `947 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/cli.py packages/tri-coach/src/tri_coach/tools/wellness.py packages/tri-wellness/tests/test_chat.py
git commit -m "refactor(wellness): chat and ask_wellness agents build through tri_core.harness"
```

---

### Task 6: tri-wellness REPL: ingest turns and chat turns on the harness

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py`
- Modify: `packages/tri-wellness/src/tri_wellness/report.py`
- Test (unchanged, must stay green): `packages/tri-wellness/tests/test_repl.py`, `test_chat.py`, `test_report.py`, `test_panels.py`

**Interfaces:**
- Consumes (plan 1):
  - `tri_core.harness.turns.Out`
  - `stream_turn(runnable, payload, config, sink, *, subgraphs, stream_mode=None, context=None, catch_all=None, rate_limit_hint=...) -> TurnFailure | None`
  - `turn_config(thread_id, *, tags=None, recursion_limit=None) -> dict[str, Any]`
  - `run_agent_turn(agent, text, thread_id, out, *, context=None, tags=None, catch_all=None) -> str`
  - `tri_core.harness.messages.text_of`
- Produces, with the same signatures and output as today:
  - `tri_wellness.repl.run_turn(graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out) -> TurnResult`
  - `tri_wellness.repl.run_chat_turn(agent: Any, text: str, thread_id: str, out: Out) -> str`
  - `tri_wellness.repl.Out` stays importable, as an explicit re-export.

- [ ] **Step 1: Run the tests on the old code**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass. Note the numbers.

- [ ] **Step 2: Replace the imports at the top of `repl.py`**

In `packages/tri-wellness/src/tri_wellness/repl.py`, replace:

```python
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

from tri_wellness.labs.models import (
```

with:

```python
import yaml
from langgraph.types import Command

from tri_core.harness.turns import Out as Out
from tri_core.harness.turns import run_agent_turn, stream_turn, turn_config
from tri_wellness.labs.models import (
```

and replace:

```python
Out = Callable[[str], None]
Read = Callable[[], Awaitable[str | None]]
```

with:

```python
Read = Callable[[], Awaitable[str | None]]
```

`Out as Out` is deliberate: `report.py` imports `Out` from this module, and `mypy --strict` only re-exports an imported name written this way. If `ruff check --fix` merges the two `tri_core.harness.turns` lines, keep whatever form it produces as long as `Out as Out` survives.

- [ ] **Step 3: Run the ingest `run_turn` on `stream_turn`**

Replace the whole of `async def run_turn` (from `async def run_turn(` through its `return result`) with:

```python
class _IngestSink:
    """Prints extract and store progress as the ingest graph's nodes finish, and keeps the review
    interrupt."""

    def __init__(self, out: Out, result: TurnResult) -> None:
        self.out = out
        self.result = result

    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None:
        if not isinstance(data, dict):
            return
        if "__interrupt__" in data:
            self.result.interrupt = dict(data["__interrupt__"][0].value)
        elif "extract" in data:
            u = data["extract"] or {}
            pages = f", {u['page_count']} pages" if u.get("page_count") else ""
            self.out(f"extracted {len(u.get('raw_results') or [])} rows{pages}\n")
            if u.get("last_error"):
                self.out(f"ingest failed: {u['last_error']}\n")
        elif "store" in data:
            self.out(f"stored panel {(data['store'] or {}).get('panel_id')}\n")


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> TurnResult:
    result = TurnResult()
    failure = await stream_turn(
        graph,
        payload,
        turn_config(thread_id),
        _IngestSink(out, result),
        subgraphs=False,
        stream_mode="updates",
        catch_all="ingest failed",
        rate_limit_hint="Wait a moment and rerun; the thread resumes.",
    )
    if failure is not None:
        result.error = failure.message
    if result.error:
        out(f"[{result.error}]\n")
    return result
```

`TurnResult` (the `@dataclass` just above) is unchanged.

- [ ] **Step 4: Remove `text_of` and `TurnPrinter`; run chat turns on `run_agent_turn`**

Delete the whole `def text_of(msg: BaseMessage) -> str:` function, which sits between `render_panels` and `ChatCommand = ...`, and the whole `class TurnPrinter:`. Keep:

```python
ChatCommand = Callable[[str], Awaitable[str]]
```

Replace the whole of `async def run_chat_turn` (from `async def run_chat_turn(` through `return printer.final_text`) with:

```python
async def run_chat_turn(agent: Any, text: str, thread_id: str, out: Out) -> str:
    return await run_agent_turn(agent, text, thread_id, out)
```

`chat_loop` and everything else in the module are unchanged.

- [ ] **Step 5: Point `report.py` at the harness `text_of`**

In `packages/tri-wellness/src/tri_wellness/report.py`, replace:

```python
from tri_core.db.repo import Conn
from tri_wellness import repo
```

with:

```python
from tri_core.db.repo import Conn
from tri_core.harness.messages import text_of
from tri_wellness import repo
```

and replace:

```python
from tri_wellness.repl import Out, text_of
```

with:

```python
from tri_wellness.repl import Out
```

- [ ] **Step 6: Run the tests again**

Run: `uv run pytest packages/tri-wellness -q`
Expected: the same numbers as Step 1. In particular these pass with untouched assertions:
- `test_run_turn_sets_error_on_api_connection_failure`
- `test_run_turn_sets_error_on_unexpected_exception` (now through `catch_all="ingest failed"`)
- `test_run_ingest_returns_1_when_graph_raises`
- Task 1's `test_run_turn_rate_limit_line_keeps_the_resume_hint` and `test_run_chat_turn_prints_api_errors_and_lets_other_errors_propagate`

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `947 passed, 6 skipped`, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-wellness/src/tri_wellness/repl.py packages/tri-wellness/src/tri_wellness/report.py
git commit -m "refactor(wellness): ingest and chat turns run on tri_core.harness.turns"
```

---

### Task 7: Nothing left behind: greps, docs, final verification

**Files:**
- Modify only if a grep below finds a hit: the file it names, plus its Obsidian copy for markdown.

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: nothing new.

- [ ] **Step 1: No harness copies remain in the two packages**

Run: `rg -n "def (text_of|_text_of)\b|class TurnPrinter\b|def make_serde\b|def open_checkpointer\b|def checkpointer_ready\b" packages/tri-analyze packages/tri-wellness`
Expected: no output.

Run: `rg -n "\bbuild_agent\b" packages/tri-wellness packages/tri-coach/src/tri_coach/tools/wellness.py`
Expected: no output.

Run: `test ! -e packages/tri-wellness/src/tri_wellness/agent.py && test ! -e packages/tri-wellness/src/tri_wellness/graph/checkpointer.py && test ! -e packages/tri-analyze/src/tri_analyze/graph/checkpointer.py && echo gone`
Expected: `gone`.

- [ ] **Step 2: No importer of a deleted path remains**

Run: `rg -n "tri_wellness\.agent\b|tri_wellness\.graph\.checkpointer|from tri_analyze\.repl import .*\b(text_of|TurnPrinter)\b|from tri_wellness\.repl import .*\btext_of\b" packages scripts`
Expected: no output.

- [ ] **Step 3: No doc names a deleted module or symbol**

Run: `rg -n "tri_wellness/agent\.py|tri_wellness\.agent|text_of|TurnPrinter|run_chat_turn|graph/checkpointer\.py" README.md packages/tri-analyze packages/tri-wellness --glob '*.md'`
Expected: at most `packages/tri-analyze/README.md` with the line from Task 3 (`run_turn (over tri_core.harness.turns.run_agent_turn), chat_loop`) and no other hit.

For any other hit, edit the line to name `tri_core.harness` in place of the deleted path, copy that file to its Obsidian path, and include it in this task's commit.

- [ ] **Step 4: Only this plan's files changed**

Run: `git diff --name-only main...HEAD`
Expected: exactly these paths:

```
packages/tri-analyze/README.md
packages/tri-analyze/src/tri_analyze/agent.py
packages/tri-analyze/src/tri_analyze/evals/target.py
packages/tri-analyze/src/tri_analyze/repl.py
packages/tri-analyze/tests/test_repl.py
packages/tri-coach/src/tri_coach/tools/wellness.py
packages/tri-wellness/src/tri_wellness/agent.py
packages/tri-wellness/src/tri_wellness/cli.py
packages/tri-wellness/src/tri_wellness/graph/checkpointer.py
packages/tri-wellness/src/tri_wellness/graph/state.py
packages/tri-wellness/src/tri_wellness/repl.py
packages/tri-wellness/src/tri_wellness/report.py
packages/tri-wellness/tests/test_chat.py
packages/tri-wellness/tests/test_checkpointer.py
packages/tri-wellness/tests/test_cli.py
packages/tri-wellness/tests/test_repl.py
```

plus any doc fixed in Step 3.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `947 passed, 6 skipped, 1 warning`: the baseline 945, plus 3 characterization tests, minus 1 duplicate. Ruff clean, `mypy` `Success`. This plan has no build step: `web/` and tri-web are untouched.

- [ ] **Step 6: Commit (only if Step 3 changed a file)**

```bash
git add <the files Step 3 changed>
git commit -m "docs(analyze,wellness): name tri_core.harness where docs named deleted modules"
```

---

## Self-review against the spec

- **§5.7, tri-analyze:**
  - `run_turn` wraps `run_agent_turn(..., context=context, tags=tags, catch_all="the turn failed")`: Task 3.
  - `build_agent` keeps its signature and adds analyst middleware, context schema, tags and metadata on top of `build_chat_agent`: Task 2.
- **§5.7, tri-wellness:**
  - `run_chat_turn` wraps `run_agent_turn` with no `catch_all`: Task 6.
  - Ingest `run_turn` keeps a private sink for `extract`, `store` and `__interrupt__` and calls `stream_turn(graph, payload, turn_config(thread_id), sink, subgraphs=False, stream_mode="updates", catch_all="ingest failed", rate_limit_hint="Wait a moment and rerun; the thread resumes.")`. On failure it sets `result.error = failure.message` and prints `[{error}]\n`: Task 6.
  - `Out` stays importable from the package `repl`: Task 6, as an explicit re-export.
- **§4 layout, tri-wellness:** `agent.py` deleted (Task 5); `graph/checkpointer.py` deleted with `STATE_TYPES` in `graph/state.py` (Task 4); `report.py` imports `text_of` from the harness (Task 6). tri-analyze `agent.py` and `repl.py`: Tasks 2 and 3.
- **§6 behaviour:**
  - Error lines are pinned byte for byte by Task 1's three tests plus the existing `"[the turn failed: RuntimeError: kaboom]"` and ingest `"boom"` tests.
  - Middleware order is unchanged: analyst `[analyst_prompt, caching]` (Task 2); wellness chat and `ask_wellness` `[caching]` (Task 5).
  - Thread ids: analyze `analyze`, wellness `wellness`, ingest `ingest:<sha256>` (unchanged callers); `ask_wellness` `wellness-<uuid4>` (untouched).
  - Checkpoint format: the same `STATE_TYPES` tuple (Task 4).
  - Exception propagation: wellness chat still raises non-Anthropic errors, pinned by Task 1.
  - The `ask_wellness` tool description is not touched.
- **§7 plans 02–04 rules:**
  - No assertion is edited; the only test edits are imports, builder construction, `make_serde`/`open_checkpointer` arguments and one patch string.
  - The one deleted duplicate is named in Task 3 with its tri-core replacements.
  - The CLI readiness imports stay inside function bodies (Task 4), so the retargeted patch works.
- **§9 item 2:** every source and test file it lists is covered. The additions it lacked are recorded in "Facts verified" item 3.
- **Type consistency:**
  - `STATE_TYPES` is used identically in `cli.py` and `test_checkpointer.py`.
  - `build_chat_agent(..., system_prompt=..., checkpointer=...)` keyword use matches plan 1's signature in Tasks 2 and 5.
  - `stream_turn`'s keywords in Task 6 match plan 1 Task 6.
  - `run_agent_turn` keywords in Tasks 3 and 6 match plan 1 Task 7.
