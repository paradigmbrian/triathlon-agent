# tri-analyze

The analyst: `tri-analyze chat` answers questions about one athlete's training from the Postgres
store that `tri sync` fills (package `tri-core`) and, when bound, five live Garmin and
TrainingPeaks reads. Feedback on completed sessions, trends over weeks and months, readiness
today. `tri-coach` runs the same agent as its `ask_analyst` tool. Design:
`docs/superpowers/specs/2026-09-13-tri-analyze-alignment-design.md` (supersedes the 2026-09-06
spec for the agent; sync and the data layer moved to `tri-core`). Plans:
`docs/superpowers/plans/2026-09-13-tri-analyze-0*.md`.

## How it works

A LangChain agent is three things: a chat model, a list of tools, and a loop.

1. The model receives the conversation plus a description of every tool.
2. It replies either with text or with a structured request: "call this tool with these
   arguments."
3. LangChain runs the tool, appends the result to the conversation, and calls the model again.
4. The loop ends when the model replies with text and no tool call.

### The model, the tools and the loop

`llm.make_model` wraps Claude in `ChatAnthropic` (no `thinking` parameter; adaptive thinking is
the model default). `agent.build_agent(model, tools, checkpointer)` calls `create_agent` with
two middlewares and an `InMemorySaver`, and returns the graph with a run config: tag `analyst`
and metadata `analyst_prompt_version`. The graph is a state machine with a `model` node and a
`tools` node and an edge that loops while tool calls exist. The checkpointer stores state per
`thread_id`; each REPL turn sends only the new human message and LangGraph loads the prior
messages, which is what makes it a conversation. Threads are isolated from each other.

### The system prompt is rendered per model call from runtime context

`repo.load_athlete_context` reads thresholds, the last seven days of load and recovery, and the
workouts one week either side of today into an `AthleteContext`. Every run passes it as
`context=`; `agent.analyst_prompt`, a `@dynamic_prompt` middleware, renders
`prompts.analyst.render_system_prompt(context, [bound tool names])` before each model call.
The prompt is not stored in the checkpoint, so `/sync` swaps the context and the next turn sees
fresh data while the thread keeps its history. The renderer is a pure function: same data, same
bytes. Anthropic's prompt cache matches on an exact prefix, so a stable prompt plus a stable tool
list means every turn after the first reads the prefix from cache. The prompt middleware is
listed before `AnthropicPromptCachingMiddleware` so the rendered prompt is what gets the
`cache_control` marker; `unsupported_model_behavior="ignore"` lets the same graph run on the
scripted test model.

`FEEDBACK_RULES` encode what a good session review covers (planned vs actual, execution
quality, load context, athlete comments, concrete takeaways) and the rule "compute with SQL, not
in your head."

### Tools described by name

`prompts.analyst.TOOL_GUIDE` has one line per tool name: what it is for and which argument to
pass. The prompt lists every bound tool in bound order, then the guide line for each name it
knows; an unknown tool is listed without a line. When only `query_training_db` is bound the
prompt says so and tells the model to work from the database. Under `tri-coach` two extra tools
from `tri-nutrition` are bound, `read_body_composition` and `read_intake_vs_targets`, and
their guide lines appear only then.

### `query_training_db`: the tool is a function plus a docstring

`tri_core.db.sql_tool.make_query_tool` wraps a typed function with `@tool`; the docstring plus
`SCHEMA_DOC` is the model's only knowledge of the database. `validate_select` rejects anything
that is not one `SELECT`/`WITH`; the query runs on a `read_only=True` connection with a 5 s
statement timeout and a 200-row cap; SQL errors come back as `{"error": ...}` text and the model
retries with better SQL.

### Live tools: MCP tools become LangChain tools

