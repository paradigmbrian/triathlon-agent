# Agent harness — shared agent builders, turn driver and persistence (module `tri_core.harness`)

**Date:** 2026-09-15
**Status:** Draft
**Purpose:** Five packages each carry their own copy of the harness around LangGraph: agent builders, the agent-as-tool runner, handoff plumbing, checkpointer and store setup, and the REPL turn driver. This spec moves that code into one module in tri-core. It is a pure refactor: no prompt, graph, tool, terminal output or error text changes. The model-routing spec (2026-09-15) lands afterwards and adds its fallback middleware in one place instead of five.

Companion specs: `model-routing` (2026-09-15, amended to follow this one); `tri-coach` (2026-09-11) owns the handoff tools, `ask_analyst`, `ask_wellness` and the turn classifier that tri-web streams; `tri-planning` (2026-09-07), `tri-nutrition` (2026-09-10), `tri-wellness` (2026-09-10) and `tri-analyze` (2026-09-06, alignment 2026-09-13) own the REPLs and checkpointers consolidated here; `tri-web` (2026-09-14) imports `tri_coach.repl.run_turn`, `TurnPrinter` and the readiness checks.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Sequencing | Harness first, model routing second (chosen 2026-09-15). | `claude_fallback` then lands in the harness's two builders rather than five package builders; the routing spec is amended to match. |
| Location | `tri_core.harness`, a subpackage of tri-core (chosen 2026-09-15). | Sits next to `tri_core.mcp` and routing's `tri_core.llm`; routing already adds the langchain dependencies to tri-core. |
| Turn driver scope | Shared stream loop, error mapping, an agent printer and a graph printer (chosen 2026-09-15). The coach's classifier and wellness ingest keep their domain handling and run on the shared loop. | The analyze/wellness printers and the planning/nutrition printers are byte-identical pairs; the coach's typed events are coach-specific and tri-web depends on them. |
| Migration | Package by package with no compatibility shims (approach A, chosen 2026-09-15). | The suite is green after every merge, and there is never a second copy of a moved function to wonder about. |
| Behaviour | Nothing observable changes. Existing test assertions and expected values are not edited. | If an assertion has to change, the change is not a refactor: the plan stops and the athlete decides. |
| Model construction | Out of scope. The five `make_model` copies stay until routing plan 01 deletes them. | Routing already designs `tri_core.llm`; designing it twice would conflict. |

## 2. Feasibility, verified 2026-09-15 on `main` @ 3a5a82c

- **Agent builders.**
  - `make_subagent(model, tools, system_prompt)` exists in `tri_coach`, `tri_planning` and `tri_nutrition` `graph/llm.py`. The planning and nutrition files are byte-identical: `create_agent(..., middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")], checkpointer=False)`. The coach's copy adds `one_tool_call_at_a_time` (a `@wrap_model_call` that sets `parallel_tool_calls=False`) before caching.
  - `tri_analyze.agent.build_agent(model, tools, checkpointer=None)` uses middleware `[analyst_prompt (dynamic_prompt), caching]`, `context_schema=AthleteContext`, `checkpointer or InMemorySaver()`, then `.with_config({"tags": ["analyst"], "metadata": {"analyst_prompt_version": PROMPT_VERSION}})`.
  - `tri_wellness.agent.build_agent(model, tools, system_prompt, checkpointer=None)` uses middleware `[caching]` and `checkpointer or InMemorySaver()`.
