# Coach harness

LangGraph is the runtime. The harness is the layer this repo builds on top of it: how agents are built, how an agent runs as a tool, how a sub-agent hands control back to its parent graph, how state is persisted, how a turn is streamed to a terminal or the browser, and which model each role runs on. That layer lives in `packages/tri-core/src/tri_core/harness/` and `tri_core/llm.py`. Each package keeps its own graphs, nodes, prompts, tools and domain dialogues, and imports the rest.

The diagrams below are SVG files in `docs/architecture/harness/`. They follow the reader's light or dark theme.

## One coach turn, layer by layer

![One coach turn, layer by layer](harness/layers.svg)

Read it top to bottom. Teal names are the harness module doing the work at that layer.

- **Hosts.** The terminal REPL, tri-web and the eval target all run a turn. The REPL and tri-web go through `tri_coach.repl.run_turn`, which streams on `harness.turns.stream_turn` with thread `"coach"` and a recursion limit of 60. tri-web's `TurnEmitter` subclasses the coach `TurnPrinter` to turn stream events into SSE.
- **Wiring.** `tri_web.runtime.open_runtime` (and the CLI's `_open_graph`) opens the MCP sessions, then the Postgres checkpointer and Store from `harness.persistence`, then builds the coach graph.
- **Orchestration.** The coach `StateGraph` routes between the `coach` node, the embedded planning and nutrition graphs, `review` and `apply` (see the next diagram). Every super-step checkpoints to Postgres; the serializer only accepts the pydantic types listed in `tri_coach.graph.state.STATE_TYPES`.
- **Inner loop.** The `coach` node renders a fresh prompt each turn and runs a `create_agent` loop built by `harness.agents.make_subagent`. Its middleware runs in a fixed order: `one_tool_call_at_a_time`, then `claude_fallback`, which retries an overloaded or unavailable call on the role's next Claude model, then prompt caching last.
- **Tool plane.** Handoff tools leave the loop through `harness.handoff.handoff()`. `ask_analyst` and `ask_wellness` are `harness.agent_tool` tools: each call builds a fresh read-only agent and runs it on a throwaway thread. Writes to TrainingPeaks and Garmin never happen inside a model loop; only `apply` calls `ToolsCaller`, and only after the athlete approves.

## How the coach graph routes

![How the coach graph routes](harness/routing.svg)

Dashed edges are tools that return `Command(graph=Command.PARENT)`, so a model's tool call becomes a jump to another node. Every one of them goes through `handoff()`, which re-emits the turn's messages and answers any sibling tool call the jump cut off, so the saved history never holds a tool call without a result.

- `consult_planning` and `consult_nutrition` run the embedded planning or nutrition graph on a throwaway `InMemorySaver` (serializer: `make_serde` with that package's `STATE_TYPES`) and swap the result into the original tool message.
- `propose_changes` goes to `review`, which pauses the thread with `interrupt()` until the athlete approves, edits or rejects.
- `apply` writes the approved changes. If sessions moved and nutrition targets exist in the horizon, nutrition runs once more to regenerate them.

## Packages on the harness

![Packages on tri_core.harness](harness/packages.svg)

| Module | Main names | What it does |
|---|---|---|
| `agents` | `make_subagent`, `build_chat_agent`, `one_tool_call_at_a_time` | Builds every `create_agent` loop. `make_subagent` has no checkpointer (the parent graph owns the messages); `build_chat_agent` keeps a thread per conversation. Every agent ends with `claude_fallback` and then prompt caching, which is always last. |
| `agent_tool` | `agent_tool`, `Invocation` | Exposes an agent as a one-question tool. `prepare()` runs inside the `try`, so a failure comes back as text; interrupts still propagate. |
| `handoff` | `handoff`, `turn_messages`, `undelivered` | Leaves a sub-agent for another node of the parent graph with a valid history. |
| `messages` | `text_of`, `last_ai_text` | Text out of LangChain messages. |
| `persistence` | `open_checkpointer`, `open_store`, `make_serde`, `checkpointer_ready`, `store_ready`, `SETUP_HINT`, `STORE_SETUP_HINT` | Postgres checkpointer and Store, readiness checks and the setup hints. |
| `turns` | `stream_turn`, `run_agent_turn`, `run_graph_turn`, `AgentTurnPrinter`, `GraphTurnPrinter`, `turn_config`, `format_failure`, `Out` | One stream loop for every REPL and for tri-web, and the error sentences a failed turn prints. |
| `tri_core.llm` (beside the harness) | `Role`, `ModelSpec`, `DEFAULTS`, `resolve`, `make_model`, `fallbacks_of`, `claude_fallback`, `structured`, `streaming`, `eval_metadata` | The model, effort, output ceiling and Claude fallback chain for each role; see the next section. |

Which harness modules each package's `src/` imports:

| Package | `agents` | `agent_tool` | `handoff` | `messages` | `persistence` | `turns` |
|---|---|---|---|---|---|---|
| tri-coach | ● | ● | ● | ● | ● | ● |
| tri-planning | ● | | | | ● | ● |
| tri-nutrition | ● | | | | ● | ● |
| tri-wellness | ● | | | ● | ● | ● |
| tri-analyze | ● | | | ● | | ● |
| tri-web | | | | ● | ● | |

## One model per role

![One model per role, with a Claude fallback chain](harness/models.svg)

Read it left to right. Every model in the app comes from `tri_core.llm.make_model(settings, Role.<ROLE>)`; the coach's `make_deps`, tri-web and the eval runners take a `ModelProvider` (role → model) so one fake can stand in for every role in tests.

- **Resolution.** `resolve` takes `TRI_MODEL_<ROLE>`, else `TRI_MODEL`, else the role's `DEFAULTS` entry; `TRI_EFFORT_<ROLE>` overrides effort; `TRI_MODEL_FALLBACKS` overrides the chain (empty disables it). The result is a `ModelSpec`, and the `ChatAnthropic` built from it carries `tri_role` and `tri_fallbacks` as metadata. A bad override raises `ValueError` when the CLI or server builds its models, before any turn.
- **Three carriers.** `claude_fallback` is a middleware in every `create_agent` loop, just before prompt caching. `structured(model, Schema)` wraps every `with_structured_output` call (planning design, nutrition fuel, lab extraction, the three judges). `streaming(model)` wraps the lab report stream and falls back only before the first chunk. All three retry on `RETRYABLE` only (rate limit, overload, 5xx, lost connection), never on a 4xx, and each hop logs a warning naming the role and both models.
- **The chain** is the first two of opus-5, opus-4-8, sonnet-5 that differ from the primary. A fallback keeps the primary's effort when its profile lists it, else runs at high (Opus 4.8), else none (Haiku); a structured role's fallbacks take no effort.
- **Defaults are tuned by eval, one role per commit.** As of 2026-09-24: `analyst` on opus-5 / medium and `nutrition_fuel` on sonnet-5; every other role on opus-5 at default effort. `judge` is never tuned so experiments stay comparable. Structured roles (`planning_design`, `nutrition_fuel`, `lab_extract`, `judge`) refuse an effort: it turns thinking on, and the API rejects thinking with the forced tool call `with_structured_output` uses. The runs behind each adoption are in `docs/notes/`.

## Where each concern lives

| Concern | Harness | Package | What it guarantees |
|---|---|---|---|
| Inner loop | `harness/agents.py` | `tri_coach/graph/nodes/coach.py` passes the middleware | One tool call per step; the cached prompt prefix stays stable. |
| Nested agents | `harness/agent_tool.py` | `tri_coach/tools/analyst.py`, `wellness.py` | Every question runs a fresh agent on a throwaway thread. |
| Handoffs | `harness/handoff.py` | `tri_coach/tools/handoff.py` (acks, update keys) | The saved history stays valid after a jump. |
| Durable state | `harness/persistence.py` | each package's `graph/state.py` (`STATE_TYPES`) | A paused review survives a restart. |
| Turn driver | `harness/turns.py` | `tri_coach/repl.py` (`TurnClassifier`, `TurnPrinter`), `tri_web/events.py` | Terminal and web share one stream loop and the same error lines. |
| Orchestration | | `tri_coach/graph/graph.py` | The coach routes; planning and nutrition start fresh on every consult. |
| Tool plane | | `tri_core/mcp/*`, `tri_core/db/sql_tool.py` | One session per MCP server; SQL is a single SELECT in a read-only transaction. |
| Guardrails | | `review.py` → `apply.py`, `allowlist.py` | Models propose. Only `apply` writes. |
| Model choice | `tri_core/llm.py` | `.env` overrides per role; `evals/run.py` per package | One model, effort and fallback chain per role; a default changes only after its eval passes the gate. |

## Rules to keep

- **Only `tri_core/harness/agents.py` calls `create_agent`.** Build agents with `make_subagent` or `build_chat_agent`.
- **Build models with `tri_core.llm.make_model(settings, Role.<ROLE>)`.** Each role has its own model, effort and fallback chain; `.env.example` lists the overrides. Structured-output calls go through `structured()`, the lab report stream through `streaming()`, so they fall back too. Roles that run structured output take no effort.
- **Coach sub-agents pass `middleware=[one_tool_call_at_a_time]`.** A handoff unwinds the loop as soon as it runs, so a parallel sibling call would lose its result. `test_the_coach_node_disables_parallel_tool_calls` and `test_the_eval_target_disables_parallel_tool_calls` fail if the argument is dropped.
- **A tool that jumps to another node returns `handoff(...)`,** never a hand-built `Command(graph=Command.PARENT)`.
- **`ask_analyst` and `ask_wellness` descriptions are part of the prompt cache prefix.** `test_ask_tool_names_descriptions_and_schemas_are_unchanged` pins them.
- **Each package's `STATE_TYPES` lives in its `graph/state.py`** and is passed to `open_checkpointer(url, STATE_TYPES)` and `make_serde(STATE_TYPES)`. A new pydantic type in graph state must be added there, or checkpoints holding it will not load.
- **CLIs import readiness helpers inside their function bodies,** so tests can patch `tri_core.harness.persistence.checkpointer_ready` and `store_ready`.
- **CLIs read `.env` in their Typer callback, never at import.** Tests import CLI modules; an import-time `load_dotenv()` switched LangSmith tracing on for the whole suite and every graph run became a trace (5,000 in two days). The root `conftest.py` also pins `LANGSMITH_TRACING=false`, and `test_tracing_guard.py` checks both.
- **A `repl.py` whose `Out` other modules import re-exports it as `from tri_core.harness.turns import Out as Out`.** mypy runs in strict mode, which rejects implicit re-exports.
- **Writes to TrainingPeaks and Garmin go only through `ToolsCaller`,** after `interrupt()` in `review` and then `apply`.