`tools/live.py` hands this agent's allow-lists (`allowlist.py`) and the two server specs to
`tri_core.mcp.live_tools.open_live_tools`. `langchain-mcp-adapters` launches each server over
stdio, fetches its tool list and turns each JSON schema into a `BaseTool`. The servers expose
about 190 tools; the agent sees five: Garmin `get_activity`, `get_activity_splits`,
`get_training_readiness`, `get_hrv_data`, and TrainingPeaks `tp_get_workout`. Sessions stay
open for the whole chat inside an `AsyncExitStack`; a server that fails to start is logged and
skipped.

### Streaming REPL

`repl.run_turn` calls `agent.astream(..., stream_mode=["messages", "updates"], context=...)`.
`messages` events are token chunks, printed inline. `updates` events fire when a node finishes:
a finished `model` node prints its tool calls as `→ name(args)`, a finished `tools` node prints
`← name: N chars`. Anthropic errors (rate limit, status, connection) and any other exception are
printed as one bracketed line; the loop continues and the thread keeps its last checkpoint.
REPL turns carry the `chat` tag.

### Testing without a model

`tri_core.testing.ScriptedChatModel` replays a list of `AIMessage`s for both `invoke` and
`stream`; `tri_analyze.testing.RecordingScriptedModel` also keeps every message list it was sent,
so tests assert on the rendered system prompt. `testing.athlete_context()` is the prompt fixture;
`seed_workouts` and `seed_daily_metrics` fill the rolled-back test database.

## Commands

```
uv run tri-analyze chat [--no-live]                    # /tools /prompt /sync /quit
uv run tri-analyze eval [--prefix P] [--recreate-dataset]   # the LangSmith feedback eval
```

`--no-live` binds only the database tool. Exit 2 when `ANTHROPIC_API_KEY` is unset or the
database is unreachable. A failed MCP server is logged and skipped. `eval` exits 2 when
`LANGSMITH_API_KEY` or `ANTHROPIC_API_KEY` is unset, 1 when any evaluator is below 100% or
any example errored, else 0.

## Layout

```
src/tri_analyze/
  config.py           AnalyzeSettings (tri_core Settings + TRI_ANALYZE_LANGSMITH_PROJECT)
  llm.py              make_model, MAX_TOKENS
  repo.py             AthleteContext, load_athlete_context
  prompts/analyst.py  PROMPT_VERSION, FEEDBACK_RULES, TOOL_GUIDE, render_system_prompt
  agent.py            analyst_prompt (@dynamic_prompt), build_agent
  allowlist.py        the Garmin and TrainingPeaks tools the agent may call live
  tools/live.py       open_live_tools over tri_core.mcp with the allow-lists
  repl.py             text_of, TurnPrinter, run_turn, chat_loop
  cli.py              chat, eval
  testing.py          athlete_context, RecordingScriptedModel, seed_workouts, seed_daily_metrics
  evals/              cases, target (stub tools), evaluators (code checks and the judge), run
```

## One question, end to end

> "Give me feedback on my last completed ride. Pull the laps."

1. The REPL reads the context holder and sends a `HumanMessage` into the graph on thread
   `analyze` with `context=` the current `AthleteContext`.
2. `analyst_prompt` renders the system prompt from that context and the bound names.
3. Model node: emits a `query_training_db` call to find the ride and its `garmin_activity_id`.
4. Tools node: runs the SQL on a read-only connection, appends the JSON as a `ToolMessage`.
5. Model node (prompt rendered again, same bytes): emits `get_activity_splits(activity_id=...)`.
6. Tools node: the MCP session forwards the call to the Garmin server; laps come back.
7. Model node: writes the review following `FEEDBACK_RULES`, no further tool calls.
8. The loop exits; the saver stores all six messages under the thread for the next turn.

With `LANGSMITH_TRACING=true`, every hop is recorded in project `tri_analyze` with the exact
prompt, tool schema JSON and token counts (look for `cache_read_input_tokens` on the second turn).
Tags: `analyst` on every run, `chat` on REPL turns, `eval` on eval targets; under `tri-coach`
the analyst's runs appear in `tri_coach` with the `analyst` tag.