- **Agent as tool.** `tri_coach/tools/analyst.py` and `tri_coach/tools/wellness.py` share one skeleton. Inside `try`, each loads context through `connect()`, builds the agent on an `InMemorySaver`, and calls `ainvoke({"messages": [HumanMessage(question)]}, {"configurable": {"thread_id": f"<prefix>-{uuid4()}"}, "recursion_limit": 40})`. The analyst also passes `context=ctx`. `GraphBubbleUp` is re-raised; any other `Exception` returns a failure sentence; otherwise the tool returns `last_ai_text(out["messages"])` or an "empty" sentence. The description is `inspect.cleandoc` of the inner function's docstring.
- **Handoff.** `tri_coach/tools/handoff.py` holds `turn_messages`, `undelivered` and `NOT_DELIVERED`. Both `_consult` and `propose_changes` return `Command(goto=..., graph=Command.PARENT, update={..., "messages": [*turn, *undelivered(turn, tool_call_id), ack]})`.
- **Persistence.**
  - `graph/checkpointer.py` exists in coach, planning, nutrition and wellness. The four copies are identical apart from `STATE_TYPES` (coach 9 types, planning 3, nutrition 2, wellness 4) and docstrings: `make_serde()`, `open_checkpointer(url)`, `checkpointer_ready(url)` and the same `SETUP_HINT` text.
  - `tri_nutrition/store.py` holds `open_store(url)`, `store_ready(url)` and `STORE_SETUP_HINT`, whose text matches `SETUP_HINT`. `scripts/setup_checkpointer.py` already creates both tables and is untouched.
- **Text.** `text_of` exists in five `repl.py` files (as `_text_of` in planning and nutrition); the coach's generator form returns the same strings. `last_ai_text` lives in `tri_coach/text.py`.
- **Turn drivers.**
  - Agent printer: `TurnPrinter.on_event(mode, data)` is identical in `tri_analyze/repl.py` and `tri_wellness/repl.py`.
    - `tri_analyze.repl.run_turn(agent, text, thread_id, out, *, context, tags)` catches every `Exception`.
    - `tri_wellness.repl.run_chat_turn(agent, text, thread_id, out)` catches Anthropic errors only.
    - Both return the final text.
  - Graph printer: `TurnPrinter.on_event(namespace, mode, data)` in `tri_planning/repl.py` and `tri_nutrition/repl.py` is identical apart from planning's `error` attribute. The printer skips root updates from `STREAMED_NODES`, which is `{intake, adjust}` in planning and `{intake, checkin}` in nutrition. `run_turn(graph, payload, thread_id, out) -> TurnPrinter` catches Anthropic errors only; planning stores the message in `printer.error`, nutrition does not.
  - Coach: `TurnClassifier` feeds `TurnPrinter.print_event`. `run_turn(graph, payload, thread_id, out, *, tags=None, printer=None) -> TurnPrinter` uses `recursion_limit` 60, catches every `Exception` and stores `printer.error`. tri-web subclasses the printer as `TurnEmitter` and imports `run_turn`. `tri_coach.checkin` and `tri_planning.checkin` import their package's `run_turn`.
  - Wellness ingest: `run_turn(graph, payload, thread_id, out) -> TurnResult` streams `stream_mode="updates"` without subgraphs, prints `extract`/`store` progress, and uses its own error sentences.
  - Error text today:

    | Driver | Rate limited | Other API status | Connection | Anything else |
    |---|---|---|---|---|
    | analyze, coach, planning, nutrition, wellness chat | `\n[rate limited: {exc}. Wait a moment and try again.]\n` | `\n[Anthropic API error {status_code}: {message}]\n` | `\n[connection error talking to Anthropic: {exc}]\n` | analyze and coach only: `\n[the turn failed: {Type}: {exc}]\n` |
    | wellness ingest | `rate limited: {exc}. Wait a moment and rerun; the thread resumes.` | same sentence, no brackets | same sentence, no brackets | `ingest failed: {Type}: {exc}` |

    Ingest prints its sentence as `[{error}]\n`. `anthropic.RateLimitError` subclasses `APIStatusError`, so every driver checks it first.
- **Dependencies.** tri-core has `langchain-core`, `langchain-mcp-adapters` and `psycopg`. The packages pin `langchain==1.4.0`, `langchain-anthropic==1.7.1` and `langgraph-checkpoint-postgres>=3.1,<4`; `anthropic` arrives transitively through `langchain-anthropic`. `mypy --strict` already covers `packages/tri-core/src`.
- **Importers of moved code** (source and tests), grouped by the plan that changes them, are listed in §9.

## 3. Overview

```
 hosts                     tri_coach.repl.run_turn ─┐   tri_planning / tri_nutrition .repl.run_turn ─┐
 (REPLs, checkin, tri-web)  tri_analyze.repl.run_turn ┤   tri_wellness.repl.run_chat_turn / run_turn ─┤
                                                      ▼                                               ▼
 tri_core.harness.turns     stream_turn(runnable, payload, config, sink, ...) ─► TurnFailure | None
                            sinks: AgentTurnPrinter · GraphTurnPrinter · coach TurnPrinter · ingest sink

 nodes and tools            make_subagent ─┐  build_chat_agent ─┐  agent_tool(prepare, ...) ─┐  handoff(goto, ...)
                                           ▼                    ▼                           ▼
 tri_core.harness.agents    create_agent + [*middleware, AnthropicPromptCachingMiddleware]
                            (routing later appends claude_fallback here, once)

 CLIs and tri-web           open_checkpointer(url, STATE_TYPES) · open_store(url) · *_ready(url) · SETUP_HINT
                            ─► tri_core.harness.persistence
```

## 4. Layout

```
packages/tri-core/
  pyproject.toml     adds langchain==1.4.0, langchain-anthropic==1.7.1,
                     langgraph-checkpoint-postgres>=3.1,<4, anthropic>=1.4,<2
  src/tri_core/harness/
    __init__.py      empty
    messages.py      text_of, last_ai_text
    agents.py        one_tool_call_at_a_time, make_subagent, build_chat_agent
    agent_tool.py    Invocation, agent_tool
    handoff.py       NOT_DELIVERED, turn_messages, undelivered, handoff
    persistence.py   SETUP_HINT, make_serde, open_checkpointer, checkpointer_ready, open_store, store_ready
    turns.py         Out, TurnSink, TurnFailure, api_error_message, turn_config, stream_turn,
                     AgentTurnPrinter, GraphTurnPrinter, format_failure, run_agent_turn, run_graph_turn
  tests/test_harness_{messages,agents,agent_tool,handoff,persistence,turns}.py

packages/tri-analyze/src/tri_analyze/
  agent.py           build_agent keeps its signature; body calls build_chat_agent
  repl.py            text_of and TurnPrinter removed; run_turn wraps run_agent_turn
packages/tri-wellness/src/tri_wellness/
  agent.py           deleted; callers use build_chat_agent
  graph/checkpointer.py  deleted; STATE_TYPES moves to graph/state.py
  repl.py            text_of and TurnPrinter removed; run_chat_turn wraps run_agent_turn;
                     ingest run_turn runs on stream_turn
  report.py          imports text_of from the harness
packages/tri-planning/src/tri_planning/
  graph/checkpointer.py  deleted; STATE_TYPES moves to graph/state.py
  graph/llm.py       make_subagent removed; make_model stays
  repl.py            _text_of and TurnPrinter removed; run_turn wraps run_graph_turn
packages/tri-nutrition/src/tri_nutrition/
  graph/checkpointer.py  deleted; STATE_TYPES moves to graph/state.py
  graph/llm.py       make_subagent removed; make_model stays
  repl.py            _text_of and TurnPrinter removed; run_turn wraps run_graph_turn
  store.py           open_store, store_ready and STORE_SETUP_HINT removed; namespace, keys and
                     typed access stay
packages/tri-coach/src/tri_coach/
  graph/checkpointer.py  deleted; STATE_TYPES moves to graph/state.py
  graph/llm.py       make_subagent and one_tool_call_at_a_time removed; make_model stays
  text.py            deleted
  tools/handoff.py   turn_messages, undelivered and NOT_DELIVERED removed; _consult and propose_changes
                     call handoff()
  tools/analyst.py   make_analyst_tool returns agent_tool(...)
  tools/wellness.py  make_wellness_tool returns agent_tool(...); wellness_tools stays
  repl.py            text_of removed; TurnClassifier, TurnPrinter and run_turn stay, run_turn on
                     stream_turn
packages/tri-web/src/tri_web/
  thread.py, routes/system.py, runtime.py   import from the harness (§9 plan 03, plan 04)
```