## Evaluation

`tri-analyze eval` runs the real agent (`build_agent`) over stub tools with canned results,
so no database or MCP server is involved, on the LangSmith dataset `tri_analyze_feedback`
(twelve cases in `evals/cases.py`: five session reviews, three trends, one readiness
question and three edge cases: empty SQL, an interval question without live tools, a
body-composition question with the coach's `read_body_composition` bound). The stubs carry
the real tool names and argument names, and `query_training_db` carries the real
description, so the model sees what it sees in production. Today is fixed at 2026-09-16.

Evaluators (a check that does not apply scores nothing):

| Key | Applies when | Passes when |
|---|---|---|
| `uses_sql` | the case needs data | at least one `query_training_db` call |
| `pulls_splits` | an interval question with live tools | at least one `get_activity_splits` call |
| `states_window` | a trend question | the answer names an ISO date, a month-and-day date, or a relative window such as "last 8 weeks" |
| `grounded` | always (LLM judge) | every number in the answer is in the context or the tool results, and missing data is stated |
| `feedback_quality` | session reviews (LLM judge) | the five feedback rules are covered, athlete comments and RPE are used, one or two concrete takeaways, no generic encouragement |

The judge is one `with_structured_output(FeedbackJudgement)` call per example over the
case's rendered system prompt, the question, the tool results and the answer. The
experiment is `analyst-v<PROMPT_VERSION>` with `prompt_version` and `model` as metadata,
so bump `PROMPT_VERSION` whenever the prompt text changes and compare runs. Latest run:
`analyst-v1-77fb7f3b` on 2026-09-13, 12 examples, 0 errored: `uses_sql` 100%, `pulls_splits`
100%, `states_window` 80%, `feedback_quality` 100%, `grounded` 17%.

## Design decisions

| Decision | Why |
|---|---|
| One flexible read-only SQL tool instead of many narrow query tools | The model composes its own questions. Safety comes from the connection mode, not from limiting what it can ask. |
| System prompt rendered from runtime context, not fetched via tools | Cheaper and faster; the model always has thresholds and current load in view, and `/sync` refreshes it without rebuilding the agent. |
| Tools described by name in `TOOL_GUIDE` | The same prompt serves the standalone chat and the coach, which binds two extra tools; each session's prompt describes exactly what is bound. |
| Raw MCP tools with an allow-list, not hand-written wrappers | Less code, and it is the real LangChain-plus-MCP integration rather than a facade. |
| Tool binding order is fixed (SQL, Garmin, TrainingPeaks, extras) | The tool list is part of the cached prompt prefix; reordering invalidates the cache. |
| In-memory checkpointer | The analyst has no interrupts and no multi-step workflow state, so nothing needs to survive the process. A persistent thread would grow token cost and carry answers computed from older synced data; `tri-coach` uses a throwaway thread per question regardless. |
| Async REPL | MCP sessions are async and must stay open across turns. |

## Knobs

- **The model writes bad SQL:** edit `SCHEMA_DOC` in `tri_core/db/sql_tool.py`.
- **Feedback is vague or misses something:** edit `FEEDBACK_RULES` in `prompts/analyst.py` and
  bump `PROMPT_VERSION`.
- **The model ignores a tool or picks the wrong one:** edit its `TOOL_GUIDE` line, or
  `allowlist.py` for which tools are bound.
- **Model or cost:** `TRI_MODEL` in `.env`; `MAX_TOKENS` in `llm.py`.
- **How much context the prompt carries:** the date windows in `repo.load_athlete_context`.
- **Where traces go:** `TRI_ANALYZE_LANGSMITH_PROJECT` (default `tri_analyze`).
- **The eval disagrees with you:** the cases are in `evals/cases.py`; `--recreate-dataset`
  pushes edits to LangSmith.