## 5. Interfaces

### 5.1 `messages.py`

```python
def text_of(msg: BaseMessage) -> str: ...            # str content as-is; else the joined "text" blocks and bare strings
def last_ai_text(messages: Sequence[Any]) -> str: ...  # text of the last AIMessage with no tool calls, else ""
```

Both are moved verbatim; `text_of` takes the analyze implementation.

### 5.2 `agents.py`

```python
Middleware = AgentMiddleware[Any, Any, Any]

one_tool_call_at_a_time: Middleware   # moved verbatim from tri_coach.graph.llm

def make_subagent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    *,
    middleware: Sequence[Middleware] = (),
) -> Any:
    """create_agent(model, list(tools), system_prompt=system_prompt,
    middleware=[*middleware, AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
    checkpointer=False)"""

def build_chat_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    *,
    system_prompt: str | None = None,
    middleware: Sequence[Middleware] = (),
    context_schema: type[Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """create_agent(model, list(tools), system_prompt=system_prompt,
    middleware=[*middleware, caching], context_schema=context_schema,
    checkpointer=checkpointer or InMemorySaver())"""
```

Caching is always last, so the rendered prompt that a `dynamic_prompt` middleware produces is what gets marked for the cache. Callers:

- The coach node calls `make_subagent(deps.model, tools, prompt, middleware=[one_tool_call_at_a_time])`.
- Planning and nutrition nodes call `make_subagent(model, tools, prompt)`.
- `tri_analyze.agent.build_agent` returns `build_chat_agent(model, tools, middleware=[analyst_prompt], context_schema=AthleteContext, checkpointer=checkpointer).with_config(...)`, keeping the same tags and metadata.
- Wellness chat and `ask_wellness` call `build_chat_agent(model, tools, system_prompt=prompt, checkpointer=...)`.

### 5.3 `agent_tool.py`

```python
@dataclass(frozen=True)
class Invocation:
    agent: Any
    context: Any = None     # passed to ainvoke as context= only when not None

def agent_tool(
    *,
    name: str,
    description: str,
    prepare: Callable[[], Invocation],
    thread_prefix: str,
    recursion_limit: int,
    failure: str,           # contains "{error}", filled with "<ExcType>: <exc>"
    empty: str,
) -> BaseTool: ...
```

The tool takes one argument, `question: str`. Each call:

1. Runs `prepare()` inside the `try`, so a context-load failure also returns `failure`.
2. Calls `ainvoke` on thread `f"{thread_prefix}-{uuid4()}"` with `recursion_limit`.
3. Re-raises `GraphBubbleUp`; any other `Exception` returns `failure.format(error=...)`.
4. Returns `last_ai_text(out["messages"]) or empty`.

The tool is built with `StructuredTool.from_function(coroutine=..., name=name, description=description)`.

Callers:
- **`ask_analyst`:** `thread_prefix="analyst"`, `recursion_limit=ANALYST_RECURSION_LIMIT`, and today's failure and empty sentences. Its description constant is today's docstring after `inspect.cleandoc`, character for character.
- **`ask_wellness`:** the same pattern with `"wellness"` and `WELLNESS_RECURSION_LIMIT`.

### 5.4 `handoff.py`

```python
NOT_DELIVERED: str                                                     # moved verbatim
def turn_messages(messages: Sequence[AnyMessage]) -> list[AnyMessage]: ...          # moved verbatim
def undelivered(turn: Sequence[AnyMessage], handoff_call_id: str) -> list[ToolMessage]: ...  # moved verbatim

def handoff(
    goto: str,
    *,
    tool_call_id: str,
    messages: Sequence[AnyMessage],
    ack: ToolMessage,
    update: Mapping[str, Any] | None = None,
) -> Command[str]:
    """turn = turn_messages(messages); Command(goto=goto, graph=Command.PARENT,
    update={**(update or {}), "messages": [*turn, *undelivered(turn, tool_call_id), ack]})"""
```

`_consult` passes `update={"brief": brief}`; `propose_changes` passes `update={"proposal_request": ...}`. Both keep building their own `ack`, including its id and content.

### 5.5 `persistence.py`

```python
SETUP_HINT: str   # today's text

def make_serde(state_types: Sequence[type]) -> JsonPlusSerializer: ...  # allowed_msgpack_modules=tuple(state_types)

@asynccontextmanager
async def open_checkpointer(url: str, state_types: Sequence[type]) -> AsyncIterator[AsyncPostgresSaver]: ...

def checkpointer_ready(url: str) -> bool: ...   # to_regclass('public.checkpoints'); False on OperationalError

@asynccontextmanager
async def open_store(url: str) -> AsyncIterator[AsyncPostgresStore]: ...

def store_ready(url: str) -> bool: ...          # to_regclass('public.store'); False on OperationalError
```

Each package's `STATE_TYPES` tuple moves unchanged into its `graph/state.py`. Callers pass it to `open_checkpointer` and `make_serde`. For example, the coach graph builds `InMemorySaver(serde=make_serde(tri_planning.graph.state.STATE_TYPES))`. `STORE_SETUP_HINT` users switch to `SETUP_HINT`, which has the same text.

### 5.6 `turns.py`

```python
Out = Callable[[str], None]

class TurnSink(Protocol):
    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None: ...

@dataclass(frozen=True)
class TurnFailure:
    exc: Exception
    message: str        # no brackets or newlines, e.g. "connection error talking to Anthropic: ..."

def api_error_message(exc: BaseException, *, rate_limit_hint: str = "Wait a moment and try again.") -> str | None:
    """RateLimitError → f"rate limited: {exc}. {rate_limit_hint}";
    APIStatusError → f"Anthropic API error {exc.status_code}: {exc.message}";
    APIConnectionError → f"connection error talking to Anthropic: {exc}"; else None."""

def turn_config(thread_id: str, *, tags: Sequence[str] | None = None,
                recursion_limit: int | None = None) -> dict[str, Any]: ...
    # {"configurable": {"thread_id": ...}}, plus "recursion_limit" and "tags" (as a list) only when given

async def stream_turn(
    runnable: Any,
    payload: Any,
    config: dict[str, Any],
    sink: TurnSink,
    *,
    subgraphs: bool,
    stream_mode: str | list[str] = ["messages", "updates"],
    context: Any = None,                    # passed as context= only when not None
    catch_all: str | None = None,           # None: non-Anthropic errors propagate
    rate_limit_hint: str = "Wait a moment and try again.",
) -> TurnFailure | None: ...

def format_failure(failure: TurnFailure) -> str: ...   # f"\n[{failure.message}]\n"

class AgentTurnPrinter:          # TurnSink; ignores namespace. Moved from tri_analyze.repl.TurnPrinter
    out: Out
    final_text: str

class GraphTurnPrinter:          # TurnSink. Moved from tri_planning.repl.TurnPrinter
    def __init__(self, out: Out, streamed_nodes: frozenset[str] = frozenset()) -> None: ...
    final_text: str
    interrupt: dict[str, Any] | None
    error: str | None

async def run_agent_turn(agent: Any, text: str, thread_id: str, out: Out, *, context: Any = None,
                         tags: Sequence[str] | None = None, catch_all: str | None = None) -> str: ...

async def run_graph_turn(graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out,
                         *, streamed_nodes: frozenset[str] = frozenset()) -> GraphTurnPrinter: ...
```

`stream_turn` normalises every stream item to `sink.on_event(namespace, mode, data)`:

| Stream shape | Item | Call |
|---|---|---|
| `subgraphs=True` | `(namespace, mode, data)` | `on_event(tuple(namespace), mode, data)` |
| `subgraphs=False`, list mode | `(mode, data)` | `on_event((), mode, data)` |
| `subgraphs=False`, single mode | `data` | `on_event((), stream_mode, data)` |

Error handling:
- An error that `api_error_message` recognises returns `TurnFailure(exc, message)`.
- Any other `Exception` returns `TurnFailure(exc, f"{catch_all}: {type(exc).__name__}: {exc}")` when `catch_all` is set, and propagates otherwise.
- `stream_turn` never prints. Formatting belongs to the driver.

The drivers:
- **`run_agent_turn`** streams `{"messages": [HumanMessage(text)]}` into an `AgentTurnPrinter`. On failure it prints `format_failure(...)`. It returns `printer.final_text`.
- **`run_graph_turn`** streams with `subgraphs=True` into a `GraphTurnPrinter`. On failure it stores and prints `format_failure(...)` in `printer.error`. It returns the printer.

### 5.7 What the packages keep

- **`tri_analyze.repl.run_turn(agent, text, thread_id, out, *, context, tags=None)`** calls `run_agent_turn(..., context=context, tags=tags, catch_all="the turn failed")`.
- **`tri_wellness.repl.run_chat_turn(agent, text, thread_id, out)`** calls `run_agent_turn(...)` with `catch_all=None`.
- **`tri_wellness.repl.run_turn(graph, payload, thread_id, out) -> TurnResult`**:
  1. Keeps a private sink that holds today's `extract`/`store` printing and records `__interrupt__`.
  2. Calls `stream_turn(graph, payload, turn_config(thread_id), sink, subgraphs=False, stream_mode="updates", catch_all="ingest failed", rate_limit_hint="Wait a moment and rerun; the thread resumes.")`.
  3. On failure, sets `result.error = failure.message` and prints `[{error}]\n`.
- **`tri_planning.repl.run_turn` and `tri_nutrition.repl.run_turn`** keep their signatures and return `await run_graph_turn(graph, payload, thread_id, out, streamed_nodes=STREAMED_NODES)`.
- **`tri_coach.repl.run_turn(graph, payload, thread_id, out, *, tags=None, printer=None) -> TurnPrinter`** keeps its signature:
  1. Builds `printer = printer or TurnPrinter(out)`.
  2. Calls `stream_turn(graph, payload, turn_config(thread_id, tags=tags, recursion_limit=60), printer, subgraphs=True, catch_all="the turn failed")`.
  3. On failure, sets `printer.error = format_failure(failure)` and prints it.
- **`TurnClassifier`, the coach `TurnPrinter`, tri-web's `TurnEmitter`**, and every domain dialogue (`render_*`, `parse_decision`, YAML editors, `chat_loop`, `checkin_run`) stay where they are.
- **`Out`**: each package's alias is replaced by an import of `tri_core.harness.turns.Out`. Names that other modules import, such as `from tri_coach.repl import Out`, stay importable from the package `repl`.

## 6. Behaviour

The refactor keeps all of the following:

1. Terminal output for every REPL, check-in and ingest run, including every error sentence in §2, byte for byte.
2. The SSE events tri-web emits and the thread views it renders.
3. Tool names, argument schemas and descriptions bound to every model. This includes `ask_analyst` and `ask_wellness`, whose descriptions must match exactly, because the prompt cache prefix depends on them.
4. Middleware order: the coach `[one_tool_call_at_a_time, caching]`, the analyst `[analyst_prompt, caching]`, everyone else `[caching]`.
5. Checkpoint format: serde allow-lists are the same tuples, so checkpoints from threads paused before the refactor resume after it.
6. The Postgres objects each readiness check looks for, and the `SETUP_HINT` text.
7. Exception propagation: non-Anthropic errors still propagate from planning, nutrition and wellness chat turns; `GraphBubbleUp` still leaves `ask_analyst` and `ask_wellness`.
8. Thread ids, recursion limits, tags and run metadata.

**The one internal difference:** nutrition's graph printer now records `error` like planning's. Nothing reads that attribute in nutrition, and it prints nothing extra.

## 7. Testing

**Plan 01: new tests in tri-core, no network.**
- `test_harness_messages.py`: `text_of` on str content, mixed blocks and bare strings; `last_ai_text` skips tool-calling messages and returns `""` when none match. Ported from `tri_analyze` and `tri_coach` tests.
- `test_harness_agents.py`:
  - Using `ScriptedChatModel` and `tool_call` from `tri_core.testing.fakes`: `make_subagent` runs a tool round trip and writes no checkpoint, and `build_chat_agent` keeps history across two turns on one thread.
  - Middleware order is `[*middleware, caching]`.
  - `one_tool_call_at_a_time` sets `parallel_tool_calls=False` (ported from `tri_coach/tests/test_tools.py`).
- `test_harness_agent_tool.py`: answer returned; context passed only when set; a `prepare` failure and an `ainvoke` failure return the formatted `failure`; `GraphBubbleUp` propagates; an empty answer returns `empty`; the thread id has the prefix.
- `test_harness_handoff.py`:
  - `turn_messages` and `undelivered`, ported from `tri_coach/tests/test_tools.py`.
  - `handoff` returns `Command.PARENT` with the update merged and messages ordered as `[*turn, *undelivered, ack]`.
- `test_harness_persistence.py`:
  - `make_serde` round-trips a registered pydantic model.
  - `@pytest.mark.db`: `open_checkpointer` and `open_store` open against `TEST_DATABASE_URL`, and both readiness checks are true there.
  - An unreachable URL makes both readiness checks false.
- `test_harness_turns.py`:
  - `api_error_message` for each error class, and `None` for others.
  - `turn_config` key presence.
  - `stream_turn`: normalises all three stream shapes; handles `catch_all` set and unset; passes `context` only when set.
  - `AgentTurnPrinter` and `GraphTurnPrinter` output, `final_text`, `interrupt` capture and `streamed_nodes` skipping. These printer tests are ported from `tri_analyze/tests/test_repl.py` and `tri_planning/tests/test_repl.py`.
  - `run_agent_turn` and `run_graph_turn` failure text.

**Plans 02–04: rules for existing tests.**
- Imports change to the harness path.
- A test that builds a moved printer constructs the harness class with the package's arguments, e.g. `GraphTurnPrinter(out, STREAMED_NODES)`.
- Assertions and expected values are not edited.
- The CLIs keep importing the readiness helpers inside their function bodies, as they do today. That way a test's string-path `monkeypatch.setattr` still takes effect when retargeted to `"tri_core.harness.persistence.checkpointer_ready"` or `".store_ready"`. Today's targets are `tri_coach.graph.checkpointer`, `tri_wellness.graph.checkpointer` and `tri_nutrition.store`.
- A package test that only duplicates a test now in `tri-core` (a printer or `text_of` unit test with no package-specific input) is deleted in the plan that migrates that package.
- `test_checkpointer.py` in planning, nutrition and wellness keeps its package-specific cases (its `STATE_TYPES` round-trip), rewritten against `make_serde(STATE_TYPES)` and `open_checkpointer(url, STATE_TYPES)`.

**Definition of done for every plan**, in order:
1. `uv run pytest`
2. `uv run ruff check`
3. `uv run mypy`
4. Plan 04 only: `npm run build` in `web/`

**After plan 04**, no definition of `text_of`, `last_ai_text`, `make_subagent`, `make_serde`, `open_checkpointer`, `checkpointer_ready`, `open_store` or `store_ready` exists outside `packages/tri-core/src/tri_core/harness/`. Verify with `rg -n "def (text_of|_text_of|last_ai_text|make_subagent|make_serde|open_checkpointer|checkpointer_ready|open_store|store_ready)\b" packages --glob '!**/tri_core/harness/**'`, which must print nothing. The only printer classes outside the harness are the coach `TurnPrinter`, tri-web's `TurnEmitter` and wellness ingest's private sink.

**Manual smoke after plan 04** (athlete-run; it costs API money): one `uv run tri-coach chat` turn that consults the analyst, and one tri-web coach turn.

## 8. Out of scope

- `make_model`, per-role models, effort and fallback: the model-routing spec.
- One event model for every package, and changes to `TurnClassifier` or tri-web's event shapes.
- `ReportWriter` streaming in `tri_wellness/report.py` beyond its `text_of` import.
- `tri_core.mcp`, `tri_coach.servers` and the allow-lists, which are already shared or coach-specific.
- New CLI commands, renamed commands or changed flags.
- Rewriting earlier specs; they are left as written.

## 9. Rollout

Each plan runs on its own `feat/tri-harness-0N` branch in a sibling worktree.

1. **Plan 01, harness core.**
   - Adds `tri_core/harness/*`, the tri-core dependency pins, `uv.lock`, and the §7 tests.
   - No existing module changes.
2. **Plan 02, tri-analyze and tri-wellness.**
   - Source: `tri_analyze/{agent,repl}.py` and `evals/target.py` (the `text_of` import); `tri_wellness/{repl,report,cli}.py` and `graph/state.py`; `tri_wellness/agent.py` and `graph/checkpointer.py` are deleted.
   - Importers outside the two packages: `tri_coach/tools/wellness.py` (`build_chat_agent`).
   - Tests: `tri-analyze/tests/{test_agent,test_repl}.py`; `tri-wellness/tests/{test_chat,test_checkpointer,test_repl}.py`; `tri-wellness/tests/test_cli.py` (its `checkpointer_ready` patch path).
3. **Plan 03, tri-planning and tri-nutrition.**
   - Source: `graph/llm.py` (drops `make_subagent`), `graph/nodes/{intake,adjust}.py` and `graph/nodes/{intake,checkin}.py`, `repl.py`, `cli.py` and `graph/state.py` in both; `tri_nutrition/store.py`. Both `graph/checkpointer.py` files are deleted.
   - Importers outside the two packages: `tri_coach/graph/graph.py` (the subgraph serdes); `tri_coach/cli.py` (`S.open_store`, `S.store_ready`, `S.STORE_SETUP_HINT`); `tri_web/runtime.py` (`S.open_store`); `tri_web/routes/system.py` (`store_ready`).
   - Tests: `tri-planning/tests/{test_checkpointer,test_repl}.py`; `tri-nutrition/tests/{test_checkpointer,test_repl,test_store}.py`; `tri-web/tests/test_runtime.py`; `tri-coach/tests/test_cli.py` (its `store_ready` patch path).
4. **Plan 04, tri-coach and tri-web.**
   - Source: `tri_coach/graph/{llm,state,graph}.py`, `graph/nodes/{coach,planning,nutrition}.py`, `tools/{handoff,analyst,wellness}.py`, `repl.py`, `cli.py`, `evals/target.py`; `tri_coach/graph/checkpointer.py` and `text.py` are deleted.
   - tri-web: `tri_web/thread.py` (`text_of`); `routes/system.py` and `runtime.py` (`checkpointer_ready`, `open_checkpointer` with the coach's `STATE_TYPES`).
   - Tests: `tri-coach/tests/{test_cli,test_graph,test_graph_apply,test_live,test_models,test_repl,test_resume,test_tools}.py`, where `test_cli` is its `checkpointer_ready` patch path; `tri-web/tests/{conftest,test_runtime}.py`. `tri-web/tests/test_routes_system.py` patches `tri_web.routes.system.<name>`, which stays valid.
   - Finishes with the §7 grep and the web build.

Every plan also greps package READMEs and `docs/` for the module paths it deletes, and points them at `tri_core.harness`. The model-routing spec's plan 01 starts after plan 04 is merged.
